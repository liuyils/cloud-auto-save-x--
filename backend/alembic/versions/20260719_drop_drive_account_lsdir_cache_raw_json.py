"""drop drive account lsdir cache raw_json

Revision ID: 20260719_drop_drive_account_lsdir_cache_raw_json
Revises: 20260711_drive_accounts_sqlite_autoincrement
Create Date: 2026-07-19 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260719_drop_drive_account_lsdir_cache_raw_json"
down_revision = "20260711_drive_accounts_sqlite_autoincrement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("drive_account_lsdir_cache")}
    if "raw_json" not in columns:
        return
    with op.batch_alter_table("drive_account_lsdir_cache") as batch_op:
        batch_op.drop_column("raw_json")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("drive_account_lsdir_cache")}
    if "raw_json" in columns:
        return
    with op.batch_alter_table("drive_account_lsdir_cache") as batch_op:
        batch_op.add_column(sa.Column("raw_json", sa.Text(), nullable=True))
