from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..models import User
from . import config
from .db import get_db


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


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
