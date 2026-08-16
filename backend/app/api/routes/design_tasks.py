from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_roles
from app.models.collaboration import DesignSubmission, DesignTask
from app.models.commerce import ProductCard, Project
from app.models.enums import ProjectStatus, RoleName
from app.models.identity import User
from app.api.routes.auth import to_user_view
from app.schemas.auth import UserView
from app.schemas.collaboration import (
    DesignReviewCreate,
    DesignSubmissionCreate,
    DesignSubmissionView,
    DesignTaskCancel,
    DesignTaskCreate,
    DesignTaskStatusUpdate,
    DesignTaskView,
)
from app.services.audit import add_audit_event


router = APIRouter()


def require_active_task_project(db: Session, task: DesignTask) -> None:
    project_status = db.scalar(
        select(Project.status).where(Project.id == task.project_id)
    )
    if project_status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is archived; restore it before changing the task",
        )
    if project_status == ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is completed; reopen it before changing the task",
        )


def to_task_view(db: Session, task: DesignTask) -> DesignTaskView:
    project = db.get(Project, task.project_id)
    assignee = db.get(User, task.assigned_to_id)
    card = db.scalar(select(ProductCard).where(ProductCard.project_id == task.project_id))
    if project is None or assignee is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Design task references missing data",
        )
    return DesignTaskView(
        id=task.id,
        project_id=task.project_id,
        project_name=project.name,
        product_name=card.product_name if card else None,
        created_by_id=task.created_by_id,
        assigned_to_id=task.assigned_to_id,
        assigned_to_name=assignee.display_name,
        title=task.title,
        brief=task.brief,
        requirements=task.requirements_json,
        priority=task.priority,
        status=task.status,
        due_at=task.due_at,
        review_notes=task.review_notes,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        submissions=[
            DesignSubmissionView.model_validate(submission)
            for submission in task.submissions
        ],
    )


def accessible_task(db: Session, task_id: str, user: User) -> DesignTask:
    task = db.get(DesignTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if RoleName.ADMIN.value in user.role_names:
        return task
    if RoleName.DESIGNER.value in user.role_names and task.assigned_to_id == user.id:
        return task
    if RoleName.OPERATOR.value in user.role_names:
        project = db.scalar(
            select(Project.id).where(
                Project.id == task.project_id,
                Project.created_by_id == user.id,
            )
        )
        if project is not None:
            return task
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task access denied")


@router.get("/designers", response_model=list[UserView])
def list_designers(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)),
) -> list[UserView]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.email)).all()
    return [
        to_user_view(user)
        for user in users
        if RoleName.DESIGNER.value in user.role_names
    ]


@router.get("", response_model=list[DesignTaskView])
def list_design_tasks(
    task_status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DesignTaskView]:
    query = select(DesignTask).order_by(DesignTask.updated_at.desc())
    if task_status:
        query = query.where(DesignTask.status == task_status)
    if RoleName.ADMIN.value in current_user.role_names:
        pass
    elif RoleName.DESIGNER.value in current_user.role_names:
        query = query.where(DesignTask.assigned_to_id == current_user.id)
    elif RoleName.OPERATOR.value in current_user.role_names:
        owned_project_ids = select(Project.id).where(
            Project.created_by_id == current_user.id
        )
        query = query.where(DesignTask.project_id.in_(owned_project_ids))
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No design task role",
        )
    return [to_task_view(db, task) for task in db.scalars(query).all()]


@router.post("", response_model=DesignTaskView, status_code=status.HTTP_201_CREATED)
def create_design_task(
    payload: DesignTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> DesignTaskView:
    project = db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.created_by_id == operator.id,
            Project.status != ProjectStatus.ARCHIVED,
            Project.status != ProjectStatus.COMPLETED,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    assignee = db.get(User, payload.assigned_to_id)
    if (
        assignee is None
        or not assignee.is_active
        or RoleName.DESIGNER.value not in assignee.role_names
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assignee must be an active designer",
        )
    task = DesignTask(
        project_id=project.id,
        created_by_id=operator.id,
        assigned_to_id=assignee.id,
        title=payload.title,
        brief=payload.brief,
        requirements_json=payload.requirements,
        priority=payload.priority,
        due_at=payload.due_at,
        status="assigned",
    )
    db.add(task)
    db.flush()
    add_audit_event(
        db,
        action="design_task.created",
        object_type="design_task",
        object_id=task.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"assigned_to_id": assignee.id, "priority": task.priority},
    )
    db.commit()
    db.refresh(task)
    return to_task_view(db, task)


