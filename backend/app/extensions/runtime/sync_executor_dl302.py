from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import grpc
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError, bad_request
from app.db.session import SessionLocal
from app.extensions.runtime.execution_log import ExecutionLog
from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile
from app.models.sync_task import SyncTask
from app.models.sync_task_lock import SyncTaskLock
from app.services.drive_account_lsdir_scan import refresh_drive_account_lsdir_paths
from app.services.notifications.sync_notify import send_sync_execution_notification
from app.services.sync_tasks import (
    get_netdisk_sync_base_path,
    is_path_within_base,
    local_sync_root,
    validate_netdisk_sync_account,
)
from app.thirdparty.dl302_grpc_client import cancel_copy_task, get_copy_task, list_copy_task_items, submit_copy_task


@dataclass(frozen=True, slots=True)
class Dl302Endpoint:
    type: str
    path: str
    drive_type: str
    account_name: str
    account_id: int | None = None
    base_path: str | None = None


@dataclass(frozen=True, slots=True)
class Dl302Strategy:
    overwrite: bool
    force_refresh: bool


class SyncCancelled(Exception):
    def __init__(self, message: str = "cancelled"):
        super().__init__(message)
        self.message = message


class _CancelChecker:
    def __init__(self, sync_execution_id: int):
        self.sync_execution_id = int(sync_execution_id)
        self._cancelled = False
        self._message: str | None = None
        self._last_check_ts = 0.0

    @property
    def message(self) -> str | None:
        return self._message

    def is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        now_ts = time.time()
        if now_ts - self._last_check_ts < 0.8:
            return False
        self._last_check_ts = now_ts
        with SessionLocal() as rdb:
            row = (
                rdb.execute(
                    select(SyncExecution.cancel_requested_at, SyncExecution.cancel_message).where(SyncExecution.id == self.sync_execution_id)
                )
                .first()
            )
        if not row:
            return False
        cancel_requested_at, cancel_message = row
        if cancel_requested_at is None:
            return False
        self._cancelled = True
        self._message = str(cancel_message).strip() if cancel_message else None
        return True

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise SyncCancelled(self._message or "cancelled")


