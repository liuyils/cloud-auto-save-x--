import { http } from '@/api/http'
import type { DL302CASTask, DL302CASTaskItem, DL302CASTaskListResult, DL302CasGenerateResult, DL302Config, DL302StrmGenerateResult, DL302SupportedDriver } from '@/types/dl302'

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
  auto_balance?: boolean | null
  cas_root_dir?: string | null
  copy_download_mode?: '0' | '1' | null
  strm_enabled?: boolean | null
  strm_mode?: 'auto' | 'independent' | null
  strm_root_dir?: string | null
  strm_prefix_url?: string | null
  strm_include_cas_root_dir?: boolean | null
  strm_source_priority?: 'video_first' | 'cas_first' | null
  cas_workers?: number | null
}) {
  const { data } = await http.patch<DL302Config>('/dl302/config', payload)
  return data
}

export async function generateDL302Strm(payload?: { mode?: 'auto' | 'independent'; persist_prefix_if_empty?: boolean }) {
  const { data } = await http.post<DL302StrmGenerateResult>('/dl302/strm/generate', payload || {})
  return data
}

export async function submitDL302CasTask(accountId: number, payload?: { fast_compute?: boolean }) {
  const { data } = await http.post<DL302CasGenerateResult>(`/dl302/cas/accounts/${accountId}/tasks`, payload || {})
  return data
}

export async function fetchDL302CasTasks(accountId: number) {
  const { data } = await http.get<DL302CASTaskListResult>(`/dl302/cas/accounts/${accountId}/tasks`)
  return data
}

export async function fetchDL302CasTask(taskId: string) {
  const { data } = await http.get<DL302CASTask>(`/dl302/cas/tasks/${taskId}`)
  return data
}

export async function fetchDL302CasTaskItems(taskId: string) {
  const { data } = await http.get<DL302CASTaskItem[]>(`/dl302/cas/tasks/${taskId}/items`)
  return data
}

export async function pauseDL302CasTask(taskId: string) {
  const { data } = await http.post<DL302CASTask>(`/dl302/cas/tasks/${taskId}/pause`)
  return data
}

export async function resumeDL302CasTask(taskId: string) {
  const { data } = await http.post<DL302CASTask>(`/dl302/cas/tasks/${taskId}/resume`)
  return data
}

export async function cancelDL302CasTask(taskId: string) {
  const { data } = await http.post<DL302CASTask>(`/dl302/cas/tasks/${taskId}/cancel`)
  return data
}
