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
    get_drive_account_lsdir_cache_subtree_freshness,
    is_path_excluded,
    is_same_or_child_path,
    _join_full_path,
    _normalize_parent_path,
    upsert_drive_account_lsdir_items,
)
from app.services.drive_account_lsdir_static_state import (
    clear_lsdir_scan_state,
    clear_static_scan_state,
    mark_lsdir_scan_completed,
    mark_lsdir_scan_failed,
    mark_lsdir_scan_running,
    mark_static_scan_completed,
    mark_static_scan_failed,
    mark_static_scan_running,
    load_lsdir_scan_state,
    should_rescan_lsdir_path,
    should_rescan_static_path,
)
from app.services.dl302_settings import (
    extract_dl302_cache_base_path,
    extract_dl302_static_cache_base_path,
    get_or_create_dl302_setting,
    load_dl302_config,
)
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
    lsdir_scope: dict[str, Any]


@dataclass(frozen=True)
class TargetPathSpec:
    full_path: str
    recursive: bool
    is_static: bool = False
    excluded_subtrees: tuple[str, ...] = ()


class DirectoryScanError(RuntimeError):
    def __init__(self, fid: str, message: str):
        super().__init__(message)
        self.fid = str(fid or "")


def _normalize_optional_scan_path(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return _normalize_parent_path(text)


def _build_static_signature(account_id: int, drive_type: str, static_path: str | None) -> str | None:
    normalized_path = _normalize_optional_scan_path(static_path)
    if not normalized_path:
        return None
    return f"{int(account_id)}:{str(drive_type or '').strip().lower()}:{normalized_path}"


def _build_lsdir_signature(account_id: int, drive_type: str, base_path: str | None) -> str | None:
    normalized_path = _normalize_optional_scan_path(base_path)
    if not normalized_path:
        return None
    return f"{int(account_id)}:{str(drive_type or '').strip().lower()}:{normalized_path}"


def _build_runtime_lsdir_scope(*, account_id: int, drive_type: str, runtime_config: dict[str, Any]) -> dict[str, Any]:
    cache_base_path = _normalize_optional_scan_path(runtime_config.get("lsdir_cache_path") or runtime_config.get("302_path"))
    static_cache_base_path = _normalize_optional_scan_path(runtime_config.get("static_lsdir_cache_path"))
    static_within_cache = bool(
        cache_base_path
        and static_cache_base_path
        and is_same_or_child_path(parent_path=cache_base_path, child_path=static_cache_base_path)
    )
    return {
        "cache_base_path": cache_base_path,
        "static_cache_base_path": static_cache_base_path,
        "static_within_cache": static_within_cache,
        "lsdir_signature": _build_lsdir_signature(account_id, drive_type, cache_base_path),
        "static_signature": _build_static_signature(account_id, drive_type, static_cache_base_path),
    }


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


def _append_cas_root_dir_target_paths(target_paths: list[TargetPathSpec]) -> list[TargetPathSpec]:
    with SessionLocal() as db:
        setting = get_or_create_dl302_setting(db)
        config = load_dl302_config(setting)
    cas_root_dir = str(config.get("cas_root_dir") or "").strip()
    if not cas_root_dir:
        return target_paths
    cas_root_dir = _normalize_parent_path(cas_root_dir)
    if not cas_root_dir:
        return target_paths
    if any(item.full_path == cas_root_dir for item in target_paths):
        return target_paths
    target_paths.append(TargetPathSpec(full_path=cas_root_dir, recursive=True))
    return target_paths


def _build_requested_target_specs(
    *,
    savepath: str,
    relative_dir_paths: list[str] | None,
    recursive_savepath: bool,
    lsdir_scope: dict[str, Any],
    allow_static_path_rescan: bool,
    include_static_base: bool,
    include_cas_root_dir: bool,
) -> list[TargetPathSpec]:
    static_base_path = _normalize_optional_scan_path(lsdir_scope.get("static_cache_base_path"))
    raw_targets = _build_target_paths(savepath, relative_dir_paths, recursive_savepath=recursive_savepath)
    target_specs: list[TargetPathSpec] = []

    for full_path, recursive in raw_targets:
        normalized_path = _normalize_parent_path(full_path)
        if static_base_path and is_same_or_child_path(parent_path=static_base_path, child_path=normalized_path):
            if not allow_static_path_rescan:
                continue
            target_specs.append(TargetPathSpec(full_path=static_base_path, recursive=True, is_static=True))
            continue
        excluded_subtrees: tuple[str, ...] = ()
        if (
            static_base_path
            and bool(lsdir_scope.get("static_within_cache"))
            and is_same_or_child_path(parent_path=normalized_path, child_path=static_base_path)
        ):
            excluded_subtrees = (static_base_path,)
        target_specs.append(
            TargetPathSpec(
                full_path=normalized_path,
                recursive=bool(recursive),
                is_static=False,
                excluded_subtrees=excluded_subtrees,
            )
        )

    if include_cas_root_dir:
        target_specs = _append_cas_root_dir_target_paths(target_specs)

    if include_static_base and static_base_path and allow_static_path_rescan:
        target_specs.append(TargetPathSpec(full_path=static_base_path, recursive=True, is_static=True))

    deduped: list[TargetPathSpec] = []
    seen: set[tuple[str, bool]] = set()
    for spec in target_specs:
        key = (spec.full_path, bool(spec.is_static))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


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


def trigger_drive_account_lsdir_targeted_scan(
    account_id: int,
    *,
    savepath: str,
    relative_dir_paths: list[str] | None,
    source: str,
    recursive_savepath: bool = False,
    allow_static_path_rescan: bool = False,
    include_static_base: bool = False,
) -> bool:
    account_key = int(account_id)
    normalized_savepath = _normalize_parent_path(savepath)

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
        args=(
            account_key,
            str(source or ""),
            normalized_savepath,
            [str(item or "") for item in (relative_dir_paths or [])],
            bool(recursive_savepath),
            bool(allow_static_path_rescan),
            bool(include_static_base),
        ),
        name=f"drive-account-lsdir-targeted-scan-{account_key}",
        daemon=True,
    )
    thread.start()
    return True


