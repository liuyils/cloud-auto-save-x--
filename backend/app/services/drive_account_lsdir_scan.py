from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.settings import settings
from app.db.session import SessionLocal
from app.extensions.adapters.adapter_factory import AdapterFactory
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.services.drive_account_lsdir_cache import (
    delete_drive_account_lsdir_cache_by_account,
    delete_drive_account_lsdir_cache_by_path,
    delete_drive_account_lsdir_cache_subtree_by_path,
    get_drive_account_lsdir_cache_freshness,
    purge_expired_drive_account_lsdir_cache,
    purge_old_drive_account_lsdir_cache,
    _join_full_path,
    _normalize_parent_path,
    upsert_drive_account_lsdir_items,
)
from app.services.dl302_settings import extract_dl302_media_base_path, get_or_create_dl302_setting, load_dl302_config
from app.services.dl302_strm import maybe_auto_generate_dl302_strm


logger = logging.getLogger(__name__)

_running_accounts: set[int] = set()
_running_accounts_lock = threading.Lock()
_last_request_at: dict[int, float] = {}
_last_request_lock = threading.Lock()


@dataclass
class ScanStats:
    scanned_dirs: int = 0
    cached_items: int = 0


@dataclass
class ScanAccountContext:
    account_id: int
    account_name: str
    drive_type: str
    runtime_config: dict[str, Any]
    runtime_cookie: str


class DirectoryScanError(RuntimeError):
    def __init__(self, fid: str, message: str):
        super().__init__(message)
        self.fid = str(fid or "")


def _build_target_paths(savepath: str, relative_dir_paths: list[str] | None, *, recursive_savepath: bool) -> list[tuple[str, bool]]:
    normalized_savepath = _normalize_parent_path(savepath)
    target_paths: list[tuple[str, bool]] = [(normalized_savepath, bool(recursive_savepath))]
    seen_paths = {normalized_savepath}
    for raw in relative_dir_paths or []:
        relative = str(raw or "").strip().strip("/")
        full_path = normalized_savepath if not relative else _join_full_path(normalized_savepath, relative)
        if full_path in seen_paths:
            continue
        seen_paths.add(full_path)
        target_paths.append((full_path, True))
    return target_paths


