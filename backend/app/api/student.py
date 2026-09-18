from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..core import config
from ..core.db import get_db
from ..core.security import APIError, require_student
from ..models import (Assignment, AssignmentProblem, Problem, Submission,
                      SubmissionResult, TeacherStudent, TestCase, User)
from ..services import scoring, stats, visibility

router = APIRouter()


class MaskedSubmissionOut(BaseModel):
    id: int
    submitted_at: str
    status_text: str


class VisibleSubmissionSummaryOut(BaseModel):
    id: int
    submitted_at: str
    status: str
    verdict: str | None = None
    score: float | None = None
    manual_score: float | None = None


class StudentResultRowOut(BaseModel):
    seq: int
    is_sample: int
    verdict: str
    time_ms: int
    score: float


class VisibleSubmissionDetailOut(BaseModel):
    id: int
    assignment_id: int
    problem_id: int
    status: str
    verdict: str | None = None
    score: float | None = None
    manual_score: float | None = None
    submitted_at: str
    judged_at: str | None = None
    judge_log: str | None = None
    results: list[StudentResultRowOut] = []


class StudentProblemViewOut(BaseModel):
    id: int
    title: str
    description: str
    input_format: str
    output_format: str
    time_limit_ms: int
    memory_limit_mb: int
    compare_mode: str
    full_score: float
    samples: list[schemas.SampleCaseOut] = []
    my_submissions: list[Union[MaskedSubmissionOut, VisibleSubmissionSummaryOut]] = []


class SubmissionIdOut(BaseModel):
    id: int


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _bound_teacher_ids(db: Session, student: User):
    return select(TeacherStudent.teacher_id).where(TeacherStudent.student_id == student.id)


def _get_audience_assignment(db: Session, student: User, assignment_id: int) -> Assignment:
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise APIError(404, "ASSIGNMENT_NOT_FOUND", "场次不存在")
    bound = db.scalar(
        select(TeacherStudent.teacher_id).where(
            TeacherStudent.student_id == student.id,
            TeacherStudent.teacher_id == assignment.created_by,
        )
    )
    if bound is None:
        raise APIError(404, "ASSIGNMENT_NOT_FOUND", "场次不存在")
    return assignment


def _my_submissions_by_problem(db: Session, assignment_id: int, user_id: int) -> dict[int, list[Submission]]:
    rows = db.execute(
        select(Submission).where(
            Submission.assignment_id == assignment_id,
            Submission.user_id == user_id,
        )
    ).scalars().all()
    grouped: dict[int, list[Submission]] = {}
    for s in rows:
        grouped.setdefault(s.problem_id, []).append(s)
    return grouped


def _my_scores(db: Session, student: User, assignment: Assignment) -> list[dict]:
    visible = visibility.can_see_detail(student, assignment)
    grouped = _my_submissions_by_problem(db, assignment.id, student.id)
    scores = []
    for ap in stats.assignment_problems_ordered(db, assignment.id):
        problem = db.get(Problem, ap.problem_id)
        effective = None
        if visible:
            effective = scoring.aggregate_scores(grouped.get(ap.problem_id, []), assignment.score_policy)
        scores.append({
            "problem_id": ap.problem_id,
            "seq": ap.seq,
            "title": problem.title if problem else "",
            "full_score": ap.full_score,
            "effective_score": effective,
        })
    return scores


def _student_assignment_out(db: Session, student: User, assignment: Assignment) -> dict:
    now_s = _utcnow()
    return {
        "id": assignment.id,
        "title": assignment.title,
        "mode": assignment.mode,
        "start_time": assignment.start_time,
        "end_time": assignment.end_time,
        "max_submissions": assignment.max_submissions,
        "score_policy": assignment.score_policy,
        "released": assignment.released,
        "state": "ongoing" if now_s <= assignment.end_time else "ended",
        "my_scores": _my_scores(db, student, assignment),
    }


@router.get("/assignments", response_model=list[schemas.StudentAssignmentOut])
def list_assignments(db: Session = Depends(get_db), student: User = Depends(require_student)):
    now_s = _utcnow()
    rows = db.execute(
        select(Assignment)
        .where(
            Assignment.created_by.in_(_bound_teacher_ids(db, student)),
            Assignment.start_time <= now_s,
        )
        .order_by(Assignment.start_time.desc(), Assignment.id.desc())
    ).scalars().all()
    return [_student_assignment_out(db, student, a) for a in rows]


@router.get("/assignments/{assignment_id}", response_model=schemas.StudentAssignmentOut)
def get_assignment(assignment_id: int,
                   db: Session = Depends(get_db), student: User = Depends(require_student)):
    assignment = _get_audience_assignment(db, student, assignment_id)
    return _student_assignment_out(db, student, assignment)


