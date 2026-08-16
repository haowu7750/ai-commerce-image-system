from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from typing import Any

from app.models.enums import (
    ImageComplianceStatus,
    ImageJobStatus,
    ImageOperation,
    ImageQaStatus,
    ImageWorkflowStatus,
)


class ImageGenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    reference_asset_ids: list[str] = Field(min_length=1)
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024", max_length=32)
    quality: str | None = Field(default=None, max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ImageOutputView(BaseModel):
    id: str
    sequence_no: int
    mime_type: str | None
    provider_url: str | None
    b64_json: str | None
    revised_prompt: str | None


class ImageJobView(BaseModel):
    id: str
    project_id: str
    workflow_id: str
    created_by_id: str
    operation: ImageOperation
    status: ImageJobStatus
    provider: str
    model: str
    prompt: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    outputs: list[ImageOutputView]


class ImageWorkflowCreate(BaseModel):
    project_id: str


class ImageWorkflowTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: ImageWorkflowStatus
    expected_revision: int = Field(ge=1)
    target_status: ImageWorkflowStatus
    product_type: dict[str, Any] | None = None
    scene_plan: dict[str, Any] | None = None
    selected_scene: dict[str, Any] | None = None
    approved_prompt: str | None = Field(default=None, min_length=30, max_length=20000)


class MockImageChecksCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    scenario: str = Field(pattern="^(clear|qa_failed|medium_risk|high_risk)$")


class ManualImageReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    product_facts_match: bool
    geometry_and_count_match: bool
    logo_text_and_personalization_match: bool
    thumbnail_readable: bool
    compliance_risk: str = Field(pattern="^(clear|medium|high)$")
    notes: str = Field(min_length=10, max_length=3000)


class ResolveMediumRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)


class ConfirmImageWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class ImageWorkflowView(BaseModel):
    id: str
    project_id: str
    created_by_id: str
    status: ImageWorkflowStatus
    product_type: dict[str, Any]
    scene_plan: dict[str, Any]
    selected_scene: dict[str, Any]
    approved_prompt: str | None
    qa_status: ImageQaStatus
    compliance_status: ImageComplianceStatus
    qa_report: dict[str, Any]
    compliance_report: dict[str, Any]
    confirmed_by_id: str | None
    confirmed_at: datetime | None
    revision: int
    stale_reason: str | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
