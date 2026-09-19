import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import config
from ..core.db import get_db
from ..core.security import APIError, hash_password, require_admin
from ..models import Group, GroupMember, SiteSetting, TeacherStudent, User
from ..schemas import (AccountCreate, BatchActiveRequest, BatchResetPasswordRequest,
                       BindStudentsRequest, GroupCreate, GroupMembershipOut,
                       GroupMembersRequest, GroupOut, GroupRef, GroupUpdate,
                       ImportFailure, ImportResult, IsActivePatch,
                       ResetPasswordRequest, SettingsOut, SettingsUpdate,
                       StudentOut, TeacherOut, UserOut)
from ..services import export as export_svc
from ..services import groups as groups_svc

router = APIRouter()

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_BG_BYTES = 5 * 1024 * 1024
ALLOWED_BG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
BG_IMAGE_URL = "/api/settings/bg_image"

# ---------- 学生导入（xlsx / txt / csv）----------
ALLOWED_IMPORT_EXTS = {".xlsx", ".txt", ".csv"}
MAX_IMPORT_BYTES = 5 * 1024 * 1024
# 组别列内的多组分隔符
GROUP_SEP_RE = re.compile(r"[、，,；;/]")
TXT_ALT_SEP_RE = re.compile(r"[,，]")
HEADER_FIRST_CELLS = {"学号", "学生ID"}
# 统一中间表示：(行号, 学号, 姓名, [组别])
ImportRow = tuple[int, str, str, list[str]]


class StudentIdsOut(BaseModel):
    student_ids: list[int]


class BgImageOut(BaseModel):
    url: str


