import { useMutation, useQueryClient } from '@tanstack/vue-query'
import {
  createDriveAccount,
  updateDriveAccount,
  deleteDriveAccount,
  probeDriveAccount,
  setDriveAccountStatus,
  setDriveAccountDefault,
  refreshDriveAccountProfiles,
  refreshDriveAccountLsdirCache,
  patchDriveAccountProbeScheduler,
} from '@/api/extensions'

export function useCreateDriveAccountMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDriveAccount,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useUpdateDriveAccountMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ accountId, payload }: { accountId: number; payload: Parameters<typeof updateDriveAccount>[1] }) =>
      updateDriveAccount(accountId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useDeleteDriveAccountMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDriveAccount,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useProbeDriveAccountMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (accountId: number) => probeDriveAccount(accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useSetDriveAccountStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ accountId, enabled }: { accountId: number; enabled: boolean }) =>
      setDriveAccountStatus(accountId, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useSetDriveAccountDefaultMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (accountId: number) => setDriveAccountDefault(accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useRefreshDriveAccountProfilesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => refreshDriveAccountProfiles(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function useRefreshDriveAccountLsdirCacheMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ accountId, rescanStatic }: { accountId: number; rescanStatic: boolean }) =>
      refreshDriveAccountLsdirCache(accountId, { rescan_static: rescanStatic }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-accounts'] }),
  })
}

export function usePatchDriveAccountProbeSchedulerMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof patchDriveAccountProbeScheduler>[0]) =>
      patchDriveAccountProbeScheduler(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drive-account-probe-scheduler'] }),
  })
}
