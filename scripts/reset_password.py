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
        db.commit()
        print(f"已重置用户 {username} 的密码")
    finally:
        db.close()


if __name__ == "__main__":
    main()
