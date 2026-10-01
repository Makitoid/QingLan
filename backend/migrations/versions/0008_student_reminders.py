"""student reminders (0.4.1 / F6)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    # F6 教师「提醒交作业」：学生登录后弹窗，read_at 非空即视为已读
    op.create_table(
        "student_reminders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("read_at", sa.Text()),
    )
    op.create_index("idx_student_reminders_student_read", "student_reminders", ["student_id", "read_at"])


def downgrade():
    op.drop_index("idx_student_reminders_student_read", table_name="student_reminders")
    op.drop_table("student_reminders")
