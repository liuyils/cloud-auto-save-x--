<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import {
  Plus, Search, Film, Play, Wrench, Square, Camera, ChevronDown, ChevronUp,
} from 'lucide-vue-next'
import TaskCard from '@/components/business/drama/TaskCard.vue'
import CreateTaskSheet from '@/components/business/drama/CreateTaskSheet.vue'
import StreamLogDialog from '@/components/business/common/StreamLogDialog.vue'
import { useTasksQuery, useTaskSchedulerSettingQuery } from '@/hooks/queries/tasks'
import {
  useDeleteTaskMutation,
  useSetTaskStatusMutation,
  useRepairBannedMutation,
  useStopCompletedMutation,
  useSyncSnapshotsMutation,
  useUpdateSchedulerMutation,
  useRunAllTasksMutation,
} from '@/hooks/mutations/tasks'
import { useToast } from '@/composables/useToast'
import type { TaskItem } from '@/types/tasks'

const { toast } = useToast()

const searchQuery = ref('')
const sheetOpen = ref(false)
const editingTask = ref<TaskItem | undefined>(undefined)

// Stream log state
const showStreamLog = ref(false)
const streamLogUrl = ref('')
const streamLogTitle = ref('执行日志')
const streamLogMethod = ref<'GET' | 'POST'>('GET')
const streamLogBody = ref<Record<string, any> | null>(null)

// Delete confirm state
const deleteDialogOpen = ref(false)
const taskToDelete = ref<TaskItem | null>(null)

// Scheduler panel collapsed state
const schedulerExpanded = ref(false)

// Queries
const { data: tasks, isLoading } = useTasksQuery()
const { data: schedulerData } = useTaskSchedulerSettingQuery()

// Mutations
const deleteMutation = useDeleteTaskMutation()
const statusMutation = useSetTaskStatusMutation()
const repairMutation = useRepairBannedMutation()
const stopMutation = useStopCompletedMutation()
const syncMutation = useSyncSnapshotsMutation()
const schedulerMutation = useUpdateSchedulerMutation()
const runAllMutation = useRunAllTasksMutation()

// Scheduler form
const schedulerForm = reactive({
  enabled: false,
  crontab: '',
  timezone: 'Asia/Shanghai',
})

watch(
  () => schedulerData.value,
  (val) => {
    if (val) {
      schedulerForm.enabled = val.enabled
      schedulerForm.crontab = val.crontab || ''
      schedulerForm.timezone = val.timezone || 'Asia/Shanghai'
    }
  },
  { immediate: true },
)

// --- Task categorization: 进行中 > 已完结 > 已禁用 ---
type TaskCategory = 'active' | 'ended' | 'disabled'

function getTaskCategory(t: TaskItem): TaskCategory {
  if (!t.enabled) return 'disabled'
  if (t.tmdb_is_ended === true || t.extra?.ended === true) return 'ended'
  return 'active'
}

const CATEGORY_ORDER: Record<TaskCategory, number> = { active: 0, ended: 1, disabled: 2 }
const CATEGORY_LABELS: Record<TaskCategory, string> = { active: '进行中', ended: '已完结', disabled: '已禁用' }

const filteredTasks = computed(() => {
  const list = tasks.value || []
  const q = searchQuery.value.trim().toLowerCase()
  const filtered = q
    ? list.filter(
        (t) =>
          t.taskname.toLowerCase().includes(q) ||
          t.shareurl.toLowerCase().includes(q) ||
          t.savepath.toLowerCase().includes(q),
      )
    : [...list]
  return filtered.sort((a, b) => CATEGORY_ORDER[getTaskCategory(a)] - CATEGORY_ORDER[getTaskCategory(b)])
})

// Grouped tasks with category headers for display
const groupedTasks = computed(() => {
  const groups: { category: TaskCategory; label: string; tasks: TaskItem[] }[] = []
  for (const cat of ['active', 'ended', 'disabled'] as TaskCategory[]) {
    const items = filteredTasks.value.filter((t) => getTaskCategory(t) === cat)
    if (items.length) groups.push({ category: cat, label: CATEGORY_LABELS[cat], tasks: items })
  }
  return groups
})

// Category counts for stat tiles (over all tasks, not filtered)
const categoryCounts = computed(() => {
  const list = tasks.value || []
  return {
    active: list.filter((t) => getTaskCategory(t) === 'active').length,
    ended: list.filter((t) => getTaskCategory(t) === 'ended').length,
    disabled: list.filter((t) => getTaskCategory(t) === 'disabled').length,
  }
})

// --- Batch actions ---
function handleRunAll() {
  streamLogTitle.value = '执行全部：日志'
  streamLogUrl.value = '/api/tasks/run-all/stream'
  streamLogMethod.value = 'POST'
  streamLogBody.value = null
  showStreamLog.value = true
}

