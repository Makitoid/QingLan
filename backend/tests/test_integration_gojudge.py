import pytest

from app.judge import gojudge

if not gojudge.health_check(timeout=2.0):
    pytest.skip(
        "go-judge 沙箱不可用（GET {GO_JUDGE_URL}/version 未返回 200）。"
        "真实沙箱集成测试需要 Docker 运行 criyle/go-judge:v1.12.3"
        "（Linux 内核，Windows 开发机需 Docker Desktop）。本机未运行该服务，跳过。",
        allow_module_level=True,
    )

from .conftest import read_fixture

LIMITS = dict(time_limit_ms=1000, memory_limit_mb=256, proc_limit=64, output_limit_mb=1)


def compile_fixture(name: str):
    result, file_id = gojudge.compile_c(
        read_fixture(name).encode("utf-8"),
        time_limit_ms=10_000,
        memory_limit_mb=512,
    )
    assert result.status == "ok", f"compile {name} failed: {result.stderr!r}"
    assert file_id is not None
    return file_id


def test_health_check():
    assert gojudge.health_check() is True


def test_ac_end_to_end():
    fid = compile_fixture("ac.c")
    res = gojudge.run_program(fid, b"1 2\n", **LIMITS)
    assert res.status == "ok"
    assert res.exit_code == 0
    assert res.stdout == b"3\n"


def test_wa_output():
    fid = compile_fixture("wa.c")
    ok = gojudge.run_program(fid, b"1 2\n", **LIMITS)
    bad = gojudge.run_program(fid, b"3 4\n", **LIMITS)
    assert ok.stdout == b"3\n"
    assert bad.stdout == b"0\n"


def test_tle():
    fid = compile_fixture("tle.c")
    res = gojudge.run_program(fid, b"", **{**LIMITS, "time_limit_ms": 500})
    assert res.status == "time_limit"


def test_mle():
    fid = compile_fixture("mle.c")
    res = gojudge.run_program(fid, b"", **{**LIMITS, "memory_limit_mb": 64})
    assert res.status == "memory_limit"


def test_re():
    fid = compile_fixture("re.c")
    res = gojudge.run_program(fid, b"", **LIMITS)
    assert res.status == "runtime_error"


def test_ce():
    result, file_id = gojudge.compile_c(
        read_fixture("ce.c").encode("utf-8"),
        time_limit_ms=10_000,
        memory_limit_mb=512,
    )
    assert result.status != "ok"
    assert result.exit_code not in (0, None)
    assert result.stderr
    assert file_id is None


def test_fork_bomb_survives():
    fid = compile_fixture("fork_bomb.c")
    res = gojudge.run_program(fid, b"", **LIMITS)
    assert res.status in ("runtime_error", "time_limit", "output_limit")
    assert gojudge.health_check() is True


def test_bigout_truncated():
    fid = compile_fixture("bigout.c")
    res = gojudge.run_program(fid, b"", **{**LIMITS, "time_limit_ms": 5000})
    assert res.status == "output_limit"
    assert len(res.stdout) <= 1024 * 1024


def test_trailing_space_and_float_fixtures():
    fid = compile_fixture("trailing_space.c")
    res = gojudge.run_program(fid, b"1 2\n", **LIMITS)
    assert res.stdout == b"3 \n"

    fid = compile_fixture("float_fmt.c")
    res = gojudge.run_program(fid, b"22 7\n", **LIMITS)
    assert res.stdout == b"3.142857\n"
