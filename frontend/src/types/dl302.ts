export type DL302CASTask = {
  id: number
  task_id: string
  drive_type: string
  account: string
  base_path: string
  status: 'pending' | 'running' | 'pausing' | 'paused' | 'done' | 'failed' | 'cancelled'
  total_items: number
  done_items: number
  failed_items: number
  skipped_items: number
  total_bytes: number
  done_bytes: number
  current_item_id: number
  last_error: string
  created_at?: string | null
  updated_at?: string | null
  finished_at?: string | null
}

export type DL302CASTaskItem = {
  id: number
  task_id: string
  file_id: string
  file_path: string
  name: string
  size: number
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'cancelled'
  stage: string
  stage_done: number
  stage_total: number
  retry_count: number
  last_error: string
  rapid_drive_types: string
}

export type DL302SupportedAccount = {
  account_id: number
  account_name: string
  drive_type: string
  drive_name: string
  enabled: boolean
  is_default: boolean
  runtime_status?: string | null
  nickname?: string | null
  username?: string | null
  has_302_path: boolean
  media_base_path?: string | null
  cas_task?: DL302CASTask | null
}

export type DL302SupportedDriver = {
  code: string
  drive_name: string
  account_count: number
  enabled_count: number
  default_account_name?: string | null
  accounts: DL302SupportedAccount[]
}

export type DL302Config = {
  proxy_url?: string | null
  proxy_path_offset: number
  intranet_cidrs: string[]
  auto_balance: boolean
  cas_root_dir: string
  copy_download_mode: '0' | '1'
  strm_enabled: boolean
  strm_mode: 'auto' | 'independent'
  strm_root_dir: string
  strm_prefix_url?: string | null
  strm_include_cas_root_dir: boolean
  strm_source_priority: 'video_first' | 'cas_first'
  strm_summary: {
    enabled: boolean
    mode: 'auto' | 'independent'
    prefix_ready: boolean
    root_exists: boolean
    source_account_count: number
    path_ready_account_count: number
    path_missing_account_count: number
    generated_file_count: number
    generated_dir_count: number
  }
}

export type DL302StrmGenerateResult = {
  ok: boolean
  mode: 'auto' | 'independent'
  strm_root_dir: string
  generated_files: number
  generated_dirs: number
  skipped_accounts: number
  message: string
}

export type DL302CasGenerateResult = {
  ok: boolean
  task: DL302CASTask
  message: string
}

export type DL302CASTaskListResult = {
  tasks: DL302CASTask[]
}
