"""admin 端接口：账号、分组、批量导入、批量操作、审计查看、主题设置。

密码口径（PW-01/04/05/06，密码能力只存在于 admin 端）：
- 新建学生/教师不再收密码，统一 `config.DEFAULT_INITIAL_PASSWORD` + `must_change_password=1`，
  `password_updated_at=NULL`（PW-05：初始密码不过期）。
- 单个重置：系统生成 8 位随机临时密码并在响应里返回明细（TempCredentialOut），无请求体。
- 批量重置：mode=unified 全员回到初始密码（整批只算一次 bcrypt、不过期）；
  mode=random 逐生独立随机密码（人数超阈值走线程池并行哈希）。
- 上述动作全部经 `services/audit.log_audit` 写审计（AU-02/04）。

导入格式：`学号 | 姓名 | 组别 | 教师`（第 4 列可选，IM-01）。教师列写教师用户名，
可多个、分隔符同组别列；生效方式是幂等写 `teacher_groups`（层 2 组-教师分配），
**不**写 `teacher_students`（层 3 由教师自行拉取，见 BD-03/04）。
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import config
from ..core.db import get_db
from ..core.security import (APIError, generate_temp_password,
                             generate_unique_temp_passwords, hash_password,
                             hash_password_many, require_admin, temp_password_expires_at,
                             utcnow_str)
from ..models import (AuditLog, Group, GroupMember, SiteSetting, TeacherGroup,
                      TeacherNotice, User)
from ..schemas import (AccountCreate, AuditLogOut, AuditLogPageOut, BatchActiveRequest,
                       BatchResetPasswordRequest, BatchResetResultOut, GroupCreate,
                       GroupMembershipOut, GroupMembersRequest, GroupOut, GroupRef,
                       GroupUpdate, ImportFailure, ImportResult, IsActivePatch,
                       RosterEntryOut, SettingsOut, SettingsUpdate, StudentOut,
                       TeacherGroupsOut, TeacherGroupsRequest, TeacherOut,
                       TeacherRosterOut, TempCredentialOut, UserOut)
from ..services import export as export_svc
from ..services import groups as groups_svc
from ..services import stats
from ..services.audit import log_audit

router = APIRouter()

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_BG_BYTES = 5 * 1024 * 1024
ALLOWED_BG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
BG_IMAGE_URL = "/api/settings/bg_image"

# ---------- 学生导入（xlsx / txt / csv）----------
ALLOWED_IMPORT_EXTS = {".xlsx", ".txt", ".csv"}
MAX_IMPORT_BYTES = 5 * 1024 * 1024
# 列数：学号、姓名、组别、教师（教师列可选，旧三列文件照常解析）
IMPORT_COLUMNS = 4
# 组别列 / 教师列内的多值分隔符（两列共用，IM-01）
GROUP_SEP_RE = re.compile(r"[、，,；;/]")
TXT_ALT_SEP_RE = re.compile(r"[,，]")
HEADER_FIRST_CELLS = {"学号", "学生ID"}
# 统一中间表示：(行号, 学号, 姓名, [组别], [教师用户名])
ImportRow = tuple[int, str, str, list[str], list[str]]


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


def search_users(query, q: str | None):
    """LI-01：按 username / display_name 模糊过滤（大小写不敏感）；q 缺省或空白时不过滤。"""
    needle = (q or "").strip().lower()
    if not needle:
        return query
    pattern = f"%{needle}%"
    return query.filter(
        or_(func.lower(User.username).like(pattern), func.lower(User.display_name).like(pattern))
    )


def create_account(db: Session, actor: User, body: AccountCreate, role: str) -> User:
    """PW-01：学生/教师建号一律统一初始密码 + 首登强制改密，admin 不再手填密码。"""
    exists = db.query(User).filter(User.username == body.username).first()
    if exists is not None:
        raise APIError(409, "DUPLICATE_USERNAME", "用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(config.DEFAULT_INITIAL_PASSWORD),
        role=role,
        display_name=body.display_name,
        must_change_password=1,
        password_updated_at=None,  # PW-05：初始密码不设 7 天有效期
    )
    db.add(user)
    db.flush()  # 先取自增 id 作为审计 target_id，再与业务写操作同事务提交
    # AU-04：student_create_pw / teacher_create_pw
    log_audit(db, actor, f"{role}_create_pw", role, user.id,
              {"must_change_password": True})
    db.commit()
    db.refresh(user)
    return user


def reset_to_temp_password(db: Session, actor: User, user: User, action: str) -> TempCredentialOut:
    """PW-04：单个重置——系统生成 8 位随机密码，一次性 + 7 天过期（PW-05 锚点）。

    调用方需已完成 role 校验；本函数负责 commit 与审计（AU-04）。
    """
    temp_password = generate_temp_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = 1
    user.password_updated_at = utcnow_str()
    log_audit(db, actor, action, user.role, user.id, {"mode": "random"})
    db.commit()
    return credential_out(user, temp_password)


def credential_out(user: User, temp_password: str) -> TempCredentialOut:
    """PW-09 明细的一行：过期时间由 password_updated_at 推算（NULL → None）。"""
    return TempCredentialOut(
        student_id=user.id,
        username=user.username,
        display_name=user.display_name,
        temp_password=temp_password,
        expires_at=temp_password_expires_at(user.password_updated_at),
    )


def teacher_to_out(t: User, student_count: int = 0) -> TeacherOut:
    return TeacherOut(
        id=t.id,
        username=t.username,
        display_name=t.display_name,
        is_active=t.is_active,
        must_change_password=bool(t.must_change_password),
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
        brand_color_dark=s.brand_color_dark,
        brand_color_source=s.brand_color_source,
        bg_image_url=bg_image_url(s.bg_image_path) if s.bg_image_path else None,
        bg_image_url_dark=bg_image_url(s.bg_image_path_dark, "dark") if s.bg_image_path_dark else None,
        bg_dual=bool(s.bg_dual),
        bg_opacity=s.bg_opacity,
    )


@router.get("/admin/teachers", response_model=list[TeacherOut])
def list_teachers(q: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    teachers = search_users(db.query(User).filter(User.role == "teacher"), q).order_by(User.id).all()
    # 0.3.2 F1：名单人数改为「可教组并集 ∪ 手动添加」口径（与 /teacher/students 同源）
    counts = groups_svc.roster_count_by_teacher(db)
    return [teacher_to_out(t, counts.get(t.id, 0)) for t in teachers]


@router.post("/admin/teachers", response_model=TeacherOut)
def create_teacher(body: AccountCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = create_account(db, admin, body, "teacher")
    return teacher_to_out(user)


@router.patch("/admin/teachers/{teacher_id}", response_model=TeacherOut)
def patch_teacher(teacher_id: int, body: IsActivePatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = get_role_user(db, teacher_id, "teacher")
    user.is_active = 1 if body.is_active else 0
    log_audit(db, admin, "user_is_active_change", "teacher", user.id,
              {"is_active": bool(body.is_active)})
    db.commit()
    db.refresh(user)
    # 同一并集口径（可教组 ∪ 手动添加）
    return teacher_to_out(user, len(stats.bound_students(db, user.id)))


@router.post("/admin/teachers/{teacher_id}/reset_password", response_model=TempCredentialOut)
def reset_teacher_password(teacher_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """PW-04【v1.1：教师同规则】：无请求体，返回系统生成的随机凭证明细。"""
    user = get_role_user(db, teacher_id, "teacher")
    return reset_to_temp_password(db, admin, user, "teacher_reset_pw")


@router.get("/admin/teachers/{teacher_id}/students", response_model=TeacherRosterOut)
def list_teacher_students(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """BD-06 + 0.3.2 F1：admin 保留教师名单的只读视图（写接口已删除，层 3 唯一写者是教师本人）。

    名单口径 = 可教组成员 ∪ 手动添加；每条给出 source（manual/group）与该生所在的可教组名，
    供教师详情页渲染矩阵来源角标。撤销组别后该组学生立即从本视图消失（手动添加者不受影响）。
    """
    get_role_user(db, teacher_id, "teacher")
    manual = groups_svc.manual_student_ids(db, teacher_id)
    group_names = groups_svc.teachable_group_names_by_student(db, teacher_id)
    return TeacherRosterOut(students=[
        RosterEntryOut(
            id=s.id,
            username=s.username,
            display_name=s.display_name,
            source="manual" if s.id in manual else "group",
            group_names=group_names.get(s.id, []),
        )
        for s in stats.bound_students(db, teacher_id)
    ])


def teacher_group_ids(db: Session, teacher_id: int) -> list[int]:
    return [row[0] for row in db.query(TeacherGroup.group_id)
            .filter(TeacherGroup.teacher_id == teacher_id)
            .order_by(TeacherGroup.group_id)
            .all()]


@router.get("/admin/teachers/{teacher_id}/groups", response_model=TeacherGroupsOut)
def list_teacher_groups(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """BD-02：查看某教师的可教组（层 2 组-教师分配）。"""
    get_role_user(db, teacher_id, "teacher")
    return TeacherGroupsOut(teacher_id=teacher_id, group_ids=teacher_group_ids(db, teacher_id))


@router.put("/admin/teachers/{teacher_id}/groups", response_model=TeacherGroupsOut)
def replace_teacher_groups(teacher_id: int, body: TeacherGroupsRequest, db: Session = Depends(get_db),
                           admin: User = Depends(require_admin)):
    """BD-02：全量替换某教师的可教组（页面 diff 确认后提交；空列表 = 清空分配）。

    决策 1e：撤销组别即刻清名单 —— 保存前先算差集，把「因本次撤销而离开名单」的学生
    写成一条 teacher_notices(kind='group_revoked')，与该变更同事务提交，教师下次登录弹窗说明。
    """
    get_role_user(db, teacher_id, "teacher")
    group_ids = sorted(dict.fromkeys(body.group_ids))
    # 任一不存在的组 → 404 GROUP_NOT_FOUND，整批不写
    groups_svc.require_groups_exist(db, group_ids)
    current = set(teacher_group_ids(db, teacher_id))
    target = set(group_ids)
    removed = sorted(current - target)

    # 新名单 = 新的可教组并集 ∪ 手动添加（手动添加者不算「离开」）
    new_teachable: set[int] = set()
    for members in groups_svc.student_ids_in_groups(db, sorted(target)).values():
        new_teachable |= members
    new_roster = new_teachable | groups_svc.manual_student_ids(db, teacher_id)
    removed_members = groups_svc.student_ids_in_groups(db, removed)
    lost_groups: list[dict] = []
    lost_students: set[int] = set()
    for gid in removed:
        lost = removed_members.get(gid, set()) - new_roster
        lost_students |= lost
        group = db.get(Group, gid)
        lost_groups.append({"id": gid, "name": group.name if group else "", "lost_count": len(lost)})

    for gid in removed:
        db.query(TeacherGroup).filter(
            TeacherGroup.teacher_id == teacher_id, TeacherGroup.group_id == gid
        ).delete(synchronize_session=False)
    groups_svc.assign_teacher_groups(db, [(teacher_id, gid) for gid in sorted(target - current)])
    if lost_students:
        # 无人离开时不打扰教师；有人离开时一次性说明所有被撤销组的损失
        db.add(TeacherNotice(
            teacher_id=teacher_id,
            kind="group_revoked",
            payload=json.dumps(
                {"groups": lost_groups, "total_lost": len(lost_students)}, ensure_ascii=False
            ),
        ))
    log_audit(db, admin, "teacher_group_assign", "teacher", teacher_id,
              {"group_ids": sorted(target), "added": sorted(target - current),
               "removed": removed})
    db.commit()
    return TeacherGroupsOut(teacher_id=teacher_id, group_ids=teacher_group_ids(db, teacher_id))


def student_to_out(s: User, teachers: list[User], groups: list[GroupRef] | None = None) -> StudentOut:
    return StudentOut(
        id=s.id,
        username=s.username,
        display_name=s.display_name,
        is_active=s.is_active,
        must_change_password=bool(s.must_change_password),
        created_at=s.created_at,
        teachers=[UserOut.model_validate(t) for t in teachers],
        groups=groups or [],
    )


@router.get("/admin/students", response_model=list[StudentOut])
def list_students(q: str | None = None, group_id: int | None = None,
                  must_change: int | None = Query(default=None, ge=0, le=1),
                  db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """LI-01/02：可选 `q`（学号/姓名模糊）、`group_id`、`must_change`（0/1）；缺省行为与旧版一致。"""
    query = db.query(User).filter(User.role == "student")
    query = search_users(query, q)
    if group_id is not None:
        query = query.join(GroupMember, GroupMember.student_id == User.id).filter(
            GroupMember.group_id == group_id
        )
    if must_change is not None:
        query = query.filter(User.must_change_password == (1 if must_change else 0))
    students = query.order_by(User.id).all()
    # 0.3.2 F1：学生→教师反查走与名单同一并集口径（组别被撤销后教师立即消失）
    teacher_map = stats.bound_teacher_map(db, [s.id for s in students])
    # 分组同理一次联查构建 map，避免 N+1
    group_map = groups_svc.groups_map_for_students(db, [s.id for s in students])
    return [
        student_to_out(s, teacher_map.get(s.id, []), group_map.get(s.id, []))
        for s in students
    ]


@router.post("/admin/students", response_model=StudentOut)
def create_student(body: AccountCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = create_account(db, admin, body, "student")
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


def split_teacher_cell(cell: str) -> list[str]:
    """IM-01：教师列拆分（分隔符同组别列）；教师按 username 精确匹配，故只去空白/去重，不套组名规则。"""
    names: list[str] = []
    for raw in GROUP_SEP_RE.split(cell or ""):
        name = raw.strip()
        if name and name not in names:
            names.append(name)
    return names


def _is_header_row(cells: list[str]) -> bool:
    return bool(cells) and cells[0].strip() in HEADER_FIRST_CELLS


def _iter_delimited_cells(filename: str, text: str):
    """txt/csv → (行号, 前 4 列文本, 原始内容)。空行静默跳过（v2.0 行为变更）。"""
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
        # 第 4 列之后的内容并入教师列，不丢数据（IM-01；旧行为是并入第 3 列组别）
        if len(cells) > IMPORT_COLUMNS:
            cells = cells[:IMPORT_COLUMNS - 1] + ["、".join(cells[IMPORT_COLUMNS - 1:])]
        yield idx, (cells + [""] * IMPORT_COLUMNS)[:IMPORT_COLUMNS], line


def _iter_xlsx_cells(raw: bytes):
    openpyxl = export_svc.load_openpyxl()
    from io import BytesIO

    try:
        wb = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise APIError(422, "INVALID_XLSX", "Excel 文件无法解析，请另存为标准 .xlsx")
    try:
        ws = wb.worksheets[0]  # 只取第一个 sheet 的前 4 列（第 4 列教师可选）
        for idx, row in enumerate(
            ws.iter_rows(min_col=1, max_col=IMPORT_COLUMNS, values_only=True), start=1
        ):
            cells = [cell_to_text(v) for v in (list(row) + [""] * IMPORT_COLUMNS)[:IMPORT_COLUMNS]]
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
        teacher_names = split_teacher_cell(cells[3]) if len(cells) > 3 else []
        rows.append((idx, username, display_name, group_names, teacher_names))
    return rows, failures


def known_teacher_ids(db: Session, usernames: set[str]) -> dict[str, int]:
    """IM-01：教师列按 username 精确匹配（role=teacher）；未命中的即失败行。"""
    if not usernames:
        return {}
    rows = db.execute(
        select(User.id, User.username).where(User.role == "teacher", User.username.in_(usernames))
    ).all()
    return {username: user_id for user_id, username in rows}


def process_import_rows(db: Session, actor: User, rows: list[ImportRow],
                        failures: list[ImportFailure] | None = None) -> ImportResult:
    """落库：先全量校验（重名学号、教师列合法性），再建组、建学生、建成员关系与组-教师分配。

    整批单事务 commit；校验通过的行才可能自动建组（IM-01）。
    密码策略对齐 PW-01：统一初始密码（整批只算一次 bcrypt）+ 首登强制改密。
    """
    failures = list(failures or [])
    existing = {row[0] for row in db.query(User.username).all()}
    # 教师列的两条整行失败规则先算：只保留学号唯一的行再查教师是否存在
    prevalid: list[ImportRow] = []
    seen: set[str] = set()
    for row in rows:
        line_no, username, display_name, group_names, teacher_names = row
        if username in existing or username in seen:
            failures.append(ImportFailure(line=line_no, content=f"{username},{display_name}",
                                          username=username, reason="学号重复"))
            continue
        seen.add(username)
        if teacher_names and not group_names:
            # 否则「校验了教师却无任何效果」——IM-01 明确为失败行
            failures.append(ImportFailure(line=line_no, content=f"{username},{display_name}",
                                          username=username, reason="教师列需与组别列同时提供"))
            continue
        prevalid.append(row)

    teacher_ids = known_teacher_ids(
        db, {name for _, _, _, _, names in prevalid for name in names}
    )
    valid: list[ImportRow] = []
    for line_no, username, display_name, group_names, teacher_names in prevalid:
        unknown = [name for name in teacher_names if name not in teacher_ids]
        if unknown:
            failures.append(ImportFailure(line=line_no, content=f"{username},{display_name}",
                                          username=username, reason=f"教师不存在：{'、'.join(unknown)}"))
            continue
        valid.append((line_no, username, display_name, group_names, teacher_names))

    if not valid:
        log_audit(db, actor, "student_import", "user", None,
                  {"success_count": 0, "failure_count": len(failures)})
        db.commit()
        return ImportResult(success_count=0, failures=sorted(failures, key=lambda f: f.line))

    # 合法行的组别才可能自动建组
    groups_by_name = {
        g.name: g for g in groups_svc.ensure_groups(
            db, [name for _, _, _, names, _ in valid for name in names]
        )
    }
    initial_hash = hash_password(config.DEFAULT_INITIAL_PASSWORD)  # 整批一次 bcrypt（坑 24）
    created: list[tuple[User, list[str], list[str]]] = []
    for _line_no, username, display_name, group_names, teacher_names in valid:
        user = User(
            username=username,
            password_hash=initial_hash,
            role="student",
            display_name=display_name,
            must_change_password=1,
            password_updated_at=None,
        )
        db.add(user)
        created.append((user, group_names, teacher_names))
    db.flush()
    teacher_group_pairs: list[tuple[int, int]] = []
    for user, group_names, teacher_names in created:
        for name in group_names:
            group = groups_by_name[name]
            db.add(GroupMember(group_id=group.id, student_id=user.id))
            # 层 2：本行给出的每位教师都拿到这个组（幂等，已有不重复插）
            for teacher_name in teacher_names:
                teacher_group_pairs.append((teacher_ids[teacher_name], group.id))
        # AU-04：导入建号与单建一致，逐生一条 student_create_pw
        log_audit(db, actor, "student_create_pw", "student", user.id,
                  {"must_change_password": True})
    groups_svc.assign_teacher_groups(db, teacher_group_pairs)
    log_audit(db, actor, "student_import", "user", None,
              {"success_count": len(created), "failure_count": len(failures)})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "IMPORT_FAILED", "导入写入冲突，整批学生未导入")
    return ImportResult(success_count=len(created), failures=sorted(failures, key=lambda f: f.line))


@router.post("/admin/students/import", response_model=ImportResult)
async def import_students(file: UploadFile = File(...), db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    raw = await file.read()
    rows, failures = parse_import_file(file.filename or "", raw)
    return process_import_rows(db, admin, rows, failures)


@router.patch("/admin/students/{student_id}", response_model=StudentOut)
def patch_student(student_id: int, body: IsActivePatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = get_role_user(db, student_id, "student")
    user.is_active = 1 if body.is_active else 0
    log_audit(db, admin, "user_is_active_change", "student", user.id,
              {"is_active": bool(body.is_active)})
    db.commit()
    db.refresh(user)
    # 同一并集口径（可教组 ∪ 手动添加），与列表接口一致
    teachers = stats.bound_teacher_map(db, [student_id]).get(student_id, [])
    group_map = groups_svc.groups_map_for_students(db, [student_id])
    return student_to_out(user, teachers, group_map.get(student_id, []))


@router.post("/admin/students/{student_id}/reset_password", response_model=TempCredentialOut)
def reset_student_password(student_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """PW-04：无请求体；响应返回随机凭证明细，供管理员转告本人 / 前端拼 CSV。"""
    user = get_role_user(db, student_id, "student")
    return reset_to_temp_password(db, admin, user, "student_reset_pw")


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
def rename_group(group_id: int, body: GroupUpdate, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if group is None:
        raise APIError(404, "GROUP_NOT_FOUND", "分组不存在")
    name = body.name.strip()
    if not name:
        raise APIError(422, "VALIDATION_ERROR", "分组名称不能为空")
    clash = db.execute(select(Group).where(Group.name == name, Group.id != group_id)).scalar_one_or_none()
    if clash is not None:
        raise APIError(409, "GROUP_NAME_EXISTS", "分组名称已存在")
    old_name = group.name
    groups_svc.forget_group_in_cache(group.id)
    group.name = name
    log_audit(db, admin, "group_update", "group", group.id,
              {"old_name": old_name, "new_name": name})
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
def delete_group(group_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if group is None:
        raise APIError(404, "GROUP_NOT_FOUND", "分组不存在")
    log_audit(db, admin, "group_delete", "group", group.id, {"name": group.name})
    # 显式清成员关系，不依赖连接的 foreign_keys 开关
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
    db.delete(group)
    db.commit()
    groups_svc.forget_group_in_cache(group_id)
    return SuccessOut(success=True)


# ---------- 审计日志查看（AU-05：只追加，不提供任何 UPDATE/DELETE 路径）----------

def audit_row_to_out(row: AuditLog, actor_names: dict[int, str]) -> AuditLogOut:
    try:
        detail = json.loads(row.detail) if row.detail else None
    except ValueError:
        detail = None  # detail 列是自由 JSON 文本，解析不出来就当没有
    return AuditLogOut(
        id=row.id,
        actor_id=row.actor_id,
        actor_name=actor_names.get(row.actor_id, "") if row.actor_id is not None else "",
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        detail=detail if isinstance(detail, dict) else None,
        created_at=row.created_at,
    )


@router.get("/admin/audit_logs", response_model=AuditLogPageOut)
def list_audit_logs(action: str | None = None, target_type: str | None = None,
                    limit: int = Query(default=50, ge=0, le=200),
                    offset: int = Query(default=0, ge=0),
                    db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AuditLog.target_type == target_type)
    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
    ).scalars().all()
    actor_names = {}
    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    if actor_ids:
        for u in db.query(User).filter(User.id.in_(actor_ids)).all():
            actor_names[u.id] = f"{u.display_name}({u.username})"
    return AuditLogPageOut(items=[audit_row_to_out(r, actor_names) for r in rows], total=total)


# ---------- 学生批量操作（仅 admin；密码能力只存在于 admin 端）----------

@router.post("/admin/students/group_members", response_model=GroupMembershipOut)
def batch_group_members(body: GroupMembersRequest, db: Session = Depends(get_db),
                        admin: User = Depends(require_admin)):
    """GR-01：组别成员（层 1）唯一写者。写入与审计同事务，故用不提交的服务函数。"""
    students = groups_svc.validate_student_ids(db, body.student_ids)
    student_ids = sorted(s.id for s in students)
    group_ids = sorted(dict.fromkeys(body.group_ids))
    changed = groups_svc.apply_membership_changes(db, student_ids, group_ids, body.action)
    log_audit(db, admin, "group_member_change", "group",
              group_ids[0] if len(group_ids) == 1 else None,  # 跨多组时以 detail 为准
              {"action": body.action, "group_ids": group_ids,
               "student_ids": student_ids, "changed": changed})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "MEMBERSHIP_CONFLICT", "成员关系写入冲突，请重试")
    return GroupMembershipOut(success_count=changed)


@router.post("/admin/students/batch_reset_password", response_model=BatchResetResultOut)
def batch_reset_password(body: BatchResetPasswordRequest, db: Session = Depends(get_db),
                         admin: User = Depends(require_admin)):
    """PW-06：unified = 全员回到统一初始密码（整批一次 bcrypt、不过期）；
    random = 逐生独立随机密码（> 阈值时线程池并行哈希），两种模式均返回逐生明细（PW-09）。
    """
    users = groups_svc.validate_student_ids(db, body.student_ids)  # 先全量校验：非法 ID 整批 422，且不做哈希
    count = len(users)
    if body.mode == "unified":
        # 坑 24【v1.1 改写】：只有统一模式仍然「整批一次 bcrypt」
        password_hash = hash_password(config.DEFAULT_INITIAL_PASSWORD)
        temp_passwords = [config.DEFAULT_INITIAL_PASSWORD] * count
        hashes = [password_hash] * count
        stamp = None  # PW-05：统一/初始密码不过期
    else:
        temp_passwords = generate_unique_temp_passwords(count)
        # 大批量随机密码走线程池（bcrypt 释放 GIL），小批量直接串行，避免线程开销
        if count > config.BATCH_RESET_ASK_THRESHOLD:
            hashes = hash_password_many(temp_passwords)
        else:
            hashes = [hash_password(pw) for pw in temp_passwords]
        stamp = utcnow_str()  # 全员同一个过期锚点

    credentials: list[TempCredentialOut] = []
    for user, temp_password, password_hash in zip(users, temp_passwords, hashes):
        user.password_hash = password_hash
        user.must_change_password = 1
        user.password_updated_at = stamp
        credentials.append(credential_out(user, temp_password))
    log_audit(db, admin, "student_batch_reset_pw", "student", None,
              {"mode": body.mode, "count": count})
    db.commit()
    return BatchResetResultOut(mode=body.mode, count=count, credentials=credentials)


@router.post("/admin/students/batch_active", response_model=SuccessOut)
def batch_active(body: BatchActiveRequest, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    users = groups_svc.validate_student_ids(db, body.student_ids)
    flag = 1 if body.is_active else 0
    for user in users:
        user.is_active = flag
        # AU-02：启停逐人一条，便于按学生追溯
        log_audit(db, admin, "user_is_active_change", "student", user.id,
                  {"is_active": bool(body.is_active)})
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
    if body.brand_color_dark is not None and not HEX_COLOR_RE.match(body.brand_color_dark):
        raise APIError(422, "INVALID_BRAND_COLOR", "暗色主题色格式无效，应为 #RRGGBB")
    s = get_or_create_settings(db)
    if body.brand_color is not None:
        s.brand_color = body.brand_color
    if body.brand_color_dark is not None:
        s.brand_color_dark = body.brand_color_dark
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
