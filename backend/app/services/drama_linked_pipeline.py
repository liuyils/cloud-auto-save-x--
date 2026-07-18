from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.extensions.runtime.execution_log import ExecutionLog
from app.models.drive_account import DriveAccount
from app.models.sync_execution_file import SyncExecutionFile
from app.services.dl302_cas import submit_dl302_cas_task_delta
from app.services.dl302_settings import extract_dl302_cas_base_paths
from app.services.dl302_strm import rebuild_dl302_strm
from app.services.drive_account_lsdir_scan import refresh_drive_account_lsdir_paths
from app.services.sync_task_triggers import run_linked_sync_tasks_blocking


logger = logging.getLogger(__name__)

_CAS_VIDEO_EXTS = {
    ".3g2",
    ".3gp",
    ".asf",
    ".mp4",
    ".mkv",
    ".avi",
    ".divx",
    ".f4v",
    ".flv",
    ".m4v",
    ".m2t",
    ".m2ts",
    ".mk3d",
    ".mov",
    ".mp2ts",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogm",
    ".ogv",
    ".qt",
    ".rm",
    ".rmvb",
    ".tp",
    ".trp",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
    ".xvid",
    ".iso",
    ".cas",
    ".zip"
}


def _norm_abs_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith("/"):
        text = "/" + text.lstrip("/")
    normalized = str(PurePosixPath(text))
    return normalized if normalized.startswith("/") else "/" + normalized.lstrip("/")


def _join_path(base: str, rel: str) -> str:
    b = _norm_abs_path(base)
    r = str(rel or "").strip().strip("/")
    if not b:
        return ""
    if not r:
        return b
    return str(PurePosixPath(b) / r)


def _is_within_base(base: str, path: str) -> bool:
    b = _norm_abs_path(base)
    p = _norm_abs_path(path)
    if not b or not p:
        return False
    if b == "/":
        return True
    return p == b or p.startswith(b + "/")


def _pick_cas_base_path(account: DriveAccount | None, target_path: str) -> str:
    normalized_target = _norm_abs_path(target_path)
    if account is None:
        return normalized_target
    configured: list[str] = []
    for raw in extract_dl302_cas_base_paths(account):
        normalized = _norm_abs_path(raw)
        if normalized and normalized not in configured:
            configured.append(normalized)
    for base_path in configured:
        if _is_within_base(base_path, normalized_target):
            return base_path
    return configured[0] if configured else normalized_target


def _is_cas_video_path(path: str) -> bool:
    suffix = str(PurePosixPath(str(path or "")).suffix or "").lower()
    return suffix in _CAS_VIDEO_EXTS


@dataclass(slots=True)
class DramaLinkedBatchItem:
    task_uid: str
    task_id: int | None
    account_id: int
    savepath: str
    changed_relative_dirs: list[str] | None = None


def _normalize_batch_items(items: list[DramaLinkedBatchItem] | None) -> list[DramaLinkedBatchItem]:
    normalized: list[DramaLinkedBatchItem] = []
    seen: set[str] = set()
    for item in items or []:
        uid = str(getattr(item, "task_uid", "") or "").strip()
        account_id = int(getattr(item, "account_id", 0) or 0)
        savepath = _norm_abs_path(str(getattr(item, "savepath", "") or ""))
        if not uid or account_id <= 0 or not savepath:
            continue
        if uid in seen:
            continue
        seen.add(uid)
        raw_changed = getattr(item, "changed_relative_dirs", None)
        changed_relative_dirs = [str(x or "").strip() for x in (raw_changed or []) if str(x or "").strip()]
        normalized.append(
            DramaLinkedBatchItem(
                task_uid=uid,
                task_id=int(getattr(item, "task_id", 0) or 0) or None,
                account_id=account_id,
                savepath=savepath,
                changed_relative_dirs=changed_relative_dirs or None,
            )
        )
    return normalized


def _load_drive_accounts(account_ids: set[int]) -> dict[int, DriveAccount]:
    normalized_ids = sorted({int(x) for x in account_ids if int(x or 0) > 0})
    if not normalized_ids:
        return {}
    with SessionLocal() as db:
        rows = db.execute(select(DriveAccount).where(DriveAccount.id.in_(normalized_ids))).scalars().all()
    return {int(getattr(row, "id", 0) or 0): row for row in rows if int(getattr(row, "id", 0) or 0) > 0}


