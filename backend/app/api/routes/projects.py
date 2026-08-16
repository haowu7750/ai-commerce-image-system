from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_roles
from app.models.collaboration import DesignTask
from app.models.commerce import Asset, ContentVersion, ProductCard, Project
from app.models.enums import (
    ContentStatus,
    ImageComplianceStatus,
    ImageQaStatus,
    ImageWorkflowStatus,
    ProjectStatus,
    RoleName,
)
from app.models.generation import ImageGenerationJob, ImageWorkflow
from app.models.identity import User
from app.schemas.project import (
    ProjectCreate,
    ProjectDeletionRequest,
    ProjectUpdate,
    ProjectView,
)
from app.schemas.catalog import (
    AssetCreate,
    AssetSelectionUpdate,
    AssetView,
    ProductCardUpsert,
    ProductCardView,
)
from app.schemas.content import (
    ContentVersionCreate,
    ContentVersionView,
    ProjectDetailView,
    ProjectResultView,
)
from app.services.audit import add_audit_event
from app.services.project_lifecycle import (
    delete_project as delete_project_service,
    restore_project as restore_project_service,
    to_project_view,
)


router = APIRouter()


PRODUCT_FIELD_RULES = (
    ("product_name", "商品名称", "无法建立稳定的商品身份", ["商品事实确认", "标题与生图"]),
    ("color", "颜色", "AI 生图缺少颜色保真依据", ["AI 生图"]),
    ("material", "材质", "AI 生图缺少质感和反光保真依据", ["AI 生图"]),
    ("selling_points", "核心卖点", "标题和详情文案缺少可验证卖点", ["标题生成", "内容生成"]),
    ("specs", "规格", "SKU 和尺寸表达可能不完整", ["SKU 生成", "美工任务"]),
    ("must_not_change", "禁改项", "无法明确约束 AI 和美工不得改变的商品事实", ["AI 生图", "美工任务"]),
)


def _card_field_value(card: ProductCard, field: str) -> Any:
    if field == "product_name":
        return card.product_name
    if field in {"color", "material"}:
        return card.facts_json.get(field)
    if field == "selling_points":
        return card.selling_points_json
    if field == "specs":
        return card.specs_json
    if field == "must_not_change":
        return card.constraints_json.get("must_not_change")
    return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def product_card_gaps(card: ProductCard) -> list[dict[str, Any]]:
    return [
        {
            "field": field,
            "label": label,
            "impact": impact,
            "required_for": required_for,
        }
        for field, label, impact, required_for in PRODUCT_FIELD_RULES
        if _is_blank(_card_field_value(card, field))
    ]


def product_card_completeness(card: ProductCard) -> float:
    missing = len(product_card_gaps(card))
    return round((len(PRODUCT_FIELD_RULES) - missing) / len(PRODUCT_FIELD_RULES) * 100, 1)


def to_product_card_view(card: ProductCard) -> ProductCardView:
    return ProductCardView(
        id=card.id,
        project_id=card.project_id,
        product_name=card.product_name,
        brand=card.brand,
        current_title=card.current_title,
        facts=card.facts_json,
        selling_points=card.selling_points_json,
        specs=card.specs_json,
        constraints=card.constraints_json,
        field_sources=card.field_sources_json,
        missing_fields=product_card_gaps(card),
        completeness_percent=card.completeness_percent,
        revision=card.revision,
        confirmed_by_id=card.confirmed_by_id,
        confirmed_at=card.confirmed_at,
    )


def to_asset_view(
    asset: Asset, *, archive_blockers: list[str] | None = None
) -> AssetView:
    metadata = asset.metadata_json or {}
    return AssetView(
        id=asset.id,
        project_id=asset.project_id,
        asset_type=asset.asset_type,
        source=asset.source,
        storage_key=asset.storage_key,
        file_url=asset.file_url,
        file_hash=asset.file_hash,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        usage_note=str(metadata.get("usage_note", "")),
        selected_for_generation=bool(metadata.get("selected_for_generation", False)),
        is_archived=asset.is_archived,
        archive_blockers=archive_blockers or [],
        metadata=metadata,
        created_at=asset.created_at,
    )


def _contains_asset_id(value: Any, asset_id: str) -> bool:
    if isinstance(value, str):
        return value == asset_id or asset_id in value
    if isinstance(value, dict):
        return any(_contains_asset_id(item, asset_id) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_asset_id(item, asset_id) for item in value)
    return False


