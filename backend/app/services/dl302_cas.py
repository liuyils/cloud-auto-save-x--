from __future__ import annotations

import json
from pathlib import PurePosixPath

import grpc

from app.core.errors import ApiError, bad_request, not_found
from app.models.drive_account import DriveAccount
from app.services.dl302_settings import extract_dl302_cas_base_path, extract_dl302_cas_base_paths


def _normalize_media_base_path(raw: object) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        normalized = str(PurePosixPath(text))
    except Exception:
        return None
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    return normalized.rstrip("/") or "/"


def _extract_account_media_base_path(account: DriveAccount) -> str | None:
    return _normalize_media_base_path(extract_dl302_cas_base_path(account))


def _extract_account_media_base_paths(account: DriveAccount) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in extract_dl302_cas_base_paths(account):
        path = _normalize_media_base_path(raw)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _is_within_any_base(path: str, base_paths: list[str]) -> bool:
    if not base_paths:
        return False
    normalized_path = _normalize_media_base_path(path)
    if not normalized_path:
        return False
    for base_path in base_paths:
        normalized_base = _normalize_media_base_path(base_path)
        if not normalized_base:
            continue
        if normalized_base == "/" or normalized_path == normalized_base or normalized_path.startswith(normalized_base + "/"):
            return True
    return False


def _wrap_dl302_rpc_error(exc: Exception, *, action: str) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, grpc.RpcError):
        code_fn = getattr(exc, "code", None)
        status_code = code_fn() if callable(code_fn) else None
        detail = str(exc).strip() or None
        if status_code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return ApiError(code="DL302_RPC_TIMEOUT", message=f"dl302 {action}超时", http_status=504, detail=detail)
        if status_code == grpc.StatusCode.UNAVAILABLE:
            return ApiError(code="DL302_RPC_UNAVAILABLE", message="dl302 服务不可用", http_status=503, detail=detail)
        return ApiError(code="DL302_RPC_FAILED", message=f"dl302 {action}失败", http_status=502, detail=detail)
    detail = str(exc).strip() or None
    if detail == "task not found":
        return not_found("DL302_CAS_TASK_NOT_FOUND", "CAS 任务不存在")
    return ApiError(code="DL302_RPC_FAILED", message=f"dl302 {action}失败", http_status=502, detail=detail)


def _task_to_dict(task) -> dict[str, object]:
    if task is None:
        return {}
    return {
        "id": int(getattr(task, "id", 0) or 0),
        "task_id": str(getattr(task, "task_id", "") or ""),
        "drive_type": str(getattr(task, "drive_type", "") or ""),
        "account": str(getattr(task, "account", "") or ""),
        "base_path": str(getattr(task, "base_path", "") or ""),
        "status": str(getattr(task, "status", "pending") or "pending"),
        "total_items": int(getattr(task, "total_items", 0) or 0),
        "done_items": int(getattr(task, "done_items", 0) or 0),
        "failed_items": int(getattr(task, "failed_items", 0) or 0),
        "skipped_items": int(getattr(task, "skipped_items", 0) or 0),
        "total_bytes": int(getattr(task, "total_bytes", 0) or 0),
        "done_bytes": int(getattr(task, "done_bytes", 0) or 0),
        "current_item_id": int(getattr(task, "current_item_id", 0) or 0),
        "last_error": str(getattr(task, "last_error", "") or ""),
        "created_at": str(getattr(task, "created_at", "") or "") or None,
        "updated_at": str(getattr(task, "updated_at", "") or "") or None,
        "finished_at": str(getattr(task, "finished_at", "") or "") or None,
    }


