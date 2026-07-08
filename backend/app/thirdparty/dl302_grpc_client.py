from __future__ import annotations

import logging
import os
from typing import Tuple

import grpc

from app.thirdparty.dl302_rpc import dl302_pb2, dl302_pb2_grpc


logger = logging.getLogger(__name__)

_GRPC_CHANNEL_OPTIONS = (
    ("grpc.enable_retries", 1),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.max_receive_message_length", 32 * 1024 * 1024),
    ("grpc.max_send_message_length", 32 * 1024 * 1024),
)


def _grpc_addr() -> str:
    addr = str(os.getenv("DL302_GRPC_ADDR", "") or "").strip()
    if not addr:
        return "127.0.0.1:9001"
    return addr


def _message(resp, fallback: str) -> str:
    return str(getattr(resp, "message", "") or "").strip() or fallback


def _raise_if_not_ok(resp, fallback: str) -> None:
    if not bool(getattr(resp, "ok", False)):
        raise RuntimeError(_message(resp, fallback))


def _is_retryable_rpc_error(exc: Exception) -> bool:
    if not isinstance(exc, grpc.RpcError):
        return False
    code_fn = getattr(exc, "code", None)
    code = code_fn() if callable(code_fn) else None
    return code in {grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE}


def _call_dl302_rpc(method_name: str, request, *, timeout_seconds: float, fallback: str, retries: int = 0):
    attempts = max(1, int(retries) + 1)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with grpc.insecure_channel(_grpc_addr(), options=_GRPC_CHANNEL_OPTIONS) as channel:
                stub = dl302_pb2_grpc.Dl302ServiceStub(channel)
                rpc = getattr(stub, method_name)
                resp = rpc(request, timeout=timeout_seconds)
            _raise_if_not_ok(resp, fallback)
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable_rpc_error(exc):
                raise
            logger.warning("dl302 rpc retry method=%s attempt=%s/%s err=%s", method_name, attempt, attempts, exc)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(fallback)


def reload_dl302(*, timeout_seconds: float = 2.0) -> Tuple[bool, str]:
    try:
        with grpc.insecure_channel(_grpc_addr(), options=_GRPC_CHANNEL_OPTIONS) as channel:
            stub = dl302_pb2_grpc.Dl302ServiceStub(channel)
            resp = stub.Reload(dl302_pb2.ReloadRequest(), timeout=timeout_seconds)
            ok = bool(getattr(resp, "ok", False))
            msg = str(getattr(resp, "message", "") or "")
            return ok, msg or ("ok" if ok else "reload failed")
    except Exception as e:
        logger.warning("dl302 reload failed: %s", e)
        return False, str(e)


def submit_cas_task(*, drive_type: str, account: str, timeout_seconds: float = 20.0):
    request = dl302_pb2.SubmitCASTaskRequest(
        drive_type=str(drive_type or ""),
        account=str(account or ""),
    )
    return _call_dl302_rpc("SubmitCASTask", request, timeout_seconds=timeout_seconds, fallback="submit cas task failed", retries=1)


def submit_cas_task_delta(
    *,
    drive_type: str,
    account: str,
    base_path: str = "",
    dir_paths: list[str] | None,
    file_paths: list[str] | None,
    timeout_seconds: float = 30.0,
):
    request = dl302_pb2.SubmitCASTaskDeltaRequest(
        drive_type=str(drive_type or ""),
        account=str(account or ""),
        base_path=str(base_path or ""),
        dir_paths=[str(item or "") for item in (dir_paths or []) if str(item or "").strip()],
        file_paths=[str(item or "") for item in (file_paths or []) if str(item or "").strip()],
    )
    return _call_dl302_rpc("SubmitCASTaskDelta", request, timeout_seconds=timeout_seconds, fallback="submit cas task delta failed", retries=1)


def get_cas_task(*, task_id: str, timeout_seconds: float = 8.0):
    request = dl302_pb2.GetCASTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("GetCASTask", request, timeout_seconds=timeout_seconds, fallback="get cas task failed", retries=1)


def list_cas_tasks(*, drive_type: str, account: str, limit: int = 5, timeout_seconds: float = 8.0):
    request = dl302_pb2.ListCASTasksRequest(
        drive_type=str(drive_type or ""),
        account=str(account or ""),
        limit=int(limit or 5),
    )
    return _call_dl302_rpc("ListCASTasks", request, timeout_seconds=timeout_seconds, fallback="list cas tasks failed", retries=1)


def list_cas_task_items(*, task_id: str, timeout_seconds: float = 20.0):
    request = dl302_pb2.GetCASTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("ListCASTaskItems", request, timeout_seconds=timeout_seconds, fallback="list cas task items failed", retries=1)


def pause_cas_task(*, task_id: str, timeout_seconds: float = 8.0):
    request = dl302_pb2.GetCASTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("PauseCASTask", request, timeout_seconds=timeout_seconds, fallback="pause cas task failed", retries=1)


def resume_cas_task(*, task_id: str, timeout_seconds: float = 8.0):
    request = dl302_pb2.GetCASTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("ResumeCASTask", request, timeout_seconds=timeout_seconds, fallback="resume cas task failed", retries=1)


def cancel_cas_task(*, task_id: str, timeout_seconds: float = 8.0):
    request = dl302_pb2.GetCASTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("CancelCASTask", request, timeout_seconds=timeout_seconds, fallback="cancel cas task failed", retries=1)


def submit_copy_task(
    *,
    src_drive_type: str,
    src_account: str,
    src_path: str,
    dst_drive_type: str,
    dst_account: str,
    dst_parent_id: str = "",
    dst_path: str = "",
    conflict_policy: str = "",
    timeout_seconds: float = 20.0,
):
    request = dl302_pb2.CopyTaskRequest(
        src_drive_type=str(src_drive_type or ""),
        src_account=str(src_account or ""),
        src_path=str(src_path or ""),
        dst_drive_type=str(dst_drive_type or ""),
        dst_account=str(dst_account or ""),
        dst_parent_id=str(dst_parent_id or ""),
        dst_path=str(dst_path or ""),
        conflict_policy=str(conflict_policy or ""),
    )
    return _call_dl302_rpc("SubmitCopyTask", request, timeout_seconds=timeout_seconds, fallback="submit copy task failed", retries=1)


def get_copy_task(*, task_id: str, timeout_seconds: float = 15.0):
    request = dl302_pb2.GetCopyTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("GetCopyTask", request, timeout_seconds=timeout_seconds, fallback="get copy task failed", retries=1)


def list_copy_task_items(*, task_id: str, timeout_seconds: float = 25.0):
    request = dl302_pb2.GetCopyTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("ListCopyTaskItems", request, timeout_seconds=timeout_seconds, fallback="list copy task items failed", retries=1)


def cancel_copy_task(*, task_id: str, timeout_seconds: float = 10.0):
    request = dl302_pb2.GetCopyTaskRequest(task_id=str(task_id or ""))
    return _call_dl302_rpc("CancelCopyTask", request, timeout_seconds=timeout_seconds, fallback="cancel copy task failed", retries=1)
