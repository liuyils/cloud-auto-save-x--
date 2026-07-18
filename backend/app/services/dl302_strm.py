from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.drive_account import DriveAccount
from app.models.drive_account_lsdir_cache import DriveAccountLsdirCache
from app.services.dl302_settings import (
    DL302_SUPPORTED_DRIVE_TYPES,
    extract_dl302_strm_scan_base_paths,
    get_or_create_dl302_setting,
    load_dl302_config,
    update_dl302_setting,
)


logger = logging.getLogger(__name__)

_VIDEO_EXTS = {
    ".3g2",
    ".3gp",
    ".asf",
    ".mp4",
    ".mkv",
    ".avi",
    ".divx",
    ".f4v",
    ".flv",
    ".m4v",
    ".m2t",
    ".m2ts",
    ".mk3d",
    ".mov",
    ".mp2ts",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogm",
    ".ogv",
    ".qt",
    ".rm",
    ".rmvb",
    ".tp",
    ".trp",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
    ".xvid",
    ".iso"
}
_CAS_EXTS = {".cas"}

_DRIVE_TYPE_ROUTE_MAP = {
    "115": "/dl/115",
    "cloud139": "/dl/139",
    "cloud189": "/dl/189",
    "quark": "/dl/quark",
    "uc": "/dl/uc",
}

_MANIFEST_PREFIX = ".dl302_strm_manifest_"
_PATH_SEGMENT_SAFE_CHARS = "-._~"


class StrmSource(tuple):
    __slots__ = ()

    @property
    def scan_base_path(self) -> str:
        return str(self[0])

    @property
    def allowed_exts(self) -> set[str] | None:
        value = self[1]
        return value if value is None else set(value)

    @property
    def use_full_path_for_url(self) -> bool:
        return bool(self[2])


def load_effective_strm_config(db: Session, *, mode: str | None = None) -> dict[str, Any]:
    item = get_or_create_dl302_setting(db)
    config = load_dl302_config(item)
    if mode in {"auto", "independent"}:
        config["strm_mode"] = mode
    return config


def ensure_strm_prefix_url(db: Session, request: Request | None = None, *, persist_if_empty: bool = True) -> str | None:
    item = get_or_create_dl302_setting(db)
    config = load_dl302_config(item)
    prefix = str(config.get("strm_prefix_url") or "").strip() or None
    if prefix or not persist_if_empty or request is None:
        return prefix
    derived = derive_request_prefix_url(request)
    if not derived:
        return None
    update_dl302_setting(db, payload={"strm_prefix_url": derived})
    db.flush()
    return derived


def derive_request_prefix_url(request: Request | None) -> str | None:
    if request is None:
        return None
    proto = str(request.headers.get("x-forwarded-proto") or request.url.scheme or "http").strip() or "http"
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc or "").strip()
    if not host:
        return None
    return f"{proto}://{host}".rstrip("/")


def list_strm_source_accounts(db: Session) -> list[DriveAccount]:
    rows = (
        db.execute(
            select(DriveAccount).where(
                DriveAccount.enabled.is_(True),
                DriveAccount.runtime_status == "active",
                DriveAccount.drive_type.in_(DL302_SUPPORTED_DRIVE_TYPES),
            )
        )
        .scalars()
        .all()
    )
    drive_order = {code: idx for idx, code in enumerate(DL302_SUPPORTED_DRIVE_TYPES)}
    return sorted(
        rows,
        key=lambda item: (
            drive_order.get(str(getattr(item, "drive_type", "") or ""), 999),
            0 if bool(getattr(item, "is_default", False)) else 1,
            str(getattr(item, "name", "") or ""),
            int(getattr(item, "id", 0) or 0),
        ),
    )


