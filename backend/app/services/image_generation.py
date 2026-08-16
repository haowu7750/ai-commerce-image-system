from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Asset
from app.models.enums import ImageJobStatus, ImageOperation, ImageWorkflowStatus
from app.models.generation import ImageGenerationJob, ImageGenerationOutput, ImageWorkflow
from app.models.identity import User
from app.providers.base import (
    EditImageParams,
    GenerateImageParams,
    ImageInput,
    ModelProvider,
    ProviderError,
)
from app.schemas.generation import ImageGenerationCreate
from app.services.audit import add_audit_event


async def create_and_run_image_job(
    db: Session,
    *,
    payload: ImageGenerationCreate,
    workflow: ImageWorkflow,
    user: User,
    provider: ModelProvider,
    reference_assets: list[Asset],
    request_id: str | None,
) -> ImageGenerationJob:
    existing = db.scalar(
        select(ImageGenerationJob).where(
            ImageGenerationJob.created_by_id == user.id,
            ImageGenerationJob.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing

    job = ImageGenerationJob(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        created_by_id=user.id,
        operation=(
            ImageOperation.GENERATION
            if provider.name == "mock"
            else ImageOperation.EDIT
        ),
        status=ImageJobStatus.QUEUED,
        provider=provider.name,
        model=provider.default_model,
        prompt=workflow.approved_prompt or "",
        options_json={"n": payload.n, "size": payload.size, "quality": payload.quality},
        input_asset_ids_json=payload.reference_asset_ids,
        idempotency_key=payload.idempotency_key,
    )
    db.add(job)
    db.flush()
    add_audit_event(
        db,
        action="image_generation.created",
        object_type="image_generation_job",
        object_id=job.id,
        project_id=job.project_id,
        actor_id=user.id,
        request_id=request_id,
        payload_summary={"provider": provider.name, "model": provider.default_model},
    )
    job.status = ImageJobStatus.RUNNING
    workflow.status = ImageWorkflowStatus.GENERATING
    workflow.revision += 1
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        params = GenerateImageParams(
            prompt=workflow.approved_prompt or "",
            model=provider.default_model,
            n=payload.n,
            size=payload.size,
            quality=payload.quality,
        )
        if provider.name == "mock":
            response = await provider.generate_image(params)
        else:
            image_inputs = [_asset_to_image_input(asset) for asset in reference_assets]
            response = await provider.edit_image(
                EditImageParams(**params.model_dump()), image_inputs
            )
        for index, image in enumerate(response.images, start=1):
            db.add(
                ImageGenerationOutput(
                    job_id=job.id,
                    sequence_no=index,
                    mime_type="image/png" if image.b64_json else None,
                    provider_url=image.url,
                    b64_json=image.b64_json,
                    revised_prompt=image.revised_prompt,
                    metadata_json=image.metadata,
                )
            )
        job.status = ImageJobStatus.SUCCEEDED
        workflow.status = ImageWorkflowStatus.CANDIDATE_READY
        workflow.revision += 1
        job.finished_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            action="image_generation.succeeded",
            object_type="image_generation_job",
            object_id=job.id,
            project_id=job.project_id,
            actor_id=user.id,
            request_id=request_id,
            payload_summary={"output_count": len(response.images)},
        )
        db.commit()
    except ProviderError as exc:
        job.status = ImageJobStatus.FAILED
        workflow.status = ImageWorkflowStatus.GENERATION_FAILED
        workflow.revision += 1
        workflow.failure_code = exc.code
        job.error_code = exc.code
        job.error_message = exc.safe_message
        job.finished_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            action="image_generation.failed",
            object_type="image_generation_job",
            object_id=job.id,
            project_id=job.project_id,
            actor_id=user.id,
            request_id=request_id,
            payload_summary={"error_code": exc.code, "retryable": exc.retryable},
            result="failed",
        )
        db.commit()
    db.refresh(job)
    return job


def _asset_to_image_input(asset: Asset) -> ImageInput:
    value = asset.file_url or ""
    if not value.startswith("data:image/") or ";base64," not in value:
        raise ProviderError(
            "REFERENCE_IMAGE_CONTENT_MISSING",
            "参考图只有外部地址，真实生图需要重新上传本地图片内容",
        )
    header, encoded = value.split(",", 1)
    content_type = header[5:].split(";", 1)[0].lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ProviderError(
            "REFERENCE_IMAGE_TYPE_UNSUPPORTED",
            "参考图格式仅支持 PNG、JPEG 或 WebP",
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProviderError(
            "REFERENCE_IMAGE_INVALID",
            "参考图内容损坏，请重新上传",
        ) from exc
    if not content or len(content) > 20 * 1024 * 1024:
        raise ProviderError(
            "REFERENCE_IMAGE_SIZE_INVALID",
            "单张参考图必须大于 0 字节且不超过 20MB",
        )
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
        content_type
    ]
    return ImageInput(
        filename=f"reference-{asset.id}.{extension}",
        content=content,
        content_type=content_type,
    )
