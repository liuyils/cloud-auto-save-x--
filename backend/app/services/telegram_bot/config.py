from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.notifications.settings import get_runtime_notification_config


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    user_id: int
    api_host: str
    channel_enabled: bool
    proxy_scheme: str
    proxy_host: str
    proxy_port: str
    proxy_auth: str

    @property
    def enabled(self) -> bool:
        return bool(self.channel_enabled and self.token and self.user_id)


def load_telegram_bot_config(db: Session) -> TelegramBotConfig:
    config = get_runtime_notification_config(db)
    token = str(config.get("TG_BOT_TOKEN") or "").strip()
    user_id_raw = str(config.get("TG_USER_ID") or "").strip()
    api_host = str(config.get("TG_API_HOST") or "").strip() or "https://api.telegram.org"
    channel_enabled_map = config.get("__channel_enabled")
    channel_enabled = True
    if isinstance(channel_enabled_map, dict) and "telegram" in channel_enabled_map:
        channel_enabled = bool(channel_enabled_map.get("telegram"))
    proxy_scheme = str(config.get("TG_PROXY_SCHEME") or "").strip()
    proxy_host = str(config.get("TG_PROXY_HOST") or "").strip()
    proxy_port = str(config.get("TG_PROXY_PORT") or "").strip()
    proxy_auth = str(config.get("TG_PROXY_AUTH") or "").strip()
    try:
        user_id = int(user_id_raw)
    except Exception:
        user_id = 0
    return TelegramBotConfig(
        token=token,
        user_id=user_id,
        api_host=api_host.rstrip("/"),
        channel_enabled=channel_enabled,
        proxy_scheme=proxy_scheme,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        proxy_auth=proxy_auth,
    )
