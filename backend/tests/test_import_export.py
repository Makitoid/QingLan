"""v2.0 学生批量导入（xlsx / txt / csv）+ 场次成绩导出 xlsx。

覆盖计划 Step 3「导入改造」与 Step 4「GET /teacher/assignments/{id}/export」。
分组 CRUD / 题目草稿由 tests/test_groups_api.py 负责，此处不重复。

约定（从源码核实）：
- 导入端点 POST /api/admin/students/import，响应 ImportResult
  = {success_count, failures:[{line, content, username, reason}]}，username 可为 null。
- 失败行 reason 实测为「字段缺失」（缺学号或缺姓名）与「学号重复」。
- 文件校验：后缀白名单 415 UNSUPPORTED_FILE_TYPE、>5MB 413 FILE_TOO_LARGE、
  空文件 422 EMPTY_FILE、xlsx 解析不了 422 INVALID_XLSX、文本编码不认识 422
  INVALID_CSV_ENCODING。
- 导出：StreamingResponse，Content-Disposition 同时带 ASCII 兜底 filename 与
  RFC5987 filename*=UTF-8''；表头 学号/姓名/提交次数/最佳有效分/最后提交时间。
"""
import importlib.util
import io
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

import app.core.config as config
from app.api.admin import MAX_IMPORT_BYTES, cell_to_text
from app.core.security import create_token
from app.main import app
from app.models import (Assignment, Group, GroupMember, Problem, Submission,
                        TeacherStudent, User)
from app.schemas import ImportResult

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = REPO_ROOT / "scripts" / "import_students.py"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_HEADER = ["学号", "姓名", "提交次数", "最佳有效分", "最后提交时间"]
IMPORT_URL = "/api/admin/students/import"


# ------------------------------------------------------------------ 基础工具

def _add(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _reload(db):
    """端点用的是另一个 Session：读库前先结束本事务，避免 SQLite 快照陈旧。"""
    db.commit()
    db.expire_all()


def _student_map(db):
    return {u.username: u for u in db.query(User).filter(User.role == "student").all()}


def _group_names(db):
    return sorted(g.name for g in db.query(Group).all())


def _groups_of(db, username):
    student = db.query(User).filter(User.username == username).one()
    rows = db.execute(
        select(Group.name)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.student_id == student.id)
    ).scalars().all()
    return sorted(rows)


def _membership_count(db):
    return db.query(GroupMember).count()


def _upload(client, headers, filename, content, ctype="text/plain"):
    return client.post(IMPORT_URL, headers=headers,
                       files={"file": (filename, content, ctype)})


def _xlsx_bytes(rows, second_sheet=None):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    if second_sheet is not None:
        extra = wb.create_sheet("第二个表")
        for row in second_sheet:
            extra.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_assignment(db, teacher, title="作业1", **kw):
    kw.setdefault("mode", "homework")
    kw.setdefault("start_time", "2026-01-01 00:00:00")
    kw.setdefault("end_time", "2027-01-01 00:00:00")
    kw.setdefault("score_policy", "best")
    return _add(db, Assignment(created_by=teacher.id, title=title, **kw))


def _make_student(db, username, display_name="学生"):
    return _add(db, User(username=username, password_hash="x", role="student",
                         display_name=display_name))


def _bind(db, teacher, *students):
    for s in students:
        _add(db, TeacherStudent(teacher_id=teacher.id, student_id=s.id))


def _submit(db, assignment, student, submitted_at, score=100.0):
    """submissions.problem_id 有外键约束（PRAGMA foreign_keys=ON），取真实题目 ID。"""
    problem_id = db.execute(select(Problem.id).order_by(Problem.id)).scalars().first()
    assert problem_id is not None, "用例需带 problem fixture（提交记录要有外键可用的题目）"
    return _add(db, Submission(
        assignment_id=assignment.id, problem_id=problem_id, user_id=student.id,
        code_text="print(1)", status="done", verdict="AC", score=score,
        submitted_at=submitted_at,
    ))


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    """bcrypt cost=12 约 250ms/学生，测试里换成可辨识的纯函数。

    返回值本身进断言，所以「初始密码 = 学号」这条契约仍被覆盖。
    """
    monkeypatch.setattr("app.api.admin.hash_password", lambda pwd: f"pw<{pwd}>")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def admin(db):
    return _add(db, User(username="root", password_hash="x", role="admin",
                         display_name="管理员"))


