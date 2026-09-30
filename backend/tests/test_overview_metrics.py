"""0.4.0 F4：总览页的班级总分指标。

契约以 ``app/services/stats.py::overview`` 为准（``GET /api/teacher/assignments/{id}/overview``）：

- **总分口径**：每人总分 = 题单内每题 ``scoring.aggregate_scores`` 有效分之和，
  未交（或全未判分）的题按 0 计入 —— 与 ``student_rows`` 的 ``total_score`` 共用
  ``_total_score``，所以两个接口的数字必须逐人相等（本文件对此有专门断言）。
- ``full_score_sum`` = Σ ``assignment_problems.full_score``；**及格线 = 0.6 * full_score_sum**（含边界）。
- ``pass_rate`` 的分母是 ``total_students``（受众学生全量，未交按 0 分自然不及格），round 4 位；
  ``avg_total_score`` round 1 位；``max_total_score`` / ``min_total_score`` 为 float。
- 受众为空时返回中性值：``avg_total_score`` 0.0、``pass_rate`` 0.0、``max/min`` 为 ``None``，
  ``full_score_sum`` 仍是题单满分和（与有没有人答题无关）。
- ``histogram`` 十桶仍是「单题有效分」口径，F4 不改。
"""
from fastapi.testclient import TestClient
import pytest

from app.core.security import create_token
from app.main import app
from app.models import AssignmentProblem, Problem, Submission, TeacherStudent, User

from .conftest import make_submission


def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def seed_students(db, n, *, teacher):
    users = [
        User(username=f"ov{i}", password_hash="x", role="student",
             display_name=f"学生ov{i}", must_change_password=0)
        for i in range(1, n + 1)
    ]
    db.add_all(users)
    db.commit()
    for user in users:
        db.refresh(user)
    for user in users:
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=user.id))
    return users


