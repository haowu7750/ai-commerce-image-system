from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.auth import to_user_view
from app.dependencies import get_db, require_roles
from app.models.collaboration import SystemResource
from app.models.commerce import AuditEvent, Project
from app.models.enums import ProjectStatus, RoleName
from app.models.identity import Role, User, UserRole
from app.schemas.auth import CreateUserRequest, UpdateUserRequest, UserView
from app.schemas.project import ProjectView
from app.schemas.collaboration import (
    AuditEventView,
    SystemResourceCreate,
    SystemResourceUpdate,
    SystemResourceView,
)
from app.security import hash_password
from app.services.audit import add_audit_event
from app.services.project_lifecycle import restore_project, to_project_view


router = APIRouter()


@router.get("/deleted-projects", response_model=list[ProjectView])
def list_deleted_projects(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.ADMIN.value)),
) -> list[ProjectView]:
    projects = db.scalars(
        select(Project)
        .where(Project.status == ProjectStatus.ARCHIVED)
        .order_by(Project.archived_at.desc())
    ).all()
    return [to_project_view(db, project) for project in projects]


@router.post("/deleted-projects/{project_id}/restore", response_model=ProjectView)
def admin_restore_deleted_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> ProjectView:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return restore_project(
        db,
        project=project,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


def to_resource_view(resource: SystemResource) -> SystemResourceView:
    return SystemResourceView(
        id=resource.id,
        kind=resource.kind,
        name=resource.name,
        description=resource.description,
        content=resource.content_json,
        version=resource.version,
        is_active=resource.is_active,
        updated_by_id=resource.updated_by_id,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


@router.get("/users", response_model=list[UserView])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.ADMIN.value)),
) -> list[UserView]:
    return [to_user_view(user) for user in db.scalars(select(User).order_by(User.email)).all()]


@router.post("/users", response_model=UserView, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> UserView:
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    roles = db.scalars(select(Role).where(Role.name.in_([role.value for role in payload.roles]))).all()
    if len(roles) != len(set(payload.roles)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown role")
    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id, assigned_by_id=admin.id))
    add_audit_event(
        db,
        action="user.created",
        object_type="user",
        object_id=user.id,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"roles": sorted(role.name for role in roles)},
    )
    db.commit()
    db.refresh(user)
    return to_user_view(user)


@router.patch("/users/{user_id}", response_model=UserView)
def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> UserView:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrators cannot deactivate their own current account",
        )
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.roles is not None:
        desired = {role.value for role in payload.roles}
        if user.id == admin.id and RoleName.ADMIN.value not in desired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Administrators cannot remove their own admin role",
            )
        roles = db.scalars(select(Role).where(Role.name.in_(desired))).all()
        if len(roles) != len(desired):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown role",
            )
        existing_by_name = {link.role.name: link for link in user.role_links}
        for role_name, link in existing_by_name.items():
            if role_name not in desired:
                db.delete(link)
        for role in roles:
            if role.name not in existing_by_name:
                db.add(
                    UserRole(
                        user_id=user.id,
                        role_id=role.id,
                        assigned_by_id=admin.id,
                    )
                )
    add_audit_event(
        db,
        action="user.updated",
        object_type="user",
        object_id=user.id,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "display_name_changed": payload.display_name is not None,
            "active_changed": payload.is_active is not None,
            "roles_changed": payload.roles is not None,
        },
    )
    db.commit()
    db.refresh(user)
    return to_user_view(user)


@router.get("/resources", response_model=list[SystemResourceView])
def list_resources(
    kind: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.ADMIN.value)),
) -> list[SystemResourceView]:
    query = select(SystemResource).order_by(
        SystemResource.kind,
        SystemResource.name,
    )
    if kind:
        query = query.where(SystemResource.kind == kind)
    return [to_resource_view(resource) for resource in db.scalars(query).all()]


@router.post(
    "/resources",
    response_model=SystemResourceView,
    status_code=status.HTTP_201_CREATED,
)
def create_resource(
    payload: SystemResourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> SystemResourceView:
    existing = db.scalar(
        select(SystemResource.id).where(
            SystemResource.kind == payload.kind,
            func.lower(SystemResource.name) == payload.name.strip().lower(),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resource with this kind and name already exists",
        )
    resource = SystemResource(
        kind=payload.kind,
        name=payload.name.strip(),
        description=payload.description,
        content_json=payload.content,
        is_active=payload.is_active,
        updated_by_id=admin.id,
    )
    db.add(resource)
    db.flush()
    add_audit_event(
        db,
        action="system_resource.created",
        object_type="system_resource",
        object_id=resource.id,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"kind": resource.kind, "name": resource.name},
    )
    db.commit()
    db.refresh(resource)
    return to_resource_view(resource)


@router.put("/resources/{resource_id}", response_model=SystemResourceView)
def update_resource(
    resource_id: str,
    payload: SystemResourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> SystemResourceView:
    resource = db.get(SystemResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if payload.description is not None:
        resource.description = payload.description
    if payload.content is not None:
        resource.content_json = payload.content
    if payload.is_active is not None:
        resource.is_active = payload.is_active
    resource.version += 1
    resource.updated_by_id = admin.id
    add_audit_event(
        db,
        action="system_resource.updated",
        object_type="system_resource",
        object_id=resource.id,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"kind": resource.kind, "version": resource.version},
    )
    db.commit()
    db.refresh(resource)
    return to_resource_view(resource)


@router.get("/audit-events", response_model=list[AuditEventView])
def list_audit_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.ADMIN.value)),
) -> list[AuditEventView]:
    safe_limit = min(max(limit, 1), 500)
    events = db.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(safe_limit)
    ).all()
    return [
        AuditEventView(
            id=event.id,
            actor_id=event.actor_id,
            project_id=event.project_id,
            action=event.action,
            object_type=event.object_type,
            object_id=event.object_id,
            request_id=event.request_id,
            payload_summary=event.payload_summary_json,
            result=event.result,
            created_at=event.created_at,
        )
        for event in events
    ]
