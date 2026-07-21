"""drop drive account lsdir cache expires_at

Revision ID: 20260721_drop_drive_account_lsdir_cache_expires_at
Revises: 20260719_drop_drive_account_lsdir_cache_raw_json
Create Date: 2026-07-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260721_drop_drive_account_lsdir_cache_expires_at"
down_revision = "20260719_drop_drive_account_lsdir_cache_raw_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "drive_account_lsdir_cache" not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes("drive_account_lsdir_cache")}
    columns = {item["name"] for item in inspector.get_columns("drive_account_lsdir_cache")}
    with op.batch_alter_table("drive_account_lsdir_cache") as batch_op:
        if "ix_drive_account_lsdir_cache_expires_at" in indexes:
            batch_op.drop_index("ix_drive_account_lsdir_cache_expires_at")
        if "expires_at" in columns:
            batch_op.drop_column("expires_at")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "drive_account_lsdir_cache" not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes("drive_account_lsdir_cache")}
    columns = {item["name"] for item in inspector.get_columns("drive_account_lsdir_cache")}
    with op.batch_alter_table("drive_account_lsdir_cache") as batch_op:
        if "expires_at" not in columns:
            batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        if "ix_drive_account_lsdir_cache_expires_at" not in indexes:
            batch_op.create_index("ix_drive_account_lsdir_cache_expires_at", ["expires_at"], unique=False)
