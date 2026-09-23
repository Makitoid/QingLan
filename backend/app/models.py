from sqlalchemy import (CheckConstraint, Column, ForeignKey, Index, Integer,
                        Text, UniqueConstraint, text)
from sqlalchemy import Float
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','teacher','student')"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    # PW-01/02：新建与重置后一律 1，首登被强制改密（前端路由级 + 后端 API 拦截）
    must_change_password = Column(Integer, nullable=False, server_default=text("1"))
    # PW-05：随机临时密码 7 天过期的唯一锚点；NULL = 不过期（统一/初始密码、自助改密后）
    password_updated_at = Column(Text)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class TeacherStudent(Base):
    __tablename__ = "teacher_students"

    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Group(Base):
    """学生分组（班级/群组），全站共享，管理员维护。"""

    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class GroupMember(Base):
    """多组模型：一个学生可属于多个组。"""

    __tablename__ = "group_members"
    __table_args__ = (Index("idx_group_members_student", "student_id"),)

    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class TeacherGroup(Base):
    """层 2「组-教师分配」（BD-02）：谁可教哪个行政班，唯一写者是 admin。"""

    __tablename__ = "teacher_groups"
    __table_args__ = (Index("idx_teacher_groups_group", "group_id"),)

    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (CheckConstraint("compare_mode IN ('exact','trim','float')"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    input_format = Column(Text, nullable=False)
    output_format = Column(Text, nullable=False)
    time_limit_ms = Column(Integer, nullable=False, server_default=text("1000"))
    memory_limit_mb = Column(Integer, nullable=False, server_default=text("256"))
    compare_mode = Column(Text, nullable=False, server_default=text("'trim'"))
    float_eps = Column(Float)
    # group 是 SQL 保留字，列名用 group_name（自由文本，可空）
    group_name = Column(Text)
    draft = Column(Text)
    draft_saved_at = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("problem_id", "seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    input = Column(Text, nullable=False)
    expected = Column(Text, nullable=False)
    is_sample = Column(Integer, nullable=False, server_default=text("0"))
    weight = Column(Integer, nullable=False, server_default=text("1"))


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("mode IN ('homework','test')"),
        CheckConstraint("score_policy IN ('best','last')"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    start_time = Column(Text, nullable=False)
    end_time = Column(Text, nullable=False)
    max_submissions = Column(Integer)
    score_policy = Column(Text, nullable=False, server_default=text("'best'"))
    released = Column(Integer, nullable=False, server_default=text("0"))
    released_at = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class AssignmentProblem(Base):
    __tablename__ = "assignment_problems"

    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), primary_key=True)
    seq = Column(Integer, nullable=False)
    full_score = Column(Float, nullable=False, server_default=text("100"))


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint("status IN ('pending','judging','done','failed')"),
        Index("idx_sub_pending", "status", "id"),
        Index("idx_sub_query", "assignment_id", "problem_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code_text = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default=text("'pending'"))
    verdict = Column(Text)
    score = Column(Float)
    manual_score = Column(Float)
    manual_score_updated_at = Column(Text)
    worker_id = Column(Text)
    judge_log = Column(Text)
    submitted_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))
    judged_at = Column(Text)


class SubmissionResult(Base):
    __tablename__ = "submission_results"
    __table_args__ = (UniqueConstraint("submission_id", "test_case_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    verdict = Column(Text, nullable=False)
    time_ms = Column(Integer, nullable=False)
    memory_kb = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)


class AuditLog(Base):
    """只追加的操作台账（AU-01~05）：不提供任何 UPDATE/DELETE 路径。

    actor_id 有意不设 CASCADE —— 系统从不删用户，但即使删了也不能级联清除日志。
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_actor", "actor_id"),
        Index("idx_audit_log_action", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey("users.id"))
    action = Column(Text, nullable=False)
    target_type = Column(Text, nullable=False)
    target_id = Column(Integer)
    detail = Column(Text)
    created_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))


class SiteSetting(Base):
    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("id = 1"),
        CheckConstraint("bg_opacity >= 0 AND bg_opacity <= 1"),
    )

    id = Column(Integer, primary_key=True)
    brand_color = Column(Text, nullable=False, server_default=text("'#0F6CBD'"))
    # 暗色模式专属品牌色；为空表示暗色沿用 brand_color
    brand_color_dark = Column(Text)
    brand_color_source = Column(Text, nullable=False, server_default=text("'manual'"))
    bg_image_path = Column(Text)
    bg_image_path_dark = Column(Text)
    bg_dual = Column(Integer, nullable=False, server_default=text("0"))
    bg_opacity = Column(Float, nullable=False, server_default=text("0.15"))
    # 审计总开关（0.3.2 F5）；关闭只停写新日志，历史日志保留
    audit_enabled = Column(Integer, nullable=False, server_default=text("1"))
    # 审计保留天数（0.3.2 F5）；NULL = 永久保存，清理任务跳过
    audit_retention_days = Column(Integer)
    updated_by = Column(Integer, ForeignKey("users.id"))
    updated_at = Column(Text, nullable=False, server_default=text("(datetime('now'))"))
