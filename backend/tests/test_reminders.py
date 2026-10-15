"""0.4.1 F6：教师「提醒交作业」与学生端未读提醒。

契约以代码实际行为为准（app/api/teacher.py::remind_assignment_students、
app/api/student.py::list_reminders / dismiss_reminder、app/models.py::StudentReminder）：
- ``POST /api/teacher/assignments/{id}/remind`` body ``{student_ids}`` → ``{created, skipped}``；
  受众必须是本场次的学生（可教组并集 ∪ 手动添加，再按 audience_mode 收窄），
  否则整批 422 ``INVALID_STUDENT_IDS``；空选择 422 ``EMPTY_SELECTION``；非自己的场次 403。
- 幂等：同一 (场次, 学生) 已有**未读**提醒时不再插行，计入 skipped。
- ``GET /api/student/reminders`` 只给未读，按时间正序；``POST /api/student/reminders/{id}/dismiss``
  标记已读，别人的提醒 404 ``REMINDER_NOT_FOUND``。
- 审计（AU-04）：一次提醒一条 ``assignment_remind``，target_type=assignment。
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_token, utcnow_str
from app.main import app
from app.models import (Assignment, AuditLog, StudentReminder, TeacherStudent,
                        User)

REMIND_URL = "/api/teacher/assignments/{aid}/remind"
STUDENT_REMINDERS = "/api/student/reminders"


def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def code_of(resp):
    return resp.json().get("code")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def teacher(db):
    return _add(db, User(username="t600", password_hash="x", role="teacher",
                         display_name="王老师", must_change_password=0))


@pytest.fixture()
def other_teacher(db):
    return _add(db, User(username="t601", password_hash="x", role="teacher",
                         display_name="李老师", must_change_password=0))


@pytest.fixture()
def students(db):
    return [
        _add(db, User(username=f"s6{i}", password_hash="x", role="student",
                      display_name=f"学生{i}", must_change_password=0))
        for i in (1, 2)
    ]


@pytest.fixture()
def assignment(db, teacher):
    return _add(db, Assignment(title="期中测评", mode="test",
                               start_time="2026-01-01 08:00:00",
                               end_time="2026-12-31 18:00:00", created_by=teacher.id))


@pytest.fixture()
def roster(db, teacher, students):
    """把两名学生手动加进教师名单（层 3），即场次默认可见的受众。"""
    for s in students:
        db.add(TeacherStudent(teacher_id=teacher.id, student_id=s.id))
    db.commit()
    return students


def remind(client, teacher, assignment, ids):
    return client.post(REMIND_URL.format(aid=assignment.id), headers=bearer(teacher),
                       json={"student_ids": ids})


# ------------------------------------------------------ 教师侧：建提醒

class TestCreateReminder:
    def test_creates_one_row_per_student(self, db, client, teacher, assignment, roster):
        resp = remind(client, teacher, assignment, [s.id for s in roster])
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"created": 2, "skipped": 0}
        db.expire_all()
        rows = db.query(StudentReminder).all()
        assert len(rows) == 2
        assert {r.student_id for r in rows} == {s.id for s in roster}
        assert {r.assignment_id for r in rows} == {assignment.id}
        assert all(r.teacher_id == teacher.id and r.read_at is None for r in rows)

    def test_repeat_remind_is_idempotent_until_read(self, db, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [roster[0].id])
        second = remind(client, teacher, assignment, [roster[0].id])
        assert second.json() == {"created": 0, "skipped": 1}
        db.expire_all()
        assert db.query(StudentReminder).count() == 1

    def test_duplicate_ids_in_one_call_count_once(self, client, teacher, assignment, roster):
        sid = roster[0].id
        assert remind(client, teacher, assignment, [sid, sid]).json() == {"created": 1, "skipped": 0}

    def test_audience_only(self, db, client, teacher, assignment, roster, students):
        outsider = _add(db, User(username="s6out", password_hash="x", role="student",
                                 display_name="旁听生", must_change_password=0))
        resp = remind(client, teacher, assignment, [roster[0].id, outsider.id])
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "INVALID_STUDENT_IDS"
        db.expire_all()
        # 整批拒绝：合法的同行也不落库
        assert db.query(StudentReminder).count() == 0

    def test_empty_selection(self, client, teacher, assignment):
        resp = remind(client, teacher, assignment, [])
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "EMPTY_SELECTION"

    def test_only_own_assignment(self, client, teacher, other_teacher, assignment, roster):
        resp = remind(client, other_teacher, assignment, [roster[0].id])
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "FORBIDDEN"

    def test_requires_teacher(self, client, assignment, roster, students):
        resp = client.post(REMIND_URL.format(aid=assignment.id), headers=bearer(students[0]),
                           json={"student_ids": [roster[0].id]})
        assert resp.status_code == 403, resp.text
        assert client.post(REMIND_URL.format(aid=assignment.id),
                           json={"student_ids": []}).status_code == 401

    def test_one_audit_row_per_call(self, db, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [s.id for s in roster])
        db.expire_all()
        rows = db.query(AuditLog).filter(AuditLog.action == "assignment_remind").all()
        assert len(rows) == 1
        assert rows[0].target_type == "assignment" and rows[0].target_id == assignment.id
        assert f'"count": {len(roster)}' in rows[0].detail


# ------------------------------------------------------ 学生侧：读与确认

class TestStudentSide:
    def test_pending_list_shape(self, client, teacher, assignment, roster, students):
        remind(client, teacher, assignment, [roster[0].id])
        resp = client.get(STUDENT_REMINDERS, headers=bearer(roster[0]))
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) == 1
        item = items[0]
        assert item["assignment_id"] == assignment.id
        assert item["assignment_title"] == "期中测评"
        assert item["assignment_mode"] == "test"
        assert item["end_time"] == "2026-12-31 18:00:00"
        assert item["teacher_name"] == "王老师"

    def test_other_student_sees_nothing(self, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [roster[0].id])
        assert client.get(STUDENT_REMINDERS, headers=bearer(roster[1])).json() == []

    def test_order_is_oldest_first(self, db, client, teacher, students, roster):
        first = _add(db, Assignment(title="早的", mode="homework", start_time="2026-01-01 08:00:00",
                                    end_time="2026-02-01 18:00:00", created_by=teacher.id))
        second = _add(db, Assignment(title="晚的", mode="homework", start_time="2026-01-01 08:00:00",
                                     end_time="2026-03-01 18:00:00", created_by=teacher.id))
        # created_at 是秒级文本，同秒时按 id 兜底，所以先插的排前面
        remind(client, teacher, first, [roster[0].id])
        remind(client, teacher, second, [roster[0].id])
        titles = [i["assignment_title"] for i in
                  client.get(STUDENT_REMINDERS, headers=bearer(roster[0])).json()]
        assert titles == ["早的", "晚的"]

    def test_dismiss_removes_it_from_pending(self, db, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [roster[0].id])
        reminder = client.get(STUDENT_REMINDERS, headers=bearer(roster[0])).json()[0]
        assert reminder["created_at"] <= utcnow_str()

        resp = client.post(f"{STUDENT_REMINDERS}/{reminder['id']}/dismiss", headers=bearer(roster[0]))
        assert resp.status_code == 200, resp.text
        assert client.get(STUDENT_REMINDERS, headers=bearer(roster[0])).json() == []
        db.expire_all()
        assert db.get(StudentReminder, reminder["id"]).read_at is not None

        # 已读之后再点一次仍然成功（幂等），且不会重新出现在未读里
        assert client.post(f"{STUDENT_REMINDERS}/{reminder['id']}/dismiss",
                           headers=bearer(roster[0])).status_code == 200

    def test_dismiss_is_per_student(self, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [roster[0].id])
        reminder = client.get(STUDENT_REMINDERS, headers=bearer(roster[0])).json()[0]
        resp = client.post(f"{STUDENT_REMINDERS}/{reminder['id']}/dismiss", headers=bearer(roster[1]))
        assert resp.status_code == 404, resp.text
        assert code_of(resp) == "REMINDER_NOT_FOUND"
        # 别人的越权尝试不会把提醒标成已读
        assert len(client.get(STUDENT_REMINDERS, headers=bearer(roster[0])).json()) == 1

    def test_requires_student(self, client, teacher):
        assert client.get(STUDENT_REMINDERS, headers=bearer(teacher)).status_code == 403
        assert client.get(STUDENT_REMINDERS).status_code == 401


# ------------------------------------------------------ 级联

class TestCascade:
    def test_reminders_follow_assignment(self, db, client, teacher, assignment, roster):
        remind(client, teacher, assignment, [roster[0].id])
        db.expire_all()
        assert db.query(StudentReminder).count() == 1
        db.delete(db.get(Assignment, assignment.id))
        db.commit()
        db.expire_all()
        assert db.query(StudentReminder).count() == 0
