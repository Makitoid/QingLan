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


def _problems_by_id(db: Session, assignment_problems: list[AssignmentProblem]) -> dict[int, Problem]:
    """题单涉及的题目一次取回（供每题列取标题；题目被删则缺项，调用侧按空标题兜底）。"""
    problem_ids = {ap.problem_id for ap in assignment_problems}
    if not problem_ids:
        return {}
    return {p.id: p for p in db.execute(
        select(Problem).where(Problem.id.in_(problem_ids))
    ).scalars()}


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
    """逐学生成绩行（SC-01）。

    - best_effective_score：语义是「各题有效分里的最高单题分」，不是本场总分；
      名字沿用历史契约以保持算法/口径不变，多题场次的合计请看 total_score。
    - total_score = Σ(problem_scores 中非 None 的有效分)，即题单内各题有效分之和，
      与 SC-02 导出的「总分」列同源。
    题目与提交各取一次（submissions 一次全取、problems 一次 in 查询），不在学生循环里查库。
    """
    students = bound_students(db, assignment.created_by)
    all_subs = db.execute(
        select(Submission).where(Submission.assignment_id == assignment.id)
    ).scalars().all()

    ordered_problems = assignment_problems_ordered(db, assignment.id)
    problems = _problems_by_id(db, ordered_problems)
    subs_by_student = _group_by_student(all_subs)

    rows = []
    for student in students:
        mine = subs_by_student.get(student.id, [])
        by_problem: dict[int, list[Submission]] = {}
        for s in mine:
            by_problem.setdefault(s.problem_id, []).append(s)
        # 每题有效分：题单内的题按 seq 逐列输出，题单外（题目已移出题单）的提交
        # 仍参与 best 的计算，但不计入 total_score —— 总分要和导出列对得上。
        effective_by_problem = {
            problem_id: scoring.aggregate_scores(s_list, assignment.score_policy)
            for problem_id, s_list in by_problem.items()
        }
        values = [v for v in effective_by_problem.values() if v is not None]
        best = round(max(values), 1) if values else 0.0

        problem_scores = []
        total = 0.0
        for ap in ordered_problems:
            problem = problems.get(ap.problem_id)
            value = effective_by_problem.get(ap.problem_id)
            if value is not None:
                total += value
            problem_scores.append({
                "problem_id": ap.problem_id,
                "seq": ap.seq,
                "title": problem.title if problem else "",
                "full_score": ap.full_score,
                "effective_score": value,
            })

        # submitted_at 为 UTC 文本 YYYY-MM-DD HH:MM:SS，字典序即时间序；同刻以 id 大者为准
        last = max(mine, key=lambda s: (s.submitted_at or "", s.id), default=None)
        rows.append({
            "student_id": student.id,
            "username": student.username,
            "name": student.display_name,
            "submitted_count": len(mine),
            "best_effective_score": best,
            "total_score": round(total, 1),
            "problem_scores": problem_scores,
            "last_submitted_at": last.submitted_at if last else None,
            "last_submission_id": last.id if last else None,
        })
    return rows
