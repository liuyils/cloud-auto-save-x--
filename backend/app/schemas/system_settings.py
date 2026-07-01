from __future__ import annotations

from pydantic import BaseModel


class SaveRuleConfigOut(BaseModel):
    enable_skip_transferred_history: bool = False


class SaveRuleConfigUpdateIn(BaseModel):
    enable_skip_transferred_history: bool | None = None
