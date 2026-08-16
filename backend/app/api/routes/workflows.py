from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_roles
from app.models.commerce import Asset, ProductCard, Project
from app.models.enums import (
    AssetType,
    ImageComplianceStatus,
    ImageJobStatus,
    ImageQaStatus,
    ImageWorkflowStatus,
    ProjectStatus,
    RoleName,
)
from app.models.generation import ImageGenerationJob, ImageWorkflow
from app.models.identity import User
from app.schemas.generation import (
    ConfirmImageWorkflow,
    ImageWorkflowCreate,
    ImageWorkflowTransition,
    ImageWorkflowView,
    ManualImageReviewCreate,
    MockImageChecksCreate,
    ResolveMediumRisk,
)
from app.services.audit import add_audit_event
from app.services.workflow import apply_workflow_transition


router = APIRouter()


def to_workflow_view(workflow: ImageWorkflow) -> ImageWorkflowView:
    return ImageWorkflowView(
        id=workflow.id,
        project_id=workflow.project_id,
        created_by_id=workflow.created_by_id,
        status=workflow.status,
        product_type=workflow.product_type_json,
        scene_plan=workflow.scene_plan_json,
        selected_scene=workflow.selected_scene_json,
        approved_prompt=workflow.approved_prompt,
        qa_status=workflow.qa_status,
        compliance_status=workflow.compliance_status,
        qa_report=workflow.qa_report_json,
        compliance_report=workflow.compliance_report_json,
        confirmed_by_id=workflow.confirmed_by_id,
        confirmed_at=workflow.confirmed_at,
        revision=workflow.revision,
        stale_reason=workflow.stale_reason,
        failure_code=workflow.failure_code,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def owned_workflow(db: Session, workflow_id: str, user_id: str) -> ImageWorkflow:
    workflow = db.scalar(
        select(ImageWorkflow).where(
            ImageWorkflow.id == workflow_id,
            ImageWorkflow.created_by_id == user_id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


def require_revision(workflow: ImageWorkflow, expected_revision: int) -> None:
    if workflow.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow revision changed; current revision is {workflow.revision}",
        )


def require_active_project(db: Session, workflow: ImageWorkflow) -> None:
    project_status = db.scalar(
        select(Project.status).where(Project.id == workflow.project_id)
    )
    if project_status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is archived; restore it before continuing the workflow",
        )
    if project_status == ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is completed; reopen it before continuing the workflow",
        )


