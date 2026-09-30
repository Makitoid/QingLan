import os
import sys
import tempfile
from pathlib import Path

_TMP_DATA = tempfile.mkdtemp(prefix="qinglan-test-data-")
os.environ["DATA_DIR"] = _TMP_DATA

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.models import (Assignment, AssignmentProblem, Base, Problem,
                        SiteSetting, Submission, TestCase, User)
from app.services.audit import invalidate_audit_cache

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    invalidate_audit_cache()
    session = SessionLocal()
    session.add(SiteSetting(id=1, brand_color="#0F6CBD", bg_opacity=0.15))
    session.commit()
    yield session
    session.close()


def _add(db: Session, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# users.must_change_password 的列默认是 1（PW-01：新建账号首登强制改密）。
# 夹具账号是直接写库的测试数据，不该被 PW-02 的业务拦截挡住，所以显式置 0；
# 需要「未改密」状态时用 must_change_password=1 单独建。
@pytest.fixture()
def teacher(db):
    return _add(db, User(username="t001", password_hash="x", role="teacher",
                         display_name="王老师", must_change_password=0))


@pytest.fixture()
def student(db):
    return _add(db, User(username="s001", password_hash="x", role="student",
                         display_name="小明", must_change_password=0))


@pytest.fixture()
def problem(db, teacher):
    return _add(
        db,
        Problem(
            title="A+B",
            description="输入两个整数，输出它们的和。",
            input_format="一行两个整数 a b",
            output_format="一行一个整数",
            time_limit_ms=1000,
            memory_limit_mb=256,
            compare_mode="trim",
            created_by=teacher.id,
        ),
    )


@pytest.fixture()
def cases(db, problem):
    c1 = _add(db, TestCase(problem_id=problem.id, seq=1, input="1 2\n", expected="3\n", is_sample=1, weight=1))
    c2 = _add(db, TestCase(problem_id=problem.id, seq=2, input="3 4\n", expected="7\n", is_sample=0, weight=3))
    return [c1, c2]


@pytest.fixture()
def assignment(db, teacher, problem):
    a = _add(
        db,
        Assignment(
            title="作业1",
            mode="homework",
            start_time="2026-01-01 00:00:00",
            end_time="2027-01-01 00:00:00",
            score_policy="best",
            created_by=teacher.id,
        ),
    )
    _add(db, AssignmentProblem(assignment_id=a.id, problem_id=problem.id, seq=1, full_score=100.0))
    return a


def make_submission(db: Session, assignment, problem, student, code_text: str) -> Submission:
    return _add(
        db,
        Submission(
            assignment_id=assignment.id,
            problem_id=problem.id,
            user_id=student.id,
            code_text=code_text,
        ),
    )


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")
