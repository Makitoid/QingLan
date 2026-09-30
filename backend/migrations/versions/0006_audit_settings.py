"""audit settings on site_settings (0.3.2 / F5-1)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    # F5：审计总开关。server_default 让存量单行回填 1 —— 与升级前「一直在写日志」
    # 的行为一致，不需要额外的 UPDATE 兜底（对照 0005 对 must_change_password 的处理）。
    op.add_column(
        "site_settings",
        sa.Column("audit_enabled", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
    )
    # F5：保留天数；可空、无 server_default —— NULL 即"永久保存"，旧数据行为不变
    op.add_column("site_settings", sa.Column("audit_retention_days", sa.Integer()))


def downgrade():
    op.drop_column("site_settings", "audit_retention_days")
    op.drop_column("site_settings", "audit_enabled")
