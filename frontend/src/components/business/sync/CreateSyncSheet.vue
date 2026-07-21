<script setup lang="ts">
import { ref, watch, computed, reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { X, Folder, FolderOpen, Loader2, ArrowUp, RefreshCw, FileText } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useCreateSyncTaskMutation, useUpdateSyncTaskMutation } from '@/hooks/mutations/sync'
import { useDriveAccountsQuery } from '@/hooks/queries/extensions'
import { useTasksQuery } from '@/hooks/queries/tasks'
import { browseLocalSync, browseNetdiskSync } from '@/api/syncTasks'
import { browseOpenList } from '@/api/openlist'
import type { SyncTaskItem } from '@/types/syncTasks'

interface Props {
  open: boolean
  editTask?: SyncTaskItem | null
}

const props = withDefaults(defineProps<Props>(), {
  editTask: null,
})

const emit = defineEmits<{
  close: []
}>()

const { toast } = useToast()
const createMutation = useCreateSyncTaskMutation()
const updateMutation = useUpdateSyncTaskMutation()
const { data: accountsData } = useDriveAccountsQuery()
const { data: dramaTasks } = useTasksQuery()

const SUPPORTED_NETDISK_DRIVE_TYPES = ['115', 'cloud139', 'cloud189', 'uc', 'quark'] as const

const availableAccounts = computed(() =>
  (accountsData.value ?? [])
    .filter((a) => a.enabled && (SUPPORTED_NETDISK_DRIVE_TYPES as readonly string[]).includes(a.drive_type))
    .sort((a, b) => (a.is_default ? -1 : b.is_default ? 1 : a.name.localeCompare(b.name))),
)

const isEditing = computed(() => !!props.editTask)
const title = computed(() => (isEditing.value ? '编辑同步任务' : '新建同步任务'))

// Form state
const name = ref('')
const enabled = ref(true)
const sourceType = ref<'local' | 'netdisk' | 'openlist'>('local')
const sourceAccountId = ref<number | null>(null)
const sourcePath = ref('/')
const targetType = ref<'local' | 'netdisk' | 'openlist'>('netdisk')
const targetAccountId = ref<number | null>(null)
const targetPath = ref('/')
const mode = ref<'one_way' | 'two_way'>('one_way')
const overwrite = ref(false)
const deleteExtras = ref(false)
const forceRefresh = ref(false)
const concurrency = ref(4)
const requestIntervalSeconds = ref(0)
const openlistCopyBatchSize = ref(200)
const dramaTaskUids = ref<string[]>([])

function resetForm() {
  name.value = ''
  enabled.value = true
  sourceType.value = 'local'
  sourceAccountId.value = null
  sourcePath.value = '/'
  targetType.value = 'netdisk'
  targetAccountId.value = null
  targetPath.value = '/'
  mode.value = 'one_way'
  overwrite.value = false
  deleteExtras.value = false
  forceRefresh.value = false
  concurrency.value = 4
  requestIntervalSeconds.value = 0
  openlistCopyBatchSize.value = 200
  dramaTaskUids.value = []
}

function fillFromTask(task: SyncTaskItem) {
  name.value = task.name
  enabled.value = task.enabled
  sourceType.value = task.source.type
  sourceAccountId.value = task.source.account_id ?? null
  sourcePath.value = task.source.path
  targetType.value = task.target.type
  targetAccountId.value = task.target.account_id ?? null
  targetPath.value = task.target.path
  mode.value = task.mode
  overwrite.value = task.strategy.overwrite
  deleteExtras.value = task.strategy.one_way_delete_extras
  forceRefresh.value = task.strategy.force_refresh
  concurrency.value = task.strategy.concurrency
  requestIntervalSeconds.value = task.strategy.request_interval_seconds
  openlistCopyBatchSize.value = task.strategy.openlist_copy_batch_size
  dramaTaskUids.value = [...(task.drama_task_uids ?? [])]
}

watch(
  () => props.open,
  (val) => {
    if (val) {
      if (props.editTask) {
        fillFromTask(props.editTask)
      } else {
        resetForm()
      }
    }
  },
)

