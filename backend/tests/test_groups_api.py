"""0.3.0 批次 M6：分组 / 批量操作 / 三层归属名单 / 题目草稿 / 权限红线。

范围说明：本文件只覆盖「分组、批量、教师名单、草稿、权限红线」；xlsx/txt/csv 导入与成绩导出
由 tests/test_import_export.py 负责，auth 侧密码流程由 tests/test_password_flow.py 负责。

契约以代码实际行为为准（app/api/admin.py、app/api/teacher.py、app/services/groups.py、
app/schemas.py、app/main.py），要点：
- 错误响应体统一为 ``{"code": "...", "message": "..."}``（app/main.py 两个 exception_handler），
  无 HTTP status 字段；pydantic 校验失败也走 422 + code=VALIDATION_ERROR。
- PW-02：``get_current_user`` 内置未改密拦截——除 ``/api/auth/{login,me,password}`` 与
  ``/api/settings*`` 白名单外一律 403 MUST_CHANGE_PASSWORD。``users.must_change_password``
  列默认 1，所以本文件里所有直接写库的账号工厂都必须显式传 0，否则整个文件的请求都被挡死。
- 三层归属（BD-01~06）：层 1 ``groups/group_members`` 与层 2 ``teacher_groups`` 的唯一写者是
  admin；层 3 ``teacher_students`` 的唯一写者是教师本人，三条路径：
  ``bind_from_class``（任一学生不在我可教的组 → 整批 403 STUDENT_NOT_IN_CLASS 且库零变化，
  幂等）、``bind``（兜底按学号，只接受 role=student 且 is_active=1，否则整批 422
  INVALID_STUDENT_IDS；响应不回学生明细）、``unbind``（只移自己的名单，不在名单里的静默忽略）。
  三者都返回 ``GroupMembershipOut{success_count}``，值是**实际新增/删除的条数**。
- 已废弃端点：``POST /api/teacher/students/group_members``、``GET /api/teacher/groups``、
  ``PUT /api/admin/teachers/{id}/students`` → 404/405；同路径 GET 保留为只读。
- 密码能力只存在于 admin 端：单个重置**无请求体** → ``TempCredentialOut{student_id,username,
  display_name,temp_password,expires_at}``；批量重置 ``{student_ids,mode:"unified"|"random"}``
  → ``{mode,count,credentials[]}``。unified 整批只算一次 bcrypt、``password_updated_at`` 为
  NULL（不过期）、密码全为 ``12345678``；random 逐生独立密码、``expires_at`` = 生成时刻 +7 天，
  人数 > ``config.BATCH_RESET_ASK_THRESHOLD`` 时改走 ``hash_password_many`` 线程池。
- 审计（AU-02~05）：``group_member_change`` / ``group_update`` / ``group_delete`` /
  ``user_is_active_change``（批量时逐人一条）/ ``teacher_group_assign`` /
  ``teacher_student_bind`` / ``teacher_student_unbind`` / ``student_batch_reset_pw``。
  ``log_audit`` 只 add 不 commit，接口自己 commit，故断言前直接查库（先 fresh()）。
- 列表筛选：``GET /admin/students?q=&group_id=&must_change=``、``GET /admin/teachers?q=``、
  ``GET /teacher/students?q=``；``StudentOut/BoundStudentOut/TeacherOut`` 均带
  ``must_change_password``。
- 草稿：``PUT /api/teacher/problems/{id}/draft`` body=ProblemDraft →
  ``ProblemDraftSavedOut{ok,draft_saved_at}``；``GET /api/teacher/problems/{id}`` 带
  ``draft`` + ``draft_saved_at``；``DELETE`` 同路径返回 ``{"ok": true}``；
  ``PUT /api/teacher/problems/{id}`` 成功后服务端清空两字段。归属校验走
  ``_get_owned_problem``：题目不存在 404 PROBLEM_NOT_FOUND，非本人题目 403 FORBIDDEN。
"""
from datetime import datetime
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import admin as admin_api
from app.api import teacher as teacher_api
from app.core import config
from app.core.security import (create_token, hash_password, temp_password_expires_at,
                               verify_password)
from app.main import app
from app.models import (AuditLog, Group, GroupMember, Problem, TeacherGroup,
                        TeacherStudent, User)

# 已知密码：种子数据共用一次 bcrypt（cost=12 约 250ms），避免每个学生都算一次
STUDENT_PWD = "pw123456"
NEW_PWD = "brand-new-9"
INITIAL = config.DEFAULT_INITIAL_PASSWORD

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


