from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TimelineEventView(BaseModel):
    id: str
    action: str
    object_type: str
    object_id: str | None
    actor_id: str | None
    summary: dict[str, Any]
    result: str
    created_at: datetime


class DesignArtifactView(BaseModel):
    task_id: str
    task_title: str
    submission_id: str
    version_no: int
    file_url: str
    notes: str


class ImageArtifactView(BaseModel):
    workflow_id: str
    job_id: str
    output_id: str
    asset_id: str | None
    provider: str
    model: str
    mime_type: str | None
    provider_url: str | None
    preview_data_url: str | None
    revised_prompt: str | None


class ProjectDeliveryPackage(BaseModel):
    project: dict[str, Any]
    product_card: dict[str, Any] | None
    final_content: dict[str, dict[str, Any]]
    accepted_designs: list[DesignArtifactView]
    confirmed_images: list[ImageArtifactView]
    blockers: list[str]
    timeline: list[TimelineEventView]


class TextExportView(BaseModel):
    filename: str
    mime_type: str
    content: str


class KnowledgeCaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    notes: str = Field(default="", max_length=5000)


class LibraryResourceView(BaseModel):
    id: str
    kind: str
    name: str
    description: str
    content: dict[str, Any]
    version: int
    updated_at: datetime


class FieldMappingSummary(BaseModel):
    id: str
    name: str
    connector_key: str
    version: int
    is_active: bool
    mapping: dict[str, str]
    updated_at: datetime


LibraryKind = Literal["prompt", "compliance_rule", "knowledge_case"]
