from __future__ import annotations

import json
from pathlib import PurePosixPath

from app.core.errors import ApiError, bad_request, not_found
from app.models.drive_account import DriveAccount


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
    payload = str(getattr(account, "config_json", "") or "").strip()
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_media_base_path(data.get("302_path"))


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
    media_base_path = _extract_account_media_base_path(account)
    if require_media_base_path and not media_base_path:
        raise bad_request("DL302_CAS_302_PATH_REQUIRED", "当前账号未配置 302_path")
    if require_enabled and not bool(getattr(account, "enabled", False)):
        raise bad_request("DL302_CAS_ACCOUNT_DISABLED", "当前账号未启用")
    return account


def submit_dl302_cas_task(account_id: int, db) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import submit_cas_task
    from app.services.dl302_settings import get_or_create_dl302_setting, load_dl302_config

    config = load_dl302_config(get_or_create_dl302_setting(db))
    if not str(config.get("cas_root_dir") or "").strip():
        raise bad_request("DL302_CAS_ROOT_DIR_REQUIRED", "请先配置 CAS 文件生成目录")
    account = _resolve_account(account_id, db, require_media_base_path=True, require_enabled=True)
    resp = submit_cas_task(
        drive_type=str(getattr(account, "drive_type", "") or ""),
        account=str(getattr(account, "name", "") or ""),
    )
    return _task_to_dict(getattr(resp, "task", None))


def submit_dl302_cas_task_delta(
    account_id: int,
    db,
    *,
    base_path: str | None = None,
    dir_paths: list[str] | None,
    file_paths: list[str] | None,
) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import submit_cas_task_delta
    from app.services.dl302_settings import get_or_create_dl302_setting, load_dl302_config

    config = load_dl302_config(get_or_create_dl302_setting(db))
    if not str(config.get("cas_root_dir") or "").strip():
        raise bad_request("DL302_CAS_ROOT_DIR_REQUIRED", "请先配置 CAS 文件生成目录")

    account = _resolve_account(account_id, db, require_media_base_path=True, require_enabled=True)
    media_base_path = _extract_account_media_base_path(account) or "/"
    effective_base_path = _normalize_media_base_path(base_path) or media_base_path
    if media_base_path != "/" and not (
        effective_base_path == media_base_path or effective_base_path.startswith(media_base_path + "/")
    ):
        raise bad_request(
            "DL302_CAS_BASE_PATH_OUTSIDE_302_PATH",
            f"CAS base_path 不在账号 302_path 范围内: base_path={effective_base_path} 302_path={media_base_path}",
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
            if effective_base_path != "/" and text != effective_base_path and not text.startswith(effective_base_path + "/"):
                continue
            out.append(text)
        return out

    filtered_dirs = _filter_within_base(dir_paths)
    filtered_files = _filter_within_base(file_paths)

    if (input_dir_count > 0 or input_file_count > 0) and not filtered_dirs and not filtered_files:
        raise bad_request(
            "DL302_CAS_DELTA_OUTSIDE_302_PATH",
            f"增量路径不在账号 302_path 范围内: 302_path={media_base_path}",
        )

    if len(filtered_files) > 5000:
        raise bad_request("DL302_CAS_DELTA_TOO_LARGE", "增量文件数过大，请改用目录增量或分批提交")

    resp = submit_cas_task_delta(
        drive_type=str(getattr(account, "drive_type", "") or ""),
        account=str(getattr(account, "name", "") or ""),
        base_path=effective_base_path,
        dir_paths=filtered_dirs,
        file_paths=filtered_files,
    )
    return _task_to_dict(getattr(resp, "task", None))


def list_dl302_cas_tasks(account_id: int, db, *, limit: int = 5) -> list[dict[str, object]]:
    from app.thirdparty.dl302_grpc_client import list_cas_tasks

    account = _resolve_account(account_id, db)
    resp = list_cas_tasks(
        drive_type=str(getattr(account, "drive_type", "") or ""),
        account=str(getattr(account, "name", "") or ""),
        limit=int(limit or 5),
    )
    return [_task_to_dict(item) for item in list(getattr(resp, "tasks", []) or [])]


def get_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import get_cas_task

    resp = get_cas_task(task_id=str(task_id or ""))
    return _task_to_dict(getattr(resp, "task", None))


def list_dl302_cas_task_items(task_id: str) -> list[dict[str, object]]:
    from app.thirdparty.dl302_grpc_client import list_cas_task_items

    resp = list_cas_task_items(task_id=str(task_id or ""))
    return [_task_item_to_dict(item) for item in list(getattr(resp, "items", []) or [])]


def pause_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import pause_cas_task

    resp = pause_cas_task(task_id=str(task_id or ""))
    return _task_to_dict(getattr(resp, "task", None))


def resume_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import resume_cas_task

    resp = resume_cas_task(task_id=str(task_id or ""))
    return _task_to_dict(getattr(resp, "task", None))


def cancel_dl302_cas_task(task_id: str) -> dict[str, object]:
    from app.thirdparty.dl302_grpc_client import cancel_cas_task

    resp = cancel_cas_task(task_id=str(task_id or ""))
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