def extract_account_media_base_paths(account: DriveAccount) -> list[str]:
    resolved = extract_dl302_strm_scan_base_paths(account)
    paths: list[str] = []
    seen: set[str] = set()
    for item in resolved:
        path = _normalize_posix_dir(item)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def list_account_strm_sources(config: dict[str, Any], account: DriveAccount) -> list[StrmSource]:
    sources: list[StrmSource] = []
    media_base_paths = extract_account_media_base_paths(account)
    if not media_base_paths:
        return sources
    include_cas_root = bool(config.get("strm_include_cas_root_dir"))
    raw_cas_root_dir = str(config.get("cas_root_dir") or "").strip()
    source_priority = str(config.get("strm_source_priority") or "video_first").strip().lower()
    use_full_media_path_for_url = len(media_base_paths) > 1
    for media_base_path in media_base_paths:
        media_video_source = StrmSource((media_base_path, _VIDEO_EXTS - _CAS_EXTS, use_full_media_path_for_url))
        media_cas_source = StrmSource((media_base_path, _CAS_EXTS, use_full_media_path_for_url))
        if source_priority == "cas_first":
            sources.extend([media_cas_source, media_video_source])
        else:
            sources.extend([media_video_source, media_cas_source])
    if include_cas_root and raw_cas_root_dir:
        normalized_cas_root = _normalize_posix_dir(raw_cas_root_dir)
        cas_source = StrmSource((normalized_cas_root, _CAS_EXTS, True))
        if source_priority == "cas_first":
            sources.insert(0, cas_source)
        else:
            sources.append(cas_source)
    return sources


def list_cached_media_items(
    db: Session,
    account_id: int,
    media_base_path: str,
    *,
    allowed_exts: set[str] | None = None,
) -> list[DriveAccountLsdirCache]:
    base = _normalize_posix_dir(media_base_path)
    stmt = select(DriveAccountLsdirCache).where(
        DriveAccountLsdirCache.account_id == int(account_id),
        DriveAccountLsdirCache.is_dir.is_(False),
    )
    if base != "/":
        stmt = stmt.where(
            (DriveAccountLsdirCache.full_path == base) | (DriveAccountLsdirCache.full_path.like(f"{base}/%"))
        )
    stmt = stmt.order_by(DriveAccountLsdirCache.full_path.asc())
    rows = db.execute(stmt).scalars().all()
    return [row for row in rows if _is_allowed_media_file_path(str(getattr(row, "full_path", "") or ""), allowed_exts)]


def build_auto_strm_tree(
    db: Session,
    accounts: list[DriveAccount],
    prefix_url: str,
    config: dict[str, Any],
) -> tuple[dict[str, str], int]:
    tree: dict[str, str] = {}
    skipped_accounts = 0
    for account in accounts:
        sources = list_account_strm_sources(config, account)
        if not sources:
            skipped_accounts += 1
            continue
        for source in sources:
            for row in list_cached_media_items(db, int(account.id), source.scan_base_path, allowed_exts=source.allowed_exts):
                full_path = _normalize_relative_media_path(str(row.full_path))
                relative_path = _to_relative_media_path(full_path, source.scan_base_path)
                output_relative_path = _normalize_strm_output_relative_path(relative_path)
                if not relative_path or not output_relative_path:
                    continue
                output_key = _media_path_to_strm_relative_path(output_relative_path)
                if output_key in tree:
                    continue
                url_path = full_path if source.use_full_path_for_url else relative_path
                tree[output_key] = render_auto_strm_url(prefix_url, url_path)
    return tree, skipped_accounts


def build_independent_strm_tree(
    db: Session,
    accounts: list[DriveAccount],
    prefix_url: str,
    config: dict[str, Any],
) -> tuple[dict[str, str], int]:
    tree: dict[str, str] = {}
    skipped_accounts = 0
    for account in accounts:
        sources = list_account_strm_sources(config, account)
        if not sources:
            skipped_accounts += 1
            continue
        drive_route = _DRIVE_TYPE_ROUTE_MAP.get(str(account.drive_type or ""))
        if not drive_route:
            skipped_accounts += 1
            continue
        account_dir = _sanitize_path_segment(str(account.name or "").strip() or f"account-{account.id}")
        for source in sources:
            for row in list_cached_media_items(db, int(account.id), source.scan_base_path, allowed_exts=source.allowed_exts):
                full_path = _normalize_relative_media_path(str(row.full_path))
                relative_path = _to_relative_media_path(full_path, source.scan_base_path)
                output_relative_path = _normalize_strm_output_relative_path(relative_path)
                if not relative_path or not output_relative_path:
                    continue
                output_key = _join_relative_output(account_dir, _media_path_to_strm_relative_path(output_relative_path))
                url_path = full_path if source.use_full_path_for_url else relative_path
                tree[output_key] = render_account_strm_url(prefix_url, str(account.drive_type), str(account.name), url_path)
    return tree, skipped_accounts


def render_auto_strm_url(prefix_url: str, relative_path: str) -> str:
    normalized = _normalize_relative_media_path(relative_path)
    return _render_path_style_strm_url(prefix_url, "/dl/auto", normalized)