def _task_item_to_dict(item) -> dict[str, object]:
    return {
        "id": int(getattr(item, "id", 0) or 0),
        "task_id": str(getattr(item, "task_id", "") or ""),
        "file_id": str(getattr(item, "file_id", "") or ""),
        "file_path": str(getattr(item, "file_path", "") or ""),
        "name": str(getattr(item, "name", "") or ""),
        "size": int(getattr(item, "size", 0) or 0),
        "status": str(getattr(item, "status", "pending") or "pending"),
        "stage": str(getattr(item, "stage", "") or ""),
        "stage_done": int(getattr(item, "stage_done", 0) or 0),
        "stage_total": int(getattr(item, "stage_total", 0) or 0),
        "retry_count": int(getattr(item, "retry_count", 0) or 0),
        "last_error": str(getattr(item, "last_error", "") or ""),
        "rapid_drive_types": str(getattr(item, "rapid_drive_types", "") or ""),
    }


def _resolve_account(
    account_id: int,
    db,
    *,
    require_media_base_path: bool = False,
    require_enabled: bool = False,
) -> DriveAccount:
    account = db.get(DriveAccount, int(account_id))
    if account is None:
        raise not_found("DL302_CAS_ACCOUNT_NOT_FOUND", "驱动账号不存在")
    drive_type = str(getattr(account, "drive_type", "") or "").strip()
    if drive_type not in {"115", "cloud139", "cloud189", "quark", "uc"}:
        raise bad_request("DL302_CAS_DRIVE_UNSUPPORTED", "当前账号类型不支持 dl302 CAS 生成")
    media_base_paths = _extract_account_media_base_paths(account)
    if require_media_base_path and not media_base_paths:
        raise bad_request("DL302_CAS_302_PATH_REQUIRED", "当前账号未配置 STRM 扫描路径")
    if require_enabled and not bool(getattr(account, "enabled", False)):
        raise bad_request("DL302_CAS_ACCOUNT_DISABLED", "当前账号未启用")
    return account


def submit_dl302_cas_task(account_id: int, db, *, fast_compute: bool = False) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import submit_cas_task
    from app.services.dl302_settings import get_or_create_dl302_setting, load_dl302_config

    config = load_dl302_config(get_or_create_dl302_setting(db))
    if not str(config.get("cas_root_dir") or "").strip():
        raise bad_request("DL302_CAS_ROOT_DIR_REQUIRED", "请先配置 CAS 文件生成目录")
    account = _resolve_account(account_id, db, require_media_base_path=True, require_enabled=True)
    try:
        resp = submit_cas_task(
            drive_type=str(getattr(account, "drive_type", "") or ""),
            account=str(getattr(account, "name", "") or ""),
            fast_compute=bool(fast_compute),
        )
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务提交") from exc
    return _task_to_dict(getattr(resp, "task", None))


