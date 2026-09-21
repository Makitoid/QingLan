from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import secrets

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..models import User
from . import config
from .db import get_db

TIME_FMT = "%Y-%m-%d %H:%M:%S"

# PW-02：未改密时仍放行的接口。改密接口本身走 get_current_user，
# 不在白名单里就会把「解除拦截」这条路径一起锁死。
PASSWORD_GUARD_ALLOWLIST = frozenset({
    "/api/auth/login",
    "/api/auth/me",
    "/api/auth/password",
    "/api/settings",
    "/api/settings/bg_image",
})


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def utcnow_str() -> str:
    """库内统一 UTC 串（坑 9：ISO 风格串可按字典序比较）。"""
    return datetime.now(timezone.utc).strftime(TIME_FMT)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def hash_password_many(passwords: list[str], workers: int | None = None) -> list[str]:
    """大批量随机密码并行哈希（PW-06）：bcrypt 计算期释放 GIL，线程池即真并行。

    结果与入参同序返回，调用方可直接 zip 到目标用户列表。
    """
    if not passwords:
        return []
    if len(passwords) == 1:
        return [hash_password(passwords[0])]
    pool_size = workers or config.BCRYPT_PARALLEL_WORKERS
    with ThreadPoolExecutor(max_workers=min(pool_size, len(passwords))) as pool:
        return list(pool.map(hash_password, passwords))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_temp_password() -> str:
    """PW-08：56 字符集、8 位，取 secrets（CSPRNG）。"""
    return "".join(
        secrets.choice(config.TEMP_PASSWORD_CHARSET) for _ in range(config.TEMP_PASSWORD_LENGTH)
    )


def generate_unique_temp_passwords(count: int) -> list[str]:
    """批量随机密码互不相同（56^8 ≈ 9.7e13，碰撞概率可忽略）。"""
    picked: set[str] = set()
    while len(picked) < count:
        picked.add(generate_temp_password())
    return list(picked)


def validate_new_password(new_password: str, *, username: str, display_name: str = "",
                         old_password: str | None = None) -> None:
    """PW-03：全角色统一的密码规则（强制改密与自助改密共用）。"""
    if len(new_password) < config.PASSWORD_MIN_LENGTH:
        raise APIError(422, "PASSWORD_POLICY", f"密码长度至少 {config.PASSWORD_MIN_LENGTH} 位")
    if any(ch.isspace() for ch in new_password):
        raise APIError(422, "PASSWORD_POLICY", "密码不能包含空格")
    forbidden = {username, display_name, config.DEFAULT_INITIAL_PASSWORD} - {"", None}
    if old_password is not None:
        forbidden.add(old_password)
    if new_password in forbidden:
        raise APIError(422, "PASSWORD_POLICY", "密码不能与学号/用户名、姓名、旧密码或初始密码相同")


def temp_password_expires_at(password_updated_at: str | None) -> str | None:
    """随机密码有效期 = 生成时刻 + 7 天；NULL（统一/初始密码）不过期。"""
    if not password_updated_at:
        return None
    try:
        base = datetime.strptime(password_updated_at[:19], TIME_FMT)
    except ValueError:
        return None
    return (base + timedelta(days=config.TEMP_PASSWORD_EXPIRE_DAYS)).strftime(TIME_FMT)


def is_temp_password_expired(password_updated_at: str | None) -> bool:
    if not password_updated_at:
        return False
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=config.TEMP_PASSWORD_EXPIRE_DAYS)).strftime(TIME_FMT)
    return password_updated_at < cutoff


def create_token(user: User) -> str:
    payload = {
        "uid": user.id,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None:
        raise APIError(401, "UNAUTHORIZED", "未登录或令牌缺失")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise APIError(401, "TOKEN_INVALID", "令牌无效或已过期")
    user = db.get(User, payload.get("uid"))
    if user is None:
        raise APIError(401, "USER_NOT_FOUND", "用户不存在")
    if not user.is_active:
        raise APIError(403, "USER_DISABLED", "账号已停用")
    # PW-02：后端强制拦截——未改密的用户只能碰白名单里的接口，业务 API 一律 403。
    # 全部依赖都过这里，因此新接口无需再各自记得加判断。
    if user.must_change_password and request.url.path not in PASSWORD_GUARD_ALLOWLIST:
        raise APIError(403, "MUST_CHANGE_PASSWORD", "请先修改密码后再继续使用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise APIError(403, "FORBIDDEN", "需要管理员权限")
    return user


def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role != "teacher":
        raise APIError(403, "FORBIDDEN", "需要教师权限")
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != "student":
        raise APIError(403, "FORBIDDEN", "需要学生权限")
    return user