def _build_linked_stage_context(
    *,
    items: list[DramaLinkedBatchItem],
    sync_results: list[dict[str, object]],
) -> tuple[dict[int, dict[str, set[str]]], dict[int, str], dict[int, str]]:
    delta_by_account: dict[int, dict[str, set[str]]] = {}
    account_base_path: dict[int, str] = {}
    account_ids = {int(item.account_id) for item in items}
    account_ids.update(int(item.get("target_account_id") or 0) for item in sync_results if int(item.get("target_account_id") or 0) > 0)
    accounts_by_id = _load_drive_accounts(account_ids)
    cas_base_path_by_account: dict[int, str] = {}

    for item in items:
        account_id = int(item.account_id)
        base_path = _norm_abs_path(item.savepath)
        account_base_path.setdefault(account_id, base_path)
        account = accounts_by_id.get(account_id)
        cas_base_path_by_account.setdefault(
            account_id,
            _pick_cas_base_path(account, base_path),
        )
        changed_dirs = set()
        for rel in item.changed_relative_dirs or []:
            changed_dirs.add(_join_path(base_path, rel))
        if not changed_dirs:
            changed_dirs.add(base_path)
        delta_by_account.setdefault(account_id, {"dir_paths": set(), "file_paths": set()})["dir_paths"].update(changed_dirs)

    for item in sync_results:
        if str(item.get("status") or "").strip().lower() != "success":
            continue
        if str(item.get("target_type") or "").strip().lower() != "netdisk":
            continue
        execution_id = int(item.get("execution_id") or 0) or 0
        account_id = int(item.get("target_account_id") or 0) or 0
        base_path = _norm_abs_path(str(item.get("target_path") or ""))
        if execution_id <= 0 or account_id <= 0 or not base_path:
            continue
        account_base_path.setdefault(account_id, base_path)
        account = accounts_by_id.get(account_id)
        cas_base_path_by_account.setdefault(
            account_id,
            _pick_cas_base_path(account, base_path),
        )
        with SessionLocal() as db:
            rows = (
                db.execute(
                    select(SyncExecutionFile.path).where(
                        SyncExecutionFile.sync_execution_id == int(execution_id),
                        SyncExecutionFile.action == "copy",
                        SyncExecutionFile.status.in_(["success", "skipped"]),
                    )
                )
                .scalars()
                .all()
            )
        payload = delta_by_account.setdefault(account_id, {"dir_paths": set(), "file_paths": set()})
        for raw_path in rows:
            full_path = _norm_abs_path(str(raw_path or ""))
            if not full_path:
                continue
            if not _is_within_base(base_path, full_path):
                continue
            if not _is_cas_video_path(full_path):
                continue
            payload["file_paths"].add(full_path)

    return delta_by_account, account_base_path, cas_base_path_by_account