def reject_confirmation(
    db: Session,
    *,
    workflow: ImageWorkflow,
    operator: User,
    request: Request,
    code: str,
    detail: str,
) -> None:
    add_audit_event(
        db,
        action="image_workflow.confirmation_denied",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"reason_code": code},
        result="denied",
    )
    db.commit()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("", response_model=ImageWorkflowView, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: ImageWorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
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
    workflow = ImageWorkflow(project_id=project.id, created_by_id=operator.id)
    db.add(workflow)
    db.flush()
    add_audit_event(
        db,
        action="image_workflow.created",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)


@router.get("", response_model=list[ImageWorkflowView])
def list_workflows(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[ImageWorkflowView]:
    query = (
        select(ImageWorkflow)
        .where(ImageWorkflow.created_by_id == operator.id)
        .order_by(ImageWorkflow.updated_at.desc())
    )
    if project_id:
        query = query.where(ImageWorkflow.project_id == project_id)
    return [
        to_workflow_view(workflow)
        for workflow in db.scalars(query).all()
    ]


@router.get("/{workflow_id}", response_model=ImageWorkflowView)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    return to_workflow_view(owned_workflow(db, workflow_id, operator.id))


@router.patch("/{workflow_id}/transition", response_model=ImageWorkflowView)
def transition_workflow(
    workflow_id: str,
    payload: ImageWorkflowTransition,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    workflow = owned_workflow(db, workflow_id, operator.id)
    require_active_project(db, workflow)
    old_status = workflow.status
    apply_workflow_transition(workflow, payload)
    add_audit_event(
        db,
        action="image_workflow.transitioned",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"from": old_status.value, "to": workflow.status.value},
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)


@router.post("/{workflow_id}/mock-checks", response_model=ImageWorkflowView)
def run_mock_checks(
    workflow_id: str,
    payload: MockImageChecksCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    """Run deterministic stage-1 checks; this never calls a vision or text model."""
    workflow = owned_workflow(db, workflow_id, operator.id)
    require_active_project(db, workflow)
    require_revision(workflow, payload.expected_revision)
    if workflow.status != ImageWorkflowStatus.CANDIDATE_READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow is not candidate_ready",
        )

    workflow.status = ImageWorkflowStatus.QA_PENDING
    workflow.qa_status = ImageQaStatus.PENDING
    workflow.compliance_status = ImageComplianceStatus.CHECKING
    workflow.revision += 1
    add_audit_event(
        db,
        action="image_workflow.mock_checks_started",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"mode": "mock"},
    )
    db.commit()

    now = datetime.now(timezone.utc).isoformat()
    qa_passed = payload.scenario != "qa_failed"
    workflow.qa_status = ImageQaStatus.PASSED if qa_passed else ImageQaStatus.FAILED
    workflow.qa_report_json = {
        "mode": "mock",
        "scenario": payload.scenario,
        "checked_at": now,
        "authenticity": "passed" if qa_passed else "failed",
        "thumbnail": "passed" if qa_passed else "failed",
        "note": "Deterministic fixture; not a real visual assessment.",
    }

    if payload.scenario == "qa_failed":
        workflow.compliance_status = ImageComplianceStatus.CLEAR
        workflow.status = ImageWorkflowStatus.QA_FAILED
        risks: list[dict[str, str]] = []
    elif payload.scenario == "medium_risk":
        workflow.compliance_status = ImageComplianceStatus.MEDIUM_OPEN
        workflow.status = ImageWorkflowStatus.COMPLIANCE_BLOCKED
        risks = [{"severity": "medium", "code": "MOCK_MEDIUM_RISK"}]
    elif payload.scenario == "high_risk":
        workflow.compliance_status = ImageComplianceStatus.HIGH_OPEN
        workflow.status = ImageWorkflowStatus.COMPLIANCE_BLOCKED
        risks = [{"severity": "high", "code": "MOCK_HIGH_RISK"}]
    else:
        workflow.compliance_status = ImageComplianceStatus.CLEAR
        workflow.status = ImageWorkflowStatus.AWAITING_OPERATOR_CONFIRMATION
        risks = []

    workflow.compliance_report_json = {
        "mode": "mock",
        "scenario": payload.scenario,
        "checked_at": now,
        "risks": risks,
        "note": "Deterministic fixture; not a real compliance assessment.",
    }
    workflow.revision += 1
    add_audit_event(
        db,
        action="image_workflow.mock_checks_completed",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "mode": "mock",
            "qa_status": workflow.qa_status.value,
            "compliance_status": workflow.compliance_status.value,
        },
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)


@router.post("/{workflow_id}/manual-review", response_model=ImageWorkflowView)
def submit_manual_image_review(
    workflow_id: str,
    payload: ManualImageReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    """Persist the operator's actual visual review without pretending to be AI QA."""
    workflow = owned_workflow(db, workflow_id, operator.id)
    require_active_project(db, workflow)
    require_revision(workflow, payload.expected_revision)
    if workflow.status != ImageWorkflowStatus.CANDIDATE_READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow is not candidate_ready",
        )
    checks = {
        "product_facts_match": payload.product_facts_match,
        "geometry_and_count_match": payload.geometry_and_count_match,
        "logo_text_and_personalization_match": (
            payload.logo_text_and_personalization_match
        ),
        "thumbnail_readable": payload.thumbnail_readable,
    }
    passed = all(checks.values())
    now = datetime.now(timezone.utc).isoformat()
    workflow.qa_status = ImageQaStatus.PASSED if passed else ImageQaStatus.FAILED
    workflow.qa_report_json = {
        "mode": "operator_manual_review",
        "reviewer_id": operator.id,
        "reviewed_at": now,
        "checks": checks,
        "notes": payload.notes,
    }
    if not passed:
        workflow.compliance_status = ImageComplianceStatus.UNCHECKED
        workflow.status = ImageWorkflowStatus.QA_FAILED
    elif payload.compliance_risk == "high":
        workflow.compliance_status = ImageComplianceStatus.HIGH_OPEN
        workflow.status = ImageWorkflowStatus.COMPLIANCE_BLOCKED
    elif payload.compliance_risk == "medium":
        workflow.compliance_status = ImageComplianceStatus.MEDIUM_OPEN
        workflow.status = ImageWorkflowStatus.COMPLIANCE_BLOCKED
    else:
        workflow.compliance_status = ImageComplianceStatus.CLEAR
        workflow.status = ImageWorkflowStatus.AWAITING_OPERATOR_CONFIRMATION
    workflow.compliance_report_json = {
        "mode": "operator_manual_review",
        "reviewer_id": operator.id,
        "reviewed_at": now,
        "declared_risk": payload.compliance_risk,
        "notes": payload.notes,
        "disclaimer": "运营人工初审记录，不替代平台审核或法律意见。",
    }
    workflow.revision += 1
    add_audit_event(
        db,
        action="image_workflow.manual_review_submitted",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "qa_status": workflow.qa_status.value,
            "compliance_status": workflow.compliance_status.value,
            "all_visual_checks_passed": passed,
        },
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)


