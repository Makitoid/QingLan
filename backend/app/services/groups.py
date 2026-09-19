"""学生分组（groups / group_members）共用服务：admin 与 teacher 两端复用。

约定：
- 组由管理员创建/维护，全站共享；教师只读组定义，可调整自己绑定学生的组成员关系。
- 所有写操作单事务：先全量校验、后写入，任何一项不合法整批拒绝，不存在部分成功。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import APIError
from ..models import Group, GroupMember, User
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


def apply_membership(db: Session, student_ids: list[int], group_ids: list[int], action: str) -> int:
    """幂等增删成员关系：add 用差集插入，remove 直接删除；单事务提交。

    返回实际写入/删除的「学生×组」条数。调用方需先完成权限校验。
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
    try:
        if action == "add":
            for group_id, student_id in sorted(target - existing):
                db.add(GroupMember(group_id=group_id, student_id=student_id))
            changed = len(target - existing)
        elif action == "remove":
            for group_id, student_id in sorted(existing & target):
                db.delete(db.get(GroupMember, (group_id, student_id)))
            changed = len(existing & target)
        else:
            raise APIError(422, "VALIDATION_ERROR", "action 仅支持 add / remove")
        db.commit()
    except APIError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise APIError(409, "MEMBERSHIP_CONFLICT", "成员关系写入冲突，请重试")
    return changed


def validate_student_ids(db: Session, student_ids: list[int]) -> list[User]:
    """批量操作前的全量校验：任一 ID 不存在或非学生 → 整批 422。"""
    ids = list(dict.fromkeys(student_ids))
    if not ids:
        raise APIError(422, "EMPTY_SELECTION", "未选择任何学生")
    rows = db.execute(select(User).where(User.id.in_(ids), User.role == "student")).scalars().all()
    if {r.id for r in rows} != set(ids):
        raise APIError(422, "INVALID_STUDENT_IDS", "存在无效或非学生的用户 ID")
    return sorted(rows, key=lambda u: u.id)
