from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

import logging
import json

from app.core.errors import ApiError, bad_request, not_found
from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import DRIVE_ACCOUNT_READ, DRIVE_ACCOUNT_WRITE
from app.db.session import get_db
from app.schemas.drive_account import DriveAccountCreateIn, DriveAccountLsdirCacheRefreshIn, DriveAccountLsdirCacheRefreshOut, DriveAccountOut, DriveAccountStatusIn, DriveAccountUpdateIn, DriveTypeOut
from app.schemas.drive_account_auth import DriveAccountCaptchaSubmitIn, DriveAccountSmsSubmitIn
from app.schemas.drive_account_probe_scheduler import DriveAccountProbeSchedulerSettingOut, DriveAccountProbeSchedulerSettingUpdateIn
from app.extensions.adapters.adapter_factory import AdapterFactory
from app.extensions.adapters.drive_auth import DriveAuthRequired
from app.extensions.adapters.aliyun_adapter import AliyunAdapter
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.extensions.runtime.task_scheduler import task_scheduler_manager
from app.models.drive_account import DriveAccount
from app.services.drive_account_probe_scheduler import get_or_create_drive_account_probe_scheduler_setting, update_drive_account_probe_scheduler_setting
from app.services.drive_account_auth_sessions import create_auth_session, delete_auth_session, get_auth_session
from app.services import audit
from app.services.drive_accounts import (
    create_drive_account,
    delete_drive_account,
    get_drive_account,
    list_drive_accounts,
    merge_runtime_account_config,
    normalize_api_datetime,
    probe_drive_account,
    refresh_drive_account_profiles,
    resolve_drive_account_config,
    serialize_drive_account,
    sign_in_drive_account,
    set_default_drive_account,
    set_drive_account_enabled,
    supported_drive_types,
    update_drive_account,
)
from app.services.drive_account_lsdir_cache import (
    delete_drive_account_lsdir_cache_by_account,
    get_drive_account_lsdir_cache_subtree_stats,
    is_same_or_child_path,
)
from app.services.drive_account_lsdir_scan import rebuild_drive_account_lsdir_cache_for_current_302_path
from app.services.drive_account_lsdir_static_state import clear_lsdir_scan_state, clear_static_scan_state
from app.services.dl302_settings import (
    extract_dl302_cache_base_path,
    extract_dl302_static_cache_base_path,
    get_or_create_dl302_setting,
    load_dl302_config,
)
from app.services.dl302_strm import ensure_strm_prefix_url
from app.services.drive_account_signin_jobs import get_drive_account_signin_job, submit_drive_account_signin_job
from app.thirdparty.dl302_grpc_client import reload_dl302

router = APIRouter()

logger = logging.getLogger(__name__)


def _reload_dl302_if_needed(drive_type: str | None) -> None:
    if str(drive_type or "") not in {"115", "cloud189", "cloud139", "quark", "uc"}:
        return
    ok, msg = reload_dl302()
    if not ok:
        logger.warning("dl302 reload failed: %s", msg)

def _out(item, *, db: Session | None = None) -> DriveAccountOut:
    payload = serialize_drive_account(item)
    base_path = extract_dl302_cache_base_path(item)
    static_base_path = extract_dl302_static_cache_base_path(item)
    stats_base_path = base_path or static_base_path
    payload["has_302_path"] = bool(stats_base_path)
    payload["lsdir_cache_base_path"] = stats_base_path
    payload["lsdir_cache_file_total"] = 0
    payload["lsdir_cache_updated_at"] = None
    if db is not None and getattr(item, "id", None) is not None and stats_base_path:
        total = 0
        latest_scanned_at = None

        def _merge_stats(full_path: str | None) -> None:
            nonlocal total, latest_scanned_at
            if not full_path:
                return
            stats = get_drive_account_lsdir_cache_subtree_stats(db, account_id=int(item.id), full_path=full_path)
            total += int(stats.get("file_total") or 0)
            scanned_at = stats.get("scanned_at")
            if scanned_at and (latest_scanned_at is None or scanned_at > latest_scanned_at):
                latest_scanned_at = scanned_at

        _merge_stats(base_path)
        if static_base_path and not is_same_or_child_path(parent_path=base_path, child_path=static_base_path):
            _merge_stats(static_base_path)

        payload["lsdir_cache_file_total"] = total
        payload["lsdir_cache_updated_at"] = normalize_api_datetime(latest_scanned_at)
    return DriveAccountOut(**payload)


