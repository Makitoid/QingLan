import httpx
import pytest

from app.judge import gojudge


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=None, response=None
            )


def goj_result(
    status="Accepted",
    exit_status=0,
    time_ns=1_500_000_000,
    memory=20_971_520,
    stdout="",
    stderr="",
    file_ids=None,
    error="",
):
    r = {
        "status": status,
        "exitStatus": exit_status,
        "time": time_ns,
        "memory": memory,
        "runTime": time_ns * 2,
        "files": {"stdout": stdout, "stderr": stderr},
    }
    if file_ids is not None:
        r["fileIds"] = file_ids
    if error:
        r["error"] = error
    return r


@pytest.fixture()
def captured(monkeypatch):
    state = {"payload": None, "url": None, "response": [goj_result()]}

    def fake_post(url, json=None, timeout=None):
        state["url"] = url
        state["payload"] = json
        state["timeout"] = timeout
        return FakeResponse(state["response"])

    monkeypatch.setattr(gojudge.httpx, "post", fake_post)
    return state


def run_once(captured, result=None, **kwargs):
    if result is not None:
        captured["response"] = [result]
    params = dict(time_limit_ms=1500, memory_limit_mb=128)
    params.update(kwargs)
    return gojudge.run(["./main"], b"1 2\n", **params)


class TestUnitConversion:
    def test_request_limits_in_ns_and_bytes(self, captured):
        run_once(captured)
        cmd = captured["payload"]["cmd"][0]
        assert cmd["cpuLimit"] == 1_500 * 1_000_000
        assert cmd["memoryLimit"] == 128 * 1024 * 1024
        assert cmd["clockLimit"] == 2 * cmd["cpuLimit"]
        assert cmd["procLimit"] == 64

    def test_response_time_ns_to_ms(self, captured):
        res = run_once(captured, goj_result(time_ns=1_234_567_890))
        assert res.time_ms == 1234

    def test_response_memory_bytes_to_kb(self, captured):
        res = run_once(captured, goj_result(memory=20_971_520))
        assert res.memory_kb == 20480

    def test_output_limit_bytes_in_request(self, captured):
        run_once(captured, output_limit_mb=2)
        files = captured["payload"]["cmd"][0]["files"]
        assert files[1] == {"name": "stdout", "max": 2 * 1024 * 1024}

    def test_url_and_timeout(self, captured):
        run_once(captured)
        assert captured["url"].endswith("/run")
        assert captured["timeout"] > 0


class TestRequestShape:
    def test_stdin_and_collectors(self, captured):
        run_once(captured)
        files = captured["payload"]["cmd"][0]["files"]
        assert files[0]["content"] == "1 2\n"
        assert files[1]["name"] == "stdout"
        assert files[2]["name"] == "stderr"

    def test_args_passed_through(self, captured):
        run_once(captured)
        assert captured["payload"]["cmd"][0]["args"] == ["./main"]

    def test_copy_in_content(self, captured):
        run_once(captured, copy_in={"main.c": b"int main(){}"})
        assert captured["payload"]["cmd"][0]["copyIn"]["main.c"]["content"] == "int main(){}"


class TestStatusNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Accepted", "ok"),
            ("Time Limit Exceeded", "time_limit"),
            ("Memory Limit Exceeded", "memory_limit"),
            ("Output Limit Exceeded", "output_limit"),
            ("Nonzero Exit Status", "runtime_error"),
            ("Signalled", "runtime_error"),
            ("Runtime Error", "runtime_error"),
            ("Dangerous Syscall", "runtime_error"),
            ("File Error", "runtime_error"),
            ("Internal Error", "runtime_error"),
            ("Something Unknown", "runtime_error"),
        ],
    )
    def test_status_map(self, captured, raw, expected):
        res = run_once(captured, goj_result(status=raw))
        assert res.status == expected

    def test_accepted_exit_code(self, captured):
        res = run_once(captured, goj_result(status="Accepted", exit_status=0))
        assert res.exit_code == 0
        assert res.signal is None

    def test_nonzero_exit_code(self, captured):
        res = run_once(captured, goj_result(status="Nonzero Exit Status", exit_status=1))
        assert res.exit_code == 1
        assert res.signal is None

    def test_signalled_sets_signal(self, captured):
        res = run_once(captured, goj_result(status="Signalled", exit_status=11))
        assert res.signal == 11
        assert res.exit_code is None

    def test_stdout_stderr_collected(self, captured):
        res = run_once(captured, goj_result(stdout="3\n", stderr="warn"))
        assert res.stdout == b"3\n"
        assert res.stderr == b"warn"

    def test_error_message_appended_to_stderr(self, captured):
        res = run_once(captured, goj_result(status="Internal Error", error="container failed"))
        assert b"container failed" in res.stderr


