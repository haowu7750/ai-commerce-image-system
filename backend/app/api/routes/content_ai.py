from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.commerce import Asset, ContentVersion, ProductCard, Project
from app.models.enums import ProjectStatus, RoleName
from app.models.identity import User
from app.schemas.content_ai import (
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    ComplianceSummary,
    ContentAiHistoryItem,
    ContentAiTrace,
    ImageAnalysisRequest,
    ImageAnalysisResponse,
    SkuGenerationRequest,
    SkuGenerationResponse,
    TitleGenerationRequest,
    TitleGenerationResponse,
)
from app.services.audit import add_audit_event
from app.services.content_ai import (
    CONTENT_TYPE_BY_OPERATION,
    OPERATION_BY_CONTENT_TYPE,
    build_input_snapshot,
    generate_compliance_report,
    generate_image_analysis,
    generate_sku_suggestions,
    generate_title_candidates,
    persist_mock_content,
    trace_from_version,
)


router = APIRouter()


def require_content_operator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    if RoleName.OPERATOR.value not in current_user.role_names:
        add_audit_event(
            db,
            action="content_ai.access_denied",
            object_type="content_ai",
            actor_id=current_user.id,
            request_id=getattr(request.state, "request_id", None),
            payload_summary={
                "reason": "operator_role_required",
                "effective_roles": sorted(current_user.role_names),
                "network_used": False,
            },
            result="denied",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only operators can use content generation and compliance tools",
        )
    return current_user


ContentOperator = Annotated[User, Depends(require_content_operator)]


def _audit_rejection(
    db: Session,
    *,
    request: Request,
    actor: User,
    action: str,
    reason: str,
    project_id: str | None,
    object_id: str | None = None,
) -> None:
    add_audit_event(
        db,
        action=action,
        object_type="content_ai",
        actor_id=actor.id,
        object_id=object_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"reason": reason, "network_used": False},
        result="denied",
    )
    db.commit()


