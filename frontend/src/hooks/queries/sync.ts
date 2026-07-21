import { useQuery } from '@tanstack/vue-query'
import { fetchSyncTasks, fetchSyncExecutions } from '@/api/syncTasks'

export function useSyncTasksQuery() {
  return useQuery({
    queryKey: ['sync-tasks'],
    queryFn: () => fetchSyncTasks(),
  })
}

export function useSyncExecutionsQuery(syncTaskId: number) {
  return useQuery({
    queryKey: ['sync-tasks', syncTaskId, 'executions'],
    queryFn: () => fetchSyncExecutions(syncTaskId),
    enabled: syncTaskId > 0,
  })
}
