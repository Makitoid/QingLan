"""学生批量导入命令行兜底（与 admin 页面导入同一套解析逻辑）。

支持 .xlsx / .txt / .csv，格式均为「学生ID[,|，]姓名[,|，]组别」，组别列可空、
多组用 、，,；;/ 分隔，不存在的组自动创建。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.admin import parse_import_file, process_import_rows
from app.core.db import SessionLocal
from app.core.security import APIError


def main():
    if len(sys.argv) != 2:
        print("用法: python scripts/import_students.py <xlsx|txt|csv 路径>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"文件不存在: {path}")
        sys.exit(1)
    db = SessionLocal()
    try:
        try:
            rows, failures = parse_import_file(path.name, path.read_bytes())
            result = process_import_rows(db, rows, failures)
        except APIError as e:
            print(f"导入失败: [{e.code}] {e.message}")
            sys.exit(1)
        print(f"成功导入 {result.success_count} 名学生，初始密码为学号")
        for f in result.failures:
            shown = f.username or f.content
            print(f"第 {f.line} 行失败: {shown!r} —— {f.reason}")
        if result.failures:
            sys.exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    main()
