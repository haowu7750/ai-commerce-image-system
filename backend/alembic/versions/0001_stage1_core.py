"""Create stage 1 identity, commerce, audit, and image generation tables.

Revision ID: 0001_stage1_core
Revises:
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op

from app.models import Base


revision: str = "0001_stage1_core"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# This revision originally called Base.metadata.create_all() without filtering.
# Once later models were imported, a clean migration incorrectly created future
# tables in revision 0001. Keep the historical boundary explicit so 0002 owns
# the role workspace tables on both fresh and existing databases.
LATER_TABLES = {
    "batch_image_tasks",
    "batch_image_items",
    "design_tasks",
    "design_submissions",
    "system_resources",
    "project_deletion_records",
    "erp_field_mappings",
    "mock_erp_products",
    "erp_external_entity_mappings",
    "erp_sync_records",
    "erp_writeback_previews",
}


def stage1_tables():
    return [
        table
        for name, table in Base.metadata.tables.items()
        if name not in LATER_TABLES
    ]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=stage1_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=stage1_tables())
