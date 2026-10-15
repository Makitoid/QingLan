"""assignment pass score and redo windows (0.4.1 / F9)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # F9 及格线：可空 = 不设；SQLite 直接 ADD COLUMN 即可（无表级约束、存量行回填 NULL）
    op.add_column("assignments", sa.Column("pass_score", sa.Float()))

    # F9 打回重做：一个 (场次, 学生) 一行，重复打回只更新 deadline
    op.create_table(
        "assignment_retries",
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("deadline", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
    )
    op.create_index("idx_assignment_retries_student_deadline", "assignment_retries", ["student_id", "deadline"])


def downgrade():
    op.drop_index("idx_assignment_retries_student_deadline", table_name="assignment_retries")
    op.drop_table("assignment_retries")
    op.drop_column("assignments", "pass_score")
