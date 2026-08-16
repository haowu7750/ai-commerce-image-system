"""Add traceable project deletion records.

Revision ID: 0003_project_lifecycle
Revises: 0002_role_workspaces
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_project_lifecycle"
down_revision: Union[str, None] = "0002_role_workspaces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_deletion_records",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_by_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status_before_delete", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_by_id", sa.String(length=36), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["deleted_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["restored_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_deletion_records_project_id",
        "project_deletion_records",
        ["project_id"],
    )
    op.create_index(
        "ix_project_deletion_records_deleted_by_id",
        "project_deletion_records",
        ["deleted_by_id"],
    )
    op.create_index(
        "ix_project_deletion_records_deleted_at",
        "project_deletion_records",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_deletion_records_deleted_at",
        table_name="project_deletion_records",
    )
    op.drop_index(
        "ix_project_deletion_records_deleted_by_id",
        table_name="project_deletion_records",
    )
    op.drop_index(
        "ix_project_deletion_records_project_id",
        table_name="project_deletion_records",
    )
    op.drop_table("project_deletion_records")