function handleRepairBanned() {
  repairMutation.mutate(undefined, {
    onSuccess: () => toast.success('修复失效完成'),
    onError: (e: any) => toast.error(e?.message || '修复失效失败'),
  })
}

function handleStopCompleted() {
  stopMutation.mutate(undefined, {
    onSuccess: () => toast.success('停止完结任务完成'),
    onError: (e: any) => toast.error(e?.message || '停止完结任务失败'),
  })
}

function handleSyncSnapshots() {
  syncMutation.mutate(undefined, {
    onSuccess: () => toast.success('同步快照完成'),
    onError: (e: any) => toast.error(e?.message || '同步快照失败'),
  })
}

// --- Scheduler ---
function saveScheduler() {
  schedulerMutation.mutate(
    {
      enabled: schedulerForm.enabled,
      crontab: schedulerForm.crontab,
      timezone: schedulerForm.timezone,
    },
    {
      onSuccess: () => toast.success('调度配置已保存'),
      onError: (e: any) => toast.error(e?.message || '保存调度配置失败'),
    },
  )
}

// --- Per-task actions ---
function handleRun(task: TaskItem) {
  streamLogTitle.value = `运行：${task.taskname}`
  streamLogUrl.value = `/api/tasks/${task.id}/run/stream`
  streamLogMethod.value = 'POST'
  streamLogBody.value = null
  showStreamLog.value = true
}

function handleRunOnceTask(task: TaskItem) {
  streamLogTitle.value = `运行一次: ${task.taskname}`
  streamLogUrl.value = `/api/tasks/${task.id}/run/stream`
  streamLogMethod.value = 'POST'
  streamLogBody.value = null
  showStreamLog.value = true
}

function handleRunOnce(payload: Record<string, any>) {
  streamLogTitle.value = `运行一次：${payload.taskname || '任务'}`
  streamLogUrl.value = '/api/tasks/run/stream'
  streamLogMethod.value = 'POST'
  streamLogBody.value = payload
  showStreamLog.value = true
  sheetOpen.value = false
  editingTask.value = undefined
}

function handleEdit(task: TaskItem) {
  editingTask.value = task
  sheetOpen.value = true
}

function handleDeleteConfirm(task: TaskItem) {
  taskToDelete.value = task
  deleteDialogOpen.value = true
}

function handleDeleteExecute() {
  if (!taskToDelete.value) return
  deleteMutation.mutate(taskToDelete.value.id, {
    onSuccess: () => {
      toast.success('任务已删除')
      deleteDialogOpen.value = false
      taskToDelete.value = null
    },
    onError: (e: any) => toast.error(e?.message || '删除失败'),
  })
}

function handleToggleStatus(task: TaskItem) {
  statusMutation.mutate(
    { taskId: task.id, enabled: !task.enabled },
    {
      onSuccess: () => toast.success(task.enabled ? '已暂停' : '已启用'),
      onError: (e: any) => toast.error(e?.message || '操作失败'),
    },
  )
}

