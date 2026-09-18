import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core import config
from ..core.db import get_db
from ..core.security import APIError, hash_password, require_admin
from ..models import SiteSetting, TeacherStudent, User
from ..schemas import (AccountCreate, BindStudentsRequest, ImportFailure,
                       ImportResult, IsActivePatch, ResetPasswordRequest,
                       SettingsOut, SettingsUpdate, StudentOut, TeacherOut,
                       UserOut)

router = APIRouter()

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_BG_BYTES = 5 * 1024 * 1024
ALLOWED_BG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
BG_IMAGE_URL = "/api/settings/bg_image"


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


def settings_to_out(s: SiteSetting) -> SettingsOut:
    return SettingsOut(
        brand_color=s.brand_color,
        bg_image_url=BG_IMAGE_URL if s.bg_image_path else None,
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


def student_to_out(s: User, teachers: list[User]) -> StudentOut:
    return StudentOut(
        id=s.id,
        username=s.username,
        display_name=s.display_name,
        is_active=s.is_active,
        created_at=s.created_at,
        teachers=[UserOut.model_validate(t) for t in teachers],
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
    return [student_to_out(s, teacher_map.get(s.id, [])) for s in students]


@router.post("/admin/students", response_model=StudentOut)
def create_student(body: AccountCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = create_account(db, body, "student")
    return student_to_out(user, [])


def parse_csv_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise APIError(422, "INVALID_CSV_ENCODING", "CSV 编码无法识别，请使用 UTF-8 或 GBK")


def process_csv_rows(db: Session, text: str) -> ImportResult:
    failures: list[ImportFailure] = []
    success_count = 0
    existing = {row[0] for row in db.query(User.username).all()}
    seen: set[str] = set()
    for idx, line in enumerate(text.splitlines(), start=1):
        if idx == 1 and line.strip() in ("学号,姓名", "学号, 姓名"):
            continue
        if not line.strip():
            failures.append(ImportFailure(line=idx, content=line, reason="空行"))
            continue
        parts = line.split(",")
        if len(parts) < 2:
            failures.append(ImportFailure(line=idx, content=line, reason="字段缺失"))
            continue
        username = parts[0].strip()
        display_name = parts[1].strip()
        if not username or not display_name:
            failures.append(ImportFailure(line=idx, content=line, reason="字段缺失"))
            continue
        if username in existing or username in seen:
            failures.append(ImportFailure(line=idx, content=line, reason="学号重复"))
            continue
        seen.add(username)
        db.add(
            User(
                username=username,
                password_hash=hash_password(username),
                role="student",
                display_name=display_name,
            )
        )
        success_count += 1
    db.commit()
    return ImportResult(success_count=success_count, failures=failures)


@router.post("/admin/students/import", response_model=ImportResult)
async def import_students(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    raw = await file.read()
    if not raw:
        raise APIError(422, "EMPTY_FILE", "CSV 文件为空")
    return process_csv_rows(db, parse_csv_bytes(raw))


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
    return student_to_out(user, teachers)


@router.post("/admin/students/{student_id}/reset_password", response_model=SuccessOut)
def reset_student_password(student_id: int, body: ResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = get_role_user(db, student_id, "student")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return SuccessOut(success=True)


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return settings_to_out(get_or_create_settings(db))


@router.get("/settings/bg_image")
def get_bg_image(db: Session = Depends(get_db)):
    s = db.get(SiteSetting, 1)
    if s is None or not s.bg_image_path:
        raise APIError(404, "BG_IMAGE_NOT_FOUND", "未设置背景图")
    path = config.BG_DIR / s.bg_image_path
    if not path.is_file():
        raise APIError(404, "BG_IMAGE_NOT_FOUND", "背景图文件不存在")
    return FileResponse(path)


@router.put("/admin/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.brand_color is not None and not HEX_COLOR_RE.match(body.brand_color):
        raise APIError(422, "INVALID_BRAND_COLOR", "主题色格式无效，应为 #RRGGBB")
    s = get_or_create_settings(db)
    if body.brand_color is not None:
        s.brand_color = body.brand_color
    if body.bg_opacity is not None:
        s.bg_opacity = body.bg_opacity
    s.updated_by = admin.id
    s.updated_at = now_str()
    db.commit()
    db.refresh(s)
    return settings_to_out(s)


@router.post("/admin/settings/bg_image", response_model=BgImageOut)
async def upload_bg_image(file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_BG_EXTS:
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "仅支持 jpg/png/webp 格式")
    raw = await file.read()
    if len(raw) > MAX_BG_BYTES:
        raise APIError(413, "FILE_TOO_LARGE", "图片超过 5MB 限制")
    if not raw:
        raise APIError(422, "EMPTY_FILE", "图片文件为空")
    s = get_or_create_settings(db)
    if s.bg_image_path:
        old = config.BG_DIR / s.bg_image_path
        if old.is_file():
            old.unlink()
    filename = f"{uuid.uuid4().hex}{ext}"
    (config.BG_DIR / filename).write_bytes(raw)
    s.bg_image_path = filename
    s.updated_by = admin.id
    s.updated_at = now_str()
    db.commit()
    return BgImageOut(url=BG_IMAGE_URL)


@router.delete("/admin/settings/bg_image", response_model=SettingsOut)
def delete_bg_image(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    s = get_or_create_settings(db)
    if s.bg_image_path:
        old = config.BG_DIR / s.bg_image_path
        if old.is_file():
            old.unlink()
        s.bg_image_path = None
        s.updated_by = admin.id
        s.updated_at = now_str()
        db.commit()
        db.refresh(s)
    return settings_to_out(s)
