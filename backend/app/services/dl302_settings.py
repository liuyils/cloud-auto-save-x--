from __future__ import annotations

import ipaddress
import json
from pathlib import PurePosixPath
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.dl302_setting import DL302Setting
from app.models.drive_account import DriveAccount
from app.services.drive_accounts import serialize_drive_account


DL302_PROXY_URL_KEY = "ProxyURL"
DL302_PROXY_PATH_OFFSET_KEY = "ProxyPathOffset"
DL302_INTRANET_CIDRS_KEY = "IntranetCIDRs"
DL302_AUTO_BALANCE_KEY = "AutoBalance"
DL302_COPY_DOWNLOAD_MODE_KEY = "CopyDownloadMode"
DL302_STRM_ENABLED_KEY = "StrmEnabled"
DL302_STRM_MODE_KEY = "StrmMode"
DL302_STRM_ROOT_DIR_KEY = "StrmRootDir"
DL302_STRM_PREFIX_URL_KEY = "StrmPrefixURL"
DL302_STRM_INCLUDE_CAS_ROOT_KEY = "StrmIncludeCASRootDir"
DL302_STRM_SOURCE_PRIORITY_KEY = "StrmSourcePriority"
DL302_CAS_ROOT_DIR_KEY = "CASRootDir"
DL302_CAS_WORKERS_KEY = "CASWorkers"
DL302_ACCOUNT_LSDIR_CACHE_PATH_KEY = "lsdir_cache_path"
DL302_ACCOUNT_STATIC_LSDIR_CACHE_PATH_KEY = "static_lsdir_cache_path"
DL302_ACCOUNT_STRM_SCAN_PATH_KEY = "strm_scan_path"
DL302_ACCOUNT_LEGACY_MEDIA_PATH_KEY = "302_path"
DL302_SUPPORTED_DRIVE_TYPES = ("115", "cloud189", "cloud139", "quark", "uc")
DL302_STRM_MODES = ("auto", "independent")
DL302_STRM_SOURCE_PRIORITIES = ("video_first", "cas_first")
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
        DL302_AUTO_BALANCE_KEY,
        DL302_COPY_DOWNLOAD_MODE_KEY,
        DL302_STRM_ENABLED_KEY,
        DL302_STRM_MODE_KEY,
        DL302_STRM_ROOT_DIR_KEY,
        DL302_STRM_PREFIX_URL_KEY,
        DL302_STRM_INCLUDE_CAS_ROOT_KEY,
        DL302_STRM_SOURCE_PRIORITY_KEY,
        DL302_CAS_ROOT_DIR_KEY,
        DL302_CAS_WORKERS_KEY,
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
    auto_balance_raw = str(payload.get(DL302_AUTO_BALANCE_KEY, "") or "").strip().lower()
    auto_balance = auto_balance_raw in {"1", "true", "yes", "on"}
    copy_download_mode_raw = str(payload.get(DL302_COPY_DOWNLOAD_MODE_KEY, "") or "").strip()
    copy_download_mode = "1" if copy_download_mode_raw == "1" else "0"
    strm_enabled_raw = str(payload.get(DL302_STRM_ENABLED_KEY, "") or "").strip().lower()
    strm_enabled = strm_enabled_raw in {"1", "true", "yes", "on"}
    strm_mode = str(payload.get(DL302_STRM_MODE_KEY, "") or "").strip().lower() or "auto"
    if strm_mode not in DL302_STRM_MODES:
        strm_mode = "auto"
    strm_root_dir = normalize_strm_root_dir(payload.get(DL302_STRM_ROOT_DIR_KEY)) or "/strm"
    strm_prefix_url = normalize_prefix_url(payload.get(DL302_STRM_PREFIX_URL_KEY))
    strm_include_cas_root_raw = str(payload.get(DL302_STRM_INCLUDE_CAS_ROOT_KEY, "") or "").strip().lower()
    strm_include_cas_root = strm_include_cas_root_raw in {"1", "true", "yes", "on"}
    strm_source_priority = str(payload.get(DL302_STRM_SOURCE_PRIORITY_KEY, "") or "").strip().lower() or "video_first"
    if strm_source_priority not in DL302_STRM_SOURCE_PRIORITIES:
        strm_source_priority = "video_first"
    cas_root_dir = normalize_cas_root_dir(payload.get(DL302_CAS_ROOT_DIR_KEY))
    cas_workers_raw = str(payload.get(DL302_CAS_WORKERS_KEY, "") or "").strip()
    try:
        cas_workers = int(cas_workers_raw) if cas_workers_raw else 4
    except ValueError:
        cas_workers = 4
    if cas_workers <= 0:
        cas_workers = 4
    return {
        "proxy_url": proxy_url,
        "proxy_path_offset": proxy_path_offset,
        "intranet_cidrs": intranet_cidrs,
        "auto_balance": auto_balance,
        "copy_download_mode": copy_download_mode,
        "strm_enabled": strm_enabled,
        "strm_mode": strm_mode,
        "strm_root_dir": strm_root_dir,
        "strm_prefix_url": strm_prefix_url,
        "strm_include_cas_root_dir": strm_include_cas_root,
        "strm_source_priority": strm_source_priority,
        "cas_root_dir": cas_root_dir,
        "cas_workers": cas_workers,
        "proxy_targets": parse_proxy_targets_json(getattr(item, "proxy_targets_json", None)),
    }