def asset_reference_blockers(db: Session, asset: Asset) -> list[str]:
    blockers: list[str] = []
    generation_jobs = db.scalars(
        select(ImageGenerationJob).where(ImageGenerationJob.project_id == asset.project_id)
    ).all()
    if any(asset.id in (job.input_asset_ids_json or []) for job in generation_jobs):
        blockers.append("该素材已被 AI 生图任务引用，需保留输入快照")

    final_versions = db.scalars(
        select(ContentVersion).where(
            ContentVersion.project_id == asset.project_id,
            ContentVersion.is_final.is_(True),
        )
    ).all()
    if any(_contains_asset_id(version.content_json, asset.id) for version in final_versions):
        blockers.append("该素材已被最终内容引用")

    design_tasks = db.scalars(
        select(DesignTask).where(DesignTask.project_id == asset.project_id)
    ).all()
    if any(
        _contains_asset_id(task.requirements_json, asset.id)
        or _contains_asset_id(task.brief, asset.id)
        for task in design_tasks
    ):
        blockers.append("该素材已被美工任务引用")
    return blockers


def to_content_view(version: ContentVersion) -> ContentVersionView:
    return ContentVersionView(
        id=version.id,
        project_id=version.project_id,
        content_type=version.content_type,
        version_no=version.version_no,
        content=version.content_json,
        source_kind=version.source_kind,
        created_by_id=version.created_by_id,
        status=version.status,
        is_final=version.is_final,
        finalized_by_id=version.finalized_by_id,
        finalized_at=version.finalized_at,
        created_at=version.created_at,
    )


def owned_project(
    db: Session,
    project_id: str,
    user_id: str,
    *,
    allow_archived: bool = False,
    require_writable: bool = False,
) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.created_by_id == user_id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status == ProjectStatus.ARCHIVED and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is archived; restore it before making changes",
        )
    if project.status == ProjectStatus.COMPLETED and require_writable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is completed; reopen it before making changes",
        )
    return project