def rebuild_drive_account_lsdir_cache_for_current_302_path(
    account_id: int,
    source: str,
    old_base_path: str | None = None,
    *,
    old_static_base_path: str | None = None,
    rebuild_dynamic: bool = True,
    rebuild_static: bool = False,
    rescan_static: bool = False,
) -> dict[str, Any]:
    account_key = int(account_id)
    cleared = 0
    static_cleared = 0
    with SessionLocal() as db:
        account = db.get(DriveAccount, account_key)
        if account is None:
            return {
                "account_id": account_key,
                "cleared": 0,
                "queued": False,
                "base_path": None,
                "reason": "account_not_found",
                "static_requested": bool(rescan_static or rebuild_static),
                "static_queued": False,
                "static_skipped_reason": "account_not_found",
            }
        base_path = extract_dl302_cache_base_path(account)
        static_base_path = extract_dl302_static_cache_base_path(account)

        if old_base_path and old_base_path != base_path:
            cleared = delete_drive_account_lsdir_cache_subtree_by_path(db, account_id=account_key, full_path=old_base_path)
            clear_lsdir_scan_state(account_key, str(account.drive_type or ""))
            logger.info(
                "drive account lsdir cleared old path account_id=%s source=%s old_path=%s cleared=%s",
                account_key,
                source,
                old_base_path,
                cleared,
            )
        elif not old_base_path and not base_path and not static_base_path:
            cleared = delete_drive_account_lsdir_cache_by_account(db, account_key)
            clear_lsdir_scan_state(account_key, str(account.drive_type or ""))
            clear_static_scan_state(account_key, str(account.drive_type or ""))
        if old_static_base_path and old_static_base_path != static_base_path:
            static_cleared += delete_drive_account_lsdir_cache_subtree_by_path(
                db,
                account_id=account_key,
                full_path=old_static_base_path,
            )
            clear_static_scan_state(account_key, str(account.drive_type or ""))
        if rebuild_static and static_base_path:
            clear_static_scan_state(account_key, str(account.drive_type or ""))
        if rebuild_dynamic and base_path:
            clear_lsdir_scan_state(account_key, str(account.drive_type or ""))
        db.commit()

    if not base_path and not static_base_path:
        logger.info(
            "drive account lsdir rebuild skipped: missing cache_path account_id=%s source=%s cleared=%s static_cleared=%s",
            account_key,
            source,
            cleared,
            static_cleared,
        )
        return {
            "account_id": account_key,
            "cleared": int((cleared or 0) + (static_cleared or 0)),
            "queued": False,
            "base_path": None,
            "reason": "missing_302_path",
            "static_requested": bool(rescan_static or rebuild_static),
            "static_queued": False,
            "static_skipped_reason": "missing_static_path" if bool(rescan_static or rebuild_static) else None,
        }

    request_static = bool(rescan_static or rebuild_static)
    queued = False
    if rebuild_dynamic and (base_path or static_base_path):
        queued = trigger_drive_account_lsdir_targeted_scan(
            account_key,
            savepath=base_path or static_base_path or "/",
            relative_dir_paths=None,
            recursive_savepath=True,
            source=source,
            allow_static_path_rescan=request_static,
            include_static_base=request_static,
        )
    elif request_static and static_base_path:
        queued = trigger_drive_account_lsdir_targeted_scan(
            account_key,
            savepath=static_base_path,
            relative_dir_paths=None,
            recursive_savepath=True,
            source=source,
            allow_static_path_rescan=True,
            include_static_base=False,
        )
    reason = "queued" if queued else "running"
    logger.info(
        "drive account lsdir rebuild requested account_id=%s source=%s cleared=%s static_cleared=%s queued=%s base_path=%s static_path=%s request_static=%s reason=%s",
        account_key,
        source,
        cleared,
        static_cleared,
        queued,
        base_path,
        static_base_path,
        request_static,
        reason,
    )
    return {
        "account_id": account_key,
        "cleared": int((cleared or 0) + (static_cleared or 0)),
        "queued": bool(queued),
        "base_path": str(base_path or static_base_path),
        "reason": reason,
        "static_requested": request_static,
        "static_queued": bool(queued and request_static and static_base_path),
        "static_skipped_reason": None if (request_static and static_base_path) else ("missing_static_path" if request_static else None),
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
    progress_hook=None,
    include_cas_root_dir: bool = True,
    allow_static_path_rescan: bool = False,
    include_static_base: bool = False,
) -> ScanStats:
    account_key = int(account_id)
    normalized_savepath = _normalize_parent_path(savepath)

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
        target_specs = _build_requested_target_specs(
            savepath=normalized_savepath,
            relative_dir_paths=relative_dir_paths,
            recursive_savepath=recursive_savepath,
            lsdir_scope=context.lsdir_scope,
            allow_static_path_rescan=allow_static_path_rescan,
            include_static_base=include_static_base,
            include_cas_root_dir=include_cas_root_dir,
        )
        stats = _refresh_account_paths(
            account_id=context.account_id,
            drive_type=context.drive_type,
            adapter=adapter,
            target_paths=target_specs,
            lsdir_scope=context.lsdir_scope,
            progress_hook=progress_hook,
        )
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
            [item.full_path for item in target_specs],
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
            [item.full_path for item in target_specs],
        )


