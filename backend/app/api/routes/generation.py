from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_model_provider, require_roles
from app.models.commerce import Asset, ProductCard
from app.models.enums import AssetType, ImageWorkflowStatus, ProjectStatus, RoleName
from app.models.commerce import Project
from app.models.generation import ImageGenerationJob, ImageWorkflow
from app.models.identity import User
from app.providers.base import ModelProvider
from app.schemas.generation import ImageGenerationCreate, ImageJobView, ImageOutputView
from app.services.image_generation import create_and_run_image_job


router = APIRouter()


def to_job_view(job: ImageGenerationJob) -> ImageJobView:
    return ImageJobView(
        id=job.id,
        project_id=job.project_id,
        workflow_id=job.workflow_id,
        created_by_id=job.created_by_id,
        operation=job.operation,
        status=job.status,
        provider=job.provider,
        model=job.model,
        prompt=job.prompt,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        outputs=[
            ImageOutputView(
                id=output.id,
                sequence_no=output.sequence_no,
                mime_type=output.mime_type,
                provider_url=output.provider_url,
                b64_json=output.b64_json,
                revised_prompt=output.revised_prompt,
            )
            for output in job.outputs
        ],
    )


@router.post("", response_model=ImageJobView, status_code=status.HTTP_201_CREATED)
async def create_image_generation(
    payload: ImageGenerationCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
    provider: ModelProvider = Depends(get_model_provider),
) -> ImageJobView:
    existing = db.scalar(
        select(ImageGenerationJob).where(
            ImageGenerationJob.created_by_id == operator.id,
            ImageGenerationJob.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.workflow_id != payload.workflow_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key is already used by another workflow",
            )
        return to_job_view(existing)

    workflow = db.scalar(
        select(ImageWorkflow).where(
            ImageWorkflow.id == payload.workflow_id,
            ImageWorkflow.created_by_id == operator.id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    project_status = db.scalar(
        select(Project.status).where(Project.id == workflow.project_id)
    )
    if project_status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is archived; restore it before generating images",
        )
    if project_status == ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is completed; reopen it before generating images",
        )
    if workflow.status != ImageWorkflowStatus.PROMPT_READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow is not prompt_ready",
        )
    card = db.scalar(
        select(ProductCard).where(ProductCard.project_id == workflow.project_id)
    )
    if card is None or card.confirmed_at is None or card.confirmed_by_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product card must be confirmed before generation",
        )
    requested_ids = set(payload.reference_asset_ids)
    assets = db.scalars(
        select(Asset).where(
            Asset.id.in_(requested_ids),
            Asset.project_id == workflow.project_id,
            Asset.is_archived.is_(False),
        )
    ).all()
    if len(assets) != len(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more reference assets are invalid for this project",
        )
    product_references = [
        asset for asset in assets if asset.asset_type == AssetType.PRODUCT_REFERENCE
    ]
    if not product_references:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one PRODUCT_REFERENCE asset is required",
        )
    if any(not asset.file_hash for asset in product_references):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Every PRODUCT_REFERENCE asset must have a verified file hash",
        )
    job = await create_and_run_image_job(
        db,
        payload=payload,
        workflow=workflow,
        user=operator,
        provider=provider,
        reference_assets=assets,
        request_id=getattr(request.state, "request_id", None),
    )
    db.refresh(job)
    return to_job_view(job)


@router.get("", response_model=list[ImageJobView])
def list_image_generations(
    workflow_id: str | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[ImageJobView]:
    query = (
        select(ImageGenerationJob)
        .where(ImageGenerationJob.created_by_id == operator.id)
        .order_by(ImageGenerationJob.created_at.desc())
    )
    if workflow_id:
        query = query.where(ImageGenerationJob.workflow_id == workflow_id)
    return [to_job_view(job) for job in db.scalars(query).all()]


@router.get("/{job_id}", response_model=ImageJobView)
def get_image_generation(
    job_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ImageJobView:
    job = db.scalar(
        select(ImageGenerationJob).where(
            ImageGenerationJob.id == job_id,
            ImageGenerationJob.created_by_id == operator.id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return to_job_view(job)
