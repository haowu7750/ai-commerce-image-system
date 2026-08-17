"""Add supervised batch image editing tasks and per-image review records.

Revision ID: 0005_batch_image_tasks
Revises: 0004_erp_mock
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_batch_image_tasks"
down_revision: Union[str, None] = "0004_erp_mock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_image_tasks",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=15), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("product_reference_asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("source_asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("created_by_id", "idempotency_key"),
    )
    for column in ("project_id", "created_by_id", "mode", "status"):
        op.create_index(f"ix_batch_image_tasks_{column}", "batch_image_tasks", [column])

    op.create_table(
        "batch_image_items",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("output_asset_id", sa.String(length=36), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_mime_type", sa.String(length=100), nullable=True),
        sa.Column("provider_url", sa.Text(), nullable=True),
        sa.Column("b64_json", sa.Text(), nullable=True),
        sa.Column("revised_prompt", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("qa_status", sa.String(length=11), nullable=False),
        sa.Column("compliance_status", sa.String(length=15), nullable=False),
        sa.Column("review_report_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["batch_image_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "position"),
    )
    for column in (
        "task_id",
        "source_asset_id",
        "output_asset_id",
        "status",
        "qa_status",
        "compliance_status",
        "reviewed_by_id",
        "confirmed_by_id",
    ):
        op.create_index(f"ix_batch_image_items_{column}", "batch_image_items", [column])


def downgrade() -> None:
    for column in (
        "confirmed_by_id",
        "reviewed_by_id",
        "compliance_status",
        "qa_status",
        "status",
        "output_asset_id",
        "source_asset_id",
        "task_id",
    ):
        op.drop_index(f"ix_batch_image_items_{column}", table_name="batch_image_items")
    op.drop_table("batch_image_items")
    for column in ("status", "mode", "created_by_id", "project_id"):
        op.drop_index(f"ix_batch_image_tasks_{column}", table_name="batch_image_tasks")
    op.drop_table("batch_image_tasks")
