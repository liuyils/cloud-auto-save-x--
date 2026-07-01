from __future__ import annotations

import ipaddress
from pathlib import PurePosixPath
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.dl302_setting import DL302Setting
from app.models.drive_account import DriveAccount


DL302_PROXY_URL_KEY = "ProxyURL"
DL302_PROXY_PATH_OFFSET_KEY = "ProxyPathOffset"
DL302_INTRANET_CIDRS_KEY = "IntranetCIDRs"
DL302_STRM_ENABLED_KEY = "StrmEnabled"
DL302_STRM_MODE_KEY = "StrmMode"
DL302_STRM_ROOT_DIR_KEY = "StrmRootDir"
DL302_STRM_PREFIX_URL_KEY = "StrmPrefixURL"
DL302_SUPPORTED_DRIVE_TYPES = ("115", "cloud189", "cloud139")
DL302_STRM_MODES = ("auto", "independent")
DL302_DEFAULT_INTRANET_CIDRS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)


def get_or_create_dl302_setting(db: Session) -> DL302Setting:
    item = db.execute(select(DL302Setting).order_by(DL302Setting.id.asc())).scalars().first()
    if item is None:
        item = DL302Setting(
            config_kv=serialize_dl302_config_kv(
                {DL302_INTRANET_CIDRS_KEY: ",".join(DL302_DEFAULT_INTRANET_CIDRS)}
            )
        )
        db.add(item)
        db.flush()
    return item


def parse_dl302_config_kv(config_kv: str | None) -> dict[str, str]:
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


