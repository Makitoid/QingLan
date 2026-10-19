import json
import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

# ---------- 运行环境与 JWT 密钥（C-02）----------
# APP_ENV=dev 仅供本机开发：允许不配 JWT_SECRET，每次启动生成随机密钥
# （旧令牌随重启失效，仍免配置）。其余环境必须显式提供足够强的密钥，
# 否则拒绝启动——绝不回落到源码里公开的默认值。
APP_ENV = (os.environ.get("APP_ENV") or "prod").strip().lower()
IS_DEV = APP_ENV in {"dev", "development", "local", "test"}
_WEAK_JWT_SECRETS = {
    "dev-secret-change-me",
    "change-me-to-a-long-random-string",
    "changeme",
    "change-me",
    "secret",
    "jwt-secret",
}
_jwt_secret = (os.environ.get("JWT_SECRET") or "").strip()
if not _jwt_secret:
    if IS_DEV:
        _jwt_secret = secrets.token_hex(32)
        print("[config] APP_ENV=dev 且未配置 JWT_SECRET，已生成本次进程随机密钥", file=sys.stderr)
    else:
        raise RuntimeError(
            "JWT_SECRET 未配置：生产/部署环境必须显式设置一个至少 32 字符的随机密钥"
            "（可用 `openssl rand -hex 32` 生成）"
        )
elif _jwt_secret.lower() in _WEAK_JWT_SECRETS or len(_jwt_secret) < 32:
    if not IS_DEV:
        raise RuntimeError(
            "JWT_SECRET 过弱：请使用至少 32 字符的随机密钥，且不要沿用示例/默认值"
            "（可用 `openssl rand -hex 32` 生成）"
        )
    print("[config] APP_ENV=dev：JWT_SECRET 过弱，仅限本机开发使用", file=sys.stderr)

JWT_SECRET = _jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12
# 生产默认关闭交互式 API 文档（L-01）；dev 保留 /docs 方便调试。
DOCS_ENABLED = IS_DEV

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

# ---------- 请求体上限（M-04）----------
# 名单导入/背景图各有 5MB 业务上限，这里留出 multipart 包装余量；
# 超过该值的请求在 ASGI 层直接断掉，避免未认证的大包把 2C2G 机器打满。
MAX_REQUEST_BYTES = 8 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024

# ---------- 登录节流（C-01 补偿控制）----------
# 统一初始密码按产品要求保留，因此用账号维度指数退避 + IP 维度滑动窗口，
# 抬高批量撞号/密码喷洒的成本。阈值与窗口均为进程内状态，重启即清零。
LOGIN_THROTTLE_ENABLED = True
LOGIN_ACCOUNT_FAILURE_THRESHOLD = 5
LOGIN_ACCOUNT_LOCK_BASE_S = 30
LOGIN_ACCOUNT_LOCK_MAX_S = 900
LOGIN_IP_FAILURE_THRESHOLD = 30
LOGIN_IP_WINDOW_S = 60

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
