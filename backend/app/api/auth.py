from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import (APIError, create_token, get_current_user,
                             hash_password, verify_password)
from ..models import User
from ..schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserOut

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise APIError(401, "BAD_CREDENTIALS", "用户名或密码错误")
    if not user.is_active:
        raise APIError(403, "USER_DISABLED", "账号已停用")
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise APIError(400, "BAD_OLD_PASSWORD", "当前密码不正确")
    if body.new_password == body.old_password:
        raise APIError(422, "SAME_PASSWORD", "新密码不能与当前密码相同")
    user.password_hash = hash_password(body.new_password)
    db.commit()
