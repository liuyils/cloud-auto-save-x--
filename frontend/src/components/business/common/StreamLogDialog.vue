<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount, computed } from 'vue'
import { useStreamLog, type StreamEvent } from '@/composables/useStreamLog'

interface Props {
  visible: boolean
  title?: string
  url: string
  autoStart?: boolean
  method?: 'GET' | 'POST'
  body?: Record<string, any> | null
}

const props = withDefaults(defineProps<Props>(), {
  title: '执行日志',
  autoStart: true,
  method: 'GET',
  body: null,
})

const emit = defineEmits<{
  'update:visible': [value: boolean]
  done: []
}>()

type Status = 'idle' | 'connecting' | 'running' | 'done' | 'error'

interface LogLine {
  time: string
  type: StreamEvent['type']
  message: string
}

const status = ref<Status>('idle')
const logs = ref<LogLine[]>([])
const progress = ref<{ current: number; total: number } | null>(null)
const logContainerRef = ref<HTMLDivElement | null>(null)

function formatTime(): string {
  const now = new Date()
  return now.toLocaleTimeString('zh-CN', { hour12: false })
}

function addLog(type: StreamEvent['type'], message: string) {
  logs.value.push({ time: formatTime(), type, message })
  nextTick(() => scrollToBottom())
}

function scrollToBottom() {
  const container = logContainerRef.value
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

const { start, stop } = useStreamLog({
  url: computed(() => props.url),
  method: computed(() => props.method),
  body: computed(() => props.body),
  onMessage(data: StreamEvent) {
    switch (data.type) {
      case 'init':
        status.value = 'running'
        addLog('init', data.message || '初始化...')
        break
      case 'stage':
        addLog('stage', data.message || `阶段: ${data.stage}`)
        break
      case 'log':
        addLog('log', data.message || (data as any).line || '')
        break
      case 'progress':
        if (data.current !== undefined && data.total !== undefined) {
          progress.value = { current: data.current, total: data.total }
        }
        break
      case 'done':
        status.value = 'done'
        addLog('done', data.message || '执行完成')
        break
      case 'error':
        status.value = 'error'
        addLog('error', data.message || '发生错误')
        break
    }
  },
  onDone() {
    if (status.value !== 'error') {
      status.value = 'done'
    }
    emit('done')
  },
  onError(err: Error) {
    status.value = 'error'
    addLog('error', `连接错误: ${err.message}`)
  },
})

function startConnection() {
  status.value = 'connecting'
  logs.value = []
  progress.value = null
  start()
}

function close() {
  emit('update:visible', false)
}

function handleCopy() {
  const text = logs.value.map((l) => `[${l.time}] ${l.message}`).join('\n')
  navigator.clipboard.writeText(text)
}

function handleClear() {
  logs.value = []
  progress.value = null
}

// Watch visible to auto start/stop
watch(
  () => props.visible,
  (val) => {
    if (val) {
      if (props.autoStart) {
        startConnection()
      }
      document.body.style.overflow = 'hidden'
    } else {
      stop()
      document.body.style.overflow = ''
    }
  },
)

onBeforeUnmount(() => {
  stop()
  document.body.style.overflow = ''
})

const statusLabel = computed(() => {
  switch (status.value) {
    case 'idle':
      return '等待中'
    case 'connecting':
      return '连接中'
    case 'running':
      return '执行中'
    case 'done':
      return '已完成'
    case 'error':
      return '失败'
    default:
      return ''
  }
})

const statusClass = computed(() => {
  switch (status.value) {
    case 'connecting':
    case 'running':
      return 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
    case 'done':
      return 'bg-emerald-500 text-white'
    case 'error':
      return 'bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))]'
    default:
      return 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
  }
})

const progressPercent = computed(() => {
  if (!progress.value || progress.value.total === 0) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="stream-log-dialog">
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-center justify-center"
      >
        <!-- Overlay -->
        <div
          class="absolute inset-0 bg-black/60"
          @click="close"
        />
        <!-- Panel -->
        <div
          class="relative z-10 flex h-[85vh] w-[90vw] max-w-5xl flex-col overflow-hidden rounded-lg bg-[hsl(var(--card))] shadow-2xl"
        >
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
            <div class="flex items-center gap-3">
              <h2 class="text-base font-semibold text-[hsl(var(--card-foreground))]">
                {{ title }}
              </h2>
              <span
                class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                :class="statusClass"
              >
                {{ statusLabel }}
              </span>
            </div>
            <button
              class="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
              @click="close"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <!-- Log Content -->
          <div
            ref="logContainerRef"
            class="flex-1 overflow-y-auto bg-[hsl(var(--foreground))] p-4 font-mono text-sm leading-6 text-[hsl(var(--background))]"
          >
            <div
              v-if="logs.length === 0"
              class="flex h-full items-center justify-center opacity-50"
            >
              {{ status === 'connecting' ? '正在连接...' : '暂无日志' }}
            </div>
            <div
              v-for="(line, idx) in logs"
              :key="idx"
              class="whitespace-pre-wrap break-all"
              :class="{
                'text-sky-400': line.type === 'stage',
                'text-red-400': line.type === 'error',
                'text-emerald-400': line.type === 'done',
                'text-zinc-400': line.type === 'init',
              }"
            >
              <span class="mr-2 opacity-60">{{ line.time }}</span>
              <span>{{ line.message }}</span>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-3">
            <!-- Progress -->
            <div class="flex flex-1 items-center gap-3">
              <template v-if="progress">
                <div class="h-2 flex-1 max-w-xs overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                  <div
                    class="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-300"
                    :style="{ width: `${progressPercent}%` }"
                  />
                </div>
                <span class="text-xs text-[hsl(var(--muted-foreground))]">
                  {{ progress.current }}/{{ progress.total }}
                </span>
              </template>
            </div>
            <!-- Actions -->
            <div class="flex items-center gap-2">
              <button
                class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
                @click="handleClear"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                </svg>
                清空
              </button>
              <button
                class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
                @click="handleCopy"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                复制
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.stream-log-dialog-enter-active,
.stream-log-dialog-leave-active {
  transition: opacity 0.2s ease;
}
.stream-log-dialog-enter-active > div:last-child,
.stream-log-dialog-leave-active > div:last-child {
  transition: transform 0.2s ease;
}
.stream-log-dialog-enter-from,
.stream-log-dialog-leave-to {
  opacity: 0;
}
.stream-log-dialog-enter-from > div:last-child,
.stream-log-dialog-leave-to > div:last-child {
  transform: scale(0.95);
}
</style>
