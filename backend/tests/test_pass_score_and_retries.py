"""0.4.1 F9：及格线 + 打回重做。

契约以代码实际行为为准（app/api/teacher.py 的 pass_score 与 retry 两端点、
app/api/student.py 的 ``_assignment_state`` / ``create_submission``、
app/services/retries.py、app/models.py::AssignmentRetry）：

- ``Assignment.pass_score``：绝对分，NULL = 不判及格线；设值必须 ≤ 本场满分，
  否则 422 ``PASS_SCORE_OUT_OF_RANGE``。``PUT`` 走 ``exclude_unset``，不传 = 不改，
  显式传 null 才清空。
- ``POST /api/teacher/assignments/{id}/retry`` body ``{student_ids, deadline}``
  → ``{created, updated, student_ids}``；``student_ids`` 为空 = 服务端按及格线
  自动挑不及格学生（没设及格线则 422 ``PASS_SCORE_MISSING``）。
  deadline 必须晚于场次 ``end_time``（422 ``RETRY_DEADLINE_TOO_EARLY``），
  学生必须在场次受众里（422 ``INVALID_STUDENT_IDS``）。
  复合主键幂等：重复打回只更新期限，``updated`` 计数。
- ``DELETE /api/teacher/assignments/{id}/retry/{student_id}`` 撤销；没有该行 404
  ``RETRY_NOT_FOUND``。
- 学生端：``state`` 多一个取值 ``'retry'``（原窗口已关、重做期限内），
  ``retry_deadline`` / ``pass_score`` 随行下发；重做期内提交不受 ``max_submissions``
  限制，超过 deadline 后 ``WINDOW_CLOSED``。
- 审计：一次打回一条 ``assignment_retry``，撤销一条 ``assignment_retry_cancel``。
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_token
from app.main import app
from app.models import (Assignment, AssignmentProblem, AssignmentRetry, AuditLog,
                        Problem, Submission, TeacherStudent, User)
from app.services import retries as retries_svc

RETRY_URL = "/api/teacher/assignments/{aid}/retry"
STUDENT_ASSIGNMENTS = "/api/student/assignments"
SUBMIT_URL = "/api/student/assignments/{aid}/problems/{pid}/submissions"


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
    return _add(db, User(username="t700", password_hash="x", role="teacher",
                         display_name="王老师", must_change_password=0))


@pytest.fixture()
def other_teacher(db):
    return _add(db, User(username="t701", password_hash="x", role="teacher",
                         display_name="李老师", must_change_password=0))


@pytest.fixture()
def students(db):
    return [
        _add(db, User(username=f"s7{i}", password_hash="x", role="student",
                      display_name=f"学生{i}", must_change_password=0))
        for i in (1, 2, 3)
    ]


@pytest.fixture()
def problem(db, teacher):
    return _add(db, Problem(title="A+B", description="d", input_format="i",
                            output_format="o", created_by=teacher.id))


@pytest.fixture()
def assignment(db, teacher, problem):
    """一个 100 满分的场次，窗口整体落在过去，方便测重做窗口。"""
    a = _add(db, Assignment(title="期中", mode="test", start_time="2026-01-01 00:00:00",
                            end_time="2026-01-02 00:00:00", created_by=teacher.id,
                            max_submissions=2))
    _add(db, AssignmentProblem(assignment_id=a.id, problem_id=problem.id, seq=1, full_score=100))
    return a


@pytest.fixture()
def audience(db, teacher, students):
    for s in students:
        db.add(TeacherStudent(teacher_id=teacher.id, student_id=s.id))
    db.commit()
    return students


def submit(client, student, aid, pid, code="int main(){}"):
    return client.post(SUBMIT_URL.format(aid=aid, pid=pid), headers=bearer(student),
                       json={"code_text": code})


def score(db, assignment, student, problem, value):
    """造一条已判完的提交，用来决定该生的总分。"""
    return _add(db, Submission(assignment_id=assignment.id, problem_id=problem.id,
                               user_id=student.id, code_text="x", status="done",
                               verdict="AC", score=value, submitted_at="2026-01-01 10:00:00"))


# ------------------------------------------------------ 及格线

class TestPassScore:
    def test_roundtrip_through_create_and_get(self, db, client, teacher, problem):
        resp = client.post("/api/teacher/assignments", headers=bearer(teacher), json={
            "title": "带及格线", "mode": "homework",
            "start_time": "2026-01-01 00:00:00", "end_time": "2026-01-02 00:00:00",
            "problems": [{"problem_id": problem.id, "seq": 1, "full_score": 100}],
            "pass_score": 60,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pass_score"] == 60
        got = client.get(f"/api/teacher/assignments/{body['id']}", headers=bearer(teacher))
        assert got.json()["pass_score"] == 60

    def test_absent_means_null(self, client, teacher, problem):
        resp = client.post("/api/teacher/assignments", headers=bearer(teacher), json={
            "title": "不设线", "mode": "homework",
            "start_time": "2026-01-01 00:00:00", "end_time": "2026-01-02 00:00:00",
            "problems": [{"problem_id": problem.id, "seq": 1, "full_score": 100}],
        })
        assert resp.json()["pass_score"] is None

    def test_above_full_score_is_422(self, client, teacher, problem):
        resp = client.post("/api/teacher/assignments", headers=bearer(teacher), json={
            "title": "超线", "mode": "homework",
            "start_time": "2026-01-01 00:00:00", "end_time": "2026-01-02 00:00:00",
            "problems": [{"problem_id": problem.id, "seq": 1, "full_score": 50}],
            "pass_score": 60,
        })
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "PASS_SCORE_OUT_OF_RANGE"

    def test_update_keeps_clears_and_revalidates(self, db, client, teacher, problem):
        """及格线只能在开赛前改，所以这个用例自己造一个未来的场次。"""
        a = _add(db, Assignment(title="未开始", mode="homework",
                                start_time="2999-01-01 00:00:00", end_time="2999-01-02 00:00:00",
                                created_by=teacher.id))
        _add(db, AssignmentProblem(assignment_id=a.id, problem_id=problem.id, seq=1, full_score=100))
        url = f"/api/teacher/assignments/{a.id}"

        ok = client.put(url, headers=bearer(teacher), json={"pass_score": 70})
        assert ok.status_code == 200, ok.text
        assert ok.json()["pass_score"] == 70
        # 不传 = 保持原值
        assert client.put(url, headers=bearer(teacher), json={"title": "改标题"}).json()["pass_score"] == 70
        # 显式 null = 清空
        assert client.put(url, headers=bearer(teacher), json={"pass_score": None}).json()["pass_score"] is None
        too_big = client.put(url, headers=bearer(teacher), json={"pass_score": 500})
        assert too_big.status_code == 422, too_big.text
        assert code_of(too_big) == "PASS_SCORE_OUT_OF_RANGE"
        db.expire_all()
        assert db.get(Assignment, a.id).pass_score is None


# ------------------------------------------------------ 不及格判定

class TestFailedDetection:
    def test_only_submitted_and_below_line(self, db, assignment, problem, students):
        score(db, assignment, students[0], problem, 40)   # 不及格
        score(db, assignment, students[1], problem, 80)   # 及格
        # students[2] 未交 → 不归打回管，归 F6 提醒管
        rows = [
            {"student_id": s.id, "submitted_count": 1 if i < 2 else 0,
             "total_score": v}
            for i, (s, v) in enumerate(zip(students, [40, 80, None]))
        ]
        assert retries_svc.failed_student_ids(rows, 60) == [students[0].id]
        assert retries_svc.failed_student_ids(rows, None) == []
        # 恰好等于及格线算及格
        assert retries_svc.failed_student_ids(
            [{"student_id": 1, "submitted_count": 1, "total_score": 60}], 60) == []


# ------------------------------------------------------ 打回 / 撤销

class TestRetry:
    def test_explicit_ids_create_one_row_each(self, db, client, teacher, assignment, audience):
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"student_ids": [audience[0].id], "deadline": "2026-06-01 00:00:00"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"created": 1, "updated": 0, "student_ids": [audience[0].id]}
        db.expire_all()
        row = db.get(AssignmentRetry, (assignment.id, audience[0].id))
        assert row.deadline == "2026-06-01 00:00:00" and row.created_by == teacher.id

    def test_repeat_updates_deadline_instead_of_duplicating(self, db, client, teacher, assignment, audience):
        sid = audience[0].id
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [sid], "deadline": "2026-06-01 00:00:00"})
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"student_ids": [sid], "deadline": "2026-09-01 00:00:00"})
        assert resp.json() == {"created": 0, "updated": 1, "student_ids": [sid]}
        db.expire_all()
        assert db.query(AssignmentRetry).count() == 1
        assert db.get(AssignmentRetry, (assignment.id, sid)).deadline == "2026-09-01 00:00:00"

    def test_empty_selection_auto_picks_failing_students(self, db, client, teacher, assignment,
                                                        problem, audience):
        db.execute(Assignment.__table__.update().where(Assignment.id == assignment.id)
                   .values(pass_score=60))
        db.commit()
        score(db, assignment, audience[0], problem, 30)
        score(db, assignment, audience[1], problem, 90)
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"deadline": "2026-06-01 00:00:00"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["student_ids"] == [audience[0].id]
        assert resp.json()["created"] == 1

    def test_auto_pick_needs_a_pass_score(self, client, teacher, assignment):
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"deadline": "2026-06-01 00:00:00"})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "PASS_SCORE_MISSING"

    def test_deadline_must_be_after_assignment_end(self, client, teacher, assignment, audience):
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"student_ids": [audience[0].id],
                                 "deadline": "2026-01-01 12:00:00"})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "RETRY_DEADLINE_TOO_EARLY"

    def test_audience_only(self, db, client, teacher, assignment, audience, other_teacher):
        outsider = _add(db, User(username="s7out", password_hash="x", role="student",
                                 display_name="旁听", must_change_password=0))
        resp = client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                           json={"student_ids": [audience[0].id, outsider.id],
                                 "deadline": "2026-06-01 00:00:00"})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "INVALID_STUDENT_IDS"
        db.expire_all()
        assert db.query(AssignmentRetry).count() == 0

    def test_only_own_assignment_and_teacher_only(self, client, teacher, other_teacher, assignment, audience):
        body = {"student_ids": [audience[0].id], "deadline": "2026-06-01 00:00:00"}
        assert code_of(client.post(RETRY_URL.format(aid=assignment.id),
                                   headers=bearer(other_teacher), json=body)) == "FORBIDDEN"
        assert client.post(RETRY_URL.format(aid=assignment.id),
                           headers=bearer(audience[0]), json=body).status_code == 403

    def test_cancel(self, db, client, teacher, assignment, audience):
        sid = audience[0].id
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [sid], "deadline": "2026-06-01 00:00:00"})
        url = f"{RETRY_URL.format(aid=assignment.id)}/{sid}"
        assert client.delete(url, headers=bearer(teacher)).status_code == 200
        db.expire_all()
        assert db.query(AssignmentRetry).count() == 0
        missing = client.delete(url, headers=bearer(teacher))
        assert missing.status_code == 404, missing.text
        assert code_of(missing) == "RETRY_NOT_FOUND"

    def test_audit_rows(self, db, client, teacher, assignment, audience):
        sid = audience[0].id
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [sid], "deadline": "2026-06-01 00:00:00"})
        client.delete(f"{RETRY_URL.format(aid=assignment.id)}/{sid}", headers=bearer(teacher))
        db.expire_all()
        actions = [(r.action, r.target_type, r.target_id)
                   for r in db.query(AuditLog).filter(
                       AuditLog.action.like("assignment_retry%")).all()]
        assert actions == [("assignment_retry", "assignment", assignment.id),
                           ("assignment_retry_cancel", "assignment", assignment.id)]


# ------------------------------------------------------ 学生端窗口

class TestStudentWindow:
    def test_state_is_retry_until_deadline(self, db, client, teacher, assignment, audience):
        sid = audience[0].id
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [sid], "deadline": "2999-01-01 00:00:00"})
        items = client.get(STUDENT_ASSIGNMENTS, headers=bearer(audience[0])).json()
        mine = next(x for x in items if x["id"] == assignment.id)
        assert mine["state"] == "retry"
        assert mine["retry_deadline"] == "2999-01-01 00:00:00"
        # 没被打回的同班学生看到的仍是 ended，也没有 retry_deadline
        other = next(x for x in client.get(STUDENT_ASSIGNMENTS, headers=bearer(audience[1])).json()
                     if x["id"] == assignment.id)
        assert other["state"] == "ended" and other["retry_deadline"] is None

    def test_pass_score_is_downstreamed(self, db, client, assignment, audience):
        db.execute(Assignment.__table__.update().where(Assignment.id == assignment.id)
                   .values(pass_score=60))
        db.commit()
        item = next(x for x in client.get(STUDENT_ASSIGNMENTS, headers=bearer(audience[0])).json()
                    if x["id"] == assignment.id)
        assert item["pass_score"] == 60

    def test_submit_allowed_after_end_during_retry(self, db, client, teacher, assignment,
                                                  problem, audience):
        sid = audience[0].id
        # 先把 max_submissions=2 用满（场次已结束，走接口交不了，直接造已判完的行）
        score(db, assignment, audience[0], problem, 50)
        score(db, assignment, audience[0], problem, 50)
        assert code_of(submit(client, audience[0], assignment.id, problem.id)) == "WINDOW_CLOSED"

        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [sid], "deadline": "2999-01-01 00:00:00"})
        # 场次已结束 + 次数早已超上限，重做期内仍放行
        assert submit(client, audience[0], assignment.id, problem.id).status_code == 200

        # 没被打回的同学依旧进不来
        assert code_of(submit(client, audience[1], assignment.id, problem.id)) == "WINDOW_CLOSED"

    def test_submit_blocked_after_retry_deadline(self, db, client, teacher, assignment,
                                                 problem, audience):
        # deadline 已过（场次结束时间之后、但同样是过去）→ 依旧关闭
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [audience[0].id], "deadline": "2026-01-03 00:00:00"})
        assert code_of(submit(client, audience[0], assignment.id, problem.id)) == "WINDOW_CLOSED"

    def test_retries_follow_assignment_delete(self, db, client, teacher, assignment, audience):
        client.post(RETRY_URL.format(aid=assignment.id), headers=bearer(teacher),
                    json={"student_ids": [audience[0].id], "deadline": "2999-01-01 00:00:00"})
        db.expire_all()
        assert db.query(AssignmentRetry).count() == 1
        db.delete(db.get(Assignment, assignment.id))
        db.commit()
        db.expire_all()
        assert db.query(AssignmentRetry).count() == 0
