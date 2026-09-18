"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.UniqueConstraint("username"),
        sa.CheckConstraint("role IN ('admin','teacher','student')"),
    )
    op.create_table(
        "teacher_students",
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_format", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False, server_default=sa.text("1000")),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False, server_default=sa.text("256")),
        sa.Column("compare_mode", sa.Text(), nullable=False, server_default=sa.text("'trim'")),
        sa.Column("float_eps", sa.Float()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint("compare_mode IN ('exact','trim','float')"),
    )
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("is_sample", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("weight", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("problem_id", "seq"),
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Text(), nullable=False),
        sa.Column("end_time", sa.Text(), nullable=False),
        sa.Column("max_submissions", sa.Integer()),
        sa.Column("score_policy", sa.Text(), nullable=False, server_default=sa.text("'best'")),
        sa.Column("released", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("released_at", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint("mode IN ('homework','test')"),
        sa.CheckConstraint("score_policy IN ('best','last')"),
    )
    op.create_table(
        "assignment_problems",
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id"), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("full_score", sa.Float(), nullable=False, server_default=sa.text("100")),
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("verdict", sa.Text()),
        sa.Column("score", sa.Float()),
        sa.Column("manual_score", sa.Float()),
        sa.Column("worker_id", sa.Text()),
        sa.Column("judge_log", sa.Text()),
        sa.Column("submitted_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("judged_at", sa.Text()),
        sa.CheckConstraint("status IN ('pending','judging','done','failed')"),
    )
    op.create_index("idx_sub_pending", "submissions", ["status", "id"])
    op.create_index("idx_sub_query", "submissions", ["assignment_id", "problem_id", "user_id"])
    op.create_table(
        "submission_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_cases.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("memory_kb", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.UniqueConstraint("submission_id", "test_case_id"),
    )
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand_color", sa.Text(), nullable=False, server_default=sa.text("'#0F6CBD'")),
        sa.Column("bg_image_path", sa.Text()),
        sa.Column("bg_opacity", sa.Float(), nullable=False, server_default=sa.text("0.15")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("bg_opacity >= 0 AND bg_opacity <= 1"),
    )
    op.execute("INSERT INTO site_settings (id) VALUES (1)")


def downgrade():
    op.drop_table("site_settings")
    op.drop_table("submission_results")
    op.drop_index("idx_sub_query", table_name="submissions")
    op.drop_index("idx_sub_pending", table_name="submissions")
    op.drop_table("submissions")
    op.drop_table("assignment_problems")
    op.drop_table("assignments")
    op.drop_table("test_cases")
    op.drop_table("problems")
    op.drop_table("teacher_students")
    op.drop_table("users")
