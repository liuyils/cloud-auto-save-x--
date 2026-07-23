"""sync task drama links add sort_order

Revision ID: 20260723_sync_task_drama_links_sort_order
Revises: 20260723_dl302_proxy_targets_json
Create Date: 2026-07-23 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260723_sync_task_drama_links_sort_order"
down_revision = "20260723_dl302_proxy_targets_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_drama_links" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("sync_task_drama_links")}
    if "sort_order" in columns:
        return

    op.add_column(
        "sync_task_drama_links",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_drama_links" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("sync_task_drama_links")}
    if "sort_order" not in columns:
        return

    op.drop_column("sync_task_drama_links", "sort_order")
