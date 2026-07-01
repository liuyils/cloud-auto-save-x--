"""dl302 intranet cidrs

Revision ID: 20260708_dl302_intranet_cidrs
Revises: 20260707_drive_account_lsdir_cache
Create Date: 2026-07-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260708_dl302_intranet_cidrs"
down_revision = "20260707_drive_account_lsdir_cache"
branch_labels = None
depends_on = None


DEFAULT_INTRANET_CIDRS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)


def _parse_config_kv(config_kv: str | None) -> dict[str, str]:
    data: dict[str, str] = {}
    for chunk in str(config_kv or "").split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if not key:
            continue
        data[key] = value.strip()
    return data


def _serialize_config_kv(data: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in data.items():
        k = key.strip()
        v = value.strip()
        if not k or not v:
            continue
        parts.append(f"{k}={v}")
    return ";".join(parts)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" not in inspector.get_table_names():
        return
    row = bind.execute(sa.text("SELECT id, config_kv FROM dl302_settings ORDER BY id ASC LIMIT 1")).fetchone()
    if not row:
        return
    config_kv = str(getattr(row, "config_kv", "") or "")
    data = _parse_config_kv(config_kv)
    if "IntranetCIDRs" in data or "IntranetCIDRs=" in config_kv:
        return
    suffix = "IntranetCIDRs=" + ",".join(DEFAULT_INTRANET_CIDRS)
    next_kv = config_kv.strip()
    if next_kv:
        next_kv = next_kv.rstrip(";") + ";" + suffix
    else:
        next_kv = suffix
    bind.execute(
        sa.text("UPDATE dl302_settings SET config_kv = :kv WHERE id = :id"),
        {"kv": next_kv, "id": getattr(row, "id")},
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "dl302_settings" not in inspector.get_table_names():
        return
    row = bind.execute(sa.text("SELECT id, config_kv FROM dl302_settings ORDER BY id ASC LIMIT 1")).fetchone()
    if not row:
        return
    config_kv = str(getattr(row, "config_kv", "") or "")
    data = _parse_config_kv(config_kv)
    if "IntranetCIDRs" not in data and "IntranetCIDRs=" not in config_kv:
        return
    parts: list[str] = []
    for chunk in config_kv.split(";"):
        part = chunk.strip()
        if not part:
            continue
        if part.startswith("IntranetCIDRs="):
            continue
        parts.append(part)
    next_kv = ";".join(parts)
    bind.execute(
        sa.text("UPDATE dl302_settings SET config_kv = :kv WHERE id = :id"),
        {"kv": next_kv, "id": getattr(row, "id")},
    )