def recover_incomplete_drive_account_static_scans(source: str = "startup.recover_static_lsdir") -> dict[str, int]:
    with SessionLocal() as db:
        accounts = (
            db.query(DriveAccount)
            .filter(
                DriveAccount.enabled.is_(True),
                DriveAccount.runtime_status == "active",
            )
            .order_by(DriveAccount.id.asc())
            .all()
        )

    checked = 0
    queued = 0
    skipped = 0
    for account in accounts:
        static_base_path = extract_dl302_static_cache_base_path(account)
        if not static_base_path:
            continue
        checked += 1
        if not should_rescan_static_path(
            int(account.id),
            str(account.drive_type or ""),
            static_path=static_base_path,
            signature=_build_static_signature(int(account.id), str(account.drive_type or ""), static_base_path),
        ):
            skipped += 1
            continue
        ok = trigger_drive_account_lsdir_targeted_scan(
            int(account.id),
            savepath=static_base_path,
            relative_dir_paths=None,
            source=source,
            recursive_savepath=True,
            allow_static_path_rescan=True,
            include_static_base=False,
        )
        if ok:
            queued += 1
        else:
            skipped += 1
    logger.info(
        "drive account static lsdir recovery finished checked=%s queued=%s skipped=%s",
        checked,
        queued,
        skipped,
    )
    return {"checked": checked, "queued": queued, "skipped": skipped}


