from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ERPFieldMapping(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "erp_field_mappings"
    __table_args__ = (UniqueConstraint("connector_key", "name"),)

    connector_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mapping_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )


class MockERPProduct(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mock_erp_products"

    external_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    external_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    draft_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_idempotency_key: Mapped[str | None] = mapped_column(String(120), index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ERPExternalEntityMapping(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "erp_external_entity_mappings"
    __table_args__ = (
        UniqueConstraint("connector_key", "external_entity_type", "external_entity_id"),
        UniqueConstraint("connector_key", "project_id", "external_entity_type"),
    )

    connector_key: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    external_entity_type: Mapped[str] = mapped_column(String(40), default="product")
    external_entity_id: Mapped[str] = mapped_column(String(120), index=True)
    external_version: Mapped[str] = mapped_column(String(120), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ERPSyncRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "erp_sync_records"

    connector_key: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)
    operation: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    external_entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    external_version_before: Mapped[str | None] = mapped_column(String(120))
    external_version_after: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), index=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class ERPWritebackPreview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "erp_writeback_previews"
    __table_args__ = (UniqueConstraint("connector_key", "idempotency_key"),)

    connector_key: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    external_mapping_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("erp_external_entity_mappings.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    expected_external_version: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    final_version_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    compliance_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    omitted_protected_fields_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    confirmed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_version_after: Mapped[str | None] = mapped_column(String(120))
