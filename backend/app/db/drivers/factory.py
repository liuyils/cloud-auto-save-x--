from __future__ import annotations

from app.core.settings import Settings, settings
from app.db.drivers.base import DatabaseDriver
from app.db.drivers.mysql import MySQLDriver
from app.db.drivers.sqlite import SQLiteDriver


def create_database_driver(config: Settings | None = None) -> DatabaseDriver:
    cfg = config or settings
    driver = cfg.normalized_db_driver
    if cfg.database_url.startswith("mysql"):
        driver = "mysql"
    if driver == "mysql":
        return MySQLDriver(cfg)
    return SQLiteDriver(cfg)
