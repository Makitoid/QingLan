"""0.3.0 批次 M6 · 人工调分边界与重判作废（SC-03 / SC-04，对应 QA-11 / QA-12）。

契约以 app/api/teacher.py 为准：
- ``PATCH /api/teacher/submissions/{id}/score``：``manual_score`` 为 null（或省略）= 撤销调分，
  两列一起置 NULL；非 null 必须落在 0 ~ 该题在本场次的 ``assignment_problems.full_score`` 之间，
  越界 → 422 MANUAL_SCORE_OUT_OF_RANGE 且库里零变化、零审计；题单里查不到该题（分值未配置）
  同样 422，不做「无上限」放行。
- 合法调分写 ``manual_score_updated_at`` 锚点 + 审计 ``score_manual_adjust``
  （detail = {old, new, full_score}，target_type=submission）。
- ``POST /api/teacher/submissions/{id}/rejudge``：判定结果回到 pending 的同时**作废人工调分**
  （SC-04），否则旧调分会以「覆盖系统分」的优先级把新判出来的成绩顶掉。
- 归属沿用 ``_get_owned_submission``：只看 ``assignments.created_by``，非本人场次 403、
  提交不存在 404。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_token
from app.main import app
from app.models import AuditLog, SubmissionResult, User

from .conftest import make_submission


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def fresh(db):
    db.commit()
    db.expire_all()


def audit_rows(db, action):
    fresh(db)
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


def score_of(db, submission):
    fresh(db)
    row = db.execute(
        text("SELECT manual_score, manual_score_updated_at FROM submissions WHERE id=:i"),
        {"i": submission.id},
    ).one()
    return row[0], row[1]


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


@pytest.fixture()
def judged(db, assignment, problem, student, cases):
    sub = make_submission(db, assignment, problem, student, "int main(){}")
    sub.status = "done"
    sub.verdict = "WA"
    sub.score = 25.0
    sub.judged_at = "2026-09-21 10:00:00"
    sub.worker_id = "w1"
    sub.judge_log = "old log"
    db.add(SubmissionResult(submission_id=sub.id, test_case_id=cases[0].id,
                            verdict="WA", time_ms=10, memory_kb=256, score=25.0))
    db.commit()
    db.refresh(sub)
    return sub


class TestManualScoreBounds:
    """QA-11：0 ~ 满分之间的边界、越界拒绝、null 撤销。"""

    def test_valid_adjust_sets_score_anchor_and_audit(self, client, db, h_teacher, judged):
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": 88.5})
        assert resp.status_code == 200, resp.text
        assert resp.json()["manual_score"] == 88.5
        manual, anchor = score_of(db, judged)
        assert manual == 88.5 and anchor

        logs = audit_rows(db, "score_manual_adjust")
        assert len(logs) == 1
        assert logs[0].target_type == "submission" and logs[0].target_id == judged.id
        assert json.loads(logs[0].detail) == {"old": None, "new": 88.5, "full_score": 100.0}

    @pytest.mark.parametrize("value", [0, 100, 99.99])
    def test_inclusive_bounds_accepted(self, client, db, h_teacher, judged, value):
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": value})
        assert resp.status_code == 200, (value, resp.text)
        assert score_of(db, judged)[0] == float(value)

    @pytest.mark.parametrize("value", [-5, -0.01, 100.01, 101])
    def test_out_of_range_rejected_without_writing(self, client, db, h_teacher, judged, value):
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": value})
        assert resp.status_code == 422, (value, resp.text)
        body = resp.json()
        assert body["code"] == "MANUAL_SCORE_OUT_OF_RANGE"
        assert f"0 ~ 100" in body["message"]
        assert score_of(db, judged) == (None, None)
        assert audit_rows(db, "score_manual_adjust") == []

    def test_adjust_existing_manual_score_records_old_value(self, client, db, h_teacher, judged):
        client.patch(f"/api/teacher/submissions/{judged.id}/score",
                     headers=h_teacher, json={"manual_score": 60})
        assert client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": 70}).status_code == 200
        assert json.loads(audit_rows(db, "score_manual_adjust")[-1].detail)["old"] == 60

    def test_null_revokes_and_clears_anchor_too(self, client, db, h_teacher, judged):
        client.patch(f"/api/teacher/submissions/{judged.id}/score",
                     headers=h_teacher, json={"manual_score": 60})
        assert score_of(db, judged)[1]

        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["manual_score"] is None
        # SC-03：撤销调分两列一起回 NULL，只清一列会让 UI 显示「调过分但无分值」
        assert score_of(db, judged) == (None, None)
        assert json.loads(audit_rows(db, "score_manual_adjust")[-1].detail) == \
            {"old": 60, "new": None, "full_score": 100.0}

    def test_omitting_field_is_treated_as_revoke(self, client, db, h_teacher, judged):
        client.patch(f"/api/teacher/submissions/{judged.id}/score",
                     headers=h_teacher, json={"manual_score": 60})
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={})
        assert resp.status_code == 200, resp.text
        assert score_of(db, judged) == (None, None)

    def test_problem_removed_from_problem_list_has_no_ceiling(self, client, db, h_teacher,
                                                              judged, assignment):
        db.execute(text("DELETE FROM assignment_problems WHERE assignment_id=:a"),
                   {"a": assignment.id})
        db.commit()
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": 10})
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "MANUAL_SCORE_OUT_OF_RANGE"
        assert "未在本场次中配置分值" in resp.json()["message"]
        assert score_of(db, judged) == (None, None)


class TestAdjustOwnership:
    def test_other_teachers_submission_is_403(self, client, db, judged):
        other = User(username="t900", password_hash="x", role="teacher",
                     display_name="另一教师", must_change_password=0)
        db.add(other)
        db.commit()
        db.refresh(other)
        poaching = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                                headers=bearer(other), json={"manual_score": 50})
        assert poaching.status_code == 403, poaching.text
        assert score_of(db, judged) == (None, None)

    def test_missing_submission_is_404(self, client, h_teacher):
        resp = client.patch("/api/teacher/submissions/424242/score",
                            headers=h_teacher, json={"manual_score": 50})
        assert resp.status_code == 404, resp.text


class TestRejudgeClearsManualScore:
    """QA-12：重判后 manual_score 与 manual_score_updated_at 均为 NULL，成绩回到系统判分。"""

    def test_rejudge_voids_manual_adjust_and_judged_results(self, client, db, h_teacher, judged):
        client.patch(f"/api/teacher/submissions/{judged.id}/score",
                     headers=h_teacher, json={"manual_score": 99})
        assert score_of(db, judged) == (99.0, score_of(db, judged)[1])

        resp = client.post(f"/api/teacher/submissions/{judged.id}/rejudge", headers=h_teacher)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["verdict"] is None and body["score"] is None
        assert body["manual_score"] is None
        assert body["judged_at"] is None and body["judge_log"] is None
        assert body["results"] == []

        fresh(db)
        row = db.execute(
            text("SELECT manual_score, manual_score_updated_at, worker_id FROM submissions "
                 "WHERE id=:i"), {"i": judged.id}).one()
        assert row == (None, None, None)
        assert db.execute(text("SELECT COUNT(*) FROM submission_results WHERE submission_id=:i"),
                          {"i": judged.id}).scalar() == 0

    def test_rejudged_submission_can_be_adjusted_again(self, client, db, h_teacher, judged):
        client.patch(f"/api/teacher/submissions/{judged.id}/score",
                     headers=h_teacher, json={"manual_score": 99})
        client.post(f"/api/teacher/submissions/{judged.id}/rejudge", headers=h_teacher)
        resp = client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": 120})
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "MANUAL_SCORE_OUT_OF_RANGE"
        assert score_of(db, judged) == (None, None)
        assert client.patch(f"/api/teacher/submissions/{judged.id}/score",
                            headers=h_teacher, json={"manual_score": 30}).status_code == 200
