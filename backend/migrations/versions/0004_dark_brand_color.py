"""site settings: dark-mode brand color

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # 可空、无 server_default：NULL 即"暗色沿用 brand_color"，旧数据行为不变
    op.add_column("site_settings", sa.Column("brand_color_dark", sa.Text()))


def downgrade():
    op.drop_column("site_settings", "brand_color_dark")
