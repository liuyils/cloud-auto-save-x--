from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, not_found
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.schemas.task_browse import DriveBrowseIn, DriveBrowseItemOut, DriveBrowseOut, DriveBrowsePathOut


def _pick_default_account_name(db: Session, drive_type: str) -> str | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type, DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active.name
    fallback = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type)
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    return None if fallback is None else fallback.name


def _pick_any_default_account(db: Session) -> DriveAccount | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True)).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc()))
        .scalars()
        .first()
    )


def _get_active_account(db: Session, account_name: str) -> DriveAccount | None:
    name = str(account_name or "").strip()
    if not name:
        return None
    active = (
        db.execute(
            select(DriveAccount).where(
                DriveAccount.enabled.is_(True),
                DriveAccount.name == name,
                DriveAccount.runtime_status == "active",
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True), DriveAccount.name == name))
        .scalars()
        .first()
    )


def _bool_is_dir(payload: dict) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("kind") in ("file",):
        return False
    if payload.get("type") in ("folder", "dir"):
        return True
    if payload.get("type") in ("file",):
        return False
    if payload.get("file_type") is not None:
        value = str(payload.get("file_type"))
        if value in ("0", "dir", "folder"):
            return True
        if value in ("1", "file"):
            return False
    return False


def _pick_name(payload: dict) -> str:
    return str(
        payload.get("file_name")
        or payload.get("server_filename")
        or payload.get("fileName")
        or payload.get("name")
        or payload.get("title")
        or payload.get("fid")
        or payload.get("fs_id")
        or ""
    )


def _pick_fid(payload: dict) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "")


def _pick_updated_at(payload: dict):
    return payload.get("updated_at") or payload.get("update_time") or payload.get("mtime") or payload.get("modified_at")


def _pick_size(payload: dict) -> int | None:
    if payload.get("size") is None:
        return None
    try:
        return int(payload.get("size"))
    except (TypeError, ValueError):
        return None


def _pick_children_count(payload: dict) -> int | None:
    for key in ("include_items", "children_count", "child_count", "count", "total"):
        if payload.get(key) is None:
            continue
        try:
            return int(payload.get(key))
        except (TypeError, ValueError):
            continue
    return None


def browse_drive_directory(db: Session, payload: DriveBrowseIn) -> DriveBrowseOut:
    drive_type: str | None = None
    account_name = str(payload.account_name or "").strip() or None
    if account_name:
        account = _get_active_account(db, account_name)
        if account is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在或不可用")
        drive_type = str(account.drive_type)
    if not account_name:
        if payload.shareurl:
            drive_type = AdapterRegistry.detect_drive_type(payload.shareurl)
            if drive_type is None:
                raise bad_request("TASK_SHAREURL_INVALID", "无法识别的网盘分享链接")
            account_name = _pick_default_account_name(db, drive_type)
        else:
            any_default = _pick_any_default_account(db)
            if any_default:
                account_name = any_default.name
                drive_type = str(any_default.drive_type)
    if not account_name:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "没有可用的驱动账号")

    manager = DatabaseAccountManager(db)
    task_payload = {"shareurl": payload.shareurl or "", "account_name": account_name}
    manager.init_for_tasks([task_payload])
    adapter = manager.get_adapter_for_task(task_payload)
    if adapter is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "没有可用的驱动账号")

    dir_path = str(payload.dir_path or "").strip() or "/"
    is_fid_mode = ("/" not in dir_path) and (dir_path not in ("/", "0"))
    normalized_path = re.sub(r"/+", "/", dir_path)
    if not normalized_path.startswith("/") and not is_fid_mode:
        normalized_path = "/" + normalized_path
    normalized_path = normalized_path.rstrip("/")

    paths: list[DriveBrowsePathOut] = []
    if dir_path in ("/", "0"):
        pdir_fid = "0"
    elif is_fid_mode:
        pdir_fid = dir_path
    else:
        fid_list = adapter.get_fids([normalized_path]) or []
        match = None
        for item in fid_list:
            item_path = item.get("file_path") or item.get("path") or item.get("filePath")
            if item_path == normalized_path:
                match = item
                break
        if match is None and fid_list:
            match = fid_list[0]
        pdir_fid = str(match.get("fid")) if match and match.get("fid") else None

        segments = [s for s in normalized_path.split("/") if s]
        if segments:
            accum_paths = ["/" + "/".join(segments[: i + 1]) for i in range(len(segments))]
            fid_arr = adapter.get_fids(accum_paths) or []
            fid_map: dict[str, str] = {}
            for item in fid_arr:
                item_path = item.get("file_path") or item.get("path") or item.get("filePath")
                fid = item.get("fid")
                if item_path and fid:
                    fid_map[str(item_path)] = str(fid)
            for i, name in enumerate(segments):
                fid = fid_map.get(accum_paths[i])
                if fid:
                    paths.append(DriveBrowsePathOut(fid=fid, name=name))

    if not pdir_fid:
        return DriveBrowseOut(
            account_name=account_name,
            drive_type=drive_type,
            dir_path=dir_path,
            exists=False,
            pdir_fid=None,
            items=[],
            paths=paths,
        )

    listing = adapter.ls_dir(str(pdir_fid), max_items=payload.max_items)
    raw_items = (((listing or {}).get("data") or {}).get("list")) or []
    items: list[DriveBrowseItemOut] = []
    for raw in raw_items[: payload.max_items]:
        fid = _pick_fid(raw)
        name = _pick_name(raw)
        if not fid or not name:
            continue
        is_dir = _bool_is_dir(raw)
        items.append(
            DriveBrowseItemOut(
                fid=fid,
                name=name,
                is_dir=is_dir,
                updated_at=_pick_updated_at(raw),
                size=_pick_size(raw),
                include_items=_pick_children_count(raw) if is_dir else None,
                file_name=name,
                dir=is_dir,
            )
        )
    return DriveBrowseOut(
        account_name=account_name,
        drive_type=drive_type,
        dir_path=dir_path,
        exists=True,
        pdir_fid=str(pdir_fid),
        items=items,
        paths=paths,
    )
