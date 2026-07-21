import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { updateNotificationConfig, sendNotificationTest } from '@/api/notifications'

export function useUpdateNotificationConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: Record<string, any>) => updateNotificationConfig({ config }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  })
}

export function useTestNotificationMutation() {
  return useMutation({
    mutationFn: (payload: { title: string; content: string; channels?: string[] }) =>
      sendNotificationTest(payload),
  })
}