function handleSheetClose() {
  sheetOpen.value = false
  editingTask.value = undefined
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="border-b border-[hsl(var(--border))] px-6 pt-5 pb-4">
      <h1 class="text-2xl font-bold text-[hsl(var(--foreground))]">🎬 追剧任务</h1>
      <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">管理追剧任务、全局调度与批量操作</p>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-6">
      <!-- Stat tiles -->
      <div class="mb-4 grid grid-cols-3 gap-3">
        <div class="glass-tile">
          <div class="glass-tile__top">
            <span class="glass-tile__emoji">🟢</span>
            <span class="glass-tile__label">进行中</span>
          </div>
          <div class="glass-tile__value">{{ categoryCounts.active }}</div>
        </div>
        <div class="glass-tile">
          <div class="glass-tile__top">
            <span class="glass-tile__emoji">🏁</span>
            <span class="glass-tile__label">已完结</span>
          </div>
          <div class="glass-tile__value">{{ categoryCounts.ended }}</div>
        </div>
        <div class="glass-tile">
          <div class="glass-tile__top">
            <span class="glass-tile__emoji">⏸️</span>
            <span class="glass-tile__label">已禁用</span>
          </div>
          <div class="glass-tile__value">{{ categoryCounts.disabled }}</div>
        </div>
      </div>

      <!-- Global Scheduler Config -->
      <div class="mb-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted)/.3)] p-3">
        <button
          class="flex w-full items-center justify-between text-sm font-medium text-[hsl(var(--foreground))]"
          @click="schedulerExpanded = !schedulerExpanded"
        >
          <span>全局调度配置</span>
          <component :is="schedulerExpanded ? ChevronUp : ChevronDown" class="h-4 w-4" />
        </button>
        <div v-if="schedulerExpanded" class="mt-3 flex flex-wrap items-center gap-4">
          <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
            <input
              type="checkbox"
              v-model="schedulerForm.enabled"
              class="h-4 w-4 rounded border-[hsl(var(--border))]"
            />
            启用
          </label>
          <div class="flex items-center gap-2">
            <label class="text-sm text-[hsl(var(--muted-foreground))]">Crontab</label>
            <Input v-model="schedulerForm.crontab" placeholder="0 */6 * * *" class="w-40 h-8 text-sm" />
          </div>
          <div class="flex items-center gap-2">
            <label class="text-sm text-[hsl(var(--muted-foreground))]">时区</label>
            <Input v-model="schedulerForm.timezone" placeholder="Asia/Shanghai" class="w-36 h-8 text-sm" />
          </div>
          <Button size="sm" @click="saveScheduler" :disabled="schedulerMutation.isPending.value">
            保存
          </Button>
        </div>
      </div>

      <!-- Toolbar: search + new task -->
      <div class="mb-4 flex items-center gap-3">
        <div class="relative flex-1 max-w-sm">
          <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <Input v-model="searchQuery" placeholder="搜索任务..." class="pl-9" />
        </div>
        <Button size="sm" @click="editingTask = undefined; sheetOpen = true">
          <Plus class="mr-1 h-4 w-4" />
          新建任务
        </Button>
      </div>

      <!-- Batch action bar -->
      <div class="mb-5 flex items-center gap-2 flex-wrap">
        <Button size="sm" @click="handleRunAll" :disabled="runAllMutation.isPending.value">
          <Play class="mr-1 h-4 w-4" /> 执行全部
        </Button>
        <Button size="sm" variant="outline" @click="handleRepairBanned" :disabled="repairMutation.isPending.value">
          <Wrench class="mr-1 h-4 w-4" /> 修复失效
        </Button>
        <Button size="sm" variant="outline" @click="handleStopCompleted" :disabled="stopMutation.isPending.value">
          <Square class="mr-1 h-4 w-4" /> 停止完结
        </Button>
        <Button size="sm" variant="outline" @click="handleSyncSnapshots" :disabled="syncMutation.isPending.value">
          <Camera class="mr-1 h-4 w-4" /> 同步快照
        </Button>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton v-for="i in 6" :key="i" class="h-36 rounded-lg" />
      </div>

      <!-- Empty state -->
      <div
        v-else-if="filteredTasks.length === 0 && !searchQuery"
        class="flex flex-col items-center justify-center py-20"
      >
        <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-[hsl(var(--muted))]">
          <Film class="h-8 w-8 text-[hsl(var(--muted-foreground))]" />
        </div>
        <h3 class="mb-1 text-lg font-medium text-[hsl(var(--foreground))]">还没有追剧任务</h3>
        <p class="mb-4 text-sm text-[hsl(var(--muted-foreground))]">创建第一个任务，开始自动追剧吧</p>
        <Button size="sm" @click="sheetOpen = true">
          <Plus class="mr-1 h-4 w-4" />
          创建任务
        </Button>
      </div>

      <!-- No results -->
      <div
        v-else-if="filteredTasks.length === 0 && searchQuery"
        class="flex flex-col items-center justify-center py-20"
      >
        <p class="text-sm text-[hsl(var(--muted-foreground))]">未找到匹配「{{ searchQuery }}」的任务</p>
      </div>

      <!-- Task grid grouped by category -->
      <div v-else class="space-y-6">
        <div v-for="group in groupedTasks" :key="group.category">
          <div class="mb-3 flex items-center gap-2">
            <span
              class="h-2 w-2 rounded-full"
              :class="{
                'bg-green-500': group.category === 'active',
                'bg-emerald-400': group.category === 'ended',
                'bg-gray-400': group.category === 'disabled',
              }"
            />
            <h2 class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ group.label }}</h2>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ group.tasks.length }}</span>
          </div>
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <TaskCard
              v-for="task in group.tasks"
              :key="task.id"
              :task="task"
              @run="handleRun"
              @run-once="handleRunOnceTask"
              @edit="handleEdit"
              @delete="handleDeleteConfirm"
              @toggle-status="handleToggleStatus"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Task Sheet -->
    <CreateTaskSheet :open="sheetOpen" :edit-task="editingTask" :preset-tmdb="null" @close="handleSheetClose" @run-once="handleRunOnce" />

    <!-- Stream Log Dialog -->
    <StreamLogDialog
      v-model:visible="showStreamLog"
      :url="streamLogUrl"
      :title="streamLogTitle"
      :method="streamLogMethod"
      :body="streamLogBody"
    />

    <!-- Delete Confirm Dialog -->
    <AlertDialog :open="deleteDialogOpen" @update:open="deleteDialogOpen = $event">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认删除</AlertDialogTitle>
          <AlertDialogDescription>
            确定要删除任务「{{ taskToDelete?.taskname }}」吗？此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="deleteDialogOpen = false">取消</AlertDialogCancel>
          <AlertDialogAction class="bg-red-600 hover:bg-red-700" @click="handleDeleteExecute">
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
