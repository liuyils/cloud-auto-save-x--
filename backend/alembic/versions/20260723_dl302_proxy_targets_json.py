"""dl302 proxy targets json

Revision ID: 20260723_dl302_proxy_targets_json
Revises: 20260721_drop_drive_account_lsdir_cache_expires_at
Create Date: 2026-07-23 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260723_dl302_proxy_targets_json"
down_revision = "20260721_drop_drive_account_lsdir_cache_expires_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("dl302_settings")]
    if "proxy_targets_json" not in columns:
        op.add_column("dl302_settings", sa.Column("proxy_targets_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("dl302_settings")]
    if "proxy_targets_json" in columns:
        op.drop_column("dl302_settings", "proxy_targets_json")
