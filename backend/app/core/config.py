import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "cg.db"
CODES_DIR = DATA_DIR / "codes"
CASES_DIR = DATA_DIR / "cases"
BG_DIR = DATA_DIR / "bg"

# 默认 5050；Windows 会把默认端口整段保留（绑定报 EACCES），start-local.ps1 顺延后的
# 实际端口记在 data/dev-ports.json 里，手动起 uvicorn / worker 时靠它对上沙箱端口。
def _dev_port(key: str, default: int) -> int:
    try:
        raw = (BASE_DIR / "data" / "dev-ports.json").read_text(encoding="utf-8-sig")
        port = int(json.loads(raw)[key])
    except (OSError, ValueError, KeyError, TypeError):
        return default
    return port if 0 < port < 65536 else default


GO_JUDGE_URL = os.environ.get("GO_JUDGE_URL") or f"http://127.0.0.1:{_dev_port('judge', 5050)}"

COMPILE_TIME_LIMIT_MS = 10_000
COMPILE_MEMORY_LIMIT_MB = 512
PROC_LIMIT = 64
OUTPUT_LIMIT_MB = 1
WORKER_POLL_INTERVAL_S = 1.0
SUBMIT_COOLDOWN_S = 2
MAX_CODE_BYTES = 64 * 1024
CE_STDERR_LIMIT = 4096

# 学生端场次「即将结束」判定窗口（小时）
ENDING_SOON_HOURS = 3

# ---------- 密码与凭证（0.3.0 批次 PW）----------
# 新建账号/统一重置的初始密码（PW-01），明文只用于告知，入库仍是 bcrypt
DEFAULT_INITIAL_PASSWORD = "12345678"
PASSWORD_MIN_LENGTH = 8
TEMP_PASSWORD_LENGTH = 8
# 排除易混字符 0 O 1 l I o，共 56 个（PW-08，以修改意见附录 A 的 JSON 为准）
TEMP_PASSWORD_CHARSET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TEMP_PASSWORD_EXPIRE_DAYS = 7
# 批量重置超过该人数时前端询问「统一初始密码 / 各自随机」（PW-06）
BATCH_RESET_ASK_THRESHOLD = 20
# 随机模式大批量时并行 bcrypt 的线程数（bcrypt 释放 GIL）
BCRYPT_PARALLEL_WORKERS = 8

for _d in (DATA_DIR, CODES_DIR, CASES_DIR, BG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
