from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Assignment, AssignmentProblem, GroupMember, Problem,
                      Submission, TeacherGroup, TeacherStudent, User)
from . import groups as groups_svc
from . import retries as retries_svc
from . import scoring

HISTOGRAM_RANGES = [
    "0-9", "10-19", "20-29", "30-39", "40-49",
    "50-59", "60-69", "70-79", "80-89", "90-100",
]


def bound_student_ids(db: Session, teacher_id: int) -> set[int]:
    """名单（层 3 校准后）的学生 ID 集合 = 可教组成员 ∪ 手动添加，只保留 role=student。

    这是 0.3.2 F1 的唯一名单口径：撤销组别 → 该组学生立即从这里消失；
    手动添加的学生不受层 2 变更影响。停用学生照常保留（与 0.3.1 一致）。
    """
    ids = groups_svc.teachable_student_ids(db, teacher_id)
    ids |= groups_svc.manual_student_ids(db, teacher_id)
    if not ids:
        return set()
    return {row[0] for row in db.execute(
        select(User.id).where(User.id.in_(sorted(ids)), User.role == "student")
    ).all()}


def bound_students(db: Session, teacher_id: int) -> list[User]:
    """名单学生（可教组并集 ∪ 手动添加），按 id 升序。

    统计、教师名单、admin 反查、admin 名单计数共用本函数，避免口径漂移。
    """
    ids = bound_student_ids(db, teacher_id)
    if not ids:
        return []
    return list(db.execute(
        select(User).where(User.id.in_(sorted(ids))).order_by(User.id)
    ).scalars().all())


def bound_teacher_map(db: Session, student_ids: list[int]) -> dict[int, list[User]]:
    """{student_id: [把该生列入名单的教师]}，与 bound_students 同一并集口径。

    admin 学生列表的「所属教师」反查用：组别被撤销后教师立即从该生身上消失。
    """
    wanted = sorted({int(sid) for sid in student_ids})
    if not wanted:
        return {}
    pairs: dict[int, set[int]] = {}
    for teacher_id, student_id in db.execute(
        select(TeacherGroup.teacher_id, GroupMember.student_id)
        .join(GroupMember, GroupMember.group_id == TeacherGroup.group_id)
        .join(User, User.id == GroupMember.student_id)
        .where(GroupMember.student_id.in_(wanted), User.role == "student")
    ).all():
        pairs.setdefault(teacher_id, set()).add(student_id)
    for teacher_id, student_id in db.execute(
        select(TeacherStudent.teacher_id, TeacherStudent.student_id)
        .where(TeacherStudent.student_id.in_(wanted))
    ).all():
        pairs.setdefault(teacher_id, set()).add(student_id)
    if not pairs:
        return {}
    teachers = {
        t.id: t for t in db.execute(
            select(User).where(User.id.in_(sorted(pairs)), User.role == "teacher")
        ).scalars()
    }
    result: dict[int, list[User]] = {}
    for teacher_id, student_ids_of_teacher in pairs.items():
        teacher = teachers.get(teacher_id)
        if teacher is None:
            continue
        for student_id in student_ids_of_teacher:
            result.setdefault(student_id, []).append(teacher)
    for rows in result.values():
        rows.sort(key=lambda u: u.id)
    return result


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


def _subs_by_student(db: Session, assignment: Assignment) -> dict[int, list[Submission]]:
    """本场次全部提交按学生分组（受众过滤由调用侧做），overview 与 student_rows 同取一次。"""
    all_subs = db.execute(
        select(Submission).where(Submission.assignment_id == assignment.id)
    ).scalars().all()
    return _group_by_student(all_subs)


def _effective_by_problem(submissions: list[Submission], score_policy: str) -> dict[int, float | None]:
    """某生每题有效分 {problem_id: aggregate_scores}：只含他有提交的题，None 表示尚无可计的分。"""
    by_problem: dict[int, list[Submission]] = {}
    for s in submissions:
        by_problem.setdefault(s.problem_id, []).append(s)
    return {
        problem_id: scoring.aggregate_scores(s_list, score_policy)
        for problem_id, s_list in by_problem.items()
    }


