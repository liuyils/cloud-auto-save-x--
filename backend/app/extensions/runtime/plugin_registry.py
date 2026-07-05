from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.plugin_definition import PluginDefinition


class PluginRegistry:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _definition_snapshot(definition: PluginDefinition) -> dict[str, Any]:
        return {
            "id": int(getattr(definition, "id", 0) or 0),
            "plugin_key": str(getattr(definition, "plugin_key", "") or ""),
            "module_name": str(getattr(definition, "module_name", "") or ""),
            "source_type": str(getattr(definition, "source_type", "") or ""),
            "version": str(getattr(definition, "version", "") or "") or None,
            "installed": bool(getattr(definition, "installed", False)),
        }

    @staticmethod
    def _config_snapshot(config: Any) -> dict[str, Any]:
        return {
            "id": int(getattr(config, "id", 0) or 0),
            "enabled": bool(getattr(config, "enabled", False)),
            "priority": int(getattr(config, "priority", 0) or 0),
            "runtime_status": str(getattr(config, "runtime_status", "") or "") or None,
            "last_error": str(getattr(config, "last_error", "") or "") or None,
            "last_checked_at": getattr(config, "last_checked_at", None),
        }

    def load_active_plugins(self) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                select(PluginDefinition)
                .options(selectinload(PluginDefinition.config))
                .where(PluginDefinition.installed.is_(True))
                .order_by(PluginDefinition.plugin_key.asc())
            )
            .scalars()
            .all()
        )
        items: list[dict[str, Any]] = []
        now = datetime.now()
        for definition in rows:
            config = definition.config
            if config is None or not config.enabled:
                continue
            try:
                module = __import__(f'app.extensions.plugins.{definition.module_name}', fromlist=['*'])
                plugin_class = getattr(module, definition.module_name.capitalize())
                payload = json.loads(config.config_json) if config.config_json else {}
                plugin = plugin_class(**payload)
                config.runtime_status = 'active' if getattr(plugin, 'is_active', False) else 'inactive'
                config.last_error = None
                config.last_checked_at = now
                items.append(
                    {
                        'definition': self._definition_snapshot(definition),
                        'config': self._config_snapshot(config),
                        'instance': plugin,
                    }
                )
            except Exception as exc:
                config.runtime_status = 'error'
                config.last_error = str(exc)
                config.last_checked_at = now
        return sorted(items, key=lambda item: int((item.get('config') or {}).get('priority') or 0))
