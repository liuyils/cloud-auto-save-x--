from __future__ import annotations

import os

from app.db.drivers.base import DatabaseDriver


class MySQLDriver(DatabaseDriver):
    name = "mysql"

    @property
    def url(self) -> str:
        return self.settings.database_url

    def prepare_environment(self) -> None:
        os.makedirs(self.settings.resolved_app_data_dir, exist_ok=True)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not str(self.settings.db_name or "").strip():
            errors.append("DB_NAME 不能为空")
        if not str(self.settings.db_user or "").strip():
            errors.append("DB_USER 不能为空")
        return errors
