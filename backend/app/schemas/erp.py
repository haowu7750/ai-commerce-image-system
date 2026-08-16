from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.erp.base import ERPConnectorCapabilities, UnifiedProduct


class ERPFieldMappingCreate(BaseModel):
    connector_key: Literal["mock"] = "mock"
    name: str = Field(min_length=2, max_length=120)
    mapping: dict[str, str]


class ERPFieldMappingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connector_key: str
    name: str
    mapping_json: dict[str, str]
    version: int
    is_active: bool
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ERPImportPreviewRequest(BaseModel):
    external_id: str = Field(min_length=1, max_length=120)
    store_name: str = Field(min_length=1, max_length=200)
    project_name: str | None = Field(default=None, max_length=200)
    target_project_id: str | None = None
    field_mapping_id: str | None = None
    field_mapping: dict[str, str] | None = None

    @model_validator(mode="after")
    def mapping_source_is_unambiguous(self) -> "ERPImportPreviewRequest":
        if self.field_mapping_id and self.field_mapping:
            raise ValueError("Choose a saved field mapping or an ad-hoc mapping, not both")
        return self


class ERPSyncRecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connector_key: str
    direction: str
    operation: str
    status: str
    actor_id: str
    project_id: str | None
    external_entity_id: str | None
    external_version_before: str | None
    external_version_after: str | None
    idempotency_key: str | None
    request_json: dict[str, Any]
    result_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ERPImportPreviewView(BaseModel):
    record: ERPSyncRecordView
    product: UnifiedProduct
    field_mapping: dict[str, str]
    warnings: list[str] = Field(default_factory=list)


class ERPExternalEntityMappingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connector_key: str
    project_id: str
    external_entity_type: str
    external_entity_id: str
    external_version: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ERPImportApplyView(BaseModel):
    project_id: str
    product_card_id: str
    mapping: ERPExternalEntityMappingView
    record: ERPSyncRecordView


class ERPWritebackPreviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)


class ERPWritebackPreviewView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connector_key: str
    project_id: str
    external_mapping_id: str
    created_by_id: str
    expected_external_version: str
    idempotency_key: str
    payload_json: dict[str, Any]
    final_version_ids_json: list[str]
    compliance_snapshot_json: dict[str, Any]
    omitted_protected_fields_json: list[str]
    status: str
    confirmed_by_id: str | None
    confirmed_at: datetime | None
    external_version_after: str | None
    created_at: datetime
    updated_at: datetime


class ERPWritebackConfirmRequest(BaseModel):
    confirm: bool


class ERPMockExternalChangeView(BaseModel):
    external_id: str
    external_version: str
    message: str


__all__ = [
    "ERPConnectorCapabilities",
    "ERPExternalEntityMappingView",
    "ERPFieldMappingCreate",
    "ERPFieldMappingView",
    "ERPImportApplyView",
    "ERPImportPreviewRequest",
    "ERPImportPreviewView",
    "ERPMockExternalChangeView",
    "ERPSyncRecordView",
    "ERPWritebackConfirmRequest",
    "ERPWritebackPreviewRequest",
    "ERPWritebackPreviewView",
]