function buildPayload() {
  return {
    name: name.value.trim(),
    enabled: enabled.value,
    source: {
      type: sourceType.value,
      path: sourcePath.value,
      account_id: sourceType.value === 'netdisk' ? sourceAccountId.value : undefined,
    },
    target: {
      type: targetType.value,
      path: targetPath.value,
      account_id: targetType.value === 'netdisk' ? targetAccountId.value : undefined,
    },
    mode: mode.value,
    strategy: {
      overwrite: overwrite.value,
      one_way_delete_extras: deleteExtras.value,
      force_refresh: forceRefresh.value,
      concurrency: concurrency.value,
      request_interval_seconds: requestIntervalSeconds.value,
      openlist_copy_batch_size: openlistCopyBatchSize.value,
    },
    drama_task_uids: dramaTaskUids.value,
  }
}

function handleSubmit() {
  if (!name.value.trim()) return
  if (isEditing.value && props.editTask) {
    updateMutation.mutate(
      { syncTaskId: props.editTask.id, payload: buildPayload() },
      {
        onSuccess: () => {
          toast.success('同步任务已更新')
          emit('close')
        },
        onError: (err: any) => {
          toast.error('更新失败', { description: err?.message || '未知错误' })
        },
      },
    )
  } else {
    createMutation.mutate(buildPayload(), {
      onSuccess: () => {
        toast.success('同步任务已创建')
        resetForm()
        emit('close')
      },
      onError: (err: any) => {
        toast.error('创建失败', { description: err?.message || '未知错误' })
      },
    })
  }
}

const isPending = computed(() => createMutation.isPending.value || updateMutation.isPending.value)

function handleOverlayClick() {
  emit('close')
}

function toggleDramaTask(uid: string) {
  const idx = dramaTaskUids.value.indexOf(uid)
  if (idx >= 0) {
    dramaTaskUids.value.splice(idx, 1)
  } else {
    dramaTaskUids.value.push(uid)
  }
}

// ===== Path Browser =====
const pathPicker = reactive({
  visible: false,
  loading: false,
  endpoint: '' as 'source' | 'target',
  endpointType: '' as 'local' | 'netdisk' | 'openlist',
  accountName: '',
  currentPath: '/',
  paths: [] as Array<{ name: string; fid?: string; path?: string }>,
  items: [] as Array<{ name: string; is_dir: boolean; size?: number | null; updated_at?: any; fid?: string; path?: string }>,
  error: '',
})

function getAccountName(accountId: number | null): string {
  if (!accountId) return ''
  const acc = availableAccounts.value.find((a) => a.id === accountId)
  return acc?.name || ''
}

async function openPathPicker(endpoint: 'source' | 'target') {
  const type = endpoint === 'source' ? sourceType.value : targetType.value
  const accountId = endpoint === 'source' ? sourceAccountId.value : targetAccountId.value

  if (type === 'netdisk' && !accountId) {
    toast.error('请先选择网盘账号')
    return
  }

  pathPicker.endpoint = endpoint
  pathPicker.endpointType = type
  pathPicker.accountName = type === 'netdisk' ? getAccountName(accountId) : ''
  pathPicker.currentPath = (endpoint === 'source' ? sourcePath.value : targetPath.value) || '/'
  pathPicker.visible = true
  pathPicker.error = ''
  await refreshPicker()
}

