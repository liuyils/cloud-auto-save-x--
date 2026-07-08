from __future__ import annotations

import json
import uuid
from pathlib import Path
import posixpath
from typing import Any
from datetime import datetime
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, not_found
from app.models.drive_account import DriveAccount
from app.models.task import Task
from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.services.dl302_settings import extract_dl302_media_base_path


DL302_SYNC_DRIVE_TYPES = {"115", "cloud139", "cloud189", "quark", "uc"}


def _local_sync_root() -> Path:
    backend_dir = Path(__file__).resolve().parents[2]
    return backend_dir / "data" / "sync"


def _validate_local_relative(path: str) -> str:
    path = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not path or path in {".", ".."}:
        raise bad_request("SYNC_LOCAL_PATH_INVALID", "本地路径无效")
    norm = posixpath.normpath(path)
    if norm.startswith("../") or norm == "..":
        raise bad_request("SYNC_LOCAL_PATH_FORBIDDEN", "本地路径不允许")
    return norm


def _normalize_posix_abs_path(path: str, *, error_code: str, error_message: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if not p:
        raise bad_request(error_code, error_message)
    if not p.startswith("/"):
        p = f"/{p}"
    norm = posixpath.normpath(p)
    if norm == ".":
        norm = "/"
    if not norm.startswith("/"):
        norm = f"/{norm}"
    return norm


def _validate_netdisk_account(db: Session, account_id: Any) -> DriveAccount:
    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        raise bad_request("SYNC_NETDISK_ACCOUNT_INVALID", "网盘账号无效")
    account = db.get(DriveAccount, aid)
    if account is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在")
    if not bool(getattr(account, "enabled", False)):
        raise bad_request("SYNC_NETDISK_ACCOUNT_DISABLED", "网盘账号未启用")
    drive_type = str(getattr(account, "drive_type", "") or "").strip()
    if drive_type not in DL302_SYNC_DRIVE_TYPES:
        raise bad_request("SYNC_NETDISK_ACCOUNT_UNSUPPORTED", "该账号不支持 dl302 网盘同步")
    return account


def validate_netdisk_sync_account(db: Session, account_id: Any) -> DriveAccount:
    return _validate_netdisk_account(db, account_id)


def get_netdisk_sync_base_path(account: DriveAccount) -> str:
    base_path = extract_dl302_media_base_path(account)
    if not base_path:
        raise bad_request("SYNC_NETDISK_302_PATH_REQUIRED", "网盘账号未配置 302_path")
    return _normalize_posix_abs_path(base_path, error_code="SYNC_NETDISK_302_PATH_REQUIRED", error_message="网盘账号未配置 302_path")


def is_path_within_base(path: str, base_path: str) -> bool:
    normalized_path = _normalize_posix_abs_path(path, error_code="SYNC_NETDISK_PATH_INVALID", error_message="网盘路径不能为空")
    normalized_base = _normalize_posix_abs_path(base_path, error_code="SYNC_NETDISK_302_PATH_REQUIRED", error_message="网盘账号未配置 302_path")
    return normalized_path == normalized_base or normalized_path.startswith(f"{normalized_base.rstrip('/')}/")


def coerce_netdisk_path_to_base(path: str, base_path: str) -> str:
    normalized_base = _normalize_posix_abs_path(base_path, error_code="SYNC_NETDISK_302_PATH_REQUIRED", error_message="网盘账号未配置 302_path")
    text = str(path or "").strip()
    if not text:
        return normalized_base
    normalized_path = _normalize_posix_abs_path(text, error_code="SYNC_NETDISK_PATH_INVALID", error_message="网盘路径不能为空")
    if is_path_within_base(normalized_path, normalized_base):
        return normalized_path
    return normalized_base


def _validate_endpoint(db: Session, tp: str, path: str, account_id: Any = None) -> tuple[str, str, int | None]:
    tp = str(tp or "").strip().lower()
    if tp not in {"local", "openlist", "netdisk"}:
        raise bad_request("SYNC_ENDPOINT_INVALID", "无效的同步端点类型")
    if tp == "local":
        root = _local_sync_root()
        root.mkdir(parents=True, exist_ok=True)
        if account_id not in (None, "", 0, "0"):
            raise bad_request("SYNC_LOCAL_ACCOUNT_FORBIDDEN", "本地端点不允许绑定网盘账号")
        return tp, _validate_local_relative(path), None
    if tp == "openlist":
        if account_id not in (None, "", 0, "0"):
            raise bad_request("SYNC_OPENLIST_ACCOUNT_FORBIDDEN", "OpenList 端点不允许绑定网盘账号")
        return tp, _normalize_posix_abs_path(path, error_code="SYNC_OPENLIST_PATH_INVALID", error_message="OpenList 路径不能为空"), None
    account = _validate_netdisk_account(db, account_id)
    netdisk_path = _normalize_posix_abs_path(path, error_code="SYNC_NETDISK_PATH_INVALID", error_message="网盘路径不能为空")
    base_path = get_netdisk_sync_base_path(account)
    if not is_path_within_base(netdisk_path, base_path):
        raise bad_request("SYNC_NETDISK_PATH_OUT_OF_302_SCOPE", "网盘路径必须位于 302_path 下")
    return tp, netdisk_path, int(account.id)


def _validate_endpoint_combo(source_type: str, target_type: str) -> None:
    kinds = {str(source_type or ""), str(target_type or "")}
    if "netdisk" in kinds and "openlist" in kinds:
        raise bad_request("SYNC_ENDPOINT_COMBO_INVALID", "暂不支持网盘与 OpenList 混合同步")


def list_sync_tasks(db: Session) -> list[SyncTask]:
    return db.execute(select(SyncTask).options(selectinload(SyncTask.executions)).order_by(SyncTask.id.desc())).scalars().all()


def get_sync_task(db: Session, sync_task_id: int) -> SyncTask:
    task = (
        db.execute(select(SyncTask).options(selectinload(SyncTask.executions)).where(SyncTask.id == sync_task_id))
        .scalars()
        .first()
    )
    if task is None:
        raise not_found("SYNC_TASK_NOT_FOUND", "同步任务不存在")
    return task


def create_sync_task(
    db: Session,
    *,
    name: str,
    enabled: bool,
    source: dict[str, Any],
    target: dict[str, Any],
    mode: str,
    strategy: dict[str, Any],
    drama_task_uids: list[str] | None = None,
    addition: dict[str, Any] | None = None,
) -> SyncTask:
    st, sp, sa = _validate_endpoint(db, source.get("type"), source.get("path"), source.get("account_id"))
    tt, tp, ta = _validate_endpoint(db, target.get("type"), target.get("path"), target.get("account_id"))
    _validate_endpoint_combo(st, tt)
    mode = str(mode or "one_way").strip() or "one_way"
    if mode not in {"one_way", "two_way"}:
        raise bad_request("SYNC_MODE_INVALID", "无效的同步模式")
    task = SyncTask(
        uid=uuid.uuid4().hex,
        name=str(name or "").strip(),
        enabled=bool(enabled),
        source_type=st,
        source_path=sp,
        source_account_id=sa,
        target_type=tt,
        target_path=tp,
        target_account_id=ta,
        mode=mode,
        strategy_json=json.dumps(strategy or {}, ensure_ascii=False),
        addition_json=json.dumps(addition or {}, ensure_ascii=False),
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    db.add(task)
    db.flush()
    _replace_drama_links(db, sync_task_uid=str(task.uid), drama_task_uids=drama_task_uids)
    return task


def update_sync_task(db: Session, sync_task_id: int, **payload: Any) -> SyncTask:
    task = get_sync_task(db, sync_task_id)
    if "name" in payload and payload["name"] is not None:
        task.name = str(payload["name"]).strip()
    if "enabled" in payload and payload["enabled"] is not None:
        task.enabled = bool(payload["enabled"])
    if "mode" in payload and payload["mode"] is not None:
        mode = str(payload["mode"] or "").strip() or "one_way"
        if mode not in {"one_way", "two_way"}:
            raise bad_request("SYNC_MODE_INVALID", "无效的同步模式")
        task.mode = mode
    if "source" in payload and payload["source"] is not None:
        st, sp, sa = _validate_endpoint(db, payload["source"].get("type"), payload["source"].get("path"), payload["source"].get("account_id"))
        task.source_type = st
        task.source_path = sp
        task.source_account_id = sa
    if "target" in payload and payload["target"] is not None:
        tt, tp, ta = _validate_endpoint(db, payload["target"].get("type"), payload["target"].get("path"), payload["target"].get("account_id"))
        task.target_type = tt
        task.target_path = tp
        task.target_account_id = ta
    _validate_endpoint_combo(task.source_type, task.target_type)
    if "strategy" in payload and payload["strategy"] is not None:
        task.strategy_json = json.dumps(payload["strategy"] or {}, ensure_ascii=False)
    if "addition" in payload and payload["addition"] is not None:
        task.addition_json = json.dumps(payload["addition"] or {}, ensure_ascii=False)
    if "drama_task_uids" in payload:
        _replace_drama_links(db, sync_task_uid=str(task.uid), drama_task_uids=payload.get("drama_task_uids"))
    task.updated_at = datetime.now()
    db.flush()
    return task


def _normalize_task_uids(value: list[str] | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in value:
        uid = str(raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _validate_drama_task_uids(db: Session, task_uids: list[str]) -> None:
    if not task_uids:
        return
    rows = db.execute(select(Task.task_uid).where(Task.task_uid.in_(task_uids), Task.task_type == "drama")).scalars().all()
    existing = {str(x) for x in rows if x}
    missing = [uid for uid in task_uids if uid not in existing]
    if missing:
        raise bad_request("SYNC_DRAMA_TASK_NOT_FOUND", "关联追剧任务不存在或不是追剧任务", detail=",".join(missing[:20]))


def _replace_drama_links(db: Session, *, sync_task_uid: str, drama_task_uids: list[str] | None) -> None:
    uids = _normalize_task_uids(drama_task_uids)
    _validate_drama_task_uids(db, uids)
    db.query(SyncTaskDramaLink).filter(SyncTaskDramaLink.sync_task_uid == str(sync_task_uid)).delete(synchronize_session=False)
    if uids:
        db.add_all([SyncTaskDramaLink(sync_task_uid=str(sync_task_uid), task_uid=str(uid)) for uid in uids])
    db.flush()


def delete_sync_task(db: Session, sync_task_id: int) -> None:
    task = get_sync_task(db, sync_task_id)
    db.query(SyncTaskDramaLink).filter(SyncTaskDramaLink.sync_task_uid == str(task.uid)).delete(synchronize_session=False)
    db.delete(task)
    db.flush()


def list_sync_executions(db: Session, sync_task_id: int, *, limit: int = 20) -> list[SyncExecution]:
    get_sync_task(db, sync_task_id)
    q = select(SyncExecution).where(SyncExecution.sync_task_id == sync_task_id).order_by(SyncExecution.id.desc())
    if limit > 0:
        q = q.limit(limit)
    return db.execute(q).scalars().all()


def list_sync_execution_files(
    db: Session,
    sync_task_id: int,
    sync_execution_id: int,
    *,
    offset: int = 0,
    limit: int = 500,
) -> list[SyncExecutionFile]:
    get_sync_task(db, sync_task_id)
    exe = (
        db.execute(select(SyncExecution).where(SyncExecution.id == sync_execution_id, SyncExecution.sync_task_id == sync_task_id))
        .scalars()
        .first()
    )
    if exe is None:
        raise not_found("SYNC_EXECUTION_NOT_FOUND", "同步执行不存在")
    status_rank = case(
        (SyncExecutionFile.status.in_(["syncing", "pending"]), 0),
        (SyncExecutionFile.status == "failed", 1),
        else_=2,
    )
    q = (
        select(SyncExecutionFile)
        .where(SyncExecutionFile.sync_execution_id == sync_execution_id)
        .order_by(status_rank.asc(), SyncExecutionFile.updated_at.desc(), SyncExecutionFile.path.asc(), SyncExecutionFile.id.desc())
        .offset(max(0, int(offset)))
    )
    if int(limit) > 0:
        q = q.limit(int(limit))
    return db.execute(q).scalars().all()


def list_sync_execution_files_page(
    db: Session,
    sync_task_id: int,
    sync_execution_id: int,
    *,
    offset: int = 0,
    limit: int = 500,
) -> tuple[list[SyncExecutionFile], int]:
    get_sync_task(db, sync_task_id)
    exe = (
        db.execute(select(SyncExecution).where(SyncExecution.id == sync_execution_id, SyncExecution.sync_task_id == sync_task_id))
        .scalars()
        .first()
    )
    if exe is None:
        raise not_found("SYNC_EXECUTION_NOT_FOUND", "同步执行不存在")

    normalized_offset = max(0, int(offset))
    normalized_limit = max(0, int(limit))
    total = int(
        db.execute(
            select(func.count(SyncExecutionFile.id)).where(SyncExecutionFile.sync_execution_id == sync_execution_id)
        ).scalar_one()
        or 0
    )
    rows = list_sync_execution_files(
        db,
        sync_task_id,
        sync_execution_id,
        offset=normalized_offset,
        limit=normalized_limit,
    )
    return rows, total


def local_sync_root() -> Path:
    root = _local_sync_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def browse_local_dir(dir_path: str) -> tuple[str, bool, list[dict[str, object]], list[dict[str, str]]]:
    root = local_sync_root()
    raw = str(dir_path or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        base = root
        rel = ""
    else:
        rel = _validate_local_relative(raw)
        base = root / rel

    segments = [s for s in rel.split("/") if s]
    paths: list[dict[str, str]] = []
    for i, name in enumerate(segments):
        p = "/".join(segments[: i + 1])
        paths.append({"name": name, "path": p})

    if not base.exists() or not base.is_dir():
        return rel, False, [], paths

    items: list[dict[str, object]] = []
    for it in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        try:
            st = it.stat()
        except Exception:
            st = None
        is_dir = it.is_dir()
        items.append(
            {
                "name": it.name,
                "path": (f"{rel}/{it.name}".lstrip("/") if rel else it.name),
                "is_dir": is_dir,
                "updated_at": int(st.st_mtime) if st is not None else None,
                "size": int(st.st_size) if (st is not None and not is_dir) else None,
            }
        )
    return rel, True, items, paths