class Dl302SyncExecutor:
    def __init__(self, db: Session | None):
        self.db = db

    @staticmethod
    def _read_with_session(loader):
        with SessionLocal() as db:
            return loader(db)

    @staticmethod
    def _write_with_session(writer):
        with SessionLocal() as db:
            result = writer(db)
            db.commit()
            return result

    def run_sync_task(
        self,
        task: SyncTask,
        *,
        log: ExecutionLog | None = None,
        strategy_override: dict[str, Any] | None = None,
    ) -> SyncExecution:
        if not bool(getattr(task, "enabled", True)):
            raise bad_request("SYNC_TASK_DISABLED", "同步任务已禁用")

        log = log or ExecutionLog()
        log.set_stage("start")
        log.section("同步开始")
        log.line(f"执行时间: {log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        log.line(f"任务名称: {str(getattr(task, 'name', '') or '')}")
        log.line("")

        source = self._build_endpoint(task, side="source")
        target = self._build_endpoint(task, side="target")
        if "openlist" in {source.type, target.type}:
            raise bad_request("SYNC_ENDPOINT_COMBO_INVALID", "暂不支持网盘与 OpenList 混合同步")

        strategy = self._load_strategy(task, override=strategy_override)
        conflict_policy = "overwrite" if strategy.overwrite else "skip"

        task_id = int(getattr(task, "id", 0) or 0)
        lock_owner = f"{os.getpid()}:{threading.get_ident()}"
        try:
            lock_now = datetime.now()
            self._write_with_session(lambda db: db.add(SyncTaskLock(sync_task_id=task_id, locked_at=lock_now, owner=lock_owner)))
        except IntegrityError:
            raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(task_id))

        def _release_lock() -> None:
            try:
                with SessionLocal() as ldb:
                    ldb.execute(delete(SyncTaskLock).where(SyncTaskLock.sync_task_id == task_id))
                    ldb.commit()
            except Exception:
                pass

        now = datetime.now()
        initial_stats: dict[str, Any] = {
            "total_files": 0,
            "done_files": 0,
            "copied_files": 0,
            "deleted_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "total_bytes": 0,
            "done_bytes": 0,
            "dl302_task_id": None,
            "recent_events": [],
        }
        execution = SyncExecution(
            sync_task_id=task_id,
            status="running",
            stage=log.stage,
            started_at=now,
            created_at=now,
            heartbeat_at=now,
            stats_json=json.dumps(initial_stats, ensure_ascii=False),
        )
        try:
            def _create_execution(db: Session) -> None:
                db.add(execution)
                db.flush()
                db.expunge(execution)

            self._write_with_session(_create_execution)
        except Exception:
            _release_lock()
            raise

        cancel_checker = _CancelChecker(int(execution.id))
        dl302_task_id = ""
        cancel_sent = False
        last_status = ""
        item_event_cache: dict[str, tuple[str, str, int, int, str]] = {}
        last_stats: dict[str, Any] = dict(initial_stats)

        def persist_execution_state(*, stats_payload: dict[str, Any] | None = None, message: str | None = None) -> None:
            values: dict[str, Any] = {
                "stage": log.stage,
                "heartbeat_at": datetime.now(),
                "run_log": log.render(),
            }
            if stats_payload is not None:
                values["stats_json"] = json.dumps(stats_payload, ensure_ascii=False)
            if message is not None:
                values["message"] = str(message)
            with SessionLocal() as w:
                w.execute(update(SyncExecution).where(SyncExecution.id == int(execution.id)).values(**values))
                w.commit()

        try:
            persist_execution_state(stats_payload=initial_stats)
            self._emit_progress(log, initial_stats)
            cancel_checker.raise_if_cancelled()
            self._refresh_netdisk_endpoints_if_needed(source=source, target=target, strategy=strategy, log=log)
            log.set_stage("submit")
            log.section("提交 dl302 复制任务")
            log.line(f"源端: type={source.type} drive={source.drive_type} account={source.account_name or '-'} path={source.path}")
            log.line(f"目标端: type={target.type} drive={target.drive_type} account={target.account_name or '-'} path={target.path}")
            persist_execution_state(stats_payload=initial_stats)
            submit_resp = submit_copy_task(
                src_drive_type=source.drive_type,
                src_account=source.account_name,
                src_path=source.path,
                dst_drive_type=target.drive_type,
                dst_account=target.account_name,
                dst_path=target.path,
                conflict_policy=conflict_policy,
            )
            dl302_task_id = str(getattr(submit_resp, "task_id", "") or "").strip()
            if not dl302_task_id:
                raise RuntimeError("dl302 copy task id 为空")
            log.line(f"dl302_task_id={dl302_task_id}")
            persisted_stats = dict(initial_stats)
            persisted_stats["dl302_task_id"] = dl302_task_id
            persist_execution_state(stats_payload=persisted_stats, message=dl302_task_id)
            self._emit_progress(log, persisted_stats)
            last_stats = dict(persisted_stats)

            while True:
                cancel_checker.raise_if_cancelled()
                try:
                    task_resp = get_copy_task(task_id=dl302_task_id)
                    items_resp = list_copy_task_items(task_id=dl302_task_id)
                except Exception as exc:
                    if self._is_transient_rpc_error(exc):
                        log.line(f"dl302 轮询超时，稍后重试: {self._rpc_error_text(exc)}")
                        self._persist_progress(execution_id=int(execution.id), log=log, stats=last_stats)
                        time.sleep(1.5)
                        continue
                    raise
                task_status = str(getattr(task_resp, "status", "") or "").strip() or "pending"
                items = list(getattr(items_resp, "items", []) or [])

                stats = self._build_stats(task_resp, items, dl302_task_id=dl302_task_id)
                recent_events = last_stats.get("recent_events")
                if isinstance(recent_events, list):
                    stats["recent_events"] = list(recent_events)
                self._sync_file_rows(int(execution.id), items)

                if task_status != last_status:
                    log.set_stage(self._map_stage(task_status))
                    log.line(
                        f"dl302 状态: {task_status} "
                        f"items={int(stats.get('done_files', 0) or 0)}/{int(stats.get('total_files', 0) or 0)} "
                        f"bytes={int(stats.get('done_bytes', 0) or 0)}/{int(stats.get('total_bytes', 0) or 0)}"
                    )
                    last_status = task_status

                for item in items:
                    path = self._item_path(item)
                    status = str(getattr(item, "status", "") or "").strip() or "pending"
                    signature = self._item_event_signature(item)
                    prev = item_event_cache.get(path)
                    if prev == signature:
                        continue
                    item_event_cache[path] = signature
                    mapped_status = self._map_item_status(status)
                    msg = self._item_event_message(item)
                    if status in {"running", "done", "failed", "skipped", "cancelled"}:
                        suffix = f" msg={msg}" if msg else ""
                        log.line(f"文件状态: {status} path={path}{suffix}")
                        event = self._build_progress_event(item, path=path, status=mapped_status, message=msg or None)
                        self._push_recent_event(stats, event)
                        self._emit_progress(log, stats, event=event)

                if cancel_checker.is_cancelled() and not cancel_sent:
                    try:
                        cancel_copy_task(task_id=dl302_task_id)
                        cancel_sent = True
                        log.line("已向 dl302 发送取消请求")
                    except Exception as exc:
                        log.line(f"dl302 取消请求失败: {str(exc).strip() or type(exc).__name__}")

                self._persist_progress(execution_id=int(execution.id), log=log, stats=stats)
                self._emit_progress(log, stats)
                last_stats = dict(stats)

                if task_status in {"done", "failed", "cancelled"}:
                    break

                time.sleep(1.0)

            final_resp = get_copy_task(task_id=dl302_task_id)
            final_items_resp = list_copy_task_items(task_id=dl302_task_id)
            final_items = list(getattr(final_items_resp, "items", []) or [])
            final_stats = self._build_stats(final_resp, final_items, dl302_task_id=dl302_task_id)
            recent_events = last_stats.get("recent_events")
            if isinstance(recent_events, list):
                final_stats["recent_events"] = list(recent_events)
            self._sync_file_rows(int(execution.id), final_items)

            final_status = str(getattr(final_resp, "status", "") or "").strip() or "failed"
            if final_status == "done":
                log.set_stage("done")
                log.section("同步完成")
                log.line(
                    f"完成: items={int(getattr(final_resp, 'done_items', 0) or 0)}/{int(getattr(final_resp, 'total_items', 0) or 0)} "
                    f"bytes={int(getattr(final_resp, 'done_bytes', 0) or 0)}/{int(getattr(final_resp, 'total_bytes', 0) or 0)}"
                )
                execution.status = "success"
                execution.message = "success"
            elif final_status == "cancelled":
                self._mark_inflight_rows_aborted(int(execution.id))
                log.set_stage("aborted")
                log.section("已停止")
                log.line(str(getattr(final_resp, "message", "") or "cancelled"))
                execution.status = "aborted"
                execution.message = str(getattr(final_resp, "message", "") or "cancelled")
            else:
                last_error = str(getattr(final_resp, "last_error", "") or getattr(final_resp, "message", "") or "failed").strip() or "failed"
                log.set_stage("error")
                log.section("异常")
                log.line(last_error)
                execution.status = "failed"
                execution.message = last_error

            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.stats_json = json.dumps(final_stats, ensure_ascii=False)
            execution.run_log = log.render()
            execution.heartbeat_at = datetime.now()
            self._write_with_session(lambda db: db.merge(execution))
            _release_lock()
            if execution.status != "aborted":
                self._write_with_session(lambda db: send_sync_execution_notification(db, db.get(SyncTask, task_id), db.get(SyncExecution, int(execution.id))))
            return execution
        except SyncCancelled as exc:
            message = str(getattr(exc, "message", None) or str(exc) or "cancelled").strip() or "cancelled"
            if dl302_task_id and not cancel_sent:
                try:
                    cancel_copy_task(task_id=dl302_task_id)
                except Exception:
                    pass
            self._mark_inflight_rows_aborted(int(execution.id))
            log.set_stage("aborted")
            log.section("已停止")
            log.line(message)
            execution.status = "aborted"
            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.run_log = log.render()
            execution.message = f"aborted: {message}"
            execution.heartbeat_at = datetime.now()
            self._write_with_session(lambda db: db.merge(execution))
            _release_lock()
            return execution
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            log.set_stage("error")
            log.section("异常")
            log.line(message)
            execution.status = "failed"
            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.run_log = log.render()
            execution.message = message
            execution.heartbeat_at = datetime.now()
            self._write_with_session(lambda db: db.merge(execution))
            _release_lock()
            self._write_with_session(lambda db: send_sync_execution_notification(db, db.get(SyncTask, task_id), db.get(SyncExecution, int(execution.id))))
            raise

    def _build_endpoint(self, task: SyncTask, *, side: str) -> Dl302Endpoint:
        if side == "source":
            endpoint_type = str(getattr(task, "source_type", "") or "").strip()
            path = str(getattr(task, "source_path", "") or "").strip()
            account_id = getattr(task, "source_account_id", None)
        else:
            endpoint_type = str(getattr(task, "target_type", "") or "").strip()
            path = str(getattr(task, "target_path", "") or "").strip()
            account_id = getattr(task, "target_account_id", None)
        if endpoint_type == "local":
            root = local_sync_root().resolve()
            candidate = (root / str(path or "").replace("\\", "/").lstrip("/")).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                raise bad_request("SYNC_LOCAL_PATH_FORBIDDEN", "本地路径不允许")
            return Dl302Endpoint(type="local", path=str(candidate), drive_type="local", account_name="")
        if endpoint_type != "netdisk":
            return Dl302Endpoint(type=endpoint_type, path=path, drive_type=endpoint_type, account_name="")
        if account_id is None:
            raise bad_request("SYNC_NETDISK_ACCOUNT_INVALID", "网盘账号无效")
        account = self._read_with_session(lambda db: validate_netdisk_sync_account(db, int(account_id)))
        if account is None:
            raise bad_request("SYNC_NETDISK_ACCOUNT_INVALID", "网盘账号不存在")
        base_path = get_netdisk_sync_base_path(account)
        if not is_path_within_base(path, base_path):
            raise bad_request("SYNC_NETDISK_PATH_OUT_OF_302_SCOPE", "网盘路径必须位于 302_path 下")
        return Dl302Endpoint(
            type="netdisk",
            path=path,
            drive_type=str(getattr(account, "drive_type", "") or "").strip(),
            account_name=str(getattr(account, "name", "") or "").strip(),
            account_id=int(getattr(account, "id", 0) or 0),
            base_path=base_path,
        )

    def _load_strategy(self, task: SyncTask, *, override: dict[str, Any] | None) -> Dl302Strategy:
        base: dict[str, Any] = {}
        raw = getattr(task, "strategy_json", None)
        if raw:
            try:
                base = json.loads(raw)
            except Exception:
                base = {}
        if override:
            base = {**base, **override}
        return Dl302Strategy(
            overwrite=bool(base.get("overwrite", False)),
            force_refresh=bool(base.get("force_refresh", False)),
        )

    def _refresh_netdisk_endpoints_if_needed(
        self,
        *,
        source: Dl302Endpoint,
        target: Dl302Endpoint,
        strategy: Dl302Strategy,
        log: ExecutionLog,
    ) -> None:
        if not bool(strategy.force_refresh):
            return
        log.set_stage("refresh")
        log.section("刷新网盘目录缓存")
        for endpoint, recursive, label in ((source, True, "源端"), (target, False, "目标端")):
            if endpoint.type != "netdisk" or not endpoint.account_id:
                continue
            self._refresh_netdisk_endpoint(endpoint=endpoint, recursive=recursive, label=label, log=log)

    def _refresh_netdisk_endpoint(self, *, endpoint: Dl302Endpoint, recursive: bool, label: str, log: ExecutionLog) -> None:
        path = str(endpoint.path or "").strip() or str(endpoint.base_path or "/")
        log.line(
            f"{label}刷新: account={endpoint.account_name or '-'} drive={endpoint.drive_type or '-'} "
            f"path={path} recursive={'true' if recursive else 'false'}"
        )
        stats = refresh_drive_account_lsdir_paths(
            int(endpoint.account_id),
            savepath=path,
            relative_dir_paths=None,
            source=f"sync_executor_dl302.{label}",
            recursive_savepath=recursive,
            wait_if_busy=True,
            max_wait_seconds=60.0,
        )
        log.line(
            f"{label}刷新完成: scanned_dirs={int(getattr(stats, 'scanned_dirs', 0) or 0)} "
            f"cached_items={int(getattr(stats, 'cached_items', 0) or 0)}"
        )

    def _is_transient_rpc_error(self, exc: Exception) -> bool:
        if not isinstance(exc, grpc.RpcError):
            return False
        code_fn = getattr(exc, "code", None)
        code = code_fn() if callable(code_fn) else None
        return code in {grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE}

    def _rpc_error_text(self, exc: Exception) -> str:
        if not isinstance(exc, grpc.RpcError):
            return str(exc).strip() or type(exc).__name__
        code_fn = getattr(exc, "code", None)
        details_fn = getattr(exc, "details", None)
        code = code_fn() if callable(code_fn) else None
        details = details_fn() if callable(details_fn) else ""
        detail_text = str(details or "").strip()
        if detail_text:
            return f"{code.name if code else 'RPC_ERROR'}: {detail_text}"
        return code.name if code else (str(exc).strip() or type(exc).__name__)

    def _map_stage(self, status: str) -> str:
        return {
            "pending": "queue",
            "running": "copy",
            "done": "done",
            "failed": "error",
            "cancelled": "aborted",
        }.get(str(status or "").strip(), "copy")

    def _build_stats(self, task_resp, items, *, dl302_task_id: str) -> dict[str, Any]:
        skipped = 0
        copied = 0
        failed = 0
        computed_done_bytes = 0
        for item in items:
            status = self._map_item_status(str(getattr(item, "status", "") or "").strip())
            if status == "skipped":
                skipped += 1
            elif status == "success":
                copied += 1
                computed_done_bytes += int(getattr(item, "size", 0) or 0)
            elif status == "failed":
                failed += 1
            elif status == "syncing":
                computed_done_bytes += self._item_progress_bytes(item)
        done_bytes = int(getattr(task_resp, "done_bytes", 0) or 0)
        if computed_done_bytes > done_bytes:
            done_bytes = computed_done_bytes
        total_bytes = int(getattr(task_resp, "total_bytes", 0) or 0)
        if total_bytes > 0 and done_bytes > total_bytes:
            done_bytes = total_bytes
        return {
            "total_files": int(getattr(task_resp, "total_items", 0) or 0),
            "done_files": int(getattr(task_resp, "done_items", 0) or 0),
            "copied_files": copied,
            "deleted_files": 0,
            "skipped_files": skipped,
            "failed_files": int(getattr(task_resp, "failed_items", 0) or failed),
            "total_bytes": total_bytes,
            "done_bytes": done_bytes,
            "dl302_task_id": dl302_task_id,
        }

    def _build_progress_event(self, item, *, path: str, status: str, message: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ts": datetime.now().isoformat(),
            "action": "copy",
            "status": str(status or "").strip() or "pending",
            "path": str(path or "").strip(),
        }
        size = int(getattr(item, "size", 0) or 0)
        if size > 0:
            payload["size"] = size
        stage = str(getattr(item, "stage", "") or "").strip()
        if stage:
            payload["stage"] = stage
            payload["stage_label"] = self._stage_label(stage)
        stage_done = int(getattr(item, "stage_done", 0) or 0)
        stage_total = int(getattr(item, "stage_total", 0) or 0)
        if stage_done > 0:
            payload["stage_done"] = stage_done
        if stage_total > 0:
            payload["stage_total"] = stage_total
        progress_percent = self._item_progress_percent(item)
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent
        if message:
            payload["message"] = str(message)
        return payload

    def _item_progress_percent(self, item) -> float | None:
        total = int(getattr(item, "stage_total", 0) or 0)
        done = int(getattr(item, "stage_done", 0) or 0)
        if total <= 0:
            return None
        done = max(0, min(done, total))
        return round((done / total) * 100.0, 1)

    def _item_progress_bytes(self, item) -> int:
        size = int(getattr(item, "size", 0) or 0)
        stage_total = int(getattr(item, "stage_total", 0) or 0)
        if size <= 0 and stage_total > 0:
            size = stage_total
        if size < 0:
            size = 0
        status = str(getattr(item, "status", "") or "").strip()
        if status == "done":
            return size
        if status != "running":
            return 0
        total = stage_total if stage_total > 0 else size
        done = int(getattr(item, "stage_done", 0) or 0)
        done = max(0, done)
        if total > 0:
            done = min(done, total)
        if size > 0:
            done = min(done, size)
        stage = str(getattr(item, "stage", "") or "").strip()
        if stage == "downloading":
            return done // 3
        if stage == "hashing":
            return size // 3 + done // 3
        if stage == "uploading":
            return (2 * size) // 3 + done // 3
        if stage in {"rapid_upload", "export_rapid", "done"}:
            return size
        return min(done, size) if size > 0 else done

    def _item_event_message(self, item) -> str:
        status = str(getattr(item, "status", "") or "").strip()
        stage = str(getattr(item, "stage", "") or "").strip()
        stage_label = self._stage_label(stage)
        if status == "running":
            retry_count = int(getattr(item, "retry_count", 0) or 0)
            last_error = str(getattr(item, "last_error", "") or "").strip()
            if stage == "start" and retry_count > 0:
                if last_error:
                    return f"重试 {retry_count}: {last_error}"
                return f"重试 {retry_count}"
            progress_percent = self._item_progress_percent(item)
            if progress_percent is not None:
                if stage_label:
                    return f"{stage_label} {progress_percent:.1f}%"
                return f"{progress_percent:.1f}%"
            if stage_label:
                return stage_label
        return str(getattr(item, "last_error", "") or "").strip()

    def _stage_label(self, stage: str) -> str:
        normalized = str(stage or "").strip()
        return {
            "downloading": "下载",
            "hashing": "校验",
            "uploading": "上传",
            "rapid_upload": "秒传",
            "rapid_fallback": "秒传回退",
            "export_rapid": "生成秒传",
            "done": "完成",
        }.get(normalized, normalized)

    def _item_event_signature(self, item) -> tuple[str, str, int, int, str]:
        return (
            str(getattr(item, "status", "") or "").strip(),
            str(getattr(item, "stage", "") or "").strip(),
            int(getattr(item, "stage_done", 0) or 0),
            int(getattr(item, "stage_total", 0) or 0),
            str(getattr(item, "last_error", "") or "").strip(),
        )

    def _push_recent_event(self, stats: dict[str, Any], event: dict[str, Any], *, limit: int = 100) -> None:
        if not isinstance(stats, dict):
            return
        items = stats.get("recent_events")
        if not isinstance(items, list):
            items = []
        items.append(dict(event or {}))
        if len(items) > int(limit):
            items = items[-int(limit) :]
        stats["recent_events"] = items

    def _emit_progress(self, log: ExecutionLog, stats: dict[str, Any], event: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "total_files": int(stats.get("total_files") or 0),
            "done_files": int(stats.get("done_files") or 0),
            "copied_files": int(stats.get("copied_files") or 0),
            "deleted_files": int(stats.get("deleted_files") or 0),
            "skipped_files": int(stats.get("skipped_files") or 0),
            "failed_files": int(stats.get("failed_files") or 0),
            "total_bytes": int(stats.get("total_bytes") or 0),
            "done_bytes": int(stats.get("done_bytes") or 0),
        }
        if event is not None:
            payload["event"] = dict(event)
        log.progress(payload)

    def _item_path(self, item) -> str:
        for raw in (getattr(item, "dst_path", None), getattr(item, "src_path", None), getattr(item, "name", None)):
            text = str(raw or "").strip()
            if text:
                return text
        return f"item-{int(getattr(item, 'id', 0) or 0)}"

    def _map_item_status(self, status: str) -> str:
        return {
            "pending": "pending",
            "running": "syncing",
            "done": "success",
            "skipped": "skipped",
            "failed": "failed",
            "cancelled": "aborted",
        }.get(str(status or "").strip(), "pending")

    def _sync_file_rows(self, execution_id: int, items) -> None:
        with SessionLocal() as w:
            existing = (
                w.execute(select(SyncExecutionFile).where(SyncExecutionFile.sync_execution_id == int(execution_id)))
                .scalars()
                .all()
            )
            existing_map = {str(getattr(row, "path", "") or ""): row for row in existing}
            now = datetime.now()
            for item in items:
                path = self._item_path(item)
                row = existing_map.get(path)
                payload = {
                    "action": "copy",
                    "status": self._map_item_status(str(getattr(item, "status", "") or "pending")),
                    "size": int(getattr(item, "size", 0) or 0) or None,
                    "message": self._item_event_message(item) or None,
                    "updated_at": now,
                }
                if row is None:
                    row = SyncExecutionFile(
                        sync_execution_id=int(execution_id),
                        path=path,
                        created_at=now,
                        **payload,
                    )
                    w.add(row)
                    existing_map[path] = row
                    continue
                for key, value in payload.items():
                    setattr(row, key, value)
            w.commit()

    def _mark_inflight_rows_aborted(self, execution_id: int) -> None:
        with SessionLocal() as w:
            w.execute(
                update(SyncExecutionFile)
                .where(
                    SyncExecutionFile.sync_execution_id == int(execution_id),
                    SyncExecutionFile.status.in_(["pending", "syncing"]),
                )
                .values(status="aborted", message="aborted", updated_at=datetime.now())
            )
            w.commit()

    def _persist_progress(self, *, execution_id: int, log: ExecutionLog, stats: dict[str, Any]) -> None:
        with SessionLocal() as w:
            w.execute(
                update(SyncExecution)
                .where(SyncExecution.id == int(execution_id))
                .values(
                    stage=log.stage,
                    heartbeat_at=datetime.now(),
                    stats_json=json.dumps(stats, ensure_ascii=False),
                    run_log=log.render(),
                    message=str(stats.get("dl302_task_id") or ""),
                )
            )
            w.commit()
