from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import (APIError, create_token, get_current_user, hash_password,
                             is_temp_password_expired, utcnow_str, validate_new_password,
                             verify_password)
from ..models import User
from ..schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserOut
from ..services.audit import log_audit

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise APIError(401, "BAD_CREDENTIALS", "用户名或密码错误")
    if not user.is_active:
        raise APIError(403, "USER_DISABLED", "账号已停用")
    # PW-05：随机临时密码自生成起 7 天未改密即过期；统一/初始密码 password_updated_at 为 NULL，不受限
    if user.must_change_password and is_temp_password_expired(user.password_updated_at):
        raise APIError(403, "PASSWORD_EXPIRED", "临时密码已过期，请联系管理员重新重置")
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise APIError(400, "BAD_OLD_PASSWORD", "当前密码不正确")
    forced = bool(user.must_change_password)
    validate_new_password(body.new_password, username=user.username,
                          display_name=user.display_name, old_password=body.old_password)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = 0
    user.password_updated_at = utcnow_str()
    log_audit(db, user, "user_change_password", "user", user.id, {"forced": forced})
    db.commit()