class SuccessOut(BaseModel):
    success: bool


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_role_user(db: Session, user_id: int, role: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.role != role:
        label = "教师" if role == "teacher" else "学生"
        raise APIError(404, "NOT_FOUND", f"{label}不存在")
    return user


def create_account(db: Session, body: AccountCreate, role: str) -> User:
    exists = db.query(User).filter(User.username == body.username).first()
    if exists is not None:
        raise APIError(409, "DUPLICATE_USERNAME", "用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=role,
        display_name=body.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def teacher_to_out(t: User, student_count: int = 0) -> TeacherOut:
    return TeacherOut(
        id=t.id,
        username=t.username,
        display_name=t.display_name,
        is_active=t.is_active,
        created_at=t.created_at,
        student_count=student_count,
    )


def get_or_create_settings(db: Session) -> SiteSetting:
    s = db.get(SiteSetting, 1)
    if s is None:
        s = SiteSetting(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


BG_FIELD_BY_MODE = {"light": "bg_image_path", "dark": "bg_image_path_dark"}


def bg_field(mode: str) -> str:
    if mode not in BG_FIELD_BY_MODE:
        raise APIError(422, "INVALID_BG_MODE", "背景图模式仅支持 light / dark")
    return BG_FIELD_BY_MODE[mode]


def bg_image_url(path: str, mode: str = "light") -> str:
    # 文件名即版本号：URL 随每次上传变化，浏览器/中间层缓存不会把旧图当成新图
    url = f"{BG_IMAGE_URL}?v={Path(path).stem}"
    return url if mode == "light" else f"{url}&mode=dark"


def settings_to_out(s: SiteSetting) -> SettingsOut:
    return SettingsOut(
        brand_color=s.brand_color,
        brand_color_source=s.brand_color_source,
        bg_image_url=bg_image_url(s.bg_image_path) if s.bg_image_path else None,
        bg_image_url_dark=bg_image_url(s.bg_image_path_dark, "dark") if s.bg_image_path_dark else None,
        bg_dual=bool(s.bg_dual),
        bg_opacity=s.bg_opacity,
    )


@router.get("/admin/teachers", response_model=list[TeacherOut])
def list_teachers(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    teachers = db.query(User).filter(User.role == "teacher").order_by(User.id).all()
    counts = dict(
        db.query(TeacherStudent.teacher_id, func.count(TeacherStudent.student_id))
        .group_by(TeacherStudent.teacher_id)
        .all()
    )
    return [teacher_to_out(t, counts.get(t.id, 0)) for t in teachers]


@router.post("/admin/teachers", response_model=TeacherOut)
def create_teacher(body: AccountCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = create_account(db, body, "teacher")
    return teacher_to_out(user)


@router.patch("/admin/teachers/{teacher_id}", response_model=TeacherOut)
def patch_teacher(teacher_id: int, body: IsActivePatch, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = get_role_user(db, teacher_id, "teacher")
    user.is_active = 1 if body.is_active else 0
    db.commit()
    db.refresh(user)
    count = (
        db.query(func.count(TeacherStudent.student_id))
        .filter(TeacherStudent.teacher_id == user.id)
        .scalar()
    )
    return teacher_to_out(user, count or 0)


@router.post("/admin/teachers/{teacher_id}/reset_password", response_model=SuccessOut)
def reset_teacher_password(teacher_id: int, body: ResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = get_role_user(db, teacher_id, "teacher")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return SuccessOut(success=True)


@router.get("/admin/teachers/{teacher_id}/students", response_model=StudentIdsOut)
def list_teacher_students(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    get_role_user(db, teacher_id, "teacher")
    ids = (
        db.query(TeacherStudent.student_id)
        .filter(TeacherStudent.teacher_id == teacher_id)
        .order_by(TeacherStudent.student_id)
        .all()
    )
    return StudentIdsOut(student_ids=[i[0] for i in ids])


@router.put("/admin/teachers/{teacher_id}/students", response_model=StudentIdsOut)
def bind_teacher_students(teacher_id: int, body: BindStudentsRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    get_role_user(db, teacher_id, "teacher")
    student_ids = list(dict.fromkeys(body.student_ids))
    if student_ids:
        valid = (
            db.query(User.id)
            .filter(User.id.in_(student_ids), User.role == "student")
            .all()
        )
        valid_ids = {row[0] for row in valid}
        if valid_ids != set(student_ids):
            raise APIError(422, "INVALID_STUDENT_IDS", "存在无效或非学生的用户 ID")
    db.query(TeacherStudent).filter(TeacherStudent.teacher_id == teacher_id).delete()
    for sid in student_ids:
        db.add(TeacherStudent(teacher_id=teacher_id, student_id=sid))
    db.commit()
    return StudentIdsOut(student_ids=student_ids)


def student_to_out(s: User, teachers: list[User], groups: list[GroupRef] | None = None) -> StudentOut:
    return StudentOut(
        id=s.id,
        username=s.username,
        display_name=s.display_name,
        is_active=s.is_active,
        created_at=s.created_at,
        teachers=[UserOut.model_validate(t) for t in teachers],
        groups=groups or [],
    )


@router.get("/admin/students", response_model=list[StudentOut])
def list_students(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    students = db.query(User).filter(User.role == "student").order_by(User.id).all()
    binds = (
        db.query(TeacherStudent.student_id, User)
        .join(User, User.id == TeacherStudent.teacher_id)
        .all()
    )
    teacher_map: dict[int, list[User]] = {}
    for student_id, teacher in binds:
        teacher_map.setdefault(student_id, []).append(teacher)
    # 分组同理一次联查构建 map，避免 N+1
    group_map = groups_svc.groups_map_for_students(db, [s.id for s in students])
    return [
        student_to_out(s, teacher_map.get(s.id, []), group_map.get(s.id, []))
        for s in students
    ]


@router.post("/admin/students", response_model=StudentOut)
def create_student(body: AccountCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = create_account(db, body, "student")
    return student_to_out(user, [])


def decode_text_bytes(raw: bytes) -> str:
    """文本编码兜底：utf-8-sig → gbk（沿用既有逻辑）。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise APIError(422, "INVALID_CSV_ENCODING", "文件编码无法识别，请使用 UTF-8 或 GBK")


def cell_to_text(value) -> str:
    """xlsx 单元格 → 文本；学号常被 Excel 存成数字。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def split_group_cell(cell: str) -> list[str]:
    return groups_svc.normalize_group_names(GROUP_SEP_RE.split(cell or ""))


def _is_header_row(cells: list[str]) -> bool:
    return bool(cells) and cells[0].strip() in HEADER_FIRST_CELLS


def _iter_delimited_cells(filename: str, text: str):
    """txt/csv → (行号, 前 3 列文本, 原始内容)。空行静默跳过（v2.0 行为变更）。"""
    is_csv = Path(filename).suffix.lower() == ".csv"
    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if is_csv:
            cells = line.split(",")
        elif "|" in line:
            cells = line.split("|")
        else:
            cells = TXT_ALT_SEP_RE.split(line)
        cells = [c.strip() for c in cells]
        # 第 3 列之后的内容并入组别列，不丢数据
        if len(cells) > 3:
            cells = cells[:2] + ["、".join(cells[2:])]
        yield idx, cells, line


def _iter_xlsx_cells(raw: bytes):
    openpyxl = export_svc.load_openpyxl()
    from io import BytesIO

    try:
        wb = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise APIError(422, "INVALID_XLSX", "Excel 文件无法解析，请另存为标准 .xlsx")
    try:
        ws = wb.worksheets[0]  # 只取第一个 sheet 的前 3 列
        for idx, row in enumerate(ws.iter_rows(min_col=1, max_col=3, values_only=True), start=1):
            cells = [cell_to_text(v) for v in (list(row) + ["", "", ""])[:3]]
            if not any(cells):
                continue
            yield idx, cells, " | ".join(c for c in cells if c)
    finally:
        wb.close()


def parse_import_file(filename: str, raw: bytes) -> tuple[list[ImportRow], list[ImportFailure]]:
    """三种格式统一解析成中间表示；行不合法的进 failures，且绝不解析其组别（无副作用）。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMPORT_EXTS:
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "仅支持 xlsx / txt / csv 格式")
    if len(raw) > MAX_IMPORT_BYTES:
        raise APIError(413, "FILE_TOO_LARGE", "导入文件超过 5MB 限制")
    if not raw:
        raise APIError(422, "EMPTY_FILE", "导入文件为空")

    cells_iter = _iter_xlsx_cells(raw) if ext == ".xlsx" else _iter_delimited_cells(filename, decode_text_bytes(raw))

    rows: list[ImportRow] = []
    failures: list[ImportFailure] = []
    for idx, cells, content in cells_iter:
        if _is_header_row(cells):
            continue
        username = cells[0] if cells else ""
        display_name = cells[1] if len(cells) > 1 else ""
        if not username or not display_name:
            failures.append(ImportFailure(line=idx, content=content, username=username or None,
                                          reason="字段缺失"))
            continue
        group_names = split_group_cell(cells[2]) if len(cells) > 2 else []
        rows.append((idx, username, display_name, group_names))
    return rows, failures


def process_import_rows(db: Session, rows: list[ImportRow],
                        failures: list[ImportFailure] | None = None) -> ImportResult:
    """落库：先全量校验（重名学号），再建组、建学生、建成员关系，整批单事务 commit。"""
    failures = list(failures or [])
    existing = {row[0] for row in db.query(User.username).all()}
    seen: set[str] = set()
    valid: list[ImportRow] = []
    for line_no, username, display_name, group_names in rows:
        if username in existing or username in seen:
            failures.append(ImportFailure(line=line_no, content=f"{username},{display_name}",
                                          username=username, reason="学号重复"))
            continue
        seen.add(username)
        valid.append((line_no, username, display_name, group_names))

    if not valid:
        db.commit()
        return ImportResult(success_count=0, failures=sorted(failures, key=lambda f: f.line))

    # 合法行的组别才可能自动建组
    groups_by_name = {
        g.name: g for g in groups_svc.ensure_groups(
            db, [name for _, _, _, names in valid for name in names]
        )
    }
    created: list[tuple[User, list[str]]] = []
    for _line_no, username, display_name, group_names in valid:
        user = User(
            username=username,
            password_hash=hash_password(username),
            role="student",
            display_name=display_name,
        )
        db.add(user)
        created.append((user, group_names))
    db.flush()
    for user, group_names in created:
        for name in group_names:
            db.add(GroupMember(group_id=groups_by_name[name].id, student_id=user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "IMPORT_FAILED", "导入写入冲突，整批学生未导入")
    return ImportResult(success_count=len(created), failures=sorted(failures, key=lambda f: f.line))


@router.post("/admin/students/import", response_model=ImportResult)
async def import_students(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    raw = await file.read()
    rows, failures = parse_import_file(file.filename or "", raw)
    return process_import_rows(db, rows, failures)


@router.patch("/admin/students/{student_id}", response_model=StudentOut)
def patch_student(student_id: int, body: IsActivePatch, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = get_role_user(db, student_id, "student")
    user.is_active = 1 if body.is_active else 0
    db.commit()
    db.refresh(user)
    teachers = (
        db.query(User)
        .join(TeacherStudent, TeacherStudent.teacher_id == User.id)
        .filter(TeacherStudent.student_id == student_id)
        .all()
    )
    group_map = groups_svc.groups_map_for_students(db, [student_id])
    return student_to_out(user, teachers, group_map.get(student_id, []))


@router.post("/admin/students/{student_id}/reset_password", response_model=SuccessOut)
def reset_student_password(student_id: int, body: ResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = get_role_user(db, student_id, "student")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return SuccessOut(success=True)


# ---------- 分组 CRUD（仅 admin）----------

def group_to_out(group: Group, member_count: int) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        created_at=group.created_at,
        member_count=member_count,
    )


@router.get("/admin/groups", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [group_to_out(g, count) for g, count in groups_svc.list_groups_with_count(db)]


@router.post("/admin/groups", response_model=GroupOut)
def create_group(body: GroupCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    name = body.name.strip()
    if not name:
        raise APIError(422, "VALIDATION_ERROR", "分组名称不能为空")
    if groups_svc.normalize_group_names([name]) != [name]:
        raise APIError(422, "GROUP_NAME_INVALID", "分组名称超长或非法")
    if db.execute(select(Group).where(Group.name == name)).scalar_one_or_none() is not None:
        raise APIError(409, "GROUP_NAME_EXISTS", "分组名称已存在")
    group = Group(name=name)
    db.add(group)
    try:
        db.commit()
    except IntegrityError:
        # 并发下唯一索引兜底
        db.rollback()
        raise APIError(409, "GROUP_NAME_EXISTS", "分组名称已存在")
    db.refresh(group)
    groups_svc.remember_group_in_cache(name, group.id)
    return group_to_out(group, 0)


@router.patch("/admin/groups/{group_id}", response_model=GroupOut)
def rename_group(group_id: int, body: GroupUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if group is None:
        raise APIError(404, "GROUP_NOT_FOUND", "分组不存在")
    name = body.name.strip()
    if not name:
        raise APIError(422, "VALIDATION_ERROR", "分组名称不能为空")
    clash = db.execute(select(Group).where(Group.name == name, Group.id != group_id)).scalar_one_or_none()
    if clash is not None:
        raise APIError(409, "GROUP_NAME_EXISTS", "分组名称已存在")
    groups_svc.forget_group_in_cache(group.id)
    group.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "GROUP_NAME_EXISTS", "分组名称已存在")
    db.refresh(group)
    groups_svc.remember_group_in_cache(name, group.id)
    count = db.scalar(
        select(func.count(GroupMember.student_id)).where(GroupMember.group_id == group.id)
    )
    return group_to_out(group, count or 0)


@router.delete("/admin/groups/{group_id}", response_model=SuccessOut)
def delete_group(group_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if group is None:
        raise APIError(404, "GROUP_NOT_FOUND", "分组不存在")
    # 显式清成员关系，不依赖连接的 foreign_keys 开关
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
    db.delete(group)
    db.commit()
    groups_svc.forget_group_in_cache(group_id)
    return SuccessOut(success=True)


# ---------- 学生批量操作（仅 admin；密码能力只存在于 admin 端）----------

@router.post("/admin/students/group_members", response_model=GroupMembershipOut)
def batch_group_members(body: GroupMembersRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    students = groups_svc.validate_student_ids(db, body.student_ids)
    changed = groups_svc.apply_membership(
        db, [s.id for s in students], body.group_ids, body.action
    )
    return GroupMembershipOut(success_count=changed)


@router.post("/admin/students/batch_reset_password", response_model=SuccessOut)
def batch_reset_password(body: BatchResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = groups_svc.validate_student_ids(db, body.student_ids)
    # N 个学生共用一次 bcrypt（cost=12 约 250ms/次），整批仍是一个事务
    password_hash = hash_password(body.new_password)
    for user in users:
        user.password_hash = password_hash
    db.commit()
    return SuccessOut(success=True)


@router.post("/admin/students/batch_active", response_model=SuccessOut)
def batch_active(body: BatchActiveRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = groups_svc.validate_student_ids(db, body.student_ids)
    flag = 1 if body.is_active else 0
    for user in users:
        user.is_active = flag
    db.commit()
    return SuccessOut(success=True)


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return settings_to_out(get_or_create_settings(db))


@router.get("/settings/bg_image")
def get_bg_image(v: str | None = None, mode: str = "light", db: Session = Depends(get_db)):
    s = db.get(SiteSetting, 1)
    stored = getattr(s, bg_field(mode)) if s is not None else None
    if not stored:
        raise APIError(404, "BG_IMAGE_NOT_FOUND", "未设置背景图")
    path = config.BG_DIR / stored
    if not path.is_file():
        raise APIError(404, "BG_IMAGE_NOT_FOUND", "背景图文件不存在")
    # 版本号正确的 URL 内容永不改变，可长期缓存；版本不符（旧标签页/旧页面）必须回源
    cache = "public, max-age=31536000, immutable" if v == Path(stored).stem else "no-store"
    return FileResponse(path, headers={"Cache-Control": cache})


@router.put("/admin/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.brand_color is not None and not HEX_COLOR_RE.match(body.brand_color):
        raise APIError(422, "INVALID_BRAND_COLOR", "主题色格式无效，应为 #RRGGBB")
    s = get_or_create_settings(db)
    if body.brand_color is not None:
        s.brand_color = body.brand_color
    if body.brand_color_source is not None:
        s.brand_color_source = body.brand_color_source
    if body.bg_dual is not None:
        s.bg_dual = 1 if body.bg_dual else 0
    if body.bg_opacity is not None:
        s.bg_opacity = body.bg_opacity
    s.updated_by = admin.id
    s.updated_at = now_str()
    db.commit()
    db.refresh(s)
    return settings_to_out(s)


@router.post("/admin/settings/bg_image", response_model=BgImageOut)
async def upload_bg_image(file: UploadFile = File(...), mode: str = "light", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    field = bg_field(mode)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_BG_EXTS:
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "仅支持 jpg/png/webp 格式")
    raw = await file.read()
    if len(raw) > MAX_BG_BYTES:
        raise APIError(413, "FILE_TOO_LARGE", "图片超过 5MB 限制")
    if not raw:
        raise APIError(422, "EMPTY_FILE", "图片文件为空")
    s = get_or_create_settings(db)
    if getattr(s, field):
        old = config.BG_DIR / getattr(s, field)
        if old.is_file():
            old.unlink()
    filename = f"{uuid.uuid4().hex}{ext}"
    (config.BG_DIR / filename).write_bytes(raw)
    setattr(s, field, filename)
    s.updated_by = admin.id
    s.updated_at = now_str()
    db.commit()
    return BgImageOut(url=bg_image_url(filename, mode))


@router.delete("/admin/settings/bg_image", response_model=SettingsOut)
def delete_bg_image(mode: str = "light", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    field = bg_field(mode)
    s = get_or_create_settings(db)
    if getattr(s, field):
        old = config.BG_DIR / getattr(s, field)
        if old.is_file():
            old.unlink()
        setattr(s, field, None)
        s.updated_by = admin.id
        s.updated_at = now_str()
        db.commit()
        db.refresh(s)
    return settings_to_out(s)
