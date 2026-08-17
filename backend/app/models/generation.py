from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    BatchImageItemStatus,
    BatchImageMode,
    BatchImageTaskStatus,
    ImageComplianceStatus,
    ImageJobStatus,
    ImageOperation,
    ImageQaStatus,
    ImageWorkflowStatus,
)


class ImageWorkflow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "image_workflows"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[ImageWorkflowStatus] = mapped_column(
        Enum(ImageWorkflowStatus, native_enum=False),
        default=ImageWorkflowStatus.DRAFT,
        index=True,
    )
    product_type_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scene_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    selected_scene_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    approved_prompt: Mapped[str | None] = mapped_column(Text)
    qa_status: Mapped[ImageQaStatus] = mapped_column(
        Enum(ImageQaStatus, native_enum=False),
        default=ImageQaStatus.PENDING,
        nullable=False,
        index=True,
    )
    compliance_status: Mapped[ImageComplianceStatus] = mapped_column(
        Enum(ImageComplianceStatus, native_enum=False),
        default=ImageComplianceStatus.UNCHECKED,
        nullable=False,
        index=True,
    )
    qa_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    compliance_report_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    confirmed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    confirmed_at: Mapped[datetime | None]
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stale_reason: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(100))

    jobs: Mapped[list[ImageGenerationJob]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class ImageGenerationJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "image_generation_jobs"
    __table_args__ = (UniqueConstraint("created_by_id", "idempotency_key"),)

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("image_workflows.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    operation: Mapped[ImageOperation] = mapped_column(
        Enum(ImageOperation, native_enum=False), default=ImageOperation.GENERATION
    )
    status: Mapped[ImageJobStatus] = mapped_column(
        Enum(ImageJobStatus, native_enum=False), default=ImageJobStatus.QUEUED, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_asset_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    outputs: Mapped[list[ImageGenerationOutput]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    workflow: Mapped[ImageWorkflow] = relationship(back_populates="jobs")


class ImageGenerationOutput(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "image_generation_outputs"

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("image_generation_jobs.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="SET NULL")
    )
    mime_type: Mapped[str | None] = mapped_column(String(100))
    provider_url: Mapped[str | None] = mapped_column(Text)
    b64_json: Mapped[str | None] = mapped_column(Text)
    revised_prompt: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    job: Mapped[ImageGenerationJob] = relationship(back_populates="outputs")


class BatchImageTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "batch_image_tasks"
    __table_args__ = (UniqueConstraint("created_by_id", "idempotency_key"),)

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    mode: Mapped[BatchImageMode] = mapped_column(
        Enum(BatchImageMode, native_enum=False), index=True
    )
    status: Mapped[BatchImageTaskStatus] = mapped_column(
        Enum(BatchImageTaskStatus, native_enum=False),
        default=BatchImageTaskStatus.QUEUED,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    product_reference_asset_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    source_asset_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    progress_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[BatchImageItem]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BatchImageItem.position",
    )


class BatchImageItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "batch_image_items"
    __table_args__ = (UniqueConstraint("task_id", "position"),)

    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("batch_image_tasks.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    output_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BatchImageItemStatus] = mapped_column(
        Enum(BatchImageItemStatus, native_enum=False),
        default=BatchImageItemStatus.QUEUED,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    output_mime_type: Mapped[str | None] = mapped_column(String(100))
    provider_url: Mapped[str | None] = mapped_column(Text)
    b64_json: Mapped[str | None] = mapped_column(Text)
    revised_prompt: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    qa_status: Mapped[ImageQaStatus] = mapped_column(
        Enum(ImageQaStatus, native_enum=False),
        default=ImageQaStatus.PENDING,
        index=True,
    )
    compliance_status: Mapped[ImageComplianceStatus] = mapped_column(
        Enum(ImageComplianceStatus, native_enum=False),
        default=ImageComplianceStatus.UNCHECKED,
        index=True,
    )
    review_report_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    reviewed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    task: Mapped[BatchImageTask] = relationship(back_populates="items")
