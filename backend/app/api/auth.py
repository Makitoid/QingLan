from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core import throttle
from ..core.db import get_db
from ..core.security import (APIError, create_token, dummy_password_hash, get_current_user,
                             hash_password, is_temp_password_expired, utcnow_str,
                             validate_new_password, verify_password)
from ..models import User
from ..schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserOut
from ..services.audit import log_audit

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttle_error(kind: str, retry_after: int) -> APIError:
    if kind == "account":
        return APIError(423, "ACCOUNT_LOCKED", "登录失败次数过多，请稍后再试",
                        headers={"Retry-After": str(retry_after)})
    return APIError(429, "TOO_MANY_ATTEMPTS", "登录尝试过于频繁，请稍后再试",
                    headers={"Retry-After": str(retry_after)})


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    # C-01：统一初始密码保留的前提下，账号维度退避 + IP 维度窗口是主要补偿控制
    blocked = throttle.check(body.username, ip)
    if blocked is not None:
        raise _throttle_error(*blocked)

    user = db.query(User).filter(User.username == body.username).first()
    # L-02：账号不存在时也对同成本哑哈希跑一次，避免用响应时间枚举用户名
    password_hash = user.password_hash if user is not None else dummy_password_hash()
    password_ok = verify_password(body.password, password_hash)
    if user is None or not password_ok:
        triggered = throttle.record_failure(body.username, ip)
        if triggered is not None:
            raise _throttle_error(*triggered)
        raise APIError(401, "BAD_CREDENTIALS", "用户名或密码错误")
    if not user.is_active:
        raise APIError(403, "USER_DISABLED", "账号已停用")
    # PW-05：随机临时密码自生成起 7 天未改密即过期；统一/初始密码 password_updated_at 为 NULL，不受限
    if user.must_change_password and is_temp_password_expired(user.password_updated_at):
        raise APIError(403, "PASSWORD_EXPIRED", "临时密码已过期，请联系管理员重新重置")
    throttle.record_success(body.username, ip)
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/password", response_model=TokenResponse)
def change_password(body: PasswordChangeRequest, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
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
    db.refresh(user)
    # M-01：口令指纹随密码改变，旧令牌全部失效；这里把当前会话换成新令牌，
    # 免得用户改密后被自己踢下线。
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))