@router.post("/{workflow_id}/resolve-medium-risk", response_model=ImageWorkflowView)
def resolve_medium_risk(
    workflow_id: str,
    payload: ResolveMediumRisk,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    workflow = owned_workflow(db, workflow_id, operator.id)
    require_active_project(db, workflow)
    require_revision(workflow, payload.expected_revision)
    if (
        workflow.status != ImageWorkflowStatus.COMPLIANCE_BLOCKED
        or workflow.compliance_status != ImageComplianceStatus.MEDIUM_OPEN
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only medium_open risk can be resolved with a retained reason",
        )
    report = dict(workflow.compliance_report_json)
    report["resolution"] = {
        "reason": payload.reason,
        "resolved_by_id": operator.id,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    workflow.compliance_report_json = report
    workflow.compliance_status = ImageComplianceStatus.MEDIUM_RESOLVED
    workflow.status = ImageWorkflowStatus.AWAITING_OPERATOR_CONFIRMATION
    workflow.revision += 1
    add_audit_event(
        db,
        action="image_workflow.medium_risk_resolved",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"reason_recorded": True},
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)


@router.post("/{workflow_id}/confirm", response_model=ImageWorkflowView)
def confirm_workflow(
    workflow_id: str,
    payload: ConfirmImageWorkflow,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageWorkflowView:
    workflow = owned_workflow(db, workflow_id, operator.id)
    require_active_project(db, workflow)
    require_revision(workflow, payload.expected_revision)
    if workflow.status != ImageWorkflowStatus.AWAITING_OPERATOR_CONFIRMATION:
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="INVALID_STATE",
            detail="Workflow is not awaiting operator confirmation",
        )
    if workflow.qa_status != ImageQaStatus.PASSED:
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="QA_NOT_PASSED",
            detail="Authenticity and thumbnail checks must pass",
        )
    if workflow.compliance_status not in {
        ImageComplianceStatus.CLEAR,
        ImageComplianceStatus.MEDIUM_RESOLVED,
    }:
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="COMPLIANCE_BLOCKED",
            detail="Open compliance risk blocks confirmation",
        )

    card = db.scalar(select(ProductCard).where(ProductCard.project_id == workflow.project_id))
    if card is None or card.confirmed_at is None:
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="PRODUCT_CARD_STALE",
            detail="Product card is not currently confirmed",
        )
    job = db.scalar(
        select(ImageGenerationJob)
        .where(
            ImageGenerationJob.workflow_id == workflow.id,
            ImageGenerationJob.status == ImageJobStatus.SUCCEEDED,
        )
        .order_by(ImageGenerationJob.finished_at.desc())
    )
    if job is None or job.model != "gpt-image-2":
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="CANDIDATE_INVALID",
            detail="A successful gpt-image-2 candidate is required",
        )
    assets = db.scalars(
        select(Asset).where(
            Asset.id.in_(set(job.input_asset_ids_json)),
            Asset.project_id == workflow.project_id,
            Asset.is_archived.is_(False),
        )
    ).all()
    if not any(
        asset.asset_type == AssetType.PRODUCT_REFERENCE and asset.file_hash
        for asset in assets
    ):
        reject_confirmation(
            db,
            workflow=workflow,
            operator=operator,
            request=request,
            code="PRODUCT_REFERENCE_STALE",
            detail="A current hashed product reference is required",
        )

    workflow.status = ImageWorkflowStatus.OPERATOR_CONFIRMED
    workflow.confirmed_by_id = operator.id
    workflow.confirmed_at = datetime.now(timezone.utc)
    workflow.revision += 1
    add_audit_event(
        db,
        action="image_workflow.operator_confirmed",
        object_type="image_workflow",
        object_id=workflow.id,
        project_id=workflow.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "publish_event_created": False,
            "erp_writeback_event_created": False,
            "content_finalized": False,
        },
    )
    db.commit()
    db.refresh(workflow)
    return to_workflow_view(workflow)
