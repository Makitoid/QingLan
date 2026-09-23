"""0.3.0 批次 M6 · 三层归属的写入路径（BD-01~07 / QA-06、QA-07、QA-08）。

对应验收：QA-06（admin 分配/替换可教组 + 层 2 审计 + 教师名单不被牵连）、
QA-07（bind_from_class 幂等与整批 403、bind 兜底且响应不泄露明细）、
QA-08（``GET /teacher/students?q=``）。层 1 改组与整批拒绝的对照组在
tests/test_groups_api.py::TestTeacherMembership，本文件不重复。

契约以代码实际行为为准（app/api/admin.py、app/api/teacher.py、app/services/groups.py）：
- 层 2 唯一写者是 admin：``PUT /api/admin/teachers/{tid}/groups``（group_ids 全量替换、
  去重升序、空列表即清空）+ ``GET`` 查看；任一不存在的组 → 404 GROUP_NOT_FOUND 且整批不写；
  审计 ``teacher_group_assign``（detail 带 group_ids/added/removed）。
- 层 3 唯一写者是教师本人：``bind_from_class``（要求每个 id 都在可教组内，否则整批 403
  STUDENT_NOT_IN_CLASS、库零变化；只校验 role=student，**停用学生也能拉**）、
  ``bind``（兜底按 id，额外要求 is_active=1，否则整批 422 INVALID_STUDENT_IDS；
  响应只有 success_count）、``unbind``（只移自己名单，其余静默忽略）。
- 边界（§4.3）：解绑组-教师分配只影响「能不能再拉新人」，教师已有名单与层 2 已有行都不牵连；
  教师停用/启用不动任何关系；一名学生可同时属于多位教师的名单。
- ``GET /teacher/students?q=`` 对 username / display_name 做大小写不敏感模糊匹配，
  只在**自己的名单**内过滤；缺省时与旧行为一致。
- 审计与写操作同事务，接口自己 commit；断言前直接查库（先 fresh()）。
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_token
from app.main import app
from app.models import (AuditLog, Group, GroupMember, Submission, TeacherGroup,
                        TeacherStudent, User)

BIND_FROM_CLASS = "/api/teacher/students/bind_from_class"
BIND = "/api/teacher/students/bind"
UNBIND = "/api/teacher/students/unbind"


# ---------- 数据工厂（直接写库的账号一律显式 must_change_password=0，见 PW-02） ----------

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


def teacher_group_pairs(db):
    fresh(db)
    return {(t, g) for t, g in db.execute(
        text("SELECT teacher_id, group_id FROM teacher_groups")).all()}


def roster_pairs(db):
    fresh(db)
    return {(t, s) for t, s in db.execute(
        text("SELECT teacher_id, student_id FROM teacher_students")).all()}


def member_pairs(db):
    fresh(db)
    return {(g, s) for g, s in db.execute(
        text("SELECT group_id, student_id FROM group_members")).all()}


def audit_rows(db, action):
    fresh(db)
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


def scalar_count(db, sql):
    fresh(db)
    return db.execute(text(sql)).scalar()


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
def teacher2(db):
    return _add(db, User(username="t002", password_hash="x", role="teacher",
                         display_name="李老师", must_change_password=0))


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


@pytest.fixture()
def h_teacher2(teacher2):
    return bearer(teacher2)


# ---------- 1. 层 2：admin 全量替换教师的可教组（QA-06） ----------

class TestTeacherGroupAssignment:
    def groups_url(self, teacher):
        return f"/api/admin/teachers/{teacher.id}/groups"

    def test_put_full_replace_then_get_reads_back(self, client, db, h_admin, admin_user, teacher):
        g1, g2, g3 = seed_group(db, "一班"), seed_group(db, "二班"), seed_group(db, "三班")
        url = self.groups_url(teacher)

        resp = client.put(url, headers=h_admin, json={"group_ids": [g2.id, g1.id]})
        assert resp.status_code == 200, resp.text
        # 返回升序去重的全量结果（前端据此刷新 diff 基线）
        assert resp.json() == {"teacher_id": teacher.id, "group_ids": [g1.id, g2.id]}
        assert client.get(url, headers=h_admin).json() == resp.json()
        assert teacher_group_pairs(db) == {(teacher.id, g1.id), (teacher.id, g2.id)}

        second = client.put(url, headers=h_admin, json={"group_ids": [g2.id, g3.id, g2.id]})
        assert second.json() == {"teacher_id": teacher.id, "group_ids": [g2.id, g3.id]}
        assert teacher_group_pairs(db) == {(teacher.id, g2.id), (teacher.id, g3.id)}

        logs = audit_rows(db, "teacher_group_assign")
        assert len(logs) == 2
        assert all(r.actor_id == admin_user.id for r in logs)
        assert all((r.target_type, r.target_id) == ("teacher", teacher.id) for r in logs)
        assert json.loads(logs[0].detail) == {
            "group_ids": [g1.id, g2.id], "added": [g1.id, g2.id], "removed": []}
        assert json.loads(logs[1].detail) == {
            "group_ids": [g2.id, g3.id], "added": [g3.id], "removed": [g1.id]}

    def test_empty_list_clears_assignment_without_touching_layer3(self, client, db, h_admin,
                                                                  teacher, h_teacher):
        g1 = seed_group(db, "要收回的班")
        s = seed_students(db, 1, prefix="keep")[0]
        seed_member(db, g1, s)
        seed_teacher_group(db, teacher, g1)
        seed_teacher_group(db, teacher, seed_group(db, "另一个班"))
        assert client.post(BIND_FROM_CLASS, headers=h_teacher,
                           json={"student_ids": [s.id]}).json() == {"success_count": 1}
        before = roster_pairs(db)

        resp = client.put(self.groups_url(teacher), headers=h_admin, json={"group_ids": []})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"teacher_id": teacher.id, "group_ids": []}
        assert teacher_group_pairs(db) == set()
        # §4.3：收回收分配只挡住「再拉新人」，已有名单保留、/classes 不再返回该组
        assert roster_pairs(db) == before
        assert client.get("/api/teacher/classes", headers=h_teacher).json() == []
        assert [r["username"] for r in client.get("/api/teacher/students",
                                                  headers=h_teacher).json()] == [s.username]
        detail = json.loads(audit_rows(db, "teacher_group_assign")[-1].detail)
        assert detail["added"] == [] and len(detail["removed"]) == 2

    def test_unknown_group_rejects_whole_batch(self, client, db, h_admin, teacher):
        real = seed_group(db, "真班")
        seed_teacher_group(db, teacher, real)
        before = teacher_group_pairs(db)
        resp = client.put(self.groups_url(teacher), headers=h_admin,
                          json={"group_ids": [real.id, 99999]})
        assert resp.status_code == 404, resp.text
        assert code_of(resp) == "GROUP_NOT_FOUND"
        # 整批不写：真班没被牵连，原有的另一条也不会被顺手删
        assert teacher_group_pairs(db) == before
        assert audit_rows(db, "teacher_group_assign") == []
        # 非教师账号（角色不符）→ 404「教师不存在」
        student = seed_students(db, 1, prefix="not_t")[0]
        wrong_role = client.put(self.groups_url(student), headers=h_admin, json={"group_ids": []})
        assert wrong_role.status_code == 404
        assert code_of(wrong_role) == "NOT_FOUND"

    def test_layer2_and_layer3_survive_teacher_deactivation(self, client, db, h_admin, teacher,
                                                           h_teacher):
        g = seed_group(db, "停用的老师")
        s = seed_students(db, 1, prefix="dormant")[0]
        seed_member(db, g, s)
        seed_teacher_group(db, teacher, g)
        client.post(BIND_FROM_CLASS, headers=h_teacher, json={"student_ids": [s.id]})
        before_l2, before_l3 = teacher_group_pairs(db), roster_pairs(db)
        assert before_l2 and before_l3

        assert client.patch(f"/api/admin/teachers/{teacher.id}", headers=h_admin,
                            json={"is_active": False}).status_code == 200
        # §4.3：停用/启用不动任何关系；令牌立即失效
        assert teacher_group_pairs(db) == before_l2
        assert roster_pairs(db) == before_l3
        assert code_of(client.get("/api/teacher/classes", headers=h_teacher)) == "USER_DISABLED"
        assert client.get(self.groups_url(teacher), headers=h_admin).json() == \
            {"teacher_id": teacher.id, "group_ids": [g.id]}

        assert client.patch(f"/api/admin/teachers/{teacher.id}", headers=h_admin,
                            json={"is_active": True}).status_code == 200
        assert client.get("/api/teacher/classes", headers=h_teacher).json()[0]["id"] == g.id

    def test_assignment_is_admin_only_and_visible_per_teacher(self, client, db, h_admin, h_teacher,
                                                            teacher, teacher2):
        g = seed_group(db, "两班共享")
        seed_teacher_group(db, teacher2, g)
        # 一名学生可被多位教师拉入名单：分配也各自独立
        assert client.get(self.groups_url(teacher2), headers=h_admin).json() == \
            {"teacher_id": teacher2.id, "group_ids": [g.id]}
        assert client.get(self.groups_url(teacher), headers=h_admin).json() == \
            {"teacher_id": teacher.id, "group_ids": []}
        for method in ("get", "put"):
            resp = client.request(method.upper(), self.groups_url(teacher2), headers=h_teacher,
                                  json={"group_ids": []})
            assert resp.status_code == 403, (method, resp.text)
            assert code_of(resp) == "FORBIDDEN"


# ---------- 2. 层 3：从班级拉人（主路径，QA-07） ----------

class TestBindFromClass:
    def test_only_roles_and_group_membership_are_checked(self, client, db, teacher, h_teacher):
        g = seed_group(db, "拉人生效的班")
        seed_teacher_group(db, teacher, g)
        active, dormant = (seed_students(db, 1, prefix="on")[0],
                           seed_students(db, 1, prefix="off", is_active=0)[0])
        seed_member(db, g, active, dormant)

        # BD-03 只校验「在我可教的组里 + 是学生」，停用学生同样能拉（BD-04 才要求 is_active）
        resp = client.post(BIND_FROM_CLASS, headers=h_teacher,
                           json={"student_ids": [active.id, dormant.id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2}
        assert roster_pairs(db) == {(teacher.id, active.id), (teacher.id, dormant.id)}
        rows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        assert rows[dormant.id]["is_active"] == 0

    def test_non_student_ids_are_rejected_as_not_in_class(self, client, db, teacher, teacher2,
                                                          h_teacher, admin_user):
        g = seed_group(db, "只收学生的班")
        seed_teacher_group(db, teacher, g)
        student = seed_students(db, 1, prefix="only")[0]
        seed_member(db, g, student)
        foreign = seed_students(db, 1, prefix="free")[0]
        seed_member(db, g, foreign)          # 组里塞一个非学生
        _add(db, GroupMember(group_id=g.id, student_id=teacher2.id))
        before = roster_pairs(db)

        for bad in (teacher2.id, admin_user.id, 999999):
            resp = client.post(BIND_FROM_CLASS, headers=h_teacher,
                               json={"student_ids": [student.id, bad]})
            assert resp.status_code == 403, (bad, resp.text)
            assert code_of(resp) == "STUDENT_NOT_IN_CLASS"
        assert roster_pairs(db) == before
        assert audit_rows(db, "teacher_student_bind") == []

    def test_teacher_without_any_assignment_cannot_bind(self, client, db, teacher, h_teacher):
        g = seed_group(db, "没分配的班")
        student = seed_students(db, 1, prefix="lonely")[0]
        seed_member(db, g, student)
        assert client.get("/api/teacher/classes", headers=h_teacher).json() == []
        resp = client.post(BIND_FROM_CLASS, headers=h_teacher, json={"student_ids": [student.id]})
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "STUDENT_NOT_IN_CLASS"
        assert roster_pairs(db) == set()


# ---------- 3. 层 3：按学号兜底添加（BD-04，QA-07） ----------

class TestBindByIdFallback:
    def test_accepts_only_active_students(self, client, db, teacher, teacher2, h_teacher,
                                          admin_user):
        ok1, ok2 = seed_students(db, 2, prefix="good")
        dormant = seed_students(db, 1, prefix="dead", is_active=0)[0]

        resp = client.post(BIND, headers=h_teacher, json={"student_ids": [ok1.id, ok2.id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2}
        assert roster_pairs(db) == {(teacher.id, ok1.id), (teacher.id, ok2.id)}

        for bad, label in ((dormant.id, "停用"), (teacher2.id, "教师"),
                           (admin_user.id, "管理员"), (424242, "不存在")):
            rejected = client.post(BIND, headers=h_teacher,
                                   json={"student_ids": [ok1.id, bad]})
            assert rejected.status_code == 422, (label, rejected.text)
            assert code_of(rejected) == "INVALID_STUDENT_IDS"
            # 整批拒绝：合法的那个也没被多写一份
            assert roster_pairs(db) == {(teacher.id, ok1.id), (teacher.id, ok2.id)}

    def test_response_never_leaks_student_details(self, client, db, teacher, h_teacher):
        s = seed_students(db, 1, prefix="secret")[0]
        _add(db, GroupMember(group_id=seed_group(db, "无关班").id, student_id=s.id))
        resp = client.post(BIND, headers=h_teacher, json={"student_ids": [s.id]})
        assert resp.status_code == 200, resp.text
        # 只回条数：这个接口不能变成教师端的全量名册
        assert resp.json() == {"success_count": 1}
        assert set(resp.json()) == {"success_count"}
        body = resp.text
        assert s.username not in body and s.display_name not in body
        assert "学生secret1" not in body

    def test_bind_is_idempotent_and_audited_with_source(self, client, db, teacher, teacher2,
                                                        h_teacher, h_teacher2):
        a, b = seed_students(db, 2, prefix="idem")
        # 同一名学生可以被两位教师各自拉入（多对多，跨班/多科任课独立存在）
        assert client.post(BIND, headers=h_teacher,
                           json={"student_ids": [a.id, b.id]}).json() == {"success_count": 2}
        assert client.post(BIND, headers=h_teacher2,
                           json={"student_ids": [a.id]}).json() == {"success_count": 1}
        assert roster_pairs(db) == {(teacher.id, a.id), (teacher.id, b.id),
                                    (teacher2.id, a.id)}

        again = client.post(BIND, headers=h_teacher,
                            json={"student_ids": [a.id, b.id, b.id]})
        assert again.json() == {"success_count": 0}

        logs = audit_rows(db, "teacher_student_bind")
        assert [json.loads(r.detail) for r in logs] == [
            {"count": 2, "student_ids": [a.id, b.id], "source": "manual"},
            {"count": 1, "student_ids": [a.id], "source": "manual"},
            {"count": 0, "student_ids": [], "source": "manual"},
        ]
        assert [r.actor_id for r in logs] == [teacher.id, teacher2.id, teacher.id]


# ---------- 4. 层 3：移除名单与历史数据（BD-05） ----------

class TestUnbindKeepsHistory:
    def test_unbind_keeps_submissions_readable(self, client, db, teacher, h_teacher,
                                               problem, assignment):
        s = seed_students(db, 1, prefix="hist")[0]
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=s.id))
        sub = _add(db, Submission(assignment_id=assignment.id, problem_id=problem.id,
                                  user_id=s.id, code_text="print(1)", status="done",
                                  verdict="AC", score=100.0))
        rows = client.get(f"/api/teacher/assignments/{assignment.id}/students",
                          headers=h_teacher).json()
        assert [r["username"] for r in rows] == ["hist1"]

        assert client.post(UNBIND, headers=h_teacher,
                           json={"student_ids": [s.id]}).json() == {"success_count": 1}
        # 提交与成绩行都留在库里，按 id 仍可读（BD-05「历史提交/成绩保留」）
        assert scalar_count(db, "SELECT COUNT(*) FROM submissions") == 1
        detail = client.get(f"/api/teacher/submissions/{sub.id}", headers=h_teacher)
        assert detail.status_code == 200, detail.text
        assert detail.json()["user_id"] == s.id
        # 但成绩列表是按「当前名单」生成的：解绑后该生不再出现在 student_rows 里。
        # 见报告：这与 BD-05 的「教师统计仍可见」有张力（app/services/stats.py 的
        # bound_students 过滤），此处按代码实际行为断言。
        assert client.get(f"/api/teacher/assignments/{assignment.id}/students",
                          headers=h_teacher).json() == []
        # 层 1/层 2 完全不受名单增删影响
        assert member_pairs(db) == set()

    def test_binding_never_touches_assignments_or_submissions(self, client, db, teacher, h_teacher,
                                                             assignment, problem):
        student = seed_students(db, 1, prefix="reg")[0]
        seed_member(db, seed_group(db, "回归班"), student)
        subs_before = scalar_count(db, "SELECT COUNT(*) FROM submissions")
        assert scalar_count(db, "SELECT COUNT(*) FROM assignments") == 1
        assert scalar_count(db, "SELECT COUNT(*) FROM assignment_problems") == 1

        resp = client.post(BIND, headers=h_teacher, json={"student_ids": [student.id]})
        assert resp.status_code == 200, resp.text
        assert scalar_count(db, "SELECT COUNT(*) FROM submissions") == subs_before
        assert scalar_count(db, "SELECT COUNT(*) FROM teacher_students") == 1
        # 拉人也不会改动题单分值（调分上界依赖它）
        assert scalar_count(db, "SELECT full_score FROM assignment_problems") == 100.0


# ---------- 5. 教师名单搜索（LI-01 / QA-08） ----------

class TestTeacherRosterSearch:
    def test_q_filters_within_own_roster_only(self, client, db, teacher, teacher2, h_teacher,
                                              h_teacher2):
        zhang = seed_students(db, 1, prefix="z")[0]
        zhang.display_name = "张三"
        li = seed_students(db, 1, prefix="l")[0]
        li.display_name = "李四"
        stranger = seed_students(db, 1, prefix="other")[0]
        stranger.display_name = "张小三"
        db.commit()
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=zhang.id))
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=li.id))
        _add(db, TeacherStudent(teacher_id=teacher2.id, student_id=stranger.id))

        def usernames(params=None):
            resp = client.get("/api/teacher/students", headers=h_teacher, params=params)
            assert resp.status_code == 200, resp.text
            return {r["username"] for r in resp.json()}

        assert usernames() == {"z1", "l1"}
        assert usernames({"q": "张"}) == {"z1"}
        assert usernames({"q": "L1"}) == {"l1"}          # username 也大小写不敏感
        assert usernames({"q": "三"}) == {"z1"}
        assert usernames({"q": ""}) == {"z1", "l1"}      # 缺省/空白 → 与旧行为一致
        assert usernames({"q": "不存在"}) == set()
        # 别人的名单不会漏进来
        assert usernames({"q": "张小三"}) == set()
        assert {r["username"] for r in
                client.get("/api/teacher/students", headers=h_teacher2).json()} == {"other1"}

        # BoundStudentOut 的字段全集（含 LI-02 徽标与层 1 组别）
        resp = client.get("/api/teacher/students", headers=h_teacher).json()
        assert set(resp[0]) == {"id", "username", "display_name", "is_active",
                                "must_change_password", "groups", "source"}
        # 层 3 直绑的学生来源为 manual（组别派生的才是 group）
        assert {r["source"] for r in resp} == {"manual"}
