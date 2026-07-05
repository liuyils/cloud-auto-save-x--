from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine

from app.core.settings import Settings


class DatabaseDriver(ABC):
    name: str

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    @abstractmethod
    def url(self) -> str:
        raise NotImplementedError

    def connect_args(self) -> dict[str, Any]:
        return {}

    def engine_kwargs(self, *, for_migrations: bool = False) -> dict[str, Any]:
        return {"future": True}

    def prepare_environment(self) -> None:
        return None

    def configure_engine(self, engine: Engine) -> None:
        return None

    def healthcheck_sql(self) -> str:
        return "SELECT 1"

    def is_lock_error(self, exc: Exception) -> bool:
        return False

    def cache_dir(self, explicit_dir: str | None = None) -> str:
        if explicit_dir and str(explicit_dir).strip():
            return str(explicit_dir).strip()
        return f"{self.settings.resolved_app_data_dir}/cache/proxy_image"

    def validation_errors(self) -> list[str]:
        return []

    def export_meta(self) -> Mapping[str, Any]:
        return {"name": self.name, "url": self.url}
