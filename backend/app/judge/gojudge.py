from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..core import config


class GoJudgeError(RuntimeError):
    pass


@dataclass
class RunResult:
    time_ms: int
    memory_kb: int
    exit_code: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    status: str


_STATUS_MAP = {
    "Accepted": "ok",
    "Time Limit Exceeded": "time_limit",
    "Memory Limit Exceeded": "memory_limit",
    "Output Limit Exceeded": "output_limit",
    "Nonzero Exit Status": "runtime_error",
    "Signalled": "runtime_error",
    "Runtime Error": "runtime_error",
    "Dangerous Syscall": "runtime_error",
    "File Error": "runtime_error",
    "Internal Error": "runtime_error",
    "Invalid": "runtime_error",
}

_DEFAULT_ENV = ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
_STDERR_COLLECT_MAX = 1024 * 1024


def health_check(timeout: float = 5.0) -> bool:
    try:
        resp = httpx.get(f"{config.GO_JUDGE_URL}/version", timeout=timeout)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _to_run_result(res: dict, output_limit_bytes: int) -> RunResult:
    raw_status = res.get("status", "")
    status = _STATUS_MAP.get(raw_status, "runtime_error")
    exit_status = res.get("exitStatus")
    if raw_status == "Signalled":
        exit_code, signal = None, exit_status
    elif exit_status is None:
        exit_code, signal = None, None
    else:
        exit_code, signal = exit_status, None
    files = res.get("files") or {}
    stdout = files.get("stdout", "").encode("utf-8", errors="replace")[:output_limit_bytes]
    stderr = files.get("stderr", "").encode("utf-8", errors="replace")
    error_msg = res.get("error") or ""
    if error_msg:
        extra = error_msg.encode("utf-8", errors="replace")
        stderr = stderr + b"\n" + extra if stderr else extra
    return RunResult(
        time_ms=int(res.get("time", 0)) // 1_000_000,
        memory_kb=int(res.get("memory", 0)) // 1024,
        exit_code=exit_code,
        signal=signal,
        stdout=stdout,
        stderr=stderr,
        status=status,
    )


def _execute(
    argv: list[str],
    stdin_data: bytes,
    *,
    time_limit_ms: int,
    memory_limit_mb: int,
    proc_limit: int,
    output_limit_mb: int,
    copy_in: dict[str, bytes] | None = None,
    copy_in_file_ids: dict[str, str] | None = None,
    copy_out_cached: list[str] | None = None,
) -> tuple[RunResult, dict[str, str]]:
    cpu_limit_ns = time_limit_ms * 1_000_000
    output_limit_bytes = output_limit_mb * 1024 * 1024
    cmd: dict = {
        "args": list(argv),
        "env": list(_DEFAULT_ENV),
        "files": [
            {"content": stdin_data.decode("utf-8", errors="replace")},
            {"name": "stdout", "max": output_limit_bytes},
            {"name": "stderr", "max": _STDERR_COLLECT_MAX},
        ],
        "cpuLimit": cpu_limit_ns,
        "clockLimit": cpu_limit_ns * 2,
        "memoryLimit": memory_limit_mb * 1024 * 1024,
        "procLimit": proc_limit,
        "copyIn": {},
    }
    for dst, content in (copy_in or {}).items():
        cmd["copyIn"][dst] = {"content": content.decode("utf-8", errors="replace")}
    for dst, file_id in (copy_in_file_ids or {}).items():
        cmd["copyIn"][dst] = {"fileId": file_id}
    if copy_out_cached:
        cmd["copyOutCached"] = list(copy_out_cached)
    timeout_s = time_limit_ms / 1000 * 2 + 15
    resp = httpx.post(f"{config.GO_JUDGE_URL}/run", json={"cmd": [cmd]}, timeout=timeout_s)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        payload = payload["results"]
    if not isinstance(payload, list) or not payload:
        raise GoJudgeError(f"unexpected /run response: {payload!r}")
    res = payload[0]
    if not isinstance(res, dict):
        raise GoJudgeError(f"unexpected /run result item: {res!r}")
    return _to_run_result(res, output_limit_bytes), (res.get("fileIds") or {})


def run(
    argv: list[str],
    stdin_data: bytes,
    *,
    time_limit_ms: int,
    memory_limit_mb: int,
    proc_limit: int = 64,
    output_limit_mb: int = 1,
    copy_in: dict[str, bytes] | None = None,
) -> RunResult:
    result, _ = _execute(
        argv,
        stdin_data,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        proc_limit=proc_limit,
        output_limit_mb=output_limit_mb,
        copy_in=copy_in,
    )
    return result


COMPILE_ARGV = ["gcc", "-std=c11", "-O2", "-o", "main", "main.c", "-lm"]


def compile_c(
    source: bytes,
    *,
    time_limit_ms: int,
    memory_limit_mb: int,
    proc_limit: int = 64,
) -> tuple[RunResult, str | None]:
    result, file_ids = _execute(
        COMPILE_ARGV,
        b"",
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        proc_limit=proc_limit,
        output_limit_mb=1,
        copy_in={"main.c": source},
        copy_out_cached=["main"],
    )
    return result, file_ids.get("main")


def run_program(
    binary_file_id: str,
    stdin_data: bytes,
    *,
    time_limit_ms: int,
    memory_limit_mb: int,
    proc_limit: int = 64,
    output_limit_mb: int = 1,
) -> RunResult:
    result, _ = _execute(
        ["./main"],
        stdin_data,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        proc_limit=proc_limit,
        output_limit_mb=output_limit_mb,
        copy_in_file_ids={"main": binary_file_id},
    )
    return result
