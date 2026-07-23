from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.extensions.runtime.sync_executor import SyncExecutor
from app.extensions.runtime.execution_log import ExecutionLog
from app.models.sync_execution import SyncExecution
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.services.drive_account_lsdir_scan import refresh_drive_account_lsdir_paths


logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1)


def trigger_linked_sync_tasks_async(task_uids: list[str], *, source: str) -> None:
    uids = _normalize_task_uids(task_uids)
    if not uids:
        return
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "submit linked sync tasks source=%s drama_task_uids=%s",
            str(source or ""),
            uids[:20],
        )
    _executor.submit(_run_linked_sync_tasks, uids, str(source or ""))


def should_trigger_linked_sync_for_drama_execution(execution: object | None) -> bool:
    if execution is None:
        return False
    if str(getattr(execution, "status", "") or "") != "success":
        return False
    tree_summary = str(getattr(execution, "tree_summary", "") or "")
    if "无可转存文件" in tree_summary:
        return False
    run_log = str(getattr(execution, "run_log", "") or "")
    for m in re.finditer(r"saved_fids:\s*(\d+)", run_log):
        try:
            if int(m.group(1)) > 0:
                return True
        except Exception:
            continue
    if " -> " in tree_summary:
        return True
    return False


def run_linked_sync_tasks_blocking(
    drama_task_uids: list[str],
    *,
    source: str,
    log: ExecutionLog | None = None,
    strategy_override_resolver: Callable[[SyncTask], dict[str, Any] | None] | None = None,
    sync_task_uids_override: list[str] | None = None,
) -> list[dict[str, object]]:
    uids = _normalize_task_uids(drama_task_uids)
    if not uids and not sync_task_uids_override:
        return []
    log = log or ExecutionLog()

    with SessionLocal() as db:
        if sync_task_uids_override:
            # Use provided sync_task_uids directly (e.g. from payload for preview/run-once)
            sync_uids = _normalize_task_uids(sync_task_uids_override)
        else:
            # For batch: compute min(sort_order) per sync_task_uid across all drama tasks,
            # then order by that min — this deduplicates and produces optimal ordering.
            rows = (
                db.execute(
                    select(
                        SyncTaskDramaLink.sync_task_uid,
                        func.min(SyncTaskDramaLink.sort_order).label("min_order"),
                    )
                    .where(SyncTaskDramaLink.task_uid.in_(uids))
                    .group_by(SyncTaskDramaLink.sync_task_uid)
                    .order_by(func.min(SyncTaskDramaLink.sort_order).asc())
                )
                .all()
            )
            sync_uids = [str(r[0]) for r in rows if str(r[0] or "").strip()]
        if not sync_uids:
            return []
        tasks = (
            db.execute(select(SyncTask).where(SyncTask.uid.in_(sync_uids), SyncTask.enabled.is_(True)))
            .scalars()
            .all()
        )
        if not tasks:
            return []
        # Sort tasks by the order defined in sync_uids
        uid_order = {uid: idx for idx, uid in enumerate(sync_uids)}
        tasks = sorted(tasks, key=lambda t: uid_order.get(str(getattr(t, 'uid', '') or ''), 999999))

    results: list[dict[str, object]] = []
    log.section("关联同步任务（阻塞）")
    log.line(f"来源: {str(source or '').strip()}")
    log.line(f"追剧任务数: {len(uids)}")
    log.line(f"同步任务数: {len(tasks)}")

    for task in tasks:
        sync_task_id = int(getattr(task, "id", 0) or 0)
        sync_task_uid = str(getattr(task, "uid", "") or "").strip()
        sync_task_name = str(getattr(task, "name", "") or "").strip()
        target_type = str(getattr(task, "target_type", "") or "").strip().lower()
        target_account_id = int(getattr(task, "target_account_id", 0) or 0) or None
        target_path = str(getattr(task, "target_path", "") or "").strip()

        # Short session: check running status and load task
        row = None
        with SessionLocal() as tdb:
            running = (
                tdb.execute(
                    select(SyncExecution.id).where(
                        SyncExecution.sync_task_id == int(sync_task_id),
                        SyncExecution.status == "running",
                        SyncExecution.finished_at.is_(None),
                    )
                )
                .scalars()
                .first()
            )
            if running is not None:
                log.line(f"跳过: {sync_task_name}（正在运行 execution_id={int(running)}）")
                results.append(
                    {
                        "sync_task_id": sync_task_id,
                        "uid": sync_task_uid,
                        "name": sync_task_name,
                        "status": "skipped",
                        "execution_id": int(running),
                        "target_type": target_type,
                        "target_account_id": target_account_id,
                        "target_path": target_path,
                        "message": "running",
                    }
                )
                continue
            row = tdb.get(SyncTask, int(sync_task_id))
            if row is None:
                log.line(f"跳过: {sync_task_name}（任务不存在）")
                results.append(
                    {
                        "sync_task_id": sync_task_id,
                        "uid": sync_task_uid,
                        "name": sync_task_name,
                        "status": "skipped",
                        "execution_id": None,
                        "target_type": target_type,
                        "target_account_id": target_account_id,
                        "target_path": target_path,
                        "message": "not_found",
                    }
                )
                continue
            # Compute strategy override while session is open
            strategy_override = None
            if strategy_override_resolver is not None:
                strategy_override = strategy_override_resolver(row)
                if not isinstance(strategy_override, dict) or not strategy_override:
                    strategy_override = None
            # Expunge row from session so it can be used after session closes
            tdb.expunge(row)

        # Session closed — execute sync task (potentially long-running)
        force_refresh_suppressed = bool(strategy_override and strategy_override.get("force_refresh") is False)
        if force_refresh_suppressed:
            log.line(f"联动覆盖: {sync_task_name} force_refresh=false")
        try:
            execution = SyncExecutor(db=None).run_sync_task(row, log=log, strategy_override=strategy_override)
            execution_id = int(getattr(execution, "id", 0) or 0) or None
            status = str(getattr(execution, "status", "") or "").strip() or "unknown"
            message = str(getattr(execution, "message", "") or "").strip()
            log.line(f"完成: {sync_task_name} status={status}")
            results.append(
                {
                    "sync_task_id": sync_task_id,
                    "uid": sync_task_uid,
                    "name": sync_task_name,
                    "status": status,
                    "execution_id": execution_id,
                    "target_type": target_type,
                    "target_account_id": target_account_id,
                    "target_path": target_path,
                    "message": message,
                    "force_refresh_suppressed": force_refresh_suppressed,
                }
            )
            # Post-sync: targeted lsdir refresh of the sync task's target directory
            if status == "success" and target_type == "netdisk" and target_account_id and target_path:
                _post_sync_refresh_target_lsdir(
                    account_id=int(target_account_id),
                    target_path=target_path,
                    sync_task_name=sync_task_name,
                    source=source,
                    log=log,
                )
        except Exception as exc:
            message = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
            log.line(f"失败: {sync_task_name} err={message}")
            results.append(
                {
                    "sync_task_id": sync_task_id,
                    "uid": sync_task_uid,
                    "name": sync_task_name,
                    "status": "failed",
                    "execution_id": None,
                    "target_type": target_type,
                    "target_account_id": target_account_id,
                    "target_path": target_path,
                    "message": message,
                    "force_refresh_suppressed": False,
                }
            )
    return results


