import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..core.db import get_db
from ..core.security import APIError, require_teacher, utcnow_str
from ..models import (Assignment, AssignmentProblem, Group, GroupMember,
                      Problem, Submission, SubmissionResult, TeacherGroup,
                      TeacherStudent, TestCase, User)
from ..services import export as export_svc
from ..services import groups as groups_svc
from ..services import stats, visibility
from ..services.audit import log_audit

router = APIRouter()

# 红线：本模块不得出现任何密码相关能力（hash_password / ResetPasswordRequest 等），
# 批量重置密码只存在于 admin 端。tests/test_groups_api.py 有断言守护。

COMPARE_MODES = {"exact", "trim", "float"}
SCORE_POLICIES = {"best", "last"}


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
    problem.draft_saved_at = utcnow_str()
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
    if utcnow_str() >= assignment.start_time:
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
    if assignment.mode != "test" or utcnow_str() <= assignment.end_time:
        raise APIError(409, "NOT_RELEASABLE", "仅测试模式且已过结束时间的场次可放出")
    assignment.released = 1
    assignment.released_at = utcnow_str()
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
    """重判：清空判定结果回到 pending（附录 A scoring.rejudge_resets 全清单）。"""
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
    # SC-04：人工调分必须一并作废 —— 否则旧调分会以「覆盖系统分」的优先级残留下来，
    # 把新判出来的成绩顶掉，造成计分错误。
    submission.manual_score = None
    submission.manual_score_updated_at = None
    db.commit()
    db.refresh(submission)
    return _submission_detail(db, submission)