def render_account_strm_url(prefix_url: str, drive_type: str, account_name: str, relative_path: str) -> str:
    route = _DRIVE_TYPE_ROUTE_MAP.get(str(drive_type or ""))
    if not route:
        raise ValueError(f"unsupported drive_type: {drive_type}")
    normalized = _normalize_relative_media_path(relative_path)
    _ = account_name
    return _render_path_style_strm_url(prefix_url, route, normalized)


def rebuild_dl302_strm(
    db: Session,
    *,
    request: Request | None = None,
    trigger: str,
    mode: str | None = None,
    persist_prefix_if_empty: bool = True,
) -> dict[str, Any]:
    config = load_effective_strm_config(db, mode=mode)
    effective_mode = str(config.get("strm_mode") or "auto")
    root_dir = str(config.get("strm_root_dir") or "/strm")
    prefix_url = ensure_strm_prefix_url(db, request, persist_if_empty=persist_prefix_if_empty) or str(config.get("strm_prefix_url") or "").strip()
    if not prefix_url:
        return {
            "ok": False,
            "mode": effective_mode,
            "strm_root_dir": root_dir,
            "generated_files": 0,
            "generated_dirs": 0,
            "skipped_accounts": 0,
            "message": "STRM 前缀 URL 为空，已跳过生成",
        }

    accounts = list_strm_source_accounts(db)
    if effective_mode == "independent":
        tree, skipped_accounts = build_independent_strm_tree(db, accounts, prefix_url, config)
    else:
        effective_mode = "auto"
        tree, skipped_accounts = build_auto_strm_tree(db, accounts, prefix_url, config)

    stats = _write_strm_files(root_dir=root_dir, mode=effective_mode, tree=tree)
    return {
        "ok": True,
        "mode": effective_mode,
        "strm_root_dir": root_dir,
        "generated_files": int(stats["generated_files"]),
        "generated_dirs": int(stats["generated_dirs"]),
        "skipped_accounts": int(skipped_accounts),
        "message": f"STRM 生成完成 trigger={trigger} mode={effective_mode} files={stats['generated_files']}",
    }


def maybe_auto_generate_dl302_strm(db: Session, *, source: str) -> dict[str, Any] | None:
    config = load_effective_strm_config(db)
    if not bool(config.get("strm_enabled")):
        return None
    if not str(config.get("strm_prefix_url") or "").strip():
        logger.info("dl302 strm auto generation skipped: missing prefix_url source=%s", source)
        return None
    return rebuild_dl302_strm(db, trigger=source, persist_prefix_if_empty=False)


def cleanup_dl302_strm_outputs(*, root_dir: str, mode: str) -> dict[str, int]:
    root = Path(str(root_dir or "").strip() or "/strm")
    manifest_path = root / f"{_MANIFEST_PREFIX}{_normalize_strm_mode(mode)}.json"
    previous_files = _load_manifest(manifest_path)
    removed_files = 0
    for relative_strm_path in previous_files:
        if _delete_managed_file(root, relative_strm_path):
            removed_files += 1
    try:
        if manifest_path.exists():
            manifest_path.unlink()
    except OSError:
        pass
    return {
        "removed_files": removed_files,
    }


def get_dl302_strm_summary(db: Session, *, mode: str | None = None) -> dict[str, Any]:
    config = load_effective_strm_config(db, mode=mode)
    effective_mode = str(config.get("strm_mode") or "auto")
    root_dir = str(config.get("strm_root_dir") or "/strm")
    prefix_url = str(config.get("strm_prefix_url") or "").strip()
    accounts = list_strm_source_accounts(db)
    path_ready_account_count = sum(1 for account in accounts if list_account_strm_sources(config, account))
    generated_files = _load_manifest(Path(root_dir) / f"{_MANIFEST_PREFIX}{effective_mode}.json")
    generated_dirs = {
        str(Path(relative_path).parent)
        for relative_path in generated_files
        if str(Path(relative_path).parent) not in {"", "."}
    }
    return {
        "enabled": bool(config.get("strm_enabled")),
        "mode": "independent" if effective_mode == "independent" else "auto",
        "prefix_ready": bool(prefix_url),
        "root_exists": Path(root_dir).exists(),
        "source_account_count": len(accounts),
        "path_ready_account_count": path_ready_account_count,
        "path_missing_account_count": max(0, len(accounts) - path_ready_account_count),
        "generated_file_count": len(generated_files),
        "generated_dir_count": len(generated_dirs),
    }