@pytest.fixture()
def admin_headers(admin):
    return {"Authorization": f"Bearer {create_token(admin)}"}


@pytest.fixture()
def teacher2(db):
    return _add(db, User(username="t002", password_hash="x", role="teacher",
                         display_name="李老师"))


@pytest.fixture()
def teacher_headers(teacher):
    return {"Authorization": f"Bearer {create_token(teacher)}"}


# ================================================ 导入：txt（含兜底分隔符）

class TestTxtImport:
    def test_pipe_separated_three_columns(self, db, client, admin_headers):
        resp = _upload(client, admin_headers, "s.txt",
                       "1001|张三|甲组\n1002|李四|乙组\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2, "failures": []}

        _reload(db)
        students = _student_map(db)
        assert sorted(students) == ["1001", "1002"]
        assert students["1001"].display_name == "张三"
        # 初始密码 = 学号（见 fast_hash 替身）
        assert students["1001"].password_hash == "pw<1001>"
        assert _groups_of(db, "1001") == ["甲组"]
        assert _groups_of(db, "1002") == ["乙组"]

    def test_no_pipe_falls_back_to_comma_and_fullwidth_comma(self, db, client, admin_headers):
        # 逐行判定：同一文件里三种分隔方式混用
        body = ("2001,王五,甲组\n"
                "2002，赵六，乙组\n"
                "2003|钱七|甲组、丙组\n")
        resp = _upload(client, admin_headers, "mix.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 3

        _reload(db)
        assert set(_student_map(db)) == {"2001", "2002", "2003"}
        assert _groups_of(db, "2001") == ["甲组"]
        assert _groups_of(db, "2002") == ["乙组"]
        assert set(_groups_of(db, "2003")) == {"丙组", "甲组"}

    def test_cells_are_stripped(self, db, client, admin_headers):
        resp = _upload(client, admin_headers, "pad.txt",
                       "  3001  |  孙八  |  甲组  \n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1, "failures": []}

        _reload(db)
        students = _student_map(db)
        assert list(students) == ["3001"]
        assert students["3001"].display_name == "孙八"
        assert _groups_of(db, "3001") == ["甲组"]


# ==================================================== 导入：csv（含两列兼容）

class TestCsvImport:
    def test_three_columns_and_legacy_two_columns(self, db, client, admin_headers):
        # BOM 头同时验证 utf-8-sig 语义
        body = "学号,姓名,组别\n4001,张三,甲组\n4002,李四\n"
        resp = _upload(client, admin_headers, "s.csv", body.encode("utf-8-sig"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2, "failures": []}

        _reload(db)
        students = _student_map(db)
        assert sorted(students) == ["4001", "4002"]
        assert "学号" not in students
        # 两列（无组别）仍是合法的老格式
        assert _groups_of(db, "4002") == []
        assert _groups_of(db, "4001") == ["甲组"]

    def test_comma_in_group_column_keeps_all_groups(self, db, client, admin_headers):
        # csv 的逗号是列分隔符，第 3 列之后的内容并入组别列（不丢数据）
        resp = _upload(client, admin_headers, "s.csv",
                       "5001,张三,甲组,乙组,丙组\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert set(_groups_of(db, "5001")) == {"丙组", "乙组", "甲组"}

    def test_semicolon_and_slash_group_column(self, db, client, admin_headers):
        body = "5002,李四,甲组;乙组\n5003,王五,甲组/丙组\n"
        resp = _upload(client, admin_headers, "s.csv", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 2

        _reload(db)
        assert set(_groups_of(db, "5002")) == {"乙组", "甲组"}
        assert set(_groups_of(db, "5003")) == {"丙组", "甲组"}


# ================================================================== 导入：xlsx

class TestXlsxImport:
    def test_first_sheet_three_columns_and_numeric_student_id(self, db, client, admin_headers):
        rows = [
            ["学号", "姓名", "组别", "备注"],          # 表头 + 第 4 列，均应被忽略
            [20240101, "张三", "甲组", "多余列"],      # Excel 存成 int
            [20240102.0, "李四", "乙组、丙组", ""],    # Excel 存成 float
            ["0012", "王五", "", ""],                 # 文本学号，前导零要保住
            [None, None, None, None],                 # 空行 → 静默跳过
        ]
        payload = _xlsx_bytes(rows, second_sheet=[["9999", "第二表学生", "幽灵组"]])
        resp = _upload(client, admin_headers, "s.xlsx", payload, ctype=XLSX_MIME)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 3, "failures": []}

        _reload(db)
        students = _student_map(db)
        # int / float 单元格还原成无小数点的字符串学号
        assert sorted(students) == ["0012", "20240101", "20240102"]
        assert students["20240102"].display_name == "李四"
        assert set(_groups_of(db, "20240102")) == {"丙组", "乙组"}
        assert _groups_of(db, "0012") == []
        # 只取第一个 sheet 的前 3 列
        assert set(_group_names(db)) == {"丙组", "乙组", "甲组"}
        assert "幽灵组" not in _group_names(db)
        assert "备注" not in students

    def test_unparseable_xlsx(self, client, admin_headers):
        resp = _upload(client, admin_headers, "fake.xlsx", b"definitely-not-a-zip",
                       ctype=XLSX_MIME)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "INVALID_XLSX"

    def test_cell_to_text_contract(self):
        assert cell_to_text(20240101) == "20240101"
        assert cell_to_text(20240101.0) == "20240101"
        assert cell_to_text(12.5) == "12.5"
        assert cell_to_text(None) == ""
        assert cell_to_text("  1001 ") == "1001"


# =================================================== 导入：组别解析与自动建组

class TestGroupAutoCreation:
    def test_all_group_separators(self, db, client, admin_headers):
        body = ("6001|张三|甲、乙\n"
                "6002|李四|甲，丙\n"
                "6003|王五|甲,丁\n"
                "6004|赵六|甲;戊\n"
                "6005|钱七|甲/己\n"
                "6006|孙八|甲、甲\n")        # 同名去重
        resp = _upload(client, admin_headers, "groups.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 6, "failures": []}

        _reload(db)
        # 五个分隔符各切出「甲 + 一个别组」，共 6 个组，无重复行
        assert set(_group_names(db)) == {"丙", "乙", "己", "甲", "戊", "丁"}
        assert len(_group_names(db)) == 6
        for username in ["6001", "6002", "6003", "6004", "6005", "6006"]:
            assert "甲" in _groups_of(db, username)
        assert set(_groups_of(db, "6001")) == {"乙", "甲"}
        assert set(_groups_of(db, "6005")) == {"己", "甲"}
        # 「甲、乙」×5 + 甲 单组 ×1 = 11 条成员关系（去重后）
        assert _membership_count(db) == 11

    def test_existing_group_reused_not_duplicated(self, db, client, admin_headers):
        existing = _add(db, Group(name="甲组"))
        resp = _upload(client, admin_headers, "reuse.txt",
                       "7001|张三|甲组\n7002|李四|甲组、乙组\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 2

        _reload(db)
        assert db.query(Group).filter(Group.name == "甲组").count() == 1
        assert _groups_of(db, "7001") == ["甲组"]

        # 第二批同名组（走 groups 服务的进程内 name→id 缓存）仍复用同一行
        resp2 = _upload(client, admin_headers, "reuse2.txt",
                        "7003|王五|甲组\n".encode("utf-8"))
        assert resp2.status_code == 200, resp2.text
        assert resp2.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert db.query(Group).filter(Group.name == "甲组").count() == 1
        assert db.get(Group, existing.id).name == "甲组"
        assert set(_group_names(db)) == {"乙组", "甲组"}
        assert _groups_of(db, "7003") == ["甲组"]

    def test_no_group_column_creates_no_groups(self, db, client, admin_headers):
        resp = _upload(client, admin_headers, "plain.txt", "8001|张三\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert _group_names(db) == []
        assert _membership_count(db) == 0


# ================================================== 导入：表头 / 空行 / 坏行

class TestRowFiltering:
    def test_header_rows_skipped(self, db, client, admin_headers):
        body = ("学号|姓名|组别\n"
                "学生ID,姓名,组别\n"      # 无 | 时走逗号兜底，仍是表头
                "9001|张三|甲组\n")
        resp = _upload(client, admin_headers, "hdr.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert sorted(_student_map(db)) == ["9001"]
        assert _group_names(db) == ["甲组"]

    def test_blank_lines_silently_skipped(self, db, client, admin_headers):
        # v2.0 行为变更：空行既不导入、也不进 failures
        body = "9101|张三|甲组\r\n\r\n   \n\n\r\n9102|李四|乙组\n\n"
        resp = _upload(client, admin_headers, "blank.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success_count"] == 2
        assert data["failures"] == []

        _reload(db)
        assert sorted(_student_map(db)) == ["9101", "9102"]

    def test_blank_xlsx_rows_skipped(self, db, client, admin_headers):
        payload = _xlsx_bytes([["9201", "张三", "甲组"], [None, None, None],
                               ["", "  ", ""], ["9202", "李四", "乙组"]])
        resp = _upload(client, admin_headers, "blank.xlsx", payload, ctype=XLSX_MIME)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 2, "failures": []}

    def test_bad_rows_reported_without_side_effects(self, db, client, admin_headers):
        body = ("9301|张三|甲组\n"
                "\n"
                "\n"
                "9304||孤立组A\n"          # 缺姓名
                "|李四|孤立组B\n"           # 缺学号
                "9306\n"                    # 只有一列
                "9307,王五\n")              # 两列不算坏行
        resp = _upload(client, admin_headers, "bad.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success_count"] == 2
        assert [(f["line"], f["username"], f["reason"]) for f in data["failures"]] == [
            (4, "9304", "字段缺失"),
            (5, None, "字段缺失"),
            (6, "9306", "字段缺失"),
        ]
        assert [f["content"] for f in data["failures"]] == [
            "9304||孤立组A", "|李四|孤立组B", "9306",
        ]
        # 空行仍占物理行号：9304 在第 4 行
        _reload(db)
        assert sorted(_student_map(db)) == ["9301", "9307"]
        # 坏行的组别名绝不落库
        assert _group_names(db) == ["甲组"]
        assert _membership_count(db) == 1

    def test_header_only_file_imports_nobody(self, db, client, admin_headers):
        resp = _upload(client, admin_headers, "only.csv", "学号,姓名,组别\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 0, "failures": []}

        _reload(db)
        assert _student_map(db) == {}


# ==================================================== 导入：重复学号 / 编码

class TestDuplicatesAndEncoding:
    def test_duplicate_username_rejected_without_group_backfill(self, db, client, admin_headers):
        old = _add(db, User(username="9000", password_hash="x", role="student",
                            display_name="老学生"))
        body = ("9000|新学生|增补组A\n"        # 与库中已有学号冲突
                "9001|甲学生|甲组\n"
                "9000|又一人|甲组\n")          # 与本批第一行冲突
        resp = _upload(client, admin_headers, "dup.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success_count"] == 1
        assert [(f["line"], f["username"], f["reason"], f["content"])
                for f in data["failures"]] == [
            (1, "9000", "学号重复", "9000,新学生"),
            (3, "9000", "学号重复", "9000,又一人"),
        ]

        _reload(db)
        db.refresh(old)
        assert old.display_name == "老学生"           # 未被覆盖
        assert _groups_of(db, "9000") == []           # 未增量补组
        # 冲突行的组别不解析；合法行的组别正常建
        assert "增补组A" not in _group_names(db)
        assert _group_names(db) == ["甲组"]
        assert _groups_of(db, "9001") == ["甲组"]

    def test_utf8_bom_and_gbk_chinese_names(self, db, client, admin_headers):
        # utf-8-sig 编码即「UTF-8 带 BOM」：BOM 只能有一个，且不得混进学号
        bom = "9501|张三|甲组\n".encode("utf-8-sig")
        assert bom.startswith(b"\xef\xbb\xbf")
        resp = _upload(client, admin_headers, "bom.txt", bom)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert sorted(_student_map(db)) == ["9501"]
        assert _student_map(db)["9501"].display_name == "张三"
        assert _group_names(db) == ["甲组"]

        gbk = "9502|李四|乙组\n"
        resp2 = _upload(client, admin_headers, "gbk.txt", gbk.encode("gbk"))
        assert resp2.status_code == 200, resp2.text
        assert resp2.json() == {"success_count": 1, "failures": []}

        _reload(db)
        assert _student_map(db)["9502"].display_name == "李四"
        assert set(_group_names(db)) == {"乙组", "甲组"}

    def test_unknown_encoding_rejected(self, client, admin_headers):
        raw = "9601|张三|甲组".encode("utf-16-le") + b"\x00\x01\xff\xfe"
        resp = _upload(client, admin_headers, "u16.txt", raw)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "INVALID_CSV_ENCODING"


# ================================================ 导入：文件级校验与响应结构

class TestFileValidation:
    def test_unsupported_extension_is_415(self, client, admin_headers):
        for name in ("students.pdf", "students", "students.docx", "a.txt.bak"):
            resp = _upload(client, admin_headers, name, "1001|张三|甲组".encode("utf-8"))
            assert resp.status_code == 415, name
            assert resp.json() == {"code": "UNSUPPORTED_FILE_TYPE",
                                   "message": "仅支持 xlsx / txt / csv 格式"}

    def test_uppercase_extension_allowed(self, db, client, admin_headers):
        resp = _upload(client, admin_headers, "STUDENTS.TXT",
                       "9701|张三|甲组\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 1

        _reload(db)
        assert "9701" in _student_map(db)

    def test_oversized_file_is_413(self, client, admin_headers):
        # 不落地真文件：5MB + 1 字节的内存字节串即可触发前置大小校验
        big = b"1" * (MAX_IMPORT_BYTES + 1)
        assert len(big) > 5 * 1024 * 1024
        resp = _upload(client, admin_headers, "big.txt", big)
        assert resp.status_code == 413, resp.text
        assert resp.json() == {"code": "FILE_TOO_LARGE", "message": "导入文件超过 5MB 限制"}

    def test_exactly_5mb_is_not_too_large(self, client, admin_headers):
        # 边界：恰好 5MB 不算超限（此处用空白内容，解析结果为 0 行）
        body = b" " * MAX_IMPORT_BYTES
        resp = _upload(client, admin_headers, "edge.txt", body)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 0, "failures": []}

    def test_empty_file_is_422(self, client, admin_headers):
        for name in ("empty.txt", "empty.csv", "empty.xlsx"):
            resp = _upload(client, admin_headers, name, b"")
            assert resp.status_code == 422, (name, resp.text)
            assert resp.json() == {"code": "EMPTY_FILE", "message": "导入文件为空"}

    def test_missing_token_is_401(self, client):
        resp = client.post(IMPORT_URL, files={"file": ("s.txt", b"1001|a|b", "text/plain")})
        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"


class TestResponseContract:
    def test_import_result_shape(self, db, client, admin_headers):
        body = ("9901|张三|甲组\n"
                "|缺学号|乙组\n"          # username 为 null
                "9903|李四|甲组\n"
                "9903|重复者|甲组\n")      # username 有值
        resp = _upload(client, admin_headers, "shape.txt", body.encode("utf-8"))
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert set(data) == {"success_count", "failures"}
        assert data["success_count"] == 2
        assert len(data["failures"]) == 2
        for failure in data["failures"]:
            # 前端 types.ts 依赖 username 键存在（值可为 null）
            assert set(failure) == {"line", "content", "username", "reason"}
        assert data["failures"][0]["username"] is None
        assert data["failures"][0]["reason"] == "字段缺失"
        assert data["failures"][1]["username"] == "9903"
        assert data["failures"][1]["reason"] == "学号重复"

        parsed = ImportResult.model_validate(data)     # 响应可被 schema 反序列化
        assert parsed.success_count == 2
        assert [f.line for f in parsed.failures] == [2, 4]

    def test_clean_file_failures_is_empty_list(self, client, admin_headers):
        resp = _upload(client, admin_headers, "ok.txt", "9911|张三|甲组\n".encode("utf-8"))
        assert resp.status_code == 200, resp.text
        assert ImportResult.model_validate(resp.json()).failures == []


# =============================================== 导入：CLI 脚本冒烟（Step 3）

class TestCliScript:
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("qinglan_cli_import_students", CLI_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_script_uses_new_parse_functions(self, db, tmp_path, monkeypatch, capsys):
        # 脚本与本进程共用 conftest 的临时 DATA_DIR，绝不碰 backend/data/cg.db
        assert "qinglan-test-data-" in str(config.DB_PATH)
        assert CLI_SCRIPT.is_file()

        path = tmp_path / "students.txt"
        path.write_text("1201|张三|甲组\n1202|李四|甲组、乙组\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["import_students.py", str(path)])

        self._load_module().main()

        out = capsys.readouterr().out
        assert "成功导入 2" in out
        assert "初始密码为学号" in out
        _reload(db)
        assert sorted(_student_map(db)) == ["1201", "1202"]
        assert _student_map(db)["1201"].password_hash == "pw<1201>"
        assert set(_groups_of(db, "1202")) == {"乙组", "甲组"}

    def test_script_reports_failed_lines_and_exit_code(self, db, tmp_path, monkeypatch, capsys):
        path = tmp_path / "bad.txt"
        path.write_text("1301|张三|甲组\n1302||乙组\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["import_students.py", str(path)])

        with pytest.raises(SystemExit) as excinfo:
            self._load_module().main()
        assert excinfo.value.code == 2

        out = capsys.readouterr().out
        assert "成功导入 1" in out
        assert "第 2 行失败" in out
        assert "字段缺失" in out
        _reload(db)
        assert sorted(_student_map(db)) == ["1301"]

    def test_script_rejects_unsupported_type(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "list.pdf"
        path.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(sys, "argv", ["import_students.py", str(path)])

        with pytest.raises(SystemExit) as excinfo:
            self._load_module().main()
        assert excinfo.value.code == 1
        assert "[UNSUPPORTED_FILE_TYPE]" in capsys.readouterr().out


# ============================================= 导出：权限与响应头（Step 4）

class TestExportAccess:
    def _url(self, assignment):
        return f"/api/teacher/assignments/{assignment.id}/export"

    def test_admin_token_is_forbidden(self, db, client, admin, teacher, assignment):
        resp = client.get(self._url(assignment),
                          headers={"Authorization": f"Bearer {create_token(admin)}"})
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "FORBIDDEN"

    def test_other_teacher_is_forbidden(self, db, client, teacher2, assignment):
        resp = client.get(self._url(assignment),
                          headers={"Authorization": f"Bearer {create_token(teacher2)}"})
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "FORBIDDEN"

    def test_unknown_assignment_is_404(self, db, client, teacher_headers):
        resp = client.get("/api/teacher/assignments/424242/export", headers=teacher_headers)
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "ASSIGNMENT_NOT_FOUND"

    def test_anonymous_is_401(self, db, client, assignment):
        resp = client.get(self._url(assignment))
        assert resp.status_code == 401, resp.text
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_student_token_is_forbidden(self, db, client, student, assignment):
        resp = client.get(self._url(assignment),
                          headers={"Authorization": f"Bearer {create_token(student)}"})
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "FORBIDDEN"


class TestExportResponseHeaders:
    def test_owner_gets_xlsx_with_rfc5987_headers(self, db, client, teacher, teacher_headers,
                                                  assignment):
        _bind(db, teacher, _make_student(db, "2001", "张三"))
        resp = client.get(f"/api/teacher/assignments/{assignment.id}/export",
                          headers=teacher_headers)
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].split(";")[0].strip() == XLSX_MIME

        cd = resp.headers["content-disposition"]
        assert cd.isascii(), cd                       # 中文必须已 percent-encode
        assert cd.startswith("attachment;")
        fallback = re.search(r'filename="([^"]*)"', cd)
        assert fallback and fallback.group(1) == "1_.xlsx"    # ASCII 兜底名
        assert f"filename*=UTF-8''{quote('作业1_成绩.xlsx', safe='')}" in cd
        assert "%E4%BD%9C%E4%B8%9A1_" in cd           # 「作业1_」

    def test_pure_chinese_title_still_has_ascii_fallback(self, db, client, teacher,
                                                         teacher_headers):
        a = _make_assignment(db, teacher, title="期中测验")
        resp = client.get(f"/api/teacher/assignments/{a.id}/export", headers=teacher_headers)
        assert resp.status_code == 200, resp.text
        cd = resp.headers["content-disposition"]
        assert cd.isascii()
        assert quote("期中测验_成绩.xlsx", safe="") in cd
        assert re.search(r'filename="([^"]*)\.xlsx"', cd)


class TestExportWorkbook:
    def _book(self, client, teacher_headers, assignment, tz_offset=None):
        url = f"/api/teacher/assignments/{assignment.id}/export"
        if tz_offset is None:
            resp = client.get(url, headers=teacher_headers)
        else:
            resp = client.get(url, params={"tz_offset": tz_offset}, headers=teacher_headers)
        assert resp.status_code == 200, resp.text
        return load_workbook(io.BytesIO(resp.content))

    def test_structure_header_freeze_and_row_count(self, db, client, teacher, teacher_headers,
                                                   assignment):
        s1 = _make_student(db, "3001", "张三")
        s2 = _make_student(db, "3002", "李四")
        s3 = _make_student(db, "3003", "王五")
        _bind(db, teacher, s1, s2, s3)
        _submit(db, assignment, s1, "2026-03-05 06:20:30", score=80.0)
        _submit(db, assignment, s1, "2026-03-05 07:00:00", score=95.0)
        _submit(db, assignment, s2, "2026-03-06 01:02:03", score=60.0)

        wb = self._book(client, teacher_headers, assignment, tz_offset=0)
        assert wb.sheetnames == ["作业1"]
        ws = wb.active
        assert [c.value for c in ws[1]] == XLSX_HEADER
        assert all(cell.font.bold for cell in ws[1])
        assert ws.freeze_panes == "A2"
        # 行数 = 该教师绑定的学生数，未提交者也占一行
        assert ws.max_row == 1 + 3

        rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
        assert sorted(rows) == ["3001", "3002", "3003"]
        assert rows["3001"][1] == "张三"
        assert rows["3001"][2] == 2                    # 提交次数
        assert float(rows["3001"][3]) == 95.0          # best 策略取最高分
        assert rows["3001"][4] == "2026-03-05 07:00:00"
        assert float(rows["3002"][3]) == 60.0
        # 未提交的学生：0 值 + 空白的「最后提交时间」单元格
        # （openpyxl 回读空字符串单元格为 None，Excel 里同样显示为空）
        assert float(rows["3003"][2]) == 0
        assert float(rows["3003"][3]) == 0
        assert rows["3003"][4] in ("", None)

    def test_rows_match_students_endpoint_payload(self, db, client, teacher, teacher_headers,
                                                  assignment):
        s1 = _make_student(db, "3101", "张三")
        s2 = _make_student(db, "3102", "李四")
        _bind(db, teacher, s1, s2)
        _submit(db, assignment, s2, "2026-04-01 10:00:00", score=70.0)

        listing = client.get(f"/api/teacher/assignments/{assignment.id}/students",
                             headers=teacher_headers).json()
        assert {r["username"] for r in listing} == {"3101", "3102"}

        ws = self._book(client, teacher_headers, assignment, tz_offset=0).active
        assert [r[0] for r in ws.iter_rows(min_row=2, values_only=True)] == [
            r["username"] for r in listing
        ]

    def test_sheet_title_truncated_to_31_chars(self, db, client, teacher_headers, teacher):
        a = _make_assignment(db, teacher, title="长" * 40)
        assert self._book(client, teacher_headers, a, tz_offset=0).sheetnames == ["长" * 31]

    def test_sheet_title_illegal_chars_stripped(self, db, client, teacher_headers, teacher):
        a = _make_assignment(db, teacher, title=r"期中[测试]:*?/\甲乙")
        wb = self._book(client, teacher_headers, a, tz_offset=0)
        assert wb.sheetnames == ["期中测试甲乙"]
        assert wb.active.max_row == 1                  # 无绑定学生 → 只有表头


class TestExportEmptyScores:
    def test_export_without_submissions(self, db, client, teacher, teacher_headers, assignment):
        _bind(db, teacher, _make_student(db, "3201", "张三"),
              _make_student(db, "3202", "李四"))
        ws = self._book(client, teacher_headers, assignment).active   # 不传 tz_offset
        assert [c.value for c in ws[1]] == XLSX_HEADER
        assert ws.max_row == 3
        body = list(ws.iter_rows(min_row=2, values_only=True))
        assert [r[0] for r in body] == ["3201", "3202"]
        assert [r[2] for r in body] == [0, 0]
        # 未提交 → 时间列为空白单元格（openpyxl 回读空串为 None）
        assert all(r[4] in ("", None) for r in body)

    def test_export_without_any_bound_student(self, db, client, teacher_headers, assignment):
        ws = self._book(client, teacher_headers, assignment, tz_offset=480).active
        assert [c.value for c in ws[1]] == XLSX_HEADER
        assert ws.max_row == 1

    @staticmethod
    def _book(client, headers, assignment, tz_offset=None):
        url = f"/api/teacher/assignments/{assignment.id}/export"
        if tz_offset is None:
            resp = client.get(url, headers=headers)
        else:
            resp = client.get(url, params={"tz_offset": tz_offset}, headers=headers)
        assert resp.status_code == 200, resp.text
        return load_workbook(io.BytesIO(resp.content))


class TestExportTimezone:
    """库内是 UTC 字符串（已知坑 9）：导出按 tz_offset 分钟偏移换算本地时间。"""

    UTC_TEXT = "2026-03-05 06:20:30"

    def _times(self, client, teacher_headers, assignment, tz_offset=None):
        url = f"/api/teacher/assignments/{assignment.id}/export"
        if tz_offset is None:
            resp = client.get(url, headers=teacher_headers)
        else:
            resp = client.get(url, params={"tz_offset": tz_offset}, headers=teacher_headers)
        assert resp.status_code == 200, resp.text
        ws = load_workbook(io.BytesIO(resp.content)).active
        return {r[0]: r[4] for r in ws.iter_rows(min_row=2, values_only=True)}

    def test_positive_offset_applied(self, db, client, teacher, teacher_headers, assignment):
        s1 = _make_student(db, "3301", "张三")
        _bind(db, teacher, s1)
        sub = _submit(db, assignment, s1, self.UTC_TEXT, score=88.0)
        _reload(db)
        assert db.get(Submission, sub.id).submitted_at == self.UTC_TEXT   # 库内仍是 UTC

        assert self._times(client, teacher_headers, assignment, 480)["3301"] == \
            "2026-03-05 14:20:30"

    def test_default_offset_is_utc(self, db, client, teacher, teacher_headers, assignment):
        s1 = _make_student(db, "3302", "李四")
        _bind(db, teacher, s1)
        _submit(db, assignment, s1, self.UTC_TEXT, score=88.0)

        assert self._times(client, teacher_headers, assignment)["3302"] == self.UTC_TEXT
        assert self._times(client, teacher_headers, assignment, 0)["3302"] == self.UTC_TEXT

    def test_negative_offset_crosses_date(self, db, client, teacher, teacher_headers, assignment):
        s1 = _make_student(db, "3303", "王五")
        _bind(db, teacher, s1)
        _submit(db, assignment, s1, self.UTC_TEXT, score=88.0)

        assert self._times(client, teacher_headers, assignment, -450)["3303"] == \
            "2026-03-04 22:50:30"

    def test_last_submission_is_max_utc_time(self, db, client, teacher, teacher_headers,
                                             assignment):
        s1 = _make_student(db, "3304", "赵六")
        _bind(db, teacher, s1)
        _submit(db, assignment, s1, "2026-03-05 06:20:30", score=50.0)
        _submit(db, assignment, s1, "2026-03-05 23:10:00", score=20.0)

        url = f"/api/teacher/assignments/{assignment.id}/export"
        resp = client.get(url, params={"tz_offset": 480}, headers=teacher_headers)
        assert resp.status_code == 200, resp.text
        row = next(load_workbook(io.BytesIO(resp.content)).active.iter_rows(
            min_row=2, values_only=True))
        assert row[0] == "3304"
        assert row[4] == "2026-03-06 07:10:00"          # 跨到次日
        assert float(row[2]) == 2                       # 提交次数
        assert float(row[3]) == 50.0                    # 最佳有效分（best 策略）