def _append_cas_root_dir_target_paths(target_paths: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    with SessionLocal() as db:
        setting = get_or_create_dl302_setting(db)
        config = load_dl302_config(setting)
    cas_root_dir = str(config.get("cas_root_dir") or "").strip()
    if not cas_root_dir:
        return target_paths
    cas_root_dir = _normalize_parent_path(cas_root_dir)
    if not cas_root_dir:
        return target_paths
    if any(path == cas_root_dir for path, _recursive in target_paths):
        return target_paths
    target_paths.append((cas_root_dir, True))
    return target_paths


def trigger_drive_account_lsdir_scan(account_id: int, source: str) -> bool:
    account_key = int(account_id)
    with _running_accounts_lock:
        if account_key in _running_accounts:
            logger.info("drive account lsdir scan skipped: already running account_id=%s source=%s", account_key, source)
            return False
        _running_accounts.add(account_key)

    thread = threading.Thread(
        target=_scan_drive_account_worker,
        args=(account_key, str(source or "")),
        name=f"drive-account-lsdir-scan-{account_key}",
        daemon=True,
    )
    thread.start()
    return True


def trigger_drive_account_lsdir_scan_if_stale(account_id: int, source: str, *, force: bool = False) -> bool:
    account_key = int(account_id)
    if not force:
        with SessionLocal() as db:
            freshness = get_drive_account_lsdir_cache_freshness(db, account_id=account_key)
            if bool(freshness.get("is_fresh")):
                logger.info(
                    "drive account lsdir scan skipped: cache fresh account_id=%s source=%s expires_at=%s total=%s",
                    account_key,
                    source,
                    freshness.get("expires_at"),
                    freshness.get("total"),
                )
                return False
    return trigger_drive_account_lsdir_scan(account_key, source)


def trigger_drive_account_lsdir_targeted_scan(
    account_id: int,
    *,
    savepath: str,
    relative_dir_paths: list[str] | None,
    source: str,
    recursive_savepath: bool = False,
) -> bool:
    account_key = int(account_id)
    normalized_savepath = _normalize_parent_path(savepath)
    target_paths = _append_cas_root_dir_target_paths(
        _build_target_paths(normalized_savepath, relative_dir_paths, recursive_savepath=recursive_savepath)
    )

    with _running_accounts_lock:
        if account_key in _running_accounts:
            logger.info(
                "drive account lsdir targeted scan skipped: already running account_id=%s source=%s savepath=%s",
                account_key,
                source,
                normalized_savepath,
            )
            return False
        _running_accounts.add(account_key)

    thread = threading.Thread(
        target=_scan_drive_account_targeted_worker,
        args=(account_key, str(source or ""), target_paths),
        name=f"drive-account-lsdir-targeted-scan-{account_key}",
        daemon=True,
    )
    thread.start()
    return True


def rebuild_drive_account_lsdir_cache_for_current_302_path(account_id: int, source: str) -> dict[str, Any]:
    account_key = int(account_id)
    with SessionLocal() as db:
        account = db.get(DriveAccount, account_key)
        if account is None:
            return {
                "account_id": account_key,
                "cleared": 0,
                "queued": False,
                "base_path": None,
                "reason": "account_not_found",
            }
        base_path = extract_dl302_media_base_path(account)
        cleared = delete_drive_account_lsdir_cache_by_account(db, account_key)
        db.commit()

    if not base_path:
        logger.info(
            "drive account lsdir rebuild skipped: missing 302_path account_id=%s source=%s cleared=%s",
            account_key,
            source,
            cleared,
        )
        return {
            "account_id": account_key,
            "cleared": int(cleared or 0),
            "queued": False,
            "base_path": None,
            "reason": "missing_302_path",
        }

    queued = trigger_drive_account_lsdir_targeted_scan(
        account_key,
        savepath=base_path,
        relative_dir_paths=None,
        recursive_savepath=True,
        source=source,
    )
    reason = "queued" if queued else "running"
    logger.info(
        "drive account lsdir rebuild requested account_id=%s source=%s cleared=%s queued=%s base_path=%s reason=%s",
        account_key,
        source,
        cleared,
        queued,
        base_path,
        reason,
    )
    return {
        "account_id": account_key,
        "cleared": int(cleared or 0),
        "queued": bool(queued),
        "base_path": str(base_path),
        "reason": reason,
    }


def refresh_drive_account_lsdir_paths(
    account_id: int,
    *,
    savepath: str,
    relative_dir_paths: list[str] | None,
    source: str,
    recursive_savepath: bool = False,
    wait_if_busy: bool = False,
    max_wait_seconds: float = 30.0,
) -> ScanStats:
    account_key = int(account_id)
    normalized_savepath = _normalize_parent_path(savepath)
    target_paths = _append_cas_root_dir_target_paths(
        _build_target_paths(normalized_savepath, relative_dir_paths, recursive_savepath=recursive_savepath)
    )

    waited = 0.0
    while True:
        with _running_accounts_lock:
            if account_key not in _running_accounts:
                _running_accounts.add(account_key)
                break
        if not bool(wait_if_busy):
            raise RuntimeError(f"drive account lsdir targeted scan busy account_id={account_key} savepath={normalized_savepath}")
        if waited >= float(max_wait_seconds or 0):
            raise RuntimeError(
                f"drive account lsdir targeted scan busy account_id={account_key} savepath={normalized_savepath} waited={waited}"
            )
        time.sleep(0.2)
        waited += 0.2

    started_at = time.monotonic()
    failed_fid: str | None = None
    stats = ScanStats()
    try:
        context = _load_scan_account_context(account_id=account_key, source=source, scan_label="sync targeted scan")
        if context is None:
            raise RuntimeError(f"drive account unavailable account_id={account_key}")
        adapter = AdapterFactory.create_adapter(
            context.drive_type,
            context.runtime_cookie,
            config=context.runtime_config,
            account_name=context.account_name,
        )
        if adapter is None:
            raise RuntimeError(f"drive account adapter unavailable account_id={account_key} drive_type={context.drive_type}")
        if not getattr(adapter, "is_active", False):
            ok = adapter.init()
            if not ok:
                raise RuntimeError(f"drive account adapter init failed account_id={account_key} drive_type={context.drive_type}")
        with SessionLocal() as db:
            purge_expired_drive_account_lsdir_cache(db)
            db.commit()
        stats = _refresh_account_paths(account_id=context.account_id, drive_type=context.drive_type, adapter=adapter, target_paths=target_paths)
        with SessionLocal() as db:
            _trigger_dl302_strm_after_scan(db=db, source=f"{source}.sync_targeted")
            db.commit()
        return stats
    except Exception as exc:
        failed_fid = getattr(exc, "fid", None) or failed_fid
        logger.exception(
            "drive account lsdir sync targeted scan failed account_id=%s source=%s failed_fid=%s target_paths=%s",
            account_key,
            source,
            failed_fid,
            [path for path, _recursive in target_paths],
        )
        raise
    finally:
        with _running_accounts_lock:
            _running_accounts.discard(account_key)
        logger.info(
            "drive account lsdir sync targeted scan finished account_id=%s source=%s scanned_dirs=%s cached_items=%s duration_ms=%s failed_fid=%s target_paths=%s",
            account_key,
            source,
            stats.scanned_dirs,
            stats.cached_items,
            int((time.monotonic() - started_at) * 1000),
            failed_fid or "",
            [path for path, _recursive in target_paths],
        )


def _scan_drive_account_worker(account_id: int, source: str) -> None:
    started_at = time.monotonic()
    failed_fid: str | None = None
    stats = ScanStats()
    try:
        context = _load_scan_account_context(account_id=account_id, source=source, scan_label="scan")
        if context is None:
            return
        adapter = AdapterFactory.create_adapter(
            context.drive_type,
            context.runtime_cookie,
            config=context.runtime_config,
            account_name=context.account_name,
        )
        if adapter is None:
            logger.warning(
                "drive account lsdir scan aborted: adapter unavailable account_id=%s account_name=%s drive_type=%s source=%s",
                account_id,
                context.account_name,
                context.drive_type,
                source,
            )
            return
        if not getattr(adapter, "is_active", False):
            ok = adapter.init()
            if not ok:
                logger.warning(
                    "drive account lsdir scan aborted: adapter init failed account_id=%s account_name=%s drive_type=%s source=%s",
                    account_id,
                    context.account_name,
                    context.drive_type,
                    source,
                )
                return
        with SessionLocal() as db:
            purge_expired_drive_account_lsdir_cache(db)
            db.commit()
        stats = _walk_account_tree(account_id=context.account_id, drive_type=context.drive_type, adapter=adapter)
        with SessionLocal() as db:
            purge_old_drive_account_lsdir_cache(
                db,
                retention_seconds=int(getattr(settings, "drive_account_lsdir_cache_retention_seconds", 7 * 24 * 60 * 60) or 7 * 24 * 60 * 60),
            )
            db.commit()
        with SessionLocal() as db:
            _trigger_dl302_strm_after_scan(db=db, source=f"{source}.full")
            db.commit()
    except Exception as exc:
        failed_fid = getattr(exc, "fid", None) or failed_fid
        logger.exception(
            "drive account lsdir scan failed account_id=%s source=%s failed_fid=%s",
            account_id,
            source,
            failed_fid,
        )
    finally:
        with _running_accounts_lock:
            _running_accounts.discard(int(account_id))
        logger.info(
            "drive account lsdir scan finished account_id=%s source=%s scanned_dirs=%s cached_items=%s duration_ms=%s failed_fid=%s",
            account_id,
            source,
            stats.scanned_dirs,
            stats.cached_items,
            int((time.monotonic() - started_at) * 1000),
            failed_fid or "",
        )


def _scan_drive_account_targeted_worker(account_id: int, source: str, target_paths: list[tuple[str, bool]]) -> None:
    started_at = time.monotonic()
    failed_fid: str | None = None
    stats = ScanStats()
    try:
        context = _load_scan_account_context(account_id=account_id, source=source, scan_label="targeted scan")
        if context is None:
            return
        adapter = AdapterFactory.create_adapter(
            context.drive_type,
            context.runtime_cookie,
            config=context.runtime_config,
            account_name=context.account_name,
        )
        if adapter is None:
            logger.warning(
                "drive account lsdir targeted scan aborted: adapter unavailable account_id=%s account_name=%s drive_type=%s source=%s",
                account_id,
                context.account_name,
                context.drive_type,
                source,
            )
            return
        if not getattr(adapter, "is_active", False):
            ok = adapter.init()
            if not ok:
                logger.warning(
                    "drive account lsdir targeted scan aborted: adapter init failed account_id=%s account_name=%s drive_type=%s source=%s",
                    account_id,
                    context.account_name,
                    context.drive_type,
                    source,
                )
                return
        with SessionLocal() as db:
            purge_expired_drive_account_lsdir_cache(db)
            db.commit()
        stats = _refresh_account_paths(account_id=context.account_id, drive_type=context.drive_type, adapter=adapter, target_paths=target_paths)
        with SessionLocal() as db:
            _trigger_dl302_strm_after_scan(db=db, source=f"{source}.targeted")
            db.commit()
    except Exception as exc:
        failed_fid = getattr(exc, "fid", None) or failed_fid
        logger.exception(
            "drive account lsdir targeted scan failed account_id=%s source=%s failed_fid=%s target_paths=%s",
            account_id,
            source,
            failed_fid,
            [path for path, _recursive in target_paths],
        )
    finally:
        with _running_accounts_lock:
            _running_accounts.discard(int(account_id))
        logger.info(
            "drive account lsdir targeted scan finished account_id=%s source=%s scanned_dirs=%s cached_items=%s duration_ms=%s failed_fid=%s target_paths=%s",
            account_id,
            source,
            stats.scanned_dirs,
            stats.cached_items,
            int((time.monotonic() - started_at) * 1000),
            failed_fid or "",
            [path for path, _recursive in target_paths],
        )


def _load_scan_account_context(*, account_id: int, source: str, scan_label: str) -> ScanAccountContext | None:
    with SessionLocal() as db:
        account = db.get(DriveAccount, int(account_id))
        if account is None:
            logger.warning("drive account lsdir %s aborted: account not found account_id=%s source=%s", scan_label, account_id, source)
            return None
        if str(getattr(account, "runtime_status", "") or "") != "active":
            logger.info(
                "drive account lsdir %s skipped: inactive account_id=%s account_name=%s source=%s runtime_status=%s",
                scan_label,
                account_id,
                account.name,
                source,
                getattr(account, "runtime_status", None),
            )
            return None
        runtime_config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
        runtime_cookie = AdapterRegistry.serialize_config(account.drive_type, runtime_config)
        return ScanAccountContext(
            account_id=int(account.id),
            account_name=str(account.name or ""),
            drive_type=str(account.drive_type or ""),
            runtime_config=runtime_config,
            runtime_cookie=runtime_cookie,
        )


def _walk_account_tree(*, account_id: int, drive_type: str, adapter) -> ScanStats:
    ttl_seconds = int(getattr(settings, "drive_account_lsdir_cache_ttl_seconds", 30 * 60) or 30 * 60)
    rate_limit = float(getattr(settings, "drive_account_lsdir_scan_rate_limit_per_second", 1.0) or 1.0)
    stats = ScanStats()
    queue: deque[tuple[str, str]] = deque([("0", "/")])
    visited_fids: set[str] = set()

    while queue:
        parent_fid, parent_path = queue.popleft()
        if parent_fid in visited_fids:
            continue
        visited_fids.add(parent_fid)

        try:
            _wait_for_account_rate_limit(int(account_id), rate_limit)
            listing = adapter.ls_dir(str(parent_fid), max_items=0) or {}
            raw_items = _extract_listing_items("ls_dir", listing)
            with SessionLocal() as db:
                normalized_items = upsert_drive_account_lsdir_items(
                    db,
                    account_id=int(account_id),
                    drive_type=str(drive_type or ""),
                    parent_fid=str(parent_fid),
                    parent_path=parent_path,
                    items=raw_items,
                    ttl_seconds=ttl_seconds,
                    scanned_at=datetime.now(),
                )
                if parent_path != "/" and not normalized_items:
                    delete_drive_account_lsdir_cache_by_path(
                        db,
                        account_id=int(account_id),
                        full_path=parent_path,
                    )
                db.commit()
        except Exception as exc:
            raise DirectoryScanError(str(parent_fid), f"scan directory failed fid={parent_fid} path={parent_path}: {exc}") from exc

        stats.scanned_dirs += 1
        stats.cached_items += len(normalized_items)
        for item in normalized_items:
            if not bool(item.get("is_dir")):
                continue
            child_fid = str(item.get("fid") or "").strip()
            child_path = str(item.get("full_path") or "").strip() or parent_path
            if child_fid and child_fid not in visited_fids:
                queue.append((child_fid, child_path))

    return stats


def _refresh_account_paths(*, account_id: int, drive_type: str, adapter, target_paths: list[tuple[str, bool]]) -> ScanStats:
    ttl_seconds = int(getattr(settings, "drive_account_lsdir_cache_ttl_seconds", 30 * 60) or 30 * 60)
    rate_limit = float(getattr(settings, "drive_account_lsdir_scan_rate_limit_per_second", 1.0) or 1.0)
    stats = ScanStats()
    queue: deque[tuple[str, str, bool]] = deque()
    visited_fids: set[str] = set()
    seen_paths: set[str] = set()

    for full_path, recursive in target_paths:
        normalized_path = _normalize_parent_path(full_path)
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        fid = _resolve_dir_fid(adapter, normalized_path)
        if not fid:
            with SessionLocal() as db:
                delete_drive_account_lsdir_cache_subtree_by_path(
                    db,
                    account_id=int(account_id),
                    full_path=normalized_path,
                )
                db.commit()
            continue
        queue.append((fid, normalized_path, bool(recursive)))

    while queue:
        parent_fid, parent_path, recursive = queue.popleft()
        if parent_fid in visited_fids:
            continue
        visited_fids.add(parent_fid)

        try:
            _wait_for_account_rate_limit(int(account_id), rate_limit)
            listing = adapter.ls_dir(str(parent_fid), max_items=0) or {}
            raw_items = _extract_listing_items("ls_dir", listing)
            with SessionLocal() as db:
                normalized_items = upsert_drive_account_lsdir_items(
                    db,
                    account_id=int(account_id),
                    drive_type=str(drive_type or ""),
                    parent_fid=str(parent_fid),
                    parent_path=parent_path,
                    items=raw_items,
                    ttl_seconds=ttl_seconds,
                    scanned_at=datetime.now(),
                )
                if parent_path != "/" and not normalized_items:
                    delete_drive_account_lsdir_cache_by_path(
                        db,
                        account_id=int(account_id),
                        full_path=parent_path,
                    )
                db.commit()
        except Exception as exc:
            raise DirectoryScanError(str(parent_fid), f"refresh directory failed fid={parent_fid} path={parent_path}: {exc}") from exc

        stats.scanned_dirs += 1
        stats.cached_items += len(normalized_items)
        if not recursive:
            continue
        for item in normalized_items:
            if not bool(item.get("is_dir")):
                continue
            child_fid = str(item.get("fid") or "").strip()
            child_path = str(item.get("full_path") or "").strip() or parent_path
            if child_fid and child_fid not in visited_fids:
                queue.append((child_fid, child_path, True))

    return stats


def _wait_for_account_rate_limit(account_id: int, rate_limit_per_second: float) -> None:
    rps = max(float(rate_limit_per_second or 0.0), 0.0001)
    interval = 1.0 / rps
    account_key = int(account_id)
    while True:
        with _last_request_lock:
            now = time.monotonic()
            last = _last_request_at.get(account_key, 0.0)
            remaining = interval - (now - last)
            if remaining <= 0:
                _last_request_at[account_key] = now
                return
        time.sleep(remaining)


def _resolve_dir_fid(adapter, dir_path: str) -> str | None:
    normalized_path = _normalize_parent_path(dir_path)
    if normalized_path == "/":
        return "0"
    try:
        fid_list = adapter.get_fids([normalized_path]) or []
    except Exception:
        return None
    match = None
    for item in fid_list:
        item_path = item.get("file_path") or item.get("path") or item.get("filePath")
        if _normalize_parent_path(item_path) == normalized_path:
            match = item
            break
    if match is None and fid_list:
        match = fid_list[0]
    fid = match.get("fid") if isinstance(match, dict) else None
    return str(fid).strip() if fid else None


def _extract_listing_items(action: str, resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, dict):
        raise RuntimeError(f"{action} invalid response type: {type(resp).__name__}")
    status = resp.get("status")
    if status is not None and status not in (200, "200"):
        raise RuntimeError(f"{action} status={status} message={resp.get('message') or ''}")
    code = resp.get("code")
    if code is not None and code not in (0, "0"):
        raise RuntimeError(f"{action} code={code} message={resp.get('message') or ''}")
    data = resp.get("data") or {}
    items = data.get("list") or []
    if not isinstance(items, list):
        raise RuntimeError(f"{action} invalid list payload")
    return [item for item in items if isinstance(item, dict)]


def _trigger_dl302_strm_after_scan(*, db, source: str) -> None:
    try:
        result = maybe_auto_generate_dl302_strm(db, source=source)
        if result:
            logger.info(
                "dl302 strm auto generation finished source=%s mode=%s files=%s dirs=%s skipped_accounts=%s",
                source,
                result.get("mode"),
                result.get("generated_files"),
                result.get("generated_dirs"),
                result.get("skipped_accounts"),
            )
    except Exception:
        logger.exception("dl302 strm auto generation failed source=%s", source)
