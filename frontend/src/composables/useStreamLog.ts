import { ref, unref, type Ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

export interface StreamEvent {
  type: 'init' | 'stage' | 'log' | 'progress' | 'done' | 'error'
  message?: string
  stage?: string
  current?: number
  total?: number
  success?: boolean
}

export interface UseStreamLogOptions {
  url: Ref<string> | string
  method?: Ref<'GET' | 'POST'> | 'GET' | 'POST'
  body?: Ref<Record<string, any> | null> | Record<string, any> | null
  onMessage: (data: StreamEvent) => void
  onDone?: () => void
  onError?: (err: Error) => void
}

export function useStreamLog(options: UseStreamLogOptions) {
  const isConnected = ref(false)
  let abortController: AbortController | null = null

  function getToken(): string {
    try {
      const auth = useAuthStore()
      return auth.accessToken || ''
    } catch {
      return ''
    }
  }

  async function start() {
    if (isConnected.value) return

    const url = unref(options.url)
    if (!url) return

    abortController = new AbortController()
    isConnected.value = true

    try {
      const token = getToken()
      const method = unref(options.method) || 'GET'
      const bodyVal = unref(options.body)
      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
      }
      if (bodyVal) {
        headers['Content-Type'] = 'application/json'
      }
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }

      const response = await fetch(url, {
        method,
        headers,
        credentials: 'include',
        body: bodyVal ? JSON.stringify(bodyVal) : undefined,
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE format: "event: type\ndata: JSON\n\n"
        const lines = buffer.split('\n')
        buffer = ''
        let currentEvent = ''

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i]

          // If this is the last line and doesn't end with newline, it's incomplete
          if (i === lines.length - 1 && line !== '') {
            buffer = line
            break
          }

          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6).trim()
            if (jsonStr) {
              try {
                const payload = JSON.parse(jsonStr)
                // Merge event type from SSE event line into payload
                const event: StreamEvent = {
                  ...payload,
                  type: currentEvent || payload.type || 'log',
                  message: payload.message || payload.line || payload.stage || undefined,
                }
                options.onMessage(event)

                if (event.type === 'done') {
                  options.onDone?.()
                }
              } catch {
                // Non-JSON data line treated as plain text log
                options.onMessage({ type: (currentEvent || 'log') as StreamEvent['type'], message: jsonStr })
              }
            }
            currentEvent = '' // reset after data line
          } else if (line === '') {
            currentEvent = '' // empty line separates events
          }
        }
      }

      // Stream ended naturally
      if (isConnected.value) {
        isConnected.value = false
        options.onDone?.()
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        // Intentional abort, do nothing
      } else {
        options.onError?.(err instanceof Error ? err : new Error(String(err)))
      }
      isConnected.value = false
    }
  }

  function stop() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isConnected.value = false
  }

  return { start, stop, isConnected }
}
