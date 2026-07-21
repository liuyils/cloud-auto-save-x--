import { useQuery } from '@tanstack/vue-query'
import {
  fetchDriveAccounts,
  fetchDriveTypes,
  fetchDriveAccountProbeScheduler,
  fetchPlugins,
  fetchSyncPlugins,
} from '@/api/extensions'
import { fetchNotificationConfig } from '@/api/notifications'
import type { DriveAccountProbeScheduler } from '@/types/extensions'

export function useDriveAccountsQuery() {
  return useQuery({
    queryKey: ['drive-accounts'],
    queryFn: () => fetchDriveAccounts(),
  })
}

export function useDriveTypesQuery() {
  return useQuery({
    queryKey: ['drive-types'],
    queryFn: () => fetchDriveTypes(),
    staleTime: 5 * 60 * 1000,
  })
}

export function useDriveAccountProbeSchedulerQuery() {
  return useQuery({
    queryKey: ['drive-account-probe-scheduler'],
    queryFn: () => fetchDriveAccountProbeScheduler() as Promise<DriveAccountProbeScheduler>,
  })
}

export function usePluginsQuery() {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: () => fetchPlugins(),
  })
}

export function useSyncPluginsQuery() {
  return useQuery({
    queryKey: ['sync-plugins'],
    queryFn: () => fetchSyncPlugins(),
  })
}

export function useNotificationsQuery() {
  return useQuery({
    queryKey: ['notifications'],
    queryFn: () => fetchNotificationConfig(),
  })
}
