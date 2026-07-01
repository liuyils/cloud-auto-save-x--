import { http } from '@/api/http'
import type { SaveRuleConfig } from '@/types/systemSettings'

export async function fetchSaveRuleConfig() {
  const { data } = await http.get<SaveRuleConfig>('/system-settings/save-rules')
  return data
}

export async function patchSaveRuleConfig(payload: { enable_skip_transferred_history?: boolean | null }) {
  const { data } = await http.patch<SaveRuleConfig>('/system-settings/save-rules', payload)
  return data
}
