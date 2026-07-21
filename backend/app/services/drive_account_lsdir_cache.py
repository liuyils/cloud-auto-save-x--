from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.models.drive_account_lsdir_cache import DriveAccountLsdirCache


def _utcnow() -> datetime:
    return datetime.now()


def _normalize_parent_path(parent_path: str | None) -> str:
    text = str(parent_path or "").strip() or "/"
    if not text.startswith("/"):
        text = "/" + text
    while "//" in text:
        text = text.replace("//", "/")
    if text != "/":
        text = text.rstrip("/")
    return text or "/"


def _join_full_path(parent_path: str, name: str) -> str:
    clean_parent = _normalize_parent_path(parent_path)
    clean_name = str(name or "").strip().strip("/")
    if clean_parent == "/":
        return f"/{clean_name}" if clean_name else "/"
    return f"{clean_parent}/{clean_name}" if clean_name else clean_parent


def is_same_or_child_path(parent_path: str | None, child_path: str | None) -> bool:
    parent = _normalize_parent_path(parent_path)
    child = _normalize_parent_path(child_path)
    return child == parent or child.startswith(f"{parent.rstrip('/')}/")


def is_same_or_parent_path(parent_path: str | None, child_path: str | None) -> bool:
    return is_same_or_child_path(parent_path=parent_path, child_path=child_path)


def is_path_excluded(full_path: str | None, excluded_subtrees: list[str] | tuple[str, ...] | set[str] | None) -> bool:
    normalized = _normalize_parent_path(full_path)
    for raw in excluded_subtrees or ():
        excluded = _normalize_parent_path(raw)
        if is_same_or_child_path(parent_path=excluded, child_path=normalized):
            return True
    return False


def _pick_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("file_name")
        or payload.get("server_filename")
        or payload.get("fileName")
        or payload.get("name")
        or payload.get("title")
        or payload.get("fid")
        or payload.get("fs_id")
        or ""
    ).strip()


def _pick_fid(payload: dict[str, Any]) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "").strip()


def _bool_is_dir(payload: dict[str, Any]) -> bool:
    for key in ("is_dir", "dir", "is_folder", "folder", "isFolder"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "folder", "dir"}:
                return True
            if normalized in {"0", "false", "no", "file"}:
                return False
    return False


