import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..core.db import get_db
from ..core.security import APIError, require_teacher
from ..models import (Assignment, AssignmentProblem, Group, Problem,
                      Submission, SubmissionResult, TestCase, User)
from ..services import export as export_svc
from ..services import groups as groups_svc
from ..services import stats, visibility

router = APIRouter()

# 红线：本模块不得出现任何密码相关能力（hash_password / ResetPasswordRequest 等），
# 批量重置密码只存在于 admin 端。tests/test_groups_api.py 有断言守护。

COMPARE_MODES = {"exact", "trim", "float"}
SCORE_POLICIES = {"best", "last"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _normalize(text_value: str) -> str:
    return text_value.replace("\r\n", "\n")


def _get_owned_problem(db: Session, teacher: User, problem_id: int) -> Problem:
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise APIError(404, "PROBLEM_NOT_FOUND", "题目不存在")
    if problem.created_by != teacher.id:
        raise APIError(403, "FORBIDDEN", "无权操作他人的题目")
    return problem


def _get_owned_assignment(db: Session, teacher: User, assignment_id: int) -> Assignment:
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise APIError(404, "ASSIGNMENT_NOT_FOUND", "场次不存在")
    if assignment.created_by != teacher.id:
        raise APIError(403, "FORBIDDEN", "无权操作他人的场次")
    return assignment


def _validate_problem_mode(compare_mode: str, float_eps: float | None):
    if compare_mode not in COMPARE_MODES:
        raise APIError(422, "VALIDATION_ERROR", "比对模式不合法")
    if compare_mode == "float" and float_eps is None:
        raise APIError(422, "VALIDATION_ERROR", "float 比对模式必须填写 float_eps")


def _get_owned_case(db: Session, teacher: User, case_id: int) -> TestCase:
    case = db.get(TestCase, case_id)
    if case is None:
        raise APIError(404, "CASE_NOT_FOUND", "用例不存在")
    _get_owned_problem(db, teacher, case.problem_id)
    return case


def _load_draft(raw: str | None) -> schemas.ProblemDraft | None:
    """草稿 JSON → ProblemDraft；脏数据按“无草稿”处理，不让编辑页打不开。"""
    if not raw:
        return None
    try:
        return schemas.ProblemDraft.model_validate(json.loads(raw))
    except Exception:
        return None


def _clear_draft(problem: Problem) -> None:
    problem.draft = None
    problem.draft_saved_at = None


def _validate_assignment_problems(db: Session, teacher: User, items: list[schemas.AssignmentProblemIn]):
    seen = set()
    for item in items:
        if item.problem_id in seen:
            raise APIError(422, "VALIDATION_ERROR", "题单中存在重复题目")
        seen.add(item.problem_id)
        _get_owned_problem(db, teacher, item.problem_id)


def _validate_window(start_time: str, end_time: str):
    if end_time <= start_time:
        raise APIError(422, "VALIDATION_ERROR", "结束时间必须晚于开始时间")


def _assignment_out(db: Session, assignment: Assignment) -> dict:
    problems = []
    for ap in stats.assignment_problems_ordered(db, assignment.id):
        problem = db.get(Problem, ap.problem_id)
        problems.append({
            "problem_id": ap.problem_id,
            "seq": ap.seq,
            "full_score": ap.full_score,
            "title": problem.title if problem else None,
        })
    return {
        "id": assignment.id,
        "title": assignment.title,
        "mode": assignment.mode,
        "start_time": assignment.start_time,
        "end_time": assignment.end_time,
        "max_submissions": assignment.max_submissions,
        "score_policy": assignment.score_policy,
        "released": assignment.released,
        "released_at": assignment.released_at,
        "created_by": assignment.created_by,
        "created_at": assignment.created_at,
        "problems": problems,
    }


def _get_owned_submission(db: Session, teacher: User, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise APIError(404, "SUBMISSION_NOT_FOUND", "提交不存在")
    assignment = db.get(Assignment, submission.assignment_id)
    if assignment is None or assignment.created_by != teacher.id:
        raise APIError(403, "FORBIDDEN", "无权查看该提交")
    return submission


def _submission_detail(db: Session, submission: Submission) -> dict:
    rows = db.execute(
        select(SubmissionResult, TestCase)
        .join(TestCase, TestCase.id == SubmissionResult.test_case_id)
        .where(SubmissionResult.submission_id == submission.id)
        .order_by(TestCase.seq)
    ).all()
    return visibility.teacher_detail(submission, rows)


@router.get("/problems", response_model=list[schemas.ProblemOut])
def list_problems(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    return db.execute(
        select(Problem).where(Problem.created_by == teacher.id).order_by(Problem.id.desc())
    ).scalars().all()


@router.post("/problems", response_model=schemas.ProblemOut)
def create_problem(body: schemas.ProblemCreate,
                   db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    _validate_problem_mode(body.compare_mode, body.float_eps)
    problem = Problem(**body.model_dump(), created_by=teacher.id)
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


@router.get("/problems/{problem_id}", response_model=schemas.ProblemDetailOut)
def get_problem(problem_id: int,
                db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    problem = _get_owned_problem(db, teacher, problem_id)
    cases = db.execute(
        select(TestCase).where(TestCase.problem_id == problem.id).order_by(TestCase.seq)
    ).scalars().all()
    draft = _load_draft(problem.draft)
    data = schemas.ProblemOut.model_validate(problem).model_dump()
    data["cases"] = cases
    data["draft"] = draft.model_dump() if draft is not None else None
    data["draft_saved_at"] = problem.draft_saved_at
    return data


@router.put("/problems/{problem_id}", response_model=schemas.ProblemOut)
def update_problem(problem_id: int, body: schemas.ProblemUpdate,
                   db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    problem = _get_owned_problem(db, teacher, problem_id)
    changes = body.model_dump(exclude_unset=True)
    merged_mode = changes.get("compare_mode", problem.compare_mode)
    merged_eps = changes.get("float_eps", problem.float_eps)
    if "compare_mode" in changes or "float_eps" in changes:
        _validate_problem_mode(merged_mode, merged_eps)
    for field, value in changes.items():
        setattr(problem, field, value)
    # 正式保存成功即视为草稿已落地，顺带清空（跨设备不再提示恢复）
    _clear_draft(problem)
    db.commit()
    db.refresh(problem)
    return problem


@router.put("/problems/{problem_id}/draft", response_model=schemas.ProblemDraftSavedOut)
def save_problem_draft(problem_id: int, body: schemas.ProblemDraft,
                       db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """保存未提交的编辑内容；新草稿直接覆盖旧草稿（每题仅一份）。"""
    problem = _get_owned_problem(db, teacher, problem_id)
    if body.compare_mode not in COMPARE_MODES:
        raise APIError(422, "VALIDATION_ERROR", "比对模式不合法")
    problem.draft = json.dumps(body.model_dump(), ensure_ascii=False)
    problem.draft_saved_at = _utcnow()
    db.commit()
    return schemas.ProblemDraftSavedOut(draft_saved_at=problem.draft_saved_at)


@router.delete("/problems/{problem_id}/draft")
def delete_problem_draft(problem_id: int,
                         db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    problem = _get_owned_problem(db, teacher, problem_id)
    _clear_draft(problem)
    db.commit()
    return {"ok": True}


@router.delete("/problems/{problem_id}")
def delete_problem(problem_id: int,
                   db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    problem = _get_owned_problem(db, teacher, problem_id)
    referenced = db.scalar(
        select(AssignmentProblem.problem_id).where(AssignmentProblem.problem_id == problem.id)
    )
    if referenced is not None:
        raise APIError(409, "PROBLEM_IN_USE", "题目已被场次引用，无法删除")
    db.delete(problem)
    db.commit()
    return {"ok": True}


@router.post("/problems/{problem_id}/cases", response_model=schemas.TestCaseOut)
def create_case(problem_id: int, body: schemas.TestCaseCreate,
                db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    _get_owned_problem(db, teacher, problem_id)
    case = TestCase(
        problem_id=problem_id,
        seq=body.seq,
        input=_normalize(body.input),
        expected=_normalize(body.expected),
        is_sample=1 if body.is_sample else 0,
        weight=body.weight,
    )
    db.add(case)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "CASE_SEQ_DUPLICATE", "该题目下用例序号重复")
    db.refresh(case)
    return case


@router.put("/cases/{case_id}", response_model=schemas.TestCaseOut)
def update_case(case_id: int, body: schemas.TestCaseUpdate,
                db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    case = _get_owned_case(db, teacher, case_id)
    changes = body.model_dump(exclude_unset=True)
    if "input" in changes and changes["input"] is not None:
        changes["input"] = _normalize(changes["input"])
    if "expected" in changes and changes["expected"] is not None:
        changes["expected"] = _normalize(changes["expected"])
    if "is_sample" in changes and changes["is_sample"] is not None:
        changes["is_sample"] = 1 if changes["is_sample"] else 0
    for field, value in changes.items():
        setattr(case, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "CASE_SEQ_DUPLICATE", "该题目下用例序号重复")
    db.refresh(case)
    return case


@router.delete("/cases/{case_id}")
def delete_case(case_id: int,
                db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    case = _get_owned_case(db, teacher, case_id)
    db.delete(case)
    db.commit()
    return {"ok": True}


@router.get("/assignments", response_model=list[schemas.AssignmentOut])
def list_assignments(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignments = db.execute(
        select(Assignment).where(Assignment.created_by == teacher.id).order_by(Assignment.id.desc())
    ).scalars().all()
    return [_assignment_out(db, a) for a in assignments]


@router.post("/assignments", response_model=schemas.AssignmentOut)
def create_assignment(body: schemas.AssignmentCreate,
                      db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    _validate_window(body.start_time, body.end_time)
    _validate_assignment_problems(db, teacher, body.problems)
    assignment = Assignment(
        title=body.title,
        mode=body.mode,
        start_time=body.start_time,
        end_time=body.end_time,
        max_submissions=body.max_submissions,
        score_policy=body.score_policy,
        created_by=teacher.id,
    )
    db.add(assignment)
    db.flush()
    for item in body.problems:
        db.add(AssignmentProblem(
            assignment_id=assignment.id,
            problem_id=item.problem_id,
            seq=item.seq,
            full_score=item.full_score,
        ))
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.get("/assignments/{assignment_id}", response_model=schemas.AssignmentOut)
def get_assignment(assignment_id: int,
                   db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    return _assignment_out(db, assignment)


@router.put("/assignments/{assignment_id}", response_model=schemas.AssignmentOut)
def update_assignment(assignment_id: int, body: schemas.AssignmentUpdate,
                      db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    if _utcnow() >= assignment.start_time:
        raise APIError(409, "ALREADY_STARTED", "场次已开始，不可修改")
    changes = body.model_dump(exclude_unset=True)
    if "problems" in changes:
        has_submissions = db.scalar(
            select(Submission.id).where(Submission.assignment_id == assignment.id)
        )
        if has_submissions is not None:
            raise APIError(409, "HAS_SUBMISSIONS", "场次已有提交，禁止修改题单")
        if not changes["problems"]:
            raise APIError(422, "VALIDATION_ERROR", "题单不能为空")
        items = [schemas.AssignmentProblemIn(**p) for p in changes.pop("problems")]
        _validate_assignment_problems(db, teacher, items)
    if "score_policy" in changes and changes["score_policy"] not in SCORE_POLICIES:
        raise APIError(422, "VALIDATION_ERROR", "计分策略不合法")
    merged_start = changes.get("start_time", assignment.start_time)
    merged_end = changes.get("end_time", assignment.end_time)
    _validate_window(merged_start, merged_end)
    for field, value in changes.items():
        setattr(assignment, field, value)
    if "problems" in body.model_fields_set:
        old = db.execute(
            select(AssignmentProblem).where(AssignmentProblem.assignment_id == assignment.id)
        ).scalars().all()
        for row in old:
            db.delete(row)
        db.flush()
        for item in items:
            db.add(AssignmentProblem(
                assignment_id=assignment.id,
                problem_id=item.problem_id,
                seq=item.seq,
                full_score=item.full_score,
            ))
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.post("/assignments/{assignment_id}/release", response_model=schemas.AssignmentOut)
def release_assignment(assignment_id: int,
                       db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    if assignment.mode != "test" or _utcnow() <= assignment.end_time:
        raise APIError(409, "NOT_RELEASABLE", "仅测试模式且已过结束时间的场次可放出")
    assignment.released = 1
    assignment.released_at = _utcnow()
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.get("/assignments/{assignment_id}/overview", response_model=schemas.OverviewOut)
def assignment_overview(assignment_id: int,
                        db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    return stats.overview(db, assignment)


@router.get("/assignments/{assignment_id}/students", response_model=list[schemas.StudentRowOut])
def assignment_students(assignment_id: int,
                        db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    return stats.student_rows(db, assignment)


@router.get("/assignments/{assignment_id}/export")
def export_assignment_students(assignment_id: int, tz_offset: int = 0,
                               db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """导出本场次成绩 xlsx。tz_offset 为前端本地时区分钟偏移（库内是 UTC，坑 9）。"""
    assignment = _get_owned_assignment(db, teacher, assignment_id)
    rows = stats.student_rows(db, assignment)
    payload = export_svc.build_assignment_students_xlsx(assignment.title, rows, tz_offset)
    headers = export_svc.attachment_headers(f"{assignment.title}_成绩.xlsx")
    return StreamingResponse(iter([payload]), media_type=export_svc.XLSX_MEDIA_TYPE, headers=headers)


@router.get("/submissions/{submission_id}", response_model=schemas.SubmissionDetailOut)
def get_submission(submission_id: int,
                   db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    submission = _get_owned_submission(db, teacher, submission_id)
    return _submission_detail(db, submission)


@router.post("/submissions/{submission_id}/rejudge", response_model=schemas.SubmissionDetailOut)
def rejudge_submission(submission_id: int,
                       db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    submission = _get_owned_submission(db, teacher, submission_id)
    results = db.execute(
        select(SubmissionResult).where(SubmissionResult.submission_id == submission.id)
    ).scalars().all()
    for row in results:
        db.delete(row)
    submission.status = "pending"
    submission.verdict = None
    submission.score = None
    submission.judged_at = None
    submission.worker_id = None
    submission.judge_log = None
    db.commit()
    db.refresh(submission)
    return _submission_detail(db, submission)


@router.patch("/submissions/{submission_id}/score", response_model=schemas.SubmissionDetailOut)
def patch_manual_score(submission_id: int, body: schemas.ManualScorePatch,
                       db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    submission = _get_owned_submission(db, teacher, submission_id)
    submission.manual_score = body.manual_score
    db.commit()
    db.refresh(submission)
    return _submission_detail(db, submission)


# ---------- 学生与分组（教师端无任何密码接口）----------

@router.get("/students", response_model=list[schemas.BoundStudentOut])
def list_bound_students(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    students = stats.bound_students(db, teacher.id)
    group_map = groups_svc.groups_map_for_students(db, [s.id for s in students])
    return [
        schemas.BoundStudentOut(
            id=s.id,
            username=s.username,
            display_name=s.display_name,
            is_active=s.is_active,
            groups=group_map.get(s.id, []),
        )
        for s in students
    ]


@router.get("/groups", response_model=list[schemas.GroupOut])
def list_groups(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """组定义全站共享，教师只读。"""
    return [
        schemas.GroupOut(id=g.id, name=g.name, created_at=g.created_at, member_count=count)
        for g, count in groups_svc.list_groups_with_count(db)
    ]


@router.post("/students/group_members", response_model=schemas.GroupMembershipOut)
def batch_group_members(body: schemas.GroupMembersRequest,
                        db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """批量加入/移出分组：先校验 student_ids ⊆ 绑定学生集合，越权则整批 403 拒绝。"""
    student_ids = list(dict.fromkeys(body.student_ids))
    if not student_ids:
        raise APIError(422, "EMPTY_SELECTION", "未选择任何学生")
    bound_ids = {s.id for s in stats.bound_students(db, teacher.id)}
    if not set(student_ids) <= bound_ids:
        raise APIError(403, "STUDENT_NOT_BOUND", "存在未绑定到本教师的学生，操作已整批取消")
    changed = groups_svc.apply_membership(db, student_ids, body.group_ids, body.action)
    return schemas.GroupMembershipOut(success_count=changed)
