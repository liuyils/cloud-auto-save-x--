export type NotificationConfig = {
  config: Record<string, any>
  default_config: Record<string, any>
  updated_at?: string | null
}

export type NotificationChannelResult = {
  channel: string
  ok: boolean
  error?: string | null
}

export type NotificationTestResult = {
  results: NotificationChannelResult[]
}

