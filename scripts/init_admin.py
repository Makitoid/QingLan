import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


def main():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "admin").first()
        if existing:
            print("admin 账号已存在，跳过创建")
            return
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
            display_name="管理员",
        )
        db.add(admin)
        db.commit()
        print("已创建初始账号 admin/admin123，请首次登录后立即修改密码")
    finally:
        db.close()


if __name__ == "__main__":
    main()