@router.patch("/{task_id}/status", response_model=DesignTaskView)
def update_design_task_status(
    task_id: str,
    payload: DesignTaskStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    designer: User = Depends(require_roles(RoleName.DESIGNER.value)),
) -> DesignTaskView:
    task = db.get(DesignTask, task_id)
    if task is None or task.assigned_to_id != designer.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    require_active_task_project(db, task)
    allowed = {
        "assigned": {"viewed", "in_progress", "needs_information"},
        "viewed": {"in_progress", "needs_information"},
        "in_progress": {"needs_information"},
        "rework": {"in_progress", "needs_information"},
        "needs_information": {"in_progress"},
    }
    if payload.status not in allowed.get(task.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot change task from {task.status} to {payload.status}",
        )
    if payload.status == "needs_information" and not payload.note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A question is required when requesting information",
        )
    previous_status = task.status
    task.status = payload.status
    add_audit_event(
        db,
        action="design_task.status_changed",
        object_type="design_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=designer.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "from": previous_status,
            "to": task.status,
            "note": payload.note,
        },
    )
    db.commit()
    db.refresh(task)
    return to_task_view(db, task)


@router.post(
    "/{task_id}/submissions",
    response_model=DesignTaskView,
    status_code=status.HTTP_201_CREATED,
)
def submit_design_result(
    task_id: str,
    payload: DesignSubmissionCreate,
    request: Request,
    db: Session = Depends(get_db),
    designer: User = Depends(require_roles(RoleName.DESIGNER.value)),
) -> DesignTaskView:
    task = db.get(DesignTask, task_id)
    if task is None or task.assigned_to_id != designer.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    require_active_task_project(db, task)
    if task.status not in {
        "assigned",
        "viewed",
        "in_progress",
        "rework",
        "needs_information",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task cannot accept a submission in its current state",
        )
    current_version = db.scalar(
        select(func.max(DesignSubmission.version_no)).where(
            DesignSubmission.task_id == task.id
        )
    )
    submission = DesignSubmission(
        task_id=task.id,
        submitted_by_id=designer.id,
        version_no=(current_version or 0) + 1,
        file_url=payload.file_url,
        notes=payload.notes,
    )
    db.add(submission)
    task.status = "submitted"
    task.review_notes = None
    db.flush()
    add_audit_event(
        db,
        action="design_submission.created",
        object_type="design_submission",
        object_id=submission.id,
        project_id=task.project_id,
        actor_id=designer.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"task_id": task.id, "version_no": submission.version_no},
    )
    db.commit()
    db.refresh(task)
    return to_task_view(db, task)


@router.post("/{task_id}/review", response_model=DesignTaskView)
def review_design_result(
    task_id: str,
    payload: DesignReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> DesignTaskView:
    task = accessible_task(db, task_id, operator)
    require_active_task_project(db, task)
    if task.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a submitted task can be reviewed",
        )
    task.review_notes = payload.notes
    task.reviewed_by_id = operator.id
    if payload.decision == "accepted":
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
    else:
        task.status = "rework"
        task.completed_at = None
        if payload.decision == "partial":
            task.review_notes = "部分通过，保留已认可部分并继续修改：" + payload.notes
    add_audit_event(
        db,
        action="design_task.reviewed",
        object_type="design_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"decision": payload.decision, "notes": payload.notes},
    )
    db.commit()
    db.refresh(task)
    return to_task_view(db, task)


@router.post("/{task_id}/cancel", response_model=DesignTaskView)
def cancel_design_task(
    task_id: str,
    payload: DesignTaskCancel,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> DesignTaskView:
    task = accessible_task(db, task_id, operator)
    require_active_task_project(db, task)
    if task.status in {"completed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed or cancelled tasks cannot be cancelled again",
        )
    previous_status = task.status
    task.status = "cancelled"
    task.review_notes = "任务已取消：" + payload.reason
    task.completed_at = None
    add_audit_event(
        db,
        action="design_task.cancelled",
        object_type="design_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"from": previous_status, "reason": payload.reason},
    )
    db.commit()
    db.refresh(task)
    return to_task_view(db, task)
