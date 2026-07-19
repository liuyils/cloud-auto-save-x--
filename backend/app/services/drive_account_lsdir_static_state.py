from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from app.core.settings import settings


def _now() -> datetime:
    return datetime.now()


def _resolve_drive_account_lsdir_state_base_dir() -> str:
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if database_url.startswith("sqlite") and "///" in database_url:
        path = database_url.split("///", 1)[1]
        directory = os.path.dirname(path) or settings.resolved_app_data_dir
        return os.path.join(directory, "cache")
    return os.path.join(settings.resolved_app_data_dir, "cache")


def resolve_drive_account_lsdir_static_state_dir() -> str:
    return os.path.join(_resolve_drive_account_lsdir_state_base_dir(), "drive_account_lsdir_static")


def resolve_drive_account_lsdir_scan_state_dir() -> str:
    return os.path.join(_resolve_drive_account_lsdir_state_base_dir(), "drive_account_lsdir_scan")


def ensure_drive_account_lsdir_static_state_dir() -> str:
    path = resolve_drive_account_lsdir_static_state_dir()
    os.makedirs(path, exist_ok=True)
    return path


def ensure_drive_account_lsdir_scan_state_dir() -> str:
    path = resolve_drive_account_lsdir_scan_state_dir()
    os.makedirs(path, exist_ok=True)
    return path


def build_drive_account_lsdir_static_state_path(account_id: int, drive_type: str) -> str:
    safe_drive_type = str(drive_type or "").strip().lower() or "unknown"
    filename = f"account_{int(account_id)}_{safe_drive_type}.json"
    return os.path.join(ensure_drive_account_lsdir_static_state_dir(), filename)


def build_drive_account_lsdir_scan_state_path(account_id: int, drive_type: str) -> str:
    safe_drive_type = str(drive_type or "").strip().lower() or "unknown"
    filename = f"account_{int(account_id)}_{safe_drive_type}.json"
    return os.path.join(ensure_drive_account_lsdir_scan_state_dir(), filename)


def _load_state(path: str) -> dict[str, Any] | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_static_scan_state(account_id: int, drive_type: str) -> dict[str, Any] | None:
    return _load_state(build_drive_account_lsdir_static_state_path(account_id, drive_type))


def load_lsdir_scan_state(account_id: int, drive_type: str) -> dict[str, Any] | None:
    return _load_state(build_drive_account_lsdir_scan_state_path(account_id, drive_type))


def _write_state(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return payload


def _write_static_scan_state(account_id: int, drive_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _write_state(build_drive_account_lsdir_static_state_path(account_id, drive_type), payload)


def _write_lsdir_scan_state(account_id: int, drive_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _write_state(build_drive_account_lsdir_scan_state_path(account_id, drive_type), payload)


def mark_static_scan_running(account_id: int, drive_type: str, *, static_path: str, signature: str | None) -> dict[str, Any]:
    existing = load_static_scan_state(account_id, drive_type) or {}
    now = _now().isoformat()
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "static_path": str(static_path or ""),
        "signature": signature,
        "status": "running",
        "started_at": now,
        "completed_at": existing.get("completed_at"),
        "last_error": None,
    }
    return _write_static_scan_state(account_id, drive_type, payload)


def mark_static_scan_completed(account_id: int, drive_type: str, *, static_path: str, signature: str | None) -> dict[str, Any]:
    existing = load_static_scan_state(account_id, drive_type) or {}
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "static_path": str(static_path or ""),
        "signature": signature,
        "status": "completed",
        "started_at": existing.get("started_at"),
        "completed_at": _now().isoformat(),
        "last_error": None,
    }
    return _write_static_scan_state(account_id, drive_type, payload)


def mark_static_scan_failed(
    account_id: int,
    drive_type: str,
    *,
    static_path: str,
    signature: str | None,
    error: str,
) -> dict[str, Any]:
    existing = load_static_scan_state(account_id, drive_type) or {}
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "static_path": str(static_path or ""),
        "signature": signature,
        "status": "failed",
        "started_at": existing.get("started_at") or _now().isoformat(),
        "completed_at": None,
        "last_error": str(error or "").strip() or None,
    }
    return _write_static_scan_state(account_id, drive_type, payload)


def clear_static_scan_state(account_id: int, drive_type: str) -> bool:
    path = build_drive_account_lsdir_static_state_path(account_id, drive_type)
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def should_rescan_static_path(
    account_id: int,
    drive_type: str,
    *,
    static_path: str | None,
    signature: str | None,
) -> bool:
    target_path = str(static_path or "").strip()
    if not target_path:
        return False
    state = load_static_scan_state(account_id, drive_type)
    if not state:
        return True
    if str(state.get("static_path") or "").strip() != target_path:
        return True
    if str(state.get("signature") or "").strip() != str(signature or "").strip():
        return True
    return str(state.get("status") or "").strip().lower() != "completed"


def mark_lsdir_scan_running(account_id: int, drive_type: str, *, base_path: str, signature: str | None) -> dict[str, Any]:
    existing = load_lsdir_scan_state(account_id, drive_type) or {}
    now = _now().isoformat()
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "base_path": str(base_path or ""),
        "signature": signature,
        "status": "running",
        "started_at": now,
        "completed_at": existing.get("completed_at"),
        "last_error": None,
    }
    return _write_lsdir_scan_state(account_id, drive_type, payload)


def mark_lsdir_scan_completed(account_id: int, drive_type: str, *, base_path: str, signature: str | None) -> dict[str, Any]:
    existing = load_lsdir_scan_state(account_id, drive_type) or {}
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "base_path": str(base_path or ""),
        "signature": signature,
        "status": "completed",
        "started_at": existing.get("started_at"),
        "completed_at": _now().isoformat(),
        "last_error": None,
    }
    return _write_lsdir_scan_state(account_id, drive_type, payload)


def mark_lsdir_scan_failed(
    account_id: int,
    drive_type: str,
    *,
    base_path: str,
    signature: str | None,
    error: str,
) -> dict[str, Any]:
    existing = load_lsdir_scan_state(account_id, drive_type) or {}
    payload = {
        "account_id": int(account_id),
        "drive_type": str(drive_type or ""),
        "base_path": str(base_path or ""),
        "signature": signature,
        "status": "failed",
        "started_at": existing.get("started_at") or _now().isoformat(),
        "completed_at": None,
        "last_error": str(error or "").strip() or None,
    }
    return _write_lsdir_scan_state(account_id, drive_type, payload)


def clear_lsdir_scan_state(account_id: int, drive_type: str) -> bool:
    path = build_drive_account_lsdir_scan_state_path(account_id, drive_type)
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def should_rescan_lsdir_path(
    account_id: int,
    drive_type: str,
    *,
    base_path: str | None,
    signature: str | None,
) -> bool:
    target_path = str(base_path or "").strip()
    if not target_path:
        return False
    state = load_lsdir_scan_state(account_id, drive_type)
    if not state:
        return True
    if str(state.get("base_path") or "").strip() != target_path:
        return True
    if str(state.get("signature") or "").strip() != str(signature or "").strip():
        return True
    return str(state.get("status") or "").strip().lower() != "completed"
