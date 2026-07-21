<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Plus, FileCheck } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useSyncTasksQuery } from '@/hooks/queries/sync'
import { useDeleteSyncTaskMutation, useUpdateSyncTaskMutation, useCancelSyncExecutionMutation } from '@/hooks/mutations/sync'
import { fetchSyncExecutions, fetchSyncExecutionLatest } from '@/api/syncTasks'
import type { SyncTaskItem } from '@/types/syncTasks'
import SyncTaskCard from '@/components/business/sync/SyncTaskCard.vue'
import CreateSyncSheet from '@/components/business/sync/CreateSyncSheet.vue'
import SyncLogDialog from '@/components/business/sync/SyncLogDialog.vue'

const { toast } = useToast()
const { data: tasks, isLoading, refetch: refetchTasks } = useSyncTasksQuery()
const deleteMutation = useDeleteSyncTaskMutation()
const updateMutation = useUpdateSyncTaskMutation()
const cancelMutation = useCancelSyncExecutionMutation()

const selectedTaskId = ref<number | null>(null)
const sheetOpen = ref(false)
const editingTask = ref<SyncTaskItem | null>(null)

// Stream log dialog state
const streamLogVisible = ref(false)
const streamLogUrl = ref('')
const streamLogTitle = ref('执行日志')
const streamLogMethod = ref<'GET' | 'POST'>('POST')
const streamLogTaskId = ref<number | null>(null)

// Delete confirm dialog
const deleteDialogOpen = ref(false)
const taskToDelete = ref<SyncTaskItem | null>(null)

// Track running tasks (by checking latest execution status)
const runningTaskIds = ref<Set<number>>(new Set())

// Sync runningTaskIds from backend is_running field on data load
watch(
  () => tasks.value,
  (taskList) => {
    if (!taskList) return
    const next = new Set<number>(runningTaskIds.value)
    for (const t of taskList) {
      if (t.is_running) {
        next.add(t.id)
      } else if (!streamLogVisible.value || !streamLogUrl.value.includes(`/${t.id}/`)) {
        // Only remove if we're not currently streaming this task's log
        next.delete(t.id)
      }
    }
    runningTaskIds.value = next
  },
  { immediate: true },
)

const selectedTask = computed(() =>
  tasks.value?.find((t) => t.id === selectedTaskId.value) ?? null,
)

const taskCount = computed(() => tasks.value?.length ?? 0)
const runningCount = computed(() => (tasks.value ?? []).filter((t) => t.is_running || runningTaskIds.value.has(t.id)).length)
const enabledCount = computed(() => (tasks.value ?? []).filter((t) => t.enabled).length)

// Executions for selected task
const { data: executions, isLoading: execLoading } = useQuery({
  queryKey: computed(() => ['sync-tasks', selectedTaskId.value, 'executions']),
  queryFn: () => fetchSyncExecutions(selectedTaskId.value!),
  enabled: computed(() => selectedTaskId.value != null && selectedTaskId.value > 0),
})

function handleSelect(task: SyncTaskItem) {
  selectedTaskId.value = selectedTaskId.value === task.id ? null : task.id
}

function handleRun(task: SyncTaskItem) {
  // Open stream log dialog for live execution
  streamLogTitle.value = `执行日志 — ${task.name}`
  streamLogUrl.value = `/api/sync-tasks/${task.id}/run/stream`
  streamLogMethod.value = 'POST'
  streamLogTaskId.value = task.id
  streamLogVisible.value = true
  runningTaskIds.value.add(task.id)
}

function handleViewLog(task: SyncTaskItem) {
  // Open stream log dialog to tail the running execution's log (GET)
  streamLogTitle.value = `执行日志 — ${task.name}`
  streamLogUrl.value = `/api/sync-tasks/${task.id}/log/stream`
  streamLogMethod.value = 'GET'
  streamLogTaskId.value = task.id
  streamLogVisible.value = true
}

function handleStop(task: SyncTaskItem) {
  // Get latest execution to cancel
  fetchSyncExecutionLatest(task.id).then((exec) => {
    if (exec && exec.status === 'running') {
      cancelMutation.mutate(
        { syncTaskId: task.id, executionId: exec.id },
        {
          onSuccess: () => {
            toast.success('已请求停止')
            runningTaskIds.value.delete(task.id)
          },
          onError: (err: any) => {
            toast.error('停止失败', { description: err?.message || '' })
          },
        },
      )
    } else {
      toast.info('当前无运行中的执行')
      runningTaskIds.value.delete(task.id)
    }
  })
}

function handleEdit(task: SyncTaskItem) {
  editingTask.value = task
  sheetOpen.value = true
}

function handleToggle(task: SyncTaskItem) {
  updateMutation.mutate(
    { syncTaskId: task.id, payload: { enabled: !task.enabled } },
    {
      onSuccess: () => {
        toast.success(task.enabled ? '已禁用' : '已启用')
      },
    },
  )
}

function handleDeleteRequest(task: SyncTaskItem) {
  taskToDelete.value = task
  deleteDialogOpen.value = true
}

function handleDeleteConfirm() {
  if (!taskToDelete.value) return
  const task = taskToDelete.value
  deleteMutation.mutate(task.id, {
    onSuccess: () => {
      toast.success(`已删除「${task.name}」`)
      if (selectedTaskId.value === task.id) selectedTaskId.value = null
    },
    onError: (err: any) => {
      toast.error('删除失败', { description: err?.message || '' })
    },
  })
  deleteDialogOpen.value = false
  taskToDelete.value = null
}