def recover_incomplete_drive_account_lsdir_scans(source: str = "startup.recover_lsdir") -> dict[str, int]:
    with SessionLocal() as db:
        accounts = (
            db.query(DriveAccount)
            .filter(
                DriveAccount.enabled.is_(True),
                DriveAccount.runtime_status == "active",
            )
            .order_by(DriveAccount.id.asc())
            .all()
        )

    checked = 0
    queued = 0
    skipped = 0
    for account in accounts:
        base_path = extract_dl302_cache_base_path(account)
        if not base_path:
            continue
        checked += 1
        state = load_lsdir_scan_state(int(account.id), str(account.drive_type or ""))
        with SessionLocal() as db:
            freshness = get_drive_account_lsdir_cache_subtree_freshness(db, account_id=int(account.id), full_path=base_path)
        total = int(freshness.get("total") or 0)
        if state is None and total > 0:
            mark_lsdir_scan_completed(
                int(account.id),
                str(account.drive_type or ""),
                base_path=base_path,
                signature=_build_lsdir_signature(int(account.id), str(account.drive_type or ""), base_path),
            )
            skipped += 1
            continue
        if not should_rescan_lsdir_path(
            int(account.id),
            str(account.drive_type or ""),
            base_path=base_path,
            signature=_build_lsdir_signature(int(account.id), str(account.drive_type or ""), base_path),
        ):
            skipped += 1
            continue
        ok = trigger_drive_account_lsdir_targeted_scan(
            int(account.id),
            savepath=base_path,
            relative_dir_paths=None,
            source=source,
            recursive_savepath=True,
            allow_static_path_rescan=False,
            include_static_base=False,
        )
        if ok:
            queued += 1
        else:
            skipped += 1
    logger.info(
        "drive account lsdir recovery finished checked=%s queued=%s skipped=%s",
        checked,
        queued,
        skipped,
    )
    return {"checked": checked, "queued": queued, "skipped": skipped}


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
        stats = _walk_account_tree(
            account_id=context.account_id,
            drive_type=context.drive_type,
            adapter=adapter,
            lsdir_scope=context.lsdir_scope,
        )
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


def _scan_drive_account_targeted_worker(
    account_id: int,
    source: str,
    savepath: str,
    relative_dir_paths: list[str] | None,
    recursive_savepath: bool,
    allow_static_path_rescan: bool,
    include_static_base: bool,
) -> None:
    started_at = time.monotonic()
    failed_fid: str | None = None
    stats = ScanStats()
    target_specs: list[TargetPathSpec] = []
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
        target_specs = _build_requested_target_specs(
            savepath=savepath,
            relative_dir_paths=relative_dir_paths,
            recursive_savepath=recursive_savepath,
            lsdir_scope=context.lsdir_scope,
            allow_static_path_rescan=allow_static_path_rescan,
            include_static_base=include_static_base,
            include_cas_root_dir=True,
        )
        stats = _refresh_account_paths(
            account_id=context.account_id,
            drive_type=context.drive_type,
            adapter=adapter,
            target_paths=target_specs,
            lsdir_scope=context.lsdir_scope,
        )
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
            [item.full_path for item in target_specs],
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
            [item.full_path for item in target_specs],
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
        lsdir_scope = _build_runtime_lsdir_scope(
            account_id=int(account.id),
            drive_type=str(account.drive_type or ""),
            runtime_config=runtime_config,
        )
        return ScanAccountContext(
            account_id=int(account.id),
            account_name=str(account.name or ""),
            drive_type=str(account.drive_type or ""),
            runtime_config=runtime_config,
            runtime_cookie=runtime_cookie,
            lsdir_scope=lsdir_scope,
        )