def run_cas_strm_stage(
    *,
    delta_by_account: dict[int, dict[str, set[str]]],
    account_base_path: dict[int, str],
    cas_base_path_by_account: dict[int, str],
    source: str,
    log: ExecutionLog,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    log.set_stage("linked_refresh_lsdir")
    log.section("刷新 lsdir 缓存")
    for account_id, payload in sorted(delta_by_account.items(), key=lambda it: it[0]):
        base_path = account_base_path.get(account_id)
        if not base_path:
            log.line(f"跳过: account_id={account_id} 缺少 base_path")
            continue
        rel_dirs: set[str] = set()
        for dir_path in payload.get("dir_paths") or set():
            dir_path = _norm_abs_path(dir_path)
            if not _is_within_base(base_path, dir_path):
                continue
            suffix = dir_path[len(_norm_abs_path(base_path)) :]
            rel = suffix.strip("/").strip()
            rel_dirs.add(rel)
        for file_path in payload.get("file_paths") or set():
            file_path = _norm_abs_path(file_path)
            parent = _norm_abs_path(str(PurePosixPath(file_path).parent))
            if not _is_within_base(base_path, parent):
                continue
            suffix = parent[len(_norm_abs_path(base_path)) :]
            rel = suffix.strip("/").strip()
            rel_dirs.add(rel)
        relative_dir_paths = sorted(rel_dirs) if rel_dirs else None
        try:
            stats = refresh_drive_account_lsdir_paths(
                account_id=int(account_id),
                savepath=str(base_path),
                relative_dir_paths=relative_dir_paths,
                recursive_savepath=False,
                source=f"{source}.linked_pipeline",
                wait_if_busy=True,
                max_wait_seconds=600.0,
            )
            log.line(f"OK: account_id={account_id} scanned_dirs={stats.scanned_dirs} cached_items={stats.cached_items}")
        except Exception as exc:
            msg = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
            log.line(f"WARN: account_id={account_id} 刷新失败 err={msg}")

    cas_tasks: list[dict[str, Any]] = []
    log.set_stage("linked_cas_delta")
    log.section("增量 CAS 生成")
    for account_id, payload in sorted(delta_by_account.items(), key=lambda it: it[0]):
        dir_paths = sorted(payload.get("dir_paths") or set())
        file_paths = sorted(payload.get("file_paths") or set())
        with SessionLocal() as db:
            try:
                task = submit_dl302_cas_task_delta(
                    int(account_id),
                    db,
                    base_path=cas_base_path_by_account.get(account_id),
                    dir_paths=dir_paths,
                    file_paths=file_paths,
                )
                db.commit()
                cas_tasks.append(task)
                log.line(
                    f"OK: account_id={account_id} task_id={str(task.get('task_id') or '')} "
                    f"total={int(task.get('total_items') or 0)} skipped={int(task.get('skipped_items') or 0)}"
                )
            except Exception as exc:
                db.rollback()
                msg = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
                log.line(f"WARN: account_id={account_id} CAS 增量提交失败 err={msg}")

    log.set_stage("linked_strm_rebuild")
    log.section("STRM 重建（本地）")
    strm_result: dict[str, Any] | None = None
    with SessionLocal() as db:
        try:
            strm_result = rebuild_dl302_strm(db, trigger=str(source or "linked_pipeline"), request=None)
            db.commit()
            log.line(
                f"OK: mode={str(strm_result.get('mode') if strm_result else '')} "
                f"files={int(strm_result.get('generated_files') if strm_result else 0)}"
            )
        except Exception as exc:
            db.rollback()
            msg = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
            log.line(f"WARN: STRM 重建失败 err={msg}")

    return cas_tasks, strm_result


def run_drama_linked_batch_pipeline(
    *,
    items: list[DramaLinkedBatchItem],
    source: str,
    log: ExecutionLog | None = None,
) -> dict[str, Any]:
    log = log or ExecutionLog()
    batch_items = _normalize_batch_items(items)
    if not batch_items:
        return {
            "ok": True,
            "drama_task_uids": [],
            "sync_results": [],
            "cas_tasks": [],
            "strm": None,
        }

    log.set_stage("linked_sync_prepare")
    log.section("联动流程")
    log.line(f"来源: {str(source or '').strip()}")
    log.line(f"追剧任务数: {len(batch_items)}")
    for item in batch_items:
        task_id_text = int(item.task_id or 0) or "-"
        log.line(
            "追剧任务: "
            f"uid={item.task_uid} task_id={task_id_text} "
            f"account_id={int(item.account_id)} savepath={item.savepath}"
        )

    log.section("联动等待")
    time.sleep(2.0)
    log.line("OK: sleep=2.0s")

    sync_results = run_linked_sync_tasks_blocking(
        [item.task_uid for item in batch_items],
        source=source,
        log=log,
    )

    delta_by_account, account_base_path, cas_base_path_by_account = _build_linked_stage_context(
        items=batch_items,
        sync_results=sync_results,
    )
    cas_tasks, strm_result = run_cas_strm_stage(
        delta_by_account=delta_by_account,
        account_base_path=account_base_path,
        cas_base_path_by_account=cas_base_path_by_account,
        source=source,
        log=log,
    )
    return {
        "ok": True,
        "drama_task_uids": [item.task_uid for item in batch_items],
        "sync_results": sync_results,
        "cas_tasks": cas_tasks,
        "strm": strm_result,
    }


def run_drama_linked_pipeline(
    *,
    drama_task_uid: str,
    drama_task_id: int | None,
    drama_account_id: int,
    drama_savepath: str,
    changed_relative_dirs: list[str] | None,
    source: str,
    log: ExecutionLog | None = None,
) -> dict[str, Any]:
    log = log or ExecutionLog()
    drama_uid = str(drama_task_uid or "").strip()
    if not drama_uid:
        raise ValueError("missing drama_task_uid")
    if drama_account_id <= 0:
        raise ValueError("missing drama_account_id")
    drama_save = _norm_abs_path(drama_savepath)
    if not drama_save:
        raise ValueError("missing drama_savepath")
    result = run_drama_linked_batch_pipeline(
        items=[
            DramaLinkedBatchItem(
                task_uid=drama_uid,
                task_id=int(drama_task_id or 0) or None,
                account_id=int(drama_account_id),
                savepath=drama_save,
                changed_relative_dirs=changed_relative_dirs,
            )
        ],
        source=source,
        log=log,
    )
    result["drama_task_uid"] = drama_uid
    return result
