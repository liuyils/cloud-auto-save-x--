<script setup lang="ts">
import { ref, reactive, watch, nextTick, onBeforeUnmount, computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { useStreamLog } from '@/composables/useStreamLog'
import { fetchSyncExecutionLatest, fetchSyncExecutionFiles, cancelSyncExecution } from '@/api/syncTasks'

interface Props {
  visible: boolean
  url: string
  title?: string
  method?: 'GET' | 'POST'
  taskId?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  title: '执行日志',
  method: 'POST',
  taskId: null,
})

const emit = defineEmits<{
  'update:visible': [val: boolean]
  done: []
}>()

// --- State ---
const status = ref<'idle' | 'connecting' | 'running' | 'done' | 'error'>('idle')
const stats = reactive({ total: 0, done: 0, copied: 0, deleted: 0, skipped: 0, failed: 0 })
const fileEventsMap = ref(new Map<string, { ts: string; action: string; status: string; path: string; size: number | null; message: string | null }>())
const rawLogs = ref<string[]>([])
const stage = ref('')
const resultMessage = ref('')
const activeTab = ref<'files' | 'logs'>('files')

const logContainerRef = ref<HTMLDivElement | null>(null)
const fileContainerRef = ref<HTMLDivElement | null>(null)

// --- SSE ---
const { start, stop, isConnected } = useStreamLog({
  url: computed(() => props.url),
  method: computed(() => props.method),
  onMessage(data: any) {
    const type = data.type || 'log'
    switch (type) {
      case 'init':
        status.value = 'running'
        // 记录当前执行ID，用于轮询时验证
        if (data.execution_id) {
          currentExecutionId = data.execution_id
          // 新执行开始，清空旧文件数据
          fileEventsMap.value.clear()
          fileEventsMap.value = new Map()
          stats.total = 0
          stats.done = 0
          stats.copied = 0
          stats.deleted = 0
          stats.skipped = 0
          stats.failed = 0
        }
        break
      case 'log':
        rawLogs.value.push(data.line || data.message || '')
        nextTick(() => scrollLogsToBottom())
        break
      case 'stage':
        stage.value = data.stage || ''
        break
      case 'progress':
        stats.total = data.total_files ?? stats.total
        stats.done = data.done_files ?? stats.done
        stats.copied = data.copied_files ?? stats.copied
        stats.deleted = data.deleted_files ?? stats.deleted
        stats.skipped = data.skipped_files ?? stats.skipped
        stats.failed = data.failed_files ?? stats.failed
        if (data.event && data.event.path) {
          const key = data.event.path
          const existing = fileEventsMap.value.get(key)
          const terminalStatuses = ['success', 'done', 'failed', 'skipped', 'aborted']
          // 如果文件已经是终态（来自轮询/数据库的权威数据），不允许 SSE 将其回退到非终态
          const incomingStatus = data.event.status || 'syncing'
          if (existing && terminalStatuses.includes(existing.status) && !terminalStatuses.includes(incomingStatus)) {
            // 跳过此次更新，保留终态
            break
          }
          const merged = {
            ...(existing || {}),
            ...data.event,
            size: data.event.size ?? existing?.size ?? null,
            message: data.event.message ?? existing?.message ?? null,
          }
          fileEventsMap.value.set(key, merged)
          fileEventsMap.value = new Map(fileEventsMap.value)
          nextTick(() => scrollFilesToBottom())
        }
        break
      case 'done':
        status.value = data.status === 'failed' ? 'error' : 'done'
        resultMessage.value = data.message || ''
        // 将所有仍为 syncing 的文件标记为完成（done了但文件没单独报错说明成功了）
        if (data.status !== 'failed') {
          for (const [key, ev] of fileEventsMap.value) {
            if (ev.status === 'syncing' || ev.status === 'SYNC') {
              fileEventsMap.value.set(key, { ...ev, status: 'success' })
            }
          }
          fileEventsMap.value = new Map(fileEventsMap.value)
        }
        break
      case 'error':
        status.value = 'error'
        resultMessage.value = data.message || '发生错误'
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
    rawLogs.value.push(`[ERROR] ${err.message}`)
  },
})

// --- Helpers ---
function scrollLogsToBottom() {
  const el = logContainerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function scrollFilesToBottom() {
  const el = fileContainerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function startConnection() {
  status.value = 'connecting'
  rawLogs.value = []
  fileEventsMap.value = new Map()
  stats.total = 0
  stats.done = 0
  stats.copied = 0
  stats.deleted = 0
  stats.skipped = 0
  stats.failed = 0
  stage.value = ''
  resultMessage.value = ''
  currentExecutionId = 0
  start()
}

function close() {
  emit('update:visible', false)
}

async function handleStop() {
  try {
    const match = props.url.match(/sync-tasks\/(\d+)/)
    if (match) {
      const taskId = Number(match[1])
      const exec = await fetchSyncExecutionLatest(taskId)
      if (exec && exec.status === 'running') {
        await cancelSyncExecution(taskId, exec.id)
      }
    }
  } catch {}
  stop()
  status.value = 'done'
  emit('done')
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)}GB`
}

function statusLabel(s: string): string {
  const map: Record<string, string> = { success: 'OK', syncing: 'SYNC', pending: 'PEND', skipped: 'SKIP', aborted: 'ABRT' }
  return map[s] || 'FAIL'
}

function statusColorClass(s: string): string {
  if (s === 'syncing' || s === 'pending') return 'text-blue-500 border-blue-300 bg-blue-50 dark:bg-blue-950/30'
  if (s === 'success') return 'text-emerald-500 border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30'
  if (s === 'skipped' || s === 'aborted') return 'text-gray-400 border-gray-300 bg-gray-50 dark:bg-gray-800/30'
  return 'text-red-500 border-red-300 bg-red-50 dark:bg-red-950/30'
}

// --- File table sort & pagination ---
const fileSortBy = ref<'ts' | 'status'>('ts')
const fileSortOrder = ref<'desc' | 'asc'>('desc')
const filePage = ref(1)
const filePageSize = ref(50)

const sortedFileEvents = computed(() => {
  const items = [...fileEventsMap.value.values()]
  if (fileSortBy.value === 'ts') {
    items.sort((a, b) => fileSortOrder.value === 'desc'
      ? (b.ts || '').localeCompare(a.ts || '')
      : (a.ts || '').localeCompare(b.ts || ''))
  } else if (fileSortBy.value === 'status') {
    const order: Record<string, number> = { success: 0, failed: 1, syncing: 2, pending: 3, skipped: 4, aborted: 5 }
    items.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9))
  }
  return items
})

const fileTotalPages = computed(() => Math.max(1, Math.ceil(sortedFileEvents.value.length / filePageSize.value)))
const filePageItems = computed(() => {
  const start = (filePage.value - 1) * filePageSize.value
  return sortedFileEvents.value.slice(start, start + filePageSize.value)
})

function toggleSort(col: 'ts' | 'status') {
  if (fileSortBy.value === col) {
    fileSortOrder.value = fileSortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    fileSortBy.value = col
    fileSortOrder.value = 'desc'
  }
  filePage.value = 1
}

const progressPercent = computed(() => {
  if (stats.total === 0) return 0
  return Math.round((stats.done / stats.total) * 100)
})

const statusBadgeLabel = computed(() => {
  switch (status.value) {
    case 'idle': return '等待中'
    case 'connecting': return '连接中'
    case 'running': return stage.value === 'aborting' ? '停止中' : stage.value === 'finalizing' ? '收尾中' : '执行中'
    case 'done': return '已完成'
    case 'error': return '失败'
    default: return ''
  }
})

const statusBadgeClass = computed(() => {
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

// --- Polling Logic (REST API for file details) ---
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollInFlight = false
let pollDelayMs = 3000
let currentExecutionId = 0

function resolveTaskId(): number | null {
  if (props.taskId) return props.taskId
  const match = props.url.match(/sync-tasks\/(\d+)/)
  return match ? Number(match[1]) : null
}

function startPolling() {
  if (pollTimer) return
  scheduleNextPoll(0) // 立即执行第一次
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function scheduleNextPoll(delayMs: number) {
  stopPolling()
  pollTimer = setTimeout(async () => {
    if (pollInFlight) {
      // 上一次还没完成，延迟重试
      scheduleNextPoll(5000)
      return
    }
    pollInFlight = true
    const startTime = Date.now()

    try {
      await pollOnce()
    } finally {
      pollInFlight = false
      const elapsed = Date.now() - startTime

      // 自适应退避
      let nextDelay = 3000
      if (elapsed > 2500) nextDelay = 8000
      else if (elapsed > 1500) nextDelay = 5000
      else if (elapsed > 800) nextDelay = 5000
      else nextDelay = 3000

      pollDelayMs = nextDelay

      // 如果还在运行中，安排下一次
      if (status.value === 'running' || status.value === 'connecting') {
        scheduleNextPoll(pollDelayMs)
      }
    }
  }, delayMs)
}

async function pollOnce() {
  const taskId = resolveTaskId()
  if (!taskId) return
  try {
    const exe = await fetchSyncExecutionLatest(taskId, { max_log_chars: 0 })
    if (!exe) return

    const exeId = exe.id || 0

    // 如果 SSE 已经告知了当前 execution_id，只处理匹配的执行记录
    if (currentExecutionId > 0 && exeId > 0 && exeId !== currentExecutionId) {
      // latest 返回的不是当前正在运行的执行
      if (exeId > currentExecutionId) {
        // 是更新的执行（理论上不应发生），更新追踪
        currentExecutionId = exeId
      } else {
        // 是旧的已完成执行，忽略其文件数据
        return
      }
    }

    // 如果还没有 currentExecutionId（SSE 还没收到 init），谨慎处理
    if (currentExecutionId === 0 && exeId > 0) {
      if (exe.status === 'running') {
        // 确实是正在运行的执行，可以锁定
        currentExecutionId = exeId
      } else if (isConnected.value || status.value === 'connecting' || status.value === 'running') {
        // SSE 正在连接或已连接但还没收到 init，而 latest 返回的是已完成的旧执行
        // 新执行可能还没持久化到数据库，忽略此次轮询结果
        return
      } else {
        // 非实时模式（纯轮询查看历史），可以采用
        currentExecutionId = exeId
      }
    }

    // Update stats from backend
    const s = exe.stats || {}
    stats.total = s.total_files ?? stats.total
    const doneFiles = (s.copied_files ?? 0) + (s.deleted_files ?? 0) + (s.skipped_files ?? 0) + (s.failed_files ?? 0)
    stats.done = s.done_files ?? doneFiles
    stats.copied = s.copied_files ?? stats.copied
    stats.deleted = s.deleted_files ?? stats.deleted
    stats.skipped = s.skipped_files ?? stats.skipped
    stats.failed = s.failed_files ?? stats.failed

    // Fetch file details - 只有确认是当前执行时才拉取文件
    if (currentExecutionId > 0 && exeId === currentExecutionId) {
      const filesData = await fetchSyncExecutionFiles(taskId, currentExecutionId, { offset: 0, limit: 500 })
      if (filesData && Array.isArray(filesData.items)) {
        for (const f of filesData.items) {
          if (f.path) {
            fileEventsMap.value.set(f.path, {
              path: f.path,
              status: f.status || 'syncing',
              action: f.action || 'copy',
              size: f.size ?? null,
              message: f.message || null,
              ts: f.updated_at || '',
            })
          }
        }
        fileEventsMap.value = new Map(fileEventsMap.value)
      }
    }

    // Check if execution finished
    if (exe.status && exe.status !== 'running') {
      if (!isConnected.value) {
        // SSE 已断开，轮询是唯一数据源，可以设置终态
        stopPolling()
        if (status.value === 'running' || status.value === 'connecting') {
          status.value = exe.status === 'failed' ? 'error' : 'done'
          resultMessage.value = exe.message || ''
        }
      }
      // else: SSE 仍在连接中，让 SSE 的 done 事件来设置终态，轮询继续保持以同步文件明细
    }
  } catch (e) {
    console.warn('[SyncLogDialog] poll failed:', e)
  }
}

// --- Lifecycle ---
watch(
  () => props.visible,
  (val) => {
    if (val) {
      startConnection()
      startPolling()
      document.body.style.overflow = 'hidden'
    } else {
      stop()
      stopPolling()
      document.body.style.overflow = ''
    }
  },
)

onBeforeUnmount(() => {
  stop()
  stopPolling()
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sync-log-dialog">
      <div
        v-if="visible"
        class="fixed inset-0 z-[100] flex items-center justify-center"
      >
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/60" @click="close" />

        <!-- Panel -->
        <div class="relative z-10 flex h-[85vh] w-[92vw] max-w-5xl flex-col overflow-hidden rounded-lg bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
            <div class="flex items-center gap-3">
              <h2 class="text-base font-semibold text-[hsl(var(--card-foreground))]">
                {{ title }}
              </h2>
              <span
                class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                :class="statusBadgeClass"
              >
                {{ statusBadgeLabel }}
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

          <!-- Stats Cards -->
          <div class="grid grid-cols-4 gap-2 px-5 py-3">
            <div class="rounded-md bg-[hsl(var(--muted)/.5)] p-2 text-center">
              <div class="text-lg font-bold text-[hsl(var(--foreground))]">{{ stats.total }}</div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">总文件</div>
            </div>
            <div class="rounded-md bg-green-50 dark:bg-green-950/30 p-2 text-center">
              <div class="text-lg font-bold text-green-600">{{ stats.copied + stats.deleted }}</div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">已同步</div>
            </div>
            <div class="rounded-md bg-amber-50 dark:bg-amber-950/30 p-2 text-center">
              <div class="text-lg font-bold text-amber-600">{{ stats.skipped }}</div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">已跳过</div>
            </div>
            <div class="rounded-md bg-red-50 dark:bg-red-950/30 p-2 text-center">
              <div class="text-lg font-bold text-red-600">{{ stats.failed }}</div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">失败</div>
            </div>
          </div>

          <!-- Progress Bar -->
          <div class="flex items-center gap-3 px-5 pb-3">
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
              <div
                class="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-300"
                :style="{ width: `${progressPercent}%` }"
              />
            </div>
            <span class="text-xs text-[hsl(var(--muted-foreground))] whitespace-nowrap">
              {{ stats.done }}/{{ stats.total }} ({{ progressPercent }}%)
            </span>
          </div>

          <!-- Tabs -->
          <div class="flex items-center gap-0 border-b border-[hsl(var(--border))] px-5">
            <button
              class="relative px-4 py-2 text-sm font-medium transition-colors"
              :class="activeTab === 'files' ? 'text-[hsl(var(--foreground))]' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="activeTab = 'files'"
            >
              文件明细
              <span v-if="fileEventsMap.size" class="ml-1 text-[10px] opacity-60">({{ fileEventsMap.size }})</span>
              <span v-if="activeTab === 'files'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-[hsl(var(--primary))]" />
            </button>
            <button
              class="relative px-4 py-2 text-sm font-medium transition-colors"
              :class="activeTab === 'logs' ? 'text-[hsl(var(--foreground))]' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="activeTab = 'logs'"
            >
              原始日志
              <span v-if="rawLogs.length" class="ml-1 text-[10px] opacity-60">({{ rawLogs.length }})</span>
              <span v-if="activeTab === 'logs'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-[hsl(var(--primary))]" />
            </button>
          </div>

          <!-- Tab Content -->
          <div class="flex-1 overflow-hidden">
            <!-- Files Tab -->
            <div v-show="activeTab === 'files'" class="h-full flex flex-col">
              <!-- Table Header -->
              <div class="grid grid-cols-[70px_60px_1fr_80px_140px] gap-1 px-4 py-2 text-xs font-medium text-[hsl(var(--muted-foreground))] border-b border-[hsl(var(--border))]">
                <span class="cursor-pointer select-none" @click="toggleSort('status')">状态 {{ fileSortBy === 'status' ? (fileSortOrder === 'desc' ? '↓' : '↑') : '' }}</span>
                <span>动作</span>
                <span>路径</span>
                <span>大小</span>
                <span class="cursor-pointer select-none" @click="toggleSort('ts')">信息/时间 {{ fileSortBy === 'ts' ? (fileSortOrder === 'desc' ? '↓' : '↑') : '' }}</span>
              </div>
              <!-- Table Body -->
              <div ref="fileContainerRef" class="flex-1 overflow-y-auto">
                <div
                  v-if="fileEventsMap.size === 0"
                  class="flex h-full items-center justify-center text-sm text-[hsl(var(--muted-foreground))] opacity-60"
                >
                  {{ status === 'connecting' ? '正在连接...' : '暂无文件事件' }}
                </div>
                <div
                  v-for="(ev, idx) in filePageItems"
                  :key="ev.path || idx"
                  class="grid grid-cols-[70px_60px_1fr_80px_140px] gap-1 px-4 py-1.5 text-xs border-b border-[hsl(var(--border)/.5)] hover:bg-[hsl(var(--accent)/.3)]"
                >
                  <span class="inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold border" :class="statusColorClass(ev.status)">
                    {{ statusLabel(ev.status) }}
                  </span>
                  <Badge :variant="ev.action === 'delete' ? 'destructive' : 'secondary'" class="text-[10px] w-fit h-fit">
                    {{ ev.action }}
                  </Badge>
                  <span class="truncate text-[hsl(var(--foreground))]" :title="ev.path">{{ ev.path }}</span>
                  <span class="text-[hsl(var(--muted-foreground))]">{{ ev.size ? formatSize(ev.size) : '-' }}</span>
                  <span class="truncate text-[hsl(var(--muted-foreground))]" :title="ev.message || ev.ts || ''">{{ ev.message || ev.ts || '-' }}</span>
                </div>
              </div>
              <!-- Pagination -->
              <div v-if="sortedFileEvents.length > 0" class="flex items-center justify-between px-3 py-2 border-t border-[hsl(var(--border))] text-xs">
                <div class="text-[hsl(var(--muted-foreground))]">
                  {{ (filePage - 1) * filePageSize + 1 }}-{{ Math.min(filePage * filePageSize, sortedFileEvents.length) }} / 共 {{ sortedFileEvents.length }} 条
                </div>
                <div class="flex items-center gap-2">
                  <select v-model.number="filePageSize" @change="filePage = 1" class="rounded border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-1 py-0.5 text-xs text-[hsl(var(--foreground))]">
                    <option :value="50">50条/页</option>
                    <option :value="100">100条/页</option>
                    <option :value="200">200条/页</option>
                  </select>
                  <button :disabled="filePage <= 1" @click="filePage--" class="px-1.5 disabled:opacity-30">◀</button>
                  <span>{{ filePage }} / {{ fileTotalPages }}</span>
                  <button :disabled="filePage >= fileTotalPages" @click="filePage++" class="px-1.5 disabled:opacity-30">▶</button>
                </div>
              </div>
            </div>

            <!-- Logs Tab -->
            <div v-show="activeTab === 'logs'" class="h-full flex flex-col">
              <div
                ref="logContainerRef"
                class="flex-1 overflow-y-auto bg-[hsl(var(--foreground))] p-4 font-mono text-sm leading-6 text-[hsl(var(--background))]"
              >
                <div
                  v-if="rawLogs.length === 0"
                  class="flex h-full items-center justify-center opacity-50"
                >
                  {{ status === 'connecting' ? '正在连接...' : '暂无日志' }}
                </div>
                <div
                  v-for="(line, idx) in rawLogs"
                  :key="idx"
                  class="whitespace-pre-wrap break-all"
                  :class="{
                    'text-red-400': line.startsWith('[ERROR]'),
                    'text-emerald-400': line.startsWith('[DONE]') || line.startsWith('[SUCCESS]'),
                    'text-sky-400': line.startsWith('[STAGE]'),
                  }"
                >{{ line }}</div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-3">
            <div class="text-xs text-[hsl(var(--muted-foreground))]">
              <template v-if="resultMessage">{{ resultMessage }}</template>
              <template v-else-if="stage">阶段: {{ stage }}</template>
            </div>
            <button
              v-if="status === 'running'"
              class="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--destructive))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--destructive-foreground))] transition-colors hover:bg-[hsl(var(--destructive))]/90"
              @click="handleStop"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              停止执行
            </button>
            <button
              v-else
              class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]"
              @click="close"
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sync-log-dialog-enter-active,
.sync-log-dialog-leave-active {
  transition: opacity 0.2s ease;
}
.sync-log-dialog-enter-active > div:last-child,
.sync-log-dialog-leave-active > div:last-child {
  transition: transform 0.2s ease;
}
.sync-log-dialog-enter-from,
.sync-log-dialog-leave-to {
  opacity: 0;
}
.sync-log-dialog-enter-from > div:last-child,
.sync-log-dialog-leave-to > div:last-child {
  transform: scale(0.95);
}
</style>