@router.get("/assignments/{assignment_id}/problems/{problem_id}", response_model=StudentProblemViewOut)
def get_problem(assignment_id: int, problem_id: int,
                db: Session = Depends(get_db), student: User = Depends(require_student)):
    assignment = _get_audience_assignment(db, student, assignment_id)
    ap = db.get(AssignmentProblem, (assignment.id, problem_id))
    if ap is None:
        raise APIError(404, "PROBLEM_NOT_FOUND", "题目不在该场次中")
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise APIError(404, "PROBLEM_NOT_FOUND", "题目不存在")
    samples = db.execute(
        select(TestCase)
        .where(TestCase.problem_id == problem.id, TestCase.is_sample == 1)
        .order_by(TestCase.seq)
    ).scalars().all()
    my_subs = db.execute(
        select(Submission)
        .where(Submission.assignment_id == assignment.id,
               Submission.problem_id == problem.id,
               Submission.user_id == student.id)
        .order_by(Submission.id.desc())
    ).scalars().all()
    visible = visibility.can_see_detail(student, assignment)
    return {
        "id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "input_format": problem.input_format,
        "output_format": problem.output_format,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "compare_mode": problem.compare_mode,
        "full_score": ap.full_score,
        "samples": [{"seq": c.seq, "input": c.input, "expected": c.expected} for c in samples],
        "my_submissions": [
            visibility.masked_submission(s) if not visible else visibility.visible_submission_summary(s)
            for s in my_subs
        ],
    }


@router.post("/assignments/{assignment_id}/problems/{problem_id}/submissions",
             response_model=SubmissionIdOut)
def create_submission(assignment_id: int, problem_id: int, body: schemas.SubmissionCreate,
                      db: Session = Depends(get_db), student: User = Depends(require_student)):
    assignment = _get_audience_assignment(db, student, assignment_id)
    ap = db.get(AssignmentProblem, (assignment.id, problem_id))
    if ap is None or db.get(Problem, problem_id) is None:
        raise APIError(404, "PROBLEM_NOT_FOUND", "题目不在该场次中")

    now_s = _utcnow()
    if not (assignment.start_time <= now_s <= assignment.end_time):
        raise APIError(409, "WINDOW_CLOSED", "不在提交时间窗口内")

    if assignment.max_submissions is not None:
        count = db.scalar(
            select(func.count()).select_from(Submission).where(
                Submission.assignment_id == assignment.id,
                Submission.problem_id == problem_id,
                Submission.user_id == student.id,
            )
        )
        if count >= assignment.max_submissions:
            raise APIError(409, "SUBMIT_LIMIT", "提交次数已达上限")

    last = db.execute(
        select(Submission)
        .where(Submission.problem_id == problem_id, Submission.user_id == student.id)
        .order_by(Submission.id.desc())
        .limit(1)
    ).scalars().first()
    if last is not None:
        last_dt = datetime.strptime(last.submitted_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        if (now_dt - last_dt).total_seconds() < config.SUBMIT_COOLDOWN_S:
            raise APIError(429, "RATE_LIMITED", "提交过于频繁，请稍后再试")

    code = body.code_text.replace("\r\n", "\n")
    if not code.strip():
        raise APIError(413, "CODE_EMPTY", "代码不能为空")
    if len(code.encode("utf-8")) > config.MAX_CODE_BYTES:
        raise APIError(413, "CODE_TOO_LARGE", "代码超过 64KB 上限")

    submission = Submission(
        assignment_id=assignment.id,
        problem_id=problem_id,
        user_id=student.id,
        code_text=code,
        status="pending",
        submitted_at=now_s,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return {"id": submission.id}


@router.get("/submissions/{submission_id}",
            response_model=Union[MaskedSubmissionOut, VisibleSubmissionDetailOut],
            response_model_exclude_none=True)
def get_submission(submission_id: int,
                   db: Session = Depends(get_db), student: User = Depends(require_student)):
    submission = db.get(Submission, submission_id)
    if submission is None or submission.user_id != student.id:
        raise APIError(404, "SUBMISSION_NOT_FOUND", "提交不存在")
    assignment = db.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise APIError(404, "ASSIGNMENT_NOT_FOUND", "场次不存在")
    if not visibility.can_see_detail(student, assignment):
        return visibility.masked_submission(submission)
    rows = db.execute(
        select(SubmissionResult, TestCase)
        .join(TestCase, TestCase.id == SubmissionResult.test_case_id)
        .where(SubmissionResult.submission_id == submission.id)
        .order_by(TestCase.seq)
    ).all()
    return visibility.student_detail(submission, rows)
