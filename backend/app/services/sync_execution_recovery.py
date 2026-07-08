from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import grpc
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.extensions.runtime.sync_executor_dl302 import Dl302SyncExecutor
from app.models.sync_execution import SyncExecution
from app.models.sync_task_lock import SyncTaskLock
from app.thirdparty.dl302_grpc_client import cancel_copy_task, get_copy_task, list_copy_task_items


logger = logging.getLogger(__name__)


def _is_transient_rpc_error(exc: Exception) -> bool:
    if not isinstance(exc, grpc.RpcError):
        return False
    code_fn = getattr(exc, "code", None)
    code = code_fn() if callable(code_fn) else None
    return code in {grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE}


def _load_execution_stats(execution: SyncExecution) -> dict[str, Any]:
    raw = str(getattr(execution, "stats_json", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_sync_execution_dl302_task_id(execution: SyncExecution) -> str:
    stats = _load_execution_stats(execution)
    return str(stats.get("dl302_task_id") or "").strip()


def refresh_running_sync_execution(db: Session, execution: SyncExecution, *, try_cancel: bool = False) -> bool:
    if execution is None:
        return False
    if str(getattr(execution, "status", "") or "") != "running" or getattr(execution, "finished_at", None) is not None:
        return False

    dl302_task_id = get_sync_execution_dl302_task_id(execution)
    if not dl302_task_id:
        return False

    helper = Dl302SyncExecutor(db=None)
    try:
        if try_cancel and getattr(execution, "cancel_requested_at", None) is not None:
            try:
                cancel_copy_task(task_id=dl302_task_id)
            except Exception as exc:
                logger.warning("sync execution cancel dl302 task failed execution_id=%s task_id=%s err=%s", int(execution.id), dl302_task_id, exc)

        task_resp = get_copy_task(task_id=dl302_task_id)
    except Exception as exc:
        if _is_transient_rpc_error(exc):
            logger.warning(
                "refresh dl302 sync execution transient rpc error execution_id=%s task_id=%s err=%s",
                int(execution.id),
                dl302_task_id,
                exc,
            )
            execution.heartbeat_at = datetime.now()
            execution.message = dl302_task_id
            return True
        logger.warning("refresh dl302 sync execution failed execution_id=%s task_id=%s err=%s", int(execution.id), dl302_task_id, exc)
        return False

    task_status = str(getattr(task_resp, "status", "") or "").strip() or "pending"
    total_items = int(getattr(task_resp, "total_items", 0) or 0)
    items = []
    if task_status in {"done", "failed", "cancelled"} or total_items <= 256:
        items_resp = list_copy_task_items(task_id=dl302_task_id)
        items = list(getattr(items_resp, "items", []) or [])
    prev_stats = _load_execution_stats(execution)
    stats = helper._build_stats(task_resp, items, dl302_task_id=dl302_task_id, prev_stats=prev_stats)
    recent_events = prev_stats.get("recent_events")
    if isinstance(recent_events, list):
        stats["recent_events"] = list(recent_events)
    if items:
        helper._sync_file_rows(int(execution.id), items, active_only=task_status in {"pending", "running"})

    execution.stage = helper._map_stage(task_status)
    execution.stats_json = json.dumps(stats, ensure_ascii=False)
    execution.heartbeat_at = datetime.now()

    if task_status in {"pending", "running"}:
        execution.status = "running"
        execution.finished_at = None
        execution.message = dl302_task_id
        return True

    if task_status == "done":
        execution.status = "success"
        execution.stage = "done"
        execution.finished_at = execution.finished_at or datetime.now()
        execution.message = "success"
        return True

    if task_status == "cancelled":
        helper._mark_inflight_rows_aborted(int(execution.id))
        execution.status = "aborted"
        execution.stage = "aborted"
        execution.finished_at = execution.finished_at or datetime.now()
        execution.message = str(getattr(task_resp, "message", "") or "cancelled").strip() or "cancelled"
        return True

    helper._mark_inflight_rows_aborted(int(execution.id))
    execution.status = "failed"
    execution.stage = "error"
    execution.finished_at = execution.finished_at or datetime.now()
    execution.message = str(getattr(task_resp, "last_error", "") or getattr(task_resp, "message", "") or "failed").strip() or "failed"
    return True


def recover_running_sync_executions_on_startup(db: Session) -> int:
    rows = (
        db.execute(select(SyncExecution).where(SyncExecution.status == "running", SyncExecution.finished_at.is_(None)))
        .scalars()
        .all()
    )
    if not rows:
        return 0
    now = datetime.now()
    for r in rows:
        if refresh_running_sync_execution(db, r, try_cancel=True):
            continue
        r.status = "aborted"
        r.stage = "aborted"
        r.finished_at = now
        r.heartbeat_at = now
        r.message = "aborted: server restarted"
    return len(rows)


def abort_stale_running_sync_executions(db: Session, *, threshold_seconds: int) -> int:
    threshold = datetime.now() - timedelta(seconds=int(threshold_seconds))
    rows = (
        db.execute(select(SyncExecution).where(SyncExecution.status == "running", SyncExecution.finished_at.is_(None)))
        .scalars()
        .all()
    )
    now = datetime.now()
    n = 0
    for r in rows:
        ts = r.heartbeat_at or r.started_at
        if ts and ts > threshold:
            continue
        if refresh_running_sync_execution(db, r, try_cancel=True):
            n += 1
            continue
        r.status = "aborted"
        r.stage = "aborted"
        r.finished_at = now
        r.heartbeat_at = now
        r.message = "aborted: stale (no heartbeat > 2h)"
        n += 1
    return n


def release_all_sync_task_locks_on_startup(db: Session) -> int:
    ids = db.execute(select(SyncTaskLock.sync_task_id)).scalars().all()
    if not ids:
        return 0
    db.execute(delete(SyncTaskLock))
    return len(ids)
