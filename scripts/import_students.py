"""学生批量导入命令行兜底（与 admin 页面导入同一套解析逻辑）。

支持 .xlsx / .txt / .csv，格式均为「学生ID[,|，]姓名[,|，]组别[,|，]教师」，组别与教师列可空、
多值用 、，,；;/ 分隔，不存在的组自动创建；教师列写的是教师用户名，只写「组-教师分配」，
不会把学生拉进该教师的名单（名单由教师本人在自己可教的组里拉）。
新学生的密码统一是初始密码，首次登录会被强制改密。
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
            # 命令行没有登录态，审计的 actor_id 记 NULL（与页面导入同一套落库逻辑）
            result = process_import_rows(db, None, rows, failures)
        except APIError as e:
            print(f"导入失败: [{e.code}] {e.message}")
            sys.exit(1)
        print(f"成功导入 {result.success_count} 名学生，初始密码统一、首登强制改密")
        for f in result.failures:
            shown = f.username or f.content
            print(f"第 {f.line} 行失败: {shown!r} —— {f.reason}")
        if result.failures:
            sys.exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    main()