def _write_strm_files(*, root_dir: str, mode: str, tree: dict[str, str]) -> dict[str, int]:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / f"{_MANIFEST_PREFIX}{_normalize_strm_mode(mode)}.json"
    previous_files = _load_manifest(manifest_path)
    for relative_strm_path in previous_files:
        _delete_managed_file(root, relative_strm_path)

    generated_dirs: set[str] = set()
    current_manifest: list[str] = []
    for relative_strm_path, url in tree.items():
        target = root / Path(relative_strm_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(url), encoding="utf-8")
        current_manifest.append(relative_strm_path)
        parent_rel = str(Path(relative_strm_path).parent)
        if parent_rel and parent_rel != ".":
            generated_dirs.add(parent_rel)

    manifest_path.write_text(json.dumps(sorted(current_manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "generated_files": len(current_manifest),
        "generated_dirs": len(generated_dirs),
    }


def _load_account_config(account: DriveAccount) -> dict[str, Any]:
    raw = getattr(account, "config_json", None)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_posix_dir(value: str) -> str:
    text = str(value or "").strip() or "/"
    if not text.startswith("/"):
        text = "/" + text
    while "//" in text:
        text = text.replace("//", "/")
    if text != "/":
        text = text.rstrip("/")
    return text or "/"


def _normalize_relative_media_path(value: str) -> str:
    text = _normalize_posix_dir(value)
    return text if text.startswith("/") else f"/{text}"


def _render_path_style_strm_url(prefix_url: str, route: str, relative_path: str) -> str:
    encoded_path = _encode_relative_media_path(relative_path)
    return f"{prefix_url.rstrip('/')}{route}{encoded_path}"


def _encode_relative_media_path(value: str) -> str:
    normalized = _normalize_relative_media_path(value)
    return "/".join(_encode_path_segment(segment) for segment in normalized.split("/"))


def _encode_path_segment(segment: str) -> str:
    out: list[str] = []
    for char in str(segment or ""):
        if char.isascii() and (not char.isalnum() and char not in _PATH_SEGMENT_SAFE_CHARS):
            out.append(quote(char, safe=""))
        else:
            out.append(char)
    return "".join(out)


def _to_relative_media_path(full_path: str, media_base_path: str) -> str | None:
    full = _normalize_posix_dir(full_path)
    base = _normalize_posix_dir(media_base_path)
    if base == "/":
        return full
    if full == base:
        return "/"
    if not full.startswith(base + "/"):
        return None
    suffix = full[len(base) :]
    return _normalize_relative_media_path(suffix)


def _is_allowed_media_file_path(path: str, allowed_exts: set[str] | None = None) -> bool:
    suffix = Path(str(path or "")).suffix.lower()
    return suffix in (allowed_exts or (_VIDEO_EXTS | _CAS_EXTS))


def _join_relative_output(prefix: str, relative_media_path: str) -> str:
    normalized = _normalize_relative_media_path(relative_media_path).lstrip("/")
    return str(PurePosixPath(prefix) / normalized)


def _sanitize_path_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return text.replace("/", "_").replace("\\", "_")


def _normalize_strm_output_relative_path(relative_media_path: str | None) -> str | None:
    normalized = _normalize_relative_media_path(relative_media_path or "")
    if not normalized:
        return None
    path = PurePosixPath(normalized)
    name = path.name
    if name.lower().endswith(".cas"):
        name = name[:-4]
    if not name:
        return str(path.parent) if str(path.parent) not in {"", "."} else "/"
    parent = str(path.parent)
    if parent in {"", "."}:
        return f"/{name}"
    return str(PurePosixPath(parent) / name)


def _media_path_to_strm_relative_path(relative_media_path: str) -> str:
    normalized = str(relative_media_path or "").strip().lstrip("/")
    if not normalized:
        return "index.strm"
    posix_path = PurePosixPath(normalized)
    parent = posix_path.parent
    suffix = posix_path.suffix.lower()
    stem = posix_path.stem if suffix in _VIDEO_EXTS else posix_path.name
    filename = f"{stem}.strm"
    if str(parent) in {"", "."}:
        return filename
    return str(parent / filename)


def _load_manifest(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_strm_mode(mode: str | None) -> str:
    return "independent" if str(mode or "").strip() == "independent" else "auto"


def _delete_managed_file(root: Path, relative_strm_path: str) -> bool:
    target = root / Path(str(relative_strm_path or "").strip())
    try:
        if target.exists():
            target.unlink()
            deleted = True
        else:
            deleted = False
    except OSError:
        return False
    current = target.parent
    while current != root and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    return deleted
