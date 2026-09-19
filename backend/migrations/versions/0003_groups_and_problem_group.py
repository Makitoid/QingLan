"""student groups + problem group_name / draft columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # 分组定义：全站共享，name 唯一（≤50 字由应用层校验）
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.UniqueConstraint("name"),
    )
    # 多组模型：学生可属多个组，组/学生删除时级联清理成员关系
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_group_members_student", "group_members", ["student_id"])
    # group 是 SQL 保留字 → 列名 group_name；三列均可空，无需 server_default
    op.add_column("problems", sa.Column("group_name", sa.Text()))
    op.add_column("problems", sa.Column("draft", sa.Text()))
    op.add_column("problems", sa.Column("draft_saved_at", sa.Text()))


def downgrade():
    op.drop_column("problems", "draft_saved_at")
    op.drop_column("problems", "draft")
    op.drop_column("problems", "group_name")
    op.drop_index("idx_group_members_student", table_name="group_members")
    op.drop_table("group_members")
    op.drop_table("groups")
