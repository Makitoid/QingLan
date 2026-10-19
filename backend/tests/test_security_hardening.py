"""0.5.x 安全整改回归：C-02 / C-01 补偿 / H-04 / M-02 / H-02 / M-04 / L-04。"""
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.security import create_token, hash_password
from app.main import app
from app.models import Problem, TeacherStudent, User
from app.services import export as export_svc

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(db):
    return TestClient(app)


def bearer(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def _seed_user(db, username="sec_t", role="teacher", password="GoodPass2026"):
    user = User(username=username, password_hash=hash_password(password), role=role,
                display_name=username, is_active=1, must_change_password=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- C-02：JWT_SECRET 缺失/弱值拒绝启动 ----------

def _run_python(code: str, **env_overrides):
    env = {k: v for k, v in os.environ.items()
           if k not in {"JWT_SECRET", "APP_ENV"}}
    env.update(env_overrides)
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
                          capture_output=True, text=True)


class TestJwtSecretBoot:
    def test_prod_refuses_missing_secret(self):
        result = _run_python("import app.core.config", APP_ENV="prod")
        assert result.returncode != 0
        assert "JWT_SECRET" in (result.stderr + result.stdout)

    def test_prod_refuses_public_placeholder(self):
        result = _run_python("import app.core.config", APP_ENV="prod",
                             JWT_SECRET="dev-secret-change-me")
        assert result.returncode != 0
        assert "JWT_SECRET" in (result.stderr + result.stdout)

    def test_dev_without_secret_still_boots(self):
        result = _run_python("import app.core.config", APP_ENV="dev")
        assert result.returncode == 0, result.stderr

    def test_prod_disables_api_docs(self):
        result = _run_python(
            "from app.main import app;"
            "assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None",
            APP_ENV="prod", JWT_SECRET="a" * 64,
        )
        assert result.returncode == 0, result.stderr


# ---------- C-01 补偿：登录失败节流 ----------

class TestLoginThrottle:
    def test_account_locks_after_repeated_failures_then_recovers(self, client, db):
        _seed_user(db, username="lockme", role="student", password="GoodPass2026")
        for _ in range(config.LOGIN_ACCOUNT_FAILURE_THRESHOLD):
            resp = client.post("/api/auth/login",
                               json={"username": "lockme", "password": "WrongPass1"})
        assert resp.status_code == 423
        assert resp.json()["code"] == "ACCOUNT_LOCKED"
        assert resp.headers.get("Retry-After")

        # 退避期内即使密码正确也先拒绝
        blocked = client.post("/api/auth/login",
                              json={"username": "lockme", "password": "GoodPass2026"})
        assert blocked.status_code == 423

        from app.core.throttle import reset_all
        reset_all()
        ok = client.post("/api/auth/login",
                         json={"username": "lockme", "password": "GoodPass2026"})
        assert ok.status_code == 200


# ---------- H-04 / L-04：更新路径与负权重 ----------

class TestUpdateBounds:
    def test_problem_update_rejects_unbounded_limits(self, client, db, problem, teacher):
        resp = client.put(f"/api/teacher/problems/{problem.id}", headers=bearer(teacher),
                          json={"time_limit_ms": 10 ** 9, "memory_limit_mb": 10 ** 6})
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_problem_update_accepts_in_range_limits(self, client, db, problem, teacher):
        resp = client.put(f"/api/teacher/problems/{problem.id}", headers=bearer(teacher),
                          json={"time_limit_ms": 30000, "memory_limit_mb": 2048})
        assert resp.status_code == 200, resp.text
        assert resp.json()["time_limit_ms"] == 30000

    def test_case_update_rejects_negative_weight(self, client, db, problem, cases, teacher):
        resp = client.put(f"/api/teacher/cases/{cases[0].id}", headers=bearer(teacher),
                          json={"weight": -1})
        assert resp.status_code == 422


# ---------- M-02：逐题成绩必须属于场次受众 ----------

class TestStudentAudience:
    def test_unbound_student_scores_are_not_readable(self, client, db, teacher, assignment,
                                                     student):
        resp = client.get(
            f"/api/teacher/assignments/{assignment.id}/students/{student.id}/problems",
            headers=bearer(teacher))
        assert resp.status_code == 404
        assert resp.json()["code"] == "STUDENT_NOT_FOUND"

    def test_bound_student_scores_are_readable(self, client, db, teacher, assignment, student):
        db.add(TeacherStudent(teacher_id=teacher.id, student_id=student.id))
        db.commit()
        resp = client.get(
            f"/api/teacher/assignments/{assignment.id}/students/{student.id}/problems",
            headers=bearer(teacher))
        assert resp.status_code == 200, resp.text


# ---------- H-02：导出公式注入 ----------

class TestExportFormulaInjection:
    def test_csv_prefixes_formula_cells(self):
        rows = [{"username": "s001", "name": '=WEBSERVICE("http://evil")',
                 "groups": ["+cmd"], "teachers": ["@x"], "is_active": True}]
        data = export_svc.build_students_csv(rows).decode("utf-8-sig")
        assert "'=WEBSERVICE" in data
        assert "'+cmd" in data
        assert "'@x" in data

    def test_xlsx_writes_literal_text_not_formula(self):
        rows = [{"username": "s001", "name": "=1+1", "groups": [],
                 "teachers": [], "is_active": True}]
        wb = export_svc.load_openpyxl().load_workbook(
            BytesIO(export_svc.build_students_xlsx(rows)), data_only=False)
        cell = wb.active["B2"]
        assert cell.value == "=1+1"
        assert cell.data_type == "s"


# ---------- M-04：ASGI 请求体上限 ----------

class TestBodyLimit:
    def test_oversized_body_is_rejected_before_parsing(self, client):
        payload = b"x" * (config.MAX_REQUEST_BYTES + 1)
        resp = client.post("/api/auth/login", content=payload,
                           headers={"content-type": "application/json"})
        assert resp.status_code == 413
        assert resp.json()["code"] == "REQUEST_TOO_LARGE"


# ---------- M-07：判题产物清理在 test_worker 中断言 ----------
