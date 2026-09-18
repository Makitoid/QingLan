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

GO_JUDGE_URL = os.environ.get("GO_JUDGE_URL", "http://127.0.0.1:5050")

COMPILE_TIME_LIMIT_MS = 10_000
COMPILE_MEMORY_LIMIT_MB = 512
PROC_LIMIT = 64
OUTPUT_LIMIT_MB = 1
WORKER_POLL_INTERVAL_S = 1.0
SUBMIT_COOLDOWN_S = 2
MAX_CODE_BYTES = 64 * 1024
CE_STDERR_LIMIT = 4096

for _d in (DATA_DIR, CODES_DIR, CASES_DIR, BG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
