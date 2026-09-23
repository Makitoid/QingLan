"""学生分组（groups / group_members）与「组-教师分配」（teacher_groups）共用服务。

约定（0.3.0 方案 B / GR-01）：
- 组是全站唯一的组织概念（行政班），**admin 是层 1 成员关系与层 2 组-教师分配的唯一写者**；
  教师对该两层只读（教师端写接口已随 GR-02 删除），只能在可教组内维护自己的学生名单（层 3）。
- 所有写操作单事务：先全量校验、后写入，任何一项不合法整批拒绝，不存在部分成功。
- 需要「写操作 + 审计同事务」的调用方（admin 端）使用不提交的 `*_changes` /
  `assign_teacher_groups`，自行 `log_audit` 后 commit；无审计需求的调用方用提交版包装。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import APIError
from ..models import (Assignment, AssignmentSubgroup, Group, GroupMember,
                      TeacherGroup, TeacherStudent, TeacherSubgroup,
                      TeacherSubgroupMember, User)
from ..schemas import GroupRef

MAX_GROUP_NAME_LEN = 50

# 进程内 name -> id 缓存：同一次导入/同批请求里的重名只落一次库，避免撞 UNIQUE。
# ensure_groups 会先与库中真实行核对，故组被删除/重命名后不会返回陈旧 ID。
_name_to_id: dict[str, int] = {}
_CACHE_MAX = 2000


def forget_group_in_cache(group_id: int) -> None:
    """组被重命名或删除后调用，清掉可能陈旧的缓存项。"""
    for name in [k for k, v in _name_to_id.items() if v == group_id]:
        _name_to_id.pop(name, None)


def remember_group_in_cache(name: str, group_id: int) -> None:
    """admin 端新建/重命名组后同步缓存，避免同批后续操作重复插入。"""
    _name_to_id[name] = group_id


def groups_map_for_students(db: Session, student_ids: list[int] | None = None) -> dict[int, list[GroupRef]]:
    """一次联查得到 {student_id: [GroupRef]}，按组名排序，供列表接口拼装。"""
    stmt = (
        select(GroupMember.student_id, Group.id, Group.name)
        .join(Group, Group.id == GroupMember.group_id)
        .order_by(Group.name, Group.id)
    )
    if student_ids is not None:
        if not student_ids:
            return {}
        stmt = stmt.where(GroupMember.student_id.in_(student_ids))
    result: dict[int, list[GroupRef]] = {}
    for student_id, group_id, name in db.execute(stmt).all():
        result.setdefault(student_id, []).append(GroupRef(id=group_id, name=name))
    return result


def list_groups_with_count(db: Session) -> list[tuple[Group, int]]:
    """全部组 + 成员数（一次聚合联查，避免 N+1）。"""
    counts = dict(
        db.query(GroupMember.group_id, func.count(GroupMember.student_id))
        .group_by(GroupMember.group_id)
        .all()
    )
    groups = db.execute(select(Group).order_by(Group.name, Group.id)).scalars().all()
    return [(g, counts.get(g.id, 0)) for g in groups]


def require_groups_exist(db: Session, group_ids: list[int]) -> list[Group]:
    groups = []
    for gid in group_ids:
        group = db.get(Group, gid)
        if group is None:
            raise APIError(404, "GROUP_NOT_FOUND", f"分组 {gid} 不存在")
        groups.append(group)
    return groups


def normalize_group_names(names) -> list[str]:
    """去空白、去空、去重（保序）、丢弃超长项。"""
    cleaned = []
    for raw in names:
        name = (raw or "").strip()
        if not name or len(name) > MAX_GROUP_NAME_LEN:
            continue
        if name not in cleaned:
            cleaned.append(name)
    return cleaned


def ensure_groups(db: Session, names: list[str]) -> list[Group]:
    """按名取组，不存在则创建（导入时自动建组用）。单事务：全部建好后统一 flush。"""
    wanted = normalize_group_names(names)
    if not wanted:
        return []
    if len(_name_to_id) > _CACHE_MAX:
        _name_to_id.clear()

    resolved: dict[str, Group] = {}
    missing: list[str] = []
    for name in wanted:
        cached_id = _name_to_id.get(name)
        if cached_id is not None:
            group = db.get(Group, cached_id)
            if group is not None and group.name == name:
                resolved[name] = group
                continue
            _name_to_id.pop(name, None)
        existing = db.execute(select(Group).where(Group.name == name)).scalar_one_or_none()
        if existing is not None:
            _name_to_id[name] = existing.id
            resolved[name] = existing
        else:
            missing.append(name)

    for name in missing:
        group = Group(name=name)
        db.add(group)
        try:
            # 保存点：并发下同名组已被他人插入时，只回滚这一条 INSERT，
            # 不动外层事务（导入流程里已插入的学生行不能被牵连）。
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            _name_to_id.clear()
            existing = db.execute(select(Group).where(Group.name == name)).scalar_one_or_none()
            if existing is None:
                raise APIError(409, "GROUP_NAME_EXISTS", f"分组「{name}」创建失败")
            _name_to_id[name] = existing.id
            resolved[name] = existing
            continue
        _name_to_id[name] = group.id
        resolved[name] = group

    return [resolved[name] for name in wanted]


def membership_pairs(db: Session, student_ids: list[int], group_ids: list[int]) -> set[tuple[int, int]]:
    rows = db.execute(
        select(GroupMember.group_id, GroupMember.student_id)
        .where(GroupMember.student_id.in_(student_ids), GroupMember.group_id.in_(group_ids))
    ).all()
    return {(group_id, student_id) for group_id, student_id in rows}


def apply_membership_changes(db: Session, student_ids: list[int], group_ids: list[int],
                             action: str) -> int:
    """幂等增删成员关系，**不 commit**（供 admin 端把审计写进同一事务）。

    add 用差集插入，remove 直接删除。返回实际写入/删除的「学生×组」条数。
    校验不过整批抛出，调用方需自行回滚。
    """
    students = list(dict.fromkeys(student_ids))
    groups = list(dict.fromkeys(group_ids))
    if not students or not groups:
        raise APIError(422, "EMPTY_SELECTION", "学生与分组均不能为空")
    require_groups_exist(db, groups)
    valid = {row[0] for row in db.execute(
        select(User.id).where(User.id.in_(students), User.role == "student")
    ).all()}
    if valid != set(students):
        raise APIError(422, "INVALID_STUDENT_IDS", "存在无效或非学生的用户 ID")

    target = {(gid, sid) for gid in groups for sid in students}
    existing = membership_pairs(db, students, groups)
    if action == "add":
        pairs = sorted(target - existing)
    elif action == "remove":
        pairs = sorted(existing & target)
    else:
        raise APIError(422, "VALIDATION_ERROR", "action 仅支持 add / remove")
    for group_id, student_id in pairs:
        if action == "add":
            db.add(GroupMember(group_id=group_id, student_id=student_id))
        else:
            db.delete(db.get(GroupMember, (group_id, student_id)))
    return len(pairs)


def apply_membership(db: Session, student_ids: list[int], group_ids: list[int], action: str) -> int:
    """`apply_membership_changes` 的单事务提交版（审计由调用方另行处理）。"""
    try:
        changed = apply_membership_changes(db, student_ids, group_ids, action)
        db.commit()
    except APIError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise APIError(409, "MEMBERSHIP_CONFLICT", "成员关系写入冲突，请重试")
    return changed


def teacher_group_pairs(db: Session, teacher_ids: list[int]) -> set[tuple[int, int]]:
    """已有分配集合，幂等写入前的一次联查。"""
    if not teacher_ids:
        return set()
    return {
        (tid, gid)
        for tid, gid in db.execute(
            select(TeacherGroup.teacher_id, TeacherGroup.group_id)
            .where(TeacherGroup.teacher_id.in_(teacher_ids))
        ).all()
    }


def assign_teacher_groups(db: Session, pairs: list[tuple[int, int]]) -> int:
    """幂等写入层 2「组-教师分配」（BD-02 / IM-01）：已存在的不重复插。

    只 db.add、**不 commit** —— 导入时这批关系要与建号同事务，由调用方提交。
    返回实际新增的条数（同批重复项只算一次）。
    """
    wanted = list(dict.fromkeys((int(tid), int(gid)) for tid, gid in pairs if tid and gid))
    if not wanted:
        return 0
    existing = teacher_group_pairs(db, sorted({tid for tid, _ in wanted}))
    added = 0
    for tid, gid in wanted:
        if (tid, gid) in existing:
            continue
        db.add(TeacherGroup(teacher_id=tid, group_id=gid))
        existing.add((tid, gid))  # 未提交前查不到自己，同批去重靠这个集合
        added += 1
    return added


def validate_student_ids(db: Session, student_ids: list[int]) -> list[User]:
    """批量操作前的全量校验：任一 ID 不存在或非学生 → 整批 422。"""
    ids = list(dict.fromkeys(student_ids))
    if not ids:
        raise APIError(422, "EMPTY_SELECTION", "未选择任何学生")
    rows = db.execute(select(User).where(User.id.in_(ids), User.role == "student")).scalars().all()
    if {r.id for r in rows} != set(ids):
        raise APIError(422, "INVALID_STUDENT_IDS", "存在无效或非学生的用户 ID")
    return sorted(rows, key=lambda u: u.id)


# ---------- 0.3.2 F1：可教组并集名单 / 子分组 / 发布受众 ----------
#
# 名单口径（决策 1b/1e）：`可教组成员 ∪ 手动添加`，是名单、统计、受众三处的唯一来源。
# 本模块只放「层 2 并集」与「子分组」两件事；组装 User 行与教师反查见 stats.bound_students。

def teachable_student_ids(db: Session, teacher_id: int) -> set[int]:
    """经 teacher_groups 分配给该教师的所有组的成员 ID（去重，层 2 并集）。"""
    return set(db.execute(
        select(GroupMember.student_id)
        .join(TeacherGroup, TeacherGroup.group_id == GroupMember.group_id)
        .where(TeacherGroup.teacher_id == teacher_id)
    ).scalars().all())


def teachable_group_names_by_student(db: Session, teacher_id: int) -> dict[int, list[str]]:
    """{student_id: [含该生的可教组名]}，按组名排序（admin 教师详情名单的 group_names 列）。"""
    rows = db.execute(
        select(GroupMember.student_id, Group.name)
        .join(TeacherGroup, TeacherGroup.group_id == GroupMember.group_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(TeacherGroup.teacher_id == teacher_id)
        .order_by(Group.name, Group.id)
    ).all()
    result: dict[int, list[str]] = {}
    for student_id, name in rows:
        result.setdefault(student_id, []).append(name)
    return result


def student_ids_in_groups(db: Session, group_ids: list[int]) -> dict[int, set[int]]:
    """{group_id: {student_id}}（只含 role=student），组别撤销时的差集统计用。"""
    ids = sorted(dict.fromkeys(group_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(GroupMember.group_id, GroupMember.student_id)
        .join(User, User.id == GroupMember.student_id)
        .where(GroupMember.group_id.in_(ids), User.role == "student")
    ).all()
    result: dict[int, set[int]] = {}
    for group_id, student_id in rows:
        result.setdefault(group_id, set()).add(student_id)
    return result


def manual_student_ids(db: Session, teacher_id: int) -> set[int]:
    """层 3「手动添加」的原始行（未过 role/is_active 口径），unbind 与通知的差集口径用。"""
    return set(db.execute(
        select(TeacherStudent.student_id).where(TeacherStudent.teacher_id == teacher_id)
    ).scalars().all())


def roster_count_by_teacher(db: Session) -> dict[int, int]:
    """每个教师的名单人数（可教组并集 ∪ 手动添加，只算 role=student），admin 列表页用。

    两条聚合查询后在内存取并集，避免逐教师 N+1。没有名单的教师不出现在结果里，
    调用方按 `counts.get(tid, 0)` 兜底。
    """
    roster: dict[int, set[int]] = {}
    for teacher_id, student_id in db.execute(
        select(TeacherGroup.teacher_id, GroupMember.student_id)
        .join(GroupMember, GroupMember.group_id == TeacherGroup.group_id)
        .join(User, User.id == GroupMember.student_id)
        .where(User.role == "student")
    ).all():
        roster.setdefault(teacher_id, set()).add(student_id)
    for teacher_id, student_id in db.execute(
        select(TeacherStudent.teacher_id, TeacherStudent.student_id)
        .join(User, User.id == TeacherStudent.student_id)
        .where(User.role == "student")
    ).all():
        roster.setdefault(teacher_id, set()).add(student_id)
    return {teacher_id: len(ids) for teacher_id, ids in roster.items()}


# ---------- 子分组（教师私有，层 3 之上的组织单位）----------

def require_owned_subgroup(db: Session, teacher_id: int, subgroup_id: int) -> TeacherSubgroup:
    """取自己的子分组：不存在或不属于该教师 → 404（不区分，避免泄露他人子分组是否存在）。"""
    subgroup = db.get(TeacherSubgroup, subgroup_id)
    if subgroup is None or subgroup.teacher_id != teacher_id:
        raise APIError(404, "SUBGROUP_NOT_FOUND", "子分组不存在")
    return subgroup


def owned_subgroup_ids(db: Session, teacher_id: int, subgroup_ids: list[int]) -> list[int]:
    """校验这批 id（去重保序）全属该教师；任一不合法整批 422（发布受众入参校验）。"""
    ids = list(dict.fromkeys(subgroup_ids))
    if not ids:
        raise APIError(422, "EMPTY_SELECTION", "未选择任何子分组")
    owned = set(db.execute(
        select(TeacherSubgroup.id).where(
            TeacherSubgroup.teacher_id == teacher_id, TeacherSubgroup.id.in_(ids)
        )
    ).scalars().all())
    if owned != set(ids):
        raise APIError(422, "SUBGROUP_NOT_FOUND", "存在不属于你的子分组")
    return ids


def subgroup_member_ids(db: Session, subgroup_id: int) -> set[int]:
    return set(db.execute(
        select(TeacherSubgroupMember.student_id).where(
            TeacherSubgroupMember.subgroup_id == subgroup_id
        )
    ).scalars().all())


def replace_subgroup_members(db: Session, subgroup_id: int, student_ids: list[int]) -> tuple[list[int], list[int]]:
    """全量替换子分组成员，**不 commit**（供调用方把审计写进同一事务）。

    返回 (added, removed)。调用方需先保证 student_ids ⊆ 当前名单。
    """
    target = set(student_ids)
    old = subgroup_member_ids(db, subgroup_id)
    added = sorted(target - old)
    removed = sorted(old - target)
    for student_id in removed:
        db.delete(db.get(TeacherSubgroupMember, (subgroup_id, student_id)))
    for student_id in added:
        db.add(TeacherSubgroupMember(subgroup_id=subgroup_id, student_id=student_id))
    return added, removed


def assignments_using_subgroup(db: Session, subgroup_id: int) -> list[Assignment]:
    """引用了该子分组的场次（删除保护用，按 id 升序）。"""
    return list(db.execute(
        select(Assignment)
        .join(AssignmentSubgroup, AssignmentSubgroup.assignment_id == Assignment.id)
        .where(AssignmentSubgroup.subgroup_id == subgroup_id)
        .order_by(Assignment.id)
    ).scalars().all())


def assignment_subgroup_ids(db: Session, assignment_id: int) -> list[int]:
    return sorted(db.execute(
        select(AssignmentSubgroup.subgroup_id).where(
            AssignmentSubgroup.assignment_id == assignment_id
        )
    ).scalars().all())


def bind_assignment_subgroups(db: Session, assignment_id: int, subgroup_ids: list[int]) -> None:
    """写入场次-子分组白名单（调用方自行 commit；入参须已校验归属）。"""
    for subgroup_id in dict.fromkeys(subgroup_ids):
        db.add(AssignmentSubgroup(assignment_id=assignment_id, subgroup_id=subgroup_id))


def clear_assignment_subgroups(db: Session, assignment_id: int) -> None:
    db.query(AssignmentSubgroup).filter(
        AssignmentSubgroup.assignment_id == assignment_id
    ).delete(synchronize_session=False)


# ---------- 发布受众（决策 1c）----------

def audience_students(db: Session, assignment: Assignment) -> list[User]:
    """本场次的受众学生：先取名单（可教组并集 ∪ 手动添加），再按受众模式收窄。

    - ``'all'``（老数据默认）→ 名单原样返回，行为与 0.3.1 一致；
    - ``'subgroup'`` → 与 assignment_subgroups 指定的、且仍属该教师的子分组成员求交集
      （限定 teacher_id 防跨教师越权；子分组删除受 409 保护，此处只会更小）。
    """
    from .stats import bound_students  # 局部导入：stats 依赖本模块的 teachable_student_ids

    students = bound_students(db, assignment.created_by)
    if (assignment.audience_mode or "all") != "subgroup":
        return students
    allowed = set(db.execute(
        select(TeacherSubgroupMember.student_id)
        .join(AssignmentSubgroup,
              AssignmentSubgroup.subgroup_id == TeacherSubgroupMember.subgroup_id)
        .join(TeacherSubgroup, TeacherSubgroup.id == TeacherSubgroupMember.subgroup_id)
        .where(AssignmentSubgroup.assignment_id == assignment.id,
               TeacherSubgroup.teacher_id == assignment.created_by)
    ).scalars().all())
    return [s for s in students if s.id in allowed]
