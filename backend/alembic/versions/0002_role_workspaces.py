"""Add designer collaboration and administrator resource tables.

Revision ID: 0002_role_workspaces
Revises: 0001_stage1_core
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_role_workspaces"
down_revision: Union[str, None] = "0001_stage1_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "design_tasks",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_to_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("requirements_json", sa.JSON(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_design_tasks_assigned_to_id", "design_tasks", ["assigned_to_id"])
    op.create_index("ix_design_tasks_created_by_id", "design_tasks", ["created_by_id"])
    op.create_index("ix_design_tasks_project_id", "design_tasks", ["project_id"])
    op.create_index("ix_design_tasks_status", "design_tasks", ["status"])

    op.create_table(
        "design_submissions",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("submitted_by_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version_no"),
    )
    op.create_index(
        "ix_design_submissions_task_id",
        "design_submissions",
        ["task_id"],
    )

    op.create_table(
        "system_resources",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_by_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name"),
    )
    op.create_index("ix_system_resources_kind", "system_resources", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_system_resources_kind", table_name="system_resources")
    op.drop_table("system_resources")
    op.drop_index("ix_design_submissions_task_id", table_name="design_submissions")
    op.drop_table("design_submissions")
    op.drop_index("ix_design_tasks_status", table_name="design_tasks")
    op.drop_index("ix_design_tasks_project_id", table_name="design_tasks")
    op.drop_index("ix_design_tasks_created_by_id", table_name="design_tasks")
    op.drop_index("ix_design_tasks_assigned_to_id", table_name="design_tasks")
    op.drop_table("design_tasks")
