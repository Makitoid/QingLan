import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


def main():
    if len(sys.argv) != 3:
        print("用法: python scripts/reset_password.py <username> <new_password>")
        sys.exit(1)
    username, new_password = sys.argv[1], sys.argv[2]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            print(f"用户不存在: {username}")
            sys.exit(1)
        user.password_hash = hash_password(new_password)
        # 运维兜底重置的是「管理员指定的密码」，因此强制本人下次登录改密；
        # password_updated_at 置 NULL 表示不走 PW-05 的 7 天过期（那是随机临时密码的规则）。
        user.must_change_password = 1
        user.password_updated_at = None
        db.commit()
        print(f"已重置用户 {username} 的密码，该账号下次登录将被强制改密")
    finally:
        db.close()


if __name__ == "__main__":
    main()
