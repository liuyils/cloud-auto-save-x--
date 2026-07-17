from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, bad_request, not_found
from app.db.session import SessionLocal
from app.extensions.adapters.adapter_factory import AdapterFactory
from app.extensions.adapters.drive_auth import DriveAuthRequired
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.services.drive_account_auth_sessions import create_auth_session

BEIJING_TZ = ZoneInfo('Asia/Shanghai')


@dataclass(slots=True)
class DriveAccountSnapshot:
    id: int
    name: str
    drive_type: str
    config_json: str | None
    cookie: str | None
    enabled: bool
    runtime_status: str | None
    probe_fail_count: int


@dataclass(slots=True)
class DriveAccountProbeOutcome:
    runtime_status: str
    last_error: str | None
    config_json: str | None
    cookie: str | None
    profile_json: str | None
    probe_fail_count: int
    enabled: bool
    last_checked_at: datetime


def list_drive_accounts(db: Session) -> list[DriveAccount]:
    return db.execute(select(DriveAccount).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())).scalars().all()


def get_drive_account(db: Session, account_id: int) -> DriveAccount:
    account = db.get(DriveAccount, account_id)
    if account is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '驱动账号不存在')
    return account


def create_drive_account(db: Session, **payload) -> DriveAccount:
    if payload['drive_type'] not in AdapterFactory.get_supported_types():
        raise bad_request('DRIVE_TYPE_INVALID', '不支持的驱动类型')
    exists = db.execute(select(DriveAccount.id).where(DriveAccount.name == payload['name'])).first()
    if exists:
        raise bad_request('DRIVE_ACCOUNT_EXISTS', '驱动账号名称已存在')
    config, cookie = _normalize_account_payload(
        payload['drive_type'],
        payload.get('config'),
        payload.get('cookie'),
    )
    account = DriveAccount(
        name=payload['name'],
        drive_type=payload['drive_type'],
        cookie=cookie,
        enabled=payload.get('enabled', True),
        is_default=payload.get('is_default', False),
        capacity_warning_threshold=payload.get('capacity_warning_threshold', 85),
    )
    account.config_json = json.dumps(config, ensure_ascii=False)
    db.add(account)
    db.flush()
    if account.is_default:
        set_default_drive_account(db, account.id)
    return account


def update_drive_account(db: Session, account_id: int, **payload) -> DriveAccount:
    account = get_drive_account(db, account_id)
    for key, value in payload.items():
        if key in {'cookie', 'config'}:
            continue
        if value is not None:
            setattr(account, key, value)
    if 'config' in payload or 'cookie' in payload:
        config, cookie = _normalize_account_payload(
            account.drive_type,
            payload.get('config'),
            payload.get('cookie'),
            current_config_json=account.config_json,
            current_cookie=account.cookie,
        )
        account.config_json = json.dumps(config, ensure_ascii=False)
        account.cookie = cookie
    db.flush()
    if payload.get('is_default'):
        set_default_drive_account(db, account.id)
    return account


def set_drive_account_enabled(db: Session, account_id: int, enabled: bool) -> DriveAccount:
    account = get_drive_account(db, account_id)
    account.enabled = enabled
    return account


def set_default_drive_account(db: Session, account_id: int) -> DriveAccount:
    account = get_drive_account(db, account_id)
    items = (
        db.execute(select(DriveAccount).where(DriveAccount.drive_type == account.drive_type))
        .scalars()
        .all()
    )
    for item in items:
        item.is_default = item.id == account.id
    return account


def delete_drive_account(db: Session, account_id: int) -> None:
    account = get_drive_account(db, account_id)
    db.delete(account)


def probe_drive_account(db: Session, account_id: int) -> DriveAccount:
    _rollback_clean_session_transaction(db)
    with SessionLocal() as rdb:
        snapshot = _load_drive_account_snapshot(rdb, account_id)
    outcome = _probe_drive_account_snapshot(snapshot)
    with SessionLocal() as wdb:
        account = get_drive_account(wdb, account_id)
        _apply_probe_outcome(account, outcome)
        wdb.commit()
    db.expire_all()
    return get_drive_account(db, account_id)