def _pick_size(payload: dict[str, Any]) -> int | None:
    value = payload.get("size")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_children_count(payload: dict[str, Any]) -> int | None:
    if payload.get("include_items") is not None:
        try:
            return int(payload.get("include_items"))
        except (TypeError, ValueError):
            pass
    for key in ("children_count", "child_count", "child_cnt", "count", "cnt", "total"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    file_count = None
    dir_count = None
    for key in ("file_count", "file_cnt", "files", "fileCount", "fileCnt", "sub_file_cnt", "subFileCount"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            file_count = int(value)
            break
        except (TypeError, ValueError):
            continue
    for key in ("dir_count", "dir_cnt", "dirs", "dirCount", "dirCnt", "sub_dir_cnt", "subDirCount"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            dir_count = int(value)
            break
        except (TypeError, ValueError):
            continue
    if file_count is None and dir_count is None:
        return None
    return int((file_count or 0) + (dir_count or 0))


def _parse_remote_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return _parse_remote_datetime(int(text))
        except ValueError:
            return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def normalize_lsdir_items(parent_path: str, items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized_parent = _normalize_parent_path(parent_path)
    result: list[dict[str, Any]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        fid = _pick_fid(raw)
        name = _pick_name(raw)
        if not fid or not name:
            continue
        is_dir = _bool_is_dir(raw)
        result.append(
            {
                "fid": fid,
                "name": name,
                "is_dir": is_dir,
                "size": _pick_size(raw),
                "children_count": _pick_children_count(raw),
                "updated_at_remote": _parse_remote_datetime(
                    raw.get("updated_at") or raw.get("update_time") or raw.get("mtime") or raw.get("modified_at")
                ),
                "full_path": _join_full_path(normalized_parent, name),
            }
        )
    return result


def delete_drive_account_lsdir_cache_by_account(db: Session, account_id: int) -> int:
    res = db.execute(delete(DriveAccountLsdirCache).where(DriveAccountLsdirCache.account_id == int(account_id)))
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def delete_drive_account_lsdir_cache_by_path(db: Session, *, account_id: int, full_path: str) -> int:
    path = _normalize_parent_path(full_path)
    if path == "/":
        return 0
    res = db.execute(
        delete(DriveAccountLsdirCache).where(
            DriveAccountLsdirCache.account_id == int(account_id),
            DriveAccountLsdirCache.full_path == path,
        )
    )
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def delete_drive_account_lsdir_cache_subtree_by_path(db: Session, *, account_id: int, full_path: str) -> int:
    path = _normalize_parent_path(full_path)
    if path == "/":
        return 0
    like_prefix = f"{path}/%"
    res = db.execute(
        delete(DriveAccountLsdirCache).where(
            DriveAccountLsdirCache.account_id == int(account_id),
            (DriveAccountLsdirCache.full_path == path) | (DriveAccountLsdirCache.full_path.like(like_prefix)),
        )
    )
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def upsert_drive_account_lsdir_items(
    db: Session,
    *,
    account_id: int,
    drive_type: str | None,
    parent_fid: str,
    parent_path: str,
    items: list[dict[str, Any]] | None,
    scanned_at: datetime | None = None,
) -> list[dict[str, Any]]:
    now = scanned_at or _utcnow()
    deduped_items: dict[str, dict[str, Any]] = {}
    for item in normalize_lsdir_items(parent_path, items):
        deduped_items[str(item["full_path"])] = item
    normalized_items = list(deduped_items.values())
    current_paths = [item["full_path"] for item in normalized_items]

    existing_map: dict[str, DriveAccountLsdirCache] = {}
    if current_paths:
        existing_rows = (
            db.execute(
                select(DriveAccountLsdirCache).where(
                    DriveAccountLsdirCache.account_id == int(account_id),
                    DriveAccountLsdirCache.full_path.in_(current_paths),
                )
            )
            .scalars()
            .all()
        )
        existing_map = {str(row.full_path): row for row in existing_rows}

    for item in normalized_items:
        row = existing_map.get(item["full_path"])
        if row is None:
            row = DriveAccountLsdirCache(
                account_id=int(account_id),
                full_path=item["full_path"],
                fid=item["fid"],
                name=item["name"],
            )
            db.add(row)
            existing_map[str(item["full_path"])] = row
        row.account_id = int(account_id)
        row.drive_type = str(drive_type or "").strip() or None
        row.parent_fid = str(parent_fid or "")
        row.fid = str(item["fid"])
        row.full_path = str(item["full_path"])
        row.name = str(item["name"])
        row.is_dir = bool(item["is_dir"])
        row.size = item["size"]
        row.updated_at_remote = item["updated_at_remote"]
        row.children_count = item["children_count"]
        row.scanned_at = now

    existing_children = (
        db.execute(
            select(DriveAccountLsdirCache).where(
                DriveAccountLsdirCache.account_id == int(account_id),
                DriveAccountLsdirCache.parent_fid == str(parent_fid or ""),
            )
        )
        .scalars()
        .all()
    )
    stale_children = [row for row in existing_children if row.full_path not in current_paths]
    for row in stale_children:
        if bool(getattr(row, "is_dir", False)):
            delete_drive_account_lsdir_cache_subtree_by_path(
                db,
                account_id=int(account_id),
                full_path=str(row.full_path),
            )
        else:
            delete_drive_account_lsdir_cache_by_path(
                db,
                account_id=int(account_id),
                full_path=str(row.full_path),
            )

    db.flush()
    return normalized_items


def get_drive_account_lsdir_cache_freshness(db: Session, *, account_id: int) -> dict[str, Any]:
    latest = (
        db.execute(
            select(
                func.max(DriveAccountLsdirCache.scanned_at),
                func.count(DriveAccountLsdirCache.id),
            ).where(DriveAccountLsdirCache.account_id == int(account_id))
        )
        .one()
    )
    scanned_at, total = latest
    return {
        "account_id": int(account_id),
        "scanned_at": scanned_at,
        "has_entries": bool(total),
        "total": int(total or 0),
    }


def get_drive_account_lsdir_cache_subtree_freshness(db: Session, *, account_id: int, full_path: str) -> dict[str, Any]:
    normalized_path = _normalize_parent_path(full_path)
    if normalized_path == "/":
        return get_drive_account_lsdir_cache_freshness(db, account_id=int(account_id))

    like_prefix = f"{normalized_path}/%"
    latest = (
        db.execute(
            select(
                func.max(DriveAccountLsdirCache.scanned_at),
                func.count(DriveAccountLsdirCache.id),
            ).where(
                DriveAccountLsdirCache.account_id == int(account_id),
                (DriveAccountLsdirCache.full_path == normalized_path) | (DriveAccountLsdirCache.full_path.like(like_prefix)),
            )
        )
        .one()
    )
    scanned_at, total = latest
    return {
        "account_id": int(account_id),
        "full_path": normalized_path,
        "scanned_at": scanned_at,
        "has_entries": bool(total),
        "total": int(total or 0),
    }


def get_drive_account_lsdir_cache_subtree_stats(db: Session, *, account_id: int, full_path: str) -> dict[str, Any]:
    normalized_path = _normalize_parent_path(full_path)
    filters = [DriveAccountLsdirCache.account_id == int(account_id)]
    if normalized_path != "/":
        like_prefix = f"{normalized_path}/%"
        filters.append((DriveAccountLsdirCache.full_path == normalized_path) | (DriveAccountLsdirCache.full_path.like(like_prefix)))

    scanned_at, entry_total, file_total, dir_total = (
        db.execute(
            select(
                func.max(DriveAccountLsdirCache.scanned_at),
                func.count(DriveAccountLsdirCache.id),
                func.coalesce(func.sum(case((DriveAccountLsdirCache.is_dir.is_(False), 1), else_=0)), 0),
                func.coalesce(func.sum(case((DriveAccountLsdirCache.is_dir.is_(True), 1), else_=0)), 0),
            ).where(*filters)
        )
        .one()
    )
    return {
        "account_id": int(account_id),
        "full_path": normalized_path,
        "scanned_at": scanned_at,
        "entry_total": int(entry_total or 0),
        "file_total": int(file_total or 0),
        "dir_total": int(dir_total or 0),
    }
