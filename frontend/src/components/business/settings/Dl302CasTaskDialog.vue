<script setup lang="ts">
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { X, RefreshCw } from 'lucide-vue-next'
import {
  fetchDL302CasTasks,
  fetchDL302CasTask,
  fetchDL302CasTaskItems,
} from '@/api/dl302'
import { useToast } from '@/composables/useToast'
import { extractErrorMessage } from '@/lib/driveAuth'
import { formatBytes } from '@/lib/capacity'
import {
  casStatusText,
  casStatusClass,
  itemStatusLabel,
  itemStatusClass,
  taskProcessedItems,
  itemPercent,
  formatStageProgress,
  isTaskActive,
  taskOptionLabel,
} from '@/lib/dl302'
import type { DL302CASTask, DL302CASTaskItem } from '@/types/dl302'

interface Props {
  open: boolean
  accountId: number
  accountName?: string
}

const props = withDefaults(defineProps<Props>(), { accountName: '' })
const emit = defineEmits<{ close: [] }>()

const { toast } = useToast()

const tasks = ref<DL302CASTask[]>([])
const selectedTaskId = ref('')
const itemsMap = reactive<Record<string, DL302CASTaskItem[]>>({})
const loadingTasks = ref(false)
const loadingItems = ref(false)

const search = ref('')
const status = ref('all')
const page = ref(1)
const pageSize = ref(10)

let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollInFlight = false
let pollDelayMs = 3000
let pollSession = 0

const selectedTask = computed(() => tasks.value.find((t) => t.task_id === selectedTaskId.value) || null)

const filteredItems = computed(() => {
  const taskId = selectedTask.value?.task_id || ''
  const keyword = search.value.trim().toLowerCase()
  const st = status.value
  return (itemsMap[taskId] || []).filter((item) => {
    if (st !== 'all' && item.status !== st) return false
    if (!keyword) return true
    return [item.name, item.file_path, item.stage, item.last_error, item.rapid_drive_types]
      .map((v) => String(v || '').toLowerCase())
      .some((v) => v.includes(keyword))
  })
})

const pageCount = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / Math.max(1, pageSize.value))))
const currentPage = computed(() => Math.min(Math.max(1, page.value), pageCount.value))
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredItems.value.slice(start, start + pageSize.value)
})