def judge(db, assignment, problem, student, score, *, verdict="WA"):
    """落一条已判分的提交（分值直接给定，不走判题机）。"""
    sub = make_submission(db, assignment, problem, student, "int main(){}")
    sub.status = "done"
    sub.verdict = verdict
    sub.score = float(score)
    sub.judged_at = "2026-09-21 10:00:00"
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def overview_of(client, assignment, headers):
    resp = client.get(f"/api/teacher/assignments/{assignment.id}/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def student_totals(client, assignment, headers):
    resp = client.get(f"/api/teacher/assignments/{assignment.id}/students", headers=headers)
    assert resp.status_code == 200, resp.text
    return {r["username"]: r["total_score"] for r in resp.json()}


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


class TestClassTotalMetrics:
    """均值/最高/最低对拍手算，且与逐学生表的 total_score 同源。"""

    def test_avg_max_min_match_hand_computed(self, client, db, teacher, h_teacher, assignment, problem):
        s1, s2, _s3 = seed_students(db, 3, teacher=teacher)
        judge(db, assignment, problem, s1, 85.0)
        judge(db, assignment, problem, s2, 55.0)

        body = overview_of(client, assignment, h_teacher)
        # 总分 = [85, 55, 0]（未交的 s3 按 0 计）：满分和 100 → 及格线 60
        assert body["total_students"] == 3
        assert body["submitted_students"] == 2
        assert body["full_score_sum"] == 100.0
        assert body["avg_total_score"] == 46.7          # round(140/3, 1)
        assert body["max_total_score"] == 85.0
        assert body["min_total_score"] == 0.0
        assert body["pass_rate"] == 0.3333              # 只有 85 过线

        assert student_totals(client, assignment, h_teacher) == {"ov1": 85.0, "ov2": 55.0, "ov3": 0.0}

    def test_unsubmitted_student_is_counted_and_fails(self, client, db, teacher, h_teacher, assignment, problem):
        s1, s2 = seed_students(db, 2, teacher=teacher)
        judge(db, assignment, problem, s1, 100.0)
        # s2 一道没交：进 total_students 分母、总分 0、不及格
        body = overview_of(client, assignment, h_teacher)
        assert body["total_students"] == 2
        assert body["min_total_score"] == 0.0
        assert body["avg_total_score"] == 50.0
        assert body["pass_rate"] == 0.5
        assert student_totals(client, assignment, h_teacher)["ov2"] == 0.0

    def test_empty_audience_returns_neutral_metrics(self, client, h_teacher, assignment):
        body = overview_of(client, assignment, h_teacher)
        assert body["total_students"] == 0
        assert body["avg_total_score"] == 0.0
        assert body["pass_rate"] == 0.0
        assert body["max_total_score"] is None
        assert body["min_total_score"] is None
        # 满分和只依赖题单
        assert body["full_score_sum"] == 100.0


class TestPassLineFollowsFullScoreSum:
    """及格线随题单满分和：50 + 70 = 120 → 及格线 72（含边界）。"""

    def test_boundary_at_sixty_percent_of_sum(self, client, db, teacher, h_teacher, assignment, problem):
        p2 = _add(db, Problem(title="B", description="输入。", input_format="一行",
                              output_format="一行", time_limit_ms=1000, memory_limit_mb=256,
                              compare_mode="trim", created_by=teacher.id))
        first = db.query(AssignmentProblem).filter_by(
            assignment_id=assignment.id, problem_id=problem.id).one()
        first.full_score = 50.0
        db.commit()
        _add(db, AssignmentProblem(assignment_id=assignment.id, problem_id=p2.id,
                                   seq=2, full_score=70.0))

        s1, s2, s3 = seed_students(db, 3, teacher=teacher)
        judge(db, assignment, problem, s1, 50.0)
        judge(db, assignment, p2, s1, 30.0)   # 80 → 及格
        judge(db, assignment, problem, s2, 40.0)
        judge(db, assignment, p2, s2, 31.0)   # 71 → 不及格
        judge(db, assignment, problem, s3, 50.0)
        judge(db, assignment, p2, s3, 22.0)   # 72 = 0.6*120 → 及格（边界含）

        body = overview_of(client, assignment, h_teacher)
        assert body["full_score_sum"] == 120.0
        assert body["max_total_score"] == 80.0
        assert body["min_total_score"] == 71.0
        assert body["avg_total_score"] == 74.3          # round(223/3, 1)
        assert body["pass_rate"] == round(2 / 3, 4)
        assert student_totals(client, assignment, h_teacher) == {"ov1": 80.0, "ov2": 71.0, "ov3": 72.0}


class TestManualScoreInTotal:
    """调分后的分进总分口径：aggregate_scores 以 manual_score 覆盖系统分。"""

    def test_manual_score_raises_total_and_pass_rate(self, client, db, teacher, h_teacher,
                                                     assignment, problem, cases):
        s1, s2 = seed_students(db, 2, teacher=teacher)
        low = judge(db, assignment, problem, s1, 20.0)
        judge(db, assignment, problem, s2, 59.0)
        assert overview_of(client, assignment, h_teacher)["pass_rate"] == 0.0

        resp = client.patch(f"/api/teacher/submissions/{low.id}/score",
                            headers=h_teacher, json={"manual_score": 95.0})
        assert resp.status_code == 200, resp.text

        body = overview_of(client, assignment, h_teacher)
        assert body["max_total_score"] == 95.0
        assert body["min_total_score"] == 59.0
        assert body["avg_total_score"] == 77.0
        assert body["pass_rate"] == 0.5                 # 59 仍差 1 分不到 60
        # 与逐学生表逐人一致（同一份 _total_score）
        assert student_totals(client, assignment, h_teacher) == {"ov1": 95.0, "ov2": 59.0}

    def test_policy_best_aggregates_multiple_submissions(self, client, db, teacher, h_teacher,
                                                         assignment, problem):
        assert assignment.score_policy == "best"
        s1, = seed_students(db, 1, teacher=teacher)
        first = Submission(assignment_id=assignment.id, problem_id=problem.id,
                           user_id=s1.id, code_text="a", status="done", verdict="WA",
                           score=40.0, submitted_at="2026-09-01 10:00:00")
        second = Submission(assignment_id=assignment.id, problem_id=problem.id,
                            user_id=s1.id, code_text="b", status="done", verdict="AC",
                            score=90.0, submitted_at="2026-09-01 11:00:00")
        db.add_all([first, second])
        db.commit()

        body = overview_of(client, assignment, h_teacher)
        assert body["avg_total_score"] == 90.0          # best 取最高，不是末次
        assert body["pass_rate"] == 1.0
