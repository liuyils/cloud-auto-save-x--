from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.errors import unauthorized
from app.core.settings import settings
from app.core.permissions import NOTIFY_READ, NOTIFY_WRITE
from app.db.session import get_db
from app.schemas.notification import NotificationConfigOut, NotificationConfigUpdateIn, NotificationRuntimeIn, NotificationTestIn, NotificationTestOut
from app.services import audit
from app.services.notifications import legacy_notify
from app.services.notifications.sender import send_runtime, send_test
from app.services.notifications.settings import get_or_create_notification_setting, load_notification_config, update_notification_setting


router = APIRouter()


def _require_internal_runtime_token(request: Request) -> None:
    expected = str(settings.internal_runtime_notify_token or "").strip()
    provided = str(request.headers.get("x-internal-token") or "").strip()
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise unauthorized("NOTIFY_INTERNAL_TOKEN_INVALID", "内部通知凭证无效")


@router.get("/config", response_model=NotificationConfigOut, dependencies=[Depends(require_permissions(NOTIFY_READ))])
def get_notification_config(db: Session = Depends(get_db)):
    item = get_or_create_notification_setting(db)
    config = load_notification_config(item)
    return NotificationConfigOut(
        config=config,
        default_config=dict(legacy_notify.DEFAULT_PUSH_CONFIG),
        updated_at=item.updated_at,
    )


@router.patch("/config", response_model=NotificationConfigOut, dependencies=[Depends(require_permissions(NOTIFY_WRITE))])
def patch_notification_config(
    request: Request,
    payload: NotificationConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = update_notification_setting(db, config=payload.config)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="notify.config.update",
        target_type="notification_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    config = load_notification_config(item)
    return NotificationConfigOut(
        config=config,
        default_config=dict(legacy_notify.DEFAULT_PUSH_CONFIG),
        updated_at=item.updated_at,
    )


@router.post("/test", response_model=NotificationTestOut, dependencies=[Depends(require_permissions(NOTIFY_WRITE))])
def post_notification_test(
    request: Request,
    payload: NotificationTestIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = get_or_create_notification_setting(db)
    config = load_notification_config(item)
    results = send_test(payload.title, payload.content, config=config, channels=payload.channels)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="notify.test.send",
        target_type="notification_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"channels={len(results)} filter={'1' if payload.channels else '0'}",
    )
    db.commit()
    return NotificationTestOut(results=results)


@router.post("/internal/runtime", response_model=NotificationTestOut)
def post_internal_runtime_notification(
    request: Request,
    payload: NotificationRuntimeIn,
    db: Session = Depends(get_db),
):
    _require_internal_runtime_token(request)
    results = send_runtime(db, payload.title, payload.content, channels=payload.channels)
    return NotificationTestOut(results=results)
