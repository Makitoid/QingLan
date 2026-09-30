"""password policy, audit log, three-layer binding (0.3.0 / M6)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # DM-01：存量账号一律下次登录强制改密（用户拍板：含 admin/教师/学生；
    # 系统尚未正式使用，存量多为测试数据，打扰成本≈0）。server_default 已回填 1，
    # 下面的 UPDATE 只是把这条拍板显式落到存量行上，防止不同方言下的回填差异。
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
    )
    op.execute("UPDATE users SET must_change_password = 1")
    # DM-05：随机临时密码 7 天过期的锚点；NULL = 不过期（统一/初始密码）
    op.add_column("users", sa.Column("password_updated_at", sa.Text()))

    # DM-03：手动调分时间，供审计与排查
    op.add_column("submissions", sa.Column("manual_score_updated_at", sa.Text()))

    # DM-04：层 2「组-教师分配」，admin 唯一写者
    op.create_table(
        "teacher_groups",
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
    )
    op.create_index("idx_teacher_groups_group", "teacher_groups", ["group_id"])

    # DM-02：只追加的审计日志；actor_id 不设 CASCADE，日志不可被级联清除
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Integer()),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
    )
    op.create_index("idx_audit_log_actor", "audit_log", ["actor_id"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])


def downgrade():
    op.drop_index("idx_audit_log_action", table_name="audit_log")
    op.drop_index("idx_audit_log_actor", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("idx_teacher_groups_group", table_name="teacher_groups")
    op.drop_table("teacher_groups")
    op.drop_column("submissions", "manual_score_updated_at")
    op.drop_column("users", "password_updated_at")
    op.drop_column("users", "must_change_password")
