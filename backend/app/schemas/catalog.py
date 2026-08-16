from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AssetType


class ProductCardUpsert(BaseModel):
    product_name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    current_title: str | None = Field(default=None, max_length=500)
    facts: dict[str, Any] = Field(default_factory=dict)
    selling_points: list[dict[str, Any]] = Field(default_factory=list)
    specs: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    field_sources: dict[str, str] = Field(default_factory=dict)
    completeness_percent: float = Field(default=0, ge=0, le=100)


class ProductFieldGap(BaseModel):
    field: str
    label: str
    impact: str
    required_for: list[str] = Field(default_factory=list)


class ProductCardView(BaseModel):
    id: str
    project_id: str
    product_name: str
    brand: str | None
    current_title: str | None
    facts: dict[str, Any]
    selling_points: list[dict[str, Any]]
    specs: list[dict[str, Any]]
    constraints: dict[str, Any]
    field_sources: dict[str, str]
    missing_fields: list[ProductFieldGap] = Field(default_factory=list)
    completeness_percent: float
    revision: int
    confirmed_by_id: str | None
    confirmed_at: datetime | None


class AssetCreate(BaseModel):
    asset_type: AssetType
    storage_key: str | None = Field(default=None, max_length=1024)
    file_url: str | None = Field(default=None, max_length=2_000_000)
    file_hash: str | None = Field(default=None, max_length=128)
    mime_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=1, le=10_000_000)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    usage_note: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetSelectionUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    selected_for_generation: bool


class AssetView(BaseModel):
    id: str
    project_id: str
    asset_type: AssetType
    source: str
    storage_key: str | None
    file_url: str | None
    file_hash: str | None
    mime_type: str | None
    file_size: int | None
    width: int | None
    height: int | None
    usage_note: str
    selected_for_generation: bool
    is_archived: bool
    archive_blockers: list[str] = Field(default_factory=list)
    metadata: dict[str, Any]
    created_at: datetime
