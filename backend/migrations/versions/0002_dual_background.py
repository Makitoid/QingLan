"""site settings: dual-mode background + brand color source

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # 带 server_default 才能给已有的单行数据补上合法值
    op.add_column("site_settings", sa.Column("brand_color_source", sa.Text(), nullable=False, server_default=sa.text("'manual'")))
    op.add_column("site_settings", sa.Column("bg_image_path_dark", sa.Text()))
    op.add_column("site_settings", sa.Column("bg_dual", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade():
    op.drop_column("site_settings", "bg_dual")
    op.drop_column("site_settings", "bg_image_path_dark")
    op.drop_column("site_settings", "brand_color_source")
