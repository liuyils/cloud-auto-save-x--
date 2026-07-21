from __future__ import annotations

from pydantic import BaseModel, field_validator


class SetupStatusOut(BaseModel):
    initialized: bool


class SetupAdminIn(BaseModel):
    username: str
    password: str
    # Email is optional and only used as an internal identifier. When omitted it
    # is generated server-side as "{username}@local", so we intentionally do NOT
    # use EmailStr here (internal domains like "@local" are not RFC-valid).
    email: str | None = None

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("用户名不能为空")
        return value

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if not value:
            raise ValueError("密码不能为空")
        return value

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None