def serialize_dl302_config_kv(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for key in (
        DL302_PROXY_URL_KEY,
        DL302_PROXY_PATH_OFFSET_KEY,
        DL302_INTRANET_CIDRS_KEY,
        DL302_STRM_ENABLED_KEY,
        DL302_STRM_MODE_KEY,
        DL302_STRM_ROOT_DIR_KEY,
        DL302_STRM_PREFIX_URL_KEY,
    ):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        parts.append(f"{key}={text}")
    return ";".join(parts)


def load_dl302_config(item: DL302Setting) -> dict[str, object]:
    payload = parse_dl302_config_kv(getattr(item, "config_kv", ""))
    offset_raw = str(payload.get(DL302_PROXY_PATH_OFFSET_KEY, "") or "").strip()
    try:
        proxy_path_offset = int(offset_raw) if offset_raw else -1
    except ValueError:
        proxy_path_offset = -1
    proxy_url = str(payload.get(DL302_PROXY_URL_KEY, "") or "").strip() or None
    intranet_cidrs = parse_intranet_cidrs(payload.get(DL302_INTRANET_CIDRS_KEY))
    strm_enabled_raw = str(payload.get(DL302_STRM_ENABLED_KEY, "") or "").strip().lower()
    strm_enabled = strm_enabled_raw in {"1", "true", "yes", "on"}
    strm_mode = str(payload.get(DL302_STRM_MODE_KEY, "") or "").strip().lower() or "auto"
    if strm_mode not in DL302_STRM_MODES:
        strm_mode = "auto"
    strm_root_dir = normalize_strm_root_dir(payload.get(DL302_STRM_ROOT_DIR_KEY)) or "/strm"
    strm_prefix_url = normalize_prefix_url(payload.get(DL302_STRM_PREFIX_URL_KEY))
    return {
        "proxy_url": proxy_url,
        "proxy_path_offset": proxy_path_offset,
        "intranet_cidrs": intranet_cidrs,
        "strm_enabled": strm_enabled,
        "strm_mode": strm_mode,
        "strm_root_dir": strm_root_dir,
        "strm_prefix_url": strm_prefix_url,
    }


def validate_proxy_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise bad_request("DL302_PROXY_URL_INVALID", "ProxyURL 必须是合法的 http/https 地址")
    return text


def parse_intranet_cidrs(value: object) -> list[str]:
    raw = value
    if raw is None:
        return list(DL302_DEFAULT_INTRANET_CIDRS)
    if isinstance(raw, (list, tuple, set)):
        parts = [str(v).strip() for v in raw]
    else:
        text = str(raw or "").strip()
        if not text:
            return list(DL302_DEFAULT_INTRANET_CIDRS)
        parts = [chunk.strip() for chunk in text.replace("\r\n", "\n").replace("\n", ",").split(",")]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        try:
            net = ipaddress.ip_network(part, strict=False)
        except ValueError:
            continue
        cidr = str(net)
        if cidr in seen:
            continue
        seen.add(cidr)
        out.append(cidr)
    return out or list(DL302_DEFAULT_INTRANET_CIDRS)


def validate_intranet_cidrs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [chunk.strip() for chunk in value.replace("\r\n", "\n").replace("\n", ",").split(",")]
    else:
        try:
            items = [str(v).strip() for v in list(value)]  # type: ignore[arg-type]
        except TypeError:
            raise bad_request("DL302_INTRANET_CIDRS_INVALID", "内网网段必须是 CIDR 列表")
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError as exc:
            raise bad_request("DL302_INTRANET_CIDRS_INVALID", f"CIDR 无效：{item}") from exc
        cidr = str(net)
        if cidr in seen:
            continue
        seen.add(cidr)
        out.append(cidr)
    return out


def normalize_prefix_url(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.rstrip("/")


def validate_strm_mode(value: object) -> str:
    text = str(value or "").strip().lower() or "auto"
    if text not in DL302_STRM_MODES:
        raise bad_request("DL302_STRM_MODE_INVALID", "STRM 模式仅支持 auto 或 independent")
    return text


def normalize_strm_root_dir(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.rstrip("/") or "/"


def validate_strm_root_dir(value: object) -> str:
    text = normalize_strm_root_dir(value)
    if not text or not text.startswith("/"):
        raise bad_request("DL302_STRM_ROOT_DIR_INVALID", "STRM 生成目录必须是绝对路径")
    try:
        path = str(PurePosixPath(text))
    except Exception as exc:  # pragma: no cover - PurePosixPath is deterministic
        raise bad_request("DL302_STRM_ROOT_DIR_INVALID", "STRM 生成目录格式无效") from exc
    return path.rstrip("/") or "/"


def validate_strm_prefix_url(value: object) -> str | None:
    text = normalize_prefix_url(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise bad_request("DL302_STRM_PREFIX_URL_INVALID", "STRM 前缀 URL 必须是合法的 http/https 地址")
    return text


def update_dl302_setting(db: Session, *, payload: dict[str, object]) -> DL302Setting:
    item = get_or_create_dl302_setting(db)
    current = parse_dl302_config_kv(item.config_kv)

    if "proxy_url" in payload:
        proxy_url = validate_proxy_url(payload.get("proxy_url"))
        if proxy_url is None:
            current.pop(DL302_PROXY_URL_KEY, None)
        else:
            current[DL302_PROXY_URL_KEY] = proxy_url

    if "proxy_path_offset" in payload:
        value = payload.get("proxy_path_offset")
        if value is None:
            current.pop(DL302_PROXY_PATH_OFFSET_KEY, None)
        else:
            current[DL302_PROXY_PATH_OFFSET_KEY] = str(int(value))

    if "intranet_cidrs" in payload:
        value = payload.get("intranet_cidrs")
        if value is None:
            current.pop(DL302_INTRANET_CIDRS_KEY, None)
        else:
            cidrs = validate_intranet_cidrs(value)
            if not cidrs:
                current.pop(DL302_INTRANET_CIDRS_KEY, None)
            else:
                current[DL302_INTRANET_CIDRS_KEY] = ",".join(cidrs)

    if "strm_enabled" in payload:
        value = payload.get("strm_enabled")
        if value is None:
            current.pop(DL302_STRM_ENABLED_KEY, None)
        else:
            current[DL302_STRM_ENABLED_KEY] = "true" if bool(value) else "false"

    if "strm_mode" in payload:
        value = payload.get("strm_mode")
        if value is None:
            current.pop(DL302_STRM_MODE_KEY, None)
        else:
            current[DL302_STRM_MODE_KEY] = validate_strm_mode(value)

    if "strm_root_dir" in payload:
        value = payload.get("strm_root_dir")
        if value is None:
            current.pop(DL302_STRM_ROOT_DIR_KEY, None)
        else:
            current[DL302_STRM_ROOT_DIR_KEY] = validate_strm_root_dir(value)

    if "strm_prefix_url" in payload:
        value = validate_strm_prefix_url(payload.get("strm_prefix_url"))
        if value is None:
            current.pop(DL302_STRM_PREFIX_URL_KEY, None)
        else:
            current[DL302_STRM_PREFIX_URL_KEY] = value

    item.config_kv = serialize_dl302_config_kv(current)
    db.flush()
    return item


def list_supported_dl302_drivers(db: Session) -> list[dict[str, object]]:
    accounts = db.execute(select(DriveAccount)).scalars().all()
    summary: dict[str, dict[str, object]] = {
        code: {
            "account_count": 0,
            "enabled_count": 0,
            "default_account_name": None,
        }
        for code in DL302_SUPPORTED_DRIVE_TYPES
    }
    for item in accounts:
        drive_type = str(getattr(item, "drive_type", "") or "")
        if drive_type not in summary:
            continue
        state = summary[drive_type]
        state["account_count"] = int(state["account_count"]) + 1
        if bool(getattr(item, "enabled", False)):
            state["enabled_count"] = int(state["enabled_count"]) + 1
        if bool(getattr(item, "is_default", False)):
            state["default_account_name"] = str(getattr(item, "name", "") or "").strip() or None

    return [
        {
            "code": code,
            "drive_name": str(AdapterRegistry.get_drive_type_meta(code).get("drive_name") or code),
            **summary[code],
        }
        for code in DL302_SUPPORTED_DRIVE_TYPES
    ]


def supported_dl302_drive_types() -> tuple[str, ...]:
    return tuple(DL302_SUPPORTED_DRIVE_TYPES)
