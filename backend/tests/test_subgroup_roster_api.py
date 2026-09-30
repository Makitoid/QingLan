"""0.3.2 批次 B1（F1）后端半：名单并集 / 教师子分组 / 发布受众 / 组别撤销通知。

契约以代码实际行为为准（app/services/groups.py、app/services/stats.py、
app/api/teacher.py、app/api/admin.py、app/api/student.py）：

- **名单口径**（决策 1b/1e）= 可教组成员 ∪ 手动添加（只算 role=student）。
  教师列表、admin 教师列表 student_count、admin 教师详情名单、admin 学生→教师反查、
  逐学生成绩表全部同源；管理员撤销组别后该组学生立即消失，手动添加者仍在。
- **admin 教师详情名单** ``GET /api/admin/teachers/{id}/students`` 返回
  ``{"students": [{id, username, display_name, source, group_names}]}``，
  ``source`` ∈ {'manual','group'}（有手动行即 manual），``group_names`` 为含该生的可教组名。
- **子分组**（教师私有）：``GET/POST /api/teacher/subgroups``、
  ``PATCH/DELETE /api/teacher/subgroups/{id}``、
  ``PUT /api/teacher/subgroups/{id}/students``（``{student_ids}`` 全量替换，⊆ 当前名单）；
  被任何场次引用时删除 → 409 ``SUBGROUP_IN_USE``（消息带场次标题）；
  跨教师访问 → 403/404。审计动作：``subgroup_create/update/delete/member_change``。
- **发布受众**：创建场次可带 ``audience_mode='all'|'subgroup'`` + ``subgroup_ids``；
  ``'subgroup'`` 场次只对白名单成员可见（学生端列表隐藏、详情 404）且逐学生成绩只列成员；
  老数据（缺省 'all'）行为与 0.3.1 一致。
- **组别撤销通知**：``PUT /api/admin/teachers/{id}/groups`` 保存前算差集，有人离开时写
  ``teacher_notices(kind='group_revoked', payload={"groups":[{id,name,lost_count}],"total_lost"})``；
  ``GET /api/teacher/notices/pending`` + ``POST /api/teacher/notices/{id}/dismiss``。
- **unbind 收窄**：只能移手动添加的学生；组别派生 → 422 ``ROSTER_DERIVED_STUDENT``
  （逐条断言在 tests/test_groups_api.py 的既有用例里）。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_token
from app.main import app
from app.models import (AuditLog, Group, GroupMember, Problem, TeacherGroup,
                        TeacherSubgroup, User)

ROSTER_URL = "/api/teacher/students"
BIND_URL = "/api/teacher/students/bind"
SUBGROUPS_URL = "/api/teacher/subgroups"
NOTICES_URL = "/api/teacher/notices/pending"


# ---------- 数据工厂（直接写库的账号一律显式 must_change_password=0，见 PW-02） ----------

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def utc_from_now(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def seed_students(db, n, *, prefix="stu"):
    users = [
        User(username=f"{prefix}{i}", password_hash="x", role="student",
             display_name=f"学生{prefix}{i}", must_change_password=0)
        for i in range(1, n + 1)
    ]
    db.add_all(users)
    db.commit()
    for user in users:
        db.refresh(user)
    return users


def seed_group(db, name):
    return _add(db, Group(name=name))


def assign_group(db, teacher, group):
    return _add(db, TeacherGroup(teacher_id=teacher.id, group_id=group.id))


def seed_problem(db, owner, title="F1题"):
    return _add(db, Problem(title=title, description="输入整数。", input_format="一行",
                            output_format="一行", time_limit_ms=1000, memory_limit_mb=256,
                            compare_mode="trim", created_by=owner.id))


def assignment_body(problem, *, title="F1场次", audience_mode=None, subgroup_ids=None):
    body = {
        "title": title,
        "mode": "homework",
        "start_time": utc_from_now(-1),
        "end_time": utc_from_now(24),
        "score_policy": "best",
        "problems": [{"problem_id": problem.id, "seq": 1, "full_score": 100}],
    }
    if audience_mode is not None:
        body["audience_mode"] = audience_mode
    if subgroup_ids is not None:
        body["subgroup_ids"] = subgroup_ids
    return body


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def fresh(db):
    db.commit()
    db.expire_all()


def scalar(db, sql):
    fresh(db)
    return db.execute(text(sql)).scalar()


def audit_rows(db, action):
    fresh(db)
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


def code_of(resp):
    return resp.json().get("code")


def usernames(resp):
    assert resp.status_code == 200, resp.text
    return [r["username"] for r in resp.json()]


# ---------- fixtures ----------

@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def admin_user(db):
    return _add(db, User(username="admin001", password_hash="x", role="admin",
                         display_name="管理员", must_change_password=0))


@pytest.fixture()
def teacher2(db):
    return _add(db, User(username="t002", password_hash="x", role="teacher",
                         display_name="李老师", must_change_password=0))


@pytest.fixture()
def h_admin(admin_user):
    return bearer(admin_user)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


@pytest.fixture()
def h_teacher2(teacher2):
    return bearer(teacher2)


# ---------- 1. 名单并集（无手动添加时非空）与反查同口径 ----------

class TestRosterUnion:
    def test_group_members_are_roster_without_any_manual_add(self, client, db, teacher,
                                                             h_teacher, h_admin):
        group = seed_group(db, "一班")
        assign_group(db, teacher, group)
        s1, s2 = seed_students(db, 2, prefix="u")
        for student in (s1, s2):
            _add(db, GroupMember(group_id=group.id, student_id=student.id))
        # 关键前提：没有任何 teacher_students 手动行
        assert scalar(db, "SELECT COUNT(*) FROM teacher_students") == 0

        # 教师名单 = 可教组并集
        assert usernames(client.get(ROSTER_URL, headers=h_teacher)) == ["u1", "u2"]
        # admin 教师列表的 student_count 是同一并集口径（否则会显示 0）
        teachers = client.get("/api/admin/teachers", headers=h_admin).json()
        assert [t["student_count"] for t in teachers] == [2]
        # admin 教师详情名单：source=group + 所在可教组名
        assert client.get(f"/api/admin/teachers/{teacher.id}/students",
                          headers=h_admin).json() == {"students": [
            {"id": s1.id, "username": "u1", "display_name": "学生u1",
             "source": "group", "group_names": ["一班"]},
            {"id": s2.id, "username": "u2", "display_name": "学生u2",
             "source": "group", "group_names": ["一班"]},
        ]}
        # admin 学生列表的「所属教师」反查也走并集
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert [t["username"] for t in rows[s1.id]["teachers"]] == ["t001"]

    def test_manual_add_is_source_manual_and_survives_group_revocation(self, client, db, teacher,
                                                                      teacher2, h_teacher,
                                                                      h_teacher2, h_admin):
        group = seed_group(db, "一班")
        assign_group(db, teacher, group)
        in_group, manual_only = seed_students(db, 2, prefix="m")
        _add(db, GroupMember(group_id=group.id, student_id=in_group.id))
        assert client.post(BIND_URL, headers=h_teacher,
                           json={"student_ids": [manual_only.id]}).json() == {"success_count": 1}

        # 手动添加者 source=manual、不在任何可教组里 → group_names 为空
        assert client.get(f"/api/admin/teachers/{teacher.id}/students",
                          headers=h_admin).json()["students"] == [
            {"id": in_group.id, "username": "m1", "display_name": "学生m1",
             "source": "group", "group_names": ["一班"]},
            {"id": manual_only.id, "username": "m2", "display_name": "学生m2",
             "source": "manual", "group_names": []},
        ]

        # 撤销组别：组派生学生立即离开名单（决策 1e），手动添加者不受影响
        assert client.put(f"/api/admin/teachers/{teacher.id}/groups", headers=h_admin,
                          json={"group_ids": []}).status_code == 200
        assert usernames(client.get(ROSTER_URL, headers=h_teacher)) == ["m2"]
        assert scalar(db, "SELECT COUNT(*) FROM teacher_students") == 1
        counts = client.get("/api/admin/teachers", headers=h_admin).json()
        assert next(t for t in counts if t["username"] == "t001")["student_count"] == 1
        # admin 反查：离开名单的这位已不属于任何教师
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert rows[in_group.id]["teachers"] == []

        # 组别撤销通知：payload 精确到「组名 + 离开人数」
        notices = client.get(NOTICES_URL, headers=h_teacher).json()
        assert len(notices) == 1
        notice = notices[0]
        assert set(notice) == {"id", "kind", "payload", "created_at"}
        assert notice["kind"] == "group_revoked"
        assert notice["payload"] == {
            "groups": [{"id": group.id, "name": "一班", "lost_count": 1}],
            "total_lost": 1,
        }
        # 别的教师看不到、也 dismiss 不了我的通知
        assert client.get(NOTICES_URL, headers=h_teacher2).json() == []
        assert client.post(f"/api/teacher/notices/{notice['id']}/dismiss",
                           headers=h_teacher2).status_code == 404
        # 确认后 pending 清空；重复确认幂等；不存在的通知 404
        dismissed = client.post(f"/api/teacher/notices/{notice['id']}/dismiss", headers=h_teacher)
        assert dismissed.status_code == 200 and dismissed.json() == {"ok": True}
        assert client.get(NOTICES_URL, headers=h_teacher).json() == []
        assert client.post(f"/api/teacher/notices/{notice['id']}/dismiss",
                           headers=h_teacher).status_code == 200
        assert client.post("/api/teacher/notices/999999/dismiss",
                           headers=h_teacher).status_code == 404

    def test_revoking_empty_group_writes_no_notice(self, client, db, teacher, h_teacher, h_admin):
        assign_group(db, teacher, seed_group(db, "空班"))
        assert client.put(f"/api/admin/teachers/{teacher.id}/groups", headers=h_admin,
                          json={"group_ids": []}).status_code == 200
        assert client.get(NOTICES_URL, headers=h_teacher).json() == []


# ---------- 2. 子分组 CRUD / 归属校验 ----------

class TestSubgroupCrud:
    def test_crud_audited_and_member_count_follows_roster(self, client, db, teacher, teacher2,
                                                          h_teacher, h_teacher2):
        group = seed_group(db, "一班")
        assign_group(db, teacher, group)
        s1, s2, outsider = seed_students(db, 3, prefix="sg")
        for student in (s1, s2):
            _add(db, GroupMember(group_id=group.id, student_id=student.id))

        created = client.post(SUBGROUPS_URL, headers=h_teacher, json={"name": " 快班 "})
        assert created.status_code == 200, created.text
        assert set(created.json()) == {"id", "name", "created_at", "member_count", "student_ids"}
        assert created.json()["name"] == "快班" and created.json()["member_count"] == 0
        sid = created.json()["id"]

        # 重名 → 409；同名子分组在另一个教师名下合法（UNIQUE 是 teacher_id + name）
        dup = client.post(SUBGROUPS_URL, headers=h_teacher, json={"name": "快班"})
        assert dup.status_code == 409 and code_of(dup) == "SUBGROUP_NAME_EXISTS"
        assert client.post(SUBGROUPS_URL, headers=h_teacher2,
                           json={"name": "快班"}).status_code == 200
        assert [s["name"] for s in client.get(SUBGROUPS_URL, headers=h_teacher2).json()] == ["快班"]

        # 全量替换成员；不在名单里的 outsider → 整批 422（库零变化）
        bad = client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                         json={"student_ids": [s1.id, outsider.id]})
        assert bad.status_code == 422 and code_of(bad) == "INVALID_STUDENT_IDS"
        assert client.get(SUBGROUPS_URL, headers=h_teacher).json()[0]["member_count"] == 0
        ok = client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                        json={"student_ids": [s1.id, s2.id, s1.id]})
        assert ok.status_code == 200, ok.text
        assert ok.json()["student_ids"] == [s1.id, s2.id]
        assert ok.json()["member_count"] == 2
        # 全量替换：只给一个 → 另一个被移出
        assert client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                          json={"student_ids": [s2.id]}).json()["student_ids"] == [s2.id]

        # 改名 + 与另一个子分组重名 → 409
        other = client.post(SUBGROUPS_URL, headers=h_teacher, json={"name": "慢班"}).json()["id"]
        assert client.patch(f"{SUBGROUPS_URL}/{sid}", headers=h_teacher,
                            json={"name": "快班2"}).json()["name"] == "快班2"
        clash = client.patch(f"{SUBGROUPS_URL}/{sid}", headers=h_teacher, json={"name": "慢班"})
        assert clash.status_code == 409 and code_of(clash) == "SUBGROUP_NAME_EXISTS"
        assert client.patch(f"{SUBGROUPS_URL}/{sid}", headers=h_teacher,
                            json={"name": "   "}).status_code == 422

        # 成员与成员数按当前名单口径收窄：撤销组别后 s2 不再计入
        assert client.put(f"/api/admin/teachers/{teacher.id}/groups",
                          headers=bearer(_admin(db)), json={"group_ids": []}).status_code == 200
        listed = {s["id"]: s for s in client.get(SUBGROUPS_URL, headers=h_teacher).json()}
        assert listed[sid]["member_count"] == 0 and listed[sid]["student_ids"] == []

        # 清空成员（空列表合法）+ 删除成功
        assert client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                          json={"student_ids": []}).json()["student_ids"] == []
        gone = client.delete(f"{SUBGROUPS_URL}/{other}", headers=h_teacher)
        assert gone.status_code == 200, gone.text
        assert {s["id"] for s in client.get(SUBGROUPS_URL, headers=h_teacher).json()} == {sid}
        assert client.delete(f"{SUBGROUPS_URL}/999999", headers=h_teacher).status_code == 404

        # 审计动作齐全；手动添加学生仍写 teacher_student_bind（动作名不变）
        for action in ("subgroup_create", "subgroup_update",
                       "subgroup_member_change", "subgroup_delete"):
            assert audit_rows(db, action), action
        # 创建 3 次（含别的教师那次）、删除 1 次、改名 1 次、成员变更 3 次（清空也算）
        assert len(audit_rows(db, "subgroup_create")) == 3
        assert len(audit_rows(db, "subgroup_delete")) == 1
        assert len(audit_rows(db, "subgroup_update")) == 1
        assert len(audit_rows(db, "subgroup_member_change")) == 3
        assert audit_rows(db, "subgroup_create")[0].target_type == "subgroup"
        assert client.post(BIND_URL, headers=h_teacher,
                           json={"student_ids": [outsider.id]}).json() == {"success_count": 1}
        bind_logs = audit_rows(db, "teacher_student_bind")
        assert len(bind_logs) == 1 and bind_logs[0].actor_id == teacher.id


def _admin(db) -> User:
    admin = db.query(User).filter(User.username == "admin001").first()
    if admin is None:
        admin = _add(db, User(username="admin001", password_hash="x", role="admin",
                              display_name="管理员", must_change_password=0))
    return admin


class TestSubgroupDeleteProtection:
    def test_delete_in_use_is_409_and_cross_teacher_is_denied(self, client, db, teacher, teacher2,
                                                              problem, h_teacher, h_teacher2):
        group = seed_group(db, "一班")
        assign_group(db, teacher, group)
        s1 = seed_students(db, 1, prefix="prot")[0]
        _add(db, GroupMember(group_id=group.id, student_id=s1.id))
        sid = client.post(SUBGROUPS_URL, headers=h_teacher, json={"name": "受众组"}).json()["id"]
        client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                   json={"student_ids": [s1.id]})
        created = client.post("/api/teacher/assignments", headers=h_teacher,
                             json=assignment_body(problem, title="引用场次",
                                                  audience_mode="subgroup",
                                                  subgroup_ids=[sid]))
        assert created.status_code == 200, created.text

        # 被引用 → 409，消息里带场次标题；子分组行还在，也不写删除审计
        blocked = client.delete(f"{SUBGROUPS_URL}/{sid}", headers=h_teacher)
        assert blocked.status_code == 409, blocked.text
        assert code_of(blocked) == "SUBGROUP_IN_USE"
        assert "引用场次" in blocked.json()["message"]
        assert scalar(db, "SELECT COUNT(*) FROM teacher_subgroups") == 1
        assert audit_rows(db, "subgroup_delete") == []

        # 跨教师：改名 / 删 / 改成员一律 403/404（不泄露存在性），库零变化
        for method, path, body in (
            ("patch", f"{SUBGROUPS_URL}/{sid}", {"name": "偷改"}),
            ("delete", f"{SUBGROUPS_URL}/{sid}", None),
            ("put", f"{SUBGROUPS_URL}/{sid}/students", {"student_ids": []}),
        ):
            resp = client.request(method.upper(), path, headers=h_teacher2, json=body)
            assert resp.status_code in (403, 404), (method, resp.status_code, resp.text)
        assert client.get(SUBGROUPS_URL, headers=h_teacher2).json() == []
        fresh(db)
        assert db.query(TeacherGroup).count() == 1          # 组分配未被越权操作牵连
        assert db.query(TeacherSubgroup).one().name == "受众组"

        # 拿别人的子分组当发布受众 → 422（不是 403，因为它压根不在你的名下）
        p2 = seed_problem(db, teacher2)
        stolen = client.post("/api/teacher/assignments", headers=h_teacher2,
                             json=assignment_body(p2, audience_mode="subgroup",
                                                  subgroup_ids=[sid]))
        assert stolen.status_code == 422, stolen.text
        assert code_of(stolen) == "SUBGROUP_NOT_FOUND"

        # 'subgroup' 模式不给 subgroup_ids → 422 EMPTY_SELECTION
        empty = client.post("/api/teacher/assignments", headers=h_teacher,
                            json=assignment_body(problem, audience_mode="subgroup",
                                                 subgroup_ids=[]))
        assert empty.status_code == 422 and code_of(empty) == "EMPTY_SELECTION"


# ---------- 3. 发布受众：非成员看不到场次、成绩表只列成员 ----------

class TestSubgroupAudience:
    def test_subgroup_assignment_hidden_from_non_members(self, client, db, teacher, problem,
                                                         h_teacher, h_admin):
        group = seed_group(db, "一班")
        assign_group(db, teacher, group)
        m1, m2, outsider = seed_students(db, 3, prefix="aud")
        for student in (m1, m2, outsider):
            _add(db, GroupMember(group_id=group.id, student_id=student.id))
        sid = client.post(SUBGROUPS_URL, headers=h_teacher, json={"name": "一半"}).json()["id"]
        client.put(f"{SUBGROUPS_URL}/{sid}/students", headers=h_teacher,
                   json={"student_ids": [m1.id, m2.id]})

        created = client.post("/api/teacher/assignments", headers=h_teacher,
                              json=assignment_body(problem, title="子分组场次",
                                                   audience_mode="subgroup",
                                                   subgroup_ids=[sid]))
        assert created.status_code == 200, created.text
        scoped = created.json()
        assert scoped["audience_mode"] == "subgroup" and scoped["subgroup_ids"] == [sid]
        scoped_id = scoped["id"]
        # 缺省（老数据口径）仍是 'all'
        plain = client.post("/api/teacher/assignments", headers=h_teacher,
                            json=assignment_body(problem, title="全班场次")).json()
        assert plain["audience_mode"] == "all" and plain["subgroup_ids"] == []

        # 教师侧：逐学生成绩表与总览都只算子分组内的两人
        assert usernames(client.get(f"/api/teacher/assignments/{scoped_id}/students",
                                    headers=h_teacher)) == ["aud1", "aud2"]
        overview = client.get(f"/api/teacher/assignments/{scoped_id}/overview",
                              headers=h_teacher).json()
        assert overview["total_students"] == 2
        # 'all' 场次仍是全部名单
        assert usernames(client.get(f"/api/teacher/assignments/{plain['id']}/students",
                                    headers=h_teacher)) == ["aud1", "aud2", "aud3"]

        # 学生端：成员可见，非成员在列表里看不到、详情/题目/提交一律 404
        # （两个场次 start_time 同刻，排序按 id 降序，故只比集合）
        assert {a["id"] for a in client.get("/api/student/assignments",
                                            headers=bearer(m1)).json()} == {scoped_id, plain["id"]}
        assert [a["id"] for a in client.get("/api/student/assignments",
                                            headers=bearer(outsider)).json()] == [plain["id"]]
        not_found = client.get(f"/api/student/assignments/{scoped_id}",
                               headers=bearer(outsider))
        assert not_found.status_code == 404 and code_of(not_found) == "ASSIGNMENT_NOT_FOUND"
        assert client.get(f"/api/student/assignments/{scoped_id}/problems/{problem.id}",
                          headers=bearer(outsider)).status_code == 404
        assert client.post(f"/api/student/assignments/{scoped_id}/problems/{problem.id}"
                           "/submissions", headers=bearer(outsider),
                           json={"code_text": "print(1)"}).status_code == 404

        # 撤销组别 → 全员离开名单，'all' 场次对 outsider 也不再可见（名单即受众）
        assert client.put(f"/api/admin/teachers/{teacher.id}/groups", headers=h_admin,
                          json={"group_ids": []}).status_code == 200
        assert client.get("/api/student/assignments", headers=bearer(outsider)).json() == []
        assert client.get(f"/api/teacher/assignments/{plain['id']}/students",
                          headers=h_teacher).json() == []
