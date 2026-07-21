import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { createSyncTask, updateSyncTask, deleteSyncTask, runSyncTask, cancelSyncExecution } from '@/api/syncTasks'

export function useCreateSyncTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createSyncTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sync-tasks'] }),
  })
}

export function useUpdateSyncTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ syncTaskId, payload }: { syncTaskId: number; payload: Parameters<typeof updateSyncTask>[1] }) =>
      updateSyncTask(syncTaskId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sync-tasks'] }),
  })
}

export function useDeleteSyncTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSyncTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sync-tasks'] }),
  })
}

export function useRunSyncTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ syncTaskId, payload }: { syncTaskId: number; payload?: { strategy?: Record<string, any> } | null }) =>
      runSyncTask(syncTaskId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sync-tasks'] }),
  })
}

export function useCancelSyncExecutionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ syncTaskId, executionId, payload }: { syncTaskId: number; executionId: number; payload?: { message?: string | null } | null }) =>
      cancelSyncExecution(syncTaskId, executionId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sync-tasks'] }),
  })
}
