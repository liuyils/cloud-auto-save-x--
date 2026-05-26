from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request
from app.extensions.runtime.plugin_loader import sync_plugin_definitions
from app.models.openlist_setting import OpenListSetting
from app.models.plugin_definition import PluginDefinition
from app.thirdparty.openlist_client import OpenListClient


def get_openlist_client(db: Session) -> OpenListClient:
    setting = db.execute(select(OpenListSetting).order_by(OpenListSetting.id.asc())).scalars().first()
    if setting is not None:
        url = str(getattr(setting, "url", "") or "").strip()
        token = str(getattr(setting, "token", "") or "").strip()
        if url and token:
            return OpenListClient(url, token=token)

    sync_plugin_definitions(db)
    definition = (
        db.execute(
            select(PluginDefinition)
            .options(selectinload(PluginDefinition.config))
            .where(PluginDefinition.plugin_key == "openlist")
        )
        .scalars()
        .first()
    )
    if definition is None or definition.config is None:
        raise bad_request("OPENLIST_NOT_CONFIGURED", "OpenList 未配置")
    raw = definition.config.config_json
    cfg = {}
    if raw:
        try:
            cfg = json.loads(raw)
        except Exception:
            cfg = {}
    url = str(cfg.get("url") or "").strip()
    token = str(cfg.get("token") or "").strip()
    if not url or not token:
        raise bad_request("OPENLIST_NOT_CONFIGURED", "OpenList 未配置")
    return OpenListClient(url, token=token)