def _total_score(ordered_problems: list[AssignmentProblem],
                 effective_by_problem: dict[int, float | None]) -> float:
    """Σ(题单内每题有效分)，缺题（未提交或还没判分）按 0 计。

    student_rows 的 total_score 与 overview 的班级总分指标共用本函数 —— 两处口径必须一份真相。
    题单外（题目已移出题单）的提交不参与合计，与 SC-02 导出的「总分」列对得上。
    """
    total = 0.0
    for ap in ordered_problems:
        value = effective_by_problem.get(ap.problem_id)
        if value is not None:
            total += value
    return round(total, 1)


def overview(db: Session, assignment: Assignment) -> dict:
    # 0.3.2 F1：受众口径（'subgroup' 时按场次白名单收窄），不再是教师全部名单
    students = groups_svc.audience_students(db, assignment)
    student_ids = {s.id for s in students}

    grouped = _subs_by_student(db, assignment)
    subs = [s for uid, s_list in grouped.items() if uid in student_ids for s in s_list]

    submitted_students = len({s.user_id for s in subs})

    ordered_problems = assignment_problems_ordered(db, assignment.id)
    # 0.4.0 F4：逐生总分 = 每题有效分之和，口径与 student_rows.total_score 完全一致
    effective_by_student = {
        s.id: _effective_by_problem(grouped.get(s.id, []), assignment.score_policy)
        for s in students
    }
    totals = [_total_score(ordered_problems, effective_by_student[s.id]) for s in students]
    full_score_sum = float(sum(ap.full_score for ap in ordered_problems))
    pass_line = 0.6 * full_score_sum
    # 浮点尾差（0.6*115 = 69.00000000000001）不该把正好卡在及格线上的总分判成不及格
    passed = sum(1 for total in totals if total >= pass_line - 1e-9)

    per_problem = []
    histogram_values: list[float] = []
    for ap in ordered_problems:
        problem = db.get(Problem, ap.problem_id)
        p_subs = [s for s in subs if s.problem_id == ap.problem_id]
        judged = [s for s in p_subs if s.status == "done"]
        ac_count = sum(1 for s in judged if s.verdict == "AC")
        pass_rate = round(ac_count / len(judged), 4) if judged else 0.0

        # 与逐学生表同一份每题有效分：有分才进直方图，None 不进（桶语义 0.4.0 起不变）
        effective_scores = []
        for s in students:
            value = effective_by_student[s.id].get(ap.problem_id)
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
        "avg_total_score": round(sum(totals) / len(totals), 1) if totals else 0.0,
        "pass_rate": round(passed / len(students), 4) if students else 0.0,
        "max_total_score": float(max(totals)) if totals else None,
        "min_total_score": float(min(totals)) if totals else None,
        "full_score_sum": full_score_sum,
    }


def student_rows(db: Session, assignment: Assignment) -> list[dict]:
    """逐学生成绩行（SC-01）。

    - best_effective_score：语义是「各题有效分里的最高单题分」，不是本场总分；
      名字沿用历史契约以保持算法/口径不变，多题场次的合计请看 total_score。
    - total_score = Σ(problem_scores 中非 None 的有效分)，即题单内各题有效分之和，
      与 SC-02 导出的「总分」列同源（与 overview 的班级总分指标同走 `_total_score`）。
    题目与提交各取一次（submissions 一次全取、problems 一次 in 查询），不在学生循环里查库。
    """
    students = groups_svc.audience_students(db, assignment)
    subs_by_student = _subs_by_student(db, assignment)

    ordered_problems = assignment_problems_ordered(db, assignment.id)
    problems = _problems_by_id(db, ordered_problems)
    # 0.4.1 F9：谁被打回重做了，教师端成绩表要能标出来（一次取回，别逐生查）
    retries_by_student = retries_svc.retry_deadlines_by_assignment(db, assignment.id)

    rows = []
    for student in students:
        mine = subs_by_student.get(student.id, [])
        effective_by_problem = _effective_by_problem(mine, assignment.score_policy)
        # best 覆盖该生所有有提交的题（含已移出题单的），total 只算题单内的题。
        values = [v for v in effective_by_problem.values() if v is not None]
        best = round(max(values), 1) if values else 0.0

        problem_scores = []
        for ap in ordered_problems:
            problem = problems.get(ap.problem_id)
            value = effective_by_problem.get(ap.problem_id)
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
            "total_score": _total_score(ordered_problems, effective_by_problem),
            "problem_scores": problem_scores,
            "last_submitted_at": last.submitted_at if last else None,
            "last_submission_id": last.id if last else None,
            "retry_deadline": retries_by_student.get(student.id),
        })
    return rows
