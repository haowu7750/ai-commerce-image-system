from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.commerce import AuditEvent


def add_audit_event(
    db: Session,
    *,
    action: str,
    object_type: str,
    actor_id: str | None,
    object_id: str | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
    payload_summary: dict[str, Any] | None = None,
    result: str = "success",
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        object_type=object_type,
        actor_id=actor_id,
        object_id=object_id,
        project_id=project_id,
        request_id=request_id,
        payload_summary_json=payload_summary or {},
        result=result,
    )
    db.add(event)
    return event

