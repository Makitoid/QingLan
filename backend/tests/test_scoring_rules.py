from app.judge import worker
from app.models import Submission


class TestCaseScore:
    def test_ac_proportional_to_weight(self):
        assert worker.case_score(100.0, 1, 4, "AC") == 25.0
        assert worker.case_score(100.0, 3, 4, "AC") == 75.0

    def test_non_ac_zero(self):
        for v in ("WA", "TLE", "MLE", "RE"):
            assert worker.case_score(100.0, 3, 4, v) == 0.0

    def test_zero_total_weight(self):
        assert worker.case_score(100.0, 1, 0, "AC") == 0.0

    def test_non_integer_weights(self):
        assert worker.case_score(10.0, 2, 3, "AC") == 10.0 * 2 / 3


class TestTotalScore:
    def test_round_one_decimal(self):
        assert worker.total_score([100 / 3, 100 / 3]) == 66.7

    def test_float_accumulation_precision(self):
        assert worker.total_score([0.1, 0.1, 0.1]) == 0.3

    def test_empty(self):
        assert worker.total_score([]) == 0.0

    def test_full(self):
        assert worker.total_score([25.0, 75.0]) == 100.0


class TestSubmissionVerdict:
    def test_all_ac(self):
        assert worker.submission_verdict(["AC", "AC", "AC"]) == "AC"

    def test_first_non_ac_in_seq_order(self):
        assert worker.submission_verdict(["AC", "TLE", "WA"]) == "TLE"
        assert worker.submission_verdict(["WA", "AC", "TLE"]) == "WA"
        assert worker.submission_verdict(["AC", "AC", "RE"]) == "RE"
        assert worker.submission_verdict(["MLE", "AC"]) == "MLE"

    def test_empty_is_ac(self):
        assert worker.submission_verdict([]) == "AC"


class TestEffectiveScore:
    def _sub(self, score, manual):
        s = Submission(code_text="x")
        s.score = score
        s.manual_score = manual
        return s

    def test_manual_overrides(self):
        assert worker.effective_score(self._sub(50.0, 90.0)) == 90.0

    def test_manual_none_falls_back(self):
        assert worker.effective_score(self._sub(50.0, None)) == 50.0

    def test_manual_zero_counts(self):
        assert worker.effective_score(self._sub(50.0, 0.0)) == 0.0


class TestScorePolicy:
    def test_best_takes_max(self):
        assert worker.pick_policy_score([50.0, 90.0, 70.0], "best") == 90.0

    def test_last_takes_chronological_last(self):
        assert worker.pick_policy_score([90.0, 50.0, 70.0], "last") == 70.0

    def test_last_skips_trailing_none(self):
        assert worker.pick_policy_score([90.0, 50.0, None], "last") == 50.0

    def test_best_ignores_none(self):
        assert worker.pick_policy_score([None, 30.0, None], "best") == 30.0

    def test_all_none(self):
        assert worker.pick_policy_score([None, None], "best") is None
        assert worker.pick_policy_score([None, None], "last") is None

    def test_empty(self):
        assert worker.pick_policy_score([], "best") is None
        assert worker.pick_policy_score([], "last") is None

    def test_best_single(self):
        assert worker.pick_policy_score([42.5], "best") == 42.5