def _walk_account_tree(*, account_id: int, drive_type: str, adapter, lsdir_scope: dict[str, Any]) -> ScanStats:
    cache_base_path = _normalize_optional_scan_path(lsdir_scope.get("cache_base_path"))
    static_base_path = _normalize_optional_scan_path(lsdir_scope.get("static_cache_base_path"))
    target_specs: list[TargetPathSpec] = []
    if cache_base_path and should_rescan_lsdir_path(
        int(account_id),
        str(drive_type or ""),
        base_path=cache_base_path,
        signature=lsdir_scope.get("lsdir_signature"),
    ):
        excluded_subtrees: tuple[str, ...] = ()
        if (
            static_base_path
            and bool(lsdir_scope.get("static_within_cache"))
            and is_same_or_child_path(parent_path=cache_base_path, child_path=static_base_path)
        ):
            excluded_subtrees = (static_base_path,)
        target_specs.append(
            TargetPathSpec(
                full_path=cache_base_path,
                recursive=True,
                is_static=False,
                excluded_subtrees=excluded_subtrees,
            )
        )
    if static_base_path and should_rescan_static_path(
        int(account_id),
        str(drive_type or ""),
        static_path=static_base_path,
        signature=lsdir_scope.get("static_signature"),
    ):
        target_specs.append(TargetPathSpec(full_path=static_base_path, recursive=True, is_static=True))
    if not target_specs:
        return ScanStats()
    return _refresh_account_paths(
        account_id=int(account_id),
        drive_type=str(drive_type or ""),
        adapter=adapter,
        target_paths=target_specs,
        lsdir_scope=lsdir_scope,
    )


