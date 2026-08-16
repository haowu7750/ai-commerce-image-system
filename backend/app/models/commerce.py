from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import AssetType, ContentStatus, ProjectStatus


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(64), default="拼多多", nullable=False)
    store_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False), default=ProjectStatus.DRAFT, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product_card: Mapped[ProductCard | None] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    content_versions: Mapped[list[ContentVersion]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        foreign_keys="ContentVersion.project_id",
    )


class ProjectDeletionRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "project_deletion_records"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    deleted_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status_before_delete: Mapped[str] = mapped_column(String(32), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    restored_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductCard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "product_cards"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200))
    current_title: Mapped[str | None] = mapped_column(String(500))
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    selling_points_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    specs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    field_sources_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    completeness_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    confirmed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="product_card")


class Asset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assets"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploaded_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, native_enum=False), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="upload", nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), unique=True)
    file_url: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    project: Mapped[Project] = relationship(back_populates="assets")


class ContentVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "content_type", "version_no"),
    )

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    content_type: Mapped[str] = mapped_column(String(64), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), default="human", nullable=False)
    source_task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("content_versions.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, native_enum=False), default=ContentStatus.EDITING, index=True
    )
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finalized_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    project: Mapped[Project] = relationship(
        back_populates="content_versions", foreign_keys=[project_id]
    )


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str | None] = mapped_column(String(64), index=True)
    request_id: Mapped[str | None] = mapped_column(String(100), index=True)
    payload_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
