"""0.4.0 F3 · admin 代加/代删「临时学生」（层 3 手动绑定行的第二条写路径）。

契约以代码实际行为为准（app/api/admin.py、app/services/groups.py、app/api/teacher.py）：
- ``POST /api/admin/teachers/{tid}/students/bind``：教师不存在或角色不符 → 404 NOT_FOUND；
  学生校验口径与教师端 ``bind`` 一致（role=student 且 is_active=1），任一不满足整批 422
  INVALID_STUDENT_IDS 且零写入；空选 422 EMPTY_SELECTION；幂等插 ``teacher_students``，
  响应只有 success_count；审计 ``admin_student_bind``（target_type=teacher，detail 带
  count/student_ids/source，source 字面量仍是 manual，UI 文案才是「临时添加」）。
- ``POST /api/admin/teachers/{tid}/students/unbind``：只删层 3 行；请求 id 属于可教组别
  派生（teachable ∩ 请求 − manual 非空）→ 整批 422 ROSTER_DERIVED_STUDENT 且不写库；
  名单外的 id 静默忽略（幂等）；审计 ``admin_student_unbind``。
- 写路径共用 ``groups_svc.bind_manual_students``：教师端 bind 的行为（幂等、审计
  teacher_student_bind、提交时机）与本文件不出现的既有契约见
  tests/test_teacher_binding_api.py。
- 解绑只影响名单归属，历史提交/成绩行保留、按 id 仍可读（BD-05 同口径）。
- 审计与写操作同事务；断言前先 fresh() 直接查库。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_token
from app.main import app
from app.models import (AuditLog, Group, GroupMember, Submission, TeacherGroup,
                        TeacherStudent, User)

BIND = "/api/admin/teachers/{tid}/students/bind"
UNBIND = "/api/admin/teachers/{tid}/students/unbind"


# ---------- 数据工厂（与 test_teacher_binding_api.py 同范式） ----------

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def seed_students(db, n, *, prefix="stu", is_active=1, must_change=0):
    users = []
    for i in range(1, n + 1):
        users.append(User(username=f"{prefix}{i}", password_hash="x", role="student",
                          display_name=f"学生{prefix}{i}", is_active=is_active,
                          must_change_password=must_change))
    db.add_all(users)
    db.commit()
    for u in users:
        db.refresh(u)
    return users


def seed_group(db, name):
    return _add(db, Group(name=name))


def seed_member(db, group, *students):
    for s in students:
        _add(db, GroupMember(group_id=group.id, student_id=s.id))


def seed_teacher_group(db, teacher, group):
    return _add(db, TeacherGroup(teacher_id=teacher.id, group_id=group.id))


def fresh(db):
    db.commit()
    db.expire_all()


def roster_pairs(db):
    fresh(db)
    return {(t, s) for t, s in db.execute(
        text("SELECT teacher_id, student_id FROM teacher_students")).all()}


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
def admin_user(db):
    return _add(db, User(username="admin001", password_hash="x", role="admin",
                         display_name="管理员", must_change_password=0))


@pytest.fixture()
def h_admin(admin_user):
    return bearer(admin_user)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


def bind_url(teacher):
    return BIND.format(tid=teacher.id)


def unbind_url(teacher):
    return UNBIND.format(tid=teacher.id)


# ---------- 1. 代加：成功 + 审计 + 幂等 + 整批拒绝 ----------

class TestAdminBind:
    def test_bind_success_writes_rows_and_audit(self, client, db, h_admin, admin_user, teacher):
        a, b = seed_students(db, 2, prefix="tmp")
        resp = client.post(bind_url(teacher), headers=h_admin, json={"student_ids": [a.id, b.id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2}
        assert roster_pairs(db) == {(teacher.id, a.id), (teacher.id, b.id)}
        # 名单接口现算 source：临时学生是 manual，组别派生才是 group
        rows = {r["id"]: r for r in
                client.get("/api/admin/teachers/{}/students".format(teacher.id),
                           headers=h_admin).json()["students"]}
        assert rows[a.id]["source"] == "manual" and rows[b.id]["source"] == "manual"

        logs = audit_rows(db, "admin_student_bind")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert (logs[0].target_type, logs[0].target_id) == ("teacher", teacher.id)
        assert json.loads(logs[0].detail) == {
            "count": 2, "student_ids": [a.id, b.id], "source": "manual"}
        # 不牵连教师端既有审计动作
        assert audit_rows(db, "teacher_student_bind") == []

    def test_bind_is_idempotent(self, client, db, h_admin, teacher):
        s = seed_students(db, 1, prefix="idem")[0]
        assert client.post(bind_url(teacher), headers=h_admin,
                           json={"student_ids": [s.id]}).json() == {"success_count": 1}
        again = client.post(bind_url(teacher), headers=h_admin,
                           json={"student_ids": [s.id, s.id]})
        assert again.status_code == 200, again.text
        assert again.json() == {"success_count": 0}
        assert roster_pairs(db) == {(teacher.id, s.id)}
        assert [json.loads(r.detail)["count"] for r in audit_rows(db, "admin_student_bind")] == [1, 0]

    def test_invalid_ids_reject_whole_batch_without_writing(self, client, db, h_admin, teacher,
                                                            admin_user):
        ok = seed_students(db, 1, prefix="good")[0]
        dormant = seed_students(db, 1, prefix="dead", is_active=0)[0]
        for bad, label in ((dormant.id, "停用"), (admin_user.id, "管理员"), (424242, "不存在")):
            resp = client.post(bind_url(teacher), headers=h_admin,
                               json={"student_ids": [ok.id, bad]})
            assert resp.status_code == 422, (label, resp.text)
            assert code_of(resp) == "INVALID_STUDENT_IDS"
        assert roster_pairs(db) == set()
        assert audit_rows(db, "admin_student_bind") == []

    def test_empty_selection_is_rejected(self, client, db, h_admin, teacher):
        resp = client.post(bind_url(teacher), headers=h_admin, json={"student_ids": []})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "EMPTY_SELECTION"
        assert audit_rows(db, "admin_student_bind") == []

    def test_unknown_or_wrong_role_teacher_is_404(self, client, db, h_admin, teacher):
        s = seed_students(db, 1, prefix="who")[0]
        missing = client.post(BIND.format(tid=99999), headers=h_admin,
                              json={"student_ids": [s.id]})
        assert missing.status_code == 404, missing.text
        assert code_of(missing) == "NOT_FOUND"
        # 角色不符（学生 id 冒充教师）同样 404，且不写任何层 3 行
        wrong = client.post(bind_url(s), headers=h_admin, json={"student_ids": [s.id]})
        assert wrong.status_code == 404, wrong.text
        assert roster_pairs(db) == set()


# ---------- 2. 代删：manual 成功 / 组别派生整批 422 / 幂等 ----------

class TestAdminUnbind:
    def test_unbind_manual_row_succeeds_and_audits(self, client, db, h_admin, admin_user, teacher):
        s = seed_students(db, 1, prefix="gone")[0]
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=s.id))
        resp = client.post(unbind_url(teacher), headers=h_admin, json={"student_ids": [s.id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1}
        assert roster_pairs(db) == set()
        logs = audit_rows(db, "admin_student_unbind")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert (logs[0].target_type, logs[0].target_id) == ("teacher", teacher.id)
        assert json.loads(logs[0].detail) == {"count": 1, "student_ids": [s.id]}

    def test_unbind_group_derived_rejects_whole_batch(self, client, db, h_admin, teacher):
        g = seed_group(db, "临时与组别的班")
        seed_teacher_group(db, teacher, g)
        derived, manual_only = seed_students(db, 2, prefix="mix")
        seed_member(db, g, derived, manual_only)
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=manual_only.id))

        resp = client.post(unbind_url(teacher), headers=h_admin,
                           json={"student_ids": [manual_only.id, derived.id]})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "ROSTER_DERIVED_STUDENT"
        # 消息与教师端 unbind 同文案：列出组别派生的 id
        assert str(derived.id) in resp.json()["message"]
        # 整批不写：manual 行原样保留
        assert roster_pairs(db) == {(teacher.id, manual_only.id)}
        assert audit_rows(db, "admin_student_unbind") == []

    def test_unbind_ids_outside_roster_are_ignored(self, client, db, h_admin, teacher):
        s = seed_students(db, 1, prefix="none")[0]
        resp = client.post(unbind_url(teacher), headers=h_admin,
                           json={"student_ids": [s.id, 888888]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 0}
        assert roster_pairs(db) == set()

    def test_unbind_unknown_teacher_is_404(self, client, db, h_admin):
        resp = client.post(UNBIND.format(tid=99999), headers=h_admin, json={"student_ids": [1]})
        assert resp.status_code == 404, resp.text
        assert code_of(resp) == "NOT_FOUND"


# ---------- 3. 解绑后历史提交/成绩保留（BD-05 同口径） ----------

class TestUnbindKeepsHistory:
    def test_admin_unbind_keeps_submissions_readable(self, client, db, h_admin, teacher,
                                                     h_teacher, problem, assignment):
        s = seed_students(db, 1, prefix="hist")[0]
        assert client.post(bind_url(teacher), headers=h_admin,
                           json={"student_ids": [s.id]}).json() == {"success_count": 1}
        sub = _add(db, Submission(assignment_id=assignment.id, problem_id=problem.id,
                                  user_id=s.id, code_text="print(1)", status="done",
                                  verdict="AC", score=100.0))

        resp = client.post(unbind_url(teacher), headers=h_admin, json={"student_ids": [s.id]})
        assert resp.status_code == 200, resp.text
        assert roster_pairs(db) == set()
        # 提交行留在库里，教师按 id 仍可读（历史成绩保留）
        assert db.execute(text("SELECT COUNT(*) FROM submissions")).scalar() == 1
        detail = client.get(f"/api/teacher/submissions/{sub.id}", headers=h_teacher)
        assert detail.status_code == 200, detail.text
        assert detail.json()["user_id"] == s.id
