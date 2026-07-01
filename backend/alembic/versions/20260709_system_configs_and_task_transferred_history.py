"""system configs and task transferred history

Revision ID: 20260709_system_configs_and_task_transferred_history
Revises: 20260708_dl302_intranet_cidrs
Create Date: 2026-07-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260709_system_configs_and_task_transferred_history"
down_revision = "20260708_dl302_intranet_cidrs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "system_configs" not in table_names:
        op.create_table(
            "system_configs",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("config_key", sa.String(length=64), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("config_key"),
        )
        op.create_index("ix_system_configs_config_key", "system_configs", ["config_key"], unique=True)

    if "tasks" in table_names:
        columns = {col["name"] for col in inspector.get_columns("tasks")}
        if "transferred_history_json" not in columns:
            op.add_column("tasks", sa.Column("transferred_history_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "tasks" in table_names:
        columns = {col["name"] for col in inspector.get_columns("tasks")}
        if "transferred_history_json" in columns:
            op.drop_column("tasks", "transferred_history_json")

    if "system_configs" in table_names:
        index_names = {item.get("name") for item in inspector.get_indexes("system_configs")}
        if "ix_system_configs_config_key" in index_names:
            op.drop_index("ix_system_configs_config_key", table_name="system_configs")
        op.drop_table("system_configs")
