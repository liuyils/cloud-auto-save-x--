from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from urllib.parse import quote_plus

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _secrets_file_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[2]
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "secrets.json"


def _load_or_init_secrets() -> dict[str, str]:
    path = _secrets_file_path()
    data: dict[str, str] = {}

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, str):
                        data[k] = v
        except Exception:
            data = {}

    changed = False

    if not data.get("jwt_secret_key"):
        data["jwt_secret_key"] = secrets.token_urlsafe(48)
        changed = True

    if not data.get("refresh_token_pepper"):
        data["refresh_token_pepper"] = secrets.token_urlsafe(48)
        changed = True

    if not data.get("internal_runtime_notify_token"):
        data["internal_runtime_notify_token"] = secrets.token_urlsafe(48)
        changed = True

    if changed:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        tmp.replace(path)

    return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "casx-api"
    environment: str = "dev"

    scheduler_enabled: bool = True

    api_prefix: str = "/api"

    cors_origins: list[AnyUrl] = []

    media_proxy_image_cache_enabled: bool = True
    media_proxy_image_cache_ttl_seconds: int = 86400
    media_proxy_image_cache_max_file_bytes: int = 10 * 1024 * 1024
    media_proxy_image_cache_max_total_bytes: int = 512 * 1024 * 1024
    media_proxy_image_cache_dir: str | None = None

    app_data_dir: str = "./data"

    db_driver: str = "sqlite3"
    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")
    db_echo: bool = False

    sqlite_path: str = "./data/app.db"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "xxm"
    db_user: str = "root"
    db_password: str = ""
    db_charset: str = "utf8mb4"

    tasks_share_preview_batch_cache_ttl_seconds: int = 300
    tasks_share_preview_batch_cache_max_entries: int = 2000
    tasks_share_preview_batch_db_cache_ttl_seconds: int = 6 * 60 * 60
    tasks_share_preview_batch_db_cache_retention_seconds: int = 7 * 24 * 60 * 60

    drive_account_lsdir_cache_ttl_seconds: int = Field(
        default=2 * 60 * 60,
        validation_alias="DRIVE_ACCOUNT_LSDIR_CACHE_TTL_SECONDS",
    )
    drive_account_lsdir_cache_retention_seconds: int = 7 * 24 * 60 * 60
    drive_account_lsdir_scan_rate_limit_per_second: float = Field(
        default=1.0,
        validation_alias="DRIVE_ACCOUNT_LSDIR_SCAN_RATE_LIMIT_PER_SECOND",
    )

    drama_runtime_retry_max_attempts: int = 3
    drama_runtime_retry_backoff_seconds: float = 1.0
    drama_runtime_retry_max_backoff_seconds: float = 8.0
    drama_runtime_retry_jitter_ratio: float = 0.2

    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expires_seconds: int = 2 * 60 * 60

    refresh_token_expires_seconds: int = 14 * 24 * 60 * 60
    refresh_token_cookie_name: str = "refresh_token"
    refresh_token_cookie_secure: bool = False
    refresh_token_cookie_samesite: str = "lax"
    refresh_token_cookie_domain: str | None = None

    refresh_token_pepper: str | None = None
    internal_runtime_notify_token: str | None = None

    @property
    def database_url(self) -> str:
        override = str(self.database_url_override or "").strip()
        if override:
            return override

        driver = self.normalized_db_driver
        if driver == "mysql":
            user = quote_plus(str(self.db_user or "").strip())
            password = quote_plus(str(self.db_password or ""))
            auth = user if not password else f"{user}:{password}"
            host = str(self.db_host or "127.0.0.1").strip() or "127.0.0.1"
            name = str(self.db_name or "xxm").strip() or "xxm"
            charset = str(self.db_charset or "utf8mb4").strip() or "utf8mb4"
            return f"mysql+pymysql://{auth}@{host}:{int(self.db_port or 3306)}/{name}?charset={charset}"

        sqlite_path = self.resolved_sqlite_path
        return f"sqlite:///{sqlite_path}"

    @property
    def normalized_db_driver(self) -> str:
        raw = str(self.db_driver or "").strip().lower()
        if raw in {"mysql", "mysql+pymysql"}:
            return "mysql"
        return "sqlite3"

    @property
    def resolved_app_data_dir(self) -> str:
        raw = str(self.app_data_dir or "").strip() or "./data"
        return str((Path(__file__).resolve().parents[2] / raw).resolve()) if not os.path.isabs(raw) else raw

    @property
    def resolved_sqlite_path(self) -> str:
        raw = str(self.sqlite_path or "./data/app.db").strip() or "./data/app.db"
        if os.path.isabs(raw):
            return raw
        return str((Path(__file__).resolve().parents[2] / raw).resolve())

    def model_post_init(self, __context) -> None:
        secrets_data = _load_or_init_secrets()

        jwt = (self.jwt_secret_key or "").strip()
        pepper = (self.refresh_token_pepper or "").strip()
        internal_notify = (self.internal_runtime_notify_token or "").strip()

        if not jwt:
            self.jwt_secret_key = secrets_data["jwt_secret_key"]
        else:
            secrets_data["jwt_secret_key"] = jwt

        if not pepper:
            self.refresh_token_pepper = secrets_data["refresh_token_pepper"]
        else:
            secrets_data["refresh_token_pepper"] = pepper

        if not internal_notify:
            self.internal_runtime_notify_token = secrets_data["internal_runtime_notify_token"]
        else:
            secrets_data["internal_runtime_notify_token"] = internal_notify

        path = _secrets_file_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(secrets_data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        tmp.replace(path)


settings = Settings()