def _drive_account_cache_signature(account: DriveAccount | None) -> dict[str, object] | None:
    if account is None:
        return None
    config = resolve_drive_account_config(account)
    dynamic_config = dict(config)
    dynamic_config.pop("static_lsdir_cache_path", None)
    return {
        "config": dynamic_config,
        "cookie": AdapterRegistry.serialize_config(account.drive_type, config),
        "base_path": extract_dl302_cache_base_path(account),
        "static_base_path": extract_dl302_static_cache_base_path(account),
        "drive_type": account.drive_type,
    }


def _should_rebuild_lsdir_cache(before: dict[str, object] | None, after: dict[str, object] | None) -> bool:
    if before is None or after is None:
        return True
    return (
        before.get("config") != after.get("config")
        or before.get("cookie") != after.get("cookie")
        or before.get("base_path") != after.get("base_path")
        or before.get("drive_type") != after.get("drive_type")
    )


def _should_rebuild_static_lsdir_cache(before: dict[str, object] | None, after: dict[str, object] | None) -> bool:
    if after is None:
        return False
    after_static = after.get("static_base_path")
    if before is None:
        return bool(after_static)
    return before.get("static_base_path") != after_static or before.get("drive_type") != after.get("drive_type")


def _request_lsdir_cache_rebuild(
    account_id: int,
    *,
    source: str,
    old_base_path: str | None = None,
    old_static_base_path: str | None = None,
    rebuild_dynamic: bool = True,
    rebuild_static: bool = False,
    rescan_static: bool = False,
) -> None:
    result = rebuild_drive_account_lsdir_cache_for_current_302_path(
        int(account_id),
        source=source,
        old_base_path=old_base_path,
        old_static_base_path=old_static_base_path,
        rebuild_dynamic=rebuild_dynamic,
        rebuild_static=rebuild_static,
        rescan_static=rescan_static,
    )
    logger.info(
        "drive account lsdir rebuild result account_id=%s source=%s cleared=%s queued=%s base_path=%s reason=%s static_requested=%s static_queued=%s static_skipped_reason=%s",
        account_id,
        source,
        result.get("cleared"),
        result.get("queued"),
        result.get("base_path"),
        result.get("reason"),
        result.get("static_requested"),
        result.get("static_queued"),
        result.get("static_skipped_reason"),
    )


def _resolve_qrcode_auth_adapter(drive_type: str):
    normalized = str(drive_type or "").strip().lower()
    if normalized == "aliyun":
        return AliyunAdapter, "aliyun"
    adapter_class = AdapterFactory.ADAPTER_MAP.get(normalized)
    if adapter_class is None:
        return None, normalized
    if hasattr(adapter_class, "start_tv_qrcode_auth") and hasattr(adapter_class, "poll_tv_qrcode_auth"):
        return adapter_class, "tv"
    return None, normalized



