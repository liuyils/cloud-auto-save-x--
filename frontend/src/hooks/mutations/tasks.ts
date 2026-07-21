import { useMutation, useQueryClient } from '@tanstack/vue-query'
import {
  createTask,
  updateTask,
  deleteTask,
  runTask,
  setTaskStatus,
  repairBannedDramaTasks,
  stopCompletedDramaTasks,
  syncDramaSavepathSnapshots,
  updateTaskSchedulerSetting,
  runAllDramaTasks,
} from '@/api/tasks'

export function useCreateTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useUpdateTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof updateTask>[1] }) =>
      updateTask(taskId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useDeleteTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useRunTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: runTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useSetTaskStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, enabled }: { taskId: number; enabled: boolean }) =>
      setTaskStatus(taskId, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useRepairBannedMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: repairBannedDramaTasks,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }) },
  })
}

export function useStopCompletedMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: stopCompletedDramaTasks,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }) },
  })
}

export function useSyncSnapshotsMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: syncDramaSavepathSnapshots,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }) },
  })
}

export function useUpdateSchedulerMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { crontab: string; timezone: string; enabled: boolean }) => updateTaskSchedulerSetting(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['task-scheduler-setting'] }) },
  })
}

export function useRunAllTasksMutation() {
  return useMutation({
    mutationFn: runAllDramaTasks,
  })
}