@router.get("", response_model=list[ProjectView])
def list_projects(
    bucket: Literal["all", "draft", "in_progress", "completed", "deleted"] = "all",
    archived: bool | None = None,
    q: str | None = Query(default=None, max_length=200),
    platform: str | None = Query(default=None, max_length=64),
    store_name: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[ProjectView]:
    if archived is True:
        bucket = "deleted"
    query = select(Project).where(Project.created_by_id == operator.id)
    if bucket == "draft":
        query = query.where(Project.status == ProjectStatus.DRAFT)
    elif bucket == "completed":
        query = query.where(Project.status == ProjectStatus.COMPLETED)
    elif bucket == "deleted":
        query = query.where(Project.status == ProjectStatus.ARCHIVED)
    elif bucket == "in_progress":
        query = query.where(
            Project.status.notin_(
                [ProjectStatus.DRAFT, ProjectStatus.COMPLETED, ProjectStatus.ARCHIVED]
            )
        )
    else:
        query = query.where(Project.status != ProjectStatus.ARCHIVED)
    search_text = (q or "").strip()
    if search_text:
        pattern = f"%{search_text}%"
        query = query.where(
            or_(
                Project.name.ilike(pattern),
                Project.store_name.ilike(pattern),
                Project.category.ilike(pattern),
            )
        )
    if platform and platform.strip():
        query = query.where(Project.platform == platform.strip())
    if store_name and store_name.strip():
        query = query.where(Project.store_name.ilike(f"%{store_name.strip()}%"))
    if category and category.strip():
        query = query.where(Project.category.ilike(f"%{category.strip()}%"))
    projects = db.scalars(query.order_by(Project.updated_at.desc())).all()
    return [to_project_view(db, project) for project in projects]


@router.post("", response_model=ProjectView, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = Project(
        created_by_id=operator.id,
        name=payload.name,
        platform=payload.platform,
        store_name=payload.store_name,
        category=payload.category,
        status=ProjectStatus.DRAFT,
    )
    db.add(project)
    db.flush()
    add_audit_event(
        db,
        action="project.created",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


@router.patch("/{project_id}", response_model=ProjectView)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(project, field, value or None if field == "category" else value)
    add_audit_event(
        db,
        action="project.updated",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"changed_fields": sorted(changes)},
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


@router.post("/{project_id}/delete", response_model=ProjectView)
def delete_project(
    project_id: str,
    payload: ProjectDeletionRequest,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(
        db,
        project_id,
        operator.id,
        allow_archived=True,
    )
    return delete_project_service(
        db,
        project=project,
        actor_id=operator.id,
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{project_id}/restore", response_model=ProjectView)
def restore_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(
        db,
        project_id,
        operator.id,
        allow_archived=True,
    )
    return restore_project_service(
        db,
        project=project,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{project_id}/start", response_model=ProjectView)
def start_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(db, project_id, operator.id)
    if project.status != ProjectStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft project can be started",
        )
    project.status = ProjectStatus.IN_PROGRESS
    add_audit_event(
        db,
        action="project.started",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"from": "draft", "to": "in_progress"},
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


def project_completion_blockers(db: Session, project: Project) -> list[str]:
    blockers: list[str] = []
    if project.product_card is None or project.product_card.confirmed_at is None:
        blockers.append("商品信息卡尚未由运营确认")
    final_title = db.scalar(
        select(ContentVersion.id).where(
            ContentVersion.project_id == project.id,
            ContentVersion.content_type == "title",
            ContentVersion.is_final.is_(True),
        )
    )
    if final_title is None:
        blockers.append("最终标题尚未确认")
    open_tasks = db.scalar(
        select(func.count(DesignTask.id)).where(
            DesignTask.project_id == project.id,
            DesignTask.status.notin_(["completed", "cancelled"]),
        )
    ) or 0
    if open_tasks:
        blockers.append(f"仍有 {open_tasks} 个美工任务未完成")
    risky_workflow = db.scalar(
        select(ImageWorkflow.id).where(
            ImageWorkflow.project_id == project.id,
            ImageWorkflow.compliance_status.in_(
                [ImageComplianceStatus.HIGH_OPEN, ImageComplianceStatus.MEDIUM_OPEN]
            ),
        )
    )
    if risky_workflow is not None:
        blockers.append("仍有未处理的生图合规风险")
    return blockers


@router.post("/{project_id}/complete", response_model=ProjectView)
def complete_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(db, project_id, operator.id)
    if project.status != ProjectStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an in-progress project can be completed",
        )
    blockers = project_completion_blockers(db, project)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="项目尚不能完成：" + "；".join(blockers),
        )
    project.status = ProjectStatus.COMPLETED
    add_audit_event(
        db,
        action="project.completed",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


@router.post("/{project_id}/reopen", response_model=ProjectView)
def reopen_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectView:
    project = owned_project(db, project_id, operator.id)
    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a completed project can be reopened",
        )
    project.status = ProjectStatus.IN_PROGRESS
    add_audit_event(
        db,
        action="project.reopened",
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(project)
    return to_project_view(db, project)


@router.get("/{project_id}", response_model=ProjectDetailView)
def get_project_detail(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectDetailView:
    project = owned_project(db, project_id, operator.id)
    assets = db.scalars(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.is_archived.is_(False))
        .order_by(Asset.created_at.desc())
    ).all()
    versions = db.scalars(
        select(ContentVersion)
        .where(ContentVersion.project_id == project.id)
        .order_by(ContentVersion.content_type, ContentVersion.version_no.desc())
    ).all()
    return ProjectDetailView(
        project=to_project_view(db, project),
        product_card=(
            to_product_card_view(project.product_card)
            if project.product_card is not None
            else None
        ),
        assets=[
            to_asset_view(asset, archive_blockers=asset_reference_blockers(db, asset))
            for asset in assets
        ],
        content_versions=[to_content_view(version) for version in versions],
    )


@router.get("/{project_id}/product-card", response_model=ProductCardView)
def get_product_card(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProductCardView:
    project = owned_project(db, project_id, operator.id)
    if project.product_card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product card not found")
    return to_product_card_view(project.product_card)


@router.get("/{project_id}/assets", response_model=list[AssetView])
def list_assets(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[AssetView]:
    project = owned_project(db, project_id, operator.id)
    assets = db.scalars(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.is_archived.is_(False))
        .order_by(Asset.created_at.desc())
    ).all()
    return [
        to_asset_view(asset, archive_blockers=asset_reference_blockers(db, asset))
        for asset in assets
    ]


@router.get(
    "/{project_id}/content-versions",
    response_model=list[ContentVersionView],
)
def list_content_versions(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[ContentVersionView]:
    project = owned_project(db, project_id, operator.id)
    versions = db.scalars(
        select(ContentVersion)
        .where(ContentVersion.project_id == project.id)
        .order_by(ContentVersion.content_type, ContentVersion.version_no.desc())
    ).all()
    return [to_content_view(version) for version in versions]


@router.post(
    "/{project_id}/content-versions",
    response_model=ContentVersionView,
    status_code=status.HTTP_201_CREATED,
)
def create_content_version(
    project_id: str,
    payload: ContentVersionCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ContentVersionView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    current_version = db.scalar(
        select(func.max(ContentVersion.version_no)).where(
            ContentVersion.project_id == project.id,
            ContentVersion.content_type == payload.content_type,
        )
    )
    version = ContentVersion(
        project_id=project.id,
        content_type=payload.content_type,
        version_no=(current_version or 0) + 1,
        content_json=payload.content,
        source_kind=payload.source_kind,
        created_by_id=operator.id,
        status=ContentStatus.PENDING_OPERATOR_CONFIRMATION,
        input_snapshot_json={
            "product_card_revision": (
                project.product_card.revision if project.product_card else None
            )
        },
    )
    db.add(version)
    db.flush()
    add_audit_event(
        db,
        action="content_version.created",
        object_type="content_version",
        object_id=version.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "content_type": version.content_type,
            "version_no": version.version_no,
            "source_kind": version.source_kind,
        },
    )
    db.commit()
    db.refresh(version)
    return to_content_view(version)


@router.post(
    "/{project_id}/content-versions/{version_id}/finalize",
    response_model=ContentVersionView,
)
def finalize_content_version(
    project_id: str,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ContentVersionView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    version = db.scalar(
        select(ContentVersion).where(
            ContentVersion.id == version_id,
            ContentVersion.project_id == project.id,
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    risk_level = str(
        version.content_json.get(
            "risk_level",
            version.content_json.get("compliance_status", ""),
        )
    ).lower()
    if risk_level in {"high", "high_open", "blocked"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="High-risk content cannot be finalized",
        )
    previous_finals = db.scalars(
        select(ContentVersion).where(
            ContentVersion.project_id == project.id,
            ContentVersion.content_type == version.content_type,
            ContentVersion.is_final.is_(True),
            ContentVersion.id != version.id,
        )
    ).all()
    for previous in previous_finals:
        previous.is_final = False
        previous.status = ContentStatus.INVALIDATED
        previous.invalidated_at = datetime.now(timezone.utc)
    version.is_final = True
    version.status = ContentStatus.FINAL
    version.finalized_by_id = operator.id
    version.finalized_at = datetime.now(timezone.utc)
    add_audit_event(
        db,
        action="content_version.finalized",
        object_type="content_version",
        object_id=version.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "content_type": version.content_type,
            "version_no": version.version_no,
        },
    )
    db.commit()
    db.refresh(version)
    return to_content_view(version)


@router.get("/{project_id}/result-summary", response_model=ProjectResultView)
def get_result_summary(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectResultView:
    project = owned_project(db, project_id, operator.id)
    final_versions = db.scalars(
        select(ContentVersion).where(
            ContentVersion.project_id == project.id,
            ContentVersion.is_final.is_(True),
        )
    ).all()
    task_counts = dict(
        db.execute(
            select(DesignTask.status, func.count(DesignTask.id))
            .where(DesignTask.project_id == project.id)
            .group_by(DesignTask.status)
        ).all()
    )
    blockers: list[str] = []
    if project.product_card is None or project.product_card.confirmed_at is None:
        blockers.append("商品信息卡尚未由运营确认")
    if not any(version.content_type == "title" for version in final_versions):
        blockers.append("最终标题尚未确认")
    if task_counts.get("rework", 0) or task_counts.get("submitted", 0):
        blockers.append("仍有美工结果待处理")
    return ProjectResultView(
        project=ProjectView.model_validate(project),
        product_card_confirmed=(
            project.product_card is not None
            and project.product_card.confirmed_at is not None
        ),
        final_content={
            version.content_type: version.content_json for version in final_versions
        },
        accepted_design_count=task_counts.get("completed", 0),
        open_design_count=sum(
            count
            for task_status, count in task_counts.items()
            if task_status not in {"completed", "cancelled"}
        ),
        blockers=blockers,
    )


@router.put("/{project_id}/product-card", response_model=ProductCardView)
def upsert_product_card(
    project_id: str,
    payload: ProductCardUpsert,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProductCardView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    card = project.product_card
    was_confirmed = card is not None and card.confirmed_at is not None
    if card is None:
        card = ProductCard(project_id=project.id, product_name=payload.product_name)
        db.add(card)
    else:
        card.revision += 1
    card.product_name = payload.product_name
    card.brand = payload.brand
    card.current_title = payload.current_title
    card.facts_json = payload.facts
    card.selling_points_json = payload.selling_points
    card.specs_json = payload.specs
    card.constraints_json = payload.constraints
    known_sources = dict(payload.field_sources)
    for field, _label, _impact, _required_for in PRODUCT_FIELD_RULES:
        if not _is_blank(_card_field_value(card, field)):
            known_sources.setdefault(field, "operator")
    if card.brand:
        known_sources.setdefault("brand", "operator")
    if card.current_title:
        known_sources.setdefault("current_title", "operator")
    if not _is_blank(card.facts_json.get("origin")):
        known_sources.setdefault("origin", "operator")
    card.field_sources_json = known_sources
    card.completeness_percent = product_card_completeness(card)
    card.confirmed_by_id = None
    card.confirmed_at = None
    if was_confirmed:
        db.execute(
            update(ImageWorkflow)
            .where(
                ImageWorkflow.project_id == project.id,
                ImageWorkflow.status.notin_(
                    [ImageWorkflowStatus.STALE, ImageWorkflowStatus.CANCELLED]
                ),
            )
            .values(
                status=ImageWorkflowStatus.STALE,
                stale_reason="product_card_changed",
                qa_status=ImageQaStatus.INVALIDATED,
                compliance_status=ImageComplianceStatus.INVALIDATED,
                confirmed_by_id=None,
                confirmed_at=None,
                revision=ImageWorkflow.revision + 1,
            )
        )
    db.flush()
    add_audit_event(
        db,
        action="product_card.saved",
        object_type="product_card",
        object_id=card.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"revision": card.revision, "invalidated_workflows": was_confirmed},
    )
    db.commit()
    db.refresh(card)
    return to_product_card_view(card)


@router.post("/{project_id}/product-card/confirm", response_model=ProductCardView)
def confirm_product_card(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProductCardView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    card = project.product_card
    if card is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product card is missing")
    card.confirmed_by_id = operator.id
    card.confirmed_at = datetime.now(timezone.utc)
    add_audit_event(
        db,
        action="product_card.confirmed",
        object_type="product_card",
        object_id=card.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"revision": card.revision},
    )
    db.commit()
    db.refresh(card)
    return to_product_card_view(card)


@router.post("/{project_id}/assets", response_model=AssetView, status_code=status.HTTP_201_CREATED)
def create_asset(
    project_id: str,
    payload: AssetCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> AssetView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    asset = Asset(
        project_id=project.id,
        uploaded_by_id=operator.id,
        asset_type=payload.asset_type,
        source="upload",
        storage_key=payload.storage_key,
        file_url=payload.file_url,
        file_hash=payload.file_hash,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        width=payload.width,
        height=payload.height,
        metadata_json={
            **{
                key: value
                for key, value in payload.metadata.items()
                if key
                not in {
                    "selected_for_generation",
                    "archived_at",
                    "archived_by_id",
                }
            },
            "usage_note": payload.usage_note.strip(),
            "selected_for_generation": False,
        },
    )
    db.add(asset)
    db.flush()
    add_audit_event(
        db,
        action="asset.created",
        object_type="asset",
        object_id=asset.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"asset_type": asset.asset_type.value},
    )
    db.commit()
    db.refresh(asset)
    return to_asset_view(asset)


@router.put("/{project_id}/assets/{asset_id}/selection", response_model=AssetView)
def update_asset_selection(
    project_id: str,
    asset_id: str,
    payload: AssetSelectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> AssetView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    asset = db.scalar(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.project_id == project.id,
            Asset.is_archived.is_(False),
        )
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    metadata = dict(asset.metadata_json or {})
    metadata["selected_for_generation"] = payload.selected_for_generation
    asset.metadata_json = metadata
    add_audit_event(
        db,
        action="asset.generation_selection_updated",
        object_type="asset",
        object_id=asset.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"selected_for_generation": payload.selected_for_generation},
    )
    db.commit()
    db.refresh(asset)
    return to_asset_view(
        asset, archive_blockers=asset_reference_blockers(db, asset)
    )


@router.post("/{project_id}/assets/{asset_id}/archive", response_model=AssetView)
def archive_asset(
    project_id: str,
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> AssetView:
    project = owned_project(db, project_id, operator.id, require_writable=True)
    asset = db.scalar(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.project_id == project.id,
            Asset.is_archived.is_(False),
        )
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    blockers = asset_reference_blockers(db, asset)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="素材不能归档：" + "；".join(blockers),
        )
    metadata = dict(asset.metadata_json or {})
    metadata.update(
        {
            "selected_for_generation": False,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "archived_by_id": operator.id,
        }
    )
    asset.metadata_json = metadata
    asset.is_archived = True
    add_audit_event(
        db,
        action="asset.archived",
        object_type="asset",
        object_id=asset.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"asset_type": asset.asset_type.value},
    )
    db.commit()
    db.refresh(asset)
    return to_asset_view(asset)
