export type DL302SupportedDriver = {
  code: string
  drive_name: string
  account_count: number
  enabled_count: number
  default_account_name?: string | null
}

export type DL302Config = {
  proxy_url?: string | null
  proxy_path_offset: number
  intranet_cidrs: string[]
  strm_enabled: boolean
  strm_mode: 'auto' | 'independent'
  strm_root_dir: string
  strm_prefix_url?: string | null
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