@router.get('/auth/{session_id}', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_auth_session_status(session_id: str):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    return {"account_id": session.account_id, "drive_type": session.drive_type, "method": session.method, "session_id": session.session_id, "payload": session.payload}


@router.get('', response_model=list[DriveAccountOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_accounts(db: Session = Depends(get_db)):
    return [_out(item, db=db) for item in list_drive_accounts(db)]


def _probe_scheduler_out(item) -> DriveAccountProbeSchedulerSettingOut:
    return DriveAccountProbeSchedulerSettingOut(
        enabled=bool(getattr(item, "enabled", True)),
        crontab=str(getattr(item, "crontab", "0 4 * * *") or "0 4 * * *"),
        timezone=str(getattr(item, "timezone", "Asia/Shanghai") or "Asia/Shanghai"),
        enabled_only=bool(getattr(item, "enabled_only", True)),
    )


@router.get('/types', response_model=list[DriveTypeOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_drive_types():
    return [DriveTypeOut(**item) for item in supported_drive_types()]


@router.get('/probe/scheduler', response_model=DriveAccountProbeSchedulerSettingOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_drive_account_probe_scheduler_setting(db: Session = Depends(get_db)):
    setting = get_or_create_drive_account_probe_scheduler_setting(db)
    db.commit()
    db.refresh(setting)
    return _probe_scheduler_out(setting)


@router.patch('/probe/scheduler', response_model=DriveAccountProbeSchedulerSettingOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_drive_account_probe_scheduler_setting(request: Request, payload: DriveAccountProbeSchedulerSettingUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    setting = update_drive_account_probe_scheduler_setting(db, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.probe_scheduler.update', target_type='drive_account_probe_scheduler_setting', target_id=str(setting.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(setting)
    task_scheduler_manager.reload()
    return _probe_scheduler_out(setting)


@router.post('', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account(request: Request, payload: DriveAccountCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = create_drive_account(db, **payload.model_dump())
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.create', target_type='drive_account', target_id=str(account.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    _request_lsdir_cache_rebuild(
        int(account.id),
        source="api.drive_accounts.create",
        rebuild_dynamic=True,
        rebuild_static=bool(extract_dl302_static_cache_base_path(account)),
    )
    return _out(account, db=db)


@router.patch('/{account_id}', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_account(request: Request, account_id: int, payload: DriveAccountUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    before_account = get_drive_account(db, account_id)
    before_signature = _drive_account_cache_signature(before_account)
    old_base_path = before_signature.get("base_path") if before_signature else None
    old_static_base_path = before_signature.get("static_base_path") if before_signature else None
    account = update_drive_account(db, account_id, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.update', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    after_signature = _drive_account_cache_signature(account)
    rebuild_dynamic = _should_rebuild_lsdir_cache(before_signature, after_signature)
    rebuild_static = _should_rebuild_static_lsdir_cache(before_signature, after_signature)
    if rebuild_dynamic or rebuild_static or (old_static_base_path and old_static_base_path != after_signature.get("static_base_path")):
        _request_lsdir_cache_rebuild(
            account_id,
            source="api.drive_accounts.update",
            old_base_path=str(old_base_path or "") or None,
            old_static_base_path=str(old_static_base_path or "") or None,
            rebuild_dynamic=rebuild_dynamic,
            rebuild_static=rebuild_static,
        )
    return _out(account, db=db)


@router.patch('/{account_id}/status', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_account_status(request: Request, account_id: int, payload: DriveAccountStatusIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.enabled:
        account = probe_drive_account(db, account_id)
        if account.runtime_status != "active":
            account.enabled = False
            audit.write_audit_log(
                db,
                actor_user_id=current.user.id,
                action="drive_account.status",
                target_type="drive_account",
                target_id=str(account_id),
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False,
                detail=f"enabled=True probe=failed fail_count={getattr(account, 'probe_fail_count', 0) or 0} error={account.last_error or ''}",
            )
            db.commit()
            db.refresh(account)
            raise bad_request("DRIVE_ACCOUNT_PROBE_FAILED", "账号探测失败，无法启用", detail=account.last_error or "驱动初始化失败")
        account.enabled = True
        account.probe_fail_count = 0
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action="drive_account.status",
            target_type="drive_account",
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
            detail="enabled=True probe=ok",
        )
        db.commit()
        db.refresh(account)
        _reload_dl302_if_needed(account.drive_type)
        return _out(account, db=db)

    account = set_drive_account_enabled(db, account_id, False)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="drive_account.status",
        target_type="drive_account",
        target_id=str(account_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail="enabled=False",
    )
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    return _out(account, db=db)


@router.post('/{account_id}/default', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_default(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = set_default_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.default', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    return _out(account, db=db)


@router.post('/{account_id}/lsdir-cache/refresh', response_model=DriveAccountLsdirCacheRefreshOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_lsdir_cache_refresh(
    request: Request,
    account_id: int,
    payload: DriveAccountLsdirCacheRefreshIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = get_drive_account(db, account_id)
    base_path = extract_dl302_cache_base_path(account)
    static_base_path = extract_dl302_static_cache_base_path(account)
    if not base_path and not static_base_path:
        raise bad_request("DRIVE_ACCOUNT_302_PATH_REQUIRED", "当前账号未配置缓存路径")
    dl302_config = load_dl302_config(get_or_create_dl302_setting(db))
    if bool(dl302_config.get("strm_enabled")):
        ensure_strm_prefix_url(db, request, persist_if_empty=True)
    result = rebuild_drive_account_lsdir_cache_for_current_302_path(
        int(account_id),
        source="api.drive_accounts.lsdir_cache_refresh",
        rebuild_dynamic=True,
        rescan_static=bool(payload.rescan_static),
    )
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action='drive_account.lsdir_cache_refresh',
        target_type='drive_account',
        target_id=str(account_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get('user-agent'),
        success=True,
        detail=(
            f"queued={bool(result.get('queued'))} reason={result.get('reason') or ''} "
            f"base_path={base_path or static_base_path or ''} "
            f"static_requested={bool(result.get('static_requested'))} "
            f"static_queued={bool(result.get('static_queued'))} "
            f"static_skipped_reason={result.get('static_skipped_reason') or ''}"
        ),
    )
    db.commit()
    return DriveAccountLsdirCacheRefreshOut(**result)


@router.delete('/{account_id}', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def delete_account(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = get_drive_account(db, account_id)
    delete_drive_account_lsdir_cache_by_account(db, int(account_id))
    clear_lsdir_scan_state(int(account_id), str(getattr(account, "drive_type", "") or ""))
    clear_static_scan_state(int(account_id), str(getattr(account, "drive_type", "") or ""))
    delete_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.delete', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    _reload_dl302_if_needed(getattr(account, "drive_type", None))
    return {'ok': True}


@router.post('/{account_id}/probe', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_probe(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = probe_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.probe', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    return _out(account, db=db)


@router.post('/{account_id}/auth/start', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_start(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = probe_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_start', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account, db=db)


@router.post('/{account_id}/auth/qrcode/start', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_qrcode_start(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.get(DriveAccount, account_id)
    if account is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
    adapter_class, adapter_mode = _resolve_qrcode_auth_adapter(account.drive_type)
    if adapter_class is None:
        raise bad_request("DRIVE_ACCOUNT_AUTH_UNSUPPORTED", "当前账号不支持扫码认证")
    if adapter_mode == "aliyun":
        resp = AliyunAdapter.generate_qrcode()
        if not isinstance(resp, dict) or not resp.get("success"):
            raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "生成二维码失败", detail=str((resp or {}).get("message") or ""))
        data = resp.get("data") or {}
        session_adapter = {"t": data.get("t") or "", "ck": data.get("ck") or ""}
        session_payload = {"qrcode_url": data.get("qrCodeUrl") or "", "status": "NEW"}
    else:
        config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
        resp = adapter_class.start_tv_qrcode_auth(config)
        if not isinstance(resp, dict) or not resp.get("success"):
            raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "生成 TV 二维码失败", detail=str((resp or {}).get("message") or ""))
        data = resp.get("data") or {}
        session_adapter = {
            "device_id": str(data.get("device_id") or config.get("device_id") or ""),
            "query_token": str(data.get("query_token") or config.get("query_token") or ""),
        }
        session_payload = {
            "qrcode_url": data.get("qrcode_url") or "",
            "qrcode_image": data.get("qrcode_image") or data.get("qrcode_url") or "",
            "status": str(data.get("status") or "NEW"),
            "message": str(data.get("message") or "等待扫码"),
            "device_id": session_adapter["device_id"],
            "query_token": session_adapter["query_token"],
        }
    session = create_auth_session(
        account_id=account.id,
        drive_type=account.drive_type,
        method="qrcode",
        adapter=session_adapter,
        payload=session_payload,
    )
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_start', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return {"account_id": account.id, "drive_type": account.drive_type, "method": "qrcode", "session_id": session.session_id, "payload": session.payload}


@router.post('/auth/{session_id}/qrcode/poll', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_qrcode_poll(request: Request, session_id: str, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "qrcode":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter_class, adapter_mode = _resolve_qrcode_auth_adapter(session.drive_type)
    if adapter_class is None:
        raise bad_request("DRIVE_ACCOUNT_AUTH_UNSUPPORTED", "当前账号不支持扫码认证")
    if adapter_mode == "aliyun":
        meta = session.adapter or {}
        t = str(meta.get("t") or "")
        ck = str(meta.get("ck") or "")
        resp = AliyunAdapter.query_qrcode_status(t, ck)
        if not isinstance(resp, dict) or not resp.get("success"):
            raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "查询二维码状态失败", detail=str((resp or {}).get("message") or ""))
        data = resp.get("data") or {}
        if str(data.get("status") or "") == "CONFIRMED" and str(data.get("refresh_token") or ""):
            delete_auth_session(session_id)
            account = db.get(DriveAccount, session.account_id)
            if account is None:
                raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
            config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
            config["refresh_token"] = str(data.get("refresh_token") or "")
            update_drive_account(db, account.id, config=config)
            db.commit()
            account = probe_drive_account(db, account.id)
            audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_confirm', target_type='drive_account', target_id=str(account.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
            db.commit()
            db.refresh(account)
            _reload_dl302_if_needed(account.drive_type)
            _request_lsdir_cache_rebuild(
                int(account.id),
                source="api.drive_accounts.auth_qrcode_confirm",
                rebuild_dynamic=True,
                rebuild_static=False,
            )
            return _out(account, db=db)
        session.payload.update({"status": str(data.get("status") or ""), "message": str(data.get("message") or "")})
    else:
        resp = adapter_class.poll_tv_qrcode_auth(session.adapter or {})
        if not isinstance(resp, dict) or not resp.get("success"):
            raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "查询 TV 二维码状态失败", detail=str((resp or {}).get("message") or ""))
        data = resp.get("data") or {}
        session.payload.update(
            {
                "status": str(data.get("status") or session.payload.get("status") or ""),
                "message": str(data.get("message") or session.payload.get("message") or ""),
                "device_id": str(data.get("device_id") or (session.adapter or {}).get("device_id") or ""),
                "query_token": str(data.get("query_token") or (session.adapter or {}).get("query_token") or ""),
            }
        )
        if data.get("qrcode_url") or data.get("qrcode_image"):
            session.payload["qrcode_url"] = str(data.get("qrcode_url") or data.get("qrcode_image") or "")
            session.payload["qrcode_image"] = str(data.get("qrcode_image") or data.get("qrcode_url") or "")
        session.adapter = {
            **dict(session.adapter or {}),
            "device_id": session.payload.get("device_id") or "",
            "query_token": session.payload.get("query_token") or "",
        }
        if str(data.get("status") or "") == "CONFIRMED" and str(data.get("refresh_token") or ""):
            delete_auth_session(session_id)
            account = db.get(DriveAccount, session.account_id)
            if account is None:
                raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
            config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
            config["refresh_token"] = str(data.get("refresh_token") or "")
            if str(data.get("device_id") or "").strip():
                config["device_id"] = str(data.get("device_id") or "").strip()
            if str(data.get("query_token") or "").strip():
                config["query_token"] = str(data.get("query_token") or "").strip()
            update_drive_account(db, account.id, config=config)
            db.commit()
            db.refresh(account)
            _reload_dl302_if_needed(account.drive_type)
            audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_confirm', target_type='drive_account', target_id=str(account.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True, detail="tv_credentials_saved")
            db.commit()
            _request_lsdir_cache_rebuild(
                int(account.id),
                source="api.drive_accounts.auth_qrcode_confirm_tv",
                rebuild_dynamic=True,
                rebuild_static=False,
            )
            return _out(account, db=db)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_poll', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    raise ApiError(
        code="DRIVE_ACCOUNT_AUTH_PENDING",
        message="扫码未完成",
        http_status=409,
        detail=json.dumps(
            {
                "account_id": session.account_id,
                "drive_type": session.drive_type,
                "method": "qrcode",
                "session_id": session.session_id,
                "payload": session.payload,
            },
            ensure_ascii=False,
        ),
    )


@router.post('/auth/{session_id}/captcha', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_captcha_submit(request: Request, session_id: str, payload: DriveAccountCaptchaSubmitIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "captcha":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    try:
        adapter.submit_captcha(payload.code)
    except DriveAuthRequired as exc:
        delete_auth_session(session_id)
        new_session = create_auth_session(
            account_id=session.account_id,
            drive_type=session.drive_type,
            method=exc.method,
            adapter=exc.adapter or adapter,
            payload=exc.payload,
        )
        raise ApiError(
            code="DRIVE_ACCOUNT_AUTH_REQUIRED",
            message=exc.message or "需要二次认证",
            http_status=409,
            detail=json.dumps(
                {
                    "account_id": session.account_id,
                    "drive_type": session.drive_type,
                    "method": exc.method,
                    "session_id": new_session.session_id,
                    "payload": exc.payload,
                },
                ensure_ascii=False,
            ),
        )
    delete_auth_session(session_id)
    account = db.get(DriveAccount, session.account_id)
    if account is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
    update_drive_account(db, session.account_id, config=merge_runtime_account_config(account, adapter.export_runtime_config()))
    db.commit()
    account = probe_drive_account(db, session.account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_captcha', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    _request_lsdir_cache_rebuild(
        int(account.id),
        source="api.drive_accounts.auth_captcha",
        rebuild_dynamic=True,
        rebuild_static=False,
    )
    return _out(account, db=db)


@router.post('/auth/{session_id}/sms/send', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_sms_send(request: Request, session_id: str, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "sms":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    result = adapter.send_sms()
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_sms_send', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return result


@router.post('/auth/{session_id}/sms/submit', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_sms_submit(request: Request, session_id: str, payload: DriveAccountSmsSubmitIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "sms":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    adapter.submit_sms(payload.code)
    delete_auth_session(session_id)
    account = db.get(DriveAccount, session.account_id)
    if account is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
    config_snapshot = merge_runtime_account_config(account, adapter.export_runtime_config())
    update_drive_account(db, session.account_id, config=config_snapshot)
    db.commit()
    try:
        account = probe_drive_account(db, session.account_id)
    except ApiError as exc:
        # 光鸭当前账号信息接口不稳定，短信登录成功后可能在二次 probe 时误判为仍需短信认证。
        if exc.code != "DRIVE_ACCOUNT_AUTH_REQUIRED" or str(session.drive_type or "") != "guangya":
            raise
        account = db.get(DriveAccount, session.account_id)
        if account is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
        nickname = str(getattr(adapter, "nickname", "") or config_snapshot.get("phone_number") or account.name or "").strip()
        username = str(config_snapshot.get("phone_number") or nickname).strip()
        account.runtime_status = "active"
        account.last_error = None
        account.probe_fail_count = 0
        account.profile_json = json.dumps(
            {
                "drive_type": str(session.drive_type or ""),
                "drive_name": str(getattr(adapter, "DRIVE_NAME", session.drive_type) or session.drive_type or ""),
                "nickname": nickname,
                "username": username,
                "used_space": None,
                "total_space": None,
                "raw": {"auth_completed": True, "probe_fallback": True},
            },
            ensure_ascii=False,
        )
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_sms_submit', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    _reload_dl302_if_needed(account.drive_type)
    _request_lsdir_cache_rebuild(
        int(account.id),
        source="api.drive_accounts.auth_sms_submit",
        rebuild_dynamic=True,
        rebuild_static=False,
    )
    return _out(account, db=db)


@router.post('/{account_id}/sign-in', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_sign_in(
    request: Request,
    account_id: int,
    async_mode: bool = Query(False, alias="async"),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if async_mode:
        get_drive_account(db, account_id)
        job = submit_drive_account_signin_job(int(account_id))
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action='drive_account.sign_in.submit',
            target_type='drive_account',
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=True,
        )
        db.commit()
        return {"ok": True, "async": True, **job}
    try:
        result = sign_in_drive_account(db, account_id)
        audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.sign_in', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
        db.commit()
        return result
    except ApiError as e:
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action='drive_account.sign_in',
            target_type='drive_account',
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=False,
            detail=f"{e.code}:{e.message}",
        )
        db.commit()
        raise
    except Exception as e:
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action='drive_account.sign_in',
            target_type='drive_account',
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=False,
            detail=str(e)[:500],
        )
        db.commit()
        raise ApiError(code="DRIVE_ACCOUNT_SIGN_IN_FAILED", message="签到失败", http_status=500, detail=str(e))


@router.get('/sign-in-jobs/{job_id}', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def get_account_sign_in_job(job_id: str):
    return get_drive_account_signin_job(job_id)


@router.post('/refresh-profiles', response_model=list[DriveAccountOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_refresh_profiles(request: Request, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    items = refresh_drive_account_profiles(db)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.refresh_profiles', target_type='drive_account', target_id='*', ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    for item in items:
        db.refresh(item)
    return [_out(item, db=db) for item in items]
