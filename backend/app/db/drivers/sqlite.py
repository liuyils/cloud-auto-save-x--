from __future__ import annotations

import os
import sqlite3

from sqlalchemy import Engine, event
from sqlalchemy.pool import NullPool

from app.db.drivers.base import DatabaseDriver


class SQLiteDriver(DatabaseDriver):
    name = "sqlite3"

    @property
    def url(self) -> str:
        return self.settings.database_url

    @property
    def path(self) -> str:
        return self.settings.resolved_sqlite_path

    def connect_args(self) -> dict[str, object]:
        return {"check_same_thread": False, "timeout": 30}

    def engine_kwargs(self, *, for_migrations: bool = False) -> dict[str, object]:
        kwargs: dict[str, object] = {"future": True}
        kwargs["poolclass"] = NullPool
        return kwargs

    def prepare_environment(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._ensure_pragmas()

    def configure_engine(self, engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            # Keep connect-time PRAGMA setup strictly connection-local.
            # Persistent database PRAGMAs such as auto_vacuum/journal_mode are
            # applied once during prepare_environment(); reapplying them on each
            # new connection under NullPool can contend for write locks.
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    def is_lock_error(self, exc: Exception) -> bool:
        return "database is locked" in str(exc).lower()

    def cache_dir(self, explicit_dir: str | None = None) -> str:
        if explicit_dir and str(explicit_dir).strip():
            return str(explicit_dir).strip()
        return os.path.join(os.path.dirname(self.path) or self.settings.resolved_app_data_dir, "cache", "proxy_image")

    def _ensure_pragmas(self) -> None:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA auto_vacuum")
            row = cur.fetchone()
            current_mode = int(row[0]) if row and row[0] is not None else 0
            if current_mode != 1:
                cur.execute("PRAGMA auto_vacuum=FULL")
                conn.commit()
                cur.execute("VACUUM")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            conn.commit()
            cur.close()
        finally:
            conn.close()
