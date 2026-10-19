import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core import config
from app.core.db import SessionLocal
from app.core.security import WEAK_PASSWORDS, generate_temp_password, hash_password, utcnow_str
from app.models import User


def _initial_password() -> tuple[str, bool]:
    """H-01：管理员初始口令。

    - `ADMIN_INITIAL_PASSWORD` 显式提供时优先使用（便于受控部署）；
    - 本机开发（APP_ENV=dev）沿用文档里的 admin123，保持一键脚本体验；
    - 其它环境随机生成、只在首次创建时打印一次，避免出厂默认口令长期有效。
    返回 (口令, 是否为自动生成的临时口令)。
    """
    configured = (os.environ.get("ADMIN_INITIAL_PASSWORD") or "").strip()
    if configured:
        if configured.lower() in WEAK_PASSWORDS or len(configured) < 8:
            print("[init_admin] 警告：ADMIN_INITIAL_PASSWORD 较弱，仅建议在受控的内网环境使用",
                  file=sys.stderr)
        return configured, False
    if config.IS_DEV:
        return "admin123", False
    return generate_temp_password(), True


def main():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "admin").first()
        if existing:
            # 关键：绝不覆盖已存在账号的口令——否则每次容器启动都会把
            # 管理员改过的密码重置回出厂值。
            print("admin 账号已存在，跳过创建")
            return
        password, generated = _initial_password()
        admin = User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
            display_name="管理员",
            # PW-01：种子 admin 同样首登强制改密
            must_change_password=1,
            # 自动生成的临时口令沿用 7 天过期；显式配置/开发默认值不过期
            password_updated_at=utcnow_str() if generated else None,
        )
        db.add(admin)
        db.commit()
        if generated:
            print(f"已创建初始账号 admin/{password}（随机临时口令，仅显示这一次，7 天内须登录改密）")
        else:
            print(f"已创建初始账号 admin/{password}，首次登录会被强制修改密码")
    finally:
        db.close()


if __name__ == "__main__":
    main()
