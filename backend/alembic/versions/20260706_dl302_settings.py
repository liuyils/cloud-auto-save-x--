"""dl302 settings

Revision ID: 20260706_dl302_settings
Revises: 20260613_telegram_bot_state_and_sessions
Create Date: 2026-07-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260706_dl302_settings"
down_revision = "20260613_telegram_bot_state_and_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" in inspector.get_table_names():
        return

    op.create_table(
        "dl302_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("config_kv", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("INSERT INTO dl302_settings (id, config_kv) VALUES (1, '')")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" not in inspector.get_table_names():
        return
    op.drop_table("dl302_settings")