def submit_dl302_cas_task_delta(
    account_id: int,
    db,
    *,
    base_path: str | None = None,
    dir_paths: list[str] | None,
    file_paths: list[str] | None,
    fast_compute: bool = False,
) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import submit_cas_task_delta
    from app.services.dl302_settings import get_or_create_dl302_setting, load_dl302_config

    config = load_dl302_config(get_or_create_dl302_setting(db))
    if not str(config.get("cas_root_dir") or "").strip():
        raise bad_request("DL302_CAS_ROOT_DIR_REQUIRED", "请先配置 CAS 文件生成目录")

    account = _resolve_account(account_id, db, require_media_base_path=True, require_enabled=True)
    media_base_paths = _extract_account_media_base_paths(account)
    effective_base_path = _normalize_media_base_path(base_path) or (media_base_paths[0] if media_base_paths else "/")
    base_scope = ",".join(media_base_paths) if media_base_paths else "/"
    if not _is_within_any_base(effective_base_path, media_base_paths or ["/"]):
        raise bad_request(
            "DL302_CAS_BASE_PATH_OUTSIDE_302_PATH",
            f"CAS base_path 不在账号 STRM 扫描路径范围内: base_path={effective_base_path} strm_scan_path={base_scope}",
        )
    input_dir_count = len([x for x in (dir_paths or []) if str(x or "").strip()])
    input_file_count = len([x for x in (file_paths or []) if str(x or "").strip()])

    def _filter_within_base(values: list[str] | None) -> list[str]:
        out: list[str] = []
        for raw in values or []:
            text = str(raw or "").strip()
            if not text:
                continue
            if not text.startswith("/"):
                text = "/" + text.lstrip("/")
            if not _is_within_any_base(text, [effective_base_path]):
                continue
            out.append(text)
        return out

    filtered_dirs = _filter_within_base(dir_paths)
    filtered_files = _filter_within_base(file_paths)

    if (input_dir_count > 0 or input_file_count > 0) and not filtered_dirs and not filtered_files:
        raise bad_request(
            "DL302_CAS_DELTA_OUTSIDE_302_PATH",
            f"增量路径不在账号 STRM 扫描路径范围内: strm_scan_path={base_scope}",
        )

    if len(filtered_files) > 5000:
        raise bad_request("DL302_CAS_DELTA_TOO_LARGE", "增量文件数过大，请改用目录增量或分批提交")

    try:
        resp = submit_cas_task_delta(
            drive_type=str(getattr(account, "drive_type", "") or ""),
            account=str(getattr(account, "name", "") or ""),
            base_path=effective_base_path,
            dir_paths=filtered_dirs,
            file_paths=filtered_files,
            fast_compute=bool(fast_compute),
        )
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 增量任务提交") from exc
    return _task_to_dict(getattr(resp, "task", None))


def list_dl302_cas_tasks(account_id: int, db, *, limit: int = 5) -> list[dict[str, object]]:
    from app.thirdparty.dl302_grpc_client import list_cas_tasks

    account = _resolve_account(account_id, db)
    try:
        resp = list_cas_tasks(
            drive_type=str(getattr(account, "drive_type", "") or ""),
            account=str(getattr(account, "name", "") or ""),
            limit=int(limit or 5),
        )
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务列表查询") from exc
    return [_task_to_dict(item) for item in list(getattr(resp, "tasks", []) or [])]


def get_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import get_cas_task

    try:
        resp = get_cas_task(task_id=str(task_id or ""))
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务详情查询") from exc
    return _task_to_dict(getattr(resp, "task", None))


def list_dl302_cas_task_items(task_id: str) -> list[dict[str, object]]:
    from app.thirdparty.dl302_grpc_client import list_cas_task_items

    try:
        resp = list_cas_task_items(task_id=str(task_id or ""))
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务明细查询") from exc
    return [_task_item_to_dict(item) for item in list(getattr(resp, "items", []) or [])]


def pause_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import pause_cas_task

    try:
        resp = pause_cas_task(task_id=str(task_id or ""))
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务暂停") from exc
    return _task_to_dict(getattr(resp, "task", None))


def resume_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import resume_cas_task

    try:
        resp = resume_cas_task(task_id=str(task_id or ""))
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务恢复") from exc
    return _task_to_dict(getattr(resp, "task", None))


def cancel_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import cancel_cas_task

    try:
        resp = cancel_cas_task(task_id=str(task_id or ""))
    except Exception as exc:
        raise _wrap_dl302_rpc_error(exc, action="CAS 任务取消") from exc
    return _task_to_dict(getattr(resp, "task", None))


def get_dl302_cas_task_summary(account_id: int, db) -> dict[str, object] | None:
    try:
        account = _resolve_account(int(account_id), db)
    except ApiError:
        return None
    try:
        from app.thirdparty.dl302_grpc_client import list_cas_tasks

        resp = list_cas_tasks(
            drive_type=str(getattr(account, "drive_type", "") or ""),
            account=str(getattr(account, "name", "") or ""),
            limit=1,
        )
    except Exception:
        return None
    tasks = [_task_to_dict(item) for item in list(getattr(resp, "tasks", []) or [])]
    return tasks[0] if tasks else None