class TestOutputTruncation:
    def test_stdout_truncated_to_limit(self, captured):
        big = "a" * (3 * 1024 * 1024)
        res = run_once(captured, goj_result(stdout=big), output_limit_mb=1)
        assert len(res.stdout) == 1024 * 1024

    def test_stdout_within_limit_untouched(self, captured):
        res = run_once(captured, goj_result(stdout="hello"), output_limit_mb=1)
        assert res.stdout == b"hello"


class TestHttpErrors:
    def test_http_error_raises(self, captured, monkeypatch):
        def fake_post(url, json=None, timeout=None):
            return FakeResponse("bad request", status_code=400)

        monkeypatch.setattr(gojudge.httpx, "post", fake_post)
        with pytest.raises(httpx.HTTPStatusError):
            gojudge.run(["./main"], b"", time_limit_ms=100, memory_limit_mb=64)

    def test_malformed_payload_raises(self, captured):
        captured["response"] = {"not": "a list"}
        with pytest.raises(gojudge.GoJudgeError):
            gojudge.run(["./main"], b"", time_limit_ms=100, memory_limit_mb=64)

    def test_dict_wrapped_results_accepted(self, captured, monkeypatch):
        def fake_post(url, json=None, timeout=None):
            return FakeResponse({"results": [goj_result(stdout="ok\n")]})

        monkeypatch.setattr(gojudge.httpx, "post", fake_post)
        res = gojudge.run(["./main"], b"", time_limit_ms=100, memory_limit_mb=64)
        assert res.stdout == b"ok\n"
        assert res.status == "ok"

    def test_empty_results_raises(self, captured):
        captured["response"] = []
        with pytest.raises(gojudge.GoJudgeError):
            gojudge.run(["./main"], b"", time_limit_ms=100, memory_limit_mb=64)


class TestCompileAndRunProgram:
    def test_compile_c_payload(self, captured):
        captured["response"] = [goj_result(file_ids={"main": "fid-1"})]
        result, file_id = gojudge.compile_c(
            b"int main(){}", time_limit_ms=10_000, memory_limit_mb=512
        )
        cmd = captured["payload"]["cmd"][0]
        assert cmd["args"] == ["gcc", "-std=c11", "-O2", "-o", "main", "main.c", "-lm"]
        assert cmd["copyIn"]["main.c"]["content"] == "int main(){}"
        assert cmd["copyOutCached"] == ["main"]
        assert cmd["cpuLimit"] == 10_000 * 1_000_000
        assert cmd["memoryLimit"] == 512 * 1024 * 1024
        assert result.status == "ok"
        assert file_id == "fid-1"

    def test_compile_c_failure_has_stderr(self, captured):
        captured["response"] = [
            goj_result(status="Nonzero Exit Status", exit_status=1, stderr="error: expected ';'\n")
        ]
        result, file_id = gojudge.compile_c(b"bad", time_limit_ms=10_000, memory_limit_mb=512)
        assert result.status == "runtime_error"
        assert result.exit_code == 1
        assert b"expected" in result.stderr
        assert file_id is None

    def test_run_program_uses_file_id(self, captured):
        captured["response"] = [goj_result(stdout="3\n")]
        res = gojudge.run_program(
            "fid-1", b"1 2\n", time_limit_ms=1000, memory_limit_mb=256
        )
        cmd = captured["payload"]["cmd"][0]
        assert cmd["args"] == ["./main"]
        assert cmd["copyIn"]["main"] == {"fileId": "fid-1"}
        assert cmd["files"][0]["content"] == "1 2\n"
        assert res.stdout == b"3\n"


class TestHealthCheck:
    def test_health_ok(self, monkeypatch):
        monkeypatch.setattr(
            gojudge.httpx, "get", lambda url, timeout=None: FakeResponse({"version": "v1.12.3"})
        )
        assert gojudge.health_check() is True

    def test_health_bad_status(self, monkeypatch):
        monkeypatch.setattr(
            gojudge.httpx, "get", lambda url, timeout=None: FakeResponse({}, status_code=500)
        )
        assert gojudge.health_check() is False

    def test_health_connection_error(self, monkeypatch):
        def boom(url, timeout=None):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(gojudge.httpx, "get", boom)
        assert gojudge.health_check() is False
