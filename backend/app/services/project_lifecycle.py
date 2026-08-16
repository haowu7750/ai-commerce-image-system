from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.collaboration import DesignTask
from app.models.commerce import Project, ProjectDeletionRecord
from app.models.enums import ProjectStatus
from app.schemas.project import ProjectView
from app.services.audit import add_audit_event


def current_deletion(
    db: Session,
    project_id: str,
) -> ProjectDeletionRecord | None:
    return db.scalar(
        select(ProjectDeletionRecord)
        .where(
            ProjectDeletionRecord.project_id == project_id,
            ProjectDeletionRecord.restored_at.is_(None),
        )
        .order_by(ProjectDeletionRecord.deleted_at.desc())
    )


def to_project_view(db: Session, project: Project) -> ProjectView:
    deletion = current_deletion(db, project.id)
    return ProjectView(
        id=project.id,
        created_by_id=project.created_by_id,
        name=project.name,
        platform=project.platform,
        store_name=project.store_name,
        category=project.category,
        source=project.source,
        status=project.status,
        archived_at=project.archived_at,
        deleted_by_id=deletion.deleted_by_id if deletion else None,
        deletion_reason=deletion.reason if deletion else None,
        status_before_delete=(deletion.status_before_delete if deletion else None),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def delete_project(
    db: Session,
    *,
    project: Project,
    actor_id: str,
    reason: str,
    request_id: str | None,
) -> ProjectView:
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is already deleted",
        )
    open_task_count = db.scalar(
        select(func.count(DesignTask.id)).where(
            DesignTask.project_id == project.id,
            DesignTask.status.notin_(["completed", "cancelled"]),
        )
    ) or 0
    if open_task_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"项目仍有 {open_task_count} 个未完成美工任务，请先完成或处理任务后再删除",
        )
    previous_status = project.status.value
    deleted_at = datetime.now(timezone.utc)
    record = ProjectDeletionRecord(
        project_id=project.id,
        deleted_by_id=actor_id,
        reason=reason.strip(),
        status_before_delete=previous_status,
        deleted_at=deleted_at,
    )
    db.add(record)
    project.status = ProjectStatus.ARCHIVED
    project.archived_at = deleted_at
    add_audit_event(
        db,
        action="project.deleted",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=actor_id,
        request_id=request_id,
        payload_summary={
            "previous_status": previous_status,
            "reason": record.reason,
            "physical_delete": False,
        },
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


def restore_project(
    db: Session,
    *,
    project: Project,
    actor_id: str,
    request_id: str | None,
) -> ProjectView:
    if project.status != ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is not deleted",
        )
    deletion = current_deletion(db, project.id)
    restored_status = ProjectStatus.DRAFT
    if deletion is not None:
        try:
            candidate = ProjectStatus(deletion.status_before_delete)
            if candidate != ProjectStatus.ARCHIVED:
                restored_status = candidate
        except ValueError:
            restored_status = ProjectStatus.DRAFT
        deletion.restored_by_id = actor_id
        deletion.restored_at = datetime.now(timezone.utc)
    project.status = restored_status
    project.archived_at = None
    add_audit_event(
        db,
        action="project.restored",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=actor_id,
        request_id=request_id,
        payload_summary={"restored_status": restored_status.value},
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)
