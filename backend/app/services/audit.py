"""统一审计入口（AU-03）。

业务代码一律经 `log_audit()` 写日志，不得直接 insert `audit_log`。
只 add 不 commit：与触发它的写操作同属一个事务，因此必须在业务 `db.commit()` 之前调用。
日志只追加，不提供任何 UPDATE/DELETE 路径。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def log_audit(db: Session, actor: User | int | None, action: str, target_type: str,
              target_id: int | None = None, detail: dict[str, Any] | None = None) -> None:
    actor_id = actor.id if isinstance(actor, User) else actor
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
    ))
