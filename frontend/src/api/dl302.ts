import { http } from '@/api/http'
import type { DL302Config, DL302StrmGenerateResult, DL302SupportedDriver } from '@/types/dl302'

export async function fetchDL302SupportedDrivers() {
  const { data } = await http.get<DL302SupportedDriver[]>('/dl302/drivers')
  return data
}

export async function fetchDL302Config() {
  const { data } = await http.get<DL302Config>('/dl302/config')
  return data
}

export async function patchDL302Config(payload: {
  proxy_url?: string | null
  proxy_path_offset?: number | null
  intranet_cidrs?: string[] | null
  strm_enabled?: boolean | null
  strm_mode?: 'auto' | 'independent' | null
  strm_root_dir?: string | null
  strm_prefix_url?: string | null
}) {
  const { data } = await http.patch<DL302Config>('/dl302/config', payload)
  return data
}

export async function generateDL302Strm(payload?: { mode?: 'auto' | 'independent'; persist_prefix_if_empty?: boolean }) {
  const { data } = await http.post<DL302StrmGenerateResult>('/dl302/strm/generate', payload || {})
  return data
}
