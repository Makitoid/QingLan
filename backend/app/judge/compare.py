from __future__ import annotations


def _to_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _trim_lines(value: str | bytes) -> list[str]:
    text = _to_text(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _tokens(value: str | bytes) -> list[str]:
    return _to_text(value).replace("\r\n", "\n").replace("\r", "\n").split()


def compare(expected: str | bytes, actual: bytes, mode: str, float_eps: float | None) -> bool:
    if mode == "exact":
        exp = expected.encode("utf-8") if isinstance(expected, str) else expected
        act = actual if isinstance(actual, bytes) else actual.encode("utf-8")
        return exp == act
    if mode == "trim":
        return _trim_lines(expected) == _trim_lines(actual)
    if mode == "float":
        eps = float_eps if float_eps is not None else 1e-6
        exp_tokens = _tokens(expected)
        act_tokens = _tokens(actual)
        if len(exp_tokens) != len(act_tokens):
            return False
        for e, a in zip(exp_tokens, act_tokens):
            if e == a:
                continue
            try:
                ef = float(e)
                af = float(a)
            except ValueError:
                return False
            if ef == af:
                continue
            if abs(ef - af) > eps:
                return False
        return True
    raise ValueError(f"unknown compare mode: {mode}")
