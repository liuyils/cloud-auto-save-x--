import { useQuery } from '@tanstack/vue-query'
import { fetchTasks, fetchTaskSchedulerSetting, fetchMagicRegex } from '@/api/tasks'

export function useTasksQuery() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => fetchTasks(),
  })
}

export function useTaskSchedulerSettingQuery() {
  return useQuery({
    queryKey: ['task-scheduler-setting'],
    queryFn: () => fetchTaskSchedulerSetting(),
  })
}

export function useMagicRegexQuery() {
  return useQuery({
    queryKey: ['magic-regex'],
    queryFn: () => fetchMagicRegex(),
  })
}