@router.patch("/submissions/{submission_id}/score", response_model=schemas.SubmissionDetailOut)
def patch_manual_score(submission_id: int, body: schemas.ManualScorePatch,
                       db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """人工调分（SC-03）：null = 撤销调分；非 null 须落在 0 ~ 该题在本场次的满分之间。"""
    submission = _get_owned_submission(db, teacher, submission_id)
    full_score = db.scalar(
        select(AssignmentProblem.full_score)
        .where(AssignmentProblem.assignment_id == submission.assignment_id,
               AssignmentProblem.problem_id == submission.problem_id)
    )
    old_score = submission.manual_score
    if body.manual_score is not None:
        # 查不到 assignment_problem（题单已被改/数据异常）时无满分上界可依，同样拒绝。
        if full_score is None:
            raise APIError(422, "MANUAL_SCORE_OUT_OF_RANGE", "该题未在本场次中配置分值，无法调分")
        if not 0 <= body.manual_score <= full_score:
            raise APIError(422, "MANUAL_SCORE_OUT_OF_RANGE", f"调分必须在 0 ~ {full_score:g} 之间")
    submission.manual_score = body.manual_score
    submission.manual_score_updated_at = utcnow_str() if body.manual_score is not None else None
    log_audit(db, teacher, "score_manual_adjust", "submission", submission.id,
              {"old": old_score, "new": body.manual_score, "full_score": full_score})
    db.commit()
    db.refresh(submission)
    return _submission_detail(db, submission)


# ---------- 学生名单与班级（教师端无任何密码接口；组别对本模块只读）----------
#
# 三层归属模型（BD-01~05）：
#   层 1  groups / group_members —— admin 唯一写者；教师只能读到「自己可教的组」，
#         且只经 /classes 这一条路径（GR-02：/groups 与批量改组成员接口已废弃）。
#   层 2  teacher_groups         —— admin 分配哪个教师可教哪个组。
#   层 3  teacher_students       —— 教师自己的名单，唯一写者是教师本人，且只能在
#         可教组内（主路径）或按有效学号（兜底）拉人，拉/移均幂等。
#
# 与既有风格一致：所有写操作单事务，先全量校验、后写入，任一不合法整批拒绝。


def _requested_student_ids(raw: list[int]) -> list[int]:
    """去重保序；空选择在写库之前就拦下。"""
    ids = list(dict.fromkeys(raw))
    if not ids:
        raise APIError(422, "EMPTY_SELECTION", "未选择任何学生")
    return ids


def _my_student_ids(db: Session, teacher_id: int) -> set[int]:
    """我的名单（层 3）里的学生 ID。"""
    return set(db.execute(
        select(TeacherStudent.student_id).where(TeacherStudent.teacher_id == teacher_id)
    ).scalars().all())


def _teachable_group_ids(db: Session, teacher_id: int) -> set[int]:
    """我经 teacher_groups 可教的组 ID（层 2）。"""
    return set(db.execute(
        select(TeacherGroup.group_id).where(TeacherGroup.teacher_id == teacher_id)
    ).scalars().all())


def _bind_students(db: Session, teacher: User, student_ids: list[int], source: str) -> int:
    """幂等拉入名单并写审计（层 3 的唯一写路径），返回实际新增条数。

    权限校验由调用方在写库之前完成，保证「先校验后写入」的单事务语义。
    """
    existing = _my_student_ids(db, teacher.id)
    added = [sid for sid in student_ids if sid not in existing]
    for sid in added:
        db.add(TeacherStudent(teacher_id=teacher.id, student_id=sid))
    log_audit(db, teacher, "teacher_student_bind", "teacher", teacher.id,
              {"count": len(added), "student_ids": added, "source": source})
    db.commit()
    return len(added)


@router.get("/students", response_model=list[schemas.BoundStudentOut])
def list_bound_students(q: str | None = None,
                        db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """我的名单（层 3）。q 为 username / display_name 的模糊匹配（大小写不敏感），缺省时行为不变。"""
    students = list(stats.bound_students(db, teacher.id))
    keyword = (q or "").strip().lower()
    if keyword:
        students = [
            s for s in students
            if keyword in s.username.lower() or keyword in (s.display_name or "").lower()
        ]
    group_map = groups_svc.groups_map_for_students(db, [s.id for s in students])
    return [
        schemas.BoundStudentOut(
            id=s.id,
            username=s.username,
            display_name=s.display_name,
            is_active=s.is_active,
            must_change_password=bool(s.must_change_password),
            groups=group_map.get(s.id, []),
        )
        for s in students
    ]


@router.get("/classes", response_model=list[schemas.ClassOut])
def list_my_classes(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """我可教的班级及其成员（层 1 只读视图，按组名排序；教师端唯一的组入口）。

    停用的学生照常返回、由 is_active 标注（BD-03）；bound 表示该生已在我的名单里，
    前端据此把「拉入」按钮置灰。没有可教的组时返回空列表。
    """
    groups = db.execute(
        select(Group)
        .join(TeacherGroup, TeacherGroup.group_id == Group.id)
        .where(TeacherGroup.teacher_id == teacher.id)
        .order_by(Group.name, Group.id)
    ).scalars().all()
    if not groups:
        return []
    roster = _my_student_ids(db, teacher.id)
    rows = db.execute(
        select(GroupMember.group_id, User.id, User.username, User.display_name, User.is_active)
        .join(User, User.id == GroupMember.student_id)
        .where(GroupMember.group_id.in_([g.id for g in groups]), User.role == "student")
        .order_by(GroupMember.group_id, User.id)
    ).all()
    members: dict[int, list[schemas.ClassStudentOut]] = {}
    for group_id, student_id, username, display_name, is_active in rows:
        members.setdefault(group_id, []).append(schemas.ClassStudentOut(
            id=student_id,
            username=username,
            display_name=display_name,
            is_active=is_active,
            bound=student_id in roster,
        ))
    out = []
    for g in groups:
        students = members.get(g.id, [])
        out.append(schemas.ClassOut(id=g.id, name=g.name,
                                    member_count=len(students), students=students))
    return out


@router.post("/students/bind_from_class", response_model=schemas.GroupMembershipOut)
def bind_students_from_class(body: schemas.BindStudentsRequest,
                             db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """BD-03 主路径：把可教班级里的学生拉进我的名单（幂等）。

    任一 student_id 不属于我可教的组 → 整批 403 且不写库，不存在部分成功。
    """
    student_ids = _requested_student_ids(body.student_ids)
    group_ids = _teachable_group_ids(db, teacher.id)
    in_class: set[int] = set()
    if group_ids:
        in_class = set(db.execute(
            select(GroupMember.student_id)
            .join(User, User.id == GroupMember.student_id)
            .where(GroupMember.group_id.in_(sorted(group_ids)),
                   GroupMember.student_id.in_(student_ids),
                   User.role == "student")
        ).scalars().all())
    if set(student_ids) != in_class:
        raise APIError(403, "STUDENT_NOT_IN_CLASS", "存在不属于我可教班级的学生，操作已整批取消")
    added = _bind_students(db, teacher, student_ids, "class")
    return schemas.GroupMembershipOut(success_count=added)


@router.post("/students/bind", response_model=schemas.GroupMembershipOut)
def bind_students_by_ids(body: schemas.BindStudentsRequest,
                         db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """BD-04 兜底：按学生 ID 直接拉入名单，覆盖转学生/旁听等「暂不在组」场景。

    仅校验 role=student 且账号有效；响应只回条数、不回学生明细，
    免得这个接口变成教师端的全量学生名册。
    """
    student_ids = _requested_student_ids(body.student_ids)
    valid = set(db.execute(
        select(User.id)
        .where(User.id.in_(student_ids), User.role == "student", User.is_active == 1)
    ).scalars().all())
    if valid != set(student_ids):
        raise APIError(422, "INVALID_STUDENT_IDS", "存在无效、非学生或已停用的账号")
    added = _bind_students(db, teacher, student_ids, "manual")
    return schemas.GroupMembershipOut(success_count=added)


@router.post("/students/unbind", response_model=schemas.GroupMembershipOut)
def unbind_students(body: schemas.BindStudentsRequest,
                    db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """BD-05：只能从自己的名单里移除；不在名单里的直接忽略（幂等，不算错）。

    移除后历史提交/成绩保留，教师统计仍可见（见 specs「移除学生后历史成绩可见性」）。
    """
    student_ids = _requested_student_ids(body.student_ids)
    removed = sorted(_my_student_ids(db, teacher.id) & set(student_ids))
    for sid in removed:
        db.delete(db.get(TeacherStudent, (teacher.id, sid)))
    log_audit(db, teacher, "teacher_student_unbind", "teacher", teacher.id,
              {"count": len(removed), "student_ids": removed})
    db.commit()
    return schemas.GroupMembershipOut(success_count=len(removed))