def seed_students(db, n, *, prefix="stu", bind_to=(), password_hash=None, must_change=0):
    """建 n 个学生；bind_to 传入的教师会与学生建立 teacher_students 绑定。

    must_change 默认 0：PW-02 的未改密拦截会把「直接写库」的账号也一起挡在业务接口外，
    只有专门验证拦截的用例才需要传 1。
    """
    users = []
    for i in range(1, n + 1):
        users.append(User(
            username=f"{prefix}{i}",
            password_hash=password_hash or shared_hash(),
            role="student",
            display_name=f"学生{prefix}{i}",
            must_change_password=must_change,
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


def seed_teacher_group(db, teacher, group):
    """层 2「谁可教哪个班」——admin 是唯一写者，测试里直接写库当既有分配。"""
    return _add(db, TeacherGroup(teacher_id=teacher.id, group_id=group.id))


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


def roster_pairs(db):
    """teacher_students 全表快照（层 3），同上用于「零变化」硬断言。"""
    fresh(db)
    rows = db.execute(text("SELECT teacher_id, student_id FROM teacher_students")).all()
    return {(t, s) for t, s in rows}


def audit_rows(db, action):
    fresh(db)
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


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
    # must_change_password=0：否则 PW-02 拦截会把 admin 的所有请求挡成 403
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
    # 0.3.0 之后 admin 端也没多出来的入口：教师侧连「改自己密码」的路由都不存在，
    # 改密码只有 /api/auth/password 一条（全角色共用）
    ("post", "/api/teacher/password/change"),
    ("post", "/api/teacher/me/password"),
    ("post", "/api/teacher/students/1/password"),
    ("put", "/api/teacher/students/1/reset_password"),
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
                           json={"student_ids": [s.id], "mode": "unified"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 批量重置的响应是凭证明细，而不是旧的 {success: true}
        assert set(body) == {"mode", "count", "credentials"}
        assert body["credentials"][0]["temp_password"] == INITIAL
        ok = login(client, s.username, INITIAL)
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["must_change_password"] is True


# ---------- 2/3. 教师端批量成员关系 ----------

class TestTeacherMembership:
    """三层归属（BD-01~05）：教师不再改组，只能在「自己可教的组」里把人拉进自己名单。

    旧版这里 4 例走的是 ``POST /api/teacher/students/group_members``（教师改组），该接口已随
    GR-02 删除；改为覆盖 ``GET /teacher/classes`` + ``POST /teacher/students/bind_from_class``。
    """

    def test_classes_only_exposes_teachable_groups(self, client, db, teacher, teacher2, h_teacher):
        mine_group = seed_group(db, "我可教的班")
        other_group = seed_group(db, "别人的班")
        seed_teacher_group(db, teacher, mine_group)
        seed_teacher_group(db, teacher2, other_group)
        in_class = seed_students(db, 2, prefix="cls")
        outsider = seed_students(db, 1, prefix="out")[0]
        for s in in_class:
            seed_group_member(db, mine_group, s)
        seed_group_member(db, other_group, outsider)

        resp = client.get("/api/teacher/classes", headers=h_teacher)
        assert resp.status_code == 200, resp.text
        classes = resp.json()
        # 只返回经 teacher_groups 分给我的组，别人班连组名都看不到
        assert [c["name"] for c in classes] == ["我可教的班"]
        assert classes[0]["id"] == mine_group.id
        assert classes[0]["member_count"] == 2
        assert {s["username"] for s in classes[0]["students"]} == {"cls1", "cls2"}
        assert all(s["bound"] is False for s in classes[0]["students"])
        assert set(classes[0]["students"][0]) == {
            "id", "username", "display_name", "is_active", "bound"}

        # 停用学生照常返回，由 is_active 标注（BD-03），不会被从名单里抹掉
        in_class[0].is_active = 0
        db.commit()
        rows = client.get("/api/teacher/classes", headers=h_teacher).json()[0]["students"]
        assert {r["id"] for r in rows} == {in_class[0].id, in_class[1].id}
        assert next(r for r in rows if r["id"] == in_class[0].id)["is_active"] == 0

    def test_bind_from_class_adds_then_is_idempotent(self, client, db, teacher, h_teacher):
        group = seed_group(db, "实验班")
        seed_teacher_group(db, teacher, group)
        s1, s2 = seed_students(db, 2, prefix="b")
        seed_group_member(db, group, s1)
        seed_group_member(db, group, s2)
        url = "/api/teacher/students/bind_from_class"

        resp = client.post(url, headers=h_teacher, json={"student_ids": [s1.id, s2.id]})
        assert resp.status_code == 200, resp.text
        # success_count 是「实际新增条数」
        assert resp.json() == {"success_count": 2}
        assert roster_pairs(db) == {(teacher.id, s1.id), (teacher.id, s2.id)}

        again = client.post(url, headers=h_teacher, json={"student_ids": [s1.id, s2.id]})
        assert again.status_code == 200, again.text
        assert again.json() == {"success_count": 0}
        assert roster_pairs(db) == {(teacher.id, s1.id), (teacher.id, s2.id)}
        # 请求体自身重复的 ID 只算一份（去重后写）
        dup = client.post(url, headers=h_teacher, json={"student_ids": [s1.id, s1.id]})
        assert dup.json() == {"success_count": 0}

        # 拉入后两份视图都反映出来
        rows = {r["id"]: r for r in client.get("/api/teacher/students", headers=h_teacher).json()}
        assert set(rows) == {s1.id, s2.id}
        assert group_names_of(rows[s1.id]) == {"实验班"}
        classes = client.get("/api/teacher/classes", headers=h_teacher).json()
        assert [s["bound"] for s in classes[0]["students"]] == [True, True]

        # AU-04：每次成功调用一条 bind 审计，detail 带实际新增 ID 与来源
        fresh(db)
        logs = audit_rows(db, "teacher_student_bind")
        assert len(logs) == 3
        assert logs[0].actor_id == teacher.id and logs[0].target_id == teacher.id
        assert json.loads(logs[0].detail) == {
            "count": 2, "student_ids": [s1.id, s2.id], "source": "class"}
        assert all(json.loads(r.detail)["count"] == 0 for r in logs[1:])

    def test_students_outside_teachable_group_reject_whole_batch(self, client, db, teacher, teacher2,
                                                                  h_teacher, h_admin, admin_user):
        mine_group = seed_group(db, "我的班")
        other_group = seed_group(db, "别人的班")
        seed_teacher_group(db, teacher, mine_group)
        seed_teacher_group(db, teacher2, other_group)
        mine = seed_students(db, 1, prefix="mine")[0]
        theirs = seed_students(db, 1, prefix="theirs")[0]
        seed_group_member(db, mine_group, mine)
        seed_group_member(db, other_group, theirs)
        before = roster_pairs(db)
        assert before == set()

        resp = client.post("/api/teacher/students/bind_from_class", headers=h_teacher,
                           json={"student_ids": [mine.id, theirs.id]})
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "STUDENT_NOT_IN_CLASS"
        # 关键：不能只看状态码，必须确认库里一行都没写进去（含那个合法的学生）
        assert roster_pairs(db) == before
        assert scalar(db, "SELECT COUNT(*) FROM teacher_students") == 0
        assert audit_rows(db, "teacher_student_bind") == []
        # 0.3.2 F1：名单口径改为「可教组并集」，失败的整批不加手动行 ——
        # 但 mine 本就是我组里的人，所以教师名单里能看见他（来源为组别，不是幽灵成员）
        roster = client.get("/api/teacher/students", headers=h_teacher).json()
        assert [r["username"] for r in roster] == [mine.username]
        assert roster_pairs(db) == set()

        # 层 1 仍由 admin 独写：改组成员成功并写审计
        added = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [mine.id, theirs.id], "group_ids": [mine_group.id], "action": "add",
        })
        assert added.status_code == 200, added.text
        # mine 已在组内（幂等 add 只补 theirs）→ 实际写入 1 条
        assert added.json() == {"success_count": 1}
        assert member_pairs(db) == {(mine_group.id, mine.id), (mine_group.id, theirs.id),
                                    (other_group.id, theirs.id)}
        fresh(db)
        logs = audit_rows(db, "group_member_change")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert logs[0].target_id == mine_group.id   # 单组时 target_id 就是那个组
        assert json.loads(logs[0].detail) == {
            "action": "add", "group_ids": [mine_group.id],
            "student_ids": sorted([mine.id, theirs.id]), "changed": 1}
        # admin 学生列表反映写入结果
        admin_rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert group_names_of(admin_rows[theirs.id]) == {"我的班", "别人的班"}
        # 层 1 变化会立刻改变教师可见范围：theirs 现在也在我可教的班里的名单中
        classes = client.get("/api/teacher/classes", headers=h_teacher).json()
        assert {s["username"] for s in classes[0]["students"]} == {"mine1", "theirs1"}
        # 于是同一个批次现在可以整批成功了
        ok = client.post("/api/teacher/students/bind_from_class", headers=h_teacher,
                         json={"student_ids": [mine.id, theirs.id]})
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"success_count": 2}
        assert roster_pairs(db) == {(teacher.id, mine.id), (teacher.id, theirs.id)}

    def test_unbind_only_touches_own_roster_and_ignores_the_rest(self, client, db, teacher, teacher2,
                                                                h_teacher):
        mine = seed_students(db, 1, prefix="mine", bind_to=[teacher])[0]
        foreign = seed_students(db, 1, prefix="foreign", bind_to=[teacher2])[0]
        group = seed_group(db, "A班")
        seed_teacher_group(db, teacher, group)
        seed_group_member(db, group, mine)
        assert roster_pairs(db) == {(teacher.id, mine.id), (teacher2.id, foreign.id)}

        # BD-05：只能移自己的名单，别人的那条静默忽略（不是整批拒绝，也不是报错）
        resp = client.post("/api/teacher/students/unbind", headers=h_teacher,
                           json={"student_ids": [mine.id, foreign.id]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1}
        # 教师 2 的名单毫发无损
        assert roster_pairs(db) == {(teacher2.id, foreign.id)}
        # 组定义（层 1）不因移除名单而受影响
        assert member_pairs(db) == {(group.id, mine.id)}
        # 0.3.2 F1 语义收窄：手动行移走后 mine 仍在名单里（由可教组派生），
        # 再次 unbind 他不再幂等成功，而是整批 422 ROSTER_DERIVED_STUDENT
        assert [r["username"] for r in
                client.get("/api/teacher/students", headers=h_teacher).json()] == [mine.username]
        again = client.post("/api/teacher/students/unbind", headers=h_teacher,
                           json={"student_ids": [mine.id]})
        assert again.status_code == 422, again.text
        assert code_of(again) == "ROSTER_DERIVED_STUDENT"
        assert str(mine.id) in again.json()["message"]
        # 非名单内且非组派生（别人的学生）仍静默忽略
        ignored = client.post("/api/teacher/students/unbind", headers=h_teacher,
                              json={"student_ids": [foreign.id]})
        assert ignored.status_code == 200, ignored.text
        assert ignored.json() == {"success_count": 0}

        fresh(db)
        logs = audit_rows(db, "teacher_student_unbind")
        assert len(logs) == 2
        assert [json.loads(r.detail)["student_ids"] for r in logs] == [[mine.id], []]
        assert logs[0].actor_id == teacher.id and logs[0].target_id == teacher.id

    def test_empty_selection_is_422(self, client, db, teacher, h_teacher):
        mine = seed_students(db, 1, prefix="mine", bind_to=[teacher])[0]
        group = seed_group(db, "A班")
        seed_teacher_group(db, teacher, group)
        seed_group_member(db, group, mine)
        before = roster_pairs(db)

        for path in ("/api/teacher/students/bind_from_class", "/api/teacher/students/bind",
                     "/api/teacher/students/unbind"):
            resp = client.post(path, headers=h_teacher, json={"student_ids": []})
            assert resp.status_code == 422, (path, resp.text)
            assert code_of(resp) == "EMPTY_SELECTION"
        # 空选择在写库之前就拦下：名单零变化，也不留审计
        assert roster_pairs(db) == before
        assert audit_rows(db, "teacher_student_bind") == []
        assert audit_rows(db, "teacher_student_unbind") == []

    def test_admin_teacher_roster_view_is_read_only(self, client, db, teacher, h_teacher, h_admin):
        group = seed_group(db, "名单班")
        seed_teacher_group(db, teacher, group)
        s1, s2 = seed_students(db, 2, prefix="r")
        for s in (s1, s2):
            seed_group_member(db, group, s)
        bound = client.post("/api/teacher/students/bind_from_class", headers=h_teacher,
                            json={"student_ids": [s1.id, s2.id]})
        assert bound.json() == {"success_count": 2}, bound.text

        # BD-06：admin 保留教师名单的只读视图（唯一写者是教师本人）
        # 0.3.2 F1：名单条目带 source（manual/group）与所在可教组名
        url = f"/api/admin/teachers/{teacher.id}/students"
        resp = client.get(url, headers=h_admin)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"students": [
            {"id": s1.id, "username": "r1", "display_name": "学生r1",
             "source": "manual", "group_names": ["名单班"]},
            {"id": s2.id, "username": "r2", "display_name": "学生r2",
             "source": "manual", "group_names": ["名单班"]},
        ]}
        # 写接口已删除：同路径只剩 405/404，且不会动到库
        for method in ("put", "delete"):
            gone = client.request(method.upper(), url, headers=h_admin,
                                  json={"student_ids": [s1.id]})
            assert gone.status_code in (404, 405), (method, gone.status_code, gone.text)
        assert roster_pairs(db) == {(teacher.id, s1.id), (teacher.id, s2.id)}
        # 未知教师 → 404（读接口还在，角色校验也生效）
        missing = client.get("/api/admin/teachers/99999/students", headers=h_admin)
        assert missing.status_code == 404
        assert code_of(missing) == "NOT_FOUND"
        # admin 学生列表能看到层 3 的归属，教师列表带 student_count
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert [t["username"] for t in rows[s1.id]["teachers"]] == ["t001"]
        counts = {t["username"]: t["student_count"] for t in
                  client.get("/api/admin/teachers", headers=h_admin).json()}
        assert counts["t001"] == 2
        # LI-02：未改密徽标（这些种子账号已显式置 0）
        t_rows = client.get("/api/teacher/students", headers=h_teacher).json()
        assert [r["must_change_password"] for r in t_rows] == [False, False]

    def test_group_definitions_are_readonly_for_teacher(self, client, db, teacher, h_teacher, h_admin):
        group = seed_group(db, "只读班")
        # GR-02：教师端唯一的组入口是 /classes，没分配给它的组连组名都看不到
        assert client.get("/api/teacher/classes", headers=h_teacher).json() == []
        seed_teacher_group(db, teacher, group)
        assert client.get("/api/teacher/classes", headers=h_teacher).json() == [{
            "id": group.id, "name": "只读班", "member_count": 0, "students": [],
        }]
        # 组本身的增删改仅 admin
        for method, path, body in (
            ("post", "/api/admin/groups", {"name": "教师建班"}),
            ("patch", f"/api/admin/groups/{group.id}", {"name": "教师改名"}),
            ("delete", f"/api/admin/groups/{group.id}", None),
            ("put", f"/api/admin/teachers/{teacher.id}/groups", {"group_ids": [group.id]}),
        ):
            resp = client.request(method.upper(), path, headers=h_teacher,
                                  json=body)
            assert resp.status_code == 403, (method, path, resp.text)
            assert code_of(resp) == "FORBIDDEN"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 1
        assert scalar(db, "SELECT COUNT(*) FROM teacher_groups") == 1
        assert client.get("/api/admin/groups", headers=h_admin).json()[0]["name"] == "只读班"


