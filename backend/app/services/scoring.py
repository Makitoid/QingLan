def case_score(full_score: float, weight: int, total_weight: int, is_ac: bool) -> float:
    if not is_ac:
        return 0.0
    return full_score * weight / total_weight


def compute_submission_score(scores) -> float:
    return round(sum(scores), 1)


def compute_verdict(verdicts_in_seq_order) -> str | None:
    if not verdicts_in_seq_order:
        return None
    for verdict in verdicts_in_seq_order:
        if verdict != "AC":
            return verdict
    return "AC"


def effective_score_for(submission):
    if submission.manual_score is not None:
        return submission.manual_score
    return submission.score


def aggregate_scores(submissions, policy: str):
    scored = [s for s in submissions if effective_score_for(s) is not None]
    if not scored:
        return None
    if policy == "last":
        scored.sort(key=lambda s: (s.submitted_at or "", s.id))
        return effective_score_for(scored[-1])
    return max(effective_score_for(s) for s in scored)
