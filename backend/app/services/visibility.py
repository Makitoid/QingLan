def can_see_detail(user, assignment) -> bool:
    if user.role in ("admin", "teacher"):
        return True
    return assignment.mode == "homework" or assignment.released == 1


def status_text(submission) -> str:
    if submission.status in ("pending", "judging"):
        return "判题中"
    return "已判题（待放出）"


def masked_submission(submission) -> dict:
    return {
        "id": submission.id,
        "submitted_at": submission.submitted_at,
        "status_text": status_text(submission),
    }


def student_result_rows(results_with_cases) -> list[dict]:
    return [
        {
            "seq": case.seq,
            "is_sample": case.is_sample,
            "verdict": result.verdict,
            "time_ms": result.time_ms,
            "score": result.score,
        }
        for result, case in results_with_cases
    ]


def teacher_result_rows(results_with_cases) -> list[dict]:
    return [
        {
            "seq": case.seq,
            "is_sample": case.is_sample,
            "verdict": result.verdict,
            "time_ms": result.time_ms,
            "memory_kb": result.memory_kb,
            "score": result.score,
        }
        for result, case in results_with_cases
    ]


def visible_submission_summary(submission) -> dict:
    return {
        "id": submission.id,
        "submitted_at": submission.submitted_at,
        "status": submission.status,
        "verdict": submission.verdict,
        "score": submission.score,
        "manual_score": submission.manual_score,
    }


def student_detail(submission, results_with_cases) -> dict:
    data = {
        "id": submission.id,
        "assignment_id": submission.assignment_id,
        "problem_id": submission.problem_id,
        "status": submission.status,
        "verdict": submission.verdict,
        "score": submission.score,
        "manual_score": submission.manual_score,
        "submitted_at": submission.submitted_at,
        "judged_at": submission.judged_at,
        "results": student_result_rows(results_with_cases),
    }
    if submission.verdict == "CE":
        data["judge_log"] = submission.judge_log
    return data


def teacher_detail(submission, results_with_cases) -> dict:
    return {
        "id": submission.id,
        "assignment_id": submission.assignment_id,
        "problem_id": submission.problem_id,
        "user_id": submission.user_id,
        "code_text": submission.code_text,
        "status": submission.status,
        "verdict": submission.verdict,
        "score": submission.score,
        "manual_score": submission.manual_score,
        "judge_log": submission.judge_log,
        "submitted_at": submission.submitted_at,
        "judged_at": submission.judged_at,
        "results": teacher_result_rows(results_with_cases),
    }
