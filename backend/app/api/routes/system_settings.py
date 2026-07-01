from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.schemas.system_settings import SaveRuleConfigOut, SaveRuleConfigUpdateIn
from app.services import audit
from app.services.system_settings import get_or_create_system_config, load_save_rule_config, update_save_rule_config


router = APIRouter()


@router.get("/save-rules", response_model=SaveRuleConfigOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_save_rule_config(db: Session = Depends(get_db)) -> SaveRuleConfigOut:
    item = get_or_create_system_config(db, config_key="save_rules")
    data = load_save_rule_config(item)
    return SaveRuleConfigOut(**data)


@router.patch("/save-rules", response_model=SaveRuleConfigOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_save_rule_config(
    request: Request,
    payload: SaveRuleConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SaveRuleConfigOut:
    item = update_save_rule_config(db, payload=payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="system_settings.save_rules.update",
        target_type="system_config",
        target_id="save_rules",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    data = load_save_rule_config(item)
    return SaveRuleConfigOut(**data)
