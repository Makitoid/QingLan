"""0.3.0 批次 M6 · admin 侧凭证发放与审计台账（PW-01/04/09、AU-02~06、LI-01/02）。

对应验收：QA-03 / QA-04 / QA-08 / QA-09 / QA-18 / QA-19（QA-01~03/05/16/18 的 auth 侧
已由 tests/test_password_flow.py 覆盖，本文件只补 admin 侧那半边，不重复）。

契约以代码实际行为为准（app/api/admin.py、app/core/security.py、app/services/audit.py、
app/schemas.py）：
- 建号：``AccountCreate{username, display_name}`` **没有 password 字段**，多余字段被忽略；
  落库是 ``hash_password(config.DEFAULT_INITIAL_PASSWORD)`` + ``must_change_password=1`` +
  ``password_updated_at IS NULL``（PW-05：初始密码不过期），审计 ``student_create_pw`` /
  ``teacher_create_pw``（detail ``{"must_change_password": true}``）。
- 单个重置：**无请求体** → ``TempCredentialOut{student_id,username,display_name,
  temp_password,expires_at}``；8 位随机密码取自 56 字符集，``password_updated_at=now``，
  ``expires_at=now+7 天``，审计 ``student_reset_pw`` / ``teacher_reset_pw``（detail.mode=random）。
- 列表筛选（LI-01/02）：``GET /admin/students?q=&group_id=&must_change=``（must_change 只收
  0/1，越界由 Query 的 ge/le 拦成 422）、``GET /admin/teachers?q=``；``q`` 对 username 与
  display_name 做大小写不敏感模糊匹配；``StudentOut/BoundStudentOut/TeacherOut`` 均带
  ``must_change_password``。
- 审计（AU-02~06）：只追加、只读。``GET /admin/audit_logs?action=&target_type=&limit=&offset=``
  → ``AuditLogPageOut{items[],total}``，按 ``(created_at, id)`` 倒序；``limit`` 允许 0
  （SQLite 语义：不返回行但 total 照给）。``detail`` 是明文 JSON，读出为 dict 或 None。
  每行另带服务端算好的 ``action_label`` / ``target_label``（0.3.2 F5，中文名单一来源）。
  ``log_audit`` 只 add 不 commit，所以断言前直接查库即可（业务接口自己会 commit）。
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.core import config
from app.core.security import (create_token, hash_password, is_temp_password_expired,
                               verify_password)
from app.main import app
from app.models import (AuditLog, Group, GroupMember, TeacherGroup, TeacherStudent,
                        User)
from app.services.audit import log_audit

INITIAL = config.DEFAULT_INITIAL_PASSWORD
AUDIT_URL = "/api/admin/audit_logs"

# 附录 A 的两条阈值：改数值等于改契约，先钉住
CONTRACT_CONSTANTS = {
    "DEFAULT_INITIAL_PASSWORD": "12345678",
    "TEMP_PASSWORD_LENGTH": 8,
    "TEMP_PASSWORD_EXPIRE_DAYS": 7,
    "BATCH_RESET_ASK_THRESHOLD": 20,
    "PASSWORD_MIN_LENGTH": 8,
}

# AU-04 要求的动作全集（required_actions 的 admin 侧子集）
AUDITED_ADMIN_ACTIONS = {
    "student_create_pw", "teacher_create_pw", "student_reset_pw", "teacher_reset_pw",
    "student_batch_reset_pw", "user_is_active_change", "group_member_change",
    "group_update", "group_delete", "student_import", "teacher_group_assign",
}


# ---------- 测试用数据工厂（直接写库；must_change 必须显式给，见 PW-02） ----------

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def seed_students(db, n, *, prefix="stu", must_change=0, display_prefix="学生", is_active=1):
    users = []
    for i in range(1, n + 1):
        users.append(User(username=f"{prefix}{i}", password_hash="x", role="student",
                          display_name=f"{display_prefix}{prefix}{i}",
                          must_change_password=must_change, is_active=is_active))
    db.add_all(users)
    db.commit()
    for u in users:
        db.refresh(u)
    return users


def seed_group(db, name):
    return _add(db, Group(name=name))


def seed_member(db, group, student):
    return _add(db, GroupMember(group_id=group.id, student_id=student.id))


def fresh(db):
    db.commit()
    db.expire_all()


def audit_rows(db, action=None):
    fresh(db)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.id).all()


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def code_of(resp):
    return resp.json().get("code")


def parse(text_value):
    return json.loads(text_value) if text_value else None


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
def teacher(db):
    return _add(db, User(username="t100", password_hash="x", role="teacher",
                         display_name="王老师", must_change_password=0))


# ---------- 1. 建号：无密码入参 + 统一初始密码 + 强制改密（PW-01 / QA-18） ----------

class TestAccountCreation:
    def test_create_student_flags_forced_change_and_audits(self, client, db, h_admin, admin_user):
        resp = client.post("/api/admin/students", headers=h_admin,
                           json={"username": "20260001", "display_name": "新同学"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"id", "username", "display_name", "is_active",
                            "must_change_password", "created_at", "teachers", "groups"}
        assert body["username"] == "20260001"
        assert body["must_change_password"] is True        # LI-02 徽标
        assert body["teachers"] == [] and body["groups"] == []

        fresh(db)
        user = db.get(User, body["id"])
        assert user.role == "student" and user.is_active == 1
        assert verify_password(INITIAL, user.password_hash)
        assert user.must_change_password == 1
        assert user.password_updated_at is None             # PW-05：初始密码不过期
        # AU-04：建号即写一条 student_create_pw
        logs = audit_rows(db, "student_create_pw")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert (logs[0].target_type, logs[0].target_id) == ("student", user.id)
        assert parse(logs[0].detail) == {"must_change_password": True}

    def test_password_field_in_body_is_ignored(self, client, db, h_admin):
        # AccountCreate 已去掉 password：老前端多传一个字段也不该改变结果
        resp = client.post("/api/admin/teachers", headers=h_admin,
                           json={"username": "t900", "display_name": "外聘教师",
                                 "password": "hunter2hunter2"})
        assert resp.status_code == 200, resp.text
        fresh(db)
        user = db.query(User).filter(User.username == "t900").one()
        assert verify_password(INITIAL, user.password_hash)
        assert not verify_password("hunter2hunter2", user.password_hash)
        assert user.must_change_password == 1
        logs = audit_rows(db, "teacher_create_pw")
        assert len(logs) == 1 and logs[0].target_type == "teacher"
        # QA-18：新建教师用 12345678 可登录、且被强制改密
        ok = client.post("/api/auth/login", json={"username": "t900", "password": INITIAL})
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["must_change_password"] is True

    def test_new_account_is_blocked_until_password_changed(self, client, db, h_admin):
        created = client.post("/api/admin/students", headers=h_admin,
                              json={"username": "20260002", "display_name": "拦一拦"}).json()
        fresh(db)
        student = db.get(User, created["id"])
        headers = bearer(student)
        # 自己建出来的号在未改密前打业务接口 → 403（PW-02 对 admin 端列表同样生效）
        blocked = client.get("/api/teacher/students", headers=headers)
        assert blocked.status_code == 403
        assert code_of(blocked) == "MUST_CHANGE_PASSWORD"

    def test_duplicate_username_is_409_without_writing_audit(self, client, db, h_admin):
        first = client.post("/api/admin/students", headers=h_admin,
                            json={"username": "dup001", "display_name": "甲"})
        assert first.status_code == 200, first.text
        dup = client.post("/api/admin/students", headers=h_admin,
                          json={"username": "dup001", "display_name": "乙"})
        assert dup.status_code == 409, dup.text
        assert code_of(dup) == "DUPLICATE_USERNAME"
        fresh(db)
        assert db.query(User).filter(User.username == "dup001").count() == 1
        # 失败的那次不留审计（审计与写操作同事务）
        assert len(audit_rows(db, "student_create_pw")) == 1


# ---------- 2. 单个重置：随机凭证明细与有效期（PW-04/05/09 / QA-03） ----------

class TestSingleResetCredential:
    def test_student_reset_returns_credential_and_ledger(self, client, db, h_admin, admin_user):
        student = seed_students(db, 1, prefix="one")[0]
        resp = client.post(f"/api/admin/students/{student.id}/reset_password", headers=h_admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"student_id", "username", "display_name", "temp_password",
                             "expires_at"}
        assert body["student_id"] == student.id
        assert body["username"] == student.username
        assert body["display_name"] == student.display_name
        temp = body["temp_password"]
        assert len(temp) == config.TEMP_PASSWORD_LENGTH
        assert set(temp) <= set(config.TEMP_PASSWORD_CHARSET)      # PW-08 的 56 字符集
        assert temp != INITIAL

        fresh(db)
        user = db.get(User, student.id)
        assert user.must_change_password == 1
        assert user.password_updated_at
        assert verify_password(temp, user.password_hash)
        # 有效期 = 生成时刻 + 7 天，且此时还没过期
        expected = (datetime.strptime(user.password_updated_at, "%Y-%m-%d %H:%M:%S")
                    + timedelta(days=config.TEMP_PASSWORD_EXPIRE_DAYS))
        assert body["expires_at"] == expected.strftime("%Y-%m-%d %H:%M:%S")
        assert is_temp_password_expired(user.password_updated_at) is False
        # QA-03：随机密码当场可用
        ok = client.post("/api/auth/login", json={"username": user.username,
                                                  "password": temp})
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["must_change_password"] is True
        # 审计 actor/target 都要对得上
        logs = audit_rows(db, "student_reset_pw")
        assert len(logs) == 1
        assert logs[0].actor_id == admin_user.id
        assert (logs[0].target_type, logs[0].target_id) == ("student", student.id)
        assert parse(logs[0].detail) == {"mode": "random"}

    def test_teacher_reset_same_rules_and_old_password_dead(self, client, db, h_admin, teacher):
        old_hash = teacher.password_hash
        resp = client.post(f"/api/admin/teachers/{teacher.id}/reset_password", headers=h_admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        temp = body["temp_password"]
        assert len(temp) == config.TEMP_PASSWORD_LENGTH
        assert set(temp) <= set(config.TEMP_PASSWORD_CHARSET)
        assert (body["student_id"], body["username"]) == (teacher.id, teacher.username)
        fresh(db)
        user = db.get(User, teacher.id)
        assert user.password_hash != old_hash and user.must_change_password == 1
        assert user.password_updated_at
        assert verify_password(temp, user.password_hash)
        assert body["expires_at"] == (datetime.strptime(user.password_updated_at,
                                                        "%Y-%m-%d %H:%M:%S")
                                      + timedelta(days=config.TEMP_PASSWORD_EXPIRE_DAYS)
                                      ).strftime("%Y-%m-%d %H:%M:%S")
        # QA-18：admin 重置教师密码 → 随机 8 位 + 审计 teacher_reset_pw
        logs = audit_rows(db, "teacher_reset_pw")
        assert len(logs) == 1
        assert (logs[0].target_type, logs[0].target_id) == ("teacher", teacher.id)
        assert parse(logs[0].detail) == {"mode": "random"}
        # 重置后的教师同样被强制改密挡住业务接口
        assert code_of(client.get("/api/teacher/students", headers=bearer(user))) == \
            "MUST_CHANGE_PASSWORD"

    def test_reset_revives_an_expired_credential(self, client, db, h_admin):
        # QA-16 后半：过期 → 403 PASSWORD_EXPIRED，admin 重新重置后恢复可用
        student = seed_students(db, 1, prefix="exp")[0]
        temp = client.post(f"/api/admin/students/{student.id}/reset_password",
                           headers=h_admin).json()["temp_password"]
        login = lambda pwd: client.post("/api/auth/login",   # noqa: E731
                                        json={"username": student.username, "password": pwd})
        assert login(temp).status_code == 200
        fresh(db)
        user = db.get(User, student.id)
        user.password_updated_at = (datetime.now(timezone.utc) - timedelta(days=8)
                                    ).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        expired = login(temp)
        assert expired.status_code == 403
        assert code_of(expired) == "PASSWORD_EXPIRED"
        again = client.post(f"/api/admin/students/{student.id}/reset_password",
                            headers=h_admin).json()
        assert login(again["temp_password"]).status_code == 200
        assert len(audit_rows(db, "student_reset_pw")) == 2


# ---------- 3. 批量重置明细可供前端拼 CSV（PW-06/09 / QA-04） ----------

class TestBatchResetCredentialDetails:
    URL = "/api/admin/students/batch_reset_password"

    @pytest.fixture(autouse=True)
    def _fast_hash(self, monkeypatch):
        # 只验证明细结构/一致性，不为 bcrypt 买单
        monkeypatch.setattr(admin_api, "hash_password", lambda p: f"fake<{p}>")

    def _ids(self, students):
        return [s.id for s in students]

    def test_random_detail_row_per_student(self, client, db, h_admin):
        batch = seed_students(db, 12, prefix="det")
        resp = client.post(self.URL, headers=h_admin,
                           json={"student_ids": self._ids(batch), "mode": "random"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["mode"], body["count"]) == ("random", 12)
        # 明细行数 = 选中数（前端据此下载 CSV：学号/姓名/临时密码/有效期）
        assert len(body["credentials"]) == body["count"] == 12
        assert [c["student_id"] for c in body["credentials"]] == self._ids(batch)
        assert [c["username"] for c in body["credentials"]] == [s.username for s in batch]
        assert [c["display_name"] for c in body["credentials"]] == \
            [s.display_name for s in batch]
        passwords = [c["temp_password"] for c in body["credentials"]]
        assert len(set(passwords)) == 12
        assert all(len(p) == config.TEMP_PASSWORD_LENGTH for p in passwords)
        assert all(c["expires_at"] for c in body["credentials"])
        assert len({c["expires_at"] for c in body["credentials"]}) == 1   # 同批同一锚点
        fresh(db)
        users = [db.get(User, s.id) for s in batch]
        assert all(u.must_change_password == 1 and u.password_updated_at for u in users)
        assert [u.password_hash for u in users] == [f"fake<{p}>" for p in passwords]
        assert parse(audit_rows(db, "student_batch_reset_pw")[0].detail) == \
            {"mode": "random", "count": 12}

    def test_unified_detail_carries_initial_password(self, client, db, h_admin):
        batch = seed_students(db, 3, prefix="uni")
        resp = client.post(self.URL, headers=h_admin,
                           json={"student_ids": self._ids(batch), "mode": "unified"})
        body = resp.json()
        assert body["mode"] == "unified" and body["count"] == 3
        assert [c["temp_password"] for c in body["credentials"]] == [INITIAL] * 3
        assert [c["expires_at"] for c in body["credentials"]] == [None] * 3
        fresh(db)
        assert all(db.get(User, s.id).password_hash == f"fake<{INITIAL}>" for s in batch)
        assert all(db.get(User, s.id).password_updated_at is None for s in batch)

    def test_threshold_and_charset_constants_are_pinned(self):
        assert len(config.TEMP_PASSWORD_CHARSET) == 56
        for name, value in CONTRACT_CONSTANTS.items():
            assert getattr(config, name) == value, name


# ---------- 4. 审计查看接口（AU-05/06 / QA-19） ----------

class TestAuditLogViewer:
    def test_items_shape_and_actor_name(self, client, db, h_admin, admin_user, teacher):
        student = seed_students(db, 1, prefix="aud")[0]
        client.post("/api/admin/students", headers=h_admin,
                    json={"username": "aud_new", "display_name": "新建号"})
        client.post(f"/api/admin/students/{student.id}/reset_password", headers=h_admin)
        client.post(f"/api/admin/teachers/{teacher.id}/reset_password", headers=h_admin)
        client.patch(f"/api/admin/students/{student.id}", headers=h_admin,
                     json={"is_active": False})

        resp = client.get(AUDIT_URL, headers=h_admin)
        assert resp.status_code == 200, resp.text
        page = resp.json()
        assert set(page) == {"items", "total"}
        assert page["total"] >= 4 and len(page["items"]) <= page["total"]
        for item in page["items"]:
            assert set(item) == {"id", "actor_id", "actor_name", "action", "action_label",
                                 "target_type", "target_label", "target_id", "detail",
                                 "created_at"}
            assert item["action"] and item["target_type"]
            assert item["detail"] is None or isinstance(item["detail"], dict)
            datetime.strptime(item["created_at"], "%Y-%m-%d %H:%M:%S")
        by_action = {i["action"]: i for i in page["items"]}
        assert by_action["student_reset_pw"]["actor_name"] == f"管理员({admin_user.username})"
        assert by_action["student_reset_pw"]["target_id"] == student.id
        # 0.3.2 F5：中文名由服务端随行下发（单一来源：services.audit 的两张标签表）
        assert by_action["student_reset_pw"]["action_label"] == "重置学生密码"
        assert by_action["student_reset_pw"]["target_label"] == "学生"
        assert by_action["teacher_reset_pw"]["target_type"] == "teacher"
        assert by_action["teacher_reset_pw"]["action_label"] == "重置教师密码"
        assert by_action["teacher_reset_pw"]["target_label"] == "教师"
        assert by_action["teacher_reset_pw"]["actor_id"] == admin_user.id
        assert by_action["user_is_active_change"]["detail"] == {"is_active": False}
        assert by_action["student_create_pw"]["detail"] == {"must_change_password": True}

    def test_filter_by_action_and_target_type(self, client, db, h_admin, teacher):
        group = seed_group(db, "审计班")
        students = seed_students(db, 2, prefix="fa")
        for s in students:
            seed_member(db, group, s)
        # 组改名 + 删组：两条 target_type=group 的审计，中间不掺 group_member_change
        client.patch(f"/api/admin/groups/{group.id}", headers=h_admin, json={"name": "审计班改"})
        client.delete(f"/api/admin/groups/{group.id}", headers=h_admin)

        only_groups = client.get(AUDIT_URL, headers=h_admin,
                                 params={"target_type": "group"}).json()
        assert {i["action"] for i in only_groups["items"]} == {"group_update", "group_delete"}
        assert only_groups["total"] == len(only_groups["items"]) == 2
        for item in only_groups["items"]:
            assert item["target_id"] == group.id

        renamed = client.get(AUDIT_URL, headers=h_admin, params={"action": "group_update"}).json()
        # 接口侧 detail 已被解析成 dict（原文是明文 JSON，中文不转义）
        assert [i["detail"] for i in renamed["items"]] == \
            [{"old_name": "审计班", "new_name": "审计班改"}]

        both = client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "group_delete", "target_type": "group"}).json()
        assert len(both["items"]) == 1
        # 组合筛不出来时是空页而不是报错
        none = client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "group_delete", "target_type": "teacher"}).json()
        assert none == {"items": [], "total": 0}
        unknown = client.get(AUDIT_URL, headers=h_admin, params={"action": "no_such_action"}).json()
        assert unknown["total"] == 0

    def test_order_is_desc_and_pagination_slices(self, client, db, h_admin):
        students = seed_students(db, 4, prefix="pg")
        for s in students:
            client.patch(f"/api/admin/students/{s.id}", headers=h_admin,
                         json={"is_active": False})
        full = client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "user_is_active_change"}).json()
        assert full["total"] == 4 and len(full["items"]) == 4
        # (created_at, id) 倒序：秒级时间戳会相同，所以次级键 id 必须是降序
        assert full["items"] == sorted(full["items"],
                                       key=lambda r: (r["created_at"], r["id"]), reverse=True)
        page1 = client.get(AUDIT_URL, headers=h_admin,
                           params={"action": "user_is_active_change", "limit": 2}).json()
        page2 = client.get(AUDIT_URL, headers=h_admin,
                           params={"action": "user_is_active_change", "limit": 2,
                                   "offset": 2}).json()
        assert [i["id"] for i in page1["items"]] == [r["id"] for r in full["items"][:2]]
        assert [i["id"] for i in page2["items"]] == [r["id"] for r in full["items"][2:]]
        assert {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]} == set()
        # total 恒等于筛选后的总数，与分页无关（前端「加载更多」据此判断到底没有）
        assert page1["total"] == page2["total"] == 4
        # limit=0 是合法值：不返回行但 total 照给
        zero = client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "user_is_active_change", "limit": 0}).json()
        assert zero["items"] == [] and zero["total"] == 4

    def test_invalid_pagination_bounds_are_422(self, client, h_admin):
        for params in ({"limit": -1}, {"offset": -1}, {"limit": 201}):
            resp = client.get(AUDIT_URL, headers=h_admin, params=params)
            assert resp.status_code == 422, (params, resp.text)
            assert code_of(resp) == "VALIDATION_ERROR"

    def test_route_is_read_only_and_role_guarded(self, client, db, h_admin, teacher, student):
        paths = app.openapi()["paths"]
        assert list(paths[AUDIT_URL]) == ["get"]        # 无任何改/删入口（AU-05 immutable）
        for method in ("put", "delete", "post", "patch"):
            resp = client.request(method.upper(), AUDIT_URL, headers=h_admin, json={})
            assert resp.status_code == 405, (method, resp.status_code, resp.text)
        for headers in (bearer(teacher), bearer(student)):
            assert code_of(client.get(AUDIT_URL, headers=headers)) == "FORBIDDEN"

    def test_row_written_by_service_is_visible_only_after_commit(self, client, db, h_admin,
                                                                 admin_user):
        # log_audit 只 add 不 commit：未提交的行读不到，提交后 admin 侧可见
        log_audit(db, admin_user, "group_member_change", "group", 7, {"action": "add"})
        assert client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "group_member_change"}).json()["total"] == 0
        db.commit()
        page = client.get(AUDIT_URL, headers=h_admin,
                          params={"action": "group_member_change"}).json()
        assert page["total"] == 1
        assert page["items"][0]["detail"] == {"action": "add"}
        assert page["items"][0]["actor_id"] == admin_user.id
        assert page["items"][0]["target_id"] == 7
        assert page["items"][0]["actor_name"] == "管理员(admin001)"

    def test_actor_name_falls_back_when_actor_is_gone(self, client, db, h_admin, admin_user):
        # CLI 导入没有登录态 → actor_id 为 NULL，admin 侧仍要能读出这行（actor_name 空串）
        log_audit(db, None, "student_import", "user", None, {"success_count": 3})
        db.commit()
        page = client.get(AUDIT_URL, headers=h_admin, params={"action": "student_import"}).json()
        assert page["total"] == 1
        assert page["items"][0]["actor_id"] is None
        assert page["items"][0]["actor_name"] == ""

    def test_required_admin_actions_all_reachable(self, client, db, h_admin, teacher):
        """AU-04 清单里 admin 侧的每个动作都得真的被写出来（一条都不能少）。"""
        g1, g2 = seed_group(db, "一班"), seed_group(db, "二班")
        students = seed_students(db, 2, prefix="cov")
        client.post("/api/admin/students", headers=h_admin,
                    json={"username": "cov_new", "display_name": "建号"})
        client.post("/api/admin/teachers", headers=h_admin,
                    json={"username": "cov_t", "display_name": "建教师"})
        client.post(f"/api/admin/students/{students[0].id}/reset_password", headers=h_admin)
        client.post(f"/api/admin/teachers/{teacher.id}/reset_password", headers=h_admin)
        client.post("/api/admin/students/batch_reset_password", headers=h_admin,
                    json={"student_ids": [students[1].id], "mode": "unified"})
        client.patch(f"/api/admin/students/{students[0].id}", headers=h_admin,
                     json={"is_active": False})
        client.patch(f"/api/admin/teachers/{teacher.id}", headers=h_admin,
                     json={"is_active": False})
        client.post("/api/admin/students/batch_active", headers=h_admin,
                    json={"student_ids": [students[1].id], "is_active": True})
        client.post("/api/admin/students/group_members", headers=h_admin,
                    json={"student_ids": [s.id for s in students],
                          "group_ids": [g1.id, g2.id], "action": "add"})
        client.patch(f"/api/admin/groups/{g1.id}", headers=h_admin, json={"name": "一班改"})
        client.delete(f"/api/admin/groups/{g1.id}", headers=h_admin)
        client.put(f"/api/admin/teachers/{teacher.id}/groups", headers=h_admin,
                   json={"group_ids": [g2.id]})
        client.post("/api/admin/students/import", headers=h_admin,
                    files={"file": ("i.txt", "3001|导入生|导入班\n".encode("utf-8"),
                                    "text/plain")})

        actions = {r.action for r in audit_rows(db)}
        missing = AUDITED_ADMIN_ACTIONS - actions
        assert missing == set(), f"以下审计动作没有落库：{missing}"
        # 启停「逐人一条」：单个 2 条（学生 + 教师）+ 批量 1 条 = 3
        assert len(audit_rows(db, "user_is_active_change")) == 3
        assert len(audit_rows(db, "group_member_change")) == 1
        # 导入：逐生一条 student_create_pw（建号 1 + 导入 1）+ 汇总一条 student_import
        assert len(audit_rows(db, "student_create_pw")) == 2
        imports = audit_rows(db, "student_import")
        assert len(imports) == 1
        assert parse(imports[0].detail) == {"success_count": 1, "failure_count": 0}
        assert imports[0].target_type == "user" and imports[0].target_id is None
        assert imports[0].actor_id is not None
        # 教师名单的启停不影响层 2 分配
        assert db.query(TeacherGroup).filter(TeacherGroup.group_id == g2.id).count() == 1


# ---------- 5. 列表筛选（LI-01/02 / QA-08、QA-09） ----------

class TestAdminListFilters:
    def test_students_q_group_id_and_must_change(self, client, db, h_admin):
        g_a, g_b = seed_group(db, "甲班"), seed_group(db, "乙班")
        zhang = seed_students(db, 1, prefix="zhang", display_prefix="张")[0]
        li = seed_students(db, 1, prefix="li", display_prefix="李")[0]
        pending = seed_students(db, 1, prefix="pend", display_prefix="王", must_change=1)[0]
        seed_member(db, g_a, zhang)
        seed_member(db, g_b, li)
        seed_member(db, g_a, pending)

        def ids(params=None):
            resp = client.get("/api/admin/students", headers=h_admin, params=params)
            assert resp.status_code == 200, resp.text
            return {r["username"] for r in resp.json()}

        # 不传参数 = 旧行为（全量）
        assert ids() == {"zhang1", "li1", "pend1"}
        # q 命中 display_name
        assert ids({"q": "张"}) == {"zhang1"}
        # q 命中 username，且大小写不敏感
        assert ids({"q": "ZHANG"}) == {"zhang1"}
        assert ids({"q": "1"}) == {"zhang1", "li1", "pend1"}
        assert ids({"q": "不存在"}) == set()
        assert ids({"q": "   "}) == {"zhang1", "li1", "pend1"}   # 纯空白不过滤
        # group_id 只看层 1 成员关系
        assert ids({"group_id": g_a.id}) == {"zhang1", "pend1"}
        assert ids({"group_id": g_b.id}) == {"li1"}
        assert ids({"group_id": 99999}) == set()
        # must_change 是「未改密」筛选（徽标可筛，QA-09）
        assert ids({"must_change": 1}) == {"pend1"}
        assert ids({"must_change": 0}) == {"zhang1", "li1"}
        # 三个条件可叠加
        assert ids({"q": "王", "group_id": g_a.id, "must_change": 1}) == {"pend1"}
        assert ids({"q": "王", "group_id": g_b.id, "must_change": 1}) == set()
        # 越界值由 Query 的 ge/le 拦在 schema 层
        for bad in (2, -1):
            resp = client.get("/api/admin/students", headers=h_admin, params={"must_change": bad})
            assert resp.status_code == 422
            assert code_of(resp) == "VALIDATION_ERROR"
        resp = client.get("/api/admin/students", headers=h_admin, params={"must_change": "x"})
        assert resp.status_code == 422

    def test_students_list_carries_badges_and_relations(self, client, db, h_admin, teacher):
        g = seed_group(db, "带徽标的班")
        s = seed_students(db, 1, prefix="badge", must_change=1)[0]
        seed_member(db, g, s)
        _add(db, TeacherGroup(teacher_id=teacher.id, group_id=g.id))
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=s.id))
        rows = client.get("/api/admin/students", headers=h_admin).json()
        assert len(rows) == 1
        row = rows[0]
        assert row["must_change_password"] is True
        assert [gref["name"] for gref in row["groups"]] == ["带徽标的班"]
        assert [t["username"] for t in row["teachers"]] == ["t100"]
        assert row["teachers"][0]["must_change_password"] is False

    def test_teachers_q_filter_and_student_count(self, client, db, h_admin, teacher):
        t_wang = teacher
        t_li = _add(db, User(username="t200", password_hash="x", role="teacher",
                             display_name="李老师", must_change_password=0))
        students = seed_students(db, 2, prefix="cnt")
        _add(db, TeacherStudent(teacher_id=t_wang.id, student_id=students[0].id))
        _add(db, TeacherGroup(teacher_id=t_wang.id, group_id=seed_group(db, "分配班").id))

        def names(params=None):
            resp = client.get("/api/admin/teachers", headers=h_admin, params=params)
            assert resp.status_code == 200, resp.text
            return resp.json()

        assert {r["username"] for r in names()} == {"t100", "t200"}
        assert {r["username"] for r in names({"q": "李"})} == {"t200"}
        assert {r["username"] for r in names({"q": "T2"})} == {"t200"}
        assert names({"q": "没有这个人"}) == []
        row = next(r for r in names() if r["username"] == "t100")
        assert set(row) == {"id", "username", "display_name", "is_active",
                            "must_change_password", "created_at", "student_count"}
        # student_count 统计的是层 3 名单，不受层 2 分配影响
        assert row["student_count"] == 1
        assert row["must_change_password"] is False
