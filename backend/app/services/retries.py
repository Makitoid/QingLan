"""「打回重做」的窗口口径（0.4.1 F9）。

及格线判定和重做窗口只在这一处定义，教师端与学生端共用，避免两边各算一份：

- **不及格**：设了 `pass_score` 且该生总分**严格小于**它。未交的学生不算不及格
  （那是 F6「提醒交作业」的活），`pass_score` 为空时整场不判及格线。
- **有效截止时刻**：`max(场次 end_time, 该生的重做 deadline)`。学生端状态、
  提交窗口校验都走 `effective_end`，不再直接读 `assignment.end_time`。
- **重做期内不限提交次数**：`in_retry` 为真时调用方跳过 `max_submissions` 判定，
  否则「打回」对已经用次数打到上限的学生毫无意义。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, AssignmentRetry


def retry_deadlines(db: Session, student_id: int) -> dict[int, str]:
    """该生全部的重做期限：{assignment_id: deadline}（列表接口一次取回，避免逐场次查）。"""
    rows = db.execute(
        select(AssignmentRetry.assignment_id, AssignmentRetry.deadline)
        .where(AssignmentRetry.student_id == student_id)
    ).all()
    return {assignment_id: deadline for assignment_id, deadline in rows}


def retry_deadlines_by_assignment(db: Session, assignment_id: int) -> dict[int, str]:
    """本场次全部的重做期限：{student_id: deadline}（教师端成绩表一次取回）。"""
    rows = db.execute(
        select(AssignmentRetry.student_id, AssignmentRetry.deadline)
        .where(AssignmentRetry.assignment_id == assignment_id)
    ).all()
    return {student_id: deadline for student_id, deadline in rows}


def retry_deadline(db: Session, assignment_id: int, student_id: int) -> str | None:
    row = db.get(AssignmentRetry, (assignment_id, student_id))
    return row.deadline if row is not None else None


def effective_end(assignment: Assignment, deadline: str | None) -> str:
    """时间窗字符串都是 UTC 的 'YYYY-MM-DD HH:MM:SS'，字典序即时间序，可直接 max。"""
    return max(assignment.end_time, deadline) if deadline else assignment.end_time


def in_retry(assignment: Assignment, deadline: str | None, now_s: str) -> bool:
    """当前是否处在「原窗口已关、靠打回续命」的那段时间里。"""
    return bool(deadline) and now_s > assignment.end_time and now_s <= deadline


def is_open(assignment: Assignment, deadline: str | None, now_s: str) -> bool:
    return assignment.start_time <= now_s <= effective_end(assignment, deadline)


def failed_student_ids(rows: list[dict], pass_score: float | None) -> list[int]:
    """从 `stats.student_rows` 的输出里挑出不及格的学生。

    rows 的每条含 student_id / submitted_count / total_score；未交与总分为空的行不参与判定。
    """
    if pass_score is None:
        return []
    return [
        row["student_id"] for row in rows
        if row.get("submitted_count") and row.get("total_score") is not None
        and float(row["total_score"]) < pass_score
    ]
