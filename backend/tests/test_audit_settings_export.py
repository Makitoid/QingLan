"""0.3.2 F5-2：系统设置里的审计开关、保留期清理与 Excel 导出。

契约以代码实际行为为准（app/services/audit.py、app/api/admin.py、app/schemas.py）：
- ``PUT /admin/settings`` 收 ``audit_enabled`` 与 ``audit_retention_days``（NULL = 永久保存），
  天数范围 1–3650，越界一律 422 ``AUDIT_RETENTION_INVALID``；未出现在请求体里的字段不改动。
- 公开 ``GET /api/settings`` 只多给 ``audit_enabled`` 一个布尔；保留天数只在 admin 端点出现。
- ``audit_enabled = 0``：``log_audit`` 直接返回（不落库）、列表接口 403 ``AUDIT_DISABLED``；
  关闭不删历史，重新打开后历史照常可见。
- 开关判定进程内缓存，写设置时显式失效（``invalidate_audit_cache``）。
- ``prune_expired``：保留期非空时删除 ``created_at < now - N 天`` 的行，NULL 一条不删；
  调用点三处——应用启动、改完保留期、``log_audit`` 内每小时最多一次的惰性触发。
- ``GET /admin/audit_logs/export`` → xlsx，列
  ``时间 / 操作人 / 工号 / 动作 / 对象类型 / 对象 ID / 详情 JSON``，中文名取自
  ``services.audit`` 的标签表；超过 50000 行 422 ``AUDIT_EXPORT_TOO_LARGE``。
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.core.security import create_token, utcnow_str
from app.main import app
from app.models import AuditLog, SiteSetting, User
from app.services import audit as audit_svc
from app.services.audit import (AUDIT_EXPORT_HEADER, AUDIT_EXPORT_MAX_ROWS,
                                AUDIT_RETENTION_MAX_DAYS, AUDIT_RETENTION_MIN_DAYS,
                                log_audit, prune_expired)
from app.services.export import XLSX_MEDIA_TYPE

PUBLIC_SETTINGS = "/api/settings"
ADMIN_SETTINGS = "/api/admin/settings"
AUDIT_URL = "/api/admin/audit_logs"
EXPORT_URL = "/api/admin/audit_logs/export"
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def code_of(resp):
    return resp.json().get("code")


def fresh(db):
    db.commit()
    db.expire_all()


def ago(days: int, extra_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days, seconds=extra_seconds)).strftime(TIME_FMT)


def seed_log(db, actor_id=None, action="student_reset_pw", target_type="student",
             target_id=1, created_at=None, detail=None):
    return _add(db, AuditLog(actor_id=actor_id, action=action, target_type=target_type,
                             target_id=target_id, detail=detail,
                             created_at=created_at or utcnow_str()))


def set_retention(db, days):
    row = db.get(SiteSetting, 1)
    row.audit_retention_days = days
    db.commit()
    audit_svc.invalidate_audit_cache()


def audit_count(db):
    fresh(db)
    return db.query(AuditLog).count()


def remaining_ids(db):
    """现存审计行 id（升序）；删掉的行不能再用 db.get 读，否则触发 ObjectDeletedError。"""
    fresh(db)
    return sorted(row[0] for row in db.query(AuditLog.id).all())


def actions_in(db):
    """现存审计行的动作名（升序）。id 会被 SQLite 复用，跨删除比较不能只看 id。"""
    fresh(db)
    return sorted(row[0] for row in db.query(AuditLog.action).all())


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def admin_user(db):
    return _add(db, User(username="admin900", password_hash="x", role="admin",
                         display_name="管理员", must_change_password=0))


@pytest.fixture()
def h_admin(admin_user):
    return bearer(admin_user)


@pytest.fixture()
def teacher(db):
    return _add(db, User(username="t900", password_hash="x", role="teacher",
                         display_name="王老师", must_change_password=0))


# ---------- 1. 设置字段：可读可写、NULL = 永久、越界 422 ----------

class TestAuditSettingsFields:
    def test_put_accepts_both_fields_and_admin_get_reads_retention(self, client, db, h_admin):
        resp = client.put(ADMIN_SETTINGS, headers=h_admin,
                          json={"audit_enabled": False, "audit_retention_days": 30})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["audit_enabled"] is False
        assert body["audit_retention_days"] == 30
        # 主题设置的老字段仍在同一份 DTO 里
        assert body["brand_color"] == "#0F6CBD"

        fresh(db)
        row = db.get(SiteSetting, 1)
        assert (row.audit_enabled, row.audit_retention_days) == (0, 30)

        admin_get = client.get(ADMIN_SETTINGS, headers=h_admin)
        assert admin_get.status_code == 200, admin_get.text
        assert admin_get.json()["audit_retention_days"] == 30

        # 公开端点只多一个布尔；保留天数与日志内容都不给未认证访客
        public = client.get(PUBLIC_SETTINGS)
        assert public.status_code == 200, public.text
        assert public.json()["audit_enabled"] is False
        assert "audit_retention_days" not in public.json()

    def test_null_retention_means_keep_forever(self, client, db, h_admin):
        assert client.put(ADMIN_SETTINGS, headers=h_admin,
                          json={"audit_retention_days": 7}).json()["audit_retention_days"] == 7
        body = client.put(ADMIN_SETTINGS, headers=h_admin,
                          json={"audit_retention_days": None}).json()
        assert body["audit_retention_days"] is None
        fresh(db)
        assert db.get(SiteSetting, 1).audit_retention_days is None

    def test_omitted_field_is_not_touched(self, client, db, h_admin):
        client.put(ADMIN_SETTINGS, headers=h_admin,
                   json={"audit_enabled": False, "audit_retention_days": 10})
        body = client.put(ADMIN_SETTINGS, headers=h_admin, json={"bg_opacity": 0.2}).json()
        assert body["bg_opacity"] == 0.2
        assert body["audit_enabled"] is False and body["audit_retention_days"] == 10

    def test_retention_bounds_and_out_of_range_is_422(self, client, db, h_admin):
        for days in (AUDIT_RETENTION_MIN_DAYS, AUDIT_RETENTION_MAX_DAYS):
            resp = client.put(ADMIN_SETTINGS, headers=h_admin,
                              json={"audit_retention_days": days})
            assert resp.status_code == 200, (days, resp.text)
            assert resp.json()["audit_retention_days"] == days
        for bad in (0, -1, AUDIT_RETENTION_MAX_DAYS + 1):
            resp = client.put(ADMIN_SETTINGS, headers=h_admin,
                              json={"audit_retention_days": bad})
            assert resp.status_code == 422, (bad, resp.text)
            assert code_of(resp) == "AUDIT_RETENTION_INVALID"
        fresh(db)
        # 越界请求整体失败，保留值仍是最后一次成功的 3650
        assert db.get(SiteSetting, 1).audit_retention_days == AUDIT_RETENTION_MAX_DAYS

    def test_admin_settings_requires_admin(self, client, db, teacher):
        assert code_of(client.get(ADMIN_SETTINGS, headers=bearer(teacher))) == "FORBIDDEN"
        assert client.get(ADMIN_SETTINGS).status_code == 401


# ---------- 2. 开关生效：不落库 + 列表 403，且历史不丢 ----------

class TestAuditDisabled:
    def _disable(self, client, h_admin):
        resp = client.put(ADMIN_SETTINGS, headers=h_admin, json={"audit_enabled": False})
        assert resp.status_code == 200, resp.text

    def test_log_audit_does_not_persist_while_disabled(self, client, db, h_admin, admin_user):
        self._disable(client, h_admin)
        log_audit(db, admin_user, "student_reset_pw", "student", 1, {"mode": "random"})
        db.commit()
        assert audit_count(db) == 0
        # 业务接口同理：批量启停不写审计
        student = _add(db, User(username="s900", password_hash="x", role="student",
                                display_name="小明", must_change_password=0))
        client.patch(f"/api/admin/students/{student.id}", headers=h_admin,
                     json={"is_active": False})
        assert audit_count(db) == 0

    def test_list_endpoint_403_while_disabled(self, client, db, h_admin, admin_user):
        seed_log(db, admin_user.id)
        self._disable(client, h_admin)
        resp = client.get(AUDIT_URL, headers=h_admin)
        assert resp.status_code == 403, resp.text
        assert code_of(resp) == "AUDIT_DISABLED"
        # 列表被拒不代表日志被删
        assert audit_count(db) == 1

    def test_disable_keeps_history_and_reenable_shows_it(self, client, db, h_admin, admin_user):
        seed_log(db, admin_user.id, action="group_update", target_type="group", target_id=5)
        seed_log(db, admin_user.id, action="group_delete", target_type="group", target_id=5)
        self._disable(client, h_admin)
        assert code_of(client.get(AUDIT_URL, headers=h_admin)) == "AUDIT_DISABLED"

        back = client.put(ADMIN_SETTINGS, headers=h_admin, json={"audit_enabled": True})
        assert back.json()["audit_enabled"] is True
        page = client.get(AUDIT_URL, headers=h_admin).json()
        assert page["total"] == 2
        assert {i["action"] for i in page["items"]} == {"group_update", "group_delete"}
        # 重新打开后新写入照常落库
        log_audit(db, admin_user, "student_import", "user", None, {"success_count": 1})
        db.commit()
        assert audit_count(db) == 3

    def test_enabled_flag_is_cached_until_invalidated(self, client, db, h_admin, admin_user):
        log_audit(db, admin_user, "group_update", "group", 1, None)
        db.commit()
        assert db.query(AuditLog).count() == 1
        # 绕过接口直接改库不会立刻生效：判定结果已被缓存
        row = db.get(SiteSetting, 1)
        row.audit_enabled = 0
        db.commit()
        log_audit(db, admin_user, "group_delete", "group", 1, None)
        db.commit()
        assert audit_count(db) == 2
        # 显式失效（PUT /admin/settings 走的就是这条路径）后立即生效
        audit_svc.invalidate_audit_cache()
        log_audit(db, admin_user, "group_update", "group", 1, None)
        db.commit()
        assert audit_count(db) == 2

    def test_export_still_available_while_disabled(self, client, db, h_admin, admin_user):
        seed_log(db, admin_user.id, action="group_update", target_type="group", target_id=5)
        self._disable(client, h_admin)
        resp = client.get(EXPORT_URL, headers=h_admin)
        assert resp.status_code == 200, resp.text
        # 表头 + 一行数据：关闭开关只是停写新日志，历史台账仍可导出
        assert len(workbook_rows(resp.content)) == 2


# ---------- 3. 保留期清理 ----------

class TestRetentionPrune:
    def test_put_retention_prunes_old_rows_immediately(self, client, db, h_admin, admin_user):
        old = seed_log(db, admin_user.id, created_at=ago(10))
        new = seed_log(db, admin_user.id, action="group_update", target_type="group",
                       created_at=ago(0, 5))
        old_id, new_id = old.id, new.id
        resp = client.put(ADMIN_SETTINGS, headers=h_admin, json={"audit_retention_days": 5})
        assert resp.status_code == 200, resp.text
        assert remaining_ids(db) == [new_id], f"保留期外的 {old_id} 应已被清理"

    def test_prune_returns_deleted_count_and_null_keeps_everything(self, db, admin_user):
        set_retention(db, 7)
        seed_log(db, admin_user.id, created_at=ago(8))
        seed_log(db, admin_user.id, created_at=ago(30))
        keep = seed_log(db, admin_user.id, created_at=ago(1))
        assert prune_expired(db) == 2
        db.commit()
        assert remaining_ids(db) == [keep.id]
        # 幂等：没有可删的行时返回 0
        assert prune_expired(db) == 0

        set_retention(db, None)
        old = seed_log(db, admin_user.id, created_at=ago(3650))
        assert prune_expired(db) == 0
        db.commit()
        assert remaining_ids(db) == sorted([keep.id, old.id])

    def test_log_audit_prunes_lazily_at_most_once_per_hour(self, db, admin_user):
        set_retention(db, 1)
        seed_log(db, admin_user.id, action="stale_one", created_at=ago(3))
        log_audit(db, admin_user, "group_update", "group", 1, None)
        db.commit()
        assert actions_in(db) == ["group_update"]

        # 守卫未到期：再写一条也不会顺带清理
        seed_log(db, admin_user.id, action="stale_two", created_at=ago(3))
        log_audit(db, admin_user, "group_delete", "group", 1, None)
        db.commit()
        assert actions_in(db) == ["group_delete", "group_update", "stale_two"]

        # 重臂守卫（PUT /admin/settings 之后的路径）→ 下一次 log_audit 立即清理
        audit_svc.invalidate_audit_cache()
        log_audit(db, admin_user, "group_update", "group", 2, None)
        db.commit()
        assert actions_in(db) == ["group_delete", "group_update", "group_update"]

    def test_disabled_log_audit_skips_prune(self, db, admin_user):
        set_retention(db, 1)
        old = seed_log(db, admin_user.id, created_at=ago(5))
        row = db.get(SiteSetting, 1)
        row.audit_enabled = 0
        db.commit()
        audit_svc.invalidate_audit_cache()
        log_audit(db, admin_user, "group_update", "group", 1, None)
        db.commit()
        assert old.id in remaining_ids(db)


# ---------- 4. Excel 导出 ----------

def workbook_rows(payload: bytes) -> list[tuple]:
    wb = openpyxl.load_workbook(BytesIO(payload))
    return list(wb.active.iter_rows(values_only=True))


class TestAuditExport:
    def test_returns_xlsx_with_chinese_label_columns(self, client, db, h_admin, admin_user):
        before = utcnow_str()
        seed_log(db, admin_user.id, action="student_reset_pw", target_type="student",
                 target_id=42, detail='{"mode": "random"}')
        resp = client.get(EXPORT_URL, headers=h_admin)
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == XLSX_MEDIA_TYPE
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "filename*=UTF-8''" in disposition

        rows = workbook_rows(resp.content)
        assert list(rows[0]) == AUDIT_EXPORT_HEADER
        assert len(rows) == 2
        time_cell, actor, username, action, target_type, target_id, detail = rows[1]
        assert before <= time_cell <= utcnow_str()
        assert (actor, username) == ("管理员", "admin900")
        assert action == "重置学生密码"          # 服务端标签表是唯一中文来源
        assert target_type == "学生"
        assert target_id == 42
        assert detail == '{"mode": "random"}'

    def test_filters_are_respected(self, client, db, h_admin, admin_user):
        seed_log(db, admin_user.id, action="student_reset_pw", target_type="student")
        seed_log(db, admin_user.id, action="group_update", target_type="group", target_id=7)
        seed_log(db, admin_user.id, action="group_delete", target_type="group", target_id=7)
        only_groups = workbook_rows(
            client.get(EXPORT_URL, headers=h_admin, params={"target_type": "group"}).content)
        assert {r[3] for r in only_groups[1:]} == {"分组改名", "删除分组"}
        one = workbook_rows(
            client.get(EXPORT_URL, headers=h_admin,
                       params={"action": "group_delete", "target_type": "group"}).content)
        assert len(one) == 2 and one[1][3] == "删除分组"
        windowed = workbook_rows(
            client.get(EXPORT_URL, headers=h_admin,
                       params={"start": "2999-01-01 00:00:00"}).content)
        assert len(windowed) == 1

    def test_retention_window_is_respected(self, client, db, h_admin, admin_user):
        seed_log(db, admin_user.id, created_at=ago(40))
        keep = seed_log(db, admin_user.id, action="group_update", target_type="group",
                        created_at=ago(1))
        set_retention(db, 10)
        rows = workbook_rows(client.get(EXPORT_URL, headers=h_admin).content)
        assert len(rows) == 2
        assert rows[1][3] == "分组改名"
        assert db.get(AuditLog, keep.id) is not None

    def test_too_many_rows_is_422(self, client, db, h_admin, admin_user, monkeypatch):
        seed_log(db, admin_user.id)
        seed_log(db, admin_user.id, action="group_update", target_type="group")
        monkeypatch.setattr(admin_api, "AUDIT_EXPORT_MAX_ROWS", 1)
        resp = client.get(EXPORT_URL, headers=h_admin)
        assert resp.status_code == 422, resp.text
        assert code_of(resp) == "AUDIT_EXPORT_TOO_LARGE"
        assert "筛选" in resp.json()["message"]
        # 加筛选条件后同一次导出就能过
        ok = client.get(EXPORT_URL, headers=h_admin, params={"action": "group_update"})
        assert ok.status_code == 200, ok.text
        # 默认上限即契约常量
        assert AUDIT_EXPORT_MAX_ROWS == 50000

    def test_export_is_admin_only(self, client, db, teacher):
        for headers in (bearer(teacher), None):
            resp = client.get(EXPORT_URL, headers=headers) if headers else client.get(EXPORT_URL)
            assert code_of(resp) in ("FORBIDDEN", "UNAUTHORIZED"), resp.text
