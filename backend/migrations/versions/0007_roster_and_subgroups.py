"""teacher subgroups, assignment audience, teacher notices (0.3.2 / F1-1)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _assignments_table(include_audience_mode):
    """0007 前后 assignments 的完整形状，供 batch 重建当蓝本。

    SQLite 反射读不到 CHECK，不显式给出完整表定义的话，重建会把
    mode / score_policy 两条已有约束悄悄丢掉（models.py 里仍然声明着它们）。
    """
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Text(), nullable=False),
        sa.Column("end_time", sa.Text(), nullable=False),
        sa.Column("max_submissions", sa.Integer()),
        sa.Column("score_policy", sa.Text(), nullable=False, server_default=sa.text("'best'")),
        sa.Column("released", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("released_at", sa.Text()),
    ]
    constraints = [
        sa.CheckConstraint("mode IN ('homework','test')"),
        sa.CheckConstraint("score_policy IN ('best','last')"),
    ]
    if include_audience_mode:
        columns.append(
            sa.Column("audience_mode", sa.Text(), nullable=False, server_default=sa.text("'all'"))
        )
        constraints.append(
            sa.CheckConstraint("audience_mode IN ('all','subgroup')",
                               name="ck_assignments_audience_mode")
        )
    columns += [
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
    ]
    return sa.Table("assignments", sa.MetaData(), *(columns + constraints))


def upgrade():
    # F1 层 3 扩展：教师私有子分组，仅供教师自己组织发布受众
    op.create_table(
        "teacher_subgroups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.UniqueConstraint("teacher_id", "name"),
    )
    op.create_index("idx_teacher_subgroups_teacher", "teacher_subgroups", ["teacher_id"])

    op.create_table(
        "teacher_subgroup_members",
        sa.Column("subgroup_id", sa.Integer(), sa.ForeignKey("teacher_subgroups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_teacher_subgroup_members_student", "teacher_subgroup_members", ["student_id"])

    # F1 发布受众：存量场次一律 'all'（等价于升级前的全部名单），行为不变。
    # server_default 让重建时旧行自动回填，不需要额外 UPDATE。
    # recreate="always"：SQLite 只能靠重建表来补 CHECK 约束（直接 ADD COLUMN 写不进表级约束）。
    with op.batch_alter_table("assignments", copy_from=_assignments_table(False),
                              recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("audience_mode", sa.Text(), nullable=False, server_default=sa.text("'all'")),
            insert_before="created_by",
        )
        batch_op.create_check_constraint(
            "ck_assignments_audience_mode", "audience_mode IN ('all','subgroup')"
        )

    # F1 场次-子分组白名单：audience_mode = 'subgroup' 时生效
    op.create_table(
        "assignment_subgroups",
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("subgroup_id", sa.Integer(), sa.ForeignKey("teacher_subgroups.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_assignment_subgroups_subgroup", "assignment_subgroups", ["subgroup_id"])

    # F1 教师端一次性提示（如管理端撤销组别导致学生离开名单）
    op.create_table(
        "teacher_notices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text()),
        sa.Column("payload", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("dismissed_at", sa.Text()),
    )
    op.create_index("idx_teacher_notices_teacher_dismissed", "teacher_notices", ["teacher_id", "dismissed_at"])


def downgrade():
    op.drop_index("idx_teacher_notices_teacher_dismissed", table_name="teacher_notices")
    op.drop_table("teacher_notices")
    op.drop_index("idx_assignment_subgroups_subgroup", table_name="assignment_subgroups")
    op.drop_table("assignment_subgroups")

    # audience_mode 被 CHECK 引用，SQLite 不能直接 DROP COLUMN —— 只能重建表
    with op.batch_alter_table("assignments", copy_from=_assignments_table(True)) as batch_op:
        batch_op.drop_constraint("ck_assignments_audience_mode", type_="check")
        batch_op.drop_column("audience_mode")

    op.drop_index("idx_teacher_subgroup_members_student", table_name="teacher_subgroup_members")
    op.drop_table("teacher_subgroup_members")
    op.drop_index("idx_teacher_subgroups_teacher", table_name="teacher_subgroups")
    op.drop_table("teacher_subgroups")
