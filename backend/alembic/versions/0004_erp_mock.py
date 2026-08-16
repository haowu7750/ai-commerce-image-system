"""Add vendor-neutral ERP mapping, Mock ERP and trace records.

Revision ID: 0004_erp_mock
Revises: 0003_project_lifecycle
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_erp_mock"
down_revision: Union[str, None] = "0003_project_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "erp_field_mappings",
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_key", "name"),
    )
    op.create_index(
        "ix_erp_field_mappings_connector_key",
        "erp_field_mappings",
        ["connector_key"],
    )

    op.create_table(
        "mock_erp_products",
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("external_version", sa.Integer(), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("draft_payload_json", sa.JSON(), nullable=False),
        sa.Column("last_idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mock_erp_products_external_id",
        "mock_erp_products",
        ["external_id"],
        unique=True,
    )
    op.create_index(
        "ix_mock_erp_products_last_idempotency_key",
        "mock_erp_products",
        ["last_idempotency_key"],
    )

    op.create_table(
        "erp_external_entity_mappings",
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("external_entity_type", sa.String(length=40), nullable=False),
        sa.Column("external_entity_id", sa.String(length=120), nullable=False),
        sa.Column("external_version", sa.String(length=120), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connector_key", "external_entity_type", "external_entity_id"
        ),
        sa.UniqueConstraint("connector_key", "project_id", "external_entity_type"),
    )
    op.create_index(
        "ix_erp_external_entity_mappings_connector_key",
        "erp_external_entity_mappings",
        ["connector_key"],
    )
    op.create_index(
        "ix_erp_external_entity_mappings_project_id",
        "erp_external_entity_mappings",
        ["project_id"],
    )
    op.create_index(
        "ix_erp_external_entity_mappings_external_entity_id",
        "erp_external_entity_mappings",
        ["external_entity_id"],
    )

    op.create_table(
        "erp_sync_records",
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("external_entity_id", sa.String(length=120), nullable=True),
        sa.Column("external_version_before", sa.String(length=120), nullable=True),
        sa.Column("external_version_after", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "connector_key",
        "direction",
        "operation",
        "status",
        "actor_id",
        "project_id",
        "external_entity_id",
        "idempotency_key",
    ):
        op.create_index(
            f"ix_erp_sync_records_{column}", "erp_sync_records", [column]
        )

    op.create_table(
        "erp_writeback_previews",
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("external_mapping_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("expected_external_version", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("final_version_ids_json", sa.JSON(), nullable=False),
        sa.Column("compliance_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("omitted_protected_fields_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confirmed_by_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_version_after", sa.String(length=120), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["external_mapping_id"],
            ["erp_external_entity_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_key", "idempotency_key"),
    )
    for column in (
        "connector_key",
        "project_id",
        "created_by_id",
        "idempotency_key",
        "status",
    ):
        op.create_index(
            f"ix_erp_writeback_previews_{column}",
            "erp_writeback_previews",
            [column],
        )


def downgrade() -> None:
    for column in (
        "status",
        "idempotency_key",
        "created_by_id",
        "project_id",
        "connector_key",
    ):
        op.drop_index(
            f"ix_erp_writeback_previews_{column}",
            table_name="erp_writeback_previews",
        )
    op.drop_table("erp_writeback_previews")

    for column in (
        "idempotency_key",
        "external_entity_id",
        "project_id",
        "actor_id",
        "status",
        "operation",
        "direction",
        "connector_key",
    ):
        op.drop_index(
            f"ix_erp_sync_records_{column}", table_name="erp_sync_records"
        )
    op.drop_table("erp_sync_records")

    op.drop_index(
        "ix_erp_external_entity_mappings_external_entity_id",
        table_name="erp_external_entity_mappings",
    )
    op.drop_index(
        "ix_erp_external_entity_mappings_project_id",
        table_name="erp_external_entity_mappings",
    )
    op.drop_index(
        "ix_erp_external_entity_mappings_connector_key",
        table_name="erp_external_entity_mappings",
    )
    op.drop_table("erp_external_entity_mappings")

    op.drop_index(
        "ix_mock_erp_products_last_idempotency_key",
        table_name="mock_erp_products",
    )
    op.drop_index("ix_mock_erp_products_external_id", table_name="mock_erp_products")
    op.drop_table("mock_erp_products")

    op.drop_index(
        "ix_erp_field_mappings_connector_key", table_name="erp_field_mappings"
    )
    op.drop_table("erp_field_mappings")