async function refreshPicker() {
  pathPicker.loading = true
  pathPicker.error = ''
  try {
    if (pathPicker.endpointType === 'local') {
      const res = await browseLocalSync({ path: pathPicker.currentPath, max_items: 500 })
      pathPicker.currentPath = res.dir_path || pathPicker.currentPath
      pathPicker.items = res.items || []
      pathPicker.paths = res.paths || []
    } else if (pathPicker.endpointType === 'netdisk') {
      const res = await browseNetdiskSync({ dir_path: pathPicker.currentPath, account_name: pathPicker.accountName, max_items: 500 })
      pathPicker.currentPath = res.dir_path || pathPicker.currentPath
      pathPicker.items = res.items || []
      pathPicker.paths = res.paths || []
    } else if (pathPicker.endpointType === 'openlist') {
      const res = await browseOpenList({ path: pathPicker.currentPath, max_items: 500 })
      pathPicker.currentPath = res.dir_path || pathPicker.currentPath
      pathPicker.items = res.items || []
      pathPicker.paths = res.paths || []
    }
  } catch (e: any) {
    pathPicker.error = e?.message || '浏览失败'
    pathPicker.items = []
    pathPicker.paths = []
  } finally {
    pathPicker.loading = false
  }
}

function pickerEnterDir(item: { name: string; path?: string }) {
  const newPath = item.path
    ? item.path
    : pathPicker.currentPath.endsWith('/')
      ? pathPicker.currentPath + item.name
      : pathPicker.currentPath + '/' + item.name
  pathPicker.currentPath = newPath
  refreshPicker()
}

function pickerGoUp() {
  const parts = pathPicker.currentPath.replace(/\/+$/, '').split('/')
  parts.pop()
  const parent = parts.join('/') || '/'
  pathPicker.currentPath = parent
  refreshPicker()
}

function pickerGoToBreadcrumb(index: number) {
  if (pathPicker.endpointType === 'local') {
    const parts = pathPicker.paths.slice(0, index + 1)
    const path = parts.map((p) => p.name).join('/') || '/'
    pathPicker.currentPath = path.startsWith('/') ? path : '/' + path
  } else {
    const parts = pathPicker.paths.slice(0, index + 1)
    pathPicker.currentPath = '/' + parts.map((p) => p.name).join('/')
  }
  refreshPicker()
}

function pickerConfirm(withTaskName: boolean) {
  let path = pathPicker.currentPath || '/'
  if (withTaskName && name.value.trim()) {
    path = `${path}/${name.value.trim()}`.replace(/\/+/g, '/')
  }
  if (pathPicker.endpoint === 'source') {
    sourcePath.value = path
  } else {
    targetPath.value = path
  }
  pathPicker.visible = false
}

function closePicker() {
  pathPicker.visible = false
}
</script>