# ---------- 3b. 已废弃端点：路由压根没注册（QA-13） ----------

# (method, path)：教师侧改组与组列表、admin 侧代教师改名单
DEPRECATED_PATHS = [
    ("post", "/api/teacher/students/group_members"),
    ("get", "/api/teacher/groups"),
    ("put", "/api/teacher/students/group_members"),
    ("delete", "/api/teacher/groups"),
    ("get", "/api/teacher/classes/1"),
]


class TestDeprecatedEndpoints:
    @pytest.mark.parametrize("method,path", DEPRECATED_PATHS)
    def test_route_is_gone_for_teacher_token(self, client, h_teacher, method, path):
        resp = client.request(method.upper(), path, headers=h_teacher,
                              json={"student_ids": [1], "group_ids": [1], "action": "add"})
        assert resp.status_code in (404, 405), (method, path, resp.status_code, resp.text)

    @pytest.mark.parametrize("method,path", DEPRECATED_PATHS)
    def test_route_is_gone_for_admin_token(self, client, h_admin, method, path):
        # 404/405 由路由匹配决定，与角色无关：不能退化成「存在但 403」
        resp = client.request(method.upper(), path, headers=h_admin,
                              json={"student_ids": [1], "group_ids": [1], "action": "add"})
        assert resp.status_code in (404, 405), (method, path, resp.status_code, resp.text)

    def test_deprecated_paths_are_not_registered_at_all(self):
        paths = app.openapi()["paths"]
        for _method, path in DEPRECATED_PATHS:
            assert path not in paths, path
        # 教师端组相关的入口：只读的 /classes + 0.3.2 F1 新增的教师私有三条子分组路由
        teacher_group_paths = {p for p in paths if p.startswith("/api/teacher")
                               and ("group" in p or p.endswith("/classes"))}
        assert teacher_group_paths == {
            "/api/teacher/classes",
            "/api/teacher/subgroups",
            "/api/teacher/subgroups/{subgroup_id}",
            "/api/teacher/subgroups/{subgroup_id}/students",
        }


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
        # AU-02：组改名写审计 group_update，detail 带新旧名
        logs = audit_rows(db, "group_update")
        assert len(logs) == 1
        assert logs[0].target_type == "group" and logs[0].target_id == g_a.id
        assert json.loads(logs[0].detail) == {"old_name": "甲班", "new_name": "甲班改"}

        missing = client.patch("/api/admin/groups/99999", headers=h_admin, json={"name": "幽灵班"})
        assert missing.status_code == 404
        assert code_of(missing) == "GROUP_NOT_FOUND"

        clash = client.patch(f"/api/admin/groups/{g_a.id}", headers=h_admin, json={"name": "乙班"})
        assert clash.status_code == 409
        assert code_of(clash) == "GROUP_NAME_EXISTS"
        # 409 后原名保持不变，也不会多出一条审计
        assert scalar(db, "SELECT name FROM groups WHERE id=:i", i=g_a.id) == "甲班改"
        assert scalar(db, "SELECT name FROM groups WHERE id=:i", i=g_b.id) == "乙班"
        assert scalar(db, "SELECT COUNT(*) FROM groups") == 2
        assert len(audit_rows(db, "group_update")) == 1

    def test_delete_group_removes_memberships_only_for_that_group(self, client, db, h_admin, teacher):
        doomed, keeper = seed_group(db, "解散班"), seed_group(db, "留下班")
        doomed_id, keeper_id = doomed.id, keeper.id
        s1, s2 = seed_students(db, 2, prefix="d")
        seed_group_member(db, doomed, s1)
        seed_group_member(db, doomed, s2)
        seed_group_member(db, keeper, s1)
        seed_teacher_group(db, teacher, doomed)
        assert member_pairs(db) == {(doomed_id, s1.id), (doomed_id, s2.id), (keeper_id, s1.id)}

        resp = client.delete(f"/api/admin/groups/{doomed_id}", headers=h_admin)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True}
        # 级联：解散班的成员关系全部消失，留下班不受影响
        assert member_pairs(db) == {(keeper_id, s1.id)}
        assert scalar(db, "SELECT COUNT(*) FROM group_members WHERE group_id=:g", g=doomed_id) == 0
        assert scalar(db, "SELECT COUNT(*) FROM groups WHERE id=:g", g=doomed_id) == 0
        # 层 2 分配随组一起级联清掉，不留悬空行
        assert scalar(db, "SELECT COUNT(*) FROM teacher_groups WHERE group_id=:g", g=doomed_id) == 0
        # AU-02：删组写审计（日志留着，即便目标已不存在）
        logs = audit_rows(db, "group_delete")
        assert len(logs) == 1
        assert logs[0].target_id == doomed_id
        assert json.loads(logs[0].detail) == {"name": "解散班"}
        assert code_of(client.delete("/api/admin/groups/99999", headers=h_admin)) == "GROUP_NOT_FOUND"
        # 404 的失败尝试不再写审计
        assert len(audit_rows(db, "group_delete")) == 1

        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert group_names_of(rows[s1.id]) == {"留下班"}
        assert group_names_of(rows[s2.id]) == set()
        assert [g["name"] for g in client.get("/api/admin/groups", headers=h_admin).json()] == ["留下班"]
        # 教师侧再也看不到解散的班
        assert client.get("/api/teacher/classes", headers=bearer(teacher)).json() == []


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
        # 跨多组时 target_id 为 None（以 detail 为准），单组时才有 target_id
        fresh(db)
        logs = audit_rows(db, "group_member_change")
        assert len(logs) == 1 and logs[0].target_id is None
        assert json.loads(logs[0].detail)["group_ids"] == [g1.id, g2.id, g3.id]
        assert json.loads(logs[0].detail)["changed"] == 6
        # 移走两个组
        resp = client.post("/api/admin/students/group_members", headers=h_admin, json={
            "student_ids": [s1.id], "group_ids": [g1.id, g2.id], "action": "remove",
        })
        assert resp.json() == {"success_count": 2}
        rows = {r["id"]: r for r in client.get("/api/admin/students", headers=h_admin).json()}
        assert group_names_of(rows[s1.id]) == {"3组"}
        assert group_names_of(rows[s2.id]) == {"1组", "2组", "3组"}


