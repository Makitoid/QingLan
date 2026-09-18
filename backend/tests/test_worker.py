import re

import pytest

from app.judge import gojudge, worker
from app.models import Submission, SubmissionResult, TestCase

from .conftest import make_submission, read_fixture

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def rr(status="ok", exit_code=0, signal=None, stdout=b"", stderr=b"", time_ms=10, memory_kb=1024):
    return gojudge.RunResult(
        time_ms=time_ms,
        memory_kb=memory_kb,
        exit_code=exit_code,
        signal=signal,
        stdout=stdout,
        stderr=stderr,
        status=status,
    )


@pytest.fixture()
def sandbox(monkeypatch):
    calls = {"compile": [], "run": []}

    def fake_compile(source, **kwargs):
        calls["compile"].append((source, kwargs))
        return calls.get("compile_result", (rr(), "fid-main"))

    def fake_run(file_id, stdin_data, **kwargs):
        calls["run"].append((file_id, stdin_data, kwargs))
        results = calls.get("run_results")
        if results:
            return results[len(calls["run"]) - 1]
        return rr()

    monkeypatch.setattr(gojudge, "compile_c", fake_compile)
    monkeypatch.setattr(gojudge, "run_program", fake_run)
    return calls


def judge(db, code_text, assignment, problem, student):
    sub = make_submission(db, assignment, problem, student, code_text)
    worker.process_submission(db, sub.id)
    db.refresh(sub)
    return sub


def results_of(db, sub):
    return (
        db.query(SubmissionResult)
        .filter(SubmissionResult.submission_id == sub.id)
        .order_by(SubmissionResult.id)
        .all()
    )


class TestAccepted:
    def test_all_ac_full_score(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"7\n")]
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.status == "done"
        assert sub.verdict == "AC"
        assert sub.score == 100.0
        assert TS_RE.match(sub.judged_at)
        rows = results_of(db, sub)
        assert [r.verdict for r in rows] == ["AC", "AC"]
        assert rows[0].score == 25.0
        assert rows[1].score == 75.0
        assert rows[0].time_ms == 10
        assert rows[0].memory_kb == 1024

    def test_compile_limits_and_crlf_stripped(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"7\n")]
        code = read_fixture("ac.c").replace("\n", "\r\n")
        judge(db, code, assignment, problem, student)
        source, kwargs = sandbox["compile"][0]
        assert b"\r\n" not in source
        assert kwargs["time_limit_ms"] == 10_000
        assert kwargs["memory_limit_mb"] == 512

    def test_case_limits_from_problem(self, db, sandbox, assignment, problem, student, cases):
        problem.time_limit_ms = 500
        problem.memory_limit_mb = 128
        db.commit()
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"7\n")]
        judge(db, read_fixture("ac.c"), assignment, problem, student)
        for _, stdin_data, kwargs in sandbox["run"]:
            assert kwargs["time_limit_ms"] == 500
            assert kwargs["memory_limit_mb"] == 128
            assert kwargs["output_limit_mb"] == 1
        assert sandbox["run"][0][0] == "fid-main"
        assert sandbox["run"][0][1] == b"1 2\n"

    def test_judge_log_empty_on_clean_ac(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"7\n")]
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.judge_log is None


class TestWrongAnswer:
    def test_wa_partial_weight(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"0\n")]
        sub = judge(db, read_fixture("wa.c"), assignment, problem, student)
        assert sub.status == "done"
        assert sub.verdict == "WA"
        assert sub.score == 25.0
        assert [r.verdict for r in results_of(db, sub)] == ["AC", "WA"]

    def test_all_wa_zero(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"0\n"), rr(stdout=b"0\n")]
        sub = judge(db, read_fixture("wa.c"), assignment, problem, student)
        assert sub.verdict == "WA"
        assert sub.score == 0.0

    def test_rounding_one_decimal(self, db, sandbox, assignment, problem, student, cases):
        for c in cases:
            db.delete(c)
        db.commit()
        for i, w in enumerate([1, 1, 1]):
            db.add(TestCase(problem_id=problem.id, seq=10 + i, input="1 2\n", expected="3\n", weight=w))
        db.commit()
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(stdout=b"3\n"), rr(stdout=b"0\n")]
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.score == 66.7