def _owned_project(
    db: Session,
    *,
    project_id: str,
    operator: User,
    request: Request,
    require_writable: bool,
) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id))
    if project is None or project.created_by_id != operator.id:
        _audit_rejection(
            db,
            request=request,
            actor=operator,
            action="content_ai.object_scope_denied",
            reason="project_not_found_or_not_owned",
            project_id=None,
            object_id=project_id,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status == ProjectStatus.ARCHIVED:
        _audit_rejection(
            db,
            request=request,
            actor=operator,
            action="content_ai.project_state_denied",
            reason="project_archived",
            project_id=project.id,
            object_id=project.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is archived; restore it before using content tools",
        )
    if require_writable and project.status == ProjectStatus.COMPLETED:
        _audit_rejection(
            db,
            request=request,
            actor=operator,
            action="content_ai.project_state_denied",
            reason="project_completed",
            project_id=project.id,
            object_id=project.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is completed; reopen it before generating new content",
        )
    return project


def _require_card(
    db: Session,
    *,
    project: Project,
    operator: User,
    request: Request,
) -> ProductCard:
    card = db.scalar(select(ProductCard).where(ProductCard.project_id == project.id))
    if card is None:
        _audit_rejection(
            db,
            request=request,
            actor=operator,
            action="content_ai.input_rejected",
            reason="product_card_required",
            project_id=project.id,
            object_id=project.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Complete the product card before using this content tool",
        )
    return card


@router.get(
    "/projects/{project_id}/history",
    response_model=list[ContentAiHistoryItem],
)
def list_content_ai_history(
    project_id: str,
    request: Request,
    operator: ContentOperator,
    db: Session = Depends(get_db),
) -> list[ContentAiHistoryItem]:
    project = _owned_project(
        db,
        project_id=project_id,
        operator=operator,
        request=request,
        require_writable=False,
    )
    content_types = tuple(CONTENT_TYPE_BY_OPERATION.values())
    versions = db.scalars(
        select(ContentVersion)
        .where(
            ContentVersion.project_id == project.id,
            ContentVersion.content_type.in_(content_types),
        )
        .order_by(ContentVersion.created_at.desc())
    ).all()
    return [
        ContentAiHistoryItem(
            id=version.id,
            project_id=version.project_id,
            operation=OPERATION_BY_CONTENT_TYPE[version.content_type],
            version_no=version.version_no,
            content=version.content_json,
            provider=version.content_json.get("provider", "unknown"),
            model=version.content_json.get("model", "unknown"),
            prompt_version=version.content_json.get("prompt_version", "unknown"),
            rule_version=version.content_json.get("rule_version", "unknown"),
            input_digest=version.input_snapshot_json.get("input_digest", ""),
            product_card_revision=version.input_snapshot_json.get("product_card_revision"),
            created_by_id=version.created_by_id,
            created_at=version.created_at,
            status=version.status.value,
            is_final=version.is_final,
        )
        for version in versions
    ]


@router.post(
    "/projects/{project_id}/image-analysis",
    response_model=ImageAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
def analyze_project_images(
    project_id: str,
    payload: ImageAnalysisRequest,
    request: Request,
    operator: ContentOperator,
    db: Session = Depends(get_db),
) -> ImageAnalysisResponse:
    project = _owned_project(
        db,
        project_id=project_id,
        operator=operator,
        request=request,
        require_writable=True,
    )
    card = _require_card(db, project=project, operator=operator, request=request)
    found_assets = db.scalars(
        select(Asset).where(
            Asset.project_id == project.id,
            Asset.id.in_(payload.selected_asset_ids),
            Asset.is_archived.is_(False),
        )
    ).all()
    assets_by_id = {asset.id: asset for asset in found_assets}
    if len(assets_by_id) != len(set(payload.selected_asset_ids)):
        _audit_rejection(
            db,
            request=request,
            actor=operator,
            action="content_ai.input_rejected",
            reason="asset_not_found_or_cross_project",
            project_id=project.id,
            object_id=project.id,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every selected image must be an active asset in the current project",
        )
    ordered_assets = [assets_by_id[asset_id] for asset_id in payload.selected_asset_ids]
    result = generate_image_analysis(card, ordered_assets, payload)
    snapshot = build_input_snapshot(
        project=project,
        card=card,
        request_payload=payload.model_dump(mode="json"),
        assets=ordered_assets,
    )
    version = persist_mock_content(
        db,
        project=project,
        card=card,
        actor=operator,
        operation="image_analysis",
        input_snapshot=snapshot,
        content=result,
        request_id=getattr(request.state, "request_id", None),
    )
    return ImageAnalysisResponse(
        trace=ContentAiTrace(**trace_from_version(version)),
        facts=result["facts"],
        judgments=result["judgments"],
        suggestions=result["suggestions"],
        uncertainties=result["uncertainties"],
        mock_limitations=result["mock_limitations"],
    )


@router.post(
    "/projects/{project_id}/title-candidates",
    response_model=TitleGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_project_title_candidates(
    project_id: str,
    payload: TitleGenerationRequest,
    request: Request,
    operator: ContentOperator,
    db: Session = Depends(get_db),
) -> TitleGenerationResponse:
    project = _owned_project(
        db,
        project_id=project_id,
        operator=operator,
        request=request,
        require_writable=True,
    )
    card = _require_card(db, project=project, operator=operator, request=request)
    result = generate_title_candidates(card, payload)
    snapshot = build_input_snapshot(
        project=project,
        card=card,
        request_payload=payload.model_dump(mode="json"),
    )
    version = persist_mock_content(
        db,
        project=project,
        card=card,
        actor=operator,
        operation="title_generation",
        input_snapshot=snapshot,
        content=result,
        request_id=getattr(request.state, "request_id", None),
    )
    return TitleGenerationResponse(
        trace=ContentAiTrace(**trace_from_version(version)),
        candidates=result["candidates"],
        excluded_terms=result["excluded_terms"],
        warnings=result["warnings"],
        overall_risk=result["overall_risk"],
        high_risk_blocked=result["high_risk_blocked"],
    )


@router.post(
    "/projects/{project_id}/sku-suggestions",
    response_model=SkuGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_project_sku_suggestions(
    project_id: str,
    payload: SkuGenerationRequest,
    request: Request,
    operator: ContentOperator,
    db: Session = Depends(get_db),
) -> SkuGenerationResponse:
    project = _owned_project(
        db,
        project_id=project_id,
        operator=operator,
        request=request,
        require_writable=True,
    )
    card = _require_card(db, project=project, operator=operator, request=request)
    result = generate_sku_suggestions(payload)
    snapshot = build_input_snapshot(
        project=project,
        card=card,
        request_payload=payload.model_dump(mode="json"),
    )
    version = persist_mock_content(
        db,
        project=project,
        card=card,
        actor=operator,
        operation="sku_generation",
        input_snapshot=snapshot,
        content=result,
        request_id=getattr(request.state, "request_id", None),
    )
    return SkuGenerationResponse(
        trace=ContentAiTrace(**trace_from_version(version)),
        suggestions=result["suggestions"],
        batch_issues=result["batch_issues"],
        protected_fields=result["protected_fields"],
        protected_fields_unchanged=result["protected_fields_unchanged"],
        can_confirm_batch=result["can_confirm_batch"],
    )


@router.post(
    "/projects/{project_id}/compliance-check",
    response_model=ComplianceCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
def check_project_content_compliance(
    project_id: str,
    payload: ComplianceCheckRequest,
    request: Request,
    operator: ContentOperator,
    db: Session = Depends(get_db),
) -> ComplianceCheckResponse:
    project = _owned_project(
        db,
        project_id=project_id,
        operator=operator,
        request=request,
        require_writable=True,
    )
    card = db.scalar(select(ProductCard).where(ProductCard.project_id == project.id))
    result = generate_compliance_report(payload)
    snapshot = build_input_snapshot(
        project=project,
        card=card,
        request_payload=payload.model_dump(mode="json"),
    )
    version = persist_mock_content(
        db,
        project=project,
        card=card,
        actor=operator,
        operation="compliance_check",
        input_snapshot=snapshot,
        content=result,
        request_id=getattr(request.state, "request_id", None),
    )
    return ComplianceCheckResponse(
        trace=ContentAiTrace(**trace_from_version(version)),
        content_type=result["content_type"],
        issues=result["issues"],
        summary=ComplianceSummary(**result["summary"]),
        overall_risk=result["overall_risk"],
        high_risk_blocked=result["high_risk_blocked"],
        requires_operator_action=result["requires_operator_action"],
        can_finalize=result["can_finalize"],
        disclaimer=result["disclaimer"],
    )