function handleSheetClose() {
  sheetOpen.value = false
  editingTask.value = null
}

function handleStreamLogDone() {
  // Refresh running state when stream ends
  runningTaskIds.value.clear()
  refetchTasks()
}

function openCreateSheet() {
  editingTask.value = null
  sheetOpen.value = true
}

function formatDuration(start: string, end?: string | null): string {
  if (!end) return '进行中'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  const secs = Math.floor(ms / 1000)
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function formatTime(t: string): string {
  return new Date(t).toLocaleString('zh-CN')
}

function execStatusLabel(status: string): string {
  const map: Record<string, string> = {
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] ?? status
}

function execStatusClass(status: string): string {
  if (status === 'success') return 'text-[hsl(var(--chart-2))]'
  if (status === 'failed') return 'text-[hsl(var(--destructive))]'
  if (status === 'running') return 'text-[hsl(var(--chart-1))]'
  return 'text-[hsl(var(--muted-foreground))]'
}
</script>

<template>
  <div class="p-6 space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-[hsl(var(--foreground))]">🔄 同步任务</h1>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">本地与网盘之间的文件同步编排</p>
      </div>
      <Button @click="openCreateSheet">
        <Plus class="mr-1.5 h-4 w-4" />
        新建同步任务
      </Button>
    </div>

    <!-- Stat tiles -->
    <div class="grid grid-cols-3 gap-3">
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">📁</span>
          <span class="glass-tile__label">任务总数</span>
        </div>
        <div class="glass-tile__value">{{ taskCount }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">⚡</span>
          <span class="glass-tile__label">运行中</span>
        </div>
        <div class="glass-tile__value">{{ runningCount }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">✅</span>
          <span class="glass-tile__label">已启用</span>
        </div>
        <div class="glass-tile__value">{{ enabledCount }}</div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Skeleton v-for="i in 4" :key="i" class="h-[180px] rounded-lg" />
    </div>

    <!-- Empty State -->
    <div
      v-else-if="!tasks?.length"
      class="glass-card flex flex-col items-center justify-center py-16 text-center"
    >
      <div class="mb-4 text-5xl">📂</div>
      <h3 class="text-lg font-medium text-[hsl(var(--foreground))]">暂无同步任务</h3>
      <p class="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
        创建同步任务来在本地与网盘之间同步文件
      </p>
      <Button class="mt-4" @click="openCreateSheet">
        <Plus class="mr-1.5 h-4 w-4" />
        创建第一个任务
      </Button>
    </div>

    <!-- Task Grid -->
    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SyncTaskCard
        v-for="task in tasks"
        :key="task.id"
        :task="task"
        :selected="selectedTaskId === task.id"
        :running="runningTaskIds.has(task.id)"
        @select="handleSelect"
        @run="handleRun"
        @stop="handleStop"
        @edit="handleEdit"
        @delete="handleDeleteRequest"
        @toggle="handleToggle"
        @view-log="handleViewLog"
      />
    </div>

    <!-- Execution History -->
    <div v-if="selectedTask" class="glass-card space-y-3">
      <div class="flex items-center gap-2">
        <span class="text-base">🕘</span>
        <h2 class="text-base font-semibold text-[hsl(var(--foreground))]">
          执行历史 — {{ selectedTask.name }}
        </h2>
      </div>

      <div v-if="execLoading" class="space-y-2">
        <Skeleton v-for="i in 3" :key="i" class="h-10 rounded" />
      </div>

      <div
        v-else-if="!executions?.length"
        class="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]"
      >
        暂无执行记录
      </div>

      <div v-else class="rounded-md border border-[hsl(var(--border))] overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-[hsl(var(--muted))]/50">
            <tr>
              <th class="px-4 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">时间</th>
              <th class="px-4 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">状态</th>
              <th class="px-4 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">文件数</th>
              <th class="px-4 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="exec in executions"
              :key="exec.id"
              class="border-t border-[hsl(var(--border))]"
            >
              <td class="px-4 py-2 text-[hsl(var(--foreground))]">{{ formatTime(exec.started_at) }}</td>
              <td class="px-4 py-2">
                <span :class="execStatusClass(exec.status)">{{ execStatusLabel(exec.status) }}</span>
              </td>
              <td class="px-4 py-2 text-[hsl(var(--foreground))]">
                <span class="inline-flex items-center gap-1">
                  <FileCheck class="h-3 w-3" />
                  {{ exec.stats?.total_files ?? '—' }}
                </span>
              </td>
              <td class="px-4 py-2 text-[hsl(var(--muted-foreground))]">
                {{ formatDuration(exec.started_at, exec.finished_at) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Create/Edit Sheet -->
    <CreateSyncSheet :open="sheetOpen" :edit-task="editingTask" @close="handleSheetClose" />

    <!-- Sync Log Dialog -->
    <SyncLogDialog
      :visible="streamLogVisible"
      :url="streamLogUrl"
      :title="streamLogTitle"
      :method="streamLogMethod"
      :task-id="streamLogTaskId"
      @update:visible="streamLogVisible = $event"
      @done="handleStreamLogDone"
    />

    <!-- Delete Confirm Dialog -->
    <AlertDialog :open="deleteDialogOpen" @update:open="deleteDialogOpen = $event">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认删除</AlertDialogTitle>
          <AlertDialogDescription>
            确定要删除同步任务「{{ taskToDelete?.name }}」吗？此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="deleteDialogOpen = false">取消</AlertDialogCancel>
          <AlertDialogAction
            class="bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] hover:bg-[hsl(var(--destructive))]/90"
            @click="handleDeleteConfirm"
          >
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
