"""sync tasks netdisk accounts

Revision ID: 20260710_sync_tasks_netdisk_accounts
Revises: 20260709_system_configs_and_task_transferred_history
Create Date: 2026-07-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260710_sync_tasks_netdisk_accounts"
down_revision = "20260709_system_configs_and_task_transferred_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "sync_tasks" not in table_names:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
    if "source_account_id" not in cols:
        op.add_column("sync_tasks", sa.Column("source_account_id", sa.Integer(), nullable=True))
    if "target_account_id" not in cols:
        op.add_column("sync_tasks", sa.Column("target_account_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "sync_tasks" not in table_names:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
    if "target_account_id" in cols:
        op.drop_column("sync_tasks", "target_account_id")
    if "source_account_id" in cols:
        op.drop_column("sync_tasks", "source_account_id")
