"""v2.0 批次 API 测试：学生分组 / 批量操作 / 题目草稿 / 权限红线。

范围说明：本文件只覆盖「分组、批量、草稿、权限红线」；xlsx/txt/csv 导入与成绩导出
不在本文件内（由导入导出专项测试负责）。

契约以代码实际行为为准（app/api/admin.py、app/api/teacher.py、app/services/groups.py、
app/schemas.py、app/main.py），要点：
- 错误响应体统一为 ``{"code": "...", "message": "..."}``（app/main.py 两个 exception_handler），
  无 HTTP status 字段；pydantic 校验失败也走 422 + code=VALIDATION_ERROR。
- 分组：``GroupOut{id,name,created_at,member_count}``；``GroupCreate/GroupUpdate{name}``（1~50 字）。
  重名 409 GROUP_NAME_EXISTS；不存在 404 GROUP_NOT_FOUND；名超 50 字由 schema ``max_length``
  拦成 422 VALIDATION_ERROR（``GROUP_NAME_INVALID`` 分支因此不可达）。
- 批量成员：``GroupMembersRequest{student_ids[],group_ids[],action:"add"|"remove"}`` →
  ``GroupMembershipOut{success_count}``，success_count 是**实际写入/删除的「学生×组」条数**
  （幂等重复 add 为 0）。admin 侧先 ``validate_student_ids``（422 INVALID_STUDENT_IDS /
  EMPTY_SELECTION）再 ``apply_membership``（404 GROUP_NOT_FOUND / 422），任一不合法整批拒绝。
- 教师批量成员：先校验 student_ids ⊆ 绑定学生，否则 403 STUDENT_NOT_BOUND（整批取消）。
- 批量重置密码 ``BatchResetPasswordRequest{student_ids[],new_password(≥6)}`` → ``SuccessOut{success}``；
  批量启停 ``BatchActiveRequest{student_ids[],is_active}`` → ``SuccessOut{success}``。
- 学生列表 groups 字段：admin ``StudentOut{...,teachers[],groups[]}``、教师
  ``BoundStudentOut{id,username,display_name,is_active,groups[]}``，``GroupRef{id,name}``。
- 草稿：``PUT /api/teacher/problems/{id}/draft`` body=ProblemDraft →
  ``ProblemDraftSavedOut{ok,draft_saved_at}``；``GET /api/teacher/problems/{id}`` 带
  ``draft`` + ``draft_saved_at``；``DELETE`` 同路径返回 ``{"ok": true}``；
  ``PUT /api/teacher/problems/{id}`` 成功后服务端清空两字段。归属校验走
  ``_get_owned_problem``：题目不存在 404 PROBLEM_NOT_FOUND，非本人题目 403 FORBIDDEN。
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import admin as admin_api
from app.api import teacher as teacher_api
from app.core.security import create_token, hash_password
from app.main import app
from app.models import Group, GroupMember, Problem, TeacherStudent, User

# 已知密码：种子数据共用一次 bcrypt（cost=12 约 250ms），避免每个学生都算一次
STUDENT_PWD = "pw123456"
NEW_PWD = "brand-new-9"

_SHARED_HASH: str | None = None


def shared_hash() -> str:
    global _SHARED_HASH
    if _SHARED_HASH is None:
        _SHARED_HASH = hash_password(STUDENT_PWD)
    return _SHARED_HASH


# ---------- 测试用数据工厂（直接写库，绕开 bcrypt 与接口开销）----------

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def seed_students(db, n, *, prefix="stu", bind_to=(), password_hash=None):
    """建 n 个学生；bind_to 传入的教师会与学生建立 teacher_students 绑定。"""
    users = []
    for i in range(1, n + 1):
        users.append(User(
            username=f"{prefix}{i}",
            password_hash=password_hash or shared_hash(),
            role="student",
            display_name=f"学生{prefix}{i}",
        ))
    db.add_all(users)
    db.flush()
    for teacher in bind_to:
        for user in users:
            db.add(TeacherStudent(teacher_id=teacher.id, student_id=user.id))
    db.commit()
    for user in users:
        db.refresh(user)
    return users


def seed_group(db, name):
    return _add(db, Group(name=name))


def seed_group_member(db, group, student):
    return _add(db, GroupMember(group_id=group.id, student_id=student.id))


# ---------- 读库断言辅助 ----------

def fresh(db):
    """结束测试会话的事务：SQLite WAL 下不结束事务会一直读到旧快照，
    同时让 ORM 身份映射里的旧值过期，确保读到 TestClient 已提交的最新行。"""
    db.commit()
    db.expire_all()


def scalar(db, sql, **params):
    fresh(db)
    return db.execute(text(sql), params).scalar()


def member_pairs(db):
    """group_members 全表快照，用于「整批拒绝 = 库里没有新增行」这类硬断言。"""
    fresh(db)
    rows = db.execute(text("SELECT group_id, student_id FROM group_members")).all()
    return {(g, s) for g, s in rows}


def group_names_of(item):
    return {g["name"] for g in item["groups"]}


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def code_of(resp):
    return resp.json().get("code")


# ---------- fixtures ----------

@pytest.fixture()
def client(db):
    # 依赖 db：先建好表结构再发请求（TestClient 里的接口用的是同一个临时库）
    return TestClient(app)


@pytest.fixture()
def admin_user(db):
    return _add(db, User(username="admin001", password_hash="x", role="admin", display_name="管理员"))


@pytest.fixture()
def teacher2(db):
    return _add(db, User(username="t002", password_hash="x", role="teacher", display_name="李老师"))


@pytest.fixture()
def h_admin(admin_user):
    return bearer(admin_user)


@pytest.fixture()
def h_teacher(teacher):
    return bearer(teacher)


@pytest.fixture()
def h_teacher2(teacher2):
    return bearer(teacher2)


# ---------- 1. 权限红线：教师端零密码能力 ----------

# 教师 token 打这些路径必须 404/405（路由压根不存在），不能退化成 401/403 之类“存在但没权限”
TEACHER_PASSWORD_PATHS = [
    ("post", "/api/teacher/students/reset_password"),
    ("post", "/api/teacher/students/batch_reset_password"),
    ("post", "/api/teacher/students/1/reset_password"),
    ("post", "/api/teacher/students/999/resetPassword"),
    ("post", "/api/teacher/teachers/1/reset_password"),
    ("post", "/api/teacher/teachers/1/batch_reset_password"),
    ("post", "/api/teacher/reset_password"),
    ("post", "/api/teacher/password"),
    ("get", "/api/teacher/students/reset_password"),
    ("put", "/api/teacher/students/batch_reset_password"),
    ("delete", "/api/teacher/students/reset_password"),
]


class TestPasswordRedLine:
    @pytest.mark.parametrize("method,path", TEACHER_PASSWORD_PATHS)
    def test_teacher_token_hits_no_password_route(self, client, h_teacher, method, path):
        # 先确认目标教师账号是活的（排除 403 USER_DISABLED 之类的干扰）
        assert client.get("/api/auth/me", headers=h_teacher).status_code == 200
        resp = client.request(method.upper(), path, headers=h_teacher,
                              json={"new_password": NEW_PWD})
        assert resp.status_code in (404, 405), (method, path, resp.status_code, resp.text)

    def test_no_password_route_registered_under_teacher_api(self):
        paths = app.openapi()["paths"]
        leaky = [p for p in paths if p.startswith("/api/teacher") and "password" in p.lower()]
        assert leaky == []
        # 密码能力只挂在 admin / auth 两侧
        password_paths = {p for p in paths if "password" in p.lower()}
        assert password_paths == {
            "/api/auth/password",
            "/api/admin/students/{student_id}/reset_password",
            "/api/admin/teachers/{teacher_id}/reset_password",
            "/api/admin/students/batch_reset_password",
        }

    def test_teacher_module_imports_no_password_capability(self):
        # 红线：api/teacher.py 不 import 任何密码相关能力（见该模块第 21 行注释）
        assert not hasattr(teacher_api, "hash_password")
        assert not hasattr(teacher_api, "verify_password")
        assert not hasattr(teacher_api, "ResetPasswordRequest")
        assert not hasattr(teacher_api, "BatchResetPasswordRequest")
        assert "hash_password" not in dir(teacher_api)

    @pytest.mark.parametrize("path", [
        "/api/admin/students/batch_reset_password",
        "/api/admin/students/1/reset_password",
        "/api/admin/teachers/1/reset_password",
    ])
    def test_password_routes_reject_teacher_token(self, client, h_teacher, path):
        resp = client.post(path, headers=h_teacher, json={"new_password": NEW_PWD, "student_ids": [1]})
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "FORBIDDEN"

    def test_admin_can_batch_reset(self, client, db, h_admin):
        s = seed_students(db, 1, prefix="adm")[0]
        resp = client.post("/api/admin/students/batch_reset_password", headers=h_admin,
                           json={"student_ids": [s.id], "new_password": NEW_PWD})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        assert login(client, s.username, NEW_PWD).status_code == 200


# ---------- 2/3. 教师端批量成员关系 ----------

class TestTeacherMembership:
    def test_unbound_students_rejected_403_and_no_rows_written(self, client, db, teacher, teacher2,
                                                               h_teacher, h_admin):
        mine, theirs = seed_students(db, 1, prefix="mine", bind_to=[teacher])[0], \
            seed_students(db, 1, prefix="theirs", bind_to=[teacher2])[0]
        group = seed_group(db, "实验班")
        before = member_pairs(db)
        assert before == set()

        resp = client.post("/api/teacher/students/group_members", headers=h_teacher, json={
            "student_ids": [mine.id, theirs.id], "group_ids": [group.id], "action": "add",
        })
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "STUDENT_NOT_BOUND"
        # 关键：不能只看状态码，必须确认库里一行都没写进去（含被合法绑定的那个学生）
        assert member_pairs(db) == before
        assert scalar(db, "SELECT COUNT(*) FROM group_members") == 0
        rows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        assert group_names_of(rows[mine.id]) == set()
        # admin 侧列表同样看不到幽灵成员
        admin_rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert admin_rows[theirs.id]["groups"] == []

    def test_mixed_batch_is_all_or_nothing_even_for_remove(self, client, db, teacher, teacher2,
                                                           h_teacher):
        mine = seed_students(db, 1, prefix="mine", bind_to=[teacher])[0]
        foreign = seed_students(db, 1, prefix="foreign", bind_to=[teacher2])[0]
        group = seed_group(db, "A班")
        seed_group_member(db, group, mine)
        assert member_pairs(db) == {(group.id, mine.id)}

        resp = client.post("/api/teacher/students/group_members", headers=h_teacher, json={
            "student_ids": [mine.id, foreign.id], "group_ids": [group.id], "action": "remove",
        })
        assert resp.status_code == 403
        assert code_of(resp) == "STUDENT_NOT_BOUND"
        # 已存在的成员关系也没被顺手删掉
        assert member_pairs(db) == {(group.id, mine.id)}

    def test_empty_selection_is_422(self, client, db, teacher, h_teacher):
        mine = seed_students(db, 1, prefix="mine", bind_to=[teacher])[0]
        group = seed_group(db, "A班")
        for body in (
            {"student_ids": [], "group_ids": [group.id], "action": "add"},
            {"student_ids": [mine.id], "group_ids": [], "action": "add"},
        ):
            resp = client.post("/api/teacher/students/group_members", headers=h_teacher, json=body)
            assert resp.status_code == 422, body
            assert code_of(resp) == "EMPTY_SELECTION"
        assert member_pairs(db) == set()

    def test_add_and_remove_for_bound_students_reflects_in_both_lists(self, client, db, teacher,
                                                                      h_teacher, h_admin):
        g1, g2 = seed_group(db, "一班"), seed_group(db, "二班")
        s1, s2 = seed_students(db, 2, prefix="b", bind_to=[teacher])
        ids = [s1.id, s2.id]

        resp = client.post("/api/teacher/students/group_members", headers=h_teacher, json={
            "student_ids": ids, "group_ids": [g1.id, g2.id], "action": "add",
        })
        assert resp.status_code == 200, resp.text
        # 2 学生 × 2 组 = 4 条成员关系
        assert resp.json() == {"success_count": 4}
        assert member_pairs(db) == {(g.id, s.id) for g in (g1, g2) for s in (s1, s2)}

        teacher_rows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        admin_rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        for sid in ids:
            assert group_names_of(teacher_rows[sid]) == {"一班", "二班"}
            assert group_names_of(admin_rows[sid]) == {"一班", "二班"}
        counts = {g["name"]: g["member_count"] for g in
                  client.get("/api/teacher/groups", headers=h_teacher).json()}
        assert counts == {"一班": 2, "二班": 2}
        admin_counts = {g["name"]: g["member_count"] for g in
                        client.get("/api/admin/groups", headers=h_admin).json()}
        assert admin_counts == counts

        # 移出其中一个组
        resp = client.post("/api/teacher/students/group_members", headers=h_teacher, json={
            "student_ids": ids, "group_ids": [g2.id], "action": "remove",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2}
        assert member_pairs(db) == {(g1.id, s1.id), (g1.id, s2.id)}
        teacher_rows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        admin_rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        for sid in ids:
            assert group_names_of(teacher_rows[sid]) == {"一班"}
            assert group_names_of(admin_rows[sid]) == {"一班"}
            assert {g["id"] for g in admin_rows[sid]["groups"]} == {g1.id}
        counts = {g["name"]: g["member_count"] for g in
                  client.get("/api/admin/groups", headers=h_admin).json()}
        assert counts == {"一班": 2, "二班": 0}

    def test_group_definitions_are_readonly_for_teacher(self, client, db, teacher, h_teacher, h_admin):
        group = seed_group(db, "只读班")
        resp = client.get("/api/teacher/groups", headers=h_teacher)
        assert resp.status_code == 200
        assert resp.json() == [{
            "id": group.id, "name": "只读班", "created_at": group.created_at, "member_count": 0,
        }]
        # 组本身的增删改仅 admin
        for method, path, body in (
            ("post", "/api/admin/groups", {"name": "教师建班"}),
            ("patch", f"/api/admin/groups/{group.id}", {"name": "教师改名"}),
            ("delete", f"/api/admin/groups/{group.id}", None),
        ):
            resp = client.request(method.upper(), path, headers=h_teacher,
                                  json=body)
            assert resp.status_code == 403, (method, path, resp.text)
            assert code_of(resp) == "FORBIDDEN"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 1
        assert client.get("/api/admin/groups", headers=h_admin).json()[0]["name"] == "只读班"


# ---------- 4. admin 分组 CRUD ----------

class TestAdminGroupsCrud:
    def test_create_group_ok_and_duplicate_409(self, client, db, h_admin):
        resp = client.post("/api/admin/groups", headers=h_admin, json={"name": "创新班"})
        assert resp.status_code == 200, resp.text
        created = resp.json()
        assert created["name"] == "创新班"
        assert created["member_count"] == 0
        assert created["id"] > 0
        assert set(created) == {"id", "name", "created_at", "member_count"}

        dup = client.post("/api/admin/groups", headers=h_admin, json={"name": "创新班"})
        assert dup.status_code == 409
        assert code_of(dup) == "GROUP_NAME_EXISTS"
        # 名称带空白先 strip 再比：等价于重名
        spaced = client.post("/api/admin/groups", headers=h_admin, json={"name": "  创新班  "})
        assert spaced.status_code == 409
        assert code_of(spaced) == "GROUP_NAME_EXISTS"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 1

        listed = client.get("/api/admin/groups", headers=h_admin).json()
        assert [g["name"] for g in listed] == ["创新班"]

    def test_create_group_name_length_limit(self, client, db, h_admin):
        ok = client.post("/api/admin/groups", headers=h_admin, json={"name": "班" * 50})
        assert ok.status_code == 200, ok.text
        assert ok.json()["name"] == "班" * 50

        too_long = client.post("/api/admin/groups", headers=h_admin, json={"name": "班" * 51})
        assert too_long.status_code == 422
        assert code_of(too_long) == "VALIDATION_ERROR"
        # 全空白名：schema min_length=1 放行，端点 strip 后拒绝
        blank = client.post("/api/admin/groups", headers=h_admin, json={"name": "   "})
        assert blank.status_code == 422
        assert code_of(blank) == "VALIDATION_ERROR"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 1

    def test_rename_group_success_not_found_and_clash(self, client, db, h_admin):
        g_a, g_b = seed_group(db, "甲班"), seed_group(db, "乙班")
        student = seed_students(db, 1, prefix="r")[0]
        seed_group_member(db, g_a, student)

        resp = client.patch(f"/api/admin/groups/{g_a.id}", headers=h_admin, json={"name": "甲班改"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "id": g_a.id, "name": "甲班改", "created_at": g_a.created_at, "member_count": 1,
        }
        assert scalar(db, "SELECT name FROM groups WHERE id=:i", i=g_a.id) == "甲班改"
        # 重命名不影响成员关系
        assert member_pairs(db) == {(g_a.id, student.id)}

        missing = client.patch("/api/admin/groups/99999", headers=h_admin, json={"name": "幽灵班"})
        assert missing.status_code == 404
        assert code_of(missing) == "GROUP_NOT_FOUND"

        clash = client.patch(f"/api/admin/groups/{g_a.id}", headers=h_admin, json={"name": "乙班"})
        assert clash.status_code == 409
        assert code_of(clash) == "GROUP_NAME_EXISTS"
        # 409 后原名保持不变
        assert scalar(db, "SELECT name FROM groups WHERE id=:i", i=g_a.id) == "甲班改"
        assert scalar(db, "SELECT name FROM groups WHERE id=:i", i=g_b.id) == "乙班"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 2

    def test_delete_group_removes_memberships_only_for_that_group(self, client, db, h_admin):
        doomed, keeper = seed_group(db, "解散班"), seed_group(db, "留下班")
        doomed_id, keeper_id = doomed.id, keeper.id
        s1, s2 = seed_students(db, 2, prefix="d")
        seed_group_member(db, doomed, s1)
        seed_group_member(db, doomed, s2)
        seed_group_member(db, keeper, s1)
        assert member_pairs(db) == {(doomed_id, s1.id), (doomed_id, s2.id), (keeper_id, s1.id)}

        resp = client.delete(f"/api/admin/groups/{doomed_id}", headers=h_admin)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        # 级联：解散班的成员关系全部消失，留下班不受影响
        assert member_pairs(db) == {(keeper_id, s1.id)}
        assert scalar(db, "SELECT COUNT(*) FROM group_members WHERE group_id=:g", g=doomed_id) == 0
        assert scalar(db, "SELECT COUNT(*) FROM groups WHERE id=:g", g=doomed_id) == 0
        assert code_of(client.delete("/api/admin/groups/99999", headers=h_admin)) == "GROUP_NOT_FOUND"

        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert group_names_of(rows[s1.id]) == {"留下班"}
        assert group_names_of(rows[s2.id]) == set()
        assert [g["name"] for g in client.get("/api/admin/groups", headers=h_admin).json()] == ["留下班"]


# ---------- 5/6. admin 批量成员：幂等与整批拒绝 ----------

class TestAdminBatchMembership:
    def test_repeated_add_is_idempotent(self, client, db, h_admin):
        group = seed_group(db, "幂等班")
        s1, s2 = seed_students(db, 2, prefix="i")
        body = {"student_ids": [s1.id, s2.id], "group_ids": [group.id], "action": "add"}

        first = client.post("/api/admin/students/group_members", headers=h_admin, json=body)
        assert first.status_code == 200, first.text
        assert first.json() == {"success_count": 2}
        second = client.post("/api/admin/students/group_members", headers=h_admin, json=body)
        assert second.status_code == 200, second.text
        # 第二次不报错，且实际写入 0 条
        assert second.json() == {"success_count": 0}
        # 复合主键下没有重复行
        assert member_pairs(db) == {(group.id, s1.id), (group.id, s2.id)}
        assert scalar(db, "SELECT COUNT(*) FROM group_members") == 2
        counts = {g["name"]: g["member_count"] for g in
                  client.get("/api/admin/groups", headers=h_admin).json()}
        assert counts == {"幂等班": 2}

        # 请求体自身带重复 ID 也只写一份
        dup = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [s1.id, s1.id, s2.id], "group_ids": [group.id, group.id], "action": "add",
        })
        assert dup.status_code == 200, dup.text
        assert dup.json() == {"success_count": 0}
        assert scalar(db, "SELECT COUNT(*) FROM group_members") == 2

    def test_unknown_group_id_rejects_whole_batch_404(self, client, db, h_admin):
        real, other = seed_group(db, "真班"), seed_group(db, "另一个班")
        students = seed_students(db, 3, prefix="g")
        ids = [s.id for s in students]
        # 只传不存在的组 → 404
        resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": ids, "group_ids": [99999], "action": "add",
        })
        assert resp.status_code == 404, resp.text
        assert code_of(resp) == "GROUP_NOT_FOUND"
        # 存在 + 不存在的组混在一起 → 仍整批拒绝，真组也不写
        mixed = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": ids, "group_ids": [real.id, 88888, other.id], "action": "add",
        })
        assert mixed.status_code == 404
        assert code_of(mixed) == "GROUP_NOT_FOUND"
        assert member_pairs(db) == set()
        counts = {g["name"]: g["member_count"] for g in
                  client.get("/api/admin/groups", headers=h_admin).json()}
        assert counts == {"真班": 0, "另一个班": 0}

    def test_non_student_id_rejects_whole_batch_422(self, client, db, h_admin, teacher, admin_user):
        group = seed_group(db, "校验班")
        students = seed_students(db, 2, prefix="v")
        for bad_id in (teacher.id, admin_user.id, 123456):
            resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
                "student_ids": [students[0].id, students[1].id, bad_id],
                "group_ids": [group.id],
                "action": "add",
            })
            assert resp.status_code == 422, (bad_id, resp.text)
            assert code_of(resp) == "INVALID_STUDENT_IDS"
        assert member_pairs(db) == set()
        # 学生非法 + 组非法同时出现时，admin 侧先做学生校验 → 422
        both_bad = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [admin_user.id], "group_ids": [99999], "action": "add",
        })
        assert both_bad.status_code == 422
        assert code_of(both_bad) == "INVALID_STUDENT_IDS"

    def test_invalid_action_is_422(self, client, db, h_admin):
        group = seed_group(db, "动作班")
        student = seed_students(db, 1, prefix="a")[0]
        resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [student.id], "group_ids": [group.id], "action": "set",
        })
        assert resp.status_code == 422
        assert code_of(resp) == "VALIDATION_ERROR"
        assert member_pairs(db) == set()

    def test_batch_group_members_reflects_admin_side_cartesian(self, client, db, h_admin):
        """admin 端与学生列表的 groups 字段（多组模型）。"""
        g1, g2, g3 = (seed_group(db, n) for n in ("1组", "2组", "3组"))
        s1, s2 = seed_students(db, 2, prefix="m")
        resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [s1.id, s2.id], "group_ids": [g1.id, g2.id, g3.id], "action": "add",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 6}
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        for sid in (s1.id, s2.id):
            assert group_names_of(rows[sid]) == {"1组", "2组", "3组"}
            # 列表里 groups 按组名排序（groups_map_for_students 的 ORDER BY Group.name）
            assert [g["name"] for g in rows[sid]["groups"]] == ["1组", "2组", "3组"]
        # 移走两个组
        resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [s1.id], "group_ids": [g1.id, g2.id], "action": "remove",
        })
        assert resp.json() == {"success_count": 2}
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert group_names_of(rows[s1.id]) == {"3组"}
        assert group_names_of(rows[s2.id]) == {"1组", "2组", "3组"}


# ---------- 7. 批量重置密码：一次 bcrypt ----------

class TestBatchResetPassword:
    def test_hashes_once_for_whole_batch_and_all_can_login(self, client, db, h_admin, monkeypatch):
        batch = seed_students(db, 5, prefix="p")
        outsider = seed_students(db, 1, prefix="out")[0]
        outsider_hash = outsider.password_hash
        batch_hashes = {s.id: s.password_hash for s in batch}

        calls = []
        real_hash = admin_api.hash_password

        def spy(password):
            calls.append(password)
            return real_hash(password)

        monkeypatch.setattr(admin_api, "hash_password", spy)

        resp = client.post("/api/admin/students/batch_reset_password", headers=h_admin,
                           json={"student_ids": [s.id for s in batch], "new_password": NEW_PWD})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        # 核心断言：5 个学生只算一次 bcrypt
        assert len(calls) == 1, calls
        assert calls == [NEW_PWD]

        fresh(db)
        stored = {s.id: db.get(User, s.id).password_hash for s in batch}
        # 同一个 hash 复用到 N 行
        assert len(set(stored.values())) == 1
        assert all(h != batch_hashes[sid] for sid, h in stored.items())
        # 未参与本批的学生密码不变
        assert db.get(User, outsider.id).password_hash == outsider_hash

        for student in batch:
            ok = login(client, student.username, NEW_PWD)
            assert ok.status_code == 200, (student.username, ok.text)
            assert ok.json()["user"]["username"] == student.username
        # 旧密码全部失效
        for student in batch:
            stale = login(client, student.username, STUDENT_PWD)
            assert stale.status_code == 401
            assert code_of(stale) == "BAD_CREDENTIALS"

    def test_invalid_batch_rejected_before_any_hashing(self, client, db, h_admin, admin_user, monkeypatch):
        students = seed_students(db, 3, prefix="q")
        calls = []
        real_hash = admin_api.hash_password
        monkeypatch.setattr(admin_api, "hash_password", lambda pw: calls.append(pw) or real_hash(pw))

        resp = client.post("/api/admin/students/batch_reset_password", headers=h_admin,
                           json={"student_ids": [students[0].id, admin_user.id],
                                 "new_password": NEW_PWD})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "INVALID_STUDENT_IDS"
        assert calls == []
        fresh(db)
        for student in students:
            assert db.get(User, student.id).password_hash == student.password_hash
        # 密码太短：schema 层 422
        short = client.post("/api/admin/students/batch_reset_password", headers=h_admin,
                            json={"student_ids": [students[0].id], "new_password": "123"})
        assert short.status_code == 422
        assert code_of(short) == "VALIDATION_ERROR"
        assert calls == []
        assert login(client, students[0].username, STUDENT_PWD).status_code == 200

    def test_single_student_reset_still_works(self, client, db, h_admin):
        student = seed_students(db, 1, prefix="one")[0]
        resp = client.post(f"/api/admin/students/{student.id}/reset_password", headers=h_admin,
                           json={"new_password": NEW_PWD})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        assert login(client, student.username, NEW_PWD).status_code == 200
        missing = client.post("/api/admin/students/99999/reset_password", headers=h_admin,
                              json={"new_password": NEW_PWD})
        assert missing.status_code == 404
        assert code_of(missing) == "NOT_FOUND"


# ---------- 8. 批量启停 ----------

class TestBatchActive:
    def test_deactivate_blocks_login_and_reactivate_restores_it(self, client, db, h_admin, h_teacher,
                                                                teacher):
        s1, s2 = seed_students(db, 2, prefix="act", bind_to=[teacher])
        kept = seed_students(db, 1, prefix="keep")[0]
        assert login(client, s1.username, STUDENT_PWD).status_code == 200

        resp = client.post("/api/admin/students/batch_active", headers=h_admin,
                           json={"student_ids": [s1.id, s2.id], "is_active": False})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        fresh(db)
        assert {db.get(User, s.id).is_active for s in (s1, s2)} == {0}
        assert db.get(User, kept.id).is_active == 1

        # 停用后无法登录
        for student in (s1, s2):
            blocked = login(client, student.username, STUDENT_PWD)
            assert blocked.status_code == 403, student.username
            assert code_of(blocked) == "USER_DISABLED"
        # 已签发的令牌同样立即失效
        stale_token = bearer(s1)
        me = client.get("/api/auth/me", headers=stale_token)
        assert me.status_code == 403
        assert code_of(me) == "USER_DISABLED"
        # 未入选学生不受影响
        assert login(client, kept.username, STUDENT_PWD).status_code == 200

        # 列表接口反映 is_active
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert (rows[s1.id]["is_active"], rows[kept.id]["is_active"]) == (0, 1)
        trows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        assert (trows[s1.id]["is_active"], trows[s2.id]["is_active"]) == (0, 0)

        back = client.post("/api/admin/students/batch_active", headers=h_admin,
                           json={"student_ids": [s1.id], "is_active": True})
        assert back.status_code == 200, back.text
        assert login(client, s1.username, STUDENT_PWD).status_code == 200
        assert login(client, s2.username, STUDENT_PWD).status_code == 403

    def test_batch_active_validation_and_permissions(self, client, db, h_admin, h_teacher, teacher,
                                                    admin_user):
        students = seed_students(db, 2, prefix="ba", bind_to=[teacher])
        for path, headers in (
            ("/api/admin/students/batch_active", h_teacher),
            ("/api/admin/students/batch_reset_password", h_teacher),
            ("/api/admin/students/group_members", h_teacher),
        ):
            forbidden = client.post(path, headers=headers, json={
                "student_ids": [students[0].id], "is_active": False, "new_password": NEW_PWD,
                "group_ids": [], "action": "add",
            })
            assert forbidden.status_code == 403, (path, forbidden.text)
            assert code_of(forbidden) == "FORBIDDEN"

        empty = client.post("/api/admin/students/batch_active", headers=h_admin,
                            json={"student_ids": [], "is_active": False})
        assert empty.status_code == 422
        assert code_of(empty) == "EMPTY_SELECTION"
        bad = client.post("/api/admin/students/batch_active", headers=h_admin,
                          json={"student_ids": [admin_user.id], "is_active": False})
        assert bad.status_code == 422
        assert code_of(bad) == "INVALID_STUDENT_IDS"
        fresh(db)
        for student in students:
            assert db.get(User, student.id).is_active == 1
        assert db.get(User, admin_user.id).is_active == 1


# ---------- 9. 题目草稿 ----------

DRAFT_A = {
    "title": "草稿标题A",
    "description": "草稿描述A，还没写完",
    "input_format": "一行两个整数",
    "output_format": "一行一个整数",
    "time_limit_ms": 1500,
    "memory_limit_mb": 128,
    "compare_mode": "float",
    "float_eps": 1e-05,
    "group_name": "草稿组A",
}

DRAFT_B = {
    "title": "草稿标题B",
    "description": "只改了标题",
    "input_format": "",
    "output_format": "",
    "time_limit_ms": 1000,
    "memory_limit_mb": 256,
    "compare_mode": "trim",
    "float_eps": None,
    "group_name": None,
}


class TestProblemDraft:
    def test_put_then_get_reads_back_every_field(self, client, db, problem, h_teacher):
        # 初始无草稿
        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] is None
        assert detail["draft_saved_at"] is None

        resp = client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_A)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"ok", "draft_saved_at"}
        assert body["ok"] is True
        # draft_saved_at 是 UTC "%Y-%m-%d %H:%M:%S"
        datetime.strptime(body["draft_saved_at"], "%Y-%m-%d %H:%M:%S")

        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] == DRAFT_A          # 字段逐一对上
        assert detail["draft_saved_at"] == body["draft_saved_at"]
        # 正式题面未被草稿污染
        assert detail["title"] == problem.title
        assert detail["time_limit_ms"] == problem.time_limit_ms
        assert detail["compare_mode"] == problem.compare_mode
        # 库里存的就是那份 JSON
        fresh(db)
        raw = db.get(Problem, problem.id).draft
        assert "草稿标题A" in raw and '"time_limit_ms": 1500' in raw
        assert db.get(Problem, problem.id).draft_saved_at == body["draft_saved_at"]

    def test_new_draft_overwrites_the_only_slot(self, client, db, problem, h_teacher):
        client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_A)
        second = client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_B)
        assert second.status_code == 200, second.text

        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] == DRAFT_B
        assert detail["draft_saved_at"] == second.json()["draft_saved_at"]
        # 每题目只有一份草稿：旧内容彻底不见，problems 里带草稿的行也只有这一条
        assert "草稿标题A" not in detail["draft"]["title"]
        fresh(db)
        raw = db.get(Problem, problem.id).draft
        assert "草稿标题A" not in raw
        assert scalar(db, "SELECT COUNT(*) FROM problems WHERE draft IS NOT NULL") == 1

    def test_delete_clears_both_columns(self, client, db, problem, h_teacher):
        client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_A)
        resp = client.delete(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True}
        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] is None
        assert detail["draft_saved_at"] is None
        fresh(db)
        row = db.get(Problem, problem.id)
        assert row.draft is None and row.draft_saved_at is None
        # 重复删除幂等
        assert client.delete(f"/api/teacher/problems/{problem.id}/draft",
                             headers=h_teacher).status_code == 200

    def test_saving_problem_clears_draft_server_side(self, client, db, problem, h_teacher):
        client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_A)
        resp = client.put(f"/api/teacher/problems/{problem.id}", headers=h_teacher,
                          json={"title": "正式保存的标题"})
        assert resp.status_code == 200, resp.text
        saved = resp.json()
        assert saved["title"] == "正式保存的标题"
        assert "draft" not in saved and "draft_saved_at" not in saved  # ProblemOut 不含草稿字段

        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] is None
        assert detail["draft_saved_at"] is None
        fresh(db)
        row = db.get(Problem, problem.id)
        assert row.draft is None and row.draft_saved_at is None

    def test_draft_validation_and_dirty_data(self, client, db, problem, cases, h_teacher):
        bad_mode = dict(DRAFT_A, compare_mode="regex")
        resp = client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=bad_mode)
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "VALIDATION_ERROR"
        assert client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()["draft"] is None

        # 脏 JSON（非草稿结构）按“无草稿”处理，编辑页不该打不开
        fresh(db)
        row = db.get(Problem, problem.id)
        row.draft = "{ 这不是 JSON"
        row.draft_saved_at = "2026-01-01 00:00:00"
        db.commit()
        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["draft"] is None
        # 用例照常返回，详情接口整体可用
        assert [c["seq"] for c in detail["cases"]] == [1, 2]


# ---------- 10. 草稿越权 ----------

class TestDraftPermissions:
    def test_other_teacher_cannot_read_write_or_delete_draft(self, client, db, problem, teacher,
                                                             teacher2, h_teacher, h_teacher2):
        client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher, json=DRAFT_A)
        saved_at = client.get(f"/api/teacher/problems/{problem.id}",
                              headers=h_teacher).json()["draft_saved_at"]

        read = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher2)
        assert read.status_code == 403, read.text
        assert code_of(read) == "FORBIDDEN"

        write = client.put(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher2,
                           json=DRAFT_B)
        assert write.status_code == 403, write.text
        assert code_of(write) == "FORBIDDEN"

        delete = client.delete(f"/api/teacher/problems/{problem.id}/draft", headers=h_teacher2)
        assert delete.status_code == 403, delete.text
        assert code_of(delete) == "FORBIDDEN"

        save = client.put(f"/api/teacher/problems/{problem.id}", headers=h_teacher2,
                          json={"title": "抢注标题"})
        assert save.status_code == 403, save.text

        # 别人的失败尝试没有动到题面与草稿
        detail = client.get(f"/api/teacher/problems/{problem.id}", headers=h_teacher).json()
        assert detail["title"] == problem.title
        assert detail["draft"] == DRAFT_A
        assert detail["draft_saved_at"] == saved_at
        fresh(db)
        assert db.get(Problem, problem.id).created_by == teacher.id

    def test_draft_on_missing_problem_is_404(self, client, db, h_teacher):
        assert client.get("/api/teacher/problems/424242", headers=h_teacher).status_code == 404
        put = client.put("/api/teacher/problems/424242/draft", headers=h_teacher, json=DRAFT_A)
        assert put.status_code == 404
        assert code_of(put) == "PROBLEM_NOT_FOUND"
        dele = client.delete("/api/teacher/problems/424242/draft", headers=h_teacher)
        assert dele.status_code == 404
        assert code_of(dele) == "PROBLEM_NOT_FOUND"
        assert scalar(db, "SELECT COUNT(*) FROM problems") == 0

    def test_student_token_cannot_touch_teacher_draft_routes(self, client, db, problem, h_admin):
        student = seed_students(db, 1, prefix="peek")[0]
        token = bearer(student)
        # 学生调教师端草稿 → 403 FORBIDDEN（路由存在但角色不符）
        resp = client.put(f"/api/teacher/problems/{problem.id}/draft", headers=token, json=DRAFT_A)
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "FORBIDDEN"
        assert client.get(f"/api/teacher/problems/{problem.id}", headers=token).status_code == 403
        assert client.get(f"/api/teacher/problems/{problem.id}", headers={}).status_code == 401
        assert client.get(f"/api/teacher/problems/{problem.id}",
                          headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
        assert client.get(f"/api/teacher/problems/{problem.id}", headers=h_admin).status_code == 403
        assert code_of(client.get(f"/api/teacher/problems/{problem.id}", headers=h_admin)) == "FORBIDDEN"
        assert client.get(f"/api/teacher/problems/{problem.id}", headers={}).json()["code"] == "UNAUTHORIZED"
