import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.admin import parse_csv_bytes, process_csv_rows
from app.core.db import SessionLocal
from app.core.security import APIError


def main():
    if len(sys.argv) != 2:
        print("用法: python scripts/import_students.py <csv路径>")
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.is_file():
        print(f"文件不存在: {csv_path}")
        sys.exit(1)
    db = SessionLocal()
    try:
        try:
            text = parse_csv_bytes(csv_path.read_bytes())
            result = process_csv_rows(db, text)
        except APIError as e:
            print(f"导入失败: [{e.code}] {e.message}")
            sys.exit(1)
        print(f"成功导入 {result.success_count} 名学生，初始密码为学号")
        for f in result.failures:
            print(f"第 {f.line} 行失败: {f.content!r} —— {f.reason}")
        if result.failures:
            sys.exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    main()