# ---------- 7. 批量重置密码：unified / random 两模式（PW-06/09） ----------

BATCH_RESET_URL = "/api/admin/students/batch_reset_password"


class TestBatchResetPassword:
    """PW-06：unified = 整批一次 bcrypt 回到 12345678（不过期）；random = 逐生独立随机密码。

    性能护栏：bcrypt cost=12 约 250ms/次，所以批量用例要么人数很小、要么把哈希换成替身；
    unified 那条保留真实 hash_password 的**计数**断言（spy 转调真实实现），人数只有 5 个。
    """

    def test_unified_hashes_once_and_never_expires(self, client, db, h_admin, admin_user, monkeypatch):
        batch = seed_students(db, 5, prefix="p")
        outsider = seed_students(db, 1, prefix="out")[0]
        outsider_hash = outsider.password_hash

        calls = []
        real_hash = admin_api.hash_password

        def spy(password):
            calls.append(password)
            return real_hash(password)

        monkeypatch.setattr(admin_api, "hash_password", spy)

        resp = client.post(BATCH_RESET_URL, headers=h_admin,
                           json={"student_ids": [s.id for s in batch], "mode": "unified"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"mode", "count", "credentials"}
        assert body["mode"] == "unified" and body["count"] == 5
        # 核心断言（QA-17）：整批 5 个人只算一次 bcrypt
        assert calls == [INITIAL], calls

        creds = body["credentials"]
        assert [c["temp_password"] for c in creds] == [INITIAL] * 5
        assert [c["expires_at"] for c in creds] == [None] * 5     # PW-05：统一密码不过期
        assert [c["student_id"] for c in creds] == [s.id for s in batch]
        assert [c["username"] for c in creds] == [s.username for s in batch]
        assert [c["display_name"] for c in creds] == [s.display_name for s in batch]

        fresh(db)
        stored = [db.get(User, s.id) for s in batch]
        hashes = {u.password_hash for u in stored}
        # 同一个 hash 复用到 N 行，且确实是 12345678 的哈希（spy 每次算的盐不同，故不比对字面值）
        assert len(hashes) == 1
        assert verify_password(INITIAL, next(iter(hashes)))
        assert next(iter(hashes)) != shared_hash()
        assert all(u.must_change_password == 1 for u in stored)
        assert all(u.password_updated_at is None for u in stored)
        # 未入选学生的密码原样不动
        assert db.get(User, outsider.id).password_hash == outsider_hash

        for student in batch:
            ok = login(client, student.username, INITIAL)
            assert ok.status_code == 200, (student.username, ok.text)
            assert ok.json()["user"]["must_change_password"] is True
        # 旧密码全部失效
        assert login(client, batch[0].username, STUDENT_PWD).status_code == 401

        logs = audit_rows(db, "student_batch_reset_pw")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert logs[0].target_type == "student" and logs[0].target_id is None
        assert json.loads(logs[0].detail) == {"mode": "unified", "count": 5}

    def test_random_issues_distinct_one_time_passwords(self, client, db, h_admin, admin_user):
        # 真实 bcrypt 路径，人数压到 3（每个约 250ms），细节断言靠库而不是靠登录次数
        batch = seed_students(db, 3, prefix="rnd")
        resp = client.post(BATCH_RESET_URL, headers=h_admin,
                           json={"student_ids": [s.id for s in batch], "mode": "random"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["mode"], body["count"]) == ("random", 3)
        creds = body["credentials"]
        passwords = [c["temp_password"] for c in creds]
        # 逐生独立、互不相同，且符合 PW-08 的 56 字符集
        assert len(set(passwords)) == 3
        assert all(len(p) == config.TEMP_PASSWORD_LENGTH for p in passwords)
        assert all(set(p) <= set(config.TEMP_PASSWORD_CHARSET) for p in passwords)
        assert INITIAL not in passwords

        fresh(db)
        users = [db.get(User, s.id) for s in batch]
        assert all(u.must_change_password == 1 for u in users)
        assert all(u.password_updated_at for u in users)     # PW-05 锚点已写
        # 同一批共用一个生成时刻 → 有效期一致
        assert len({c["expires_at"] for c in creds}) == 1
        assert [c["expires_at"] for c in creds] == \
            [temp_password_expires_at(u.password_updated_at) for u in users]
        # 各人的哈希各不相同
        assert len({u.password_hash for u in users}) == 3

        # 随机密码能登录、且只对得上自己那个人（一次性凭证的归属）
        assert login(client, batch[0].username, passwords[0]).status_code == 200
        assert login(client, batch[1].username, passwords[0]).status_code == 401
        logs = audit_rows(db, "student_batch_reset_pw")
        assert [json.loads(r.detail) for r in logs] == [{"mode": "random", "count": 3}]

    def test_random_over_threshold_goes_through_thread_pool(self, client, db, h_admin, monkeypatch):
        n = config.BATCH_RESET_ASK_THRESHOLD + 1          # 21 > 20 → 并行分支
        batch = seed_students(db, n, prefix="par")
        seen = {}

        def fake_many(passwords, workers=None):
            seen["passwords"] = list(passwords)
            seen["workers"] = workers
            return [f"fake<{p}>" for p in passwords]

        monkeypatch.setattr(admin_api, "hash_password_many", fake_many)
        serial = []
        monkeypatch.setattr(admin_api, "hash_password", lambda p: serial.append(p) or "serial")

        resp = client.post(BATCH_RESET_URL, headers=h_admin,
                           json={"student_ids": [s.id for s in batch], "mode": "random"})
        assert resp.status_code == 200, resp.text
        # 整批一次性交给线程池，且密码互不相同
        assert len(seen["passwords"]) == n
        assert len(set(seen["passwords"])) == n
        assert serial == []                                # 没有退化成串行逐个哈希
        assert seen["workers"] is None                     # 用 config.BCRYPT_PARALLEL_WORKERS
        fresh(db)
        assert {db.get(User, s.id).password_hash for s in batch} == \
            {f"fake<{p}>" for p in seen["passwords"]}
        assert [c["temp_password"] for c in resp.json()["credentials"]] == seen["passwords"]

    def test_random_at_threshold_stays_serial(self, client, db, h_admin, monkeypatch):
        n = config.BATCH_RESET_ASK_THRESHOLD               # 20 人：阈值是「超过」才并行
        batch = seed_students(db, n, prefix="seq")
        monkeypatch.setattr(admin_api, "hash_password_many",
                            lambda ps, workers=None: pytest.fail("不该走线程池"))
        hashed = []
        monkeypatch.setattr(admin_api, "hash_password",
                            lambda p: hashed.append(p) or f"fake<{p}>")

        resp = client.post(BATCH_RESET_URL, headers=h_admin,
                           json={"student_ids": [s.id for s in batch], "mode": "random"})
        assert resp.status_code == 200, resp.text
        assert len(hashed) == n
        assert len(set(hashed)) == n
        assert [c["expires_at"] for c in resp.json()["credentials"]][0] is not None
        fresh(db)
        assert db.get(User, batch[0].id).password_hash == f"fake<{hashed[0]}>"

    def test_invalid_batch_rejected_before_any_hashing(self, client, db, h_admin, admin_user,
                                                      monkeypatch):
        students = seed_students(db, 3, prefix="q")
        before_hashes = {s.id: s.password_hash for s in students}
        calls = []
        real_hash = admin_api.hash_password
        monkeypatch.setattr(admin_api, "hash_password",
                            lambda pw: calls.append(pw) or real_hash(pw))
        monkeypatch.setattr(admin_api, "hash_password_many",
                            lambda ps, workers=None: calls.extend(ps) or ["x"] * len(ps))

        resp = client.post(BATCH_RESET_URL, headers=h_admin,
                           json={"student_ids": [students[0].id, admin_user.id], "mode": "random"})
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "INVALID_STUDENT_IDS"
        assert calls == []
        fresh(db)
        # 整批拒绝：没有任何一行的密码被动过（逐行比对，不看集合）
        for sid, old_hash in before_hashes.items():
            assert db.get(User, sid).password_hash == old_hash
        assert all(db.get(User, sid).must_change_password == 0 for sid in before_hashes)

        # mode 由 schema 的 Literal 兜住；缺省时按 random 处理
        bad_mode = client.post(BATCH_RESET_URL, headers=h_admin,
                               json={"student_ids": [students[0].id], "mode": "set"})
        assert bad_mode.status_code == 422
        assert code_of(bad_mode) == "VALIDATION_ERROR"
        empty = client.post(BATCH_RESET_URL, headers=h_admin, json={"student_ids": []})
        assert empty.status_code == 422
        assert code_of(empty) == "EMPTY_SELECTION"
        # 校验在哈希之前：整批非法时一次 bcrypt 都不该发生
        assert calls == []
        assert audit_rows(db, "student_batch_reset_pw") == []

    def test_single_student_reset_needs_no_body_and_is_role_scoped(self, client, db, h_admin, teacher):
        student = seed_students(db, 1, prefix="one")[0]
        resp = client.post(f"/api/admin/students/{student.id}/reset_password", headers=h_admin)
        assert resp.status_code == 200, resp.text
        assert set(resp.json()) == {"student_id", "username", "display_name",
                                    "temp_password", "expires_at"}
        missing = client.post("/api/admin/students/99999/reset_password", headers=h_admin)
        assert missing.status_code == 404
        assert code_of(missing) == "NOT_FOUND"
        # 学生端点打教师 ID → 404「学生不存在」，两条路径不互通
        wrong_role = client.post(f"/api/admin/students/{teacher.id}/reset_password", headers=h_admin)
        assert wrong_role.status_code == 404
        assert code_of(wrong_role) == "NOT_FOUND"


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

        # AU-02：批量启停「逐人一条」，而不是一批一条汇总
        assert [(r.target_type, r.target_id, json.loads(r.detail)) for r in
                audit_rows(db, "user_is_active_change")] == [
            ("student", s1.id, {"is_active": False}),
            ("student", s2.id, {"is_active": False}),
        ]

        back = client.post("/api/admin/students/batch_active", headers=h_admin,
                           json={"student_ids": [s1.id], "is_active": True})
        assert back.status_code == 200, back.text
        assert login(client, s1.username, STUDENT_PWD).status_code == 200
        assert login(client, s2.username, STUDENT_PWD).status_code == 403
        assert [(r.target_id, json.loads(r.detail)) for r in
                audit_rows(db, "user_is_active_change")][-1] == (s1.id, {"is_active": True})

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
