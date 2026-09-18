import pytest

from app.judge.compare import compare


class TestExact:
    def test_identical_bytes(self):
        assert compare("3\n", b"3\n", "exact", None) is True

    def test_str_expected_encoded(self):
        assert compare("3\n", "3\n".encode("utf-8"), "exact", None) is True

    def test_trailing_newline_matters(self):
        assert compare("3\n", b"3", "exact", None) is False

    def test_trailing_space_matters(self):
        assert compare("3\n", b"3 \n", "exact", None) is False

    def test_crlf_differs(self):
        assert compare("3\n", b"3\r\n", "exact", None) is False

    def test_multibyte_utf8(self):
        assert compare("你好\n", "你好\n".encode("utf-8"), "exact", None) is True


class TestTrim:
    def test_trailing_space_ignored(self):
        assert compare("3\n", b"3 \n", "trim", None) is True

    def test_trailing_tab_ignored(self):
        assert compare("3\n", b"3\t\n", "trim", None) is True

    def test_trailing_blank_lines_ignored(self):
        assert compare("3\n", b"3\n\n\n", "trim", None) is True

    def test_missing_final_newline_ignored(self):
        assert compare("3\n", b"3", "trim", None) is True

    def test_crlf_actual_equals_lf_expected(self):
        assert compare("3\n4\n", b"3\r\n4\r\n", "trim", None) is True

    def test_lone_cr_normalized(self):
        assert compare("3\n4\n", b"3\r4\r", "trim", None) is True

    def test_crlf_expected_side(self):
        assert compare("3\r\n", b"3\n", "trim", None) is True

    def test_inner_blank_line_kept(self):
        assert compare("3\n\n4\n", b"3\n4\n", "trim", None) is False

    def test_leading_space_kept(self):
        assert compare("3\n", b" 3\n", "trim", None) is False

    def test_wrong_value(self):
        assert compare("7\n", b"0\n", "trim", None) is False

    def test_multiline_with_spaces(self):
        assert compare("3 \n7\n", b"3\n7 \n", "trim", None) is True


class TestFloat:
    def test_within_eps(self):
        assert compare("3.14\n", b"3.140001\n", "float", 1e-3) is True

    def test_outside_eps(self):
        assert compare("3.14\n", b"3.2\n", "float", 1e-3) is False

    def test_boundary_equal_to_eps(self):
        assert compare("1.0\n", b"1.5\n", "float", 0.5) is True

    def test_token_count_mismatch(self):
        assert compare("1.0 2.0\n", b"1.0\n", "float", 1e-6) is False

    def test_token_count_mismatch_extra(self):
        assert compare("1.0\n", b"1.0 2.0\n", "float", 1e-6) is False

    def test_non_numeric_tokens_equal(self):
        assert compare("ans 1.0\n", b"ans 1.0\n", "float", 1e-6) is True

    def test_non_numeric_tokens_differ(self):
        assert compare("yes 1.0\n", b"no 1.0\n", "float", 1e-6) is False

    def test_mixed_tokens(self):
        assert compare("ans 3.14\n", b"ans  3.1400001\n", "float", 1e-6) is True

    def test_integer_tokens_as_float(self):
        assert compare("3\n", b"3.0000001\n", "float", 1e-6) is True

    def test_default_eps_when_none(self):
        assert compare("1.0\n", b"1.0000001\n", "float", None) is True
        assert compare("1.0\n", b"1.001\n", "float", None) is False

    def test_scientific_notation(self):
        assert compare("1e3\n", b"1000.0\n", "float", 1e-6) is True

    def test_whitespace_split_any(self):
        assert compare("1.0\t2.0\n", b"1.0\n2.0\n", "float", 1e-9) is True


class TestFixtureSemantics:
    def test_trailing_space_fixture_trim_ac(self):
        assert compare("3\n", b"3 \n", "trim", None) is True

    def test_trailing_space_fixture_exact_wa(self):
        assert compare("3\n", b"3 \n", "exact", None) is False

    def test_float_fmt_fixture_float_ac(self):
        assert compare("3.14\n", b"3.142857\n", "float", 0.01) is True

    def test_float_fmt_fixture_trim_wa(self):
        assert compare("3.14\n", b"3.142857\n", "trim", None) is False

    def test_float_fmt_fixture_tight_eps_wa(self):
        assert compare("3.14\n", b"3.142857\n", "float", 1e-9) is False


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        compare("3\n", b"3\n", "fuzzy", None)
