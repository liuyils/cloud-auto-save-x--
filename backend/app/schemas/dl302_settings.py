from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DL302SupportedDriverOut(BaseModel):
    code: str
    drive_name: str
    account_count: int = 0
    enabled_count: int = 0
    default_account_name: str | None = None
    accounts: list["DL302SupportedAccountOut"] = Field(default_factory=list)


class DL302CASTaskOut(BaseModel):
    id: int = 0
    task_id: str = ""
    drive_type: str = ""
    account: str = ""
    base_path: str = ""
    status: Literal["pending", "running", "pausing", "paused", "done", "failed", "cancelled"] = "pending"
    total_items: int = 0
    done_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    total_bytes: int = 0
    done_bytes: int = 0
    current_item_id: int = 0
    last_error: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None


class DL302CASTaskItemOut(BaseModel):
    id: int = 0
    task_id: str = ""
    file_id: str = ""
    file_path: str = ""
    name: str = ""
    size: int = 0
    status: Literal["pending", "running", "done", "failed", "skipped", "cancelled"] = "pending"
    stage: str = ""
    stage_done: int = 0
    stage_total: int = 0
    retry_count: int = 0
    last_error: str = ""
    rapid_drive_types: str = ""


class DL302CASTaskListOut(BaseModel):
    tasks: list[DL302CASTaskOut] = Field(default_factory=list)


class DL302SupportedAccountOut(BaseModel):
    account_id: int
    account_name: str
    drive_type: str
    drive_name: str
    enabled: bool = False
    is_default: bool = False
    runtime_status: str | None = None
    nickname: str | None = None
    username: str | None = None
    has_302_path: bool = False
    media_base_path: str | None = None
    cache_base_path: str | None = None
    strm_scan_base_path: str | None = None
    cas_task: DL302CASTaskOut | None = None


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
    auto_balance: bool = False
    copy_download_mode: Literal["0", "1"] = "0"
    strm_enabled: bool = False
    strm_mode: Literal["auto", "independent"] = "auto"
    strm_root_dir: str = "/strm"
    strm_prefix_url: str | None = None
    strm_include_cas_root_dir: bool = False
    strm_source_priority: Literal["video_first", "cas_first"] = "video_first"
    cas_root_dir: str | None = None
    cas_workers: int = 4
    strm_summary: DL302StrmSummaryOut = Field(default_factory=DL302StrmSummaryOut)


class DL302ConfigUpdateIn(BaseModel):
    proxy_url: str | None = Field(default=None)
    proxy_path_offset: int | None = Field(default=None)
    intranet_cidrs: list[str] | None = Field(default=None)
    auto_balance: bool | None = Field(default=None)
    copy_download_mode: Literal["0", "1"] | None = Field(default=None)
    strm_enabled: bool | None = Field(default=None)
    strm_mode: Literal["auto", "independent"] | None = Field(default=None)
    strm_root_dir: str | None = Field(default=None)
    strm_prefix_url: str | None = Field(default=None)
    strm_include_cas_root_dir: bool | None = Field(default=None)
    strm_source_priority: Literal["video_first", "cas_first"] | None = Field(default=None)
    cas_root_dir: str | None = Field(default=None)
    cas_workers: int | None = Field(default=None)


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


class DL302CasGenerateIn(BaseModel):
    fast_compute: bool = Field(default=False)



class DL302CasGenerateOut(BaseModel):
    ok: bool = True
    task: DL302CASTaskOut
