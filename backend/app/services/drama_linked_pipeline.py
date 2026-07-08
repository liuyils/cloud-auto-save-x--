from __future__ import annotations

import logging
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.sync_executor import SyncExecutor
from app.models.drive_account import DriveAccount
from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.services.dl302_cas import _extract_account_media_base_path, submit_dl302_cas_task_delta
from app.services.dl302_strm import rebuild_dl302_strm
from app.services.drive_account_lsdir_scan import refresh_drive_account_lsdir_paths


logger = logging.getLogger(__name__)

_CAS_VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mts",
    ".mpg",
    ".mpeg",
    ".webm",
    ".rmvb",
    ".rm",
    ".asf",
    ".3gp",
    ".mp2",
    ".mpe",
    ".mpv",
    ".mxf",
    ".ogm",
    ".ogv",
    ".qt",
    ".vob",
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


def _is_cas_video_path(path: str) -> bool:
    suffix = str(PurePosixPath(str(path or "")).suffix or "").lower()
    return suffix in _CAS_VIDEO_EXTS


@dataclass(slots=True)
class SyncRunResult:
    sync_task_id: int
    uid: str
    name: str
    status: str
    execution_id: int | None
    target_type: str
    target_account_id: int | None
    target_path: str
    message: str


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
                max_wait_seconds=60.0,
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
    drama_save = _norm_abs_path(drama_savepath)
    if not drama_uid:
        raise ValueError("missing drama_task_uid")
    if drama_account_id <= 0:
        raise ValueError("missing drama_account_id")
    if not drama_save:
        raise ValueError("missing drama_savepath")

    log.set_stage("linked_sync_prepare")
    log.section("联动流程")
    log.line(f"来源: {str(source or '').strip()}")
    log.line(f"追剧任务: uid={drama_uid} task_id={int(drama_task_id or 0) or '-'}")

    with SessionLocal() as db:
        links = (
            db.execute(select(SyncTaskDramaLink.sync_task_uid).where(SyncTaskDramaLink.task_uid == drama_uid))
            .scalars()
            .all()
        )
        sync_uids = [str(x or "").strip() for x in links if str(x or "").strip()]
        if sync_uids:
            tasks = (
                db.execute(
                    select(SyncTask)
                    .where(SyncTask.uid.in_(sync_uids), SyncTask.enabled.is_(True))
                    .order_by(SyncTask.id.asc())
                )
                .scalars()
                .all()
            )
        else:
            tasks = []

        drama_account = db.get(DriveAccount, int(drama_account_id))
        if drama_account is None:
            raise RuntimeError(f"drama account not found id={int(drama_account_id)}")
        drama_drive_type = str(getattr(drama_account, "drive_type", "") or "").strip()
        drama_account_name = str(getattr(drama_account, "name", "") or "").strip()

    log.line(f"追剧目标账号: id={int(drama_account_id)} {drama_drive_type}:{drama_account_name}")
    log.line(f"追剧保存路径: {drama_save}")
    log.line(f"关联同步任务数: {len(tasks)}")

    log.section("联动等待")
    time.sleep(2.0)
    log.line("OK: sleep=2.0s")

    sync_results: list[SyncRunResult] = []
    if tasks:
        log.set_stage("linked_sync_run")
        log.section("关联同步任务")
        for task in tasks:
            sync_task_id = int(getattr(task, "id", 0) or 0)
            sync_uid = str(getattr(task, "uid", "") or "").strip()
            sync_name = str(getattr(task, "name", "") or "").strip()
            target_type = str(getattr(task, "target_type", "") or "").strip().lower()
            target_account_id = int(getattr(task, "target_account_id", 0) or 0) or None
            target_path = _norm_abs_path(str(getattr(task, "target_path", "") or ""))

            with SessionLocal() as db:
                running = (
                    db.execute(
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
                msg = f"跳过: 正在运行 execution_id={int(running)}（详情请到同步任务列表查看）"
                log.line(f"{sync_name} ({sync_uid}) {msg}")
                sync_results.append(
                    SyncRunResult(
                        sync_task_id=sync_task_id,
                        uid=sync_uid,
                        name=sync_name,
                        status="skipped",
                        execution_id=int(running),
                        target_type=target_type,
                        target_account_id=target_account_id,
                        target_path=target_path,
                        message=msg,
                    )
                )
                continue
            try:
                log.line(f"{sync_name} ({sync_uid}) 已发起（同步进度请到同步任务列表查看）")
                sync_log = ExecutionLog()
                execution = SyncExecutor(db=None).run_sync_task(task, log=sync_log)
                execution_id = int(getattr(execution, "id", 0) or 0) or None
                status = str(getattr(execution, "status", "") or "").strip() or "unknown"
                msg = str(getattr(execution, "message", "") or "").strip()
                log.line(f"{sync_name} ({sync_uid}) 执行完成 status={status} execution_id={execution_id or '-'}（详情请到同步任务列表查看）")
                sync_results.append(
                    SyncRunResult(
                        sync_task_id=sync_task_id,
                        uid=sync_uid,
                        name=sync_name,
                        status=status,
                        execution_id=execution_id,
                        target_type=target_type,
                        target_account_id=target_account_id,
                        target_path=target_path,
                        message=msg,
                    )
                )
            except Exception as exc:
                msg = str(getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
                log.line(f"{sync_name} ({sync_uid}) 执行失败 err={msg}（详情请到同步任务列表查看）")
                sync_results.append(
                    SyncRunResult(
                        sync_task_id=sync_task_id,
                        uid=sync_uid,
                        name=sync_name,
                        status="failed",
                        execution_id=None,
                        target_type=target_type,
                        target_account_id=target_account_id,
                        target_path=target_path,
                        message=msg,
                    )
                )

    delta_by_account: dict[int, dict[str, set[str]]] = {}
    account_base_path: dict[int, str] = {int(drama_account_id): drama_save}
    drama_media_base_path = _norm_abs_path(
        str(getattr(drama_account, "proxy_base_path", "") or "").strip()
        or _extract_account_media_base_path(drama_account)
        or drama_save
    )
    cas_base_path_by_account: dict[int, str] = {int(drama_account_id): drama_media_base_path}

    drama_dirs = set()
    for rel in changed_relative_dirs or []:
        drama_dirs.add(_join_path(drama_save, str(rel or "").strip()))
    if not drama_dirs:
        drama_dirs.add(drama_save)
    delta_by_account.setdefault(int(drama_account_id), {"dir_paths": set(), "file_paths": set()})["dir_paths"].update(drama_dirs)

    for item in sync_results:
        if item.status != "success":
            continue
        if item.target_type != "netdisk":
            continue
        if not item.execution_id or not item.target_account_id or not item.target_path:
            continue
        account_id = int(item.target_account_id)
        base_path = _norm_abs_path(item.target_path)
        account_base_path.setdefault(account_id, base_path)
        if account_id not in cas_base_path_by_account:
            with SessionLocal() as db:
                target_account = db.get(DriveAccount, account_id)
            if target_account is not None:
                target_media_base_path = _norm_abs_path(
                    str(getattr(target_account, "proxy_base_path", "") or "").strip()
                    or _extract_account_media_base_path(target_account)
                    or base_path
                )
                cas_base_path_by_account[account_id] = target_media_base_path
        with SessionLocal() as db:
            rows = (
                db.execute(
                    select(SyncExecutionFile.path).where(
                        SyncExecutionFile.sync_execution_id == int(item.execution_id),
                        SyncExecutionFile.action == "copy",
                        SyncExecutionFile.status.in_(["success", "skipped"]),
                    )
                )
                .scalars()
                .all()
            )
        for p in rows:
            full_path = _norm_abs_path(str(p or ""))
            if not full_path:
                continue
            if not _is_within_base(base_path, full_path):
                continue
            if not _is_cas_video_path(full_path):
                continue
            delta_by_account.setdefault(account_id, {"dir_paths": set(), "file_paths": set()})["file_paths"].add(full_path)

    cas_tasks, strm_result = run_cas_strm_stage(
        delta_by_account=delta_by_account,
        account_base_path=account_base_path,
        cas_base_path_by_account=cas_base_path_by_account,
        source=source,
        log=log,
    )

    return {
        "ok": True,
        "drama_task_uid": drama_uid,
        "sync_results": [asdict(item) for item in sync_results],
        "cas_tasks": cas_tasks,
        "strm": strm_result,
    }
