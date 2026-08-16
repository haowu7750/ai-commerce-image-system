from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ContentStatus
from app.schemas.catalog import AssetView, ProductCardView
from app.schemas.project import ProjectView


ContentType = Literal["title", "sku", "compliance", "design_brief", "result_note"]


class ContentVersionCreate(BaseModel):
    content_type: ContentType
    content: dict[str, Any]
    source_kind: Literal["human", "ai", "import"] = "human"


class ContentVersionView(BaseModel):
    id: str
    project_id: str
    content_type: str
    version_no: int
    content: dict[str, Any]
    source_kind: str
    created_by_id: str
    status: ContentStatus
    is_final: bool
    finalized_by_id: str | None
    finalized_at: datetime | None
    created_at: datetime


class ProjectDetailView(BaseModel):
    project: ProjectView
    product_card: ProductCardView | None
    assets: list[AssetView]
    content_versions: list[ContentVersionView]


class ProjectResultView(BaseModel):
    project: ProjectView
    product_card_confirmed: bool
    final_content: dict[str, dict[str, Any]]
    accepted_design_count: int
    open_design_count: int
    blockers: list[str]
