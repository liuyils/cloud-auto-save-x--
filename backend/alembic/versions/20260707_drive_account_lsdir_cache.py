"""drive account lsdir cache

Revision ID: 20260707_drive_account_lsdir_cache
Revises: 20260706_dl302_settings
Create Date: 2026-07-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260707_drive_account_lsdir_cache"
down_revision = "20260706_dl302_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "drive_account_lsdir_cache" in inspector.get_table_names():
        return

    op.create_table(
        "drive_account_lsdir_cache",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("drive_type", sa.String(length=64), nullable=True),
        sa.Column("parent_fid", sa.String(length=128), nullable=True),
        sa.Column("fid", sa.String(length=128), nullable=False),
        sa.Column("full_path", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("is_dir", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("updated_at_remote", sa.DateTime(timezone=True), nullable=True),
        sa.Column("children_count", sa.Integer(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "full_path", name="uq_drive_account_lsdir_cache_account_path"),
    )
    op.create_index("ix_drive_account_lsdir_cache_account_id", "drive_account_lsdir_cache", ["account_id"])
    op.create_index("ix_drive_account_lsdir_cache_account_parent", "drive_account_lsdir_cache", ["account_id", "parent_fid"])
    op.create_index("ix_drive_account_lsdir_cache_expires_at", "drive_account_lsdir_cache", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "drive_account_lsdir_cache" not in inspector.get_table_names():
        return
    op.drop_index("ix_drive_account_lsdir_cache_expires_at", table_name="drive_account_lsdir_cache")
    op.drop_index("ix_drive_account_lsdir_cache_account_parent", table_name="drive_account_lsdir_cache")
    op.drop_index("ix_drive_account_lsdir_cache_account_id", table_name="drive_account_lsdir_cache")
    op.drop_table("drive_account_lsdir_cache")