def validate_proxy_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise bad_request("DL302_PROXY_URL_INVALID", "ProxyURL 必须是合法的 http/https 地址")
    return text


DL302_PROXY_TARGET_TYPES = ("fnos", "emby", "jellyfin", "generic")


def parse_proxy_targets_json(raw: str | None) -> list[dict]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        items = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("id") or "").strip()
        if not target_id:
            continue
        out.append({
            "id": target_id,
            "name": str(item.get("name") or "").strip(),
            "type": str(item.get("type") or "generic").strip(),
            "target_url": str(item.get("target_url") or "").strip(),
            "listen_addr": str(item.get("listen_addr") or "").strip(),
            "path_offset": int(item.get("path_offset") or 0),
            "enabled": bool(item.get("enabled", True)),
        })
    return out


def validate_proxy_targets(targets: list[dict] | None) -> str | None:
    """Validate and serialize proxy targets to JSON string."""
    if targets is None:
        return None
    if not targets:
        return "[]"
    import uuid as uuid_mod
    seen_addrs: set[str] = set()
    out: list[dict] = []
    for item in targets:
        target_id = str(item.get("id") or "").strip()
        if not target_id:
            target_id = str(uuid_mod.uuid4())
        name = str(item.get("name") or "").strip()
        if not name:
            raise bad_request("DL302_PROXY_TARGET_NAME_EMPTY", "反代目标名称不能为空")
        target_type = str(item.get("type") or "generic").strip().lower()
        if target_type not in DL302_PROXY_TARGET_TYPES:
            raise bad_request("DL302_PROXY_TARGET_TYPE_INVALID", f"反代目标类型不合法: {target_type}")
        target_url = str(item.get("target_url") or "").strip()
        if target_url:
            parsed = urlparse(target_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise bad_request("DL302_PROXY_TARGET_URL_INVALID", f"反代目标地址不合法: {target_url}")
        listen_addr = str(item.get("listen_addr") or "").strip()
        if not listen_addr:
            raise bad_request("DL302_PROXY_TARGET_LISTEN_ADDR_EMPTY", "反代目标监听地址不能为空")
        # Auto-prepend colon if user only entered a port number.
        if listen_addr.isdigit():
            listen_addr = ":" + listen_addr
        elif not listen_addr.startswith(":") and ":" not in listen_addr:
            listen_addr = ":" + listen_addr
        if listen_addr in seen_addrs:
            raise bad_request("DL302_PROXY_TARGET_LISTEN_ADDR_DUPLICATE", f"反代目标监听地址重复: {listen_addr}")
        seen_addrs.add(listen_addr)
        path_offset = int(item.get("path_offset") or 0)
        enabled = bool(item.get("enabled", True))
        out.append({
            "id": target_id,
            "name": name,
            "type": target_type,
            "target_url": target_url,
            "listen_addr": listen_addr,
            "path_offset": path_offset,
            "enabled": enabled,
        })
    return json.dumps(out, ensure_ascii=False)


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


def validate_strm_source_priority(value: object) -> str:
    text = str(value or "").strip().lower() or "video_first"
    if text not in DL302_STRM_SOURCE_PRIORITIES:
        raise bad_request("DL302_STRM_SOURCE_PRIORITY_INVALID", "STRM 源优先级仅支持 video_first 或 cas_first")
    return text


def normalize_strm_root_dir(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.rstrip("/") or "/"


def normalize_cas_root_dir(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith("/"):
        text = "/" + text.lstrip("/")
    try:
        path = str(PurePosixPath(text))
    except Exception:
        return None
    return path.rstrip("/") or "/"


def validate_cas_root_dir(value: object) -> str:
    text = normalize_cas_root_dir(value)
    if not text or not text.startswith("/"):
        raise bad_request("DL302_CAS_ROOT_DIR_INVALID", "CASRootDir 必须是绝对路径")
    return text.rstrip("/") or "/"


def validate_cas_workers(value: object) -> int:
    try:
        workers = int(value)
    except (TypeError, ValueError) as exc:
        raise bad_request("DL302_CAS_WORKERS_INVALID", "CAS workers 必须是正整数") from exc
    if workers <= 0:
        raise bad_request("DL302_CAS_WORKERS_INVALID", "CAS workers 必须是正整数")
    return workers


def _normalize_account_posix_path(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        path = str(PurePosixPath(text))
    except Exception:
        return None
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return path.rstrip("/") or "/"


def _normalize_account_posix_paths(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = str(value or "").split(",")
    paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        path = _normalize_account_posix_path(raw)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _load_drive_account_config(account: DriveAccount) -> dict[str, object]:
    payload = str(getattr(account, "config_json", "") or "").strip()
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def extract_dl302_cache_base_path(account: DriveAccount) -> str | None:
    data = _load_drive_account_config(account)
    return _normalize_account_posix_path(
        data.get(DL302_ACCOUNT_LSDIR_CACHE_PATH_KEY) or data.get(DL302_ACCOUNT_LEGACY_MEDIA_PATH_KEY)
    )


def extract_dl302_static_cache_base_path(account: DriveAccount) -> str | None:
    data = _load_drive_account_config(account)
    return _normalize_account_posix_path(data.get(DL302_ACCOUNT_STATIC_LSDIR_CACHE_PATH_KEY))


def extract_dl302_lsdir_scan_scope(account: DriveAccount) -> dict[str, str | bool | None]:
    cache_base_path = extract_dl302_cache_base_path(account)
    static_cache_base_path = extract_dl302_static_cache_base_path(account)
    static_within_cache = False
    if cache_base_path and static_cache_base_path:
        static_within_cache = (
            static_cache_base_path == cache_base_path
            or static_cache_base_path.startswith(f"{cache_base_path.rstrip('/')}/")
        )
    return {
        "cache_base_path": cache_base_path,
        "static_cache_base_path": static_cache_base_path,
        "static_within_cache": static_within_cache,
    }


def build_dl302_static_lsdir_signature(account: DriveAccount) -> str | None:
    static_path = extract_dl302_static_cache_base_path(account)
    if not static_path:
        return None
    account_id = int(getattr(account, "id", 0) or 0)
    drive_type = str(getattr(account, "drive_type", "") or "").strip().lower()
    return f"{account_id}:{drive_type}:{static_path}"


def extract_dl302_strm_scan_base_paths(account: DriveAccount) -> list[str]:
    data = _load_drive_account_config(account)
    paths = _normalize_account_posix_paths(data.get(DL302_ACCOUNT_STRM_SCAN_PATH_KEY))
    if paths:
        return paths
    cache_base_path = extract_dl302_cache_base_path(account)
    if cache_base_path:
        return [cache_base_path]
    legacy_path = _normalize_account_posix_path(data.get(DL302_ACCOUNT_LEGACY_MEDIA_PATH_KEY))
    if legacy_path:
        return [legacy_path]
    return []


def extract_dl302_strm_scan_base_path(account: DriveAccount) -> str | None:
    paths = extract_dl302_strm_scan_base_paths(account)
    if not paths:
        return None
    return paths[0]


def extract_dl302_sync_base_path(account: DriveAccount) -> str | None:
    return extract_dl302_cache_base_path(account)


def extract_dl302_cas_base_path(account: DriveAccount) -> str | None:
    return extract_dl302_strm_scan_base_path(account)


def extract_dl302_cas_base_paths(account: DriveAccount) -> list[str]:
    return extract_dl302_strm_scan_base_paths(account)


def extract_dl302_media_base_path(account: DriveAccount) -> str | None:
    return extract_dl302_cache_base_path(account)


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

    if "auto_balance" in payload:
        value = payload.get("auto_balance")
        if value is None:
            current.pop(DL302_AUTO_BALANCE_KEY, None)
        else:
            current[DL302_AUTO_BALANCE_KEY] = "true" if bool(value) else "false"

    if "copy_download_mode" in payload:
        value = str(payload.get("copy_download_mode") or "").strip()
        if value not in {"0", "1"}:
            raise bad_request("DL302_COPY_DOWNLOAD_MODE_INVALID", "复制方式仅支持 0(流式) 或 1(下载)")
        current[DL302_COPY_DOWNLOAD_MODE_KEY] = value

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

    if "strm_include_cas_root_dir" in payload:
        value = payload.get("strm_include_cas_root_dir")
        if value is None:
            current.pop(DL302_STRM_INCLUDE_CAS_ROOT_KEY, None)
        else:
            current[DL302_STRM_INCLUDE_CAS_ROOT_KEY] = "true" if bool(value) else "false"

    if "strm_source_priority" in payload:
        value = payload.get("strm_source_priority")
        if value is None:
            current.pop(DL302_STRM_SOURCE_PRIORITY_KEY, None)
        else:
            current[DL302_STRM_SOURCE_PRIORITY_KEY] = validate_strm_source_priority(value)

    if "cas_root_dir" in payload:
        value = payload.get("cas_root_dir")
        if value is None:
            current.pop(DL302_CAS_ROOT_DIR_KEY, None)
        else:
            current[DL302_CAS_ROOT_DIR_KEY] = validate_cas_root_dir(value)

    if "cas_workers" in payload:
        value = payload.get("cas_workers")
        if value is None:
            current.pop(DL302_CAS_WORKERS_KEY, None)
        else:
            current[DL302_CAS_WORKERS_KEY] = str(validate_cas_workers(value))

    if "proxy_targets" in payload:
        targets_raw = payload.get("proxy_targets")
        if targets_raw is None:
            item.proxy_targets_json = None
        else:
            targets_list = [
                (t.model_dump() if hasattr(t, "model_dump") else dict(t))
                for t in targets_raw
            ] if not isinstance(targets_raw, list) else [
                (t.model_dump() if hasattr(t, "model_dump") else dict(t)) if not isinstance(t, dict) else t
                for t in targets_raw
            ]
            validated_json = validate_proxy_targets(targets_list)
            item.proxy_targets_json = validated_json

    item.config_kv = serialize_dl302_config_kv(current)
    db.flush()
    return item


def list_supported_dl302_drivers(db: Session) -> list[dict[str, object]]:
    from app.services.dl302_cas import get_dl302_cas_task_summary

    accounts = db.execute(select(DriveAccount)).scalars().all()
    summary: dict[str, dict[str, object]] = {
        code: {
            "account_count": 0,
            "enabled_count": 0,
            "default_account_name": None,
            "accounts": [],
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
        account_data = serialize_drive_account(item)
        profile = dict(account_data.get("profile") or {})
        cache_base_path = extract_dl302_cache_base_path(item)
        strm_scan_base_paths = extract_dl302_strm_scan_base_paths(item)
        strm_scan_base_path = ",".join(strm_scan_base_paths) if strm_scan_base_paths else None
        state["accounts"].append(
            {
                "account_id": int(account_data.get("id") or 0),
                "account_name": str(account_data.get("name") or ""),
                "drive_type": drive_type,
                "drive_name": str(profile.get("drive_name") or AdapterRegistry.get_drive_type_meta(drive_type).get("drive_name") or drive_type),
                "enabled": bool(account_data.get("enabled")),
                "is_default": bool(account_data.get("is_default")),
                "runtime_status": account_data.get("runtime_status"),
                "nickname": str(profile.get("nickname") or "").strip() or None,
                "username": str(profile.get("username") or "").strip() or None,
                "has_302_path": bool(cache_base_path),
                "media_base_path": strm_scan_base_path,
                "cache_base_path": cache_base_path,
                "strm_scan_base_path": strm_scan_base_path,
                "cas_task": get_dl302_cas_task_summary(int(account_data.get("id") or 0), db),
            }
        )

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
