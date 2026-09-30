"""0.4.0 批次 F1 · 题库批处理（批量分组 / 批量删除）。

契约以代码实际行为为准（app/api/teacher.py::batch_group_problems / batch_delete_problems）：
- 两个端点都沿用全仓批量范式：**先去重保序、再逐题归属校验，任一题非法即整批拒绝、零写入**，
  响应复用 ``GroupMembershipOut{success_count}``。
- 空选择（去重后为空）→ 422 EMPTY_SELECTION，且在写库之前就拦下。
- 归属校验：不存在的 id → 404 PROBLEM_NOT_FOUND；他人创建的题 → 403 FORBIDDEN；
  两类都是整批拒绝、审计不落。
- batch_group：group_name 去首尾空白后为空 → 422；成功时把 strip 后的组名统一写入整批题目。
- batch_delete：批次内任一题被 ``assignment_problems`` 引用 → 整批 409 PROBLEM_IN_USE，
  message 列出被引用题名（超过 3 个时列前 3 个并加「等 N 道」），一题都不删；
  无引用时与单删一致的级联（题面 + 全部测试用例，FK ondelete=CASCADE）。
- 审计 ``problem_batch_group``（detail 带 problem_ids/group_name）与 ``problem_batch_delete``
  （detail 带 problem_ids），target_type=problem、target_id=None，与写入同事务。
- 断言前直接查库（fresh() 提交并过期缓存）。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_token
from app.main import app
from app.models import (Assignment, AssignmentProblem, AuditLog, Problem,
                        TestCase, User)

BATCH_GROUP = "/api/teacher/problems/batch_group"
BATCH_DELETE = "/api/teacher/problems/batch_delete"


# ---------- 数据工厂 ----------

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def seed_problem(db, teacher, title, *, group_name=None):
    return _add(db, Problem(title=title, description="描述", input_format="入",
                             output_format="出", time_limit_ms=1000, memory_limit_mb=256,
                             compare_mode="trim", group_name=group_name,
                             created_by=teacher.id))


def seed_case(db, problem, seq):
    return _add(db, TestCase(problem_id=problem.id, seq=seq, input="1\n",
                             expected="1\n", is_sample=0, weight=1))


def seed_assignment_with(db, teacher, problem, title="引用场次"):
    a = _add(db, Assignment(title=title, mode="homework",
                            start_time="2026-01-01 00:00:00",
                            end_time="2027-01-01 00:00:00",
                            score_policy="best", created_by=teacher.id))
    _add(db, AssignmentProblem(assignment_id=a.id, problem_id=problem.id,
                               seq=1, full_score=100.0))
    return a


def fresh(db):
    db.commit()
    db.expire_all()


def problem_exists(db, pid):
    fresh(db)
    return db.execute(text("SELECT COUNT(*) FROM problems WHERE id = :i"),
                      {"i": pid}).scalar() == 1


def case_count(db, problem_id):
    fresh(db)
    return db.execute(text("SELECT COUNT(*) FROM test_cases WHERE problem_id = :i"),
                      {"i": problem_id}).scalar()


def group_name_of(db, pid):
    fresh(db)
    return db.execute(text("SELECT group_name FROM problems WHERE id = :i"),
                      {"i": pid}).scalar()


def audit_rows(db, action):
    fresh(db)
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def code_of(resp):
    return resp.json().get("code")


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


@pytest.fixture()
def teacher2(db):
    return _add(db, User(username="t002", password_hash="x", role="teacher",
                         display_name="李老师", must_change_password=0))


@pytest.fixture()
def h_teacher2(teacher2):
    return bearer(teacher2)


# ---------- 1. batch_group：成功路径与审计 ----------

class TestBatchGroup:
    def test_success_writes_stripped_name_and_audit(self, client, db, teacher, h_teacher):
        p1 = seed_problem(db, teacher, "甲", group_name="旧组")
        p2 = seed_problem(db, teacher, "乙")
        resp = client.post(BATCH_GROUP, headers=h_teacher,
                           json={"problem_ids": [p1.id, p2.id, p1.id],
                                 "group_name": "  基础题  "})
        assert resp.status_code == 200, resp.text
        # 去重保序后按实际写入条数返回
        assert resp.json() == {"success_count": 2}
        assert group_name_of(db, p1.id) == "基础题"
        assert group_name_of(db, p2.id) == "基础题"

        logs = audit_rows(db, "problem_batch_group")
        assert len(logs) == 1
        row = logs[0]
        assert (row.actor_id, row.target_type, row.target_id) == (teacher.id, "problem", None)
        assert json.loads(row.detail) == {"problem_ids": [p1.id, p2.id],
                                          "group_name": "基础题"}

    def test_foreign_problem_rejects_whole_batch(self, client, db, teacher, teacher2, h_teacher):
        mine = seed_problem(db, teacher, "我的题")
        theirs = seed_problem(db, teacher2, "别人的题")
        resp = client.post(BATCH_GROUP, headers=h_teacher,
                           json={"problem_ids": [mine.id, theirs.id], "group_name": "新组"})
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "FORBIDDEN"
        # 整批零写入：合法那题保持原样
        assert group_name_of(db, mine.id) is None
        assert group_name_of(db, theirs.id) is None
        assert audit_rows(db, "problem_batch_group") == []

    def test_blank_group_name_is_422(self, client, db, teacher, h_teacher):
        p = seed_problem(db, teacher, "空白组名", group_name="保持我")
        resp = client.post(BATCH_GROUP, headers=h_teacher,
                           json={"problem_ids": [p.id], "group_name": "   "})
        assert resp.status_code == 422, resp.text
        assert group_name_of(db, p.id) == "保持我"
        assert audit_rows(db, "problem_batch_group") == []

    def test_empty_selection_is_422(self, client, db, teacher, h_teacher):
        for url, body in ((BATCH_GROUP, {"problem_ids": [], "group_name": "组"}),
                          (BATCH_DELETE, {"problem_ids": []})):
            resp = client.post(url, headers=h_teacher, json=body)
            assert resp.status_code == 422, (url, resp.text)
            assert code_of(resp) == "EMPTY_SELECTION"

    def test_unknown_problem_id_is_404(self, client, db, teacher, h_teacher):
        real = seed_problem(db, teacher, "真题")
        for url, body in ((BATCH_GROUP, {"problem_ids": [real.id, 424242], "group_name": "组"}),
                          (BATCH_DELETE, {"problem_ids": [real.id, 424242]})):
            resp = client.post(url, headers=h_teacher, json=body)
            assert resp.status_code == 404, (url, resp.text)
            assert code_of(resp) == "PROBLEM_NOT_FOUND"
        # 整批拒绝：真题没被牵连
        assert group_name_of(db, real.id) is None
        assert problem_exists(db, real.id)


# ---------- 2. batch_delete：成功、级联与引用保护 ----------

class TestBatchDelete:
    def test_success_deletes_cases_as_single_delete(self, client, db, teacher, h_teacher,
                                                    problem, cases):
        extra = seed_problem(db, teacher, "多余题")
        seed_case(db, extra, 1)
        assert case_count(db, problem.id) == 2
        # 先捕获主键：删除 + expire_all 之后再碰 ORM 对象会触发过期刷新
        pid, extra_id = problem.id, extra.id

        resp = client.post(BATCH_DELETE, headers=h_teacher,
                           json={"problem_ids": [pid, extra_id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2}
        # 与单删 DELETE /problems/{id} 一致的级联：题面与全部测试用例都不在库里
        assert not problem_exists(db, pid)
        assert not problem_exists(db, extra_id)
        assert case_count(db, pid) == 0
        assert case_count(db, extra_id) == 0

        logs = audit_rows(db, "problem_batch_delete")
        assert len(logs) == 1
        assert (logs[0].actor_id, logs[0].target_type, logs[0].target_id) == (
            teacher.id, "problem", None)
        assert json.loads(logs[0].detail) == {"problem_ids": [pid, extra_id]}

    def test_referenced_problem_rejects_whole_batch_with_titles(self, client, db, teacher,
                                                                h_teacher, problem, assignment):
        spare = seed_problem(db, teacher, "没被引用的题")
        resp = client.post(BATCH_DELETE, headers=h_teacher,
                           json={"problem_ids": [problem.id, spare.id]})
        assert resp.status_code == 409, resp.text
        assert code_of(resp) == "PROBLEM_IN_USE"
        # message 列出被引用题名，供前端直接展示
        assert problem.title in resp.json()["message"]
        # 整批不删：连没被引用的那题也留在库里
        assert problem_exists(db, problem.id)
        assert problem_exists(db, spare.id)
        assert audit_rows(db, "problem_batch_delete") == []

    def test_more_than_three_blocked_lists_first_three_and_count(self, client, db, teacher,
                                                                 h_teacher):
        blocked = [seed_problem(db, teacher, f"被引用{i}") for i in range(1, 5)]
        for p in blocked:
            seed_assignment_with(db, teacher, p, title=f"场次{p.title}")
        resp = client.post(BATCH_DELETE, headers=h_teacher,
                           json={"problem_ids": [p.id for p in blocked]})
        assert resp.status_code == 409, resp.text
        assert code_of(resp) == "PROBLEM_IN_USE"
        message = resp.json()["message"]
        # >3 时列前 3 个题名并加「等 N 道」，第 4 个不再展开
        for p in blocked[:3]:
            assert p.title in message
        assert blocked[3].title not in message
        assert "等 4 道" in message
        for p in blocked:
            assert problem_exists(db, p.id)
