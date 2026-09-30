"""0.3.2 批次 A5（F7）· 学生端场次状态三态（ongoing / ending / ended）。

契约以代码实际行为为准（app/api/student.py::_assignment_state）：
- ``ended``：now > end_time；
- ``ending``：未结束且 end_time - now <= config.ENDING_SOON_HOURS；
- ``ongoing``：其余。
时间比较沿用 UTC 串字典序（坑 9），本文件用 ``datetime.now(timezone.utc)`` 造相对时间。
未开始的场次被 ``start_time <= now`` 过滤掉，不参与本文件断言。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.security import create_token
from app.main import app
from app.models import Assignment, TeacherStudent

ASSIGNMENTS = "/api/student/assignments"


def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def utc_from_now(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def seed_assignment(db, teacher, *, title, end_in_hours, start_in_hours=-24.0, mode="homework"):
    return _add(
        db,
        Assignment(
            title=title,
            mode=mode,
            start_time=utc_from_now(start_in_hours),
            end_time=utc_from_now(end_in_hours),
            score_policy="best",
            created_by=teacher.id,
        ),
    )


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def bound(db, teacher, student):
    return _add(db, TeacherStudent(teacher_id=teacher.id, student_id=student.id))


@pytest.fixture()
def h_student(student, bound):
    return bearer(student)


def states_by_title(resp) -> dict[str, str]:
    assert resp.status_code == 200
    return {a["title"]: a["state"] for a in resp.json()}


class TestAssignmentState:
    def test_ending_within_window(self, client, db, teacher, h_student):
        seed_assignment(db, teacher, title="快到期", end_in_hours=config.ENDING_SOON_HOURS - 1)
        assert states_by_title(client.get(ASSIGNMENTS, headers=h_student)) == {"快到期": "ending"}

    def test_ongoing_beyond_window(self, client, db, teacher, h_student):
        seed_assignment(db, teacher, title="还早", end_in_hours=config.ENDING_SOON_HOURS + 1)
        assert states_by_title(client.get(ASSIGNMENTS, headers=h_student)) == {"还早": "ongoing"}

    def test_ended_past_deadline(self, client, db, teacher, h_student):
        seed_assignment(db, teacher, title="已过期", end_in_hours=-1)
        assert states_by_title(client.get(ASSIGNMENTS, headers=h_student)) == {"已过期": "ended"}

    def test_three_states_in_one_response(self, client, db, teacher, h_student):
        seed_assignment(db, teacher, title="已过期", end_in_hours=-1)
        seed_assignment(db, teacher, title="快到期", end_in_hours=config.ENDING_SOON_HOURS - 1)
        seed_assignment(db, teacher, title="还早", end_in_hours=config.ENDING_SOON_HOURS + 1)
        assert states_by_title(client.get(ASSIGNMENTS, headers=h_student)) == {
            "已过期": "ended",
            "快到期": "ending",
            "还早": "ongoing",
        }

    def test_detail_endpoint_uses_same_state(self, client, db, teacher, h_student):
        a = seed_assignment(db, teacher, title="快到期", end_in_hours=config.ENDING_SOON_HOURS - 1)
        resp = client.get(f"{ASSIGNMENTS}/{a.id}", headers=h_student)
        assert resp.status_code == 200
        assert resp.json()["state"] == "ending"