def _normalize_task_uids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        uid = str(raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _post_sync_refresh_target_lsdir(
    *,
    account_id: int,
    target_path: str,
    sync_task_name: str,
    source: str,
    log: ExecutionLog | None = None,
) -> None:
    """After a sync task completes successfully, refresh its target directory lsdir cache."""
    if not target_path or account_id <= 0:
        return
    try:
        stats = refresh_drive_account_lsdir_paths(
            account_id=int(account_id),
            savepath=str(target_path),
            relative_dir_paths=None,
            recursive_savepath=False,
            source=f"{source}.post_sync_refresh",
            wait_if_busy=True,
            max_wait_seconds=600.0,
            include_cas_root_dir=False,
        )
        if log:
            log.line(
                f"后置刷新: {sync_task_name} account_id={account_id} target={target_path} "
                f"scanned_dirs={int(getattr(stats, 'scanned_dirs', 0) or 0)} "
                f"cached_items={int(getattr(stats, 'cached_items', 0) or 0)}"
            )
    except Exception as exc:
        msg = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
        if log:
            log.line(f"后置刷新失败: {sync_task_name} account_id={account_id} target={target_path} err={msg}")
        logger.warning(
            "同步任务后置lsdir刷新失败 sync_task=%s account_id=%s target=%s err=%s",
            sync_task_name, account_id, target_path, msg,
        )


def _run_linked_sync_tasks(task_uids: list[str], source: str) -> None:
    try:
        with SessionLocal() as db:
            rows = (
                db.execute(
                    select(
                        SyncTaskDramaLink.sync_task_uid,
                        func.min(SyncTaskDramaLink.sort_order).label("min_order"),
                    )
                    .where(SyncTaskDramaLink.task_uid.in_(task_uids))
                    .group_by(SyncTaskDramaLink.sync_task_uid)
                    .order_by(func.min(SyncTaskDramaLink.sort_order).asc())
                )
                .all()
            )
            sync_uids = [str(r[0]) for r in rows if str(r[0] or "").strip()]
            if not sync_uids:
                return

            tasks = (
                db.execute(
                    select(SyncTask.id, SyncTask.uid, SyncTask.name)
                    .where(SyncTask.uid.in_(sync_uids), SyncTask.enabled.is_(True))
                )
                .all()
            )
            if not tasks:
                return
            # Sort tasks by the order defined in sync_uids
            uid_order = {uid: idx for idx, uid in enumerate(sync_uids)}
            tasks = sorted(tasks, key=lambda t: uid_order.get(str(t[1] or ''), 999999))

        logger.info("触发关联同步任务 source=%s drama_tasks=%s sync_tasks=%s", source, len(task_uids), len(tasks))
        skipped = 0
        failed = 0
        success = 0

        for task_id, task_uid, task_name in tasks:
            with SessionLocal() as tdb:
                running = (
                    tdb.execute(
                        select(SyncExecution.id).where(
                            SyncExecution.sync_task_id == int(task_id),
                            SyncExecution.status == "running",
                            SyncExecution.finished_at.is_(None),
                        )
                    )
                    .scalars()
                    .first()
                )
                if running is not None:
                    skipped += 1
                    logger.info(
                        "跳过同步任务：正在运行 sync_task_id=%s uid=%s name=%s running_execution_id=%s",
                        task_id,
                        task_uid,
                        task_name,
                        running,
                    )
                    continue
                task = tdb.get(SyncTask, int(task_id))
                if task is None:
                    skipped += 1
                    continue
                try:
                    execution = SyncExecutor(db=None).run_sync_task(task)
                    success += 1
                except Exception as e:
                    failed += 1
                    logger.warning(
                        "同步任务执行失败 sync_task_id=%s uid=%s name=%s err=%s",
                        task_id,
                        task_uid,
                        task_name,
                        str(e).strip() or type(e).__name__,
                    )

        logger.info(
            "关联同步任务触发完成 source=%s drama_tasks=%s sync_tasks=%s success=%s skipped=%s failed=%s",
            source,
            len(task_uids),
            len(tasks),
            success,
            skipped,
            failed,
        )
    except Exception as e:
        logger.exception("关联同步任务触发异常 source=%s err=%s", source, str(e).strip() or type(e).__name__)


def trigger_sync_tasks_by_sync_uids(sync_task_uids: list[str], *, source: str) -> None:
    """直接按同步任务 uid 触发同步任务，不依赖 SyncTaskDramaLink 关联表。"""
    if not sync_task_uids:
        return
    _executor.submit(_run_sync_tasks_by_uids, list(sync_task_uids), str(source or ""))


def _run_sync_tasks_by_uids(sync_uids: list[str], source: str) -> None:
    try:
        with SessionLocal() as db:
            tasks = (
                db.execute(
                    select(SyncTask.id, SyncTask.uid, SyncTask.name)
                    .where(SyncTask.uid.in_(sync_uids), SyncTask.enabled.is_(True))
                )
                .all()
            )
            if not tasks:
                return
            # Sort tasks by the order defined in sync_uids
            uid_order = {uid: idx for idx, uid in enumerate(sync_uids)}
            tasks = sorted(tasks, key=lambda t: uid_order.get(str(t[1] or ''), 999999))

        logger.info("直接触发同步任务 source=%s sync_tasks=%s", source, len(tasks))
        for task_id, task_uid, task_name in tasks:
            with SessionLocal() as tdb:
                running = (
                    tdb.execute(
                        select(SyncExecution.id).where(
                            SyncExecution.sync_task_id == int(task_id),
                            SyncExecution.status == "running",
                            SyncExecution.finished_at.is_(None),
                        )
                    )
                    .scalars()
                    .first()
                )
                if running is not None:
                    logger.info("跳过同步任务（正在运行） uid=%s name=%s", task_uid, task_name)
                    continue
                task = tdb.get(SyncTask, int(task_id))
                if task is None:
                    continue
                try:
                    execution = SyncExecutor(db=None).run_sync_task(task)
                    logger.info(
                        "同步任务执行完成 uid=%s status=%s",
                        task_uid,
                        str(getattr(execution, "status", "") or ""),
                    )
                except Exception as e:
                    logger.warning("同步任务执行失败 uid=%s name=%s err=%s", task_uid, task_name, str(e).strip() or type(e).__name__)
    except Exception as e:
        logger.exception("直接触发同步任务异常 sync_uids=%s source=%s err=%s", sync_uids, source, str(e).strip() or type(e).__name__)
