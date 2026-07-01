from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DL302SupportedDriverOut(BaseModel):
    code: str
    drive_name: str
    account_count: int = 0
    enabled_count: int = 0
    default_account_name: str | None = None


class DL302StrmSummaryOut(BaseModel):
    enabled: bool = False
    mode: Literal["auto", "independent"] = "auto"
    prefix_ready: bool = False
    root_exists: bool = False
    source_account_count: int = 0
    path_ready_account_count: int = 0
    path_missing_account_count: int = 0
    generated_file_count: int = 0
    generated_dir_count: int = 0


class DL302ConfigOut(BaseModel):
    proxy_url: str | None = None
    proxy_path_offset: int = -1
    intranet_cidrs: list[str] = Field(default_factory=list)
    strm_enabled: bool = False
    strm_mode: Literal["auto", "independent"] = "auto"
    strm_root_dir: str = "/strm"
    strm_prefix_url: str | None = None
    strm_summary: DL302StrmSummaryOut = Field(default_factory=DL302StrmSummaryOut)


class DL302ConfigUpdateIn(BaseModel):
    proxy_url: str | None = Field(default=None)
    proxy_path_offset: int | None = Field(default=None)
    intranet_cidrs: list[str] | None = Field(default=None)
    strm_enabled: bool | None = Field(default=None)
    strm_mode: Literal["auto", "independent"] | None = Field(default=None)
    strm_root_dir: str | None = Field(default=None)
    strm_prefix_url: str | None = Field(default=None)


class DL302StrmGenerateIn(BaseModel):
    mode: Literal["auto", "independent"] | None = Field(default=None)
    persist_prefix_if_empty: bool = Field(default=True)


class DL302StrmGenerateOut(BaseModel):
    ok: bool = True
    mode: Literal["auto", "independent"] = "auto"
    strm_root_dir: str = "/strm"
    generated_files: int = 0
    generated_dirs: int = 0
    skipped_accounts: int = 0
    message: str = ""