def sign_in_drive_account(db: Session, account_id: int) -> dict[str, Any]:
    with SessionLocal() as rdb:
        snapshot = _load_drive_account_snapshot(rdb, account_id)
    runtime_config = AdapterRegistry.parse_config_json(snapshot.drive_type, snapshot.config_json, snapshot.cookie)
    runtime_cookie = AdapterRegistry.serialize_config(snapshot.drive_type, runtime_config)
    adapter = AdapterFactory.create_adapter(
        snapshot.drive_type,
        runtime_cookie,
        config=runtime_config,
        account_name=snapshot.name,
    )
    if adapter is None:
        raise bad_request("DRIVE_SIGNIN_FAILED", "驱动实例创建失败")
    result = adapter.sign_in()
    if not isinstance(result, dict) or not result.get("supported"):
        raise bad_request("DRIVE_SIGNIN_UNSUPPORTED", "该网盘暂不支持签到")
    if not result.get("ok", True):
        raise bad_request("DRIVE_SIGNIN_FAILED", result.get("message") or "签到失败", detail=str(result.get("reward") or result.get("message") or ""))
    config_snapshot = merge_runtime_account_config_values(snapshot.drive_type, snapshot.config_json, snapshot.cookie, adapter.export_runtime_config())
    if isinstance(config_snapshot, dict) and config_snapshot:
        with SessionLocal() as wdb:
            account = get_drive_account(wdb, account_id)
            account.config_json = json.dumps(config_snapshot, ensure_ascii=False)
            account.cookie = AdapterRegistry.serialize_config(snapshot.drive_type, config_snapshot)
            wdb.commit()
        db.expire_all()
    return result


def _rollback_clean_session_transaction(db: Session) -> None:
    try:
        if db.new or db.dirty or db.deleted:
            return
        if db.in_transaction():
            db.rollback()
    except Exception:
        return


def supported_drive_types() -> list[dict[str, str]]:
    return AdapterRegistry.supported_drive_types()


def resolve_drive_account_config(account: DriveAccount) -> dict:
    return AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)


def resolve_drive_account_profile(account: DriveAccount) -> dict[str, Any]:
    if not account.profile_json:
        return {}
    try:
        profile = json.loads(account.profile_json)
    except (TypeError, ValueError):
        return {}
    return profile if isinstance(profile, dict) else {}


