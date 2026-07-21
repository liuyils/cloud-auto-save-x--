import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { upsertMagicRegexRule, deleteMagicRegexRule } from '@/api/magicRegex'
import { patchTMDBConfig } from '@/api/tmdb'
import { patchResourceSearchSource } from '@/api/resourceSearch'
import { patchOpenListConfig } from '@/api/openlist'
import { patchSaveRuleConfig } from '@/api/systemSettings'
import type { ResourceSearchSourceKey } from '@/types/resourceSearch'

export function useUpsertMagicRegexRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: Parameters<typeof upsertMagicRegexRule>[1] }) =>
      upsertMagicRegexRule(key, payload),
    // 以 ['magic-regex'] 前缀失效，同时刷新设置页规则列表与追剧任务的内置规则选择器（/tasks/magic-regex）
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['magic-regex'] }),
  })
}

export function useDeleteMagicRegexRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => deleteMagicRegexRule(key),
    // 以 ['magic-regex'] 前缀失效，同时刷新设置页规则列表与追剧任务的内置规则选择器（/tasks/magic-regex）
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['magic-regex'] }),
  })
}

export function usePatchTMDBConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof patchTMDBConfig>[0]) => patchTMDBConfig(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tmdb', 'config'] }),
  })
}

export function usePatchResourceSearchSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, payload }: { key: ResourceSearchSourceKey; payload: Parameters<typeof patchResourceSearchSource>[1] }) =>
      patchResourceSearchSource(key, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['resource-search', 'sources'] }),
  })
}

export function usePatchOpenListConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof patchOpenListConfig>[0]) => patchOpenListConfig(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['openlist', 'config'] }),
  })
}

export function usePatchSaveRuleConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof patchSaveRuleConfig>[0]) => patchSaveRuleConfig(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['system-settings', 'save-rules'] }),
  })
}