def _refresh_account_paths(
    *,
    account_id: int,
    drive_type: str,
    adapter,
    target_paths: list[TargetPathSpec],
    lsdir_scope: dict[str, Any],
    progress_hook=None,
) -> ScanStats:
    rate_limit = float(getattr(settings, "drive_account_lsdir_scan_rate_limit_per_second", 1.0) or 1.0)
    stats = ScanStats()
    queue: deque[tuple[str, TargetPathSpec]] = deque()
    visited_paths: set[tuple[str, bool]] = set()
    static_targets: list[TargetPathSpec] = []
    lsdir_targets: list[TargetPathSpec] = []
    static_signature = lsdir_scope.get("static_signature")
    lsdir_signature = lsdir_scope.get("lsdir_signature")
    cache_base_path = _normalize_optional_scan_path(lsdir_scope.get("cache_base_path"))

    for spec in target_paths:
        normalized_path = _normalize_parent_path(spec.full_path)
        if is_path_excluded(normalized_path, spec.excluded_subtrees):
            continue
        normalized_spec = TargetPathSpec(
            full_path=normalized_path,
            recursive=bool(spec.recursive),
            is_static=bool(spec.is_static),
            excluded_subtrees=tuple(spec.excluded_subtrees),
        )
        if normalized_spec.is_static:
            static_targets.append(normalized_spec)
            mark_static_scan_running(
                int(account_id),
                str(drive_type or ""),
                static_path=normalized_spec.full_path,
                signature=str(static_signature or "") or None,
            )
        elif cache_base_path and normalized_spec.full_path == cache_base_path and normalized_spec.recursive:
            lsdir_targets.append(normalized_spec)
            mark_lsdir_scan_running(
                int(account_id),
                str(drive_type or ""),
                base_path=normalized_spec.full_path,
                signature=str(lsdir_signature or "") or None,
            )
        fid = _resolve_dir_fid(adapter, normalized_path)
        if not fid:
            with SessionLocal() as db:
                delete_drive_account_lsdir_cache_subtree_by_path(
                    db,
                    account_id=int(account_id),
                    full_path=normalized_path,
                )
                db.commit()
            if normalized_spec.is_static:
                mark_static_scan_failed(
                    int(account_id),
                    str(drive_type or ""),
                    static_path=normalized_spec.full_path,
                    signature=str(static_signature or "") or None,
                    error="static_path_not_found",
                )
            elif cache_base_path and normalized_spec.full_path == cache_base_path and normalized_spec.recursive:
                mark_lsdir_scan_failed(
                    int(account_id),
                    str(drive_type or ""),
                    base_path=normalized_spec.full_path,
                    signature=str(lsdir_signature or "") or None,
                    error="cache_path_not_found",
                )
            continue
        queue.append((fid, normalized_spec))

    while queue:
        parent_fid, spec = queue.popleft()
        visited_key = (str(parent_fid), bool(spec.is_static))
        if visited_key in visited_paths:
            continue
        visited_paths.add(visited_key)
        parent_path = spec.full_path

        try:
            _wait_for_account_rate_limit(int(account_id), rate_limit)
            listing = adapter.ls_dir(str(parent_fid), max_items=0) or {}
            raw_items = _extract_listing_items("ls_dir", listing)
            now = datetime.now()
            with SessionLocal() as db:
                normalized_items = upsert_drive_account_lsdir_items(
                    db,
                    account_id=int(account_id),
                    drive_type=str(drive_type or ""),
                    parent_fid=str(parent_fid),
                    parent_path=parent_path,
                    items=raw_items,
                    scanned_at=now,
                )
                if parent_path != "/" and not normalized_items:
                    delete_drive_account_lsdir_cache_by_path(
                        db,
                        account_id=int(account_id),
                        full_path=parent_path,
                    )
                db.commit()
        except Exception as exc:
            if cache_base_path and spec.full_path == cache_base_path and spec.recursive and not spec.is_static:
                mark_lsdir_scan_failed(
                    int(account_id),
                    str(drive_type or ""),
                    base_path=spec.full_path,
                    signature=str(lsdir_signature or "") or None,
                    error=str(exc),
                )
            if spec.is_static:
                mark_static_scan_failed(
                    int(account_id),
                    str(drive_type or ""),
                    static_path=spec.full_path,
                    signature=str(static_signature or "") or None,
                    error=str(exc),
                )
            raise DirectoryScanError(str(parent_fid), f"refresh directory failed fid={parent_fid} path={parent_path}: {exc}") from exc

        stats.scanned_dirs += 1
        stats.cached_items += len(normalized_items)
        if progress_hook is not None:
            try:
                progress_hook(stats, parent_path, len(queue))
            except Exception:
                pass
        if not spec.recursive:
            continue
        for item in normalized_items:
            if not bool(item.get("is_dir")):
                continue
            child_fid = str(item.get("fid") or "").strip()
            child_path = str(item.get("full_path") or "").strip() or parent_path
            if not child_fid or is_path_excluded(child_path, spec.excluded_subtrees):
                continue
            queue.append(
                (
                    child_fid,
                    TargetPathSpec(
                        full_path=child_path,
                        recursive=True,
                        is_static=spec.is_static,
                        excluded_subtrees=spec.excluded_subtrees,
                    ),
                )
            )

    for spec in static_targets:
        mark_static_scan_completed(
            int(account_id),
            str(drive_type or ""),
            static_path=spec.full_path,
            signature=str(static_signature or "") or None,
        )
    for spec in lsdir_targets:
        mark_lsdir_scan_completed(
            int(account_id),
            str(drive_type or ""),
            base_path=spec.full_path,
            signature=str(lsdir_signature or "") or None,
        )

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
                "dl302 strm auto generation finished source=%s mode=%s total=%s added=%s updated=%s removed=%s unchanged=%s dirs=%s skipped_accounts=%s",
                source,
                result.get("mode"),
                result.get("generated_files"),
                result.get("added_files"),
                result.get("updated_files"),
                result.get("removed_files"),
                result.get("unchanged_files"),
                result.get("generated_dirs"),
                result.get("skipped_accounts"),
            )
    except Exception:
        logger.exception("dl302 strm auto generation failed source=%s", source)
