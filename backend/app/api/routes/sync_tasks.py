import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, get_current_user_scoped, require_permissions, require_permissions_scoped
from app.core.errors import ApiError
from app.core.permissions import SYNC_READ, SYNC_RUN, SYNC_WRITE
from app.db.session import SessionLocal, get_db
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.sync_executor import SyncExecutor
from app.models.drive_account import DriveAccount
from app.models.sync_execution import SyncExecution
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.schemas.task_browse import DriveBrowseIn, DriveBrowseOut
from app.schemas.sync_execution_files import SyncExecutionFileOut, SyncExecutionFilePageOut
from app.schemas.sync_task import SyncCancelIn, SyncExecutionOut, SyncRunIn, SyncTaskCreateIn, SyncTaskOut, SyncTaskUpdateIn
from app.schemas.path_browse import PathBrowseIn, PathBrowseItemOut, PathBrowseOut, PathBrowsePathOut
from app.services import audit
from app.services.drive_browse import browse_drive_directory
from app.services.sync_tasks import (
    browse_local_dir,
    coerce_netdisk_path_to_base,
    create_sync_task,
    delete_sync_task,
    get_sync_task,
    get_netdisk_sync_base_path,
    list_sync_execution_files_page,
    list_sync_executions,
    list_sync_tasks,
    update_sync_task,
    validate_netdisk_sync_account,
)
from app.services.sync_execution_recovery import refresh_running_sync_execution


logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_min_started_at(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except Exception:
        raise ApiError(code="SYNC_EXECUTION_STARTED_AT_INVALID", message="started_at 参数无效", http_status=400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _build_account_map(db: Session, rows: list[SyncTask]) -> dict[int, dict[str, object]]:
    account_ids: set[int] = set()
    for item in rows:
        for raw in (getattr(item, "source_account_id", None), getattr(item, "target_account_id", None)):
            try:
                if raw is not None:
                    account_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
    if not account_ids:
        return {}
    accounts = db.execute(select(DriveAccount).where(DriveAccount.id.in_(sorted(account_ids)))).scalars().all()
    return {
        int(item.id): {
            "account_id": int(item.id),
            "account_name": str(getattr(item, "name", "") or "").strip() or None,
            "drive_type": str(getattr(item, "drive_type", "") or "").strip() or None,
        }
        for item in accounts
    }


def _endpoint_out(tp: str, path: str, account_id: int | None, account_map: dict[int, dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {"type": tp, "path": path}
    if tp != "netdisk":
        return out
    info = account_map.get(int(account_id or 0), {}) if account_id is not None else {}
    out["account_id"] = int(account_id) if account_id is not None else None
    out["account_name"] = info.get("account_name")
    out["drive_type"] = info.get("drive_type")
    return out


def _task_out(item: SyncTask, *, drama_task_uids: list[str] | None = None, account_map: dict[int, dict[str, object]] | None = None) -> SyncTaskOut:
    account_map = account_map or {}
    strategy = {}
    if item.strategy_json:
        try:
            strategy = json.loads(item.strategy_json)
        except Exception:
            strategy = {}
    addition = {}
    raw_addition = getattr(item, "addition_json", None)
    if raw_addition:
        try:
            parsed = json.loads(raw_addition)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            addition = parsed
    return SyncTaskOut(
        id=item.id,
        uid=item.uid,
        name=item.name,
        enabled=item.enabled,
        source=_endpoint_out(item.source_type, item.source_path, getattr(item, "source_account_id", None), account_map),
        target=_endpoint_out(item.target_type, item.target_path, getattr(item, "target_account_id", None), account_map),
        mode=item.mode,
        strategy=strategy,
        drama_task_uids=list(drama_task_uids or []),
        addition=addition,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _execution_out(item: SyncExecution) -> SyncExecutionOut:
    stats: dict[str, Any] = {}
    if item.stats_json:
        try:
            parsed = json.loads(item.stats_json)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            stats = parsed
    return SyncExecutionOut(
        id=item.id,
        sync_task_id=item.sync_task_id,
        status=item.status,
        started_at=item.started_at,
        finished_at=item.finished_at,
        stage=item.stage,
        run_log=item.run_log,
        stats=stats,
        message=item.message,
        cancel_requested_at=getattr(item, "cancel_requested_at", None),
        cancel_requested_by=getattr(item, "cancel_requested_by", None),
        cancel_message=getattr(item, "cancel_message", None),
    )


@router.post(
    "/{sync_task_id:int}/executions/{sync_execution_id:int}/cancel",
    response_model=SyncExecutionOut,
    dependencies=[Depends(require_permissions(SYNC_RUN))],
)
def post_cancel_sync_execution(
    request: Request,
    sync_task_id: int,
    sync_execution_id: int,
    payload: SyncCancelIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    execution = (
        db.execute(select(SyncExecution).where(SyncExecution.id == sync_execution_id, SyncExecution.sync_task_id == sync_task_id))
        .scalars()
        .first()
    )
    if execution is None:
        raise ApiError(code="SYNC_EXECUTION_NOT_FOUND", message="同步执行不存在", http_status=404)
    if str(execution.status or "") != "running" or execution.finished_at is not None:
        raise ApiError(code="SYNC_EXECUTION_NOT_RUNNING", message="同步执行不在运行中", http_status=409)

    if execution.cancel_requested_at is None:
        now = datetime.now()
        execution.cancel_requested_at = now
        execution.cancel_requested_by = int(current.user.id)
        execution.cancel_message = str(payload.message) if payload and payload.message else None
        execution.stage = "aborting"
        execution.message = "cancel requested"
        execution.heartbeat_at = now

        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action="sync_task.execution.cancel",
            target_type="sync_execution",
            target_id=str(sync_execution_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
            detail=execution.cancel_message,
        )
        db.commit()
        db.refresh(execution)
        refresh_running_sync_execution(db, execution, try_cancel=True)
        db.commit()
        db.refresh(execution)

    return _execution_out(execution)


@router.get("", response_model=list[SyncTaskOut], dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_tasks(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list_sync_tasks(db)
    uids = [str(t.uid) for t in rows if getattr(t, "uid", None)]
    mapping: dict[str, list[str]] = {}
    if uids:
        links = db.execute(select(SyncTaskDramaLink).where(SyncTaskDramaLink.sync_task_uid.in_(uids))).scalars().all()
        for it in links:
            mapping.setdefault(str(it.sync_task_uid), []).append(str(it.task_uid))
    account_map = _build_account_map(db, rows)
    # Query running executions for all tasks
    task_ids = [int(t.id) for t in rows]
    running_map: dict[int, int] = {}
    if task_ids:
        running_execs = (
            db.execute(
                select(SyncExecution)
                .where(SyncExecution.sync_task_id.in_(task_ids), SyncExecution.status == "running", SyncExecution.finished_at.is_(None))
            )
            .scalars()
            .all()
        )
        for ex in running_execs:
            running_map[int(ex.sync_task_id)] = int(ex.id)
    result = []
    for t in rows:
        out = _task_out(t, drama_task_uids=mapping.get(str(t.uid), []), account_map=account_map)
        if int(t.id) in running_map:
            out.is_running = True
            out.running_execution_id = running_map[int(t.id)]
        result.append(out)
    return result


@router.post("", response_model=SyncTaskOut, dependencies=[Depends(require_permissions(SYNC_WRITE))])
def post_sync_task(request: Request, payload: SyncTaskCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = create_sync_task(
        db,
        name=payload.name,
        enabled=payload.enabled,
        source=payload.source.model_dump(mode="json"),
        target=payload.target.model_dump(mode="json"),
        mode=payload.mode,
        strategy=payload.strategy.model_dump(mode="json"),
        drama_task_uids=list(payload.drama_task_uids or []),
        addition=payload.addition,
    )
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.create",
        target_type="sync_task",
        target_id=str(task.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(task)
    linked = db.execute(select(SyncTaskDramaLink.task_uid).where(SyncTaskDramaLink.sync_task_uid == str(task.uid))).scalars().all()
    return _task_out(task, drama_task_uids=[str(x) for x in linked if x], account_map=_build_account_map(db, [task]))


@router.patch("/{sync_task_id:int}", response_model=SyncTaskOut, dependencies=[Depends(require_permissions(SYNC_WRITE))])
def patch_sync_task(request: Request, sync_task_id: int, payload: SyncTaskUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = update_sync_task(db, sync_task_id, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.update",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(task)
    linked = db.execute(select(SyncTaskDramaLink.task_uid).where(SyncTaskDramaLink.sync_task_uid == str(task.uid))).scalars().all()
    return _task_out(task, drama_task_uids=[str(x) for x in linked if x], account_map=_build_account_map(db, [task]))


@router.delete("/{sync_task_id:int}", dependencies=[Depends(require_permissions(SYNC_WRITE))])
def delete_sync_task_by_id(request: Request, sync_task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_sync_task(db, sync_task_id)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.delete",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    return {"ok": True}


@router.get("/{sync_task_id:int}/executions", response_model=list[SyncExecutionOut], dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_task_executions(sync_task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list_sync_executions(db, sync_task_id)
    changed = False
    for item in rows:
        changed = refresh_running_sync_execution(db, item, try_cancel=True) or changed
    if changed:
        db.commit()
    return [_execution_out(e) for e in rows]


@router.get("/{sync_task_id:int}/executions/latest", response_model=SyncExecutionOut | None, dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_task_execution_latest(
    sync_task_id: int,
    max_log_chars: int = 0,
    min_started_at: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    threshold = _parse_min_started_at(min_started_at)
    rows = list_sync_executions(db, sync_task_id, limit=20 if threshold else 1)
    if not rows:
        return None
    target = None
    for row in rows:
        row_started_at = getattr(row, "started_at", None)
        if threshold is not None:
            if row_started_at is None:
                continue
            normalized_started = row_started_at
            if normalized_started.tzinfo is None:
                normalized_started = normalized_started.replace(tzinfo=timezone.utc)
            if normalized_started < threshold:
                continue
        target = row
        break
    if target is None:
        return None
    changed = refresh_running_sync_execution(db, target, try_cancel=True)
    if changed:
        db.commit()
        db.refresh(target)
    out = _execution_out(target)
    if max_log_chars and out.run_log and len(out.run_log) > max_log_chars:
        out.run_log = out.run_log[-int(max_log_chars) :]
    return out


@router.get(
    "/{sync_task_id:int}/executions/{sync_execution_id:int}/files",
    response_model=SyncExecutionFilePageOut,
    dependencies=[Depends(require_permissions(SYNC_READ))],
)
def get_sync_execution_files(
    sync_task_id: int,
    sync_execution_id: int,
    offset: int = 0,
    limit: int = 500,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_offset = max(0, int(offset))
    normalized_limit = max(1, min(int(limit), 1000))
    rows, total = list_sync_execution_files_page(
        db,
        sync_task_id,
        sync_execution_id,
        offset=normalized_offset,
        limit=normalized_limit,
    )
    return SyncExecutionFilePageOut(
        items=[
            SyncExecutionFileOut(
                id=r.id,
                sync_execution_id=r.sync_execution_id,
                path=r.path,
                action=r.action,
                status=r.status,
                size=r.size,
                message=r.message,
                updated_at=r.updated_at,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
        offset=normalized_offset,
        limit=normalized_limit,
    )


@router.post("/local/browse", response_model=PathBrowseOut, dependencies=[Depends(require_permissions(SYNC_READ))])
def post_local_browse(payload: PathBrowseIn, current: CurrentUser = Depends(get_current_user)) -> PathBrowseOut:
    rel, exists, items, paths = browse_local_dir(payload.path)
    out_items = [
        PathBrowseItemOut(
            name=str(it["name"]),
            path=str(it["path"]),
            is_dir=bool(it.get("is_dir")),
            updated_at=it.get("updated_at"),
            size=it.get("size"),
        )
        for it in items[: int(payload.max_items)]
    ]
    out_paths = [PathBrowsePathOut(name=str(p["name"]), path=str(p["path"])) for p in paths]
    return PathBrowseOut(dir_path=str(rel), exists=bool(exists), paths=out_paths, items=out_items)


@router.post("/netdisk/browse", response_model=DriveBrowseOut, dependencies=[Depends(require_permissions(SYNC_READ))])
def post_netdisk_browse(payload: DriveBrowseIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> DriveBrowseOut:
    account_name = str(payload.account_name or "").strip()
    if not account_name:
        raise ApiError(code="SYNC_NETDISK_ACCOUNT_INVALID", message="请先选择网盘账号", http_status=400)
    account = (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True), DriveAccount.name == account_name)).scalars().first()
    )
    if account is None:
        raise ApiError(code="DRIVE_ACCOUNT_NOT_FOUND", message="指定账号不存在或不可用", http_status=404)
    account = validate_netdisk_sync_account(db, int(account.id))
    base_path = get_netdisk_sync_base_path(account)
    scoped_payload = payload.model_copy(update={"dir_path": coerce_netdisk_path_to_base(payload.dir_path, base_path)})
    result = browse_drive_directory(db, scoped_payload)
    result.base_path = base_path
    result.dir_path = coerce_netdisk_path_to_base(result.dir_path, base_path)
    return result


@router.post("/{sync_task_id:int}/run", response_model=SyncExecutionOut, dependencies=[Depends(require_permissions(SYNC_RUN))])
def post_run_sync_task(
    request: Request,
    sync_task_id: int,
    payload: SyncRunIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    override = payload.strategy.model_dump(mode="json") if payload and payload.strategy else None
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "sync run request sync_task_id=%s user_id=%s ip=%s override=%s",
            int(sync_task_id),
            int(getattr(current.user, "id", 0) or 0),
            request.client.host if request.client else None,
            json.dumps(override, ensure_ascii=False) if override else None,
        )
    running = (
        db.execute(
            select(SyncExecution)
            .where(SyncExecution.sync_task_id == sync_task_id, SyncExecution.status == "running", SyncExecution.finished_at.is_(None))
            .order_by(SyncExecution.started_at.desc())
        )
        .scalars()
        .first()
    )
    if running is not None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("sync run rejected sync_task_id=%s running_execution_id=%s", int(sync_task_id), int(running.id))
        raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(running.id))
    task = get_sync_task(db, sync_task_id)
    db.close()
    execution = SyncExecutor(db).run_sync_task(task, strategy_override=override)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "sync run finished sync_task_id=%s sync_execution_id=%s status=%s stage=%s",
            int(sync_task_id),
            int(getattr(execution, "id", 0) or 0),
            str(getattr(execution, "status", "") or ""),
            str(getattr(execution, "stage", "") or ""),
        )
    with SessionLocal() as adb:
        audit.write_audit_log(
            adb,
            actor_user_id=current.user.id,
            action="sync_task.run",
            target_type="sync_task",
            target_id=str(sync_task_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=execution.status == "success",
            detail=execution.message,
        )
        adb.commit()
    return _execution_out(execution)


@router.get("/{sync_task_id:int}/log/stream", dependencies=[Depends(require_permissions_scoped(SYNC_READ))])
def get_running_log_stream(
    request: Request,
    sync_task_id: int,
    current: CurrentUser = Depends(get_current_user_scoped),
):
    """SSE endpoint that tails the run_log of the currently running execution for a task."""
    with SessionLocal() as db:
        # 先找 running 的
        running = (
            db.execute(
                select(SyncExecution)
                .where(
                    SyncExecution.sync_task_id == sync_task_id,
                    SyncExecution.status == "running",
                    SyncExecution.finished_at.is_(None),
                )
                .order_by(SyncExecution.started_at.desc())
            )
            .scalars()
            .first()
        )
        # 没有 running 的就找最近一条
        if running is None:
            running = (
                db.execute(
                    select(SyncExecution)
                    .where(SyncExecution.sync_task_id == sync_task_id)
                    .order_by(SyncExecution.started_at.desc())
                )
                .scalars()
                .first()
            )
        if running is None:
            raise ApiError(code="SYNC_EXECUTION_NOT_FOUND", message="该任务没有执行记录", http_status=404)
        execution_id = int(running.id)
        is_already_finished = running.finished_at is not None or running.status != "running"

    def sse(event: str, data: object) -> bytes:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")

    def _parse_stats(exe) -> dict:
        """Parse stats_json field into a progress dict."""
        raw = exe.stats_json
        if not raw:
            return {}
        try:
            s = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {}
        return {
            "total_files": s.get("total_files", 0),
            "done_files": s.get("done_files", 0),
            "success_files": s.get("success_files", s.get("copied_files", 0)),
            "skipped_files": s.get("skipped_files", 0),
            "failed_files": s.get("failed_files", 0),
        }

    def gen():
        yield sse("init", {"sync_task_id": sync_task_id, "execution_id": execution_id, "started_at": datetime.now().isoformat()})

        # If execution already finished, send all data at once and exit
        if is_already_finished:
            with SessionLocal() as db:
                exe = db.execute(select(SyncExecution).where(SyncExecution.id == execution_id)).scalars().first()
                if exe is None:
                    yield sse("done", {"status": "failed", "message": "执行记录不存在"})
                    return
                current_log = str(exe.run_log or "")
                current_status = str(exe.status or "")
                message = str(exe.message or "")
                progress = _parse_stats(exe)
            # Send all log lines
            for line in current_log.splitlines():
                if line:
                    yield sse("log", {"line": line})
            # Send progress
            if progress:
                yield sse("progress", progress)
            # Send done
            yield sse("done", {"status": current_status, "message": message})
            return

        # Live tailing for running execution
        last_log_len = 0
        while True:
            time.sleep(2)
            with SessionLocal() as db:
                exe = db.execute(select(SyncExecution).where(SyncExecution.id == execution_id)).scalars().first()
                if exe is None:
                    yield sse("done", {"status": "failed", "message": "执行记录不存在"})
                    break
                current_log = str(exe.run_log or "")
                current_status = str(exe.status or "")
                current_stage = str(exe.stage or "")
                finished = exe.finished_at is not None
                message = str(exe.message or "")
                progress = _parse_stats(exe)
            # Emit new log lines
            if len(current_log) > last_log_len:
                new_text = current_log[last_log_len:]
                for line in new_text.splitlines():
                    if line:
                        yield sse("log", {"line": line})
                last_log_len = len(current_log)
            # Emit progress
            if progress:
                yield sse("progress", progress)
            # Emit stage
            if current_stage:
                yield sse("stage", {"stage": current_stage})
            # Check if done
            if finished or current_status != "running":
                yield sse("done", {"status": current_status, "message": message})
                break
            # Keep alive
            yield b": ping\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{sync_task_id:int}/run/stream", dependencies=[Depends(require_permissions_scoped(SYNC_RUN))])
def post_run_sync_task_stream(
    request: Request,
    sync_task_id: int,
    payload: SyncRunIn | None = None,
    current: CurrentUser = Depends(get_current_user_scoped),
):
    actor_user_id = int(getattr(current.user, "id", 0) or 0)
    init_payload = {"sync_task_id": int(sync_task_id), "started_at": datetime.now().isoformat()}
    with SessionLocal() as adb:
        running = (
            adb.execute(
                select(SyncExecution)
                .where(
                    SyncExecution.sync_task_id == sync_task_id,
                    SyncExecution.status == "running",
                    SyncExecution.finished_at.is_(None),
                )
                .order_by(SyncExecution.started_at.desc())
            )
            .scalars()
            .first()
        )
        if running is not None:
            raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(running.id))
        audit.write_audit_log(
            adb,
            actor_user_id=actor_user_id,
            action="sync_task.run.stream",
            target_type="sync_task",
            target_id=str(sync_task_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
        adb.commit()

    q: queue.Queue[tuple[str, object]] = queue.Queue()
    done_sentinel = object()

    def emit_line(line: str) -> None:
        q.put(("log", line))

    def emit_stage(stage: str) -> None:
        q.put(("stage", stage))

    def emit_progress(payload: dict) -> None:
        q.put(("progress", dict(payload or {})))

    override = payload.strategy.model_dump(mode="json") if payload and payload.strategy else None

    def worker() -> None:
        log = ExecutionLog(emit_line=emit_line, emit_stage=emit_stage, emit_progress=emit_progress)
        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "sync run(stream) start sync_task_id=%s user_id=%s ip=%s override=%s",
                    int(sync_task_id),
                    actor_user_id,
                    request.client.host if request.client else None,
                    json.dumps(override, ensure_ascii=False) if override else None,
                )
            with SessionLocal() as wdb:
                wtask = get_sync_task(wdb, sync_task_id)
            execution = SyncExecutor(db=None).run_sync_task(wtask, log=log, strategy_override=override)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "sync run(stream) finished sync_task_id=%s sync_execution_id=%s status=%s stage=%s",
                    int(sync_task_id),
                    int(getattr(execution, "id", 0) or 0),
                    str(getattr(execution, "status", "") or ""),
                    str(getattr(execution, "stage", "") or ""),
                )
            q.put(("done", {"status": execution.status, "message": execution.message, "execution": _execution_out(execution).model_dump(mode="json")}))
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc).strip() or type(exc).__name__
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "sync run(stream) failed sync_task_id=%s err=%s",
                    int(sync_task_id),
                    message,
                )
            q.put(
                (
                    "done",
                    {
                            "status": "failed",
                            "message": message,
                            "execution": {
                                "id": 0,
                                "sync_task_id": sync_task_id,
                                "status": "failed",
                                "started_at": log.started_at.isoformat(),
                                "finished_at": datetime.now().isoformat(),
                                "stage": log.stage,
                                "run_log": log.render(),
                                "stats": {},
                                "message": message,
                            },
                    },
                )
            )
        finally:
            q.put(("done_sentinel", done_sentinel))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def sse(event: str, data: object) -> bytes:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")

    def gen():
        yield sse("init", init_payload)
        while True:
            try:
                kind, value = q.get(timeout=15)
            except queue.Empty:
                yield b": ping\n\n"
                continue
            if kind == "log":
                yield sse("log", {"line": str(value)})
                continue
            if kind == "stage":
                yield sse("stage", {"stage": str(value)})
                continue
            if kind == "progress":
                yield sse("progress", value)
                continue
            if kind == "done":
                yield sse("done", value)
                continue
            if kind == "done_sentinel":
                break

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
