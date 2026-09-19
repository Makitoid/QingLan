"""成绩导出：openpyxl 生成 xlsx。

openpyxl 采用函数内延迟 import —— 未安装该依赖时后端进程仍可启动，
只有真正调用导出/解析接口才报错，避免拖垮整个服务。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote

from ..core.security import APIError

XLSX_SHEET_MAX_LEN = 31
XLSX_SHEET_ILLEGAL = "[]:*?/\\"
XLSX_HEADER = ["学号", "姓名", "提交次数", "最佳有效分", "最后提交时间"]
XLSX_COL_WIDTHS = [16, 16, 12, 14, 22]
TIME_FMT = "%Y-%m-%d %H:%M:%S"

MISSING_OPENPYXL = APIError(500, "OPENPYXL_MISSING", "服务器未安装 openpyxl，无法处理 Excel 文件")


def load_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise MISSING_OPENPYXL
    return openpyxl


def sheet_title(title: str) -> str:
    """Excel 限制：sheet 名 ≤31 字符且不含 []:*?/\\ ；空名回退为「成绩」。"""
    cleaned = "".join(ch for ch in (title or "") if ch not in XLSX_SHEET_ILLEGAL).strip()
    cleaned = cleaned[:XLSX_SHEET_MAX_LEN]
    return cleaned or "成绩"


def to_local(utc_text: str | None, tz_offset: int) -> str:
    """库内时间存 UTC（本项目已知坑 9）；导出按前端传入的分钟偏移换算本地时间。"""
    if not utc_text:
        return ""
    try:
        moment = datetime.strptime(utc_text[:19], TIME_FMT)
    except ValueError:
        return utc_text
    return (moment + timedelta(minutes=tz_offset)).strftime(TIME_FMT)


def build_assignment_students_xlsx(assignment_title: str, rows: list[dict], tz_offset: int = 0) -> bytes:
    """场次学生成绩 → xlsx 字节串。

    rows 为 services.stats.student_rows 的输出（含 username / name /
    submitted_count / best_effective_score / last_submitted_at）。
    """
    openpyxl = load_openpyxl()
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title(assignment_title)

    ws.append(XLSX_HEADER)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for idx, width in enumerate(XLSX_COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    for row in rows:
        ws.append([
            row.get("username", ""),
            row.get("name", ""),
            row.get("submitted_count", 0),
            row.get("best_effective_score", 0),
            to_local(row.get("last_submitted_at"), tz_offset),
        ])

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def attachment_headers(filename: str) -> dict[str, str]:
    """Content-Disposition：RFC5987 filename* 传中文，另给 ASCII 兜底文件名。"""
    safe = "".join(ch for ch in filename if ch.isascii() and (ch.isalnum() or ch in "._-")) or "export"
    fallback = safe if safe.lower().endswith(".xlsx") else f"{safe}.xlsx"
    quoted = quote(filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx", safe="")
    return {"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quoted}"}
