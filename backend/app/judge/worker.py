from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core import config
from ..core.db import SessionLocal
from ..models import (AssignmentProblem, Problem, Submission,
                      SubmissionResult, TestCase)
from . import gojudge
from .compare import compare

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

_CLAIM_SQL = text(
    "UPDATE submissions"
    "   SET status='judging', worker_id=:wid"
    " WHERE id = (SELECT id FROM submissions WHERE status='pending' ORDER BY id LIMIT 1)"
    " RETURNING *"
)

_JUDGE_LOG_LIMIT = 4096


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def claim_task(db: Session) -> int | None:
    row = db.execute(_CLAIM_SQL, {"wid": WORKER_ID}).mappings().first()
    db.commit()
    if row is None:
        return None
    return int(row["id"])


def case_score(full_score: float, weight: int, total_weight: int, verdict: str) -> float:
    if verdict != "AC" or total_weight <= 0:
        return 0.0
    return full_score * weight / total_weight


def total_score(case_scores: list[float]) -> float:
    return round(sum(case_scores), 1)


def submission_verdict(verdicts_by_seq: list[str]) -> str:
    for v in verdicts_by_seq:
        if v != "AC":
            return v
    return "AC"


def effective_score(sub: Submission) -> float | None:
    return sub.manual_score if sub.manual_score is not None else sub.score


def pick_policy_score(ordered_scores: list[float | None], policy: str) -> float | None:
    if policy == "last":
        for s in reversed(ordered_scores):
            if s is not None:
                return s
        return None
    best: float | None = None
    for s in ordered_scores:
        if s is not None and (best is None or s > best):
            best = s
    return best


def case_verdict(
    result: gojudge.RunResult,
    expected: str,
    compare_mode: str,
    float_eps: float | None,
) -> tuple[str, str | None]:
    if result.status == "time_limit":
        return "TLE", None
    if result.status == "memory_limit":
        return "MLE", None
    if result.status == "runtime_error":
        return "RE", None
    if result.status == "output_limit":
        return "WA", "output limit exceeded, stdout truncated"
    if compare(expected, result.stdout, compare_mode, float_eps):
        return "AC", None
    return "WA", None


def _mark_compile_error(db: Session, sub: Submission, stderr: bytes) -> None:
    sub.status = "done"
    sub.verdict = "CE"
    sub.score = 0.0
    sub.judge_log = stderr.decode("utf-8", errors="replace")[: config.CE_STDERR_LIMIT]
    sub.judged_at = now_utc()
    db.commit()


def _judge(db: Session, sub: Submission) -> None:
    problem = db.get(Problem, sub.problem_id)
    if problem is None:
        raise ValueError(f"problem {sub.problem_id} not found")
    ap = db.get(AssignmentProblem, (sub.assignment_id, sub.problem_id))
    full_score = float(ap.full_score) if ap is not None else 100.0
    cases = (
        db.query(TestCase)
        .filter(TestCase.problem_id == problem.id)
        .order_by(TestCase.seq)
        .all()
    )

    source = sub.code_text.replace("\r\n", "\n").encode("utf-8")
    compile_result, binary_file_id = gojudge.compile_c(
        source,
        time_limit_ms=config.COMPILE_TIME_LIMIT_MS,
        memory_limit_mb=config.COMPILE_MEMORY_LIMIT_MB,
        proc_limit=config.PROC_LIMIT,
    )
    if compile_result.status != "ok" or compile_result.exit_code not in (0, None):
        _mark_compile_error(db, sub, compile_result.stderr)
        return
    if binary_file_id is None:
        raise gojudge.GoJudgeError("compile succeeded but no binary fileId returned")

    total_weight = sum(c.weight for c in cases)
    scores: list[float] = []
    verdicts: list[str] = []
    logs: list[str] = []
    for case in cases:
        result = gojudge.run_program(
            binary_file_id,
            case.input.encode("utf-8"),
            time_limit_ms=problem.time_limit_ms,
            memory_limit_mb=problem.memory_limit_mb,
            proc_limit=config.PROC_LIMIT,
            output_limit_mb=config.OUTPUT_LIMIT_MB,
        )
        verdict, log = case_verdict(result, case.expected, problem.compare_mode, problem.float_eps)
        score = case_score(full_score, case.weight, total_weight, verdict)
        scores.append(score)
        verdicts.append(verdict)
        if log:
            logs.append(f"case seq={case.seq}: {log}")
        db.add(
            SubmissionResult(
                submission_id=sub.id,
                test_case_id=case.id,
                verdict=verdict,
                time_ms=result.time_ms,
                memory_kb=result.memory_kb,
                score=score,
            )
        )

    sub.status = "done"
    sub.verdict = submission_verdict(verdicts)
    sub.score = total_score(scores)
    sub.judge_log = "; ".join(logs)[:_JUDGE_LOG_LIMIT] if logs else None
    sub.judged_at = now_utc()
    db.commit()


def process_submission(db: Session, submission_id: int) -> None:
    sub = db.get(Submission, submission_id)
    if sub is None:
        return
    try:
        _judge(db, sub)
    except Exception as exc:
        db.rollback()
        sub = db.get(Submission, submission_id)
        if sub is not None:
            sub.status = "failed"
            sub.judge_log = f"worker error: {exc!r}"[:_JUDGE_LOG_LIMIT]
            sub.judged_at = now_utc()
            db.commit()


def main() -> None:
    if not gojudge.health_check():
        raise SystemExit(
            f"go-judge health check failed at {config.GO_JUDGE_URL}/version; worker refuses to start"
        )
    while True:
        db = SessionLocal()
        try:
            submission_id = claim_task(db)
            if submission_id is None:
                time.sleep(config.WORKER_POLL_INTERVAL_S)
                continue
            process_submission(db, submission_id)
        finally:
            db.close()


if __name__ == "__main__":
    main()
