from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.schemas.dl302_settings import (
    DL302ConfigOut,
    DL302ConfigUpdateIn,
    DL302StrmGenerateIn,
    DL302StrmGenerateOut,
    DL302SupportedDriverOut,
)
from app.services import audit
from app.services.dl302_strm import cleanup_dl302_strm_outputs, ensure_strm_prefix_url, get_dl302_strm_summary, rebuild_dl302_strm
from app.services.dl302_settings import get_or_create_dl302_setting, list_supported_dl302_drivers, load_dl302_config, update_dl302_setting
from app.thirdparty.dl302_grpc_client import reload_dl302


router = APIRouter()
logger = logging.getLogger(__name__)


def _build_dl302_config_out(db: Session, item) -> DL302ConfigOut:
    payload = load_dl302_config(item)
    payload["strm_summary"] = get_dl302_strm_summary(db, mode=str(payload.get("strm_mode") or "auto"))
    return DL302ConfigOut(**payload)


@router.get("/drivers", response_model=list[DL302SupportedDriverOut], dependencies=[Depends(require_permissions(TASK_READ))])
def get_dl302_supported_drivers(db: Session = Depends(get_db)) -> list[DL302SupportedDriverOut]:
    return [DL302SupportedDriverOut(**item) for item in list_supported_dl302_drivers(db)]


@router.get("/config", response_model=DL302ConfigOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_dl302_config(request: Request, db: Session = Depends(get_db)) -> DL302ConfigOut:
    item = get_or_create_dl302_setting(db)
    persisted_prefix = ensure_strm_prefix_url(db, request=request, persist_if_empty=True)
    if persisted_prefix:
        db.commit()
        db.refresh(item)
    return _build_dl302_config_out(db, item)


@router.patch("/config", response_model=DL302ConfigOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_dl302_config(
    request: Request,
    payload: DL302ConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DL302ConfigOut:
    previous_item = get_or_create_dl302_setting(db)
    previous_config = load_dl302_config(previous_item)
    item = update_dl302_setting(db, payload=payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="dl302.config.update",
        target_type="dl302_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    ok, msg = reload_dl302()
    if not ok:
        logger.warning("dl302 reload failed after config update: %s", msg)
    config = load_dl302_config(item)
    if bool(config.get("strm_enabled")):
        strm_config_changed = any(
            key in payload.model_fields_set for key in {"strm_mode", "strm_root_dir", "strm_prefix_url"}
        )
        if strm_config_changed and (
            str(previous_config.get("strm_root_dir") or "") != str(config.get("strm_root_dir") or "")
            or str(previous_config.get("strm_mode") or "auto") != str(config.get("strm_mode") or "auto")
        ):
            cleanup_dl302_strm_outputs(
                root_dir=str(previous_config.get("strm_root_dir") or "/strm"),
                mode=str(previous_config.get("strm_mode") or "auto"),
            )
        result = rebuild_dl302_strm(
            db,
            request=request,
            trigger="config_update",
            persist_prefix_if_empty=True,
        )
        db.commit()
        db.refresh(item)
        if not bool(result.get("ok")):
            logger.warning("dl302 strm rebuild skipped after config update: %s", result.get("message"))
    return _build_dl302_config_out(db, item)


@router.post("/strm/generate", response_model=DL302StrmGenerateOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_dl302_strm_generate(
    request: Request,
    payload: DL302StrmGenerateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DL302StrmGenerateOut:
    result = rebuild_dl302_strm(
        db,
        request=request,
        trigger="manual",
        mode=payload.mode,
        persist_prefix_if_empty=bool(payload.persist_prefix_if_empty),
    )
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="dl302.strm.generate",
        target_type="dl302_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=bool(result.get("ok")),
        detail=f"mode={result.get('mode') or payload.mode or ''}",
    )
    db.commit()
    return DL302StrmGenerateOut(**result)
