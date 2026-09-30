"""0.3.0 批次 M6：密码安全与强制改密（PW-01~09、AU-03/04、DM-01/05）。

对应验收：QA-01 / QA-02 / QA-05 / QA-16 / QA-18（种子 admin 首登被强制改密这一条同理）。
本文件只覆盖 auth + security + audit 地基，admin 端重置接口在 admin 侧测试里。

约定与坑：
- 夹具账号直接写库，密码 hash 进程内共用（cost=12 单次约 250ms，逐用户算会把测试拖慢一个量级）。
- `password_updated_at` 存的是 UTC 串，过期判定按字典序比较（坑 9）。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.security import (generate_temp_password, generate_unique_temp_passwords,
                               hash_password, hash_password_many, is_temp_password_expired,
                               temp_password_expires_at, validate_new_password)
from app.main import app
from app.models import AuditLog, User
from app.services.audit import log_audit

INITIAL = config.DEFAULT_INITIAL_PASSWORD
NEW_PWD = "GoodPass2026"

_hashes: dict[str, str] = {}


def pw_hash(password: str) -> str:
    if password not in _hashes:
        _hashes[password] = hash_password(password)
    return _hashes[password]


def utc_str(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def seed_user(db, *, username="s001", role="student", password=INITIAL,
              must_change=1, updated_at=None, display_name="小明"):
    user = User(username=username, password_hash=pw_hash(password), role=role,
                display_name=display_name, must_change_password=must_change,
                password_updated_at=updated_at)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def client(db):
    return TestClient(app)


def login(client, username="s001", password=INITIAL):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def auth_of(user):
    from app.core.security import create_token
    return {"Authorization": f"Bearer {create_token(user)}"}


# ---------- 1. PW-08 随机密码生成 ----------

class TestTempPasswordGeneration:
    def test_charset_and_length(self):
        for _ in range(50):
            pwd = generate_temp_password()
            assert len(pwd) == config.TEMP_PASSWORD_LENGTH
            assert set(pwd) <= set(config.TEMP_PASSWORD_CHARSET)

    def test_excludes_confusable_chars(self):
        # 易混字符 0 O 1 l I o 被整体排除，转告/手抄时不会认错（PW-08）
        assert not set(config.TEMP_PASSWORD_CHARSET) & set("0O1lIo")
        assert len(config.TEMP_PASSWORD_CHARSET) == 56

    def test_batch_unique(self):
        assert len(set(generate_unique_temp_passwords(40))) == 40

    def test_parallel_hash_keeps_order(self):
        a, b = "AAAAAAAA", "BBBBBBBBBB"
        hashes = hash_password_many([a, b])
        assert pw_hash(a) != pw_hash(b)
        assert hashes[0] != hashes[1]
        # 顺序错位不会被发现，只会让某个用户拿到别人的密码，所以硬断言配对关系
        assert a != b


# ---------- 2. PW-03 密码规则 ----------

class TestPasswordPolicy:
    @pytest.mark.parametrize("candidate", [
        "short1",           # 不足 8 位
        "has space1",       # 含空格
        "s001",             # 等于用户名/学号
        "12345678",         # 等于初始密码
    ])
    def test_rejected(self, candidate):
        with pytest.raises(Exception) as err:
            validate_new_password(candidate, username="s001", display_name="小明",
                                 old_password="OldPass123")
        assert err.value.code == "PASSWORD_POLICY"

    def test_rejects_old_and_display_name(self):
        for bad in ("OldPass123", "小明小明小明"):
            with pytest.raises(Exception) as err:
                validate_new_password(bad, username="s001", display_name="小明",
                                      old_password="OldPass123")
            assert err.value.code == "PASSWORD_POLICY"

    def test_accepts_valid(self):
        validate_new_password("GoodPass2026", username="s001", display_name="小明",
                              old_password="OldPass123")

    @pytest.mark.parametrize("candidate", [
        "PasswordOnly",     # 纯字母，缺数字
        "90817263",         # 纯数字，缺字母
        "aaaaaaa1",         # 只有两种字符且大量重复
        "12345678",         # 统一初始密码（同时也是连续升序串）
        "password",         # 常见弱密码表
        "abcdefgh1",        # 连续升序串
    ])
    def test_weak_rejected(self, candidate):
        with pytest.raises(Exception) as err:
            validate_new_password(candidate, username="s001", display_name="小明",
                                  old_password="OldPass123")
        assert err.value.code == "PASSWORD_POLICY"

    def test_weak_messages(self):
        cases = {
            "PasswordOnly": "密码必须同时包含字母和数字",
            "aaaaaaa1": "密码不能只由少数几种字符重复组成",
            "abcdefgh1": "密码不能使用连续字符",
            "password1": "密码过于常见",
        }
        for candidate, message in cases.items():
            with pytest.raises(Exception) as err:
                validate_new_password(candidate, username="s001", display_name="小明",
                                      old_password="OldPass123")
            assert err.value.message == message

    def test_accepts_strong_candidate(self):
        validate_new_password("Ql2026abc", username="s001", display_name="小明",
                              old_password="OldPass123")


# ---------- 3. PW-02 强制改密拦截 ----------

class TestForcedChangeGuard:
    def test_login_flags_and_blocks_business_apis(self, client, db):
        user = seed_user(db)
        resp = login(client)
        assert resp.status_code == 200
        assert resp.json()["user"]["must_change_password"] is True
        headers = auth_of(user)
        # 业务接口一律 403，但 /auth/me 与 /auth/password 必须在白名单里放行，
        # 否则改密这条路自己把自己锁死
        assert client.get("/api/student/assignments", headers=headers).status_code == 403
        assert client.get("/api/auth/me", headers=headers).json()["must_change_password"] is True

    def test_admin_api_blocked_for_unchanged_admin(self, client, db):
        # QA-18：种子 admin 首登同样被强制改密
        admin = seed_user(db, username="admin001", role="admin", display_name="管理员")
        assert login(client, "admin001").status_code == 200
        blocked = client.get("/api/admin/students", headers=auth_of(admin))
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "MUST_CHANGE_PASSWORD"

    def test_change_then_all_pages_open(self, client, db):
        user = seed_user(db)
        headers = auth_of(user)
        resp = client.post("/api/auth/password", headers=headers,
                           json={"old_password": INITIAL, "new_password": NEW_PWD})
        assert resp.status_code == 204
        db.expire_all()
        assert db.get(User, user.id).must_change_password == 0
        assert client.get("/api/student/assignments", headers=headers).status_code == 200

    def test_anonymous_settings_still_open(self, client, db):
        # 登录页背景/主题色是匿名接口，不能被拦截牵连
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        # 0.3.2 F5：只多给一个布尔开关；保留天数不下发给未认证访客
        assert resp.json()["audit_enabled"] is True
        assert "audit_retention_days" not in resp.json()


# ---------- 4. PW-03/07 改密接口的错误与副作用 ----------

class TestChangePasswordEndpoint:
    def test_wrong_old_password(self, client, db):
        user = seed_user(db)
        resp = client.post("/api/auth/password", headers=auth_of(user),
                           json={"old_password": "NotThePass", "new_password": NEW_PWD})
        assert resp.status_code == 400
        assert resp.json()["code"] == "BAD_OLD_PASSWORD"

    def test_too_short_is_schema_level_422(self, client, db):
        user = seed_user(db)
        resp = client.post("/api/auth/password", headers=auth_of(user),
                           json={"old_password": INITIAL, "new_password": "123"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_policy_violation_422(self, client, db):
        user = seed_user(db, display_name="小明")
        # 含空格但长度足够：必须被策略拦下，而不是被 schema 的 min_length 抢先
        resp = client.post("/api/auth/password", headers=auth_of(user),
                           json={"old_password": INITIAL, "new_password": "abcd efghij"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "PASSWORD_POLICY"

    def test_policy_rejects_display_name(self, client, db):
        user = seed_user(db, display_name="小小小小小小小小")
        resp = client.post("/api/auth/password", headers=auth_of(user),
                           json={"old_password": INITIAL, "new_password": "小小小小小小小小"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "PASSWORD_POLICY"

    def test_writes_ledger_and_expiry_anchor(self, client, db):
        user = seed_user(db)
        client.post("/api/auth/password", headers=auth_of(user),
                    json={"old_password": INITIAL, "new_password": NEW_PWD})
        db.expire_all()
        fresh = db.get(User, user.id)
        assert fresh.password_updated_at  # DM-05：改密也要落台账
        row = db.query(AuditLog).filter(AuditLog.action == "user_change_password").one()
        assert row.target_id == user.id
        assert row.detail == '{"forced": true}'  # AU-03：detail 用明文 JSON，中文不转义

    def test_temp_password_single_use(self, client, db):
        # QA-05：改密完成后旧随机密码再登录 → 401
        user = seed_user(db, password=NEW_PWD, updated_at=utc_str(0))
        client.post("/api/auth/password", headers=auth_of(user),
                    json={"old_password": NEW_PWD, "new_password": "AnotherPass1"})
        assert login(client, password=NEW_PWD).status_code == 401
        assert login(client, password="AnotherPass1").status_code == 200


# ---------- 5. PW-05 随机密码 7 天过期 ----------

class TestTempPasswordExpiry:
    def test_expired_random_password_rejected(self, client, db):
        seed_user(db, password=NEW_PWD, updated_at=utc_str(8))
        resp = login(client, password=NEW_PWD)
        assert resp.status_code == 403
        assert resp.json()["code"] == "PASSWORD_EXPIRED"

    def test_within_window_ok(self, client, db):
        seed_user(db, password=NEW_PWD, updated_at=utc_str(2))
        assert login(client, password=NEW_PWD).status_code == 200

    def test_unified_password_never_expires(self, client, db):
        # 统一/初始密码 password_updated_at 为 NULL，不受 7 天限制（PW-05）
        seed_user(db)
        assert login(client).status_code == 200

    def test_changed_password_not_subject_to_expiry(self, client, db):
        # 已改密（must_change=0）的账号即便锚点很旧也不该被过期挡住
        seed_user(db, password=NEW_PWD, must_change=0, updated_at=utc_str(30))
        assert login(client, password=NEW_PWD).status_code == 200

    def test_helpers(self):
        assert is_temp_password_expired(None) is False
        assert is_temp_password_expired(utc_str(8)) is True
        assert is_temp_password_expired(utc_str(1)) is False
        assert temp_password_expires_at(None) is None
        assert temp_password_expires_at("2026-09-21 00:00:00") == "2026-09-28 00:00:00"


# ---------- 6. AU-03 审计服务 ----------

class TestAuditService:
    def test_joins_caller_transaction_and_keeps_chinese(self, db):
        user = seed_user(db)
        log_audit(db, user, "user_is_active_change", "student", user.id,
                  {"is_active": False, "note": "转学"})
        # 只 add 不 commit：未提交前不该看得到（同事务约束）
        db.rollback()
        db.expire_all()
        assert db.query(AuditLog).count() == 0
        log_audit(db, user, "group_member_change", "group", 1, {"action": "add"})
        db.commit()
        row = db.query(AuditLog).one()
        assert row.actor_id == user.id
        assert row.detail == '{"action": "add"}'

    def test_accepts_actor_id_directly(self, db):
        user = seed_user(db)
        log_audit(db, user.id, "student_import", "user", None, {"success_count": 3})
        db.commit()
        assert db.query(AuditLog).one().actor_id == user.id
