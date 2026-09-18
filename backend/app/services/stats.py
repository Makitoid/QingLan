from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, AssignmentProblem, Problem, Submission, TeacherStudent, User
from . import scoring

HISTOGRAM_RANGES = [
    "0-9", "10-19", "20-29", "30-39", "40-49",
    "50-59", "60-69", "70-79", "80-89", "90-100",
]


def bound_students(db: Session, teacher_id: int) -> list[User]:
    rows = db.execute(
        select(User)
        .join(TeacherStudent, TeacherStudent.student_id == User.id)
        .where(TeacherStudent.teacher_id == teacher_id)
        .order_by(User.id)
    ).scalars().all()
    return list(rows)


def assignment_problems_ordered(db: Session, assignment_id: int) -> list[AssignmentProblem]:
    rows = db.execute(
        select(AssignmentProblem).where(AssignmentProblem.assignment_id == assignment_id)
    ).scalars().all()
    return sorted(rows, key=lambda ap: (ap.seq, ap.problem_id))


def _histogram(values: list[float]) -> list[dict]:
    counts = [0] * 10
    for v in values:
        idx = int(v // 10)
        if idx > 9:
            idx = 9
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return [{"range": r, "count": c} for r, c in zip(HISTOGRAM_RANGES, counts)]


def _group_by_student(submissions: list[Submission]) -> dict[int, list[Submission]]:
    grouped: dict[int, list[Submission]] = {}
    for s in submissions:
        grouped.setdefault(s.user_id, []).append(s)
    return grouped


def overview(db: Session, assignment: Assignment) -> dict:
    students = bound_students(db, assignment.created_by)
    student_ids = {s.id for s in students}

    all_subs = db.execute(
        select(Submission).where(Submission.assignment_id == assignment.id)
    ).scalars().all()
    subs = [s for s in all_subs if s.user_id in student_ids]

    submitted_students = len({s.user_id for s in subs})

    per_problem = []
    histogram_values: list[float] = []
    for ap in assignment_problems_ordered(db, assignment.id):
        problem = db.get(Problem, ap.problem_id)
        p_subs = [s for s in subs if s.problem_id == ap.problem_id]
        judged = [s for s in p_subs if s.status == "done"]
        ac_count = sum(1 for s in judged if s.verdict == "AC")
        pass_rate = round(ac_count / len(judged), 4) if judged else 0.0

        effective_scores = []
        for _uid, s_list in _group_by_student(p_subs).items():
            value = scoring.aggregate_scores(s_list, assignment.score_policy)
            if value is not None:
                effective_scores.append(value)
        avg_effective = round(sum(effective_scores) / len(effective_scores), 1) if effective_scores else 0.0
        histogram_values.extend(effective_scores)

        per_problem.append({
            "problem_id": ap.problem_id,
            "title": problem.title if problem else "",
            "submit_count": len(p_subs),
            "pass_rate": pass_rate,
            "avg_effective_score": avg_effective,
        })

    return {
        "total_students": len(students),
        "submitted_students": submitted_students,
        "per_problem": per_problem,
        "histogram": _histogram(histogram_values),
    }


def student_rows(db: Session, assignment: Assignment) -> list[dict]:
    students = bound_students(db, assignment.created_by)
    all_subs = db.execute(
        select(Submission).where(Submission.assignment_id == assignment.id)
    ).scalars().all()

    rows = []
    for student in students:
        mine = [s for s in all_subs if s.user_id == student.id]
        best = 0.0
        if mine:
            by_problem: dict[int, list[Submission]] = {}
            for s in mine:
                by_problem.setdefault(s.problem_id, []).append(s)
            values = []
            for s_list in by_problem.values():
                value = scoring.aggregate_scores(s_list, assignment.score_policy)
                if value is not None:
                    values.append(value)
            if values:
                best = round(max(values), 1)
        last_submitted_at = max((s.submitted_at for s in mine), default=None)
        rows.append({
            "student_id": student.id,
            "name": student.display_name,
            "submitted_count": len(mine),
            "best_effective_score": best,
            "last_submitted_at": last_submitted_at,
        })
    return rows
