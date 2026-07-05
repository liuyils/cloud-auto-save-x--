"""drive accounts sqlite autoincrement

Revision ID: 20260711_drive_accounts_sqlite_autoincrement
Revises: 20260710_sync_tasks_netdisk_accounts
Create Date: 2026-07-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_drive_accounts_sqlite_autoincrement"
down_revision = "20260710_sync_tasks_netdisk_accounts"
branch_labels = None
depends_on = None


_TABLE_NAME = "drive_accounts"
_TMP_TABLE_NAME = "drive_accounts__tmp_autoinc"


def _create_drive_accounts_table_sql(*, table_name: str, autoincrement: bool) -> str:
    autoinc = " AUTOINCREMENT" if autoincrement else ""
    return f"""
    CREATE TABLE {table_name} (
        id INTEGER NOT NULL PRIMARY KEY{autoinc},
        name VARCHAR(128) NOT NULL,
        drive_type VARCHAR(64) NOT NULL,
        cookie TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT '1',
        is_default BOOLEAN NOT NULL DEFAULT '0',
        runtime_status VARCHAR(32),
        last_checked_at DATETIME,
        last_error TEXT,
        created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        config_json TEXT,
        probe_fail_count INTEGER NOT NULL DEFAULT '0',
        profile_json TEXT,
        capacity_warning_threshold INTEGER NOT NULL DEFAULT '85'
    )
    """


def _recreate_drive_accounts_table(*, autoincrement: bool) -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute(f"DROP TABLE IF EXISTS {_TMP_TABLE_NAME}")
    op.execute(_create_drive_accounts_table_sql(table_name=_TMP_TABLE_NAME, autoincrement=autoincrement))
    op.execute(
        f"""
        INSERT INTO {_TMP_TABLE_NAME} (
            id,
            name,
            drive_type,
            cookie,
            enabled,
            is_default,
            runtime_status,
            last_checked_at,
            last_error,
            created_at,
            updated_at,
            config_json,
            probe_fail_count,
            profile_json,
            capacity_warning_threshold
        )
        SELECT
            id,
            name,
            drive_type,
            cookie,
            enabled,
            is_default,
            runtime_status,
            last_checked_at,
            last_error,
            created_at,
            updated_at,
            config_json,
            probe_fail_count,
            profile_json,
            capacity_warning_threshold
        FROM {_TABLE_NAME}
        """
    )
    op.execute(f"DROP TABLE {_TABLE_NAME}")
    op.execute(f"ALTER TABLE {_TMP_TABLE_NAME} RENAME TO {_TABLE_NAME}")
    op.create_index(op.f("ix_drive_accounts_name"), _TABLE_NAME, ["name"], unique=True)
    op.create_index(op.f("ix_drive_accounts_drive_type"), _TABLE_NAME, ["drive_type"], unique=False)
    if autoincrement:
        op.execute("DELETE FROM sqlite_sequence WHERE name = 'drive_accounts'")
        op.execute(
            """
            INSERT INTO sqlite_sequence(name, seq)
            SELECT 'drive_accounts', COALESCE(MAX(id), 0)
            FROM drive_accounts
            """
        )
    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    _recreate_drive_accounts_table(autoincrement=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    _recreate_drive_accounts_table(autoincrement=False)