class TestRuntimeVerdicts:
    def test_tle(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(status="time_limit", exit_code=None, signal=9, time_ms=1000), rr(stdout=b"7\n")]
        sub = judge(db, read_fixture("tle.c"), assignment, problem, student)
        assert sub.verdict == "TLE"
        assert sub.score == 75.0

    def test_mle(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(stdout=b"3\n"), rr(status="memory_limit", exit_code=None)]
        sub = judge(db, read_fixture("mle.c"), assignment, problem, student)
        assert sub.verdict == "MLE"
        assert sub.score == 25.0

    def test_re(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(status="runtime_error", exit_code=None, signal=8), rr(stdout=b"7\n")]
        sub = judge(db, read_fixture("re.c"), assignment, problem, student)
        assert sub.verdict == "RE"
        assert sub.score == 75.0

    def test_output_limit_is_wa_with_log(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(status="output_limit", stdout=b"a" * 100), rr(stdout=b"7\n")]
        sub = judge(db, read_fixture("bigout.c"), assignment, problem, student)
        assert sub.verdict == "WA"
        assert "output limit" in sub.judge_log
        assert sub.score == 75.0

    def test_verdict_is_first_non_ac_by_seq(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(status="runtime_error", signal=8), rr(status="time_limit")]
        sub = judge(db, "x", assignment, problem, student)
        assert sub.verdict == "RE"

    def test_verdict_first_non_ac_reversed(self, db, sandbox, assignment, problem, student, cases):
        sandbox["run_results"] = [rr(status="time_limit"), rr(status="runtime_error", signal=8)]
        sub = judge(db, "x", assignment, problem, student)
        assert sub.verdict == "TLE"


class TestCompileError:
    def test_ce_path(self, db, sandbox, assignment, problem, student, cases):
        sandbox["compile_result"] = (
            rr(status="runtime_error", exit_code=1, stderr=b"main.c:2:5: error: expected ';'"),
            None,
        )
        sub = judge(db, read_fixture("ce.c"), assignment, problem, student)
        assert sub.status == "done"
        assert sub.verdict == "CE"
        assert sub.score == 0.0
        assert "expected" in sub.judge_log
        assert TS_RE.match(sub.judged_at)
        assert results_of(db, sub) == []
        assert sandbox["run"] == []

    def test_ce_stderr_truncated_to_4096(self, db, sandbox, assignment, problem, student, cases):
        sandbox["compile_result"] = (
            rr(status="runtime_error", exit_code=1, stderr=b"e" * 10000),
            None,
        )
        sub = judge(db, read_fixture("ce.c"), assignment, problem, student)
        assert len(sub.judge_log) == 4096

    def test_compile_ok_without_file_id_fails(self, db, sandbox, assignment, problem, student, cases):
        sandbox["compile_result"] = (rr(), None)
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.status == "failed"
        assert "fileId" in sub.judge_log


class TestFailedPath:
    def test_exception_marks_failed(self, db, sandbox, assignment, problem, student, cases, monkeypatch):
        def boom(source, **kwargs):
            raise RuntimeError("go-judge down")

        monkeypatch.setattr(gojudge, "compile_c", boom)
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.status == "failed"
        assert "go-judge down" in sub.judge_log
        assert sub.verdict is None
        assert sub.score is None

    def test_run_exception_marks_failed_and_no_partial_results(
        self, db, sandbox, assignment, problem, student, cases, monkeypatch
    ):
        calls = {"n": 0}

        def flaky(file_id, stdin_data, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("connection reset")
            return rr(stdout=b"3\n")

        monkeypatch.setattr(gojudge, "run_program", flaky)
        sub = judge(db, read_fixture("ac.c"), assignment, problem, student)
        assert sub.status == "failed"
        assert "connection reset" in sub.judge_log
        assert results_of(db, sub) == []


class TestClaimTask:
    def test_claim_atomic_and_sets_judging(self, db, assignment, problem, student):
        sub = make_submission(db, assignment, problem, student, "code")
        sid = worker.claim_task(db)
        assert sid == sub.id
        db.refresh(sub)
        assert sub.status == "judging"
        assert sub.worker_id == worker.WORKER_ID

    def test_claim_returns_none_when_empty(self, db):
        assert worker.claim_task(db) is None

    def test_claim_picks_lowest_pending_first(self, db, assignment, problem, student):
        s1 = make_submission(db, assignment, problem, student, "a")
        s2 = make_submission(db, assignment, problem, student, "b")
        assert worker.claim_task(db) == s1.id
        assert worker.claim_task(db) == s2.id
        assert worker.claim_task(db) is None
        db.refresh(s1)
        db.refresh(s2)
        assert s1.status == "judging"
        assert s2.status == "judging"

    def test_claim_skips_non_pending(self, db, assignment, problem, student):
        sub = make_submission(db, assignment, problem, student, "a")
        sub.status = "done"
        db.commit()
        assert worker.claim_task(db) is None


class TestWorkerStartup:
    def test_refuses_to_start_without_sandbox(self, monkeypatch):
        monkeypatch.setattr(gojudge, "health_check", lambda *a, **k: False)
        with pytest.raises(SystemExit):
            worker.main()
