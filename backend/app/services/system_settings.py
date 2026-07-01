from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig


SAVE_RULE_CONFIG_KEY = "save_rules"


def _load_json(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_or_create_system_config(db: Session, *, config_key: str) -> SystemConfig:
    item = db.execute(select(SystemConfig).where(SystemConfig.config_key == str(config_key)).limit(1)).scalars().first()
    if item is not None:
        return item
    item = SystemConfig(config_key=str(config_key), config_json=json.dumps({}, ensure_ascii=False))
    db.add(item)
    db.flush()
    return item


def load_save_rule_config(item: SystemConfig) -> dict[str, object]:
    raw = _load_json(item.config_json)
    return {
        "enable_skip_transferred_history": bool(raw.get("enable_skip_transferred_history") or False),
    }


def get_save_rule_runtime_config(db: Session) -> dict[str, object]:
    item = get_or_create_system_config(db, config_key=SAVE_RULE_CONFIG_KEY)
    return load_save_rule_config(item)


def update_save_rule_config(db: Session, *, payload: dict[str, Any]) -> SystemConfig:
    item = get_or_create_system_config(db, config_key=SAVE_RULE_CONFIG_KEY)
    raw = _load_json(item.config_json)
    if "enable_skip_transferred_history" in payload and payload.get("enable_skip_transferred_history") is not None:
        raw["enable_skip_transferred_history"] = bool(payload.get("enable_skip_transferred_history"))
    item.config_json = json.dumps(raw, ensure_ascii=False)
    db.flush()
    return item