<template>
  <!-- ===== Path Browser Modal ===== -->
  <Teleport to="body">
    <div v-if="pathPicker.visible" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="closePicker" />
      <div class="relative z-10 w-[640px] max-w-[90vw] max-h-[80vh] rounded-lg bg-[hsl(var(--background))] shadow-xl flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))]">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">
            浏览{{ pathPicker.endpoint === 'source' ? '源' : '目标' }}路径
            <span class="ml-2 text-xs font-normal text-[hsl(var(--muted-foreground))]">
              ({{ pathPicker.endpointType === 'local' ? '本地' : pathPicker.endpointType === 'netdisk' ? '网盘' : 'OpenList' }})
            </span>
          </h3>
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))]" @click="closePicker">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>

        <!-- Breadcrumb & toolbar -->
        <div class="px-5 py-2 border-b border-[hsl(var(--border))] flex items-center gap-2">
          <button
            class="rounded p-1 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]"
            title="返回上级"
            @click="pickerGoUp"
          >
            <ArrowUp class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]"
            title="刷新"
            @click="refreshPicker"
          >
            <RefreshCw class="h-4 w-4" />
          </button>
          <div class="flex-1 flex items-center gap-0.5 overflow-x-auto text-xs text-[hsl(var(--muted-foreground))]">
            <button
              class="hover:text-[hsl(var(--foreground))] hover:underline shrink-0 px-1"
              @click="pathPicker.currentPath = '/'; refreshPicker()"
            >/</button>
            <template v-for="(seg, idx) in pathPicker.paths" :key="idx">
              <span class="shrink-0">/</span>
              <button
                class="hover:text-[hsl(var(--foreground))] hover:underline shrink-0 px-1 truncate max-w-[120px]"
                :title="seg.name"
                @click="pickerGoToBreadcrumb(idx)"
              >{{ seg.name }}</button>
            </template>
          </div>
        </div>

        <!-- Directory listing -->
        <div class="flex-1 overflow-y-auto px-5 py-3 min-h-[200px]">
          <div v-if="pathPicker.loading" class="flex items-center justify-center py-8">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="pathPicker.error" class="text-xs text-red-500 py-4 text-center">{{ pathPicker.error }}</div>
          <div v-else-if="pathPicker.items.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-4 text-center">
            当前目录为空
          </div>
          <div v-else class="space-y-0.5">
            <div
              v-for="(item, idx) in pathPicker.items.filter(i => i.is_dir)"
              :key="'d-' + idx"
              class="flex items-center gap-2 px-2 py-2 rounded cursor-pointer hover:bg-[hsl(var(--accent))] text-sm"
              @click="pickerEnterDir(item)"
            >
              <Folder class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0" />
              <span class="truncate text-[hsl(var(--foreground))] flex-1">{{ item.name }}</span>
            </div>
            <div
              v-for="(item, idx) in pathPicker.items.filter(i => !i.is_dir)"
              :key="'f-' + idx"
              class="flex items-center gap-2 px-2 py-2 rounded text-sm opacity-60"
            >
              <FileText class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0" />
              <span class="truncate text-[hsl(var(--foreground))] flex-1">{{ item.name }}</span>
              <span v-if="item.size" class="text-xs text-[hsl(var(--muted-foreground))] shrink-0">
                {{ item.size > 1048576 ? (item.size / 1048576).toFixed(1) + ' MB' : item.size > 1024 ? (item.size / 1024).toFixed(1) + ' KB' : item.size + ' B' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-[hsl(var(--border))] flex items-center gap-2">
          <Button size="sm" @click="pickerConfirm(false)">使用当前文件夹</Button>
          <Button v-if="name.trim()" size="sm" variant="outline" @click="pickerConfirm(true)">
            当前文件夹/{{ name.trim() }}
          </Button>
          <div class="flex-1" />
          <span class="text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[200px]" :title="pathPicker.currentPath">
            {{ pathPicker.currentPath }}
          </span>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Main Sheet ===== -->
  <Teleport to="body">
    <Transition name="sync-sheet">
      <div v-if="open" class="fixed inset-0 z-50 flex justify-end">
        <!-- Overlay -->
        <div
          class="absolute inset-0 bg-black/50 transition-opacity"
          @click="handleOverlayClick"
        />
        <!-- Panel -->
        <div
          class="relative z-10 flex h-full w-[480px] max-w-[90vw] flex-col bg-[hsl(var(--card))] shadow-xl"
        >
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
            <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">{{ title }}</h2>
            <Button variant="ghost" size="icon" class="h-8 w-8" @click="emit('close')">
              <X class="h-4 w-4" />
            </Button>
          </div>

          <!-- Form -->
          <div class="flex-1 overflow-y-auto px-6 py-4 space-y-6">
            <!-- 基础信息 -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">基础信息</h3>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">任务名称</label>
                <Input v-model="name" placeholder="输入任务名称" />
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">源类型</label>
                <select
                  v-model="sourceType"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option value="local">本地路径</option>
                  <option value="netdisk">网盘</option>
                  <option value="openlist">OpenList</option>
                </select>
              </div>

              <div v-if="sourceType === 'netdisk'" class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">源网盘账号</label>
                <select
                  v-model="sourceAccountId"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option :value="null">请选择账号</option>
                  <option v-for="acc in availableAccounts" :key="acc.id" :value="acc.id">
                    {{ acc.name }} ({{ acc.drive_type }})
                  </option>
                </select>
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">源路径</label>
                <div class="flex gap-2">
                  <Input v-model="sourcePath" placeholder="输入源路径" class="flex-1" />
                  <Button variant="outline" size="sm" @click="openPathPicker('source')">
                    <FolderOpen class="h-4 w-4 mr-1" />
                    浏览
                  </Button>
                </div>
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">目标类型</label>
                <select
                  v-model="targetType"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option value="local">本地路径</option>
                  <option value="netdisk">网盘</option>
                  <option value="openlist">OpenList</option>
                </select>
              </div>

              <div v-if="targetType === 'netdisk'" class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">目标网盘账号</label>
                <select
                  v-model="targetAccountId"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option :value="null">请选择账号</option>
                  <option v-for="acc in availableAccounts" :key="acc.id" :value="acc.id">
                    {{ acc.name }} ({{ acc.drive_type }})
                  </option>
                </select>
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">目标路径</label>
                <div class="flex gap-2">
                  <Input v-model="targetPath" placeholder="输入目标路径" class="flex-1" />
                  <Button variant="outline" size="sm" @click="openPathPicker('target')">
                    <FolderOpen class="h-4 w-4 mr-1" />
                    浏览
                  </Button>
                </div>
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">同步模式</label>
                <select
                  v-model="mode"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option value="one_way">单向同步</option>
                  <option value="two_way">双向同步</option>
                </select>
              </div>
            </div>

            <!-- 策略参数 -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">策略参数</h3>

              <label class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" v-model="overwrite" class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                <span class="text-sm text-[hsl(var(--foreground))]">覆盖同名文件</span>
              </label>

              <label class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" v-model="deleteExtras" class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                <span class="text-sm text-[hsl(var(--foreground))]">删除多余文件（单向模式）</span>
              </label>

              <label class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" v-model="forceRefresh" class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                <span class="text-sm text-[hsl(var(--foreground))]">强制刷新</span>
              </label>

              <label class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" v-model="enabled" class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                <span class="text-sm text-[hsl(var(--foreground))]">启用任务</span>
              </label>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">并发数</label>
                <Input v-model.number="concurrency" type="number" min="1" max="32" placeholder="4" />
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">请求间隔（秒）</label>
                <Input v-model.number="requestIntervalSeconds" type="number" min="0" max="5" step="0.1" placeholder="0" />
              </div>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">批量复制大小</label>
                <Input v-model.number="openlistCopyBatchSize" type="number" min="1" max="5000" placeholder="200" />
              </div>
            </div>

            <!-- 高级选项 -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">高级选项</h3>

              <div class="space-y-1.5">
                <label class="text-sm font-medium text-[hsl(var(--foreground))]">关联追剧任务</label>
                <div class="max-h-40 overflow-y-auto rounded-md border border-[hsl(var(--border))] p-2 space-y-1">
                  <div v-if="!dramaTasks?.length" class="text-xs text-[hsl(var(--muted-foreground))] py-2 text-center">
                    暂无追剧任务
                  </div>
                  <label
                    v-for="dt in dramaTasks"
                    :key="dt.task_uid"
                    class="flex items-center gap-2 rounded px-2 py-1 cursor-pointer hover:bg-[hsl(var(--muted))]"
                  >
                    <input
                      type="checkbox"
                      :checked="dramaTaskUids.includes(dt.task_uid)"
                      class="h-3.5 w-3.5 rounded border-[hsl(var(--border))]"
                      @change="toggleDramaTask(dt.task_uid)"
                    />
                    <span class="text-sm text-[hsl(var(--foreground))] truncate">{{ dt.taskname }}</span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="border-t border-[hsl(var(--border))] px-6 py-4 flex gap-3">
            <Button variant="outline" class="flex-1" @click="emit('close')">取消</Button>
            <Button
              variant="default"
              class="flex-1"
              :disabled="!name.trim() || isPending"
              @click="handleSubmit"
            >
              {{ isPending ? '保存中...' : isEditing ? '保存修改' : '创建任务' }}
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sync-sheet-enter-active,
.sync-sheet-leave-active {
  transition: opacity 0.2s ease;
}
.sync-sheet-enter-active > div:last-child,
.sync-sheet-leave-active > div:last-child {
  transition: transform 0.2s ease;
}
.sync-sheet-enter-from,
.sync-sheet-leave-to {
  opacity: 0;
}
.sync-sheet-enter-from > div:last-child,
.sync-sheet-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