watch([() => filteredItems.value.length, pageSize], () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

function nextPollDelay(elapsedMs: number, failed: boolean) {
  if (failed) return 8000
  if (elapsedMs > 2500) return 8000
  if (elapsedMs > 1500) return 5000
  if (elapsedMs > 800) return 5000
  return 3000
}

function clearPollTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function stopPoll() {
  pollSession += 1
  clearPollTimer()
  pollInFlight = false
  pollDelayMs = 3000
}

function startPoll() {
  const task = selectedTask.value
  if (!task?.task_id || !isTaskActive(task.status)) {
    stopPoll()
    return
  }
  pollSession += 1
  pollDelayMs = 3000
  scheduleNextPoll(0, pollSession)
}

function scheduleNextPoll(delayMs: number, session = pollSession) {
  clearPollTimer()
  if (session !== pollSession) return
  pollTimer = window.setTimeout(async () => {
    if (session !== pollSession) return
    if (pollInFlight) {
      scheduleNextPoll(Math.max(pollDelayMs, 5000), session)
      return
    }

    pollInFlight = true
    const startedAt = Date.now()
    let failed = false
    let shouldContinue = false

    try {
      shouldContinue = await pollSelectedOnce(session)
    } catch {
      failed = true
      shouldContinue = true
    } finally {
      pollInFlight = false
      if (session !== pollSession) return
      if (!shouldContinue) {
        stopPoll()
        return
      }
      pollDelayMs = nextPollDelay(Date.now() - startedAt, failed)
      scheduleNextPoll(pollDelayMs, session)
    }
  }, delayMs)
}

async function pollSelectedOnce(session: number) {
  const task = selectedTask.value
  if (!task?.task_id || !isTaskActive(task.status)) {
    return false
  }
  const taskId = task.task_id
  const latest = await fetchDL302CasTask(taskId)
  if (session !== pollSession || selectedTaskId.value !== taskId) return false

  tasks.value = tasks.value.map((t) => (t.task_id === latest.task_id ? latest : t))
  if (!isTaskActive(latest.status)) return false

  const items = await fetchDL302CasTaskItems(taskId)
  if (session !== pollSession || selectedTaskId.value !== taskId) return false
  itemsMap[taskId] = items

  return isTaskActive(latest.status)
}

async function loadTaskItems(taskId: string) {
  if (!taskId) return
  loadingItems.value = true
  try {
    itemsMap[taskId] = await fetchDL302CasTaskItems(taskId)
  } catch (e) {
    toast.error(extractErrorMessage(e, '加载明细失败'))
  } finally {
    loadingItems.value = false
  }
}

async function loadTasks() {
  if (!props.accountId) return
  stopPoll()
  loadingTasks.value = true
  try {
    const result = await fetchDL302CasTasks(props.accountId)
    tasks.value = result.tasks || []
    if ((!selectedTaskId.value || !tasks.value.some((t) => t.task_id === selectedTaskId.value)) && tasks.value.length) {
      selectedTaskId.value = tasks.value[0].task_id
    }
    if (selectedTaskId.value) await loadTaskItems(selectedTaskId.value)
    startPoll()
  } catch (e) {
    toast.error(extractErrorMessage(e, '加载任务失败'))
  } finally {
    loadingTasks.value = false
  }
}

async function handleSelectTask(taskId: string) {
  stopPoll()
  selectedTaskId.value = taskId
  page.value = 1
  await loadTaskItems(taskId)
  startPoll()
}

function handleClose() {
  stopPoll()
  emit('close')
}

watch(
  () => props.open,
  (visible) => {
    if (visible) {
      search.value = ''
      status.value = 'all'
      page.value = 1
      pageSize.value = 10
      selectedTaskId.value = ''
      tasks.value = []
      loadTasks()
    } else {
      stopPoll()
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopPoll)
</script>

<template>
  <Teleport to="body">
    <Transition name="cas-fade">
      <div v-if="open" class="fixed inset-0 z-[60] flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50" @click="handleClose" />
        <div class="relative z-10 flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
            <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">
              {{ accountName ? `${accountName} · CAS 任务管理` : 'CAS 任务管理' }}
            </h3>
            <button class="rounded-md p-1 transition-colors hover:bg-[hsl(var(--muted))]" @click="handleClose">
              <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            </button>
          </div>

          <!-- Toolbar -->
          <div class="flex flex-wrap items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-3">
            <select
              :value="selectedTaskId"
              class="h-9 w-56 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              @change="handleSelectTask(($event.target as HTMLSelectElement).value)"
            >
              <option v-if="!tasks.length" value="">暂无任务</option>
              <option v-for="task in tasks" :key="task.task_id" :value="task.task_id">{{ taskOptionLabel(task) }}</option>
            </select>
            <Input v-model="search" placeholder="搜索文件名 / 路径 / 阶段 / 错误" class="w-64" @update:model-value="page = 1" />
            <select
              v-model="status"
              class="h-9 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              @change="page = 1"
            >
              <option value="all">全部状态</option>
              <option value="pending">待处理</option>
              <option value="running">处理中</option>
              <option value="done">已完成</option>
              <option value="skipped">已跳过</option>
              <option value="failed">失败</option>
              <option value="cancelled">已取消</option>
            </select>
            <div class="flex-1" />
            <Button variant="outline" size="sm" :disabled="loadingTasks" @click="loadTasks">
              <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': loadingTasks }" />
              刷新任务
            </Button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-4">
            <template v-if="selectedTask">
              <!-- Task detail summary -->
              <div class="mb-4 rounded-lg border border-[hsl(var(--border))] p-3 text-xs text-[hsl(var(--muted-foreground))]">
                <div class="mb-2 flex items-center gap-2">
                  <span class="rounded-full px-2 py-0.5 text-[11px] font-medium" :class="casStatusClass(selectedTask.status)">
                    {{ casStatusText(selectedTask.status) }}
                  </span>
                  <span class="font-mono text-[hsl(var(--foreground))]">{{ selectedTask.task_id }}</span>
                </div>
                <div class="grid grid-cols-1 gap-1 sm:grid-cols-2">
                  <span>扫描目录：{{ selectedTask.base_path || '-' }}</span>
                  <span>已处理：{{ taskProcessedItems(selectedTask) }} / {{ selectedTask.total_items }}</span>
                  <span>字节进度：{{ formatBytes(selectedTask.done_bytes || 0) }} / {{ formatBytes(selectedTask.total_bytes || 0) }}</span>
                  <span>完成 {{ selectedTask.done_items || 0 }} · 跳过 {{ selectedTask.skipped_items || 0 }} · 失败 {{ selectedTask.failed_items || 0 }}</span>
                </div>
                <div v-if="selectedTask.last_error" class="mt-1 text-red-500">错误：{{ selectedTask.last_error }}</div>
              </div>

              <!-- Items meta -->
              <div class="mb-2 flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
                <span>共 {{ filteredItems.length }} 条 · 当前页 {{ pagedItems.length }} 条</span>
                <span v-if="loadingItems">加载中...</span>
              </div>

              <!-- Item list -->
              <div v-if="pagedItems.length" class="space-y-2">
                <div
                  v-for="item in pagedItems"
                  :key="item.id"
                  class="rounded-lg border border-[hsl(var(--border))] p-3"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="break-all text-sm font-medium text-[hsl(var(--foreground))]">{{ item.name || item.file_path }}</span>
                    <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium" :class="itemStatusClass(item.status)">
                      {{ itemStatusLabel(item.status) }}
                    </span>
                  </div>
                  <div class="mt-1 break-all text-xs text-[hsl(var(--muted-foreground))]">{{ item.file_path }}</div>
                  <div class="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                    <span>阶段：{{ item.stage || '-' }}</span>
                    <span>大小：{{ formatBytes(item.size) }}</span>
                    <span>进度：{{ formatStageProgress(item) }}</span>
                    <span v-if="item.rapid_drive_types">预热驱动：{{ item.rapid_drive_types }}</span>
                    <span v-if="item.retry_count">重试：{{ item.retry_count }}</span>
                  </div>
                  <div v-if="item.status === 'running' || item.stage_total > 0" class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                    <div class="h-full rounded-full bg-[hsl(var(--primary))] transition-all" :style="{ width: `${itemPercent(item)}%` }" />
                  </div>
                  <div v-if="item.last_error" class="mt-1 break-all text-xs text-red-500">错误：{{ item.last_error }}</div>
                </div>
              </div>
              <div v-else class="py-10 text-center text-sm text-[hsl(var(--muted-foreground))]">当前筛选条件下暂无明细</div>

              <!-- Pagination -->
              <div v-if="filteredItems.length" class="mt-3 flex items-center justify-end gap-2 text-sm">
                <select
                  v-model.number="pageSize"
                  class="h-8 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-xs text-[hsl(var(--foreground))] focus:outline-none"
                >
                  <option :value="10">10 / 页</option>
                  <option :value="20">20 / 页</option>
                  <option :value="50">50 / 页</option>
                  <option :value="100">100 / 页</option>
                </select>
                <Button variant="outline" size="sm" class="h-8 px-2" :disabled="currentPage <= 1" @click="page = currentPage - 1">上一页</Button>
                <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ currentPage }} / {{ pageCount }}</span>
                <Button variant="outline" size="sm" class="h-8 px-2" :disabled="currentPage >= pageCount" @click="page = currentPage + 1">下一页</Button>
              </div>
            </template>
            <div v-else class="py-16 text-center text-sm text-[hsl(var(--muted-foreground))]">该账号暂无 CAS 任务</div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cas-fade-enter-active,
.cas-fade-leave-active {
  transition: opacity 0.2s ease;
}
.cas-fade-enter-from,
.cas-fade-leave-to {
  opacity: 0;
}
</style>