def merge_runtime_account_config(account: DriveAccount, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
    return merge_runtime_account_config_values(account.drive_type, account.config_json, account.cookie, runtime_config)


def extract_capacity_metrics(profile: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    used_value = profile.get('used_space')
    total_value = profile.get('total_space')
    try:
        used_space = int(used_value) if used_value is not None else None
    except (TypeError, ValueError):
        used_space = None
    try:
        total_space = int(total_value) if total_value is not None else None
    except (TypeError, ValueError):
        total_space = None

    usage_ratio: float | None = None
    if used_space is not None and total_space and total_space > 0:
        usage_ratio = round(used_space / total_space, 4)
    return used_space, total_space, usage_ratio


def serialize_drive_account(account: DriveAccount) -> dict[str, Any]:
    profile = resolve_drive_account_profile(account)
    used_space, total_space, usage_ratio = extract_capacity_metrics(profile)
    return {
        'id': account.id,
        'name': account.name,
        'drive_type': account.drive_type,
        'config': resolve_drive_account_config(account),
        'profile': profile,
        'enabled': account.enabled,
        'is_default': account.is_default,
        'capacity_warning_threshold': account.capacity_warning_threshold,
        'used_space': used_space,
        'total_space': total_space,
        'usage_ratio': usage_ratio,
        'runtime_status': account.runtime_status,
        'probe_fail_count': int(getattr(account, "probe_fail_count", 0) or 0),
        'last_checked_at': normalize_api_datetime(account.last_checked_at),
        'profile_updated_at': normalize_api_datetime(account.last_checked_at),
        'last_error': account.last_error,
        'created_at': normalize_api_datetime(account.created_at),
        'updated_at': normalize_api_datetime(account.updated_at),
    }


def refresh_drive_account_profiles(db: Session) -> list[DriveAccount]:
    with SessionLocal() as rdb:
        account_ids = [int(x) for x in rdb.execute(select(DriveAccount.id).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())).scalars().all()]
    for account_id in account_ids:
        probe_drive_account(db, account_id)
    db.expire_all()
    return list_drive_accounts(db)


def build_capacity_overview(db: Session) -> dict[str, Any]:
    accounts = [serialize_drive_account(item) for item in list_drive_accounts(db)]
    total_used_space = 0
    total_capacity = 0
    capacity_account_count = 0
    warning_accounts: list[dict[str, Any]] = []
    unsupported_accounts: list[dict[str, Any]] = []

    for item in accounts:
        usage_ratio = item['usage_ratio']
        total_space = item['total_space']
        used_space = item['used_space']
        threshold = item['capacity_warning_threshold']
        if used_space is not None and total_space is not None and total_space > 0:
            total_used_space += used_space
            total_capacity += total_space
            capacity_account_count += 1
            if usage_ratio is not None and usage_ratio >= threshold / 100:
                warning_accounts.append(item)
        else:
            unsupported_accounts.append(item)

    warning_accounts.sort(key=lambda item: (item['usage_ratio'] is None, -(item['usage_ratio'] or 0), item['name']))
    usage_ratio = round(total_used_space / total_capacity, 4) if total_capacity > 0 else None

    return {
        'summary': {
            'account_count': len(accounts),
            'enabled_account_count': sum(1 for item in accounts if item['enabled']),
            'capacity_account_count': capacity_account_count,
            'warning_account_count': len(warning_accounts),
            'total_used_space': total_used_space or None,
            'total_space': total_capacity or None,
            'usage_ratio': usage_ratio,
        },
        'accounts': accounts,
        'warning_accounts': warning_accounts,
        'unsupported_accounts': unsupported_accounts,
        'updated_at': max((item['profile_updated_at'] for item in accounts if item['profile_updated_at']), default=None),
    }


def _build_account_profile(adapter: Any, account: DriveAccount) -> dict[str, Any] | None:
    profile = adapter.get_account_config()
    if not isinstance(profile, dict):
        return None
    profile.setdefault('drive_type', account.drive_type)
    profile.setdefault('drive_name', account.drive_type)
    profile.setdefault('nickname', '')
    profile.setdefault('username', '')
    profile.setdefault('used_space', None)
    profile.setdefault('total_space', None)
    profile.setdefault('raw', None)
    return profile


def merge_runtime_account_config_values(
    drive_type: str,
    config_json: str | None,
    cookie: str | None,
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:
    current = AdapterRegistry.parse_config_json(drive_type, config_json, cookie)
    merged = dict(current)
    if isinstance(runtime_config, dict):
        for key, value in runtime_config.items():
            if value is None and key in merged:
                continue
            if isinstance(value, str) and not value.strip() and isinstance(merged.get(key), str) and str(merged.get(key) or "").strip():
                continue
            merged[key] = value
    return AdapterRegistry.normalize_config(drive_type, merged)


def _load_drive_account_snapshot(db: Session, account_id: int) -> DriveAccountSnapshot:
    account = get_drive_account(db, account_id)
    return DriveAccountSnapshot(
        id=int(account.id),
        name=str(account.name or ""),
        drive_type=str(account.drive_type or ""),
        config_json=account.config_json,
        cookie=account.cookie,
        enabled=bool(account.enabled),
        runtime_status=str(account.runtime_status or "") or None,
        probe_fail_count=int(getattr(account, "probe_fail_count", 0) or 0),
    )


def _probe_drive_account_snapshot(snapshot: DriveAccountSnapshot) -> DriveAccountProbeOutcome:
    runtime_config = AdapterRegistry.parse_config_json(snapshot.drive_type, snapshot.config_json, snapshot.cookie)
    runtime_cookie = AdapterRegistry.serialize_config(snapshot.drive_type, runtime_config)
    cookie_value = runtime_cookie if runtime_cookie else snapshot.cookie
    last_checked_at = datetime.now()
    adapter = AdapterFactory.create_adapter(
        snapshot.drive_type,
        runtime_cookie,
        config=runtime_config,
        account_name=snapshot.name,
    )
    ok = False
    runtime_status = "error"
    last_error: str | None = "驱动实例创建失败"
    config_json_value = snapshot.config_json
    profile_json_value: str | None = None

    if adapter is not None:
        try:
            ok = adapter.init()
            runtime_status = "active" if ok else "inactive"
            last_error = None if ok else "驱动初始化失败"
            if ok:
                config_snapshot = merge_runtime_account_config_values(
                    snapshot.drive_type,
                    snapshot.config_json,
                    snapshot.cookie,
                    adapter.export_runtime_config(),
                )
                if snapshot.drive_type == "cloud189":
                    refresh_token = str(config_snapshot.get("refresh_token") or config_snapshot.get("refreshToken") or "").strip()
                    if not refresh_token:
                        last_error = "dl302: 缺少 access_token/refresh_token，302/CAS 播放不可用，请重新登录"
                config_json_value = json.dumps(config_snapshot, ensure_ascii=False)
                cookie_value = AdapterRegistry.serialize_config(snapshot.drive_type, config_snapshot)
                profile = _build_account_profile(adapter, snapshot)
                if profile is not None:
                    profile_json_value = json.dumps(profile, ensure_ascii=False)
        except DriveAuthRequired as exc:
            session = create_auth_session(
                account_id=snapshot.id,
                drive_type=snapshot.drive_type,
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
                        "account_id": snapshot.id,
                        "drive_type": snapshot.drive_type,
                        "method": exc.method,
                        "session_id": session.session_id,
                        "payload": exc.payload,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            runtime_status = "error"
            last_error = str(exc)

    if ok:
        probe_fail_count = 0
        enabled = snapshot.enabled
    else:
        probe_fail_count = int(snapshot.probe_fail_count or 0) + 1
        enabled = snapshot.enabled and probe_fail_count < 3

    return DriveAccountProbeOutcome(
        runtime_status=runtime_status,
        last_error=last_error,
        config_json=config_json_value,
        cookie=cookie_value,
        profile_json=profile_json_value,
        probe_fail_count=probe_fail_count,
        enabled=enabled,
        last_checked_at=last_checked_at,
    )


def _apply_probe_outcome(account: DriveAccount, outcome: DriveAccountProbeOutcome) -> None:
    account.last_checked_at = outcome.last_checked_at
    account.runtime_status = outcome.runtime_status
    account.last_error = outcome.last_error
    account.probe_fail_count = int(outcome.probe_fail_count or 0)
    account.enabled = bool(outcome.enabled)
    if outcome.config_json is not None:
        account.config_json = outcome.config_json
    if outcome.cookie is not None:
        account.cookie = outcome.cookie
    if outcome.profile_json is not None:
        account.profile_json = outcome.profile_json


def normalize_api_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ)


def _normalize_account_payload(
    drive_type: str,
    config: dict | None,
    cookie: str | None,
    *,
    current_config_json: str | None = None,
    current_cookie: str | None = None,
) -> tuple[dict, str]:
    if config is not None:
        normalized_config = AdapterRegistry.normalize_config(drive_type, config)
    elif cookie is not None:
        normalized_config = AdapterRegistry.deserialize_cookie(drive_type, cookie)
    elif current_config_json is not None or current_cookie is not None:
        normalized_config = AdapterRegistry.parse_config_json(drive_type, current_config_json, current_cookie)
    else:
        raise bad_request('DRIVE_ACCOUNT_CONFIG_REQUIRED', '请填写驱动账号登录参数')
    runtime_cookie = AdapterRegistry.serialize_config(drive_type, normalized_config)
    if not runtime_cookie.strip():
        raise bad_request('DRIVE_ACCOUNT_CONFIG_REQUIRED', '请填写驱动账号登录参数')
    return normalized_config, runtime_cookie
