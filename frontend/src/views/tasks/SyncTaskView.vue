<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  browseNetdiskSync,
  browseLocalSync,
  cancelSyncExecution,
  createSyncTask,
  deleteSyncTask,
  fetchSyncExecutionFiles,
  fetchSyncExecutionLatest,
  fetchSyncExecutions,
  fetchSyncTasks,
  updateSyncTask,
} from '@/api/syncTasks'
import { fetchDriveAccounts } from '@/api/extensions'
import { fetchTasks } from '@/api/tasks'
import { fetchSyncPlugins } from '@/api/extensions'
import { SYNC_RUN, SYNC_WRITE } from '@/constants/permissions'
import { useIsMobile } from '@/composables/useIsMobile'
import { useAuthStore } from '@/stores/auth'
import { browseOpenList } from '@/api/openlist'
import type { PathBrowseItem, PathBrowsePath } from '@/types/pathBrowse'
import type { SyncExecutionFileItem, SyncExecutionItem, SyncMode, SyncTaskItem } from '@/types/syncTasks'
import type { DriveBrowseItem, DriveBrowsePath, TaskItem } from '@/types/tasks'
import type { DriveAccountItem, PluginItem } from '@/types/extensions'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(SYNC_WRITE))
const canRun = computed(() => auth.permissions.includes(SYNC_RUN))
const isMobile = useIsMobile()

const loading = ref(false)
const submitting = ref(false)
const tasks = ref<SyncTaskItem[]>([])
const executionsMap = ref(new Map<number, SyncExecutionItem[]>())
const dramaTasks = ref<TaskItem[]>([])
const plugins = ref<PluginItem[]>([])
const driveAccounts = ref<DriveAccountItem[]>([])

const SUPPORTED_NETDISK_DRIVE_TYPES = ['115', 'cloud139', 'cloud189'] as const

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

const activePlugins = computed(() => {
  return [...plugins.value]
    .filter((item) => Boolean(item.installed) && Boolean(item.enabled))
    .sort((a, b) => {
      const ap = Number(a.priority) || 0
      const bp = Number(b.priority) || 0
      if (ap !== bp) return ap - bp
      return String(a.plugin_key).localeCompare(String(b.plugin_key))
    })
})

const dialogWidth = computed(() => (isMobile.value ? '100%' : '900px'))
const dialogTop = computed(() => (isMobile.value ? '0' : '6vh'))
const runStatsGridStyle = computed(() => ({
  display: 'grid',
  gridTemplateColumns: isMobile.value ? 'repeat(2, minmax(0, 1fr))' : 'repeat(4, minmax(0, 1fr))',
  gap: '10px',
  marginBottom: '12px',
}))
const transferStyle = computed(() => ({ width: '100%', minWidth: isMobile.value ? '520px' : '740px' }))
const runEventsTableHeight = computed(() => (isMobile.value ? '50vh' : 360))
const runTreeStyle = computed(() => ({ maxHeight: isMobile.value ? '50vh' : '360px', overflow: 'auto' }))
const runFileCurrentOffset = computed(() => Math.max(0, (Number(runFilePage.page) - 1) * Number(runFilePage.pageSize)))
const runFileDisplayStart = computed(() => (runFilePage.items.length > 0 ? runFileCurrentOffset.value + 1 : 0))
const runFileDisplayEnd = computed(() => runFileCurrentOffset.value + runFilePage.items.length)
const runFileUsingLiveFallback = computed(() => runFilePage.items.length === 0 && runFileLiveItems.value.length > 0)
const runFileDisplayItems = computed(() => (runFileUsingLiveFallback.value ? runFileLiveItems.value : runFilePage.items))

const dramaTransferData = computed(() =>
  dramaTasks.value.map((t) => ({
    key: t.task_uid,
    label: t.taskname,
    disabled: !t.enabled,
  })),
)

const filters = reactive({
  keyword: '',
  enabled: 'all',
})

const filteredTasks = computed(() =>
  tasks.value
    .filter((t) => {
      const kw = String(filters.keyword || '').trim().toLowerCase()
      if (!kw) return true
      return [t.name, endpointText(t.source), endpointText(t.target)].some((v) => String(v || '').toLowerCase().includes(kw))
    })
    .filter((t) => {
      if (filters.enabled === 'all') return true
      if (filters.enabled === 'enabled') return Boolean(t.enabled)
      if (filters.enabled === 'disabled') return !t.enabled
      return true
    }),
)

const drawer = reactive({
  visible: false,
  editing: false,
  id: 0,
  name: '',
  enabled: true,
  mode: 'one_way' as SyncMode,
  sourceType: 'netdisk',
  sourcePath: '/',
  sourceAccountId: null as number | null,
  targetType: 'netdisk',
  targetPath: '/',
  targetAccountId: null as number | null,
  dramaTaskUids: [] as string[],
  addition: {} as Record<string, any>,
  overwrite: false,
  one_way_delete_extras: false,
  force_refresh: false,
  concurrency: 4,
  request_interval_seconds: 0,
  openlist_copy_batch_size: 10,
})

const runLogDialog = reactive({
  visible: false,
  title: '执行日志',
  content: '',
  status: '',
  stage: '',
  message: '',
  syncTaskId: 0,
  executionId: 0,
  startedAt: '',
})

type SyncFileEvent = {
  ts: string
  action: string
  status: string
  path: string
  size?: number
  message?: string
}

const runFileStats = reactive({
  total_files: 0,
  done_files: 0,
  copied_files: 0,
  deleted_files: 0,
  skipped_files: 0,
  failed_files: 0,
})

const runFilePage = reactive({
  loading: false,
  total: 0,
  page: 1,
  pageSize: 100,
  items: [] as SyncFileEvent[],
  executionId: 0,
})
const runFileLiveItems = ref<SyncFileEvent[]>([])

const runFileView = ref<'list' | 'tree'>('list')
let runPollTimer: any = null
let runPollInFlight = false
let runPollDelayMs = 3000
let runFilePageRequestSeq = 0
const runFileTreeRef = ref<any>(null)
const runFileTreeExpandedKeys = ref<string[]>([])

const runLogPre = ref<HTMLElement | null>(null)
let runLogController: AbortController | null = null
let runLogClosing = false

let statusPollTimer: any = null
let statusPollInFlight = false
let statusPollDelayMs = 3000

const pathPicker = reactive({
  visible: false,
  loading: false,
  endpoint: 'source' as 'source' | 'target',
  endpointType: 'openlist' as 'openlist' | 'local' | 'netdisk',
  basePath: '/',
  dirPath: '',
  exists: true,
  paths: [] as PathBrowsePath[],
  items: [] as PathBrowseItem[],
  sortBy: 'file_name' as 'file_name' | 'updated_at',
  sortOrder: 'asc' as 'asc' | 'desc',
})

function endpointText(ep: { type: string; path: string } | null | undefined) {
  if (!ep) return '-'
  const tp = String(ep.type || '').trim() || '-'
  const p = String(ep.path || '').trim() || '-'
  const account = String((ep as any).account_name || '').trim()
  return account ? `${tp}[${account}]:${p}` : `${tp}:${p}`
}

function normalizeOpenListPath(value: string) {
  let p = String(value || '').trim()
  if (!p) return '/'
  if (!p.startsWith('/')) p = `/${p}`
  return p
}

function normalizeLocalRelative(value: string) {
  return String(value || '')
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
}

function normalizeNetdiskPath(value: string) {
  let p = String(value || '').trim().replace(/\\/g, '/')
  if (!p) return '/'
  if (!p.startsWith('/')) p = `/${p}`
  return p.replace(/\/+/g, '/')
}

function joinNetdiskPath(base: string, name: string) {
  const root = normalizeNetdiskPath(base)
  const cleanName = String(name || '').replace(/^\/+/, '')
  if (!cleanName) return root
  return root === '/' ? `/${cleanName}` : `${root}/${cleanName}`
}

function clampNetdiskPathToBase(path: string, basePath: string) {
  const normalizedBase = normalizeNetdiskPath(basePath || '/')
  const normalizedPath = normalizeNetdiskPath(path || normalizedBase)
  if (normalizedBase === '/') return normalizedPath
  if (normalizedPath === normalizedBase || normalizedPath.startsWith(`${normalizedBase}/`)) return normalizedPath
  return normalizedBase
}

function currentNetdiskBasePath() {
  return normalizeNetdiskPath(pathPicker.basePath || '/')
}

const availableNetdiskAccounts = computed(() =>
  [...driveAccounts.value]
    .filter((item) => Boolean(item.enabled) && SUPPORTED_NETDISK_DRIVE_TYPES.includes(item.drive_type as any))
    .sort((a, b) => {
      const ad = a.is_default ? 0 : 1
      const bd = b.is_default ? 0 : 1
      if (ad !== bd) return ad - bd
      return String(a.name || '').localeCompare(String(b.name || ''))
    }),
)

function defaultNetdiskAccountId() {
  const first = availableNetdiskAccounts.value[0]
  return first ? Number(first.id) || null : null
}

function endpointAccountId(endpoint: 'source' | 'target') {
  return endpoint === 'source' ? drawer.sourceAccountId : drawer.targetAccountId
}

function endpointAccount(endpoint: 'source' | 'target') {
  const accountId = endpointAccountId(endpoint)
  return availableNetdiskAccounts.value.find((item) => Number(item.id) === Number(accountId || 0)) || null
}

function isNetdiskType(tp: string) {
  return String(tp || '') === 'netdisk'
}

function isOpenListType(tp: string) {
  return String(tp || '') === 'openlist'
}

function isTypeOptionDisabled(endpoint: 'source' | 'target', option: 'openlist' | 'local' | 'netdisk') {
  const otherType = endpoint === 'source' ? String(drawer.targetType) : String(drawer.sourceType)
  if (option === 'netdisk' && otherType === 'openlist') return true
  if (option === 'openlist' && otherType === 'netdisk') return true
  return false
}

function formatTs(value: any) {
  if (value === undefined || value === null || value === '') return ''
  const n = Number(value)
  const ts = Number.isFinite(n) ? (n < 1e12 ? n * 1000 : n) : Date.parse(String(value))
  if (!Number.isFinite(ts)) return String(value)
  const d = new Date(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd} ${hh}:${mi}`
}

function formatSize(size: any) {
  const n = Number(size)
  if (!Number.isFinite(n) || n < 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  if (idx === 0) return `${Math.floor(value)} ${units[idx]}`
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[idx]}`
}

function toPercent(done: any, total: any) {
  const d = Number(done) || 0
  const t = Number(total) || 0
  if (t <= 0) return 0
  const p = Math.floor((d / t) * 100)
  return Math.max(0, Math.min(100, p))
}

function sortPickerItems(by = pathPicker.sortBy, order = pathPicker.sortOrder) {
  pathPicker.sortBy = by
  pathPicker.sortOrder = order
  const direction = pathPicker.sortOrder === 'asc' ? 1 : -1
  pathPicker.items.sort((a, b) => {
    if (pathPicker.sortBy === 'updated_at') {
      const av = Number((a as any)?.updated_at) || 0
      const bv = Number((b as any)?.updated_at) || 0
      return (av - bv) * direction
    }
    const an = String((a as any)?.name || '').toLowerCase()
    const bn = String((b as any)?.name || '').toLowerCase()
    return an.localeCompare(bn) * direction
  })
}

function onPickerSortChange(payload: any) {
  const prop = String(payload?.prop || '')
  const order = String(payload?.order || '')
  if (prop !== 'name' && prop !== 'updated_at') return
  const by = prop === 'updated_at' ? 'updated_at' : 'file_name'
  if (order === 'ascending') sortPickerItems(by as any, 'asc')
  if (order === 'descending') sortPickerItems(by as any, 'desc')
}

function sanitizeFolderName(name: string) {
  return String(name || '')
    .trim()
    .replace(/[\\/]+/g, '_')
}

async function refreshPathPicker() {
  pathPicker.loading = true
  try {
    if (pathPicker.endpointType === 'openlist') {
      pathPicker.basePath = '/'
      const data = await browseOpenList({ path: normalizeOpenListPath(pathPicker.dirPath), max_items: 500 })
      pathPicker.dirPath = String(data.dir_path || '/')
      pathPicker.exists = Boolean(data.exists)
      pathPicker.paths = data.paths || []
      pathPicker.items = data.items || []
      sortPickerItems(pathPicker.sortBy, pathPicker.sortOrder)
      return
    }
    if (pathPicker.endpointType === 'netdisk') {
      const account = endpointAccount(pathPicker.endpoint)
      if (!account) {
        ElMessage.warning('请先选择网盘账号')
        pathPicker.exists = false
        pathPicker.paths = []
        pathPicker.items = []
        return
      }
      const data = await browseNetdiskSync({
        dir_path: normalizeNetdiskPath(pathPicker.dirPath),
        account_name: account.name,
        max_items: 500,
      })
      const basePath = normalizeNetdiskPath(String(data.base_path || '/'))
      const currentPath = clampNetdiskPathToBase(String(data.dir_path || basePath), basePath)
      const items = ((data.items || []) as DriveBrowseItem[]).map((item) => ({
        name: String(item.name || ''),
        path: joinNetdiskPath(currentPath, String(item.name || '')),
        is_dir: Boolean(item.is_dir),
        updated_at: item.updated_at,
        size: item.size ?? null,
      }))
      const rawPaths = ((data.paths || []) as DriveBrowsePath[]).map((item, idx, arr) => ({
        name: String(item.name || ''),
        path: clampNetdiskPathToBase(`/${arr.slice(0, idx + 1).map((part) => String(part.name || '')).filter(Boolean).join('/')}`, basePath),
      }))
      const paths = rawPaths.filter((item) => item.path !== basePath)
      pathPicker.basePath = basePath
      pathPicker.dirPath = currentPath
      pathPicker.exists = Boolean(data.exists)
      pathPicker.paths = paths
      pathPicker.items = items
      sortPickerItems(pathPicker.sortBy, pathPicker.sortOrder)
      return
    }
    pathPicker.basePath = '/'
    const data = await browseLocalSync({ path: normalizeLocalRelative(pathPicker.dirPath), max_items: 500 })
    pathPicker.dirPath = String(data.dir_path || '')
    pathPicker.exists = Boolean(data.exists)
    pathPicker.paths = data.paths || []
    pathPicker.items = data.items || []
    sortPickerItems(pathPicker.sortBy, pathPicker.sortOrder)
  } finally {
    pathPicker.loading = false
  }
}

async function openPathPicker(endpoint: 'source' | 'target') {
  const tp = endpoint === 'source' ? String(drawer.sourceType) : String(drawer.targetType)
  if (tp === 'netdisk' && !endpointAccount(endpoint)) {
    ElMessage.warning('请先选择网盘账号')
    return
  }
  pathPicker.endpoint = endpoint
  pathPicker.endpointType = tp === 'local' ? 'local' : tp === 'netdisk' ? 'netdisk' : 'openlist'
  pathPicker.sortBy = 'file_name'
  pathPicker.sortOrder = 'asc'

  if (pathPicker.endpointType === 'openlist') {
    pathPicker.basePath = '/'
    const current = endpoint === 'source' ? drawer.sourcePath : drawer.targetPath
    pathPicker.dirPath = normalizeOpenListPath(String(current || '/'))
  } else if (pathPicker.endpointType === 'netdisk') {
    const current = endpoint === 'source' ? drawer.sourcePath : drawer.targetPath
    pathPicker.basePath = '/'
    pathPicker.dirPath = normalizeNetdiskPath(String(current || '/'))
  } else {
    pathPicker.basePath = '/'
    const current = endpoint === 'source' ? drawer.sourcePath : drawer.targetPath
    pathPicker.dirPath = normalizeLocalRelative(String(current || ''))
  }

  pathPicker.visible = true
  await refreshPathPicker()
}

async function enterPickerDir(item: PathBrowseItem) {
  if (!item.is_dir) return
  pathPicker.dirPath = String(item.path || '')
  await refreshPathPicker()
}

async function pickCrumb(path: string) {
  pathPicker.dirPath = String(path || '')
  await refreshPathPicker()
}

function useCurrentPickerPath(withTaskname: boolean) {
  let base = String(pathPicker.dirPath || '').trim()
  if (pathPicker.endpointType === 'openlist') base = normalizeOpenListPath(base)
  else if (pathPicker.endpointType === 'netdisk') base = clampNetdiskPathToBase(base, currentNetdiskBasePath())
  else base = normalizeLocalRelative(base)

  if (pathPicker.endpointType === 'local' && !base) {
    ElMessage.warning('本地路径需要选择 data/sync 下的子目录')
    return
  }

  let finalPath = base
  if (withTaskname) {
    const n = sanitizeFolderName(drawer.name)
    if (n) {
      if (pathPicker.endpointType === 'netdisk') finalPath = joinNetdiskPath(base, n)
      else finalPath = (base ? `${base}/${n}` : n).replace(/\/+/g, '/')
    }
  }

  if (pathPicker.endpoint === 'source') drawer.sourcePath = finalPath
  else drawer.targetPath = finalPath
  pathPicker.visible = false
}

async function pickerGoRoot() {
  pathPicker.dirPath = pathPicker.endpointType === 'local' ? '' : pathPicker.endpointType === 'netdisk' ? currentNetdiskBasePath() : '/'
  await refreshPathPicker()
}

async function pickerGoBack() {
  if (pathPicker.endpointType === 'openlist' || pathPicker.endpointType === 'netdisk') {
    const p = pathPicker.endpointType === 'netdisk' ? clampNetdiskPathToBase(pathPicker.dirPath, currentNetdiskBasePath()) : normalizeOpenListPath(pathPicker.dirPath)
    const rootPath = pathPicker.endpointType === 'netdisk' ? currentNetdiskBasePath() : '/'
    if (p === rootPath || !p) {
      await pickerGoRoot()
      return
    }
    const segs = p.split('/').filter(Boolean)
    segs.pop()
    const nextPath = segs.length ? `/${segs.join('/')}` : rootPath
    pathPicker.dirPath = pathPicker.endpointType === 'netdisk' ? clampNetdiskPathToBase(nextPath, rootPath) : nextPath
    await refreshPathPicker()
    return
  }
  const rel = normalizeLocalRelative(pathPicker.dirPath)
  if (!rel) {
    await pickerGoRoot()
    return
  }
  const segs = rel.split('/').filter(Boolean)
  segs.pop()
  pathPicker.dirPath = segs.join('/')
  await refreshPathPicker()
}

async function syncNetdiskEndpointPath(endpoint: 'source' | 'target') {
  const account = endpointAccount(endpoint)
  if (!account) return
  const current = endpoint === 'source' ? drawer.sourcePath : drawer.targetPath
  const data = await browseNetdiskSync({
    dir_path: normalizeNetdiskPath(String(current || '/')),
    account_name: account.name,
    max_items: 1,
  })
  const basePath = normalizeNetdiskPath(String(data.base_path || '/'))
  const normalizedPath = clampNetdiskPathToBase(String(current || basePath), basePath)
  if (endpoint === 'source') drawer.sourcePath = normalizedPath
  else drawer.targetPath = normalizedPath
  if (pathPicker.visible && pathPicker.endpoint === endpoint && pathPicker.endpointType === 'netdisk') {
    pathPicker.basePath = basePath
    pathPicker.dirPath = normalizedPath
  }
}

function modeText(mode: string) {
  return mode === 'two_way' ? '双向' : '单向'
}

function lastExecution(taskId: number) {
  const list = executionsMap.value.get(taskId) || []
  if (!list.length) return null
  return [...list].sort((a, b) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || '')))[0] || null
}

function isDbRunning(taskId: number) {
  const exe = lastExecution(taskId)
  return Boolean(exe && String(exe.status || '') === 'running' && !exe.finished_at)
}

function isDbAborting(taskId: number) {
  const exe = lastExecution(taskId)
  if (!exe) return false
  if (String(exe.status || '') !== 'running' || exe.finished_at) return false
  return String(exe.stage || '') === 'aborting' || Boolean((exe as any).cancel_requested_at)
}

function anyTaskRunning() {
  return runLogDialog.status === 'running' && runLogDialog.syncTaskId > 0
}

function stopStatusPoll() {
  if (statusPollTimer) {
    clearTimeout(statusPollTimer)
    statusPollTimer = null
  }
  statusPollInFlight = false
}

async function refreshRunningStatuses() {
  const ids = tasks.value.filter((t) => isDbRunning(t.id)).map((t) => t.id)
  if (!ids.length) return
  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        const exe = await fetchSyncExecutionLatest(id, { max_log_chars: 200 })
        return { id, exe }
      } catch {
        return { id, exe: null as any }
      }
    }),
  )

  const next = new Map(executionsMap.value)
  for (const { id, exe } of results) {
    if (!exe) continue
    const list = [...(next.get(id) || [])]
    const idx = list.findIndex((x) => Number(x?.id) === Number(exe.id))
    if (idx >= 0) list.splice(idx, 1, exe)
    else list.unshift(exe)
    next.set(id, list)
  }
  executionsMap.value = next
}

function startStatusPoll() {
  stopStatusPoll()
  statusPollDelayMs = 3000

  const computeNextDelay = (costMs: number) => {
    let base = 3000
    if (runLogController) base = 8000

    let next = base
    if (costMs >= 4000) next = 10000
    else if (costMs >= 2500) next = 8000
    else if (costMs >= 1500) next = 5000
    return Math.max(base, next)
  }

  const schedule = (delayMs: number) => {
    if (statusPollTimer) clearTimeout(statusPollTimer)
    statusPollDelayMs = delayMs
    statusPollTimer = setTimeout(tick, delayMs)
  }

  const tick = async () => {
    if (statusPollInFlight) return schedule(Math.max(statusPollDelayMs, 3000))
    if (!tasks.value.some((t) => isDbRunning(t.id))) return stopStatusPoll()

    statusPollInFlight = true
    const t0 = Date.now()
    try {
      await refreshRunningStatuses()
    } finally {
      statusPollInFlight = false
    }

    const cost = Date.now() - t0
    schedule(computeNextDelay(cost))
  }

  schedule(runLogController ? 3000 : 1500)
}

watch(
  () => tasks.value.map((t) => `${t.id}:${isDbRunning(t.id) ? '1' : '0'}`).join(','),
  () => {
    const hasRunning = tasks.value.some((t) => isDbRunning(t.id))
    if (hasRunning) startStatusPoll()
    else stopStatusPoll()
  },
)

async function stopTask(row: SyncTaskItem) {
  if (!isDbRunning(row.id) || isDbAborting(row.id)) return
  const exe = lastExecution(row.id)
  const executionId = Number(exe?.id) || 0
  if (!executionId) return
  await cancelSyncExecution(row.id, executionId, { message: '用户停止' })
  await loadData()
}

async function confirmStopTask(row: SyncTaskItem) {
  if (!isDbRunning(row.id) || isDbAborting(row.id)) return
  await ElMessageBox.confirm(`确定停止正在运行的同步任务「${row.name}」？`, '停止确认', { type: 'warning' })
  await stopTask(row)
  ElMessage.success('已请求停止')
}

async function loadData() {
  loading.value = true
  try {
    const [data, taskRows, pluginRows, accountRows] = await Promise.all([
      fetchSyncTasks(),
      fetchTasks().catch(() => [] as TaskItem[]),
      fetchSyncPlugins().catch(() => [] as PluginItem[]),
      fetchDriveAccounts().catch(() => [] as DriveAccountItem[]),
    ])
    tasks.value = data
    dramaTasks.value = (taskRows || []).filter((t) => String(t.task_type || '') === 'drama')
    plugins.value = pluginRows || []
    driveAccounts.value = accountRows || []
    const mapping = new Map<number, SyncExecutionItem[]>()
    await Promise.all(
      data.map(async (t) => {
        try {
          const rows = await fetchSyncExecutions(t.id)
          mapping.set(t.id, rows || [])
        } catch {
          mapping.set(t.id, [])
        }
      }),
    )
    executionsMap.value = mapping
    const hasRunning = data.some((t) => {
      const list = mapping.get(t.id) || []
      const exe = list.length ? [...list].sort((a, b) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || '')))[0] : null
      return Boolean(exe && String(exe.status || '') === 'running' && !exe.finished_at)
    })
    if (hasRunning) startStatusPoll()
    else stopStatusPoll()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  drawer.visible = true
  drawer.editing = false
  drawer.id = 0
  drawer.name = ''
  drawer.enabled = true
  drawer.mode = 'one_way'
  drawer.sourceType = 'netdisk'
  drawer.sourcePath = '/'
  drawer.sourceAccountId = defaultNetdiskAccountId()
  drawer.targetType = 'netdisk'
  drawer.targetPath = '/'
  drawer.targetAccountId = defaultNetdiskAccountId()
  drawer.dramaTaskUids = []
  drawer.addition = {}
  drawer.overwrite = false
  drawer.one_way_delete_extras = false
  drawer.force_refresh = true
  drawer.concurrency = 4
  drawer.request_interval_seconds = 1
  drawer.openlist_copy_batch_size = 10
  syncDrawerAddition({})
}

function openEdit(row: SyncTaskItem) {
  drawer.visible = true
  drawer.editing = true
  drawer.id = row.id
  drawer.name = row.name
  drawer.enabled = Boolean(row.enabled)
  drawer.mode = row.mode
  drawer.sourceType = row.source.type
  drawer.sourcePath = row.source.path
  drawer.sourceAccountId = row.source.account_id ?? null
  drawer.targetType = row.target.type
  drawer.targetPath = row.target.path
  drawer.targetAccountId = row.target.account_id ?? null
  drawer.dramaTaskUids = [...(row.drama_task_uids || [])]
  drawer.addition = clone((row as any).addition || {})
  drawer.overwrite = Boolean(row.strategy?.overwrite)
  drawer.one_way_delete_extras = Boolean(row.strategy?.one_way_delete_extras)
  drawer.force_refresh = Boolean(row.strategy?.force_refresh)
  drawer.concurrency = Number(row.strategy?.concurrency ?? 4) || 4
  drawer.request_interval_seconds = Number(row.strategy?.request_interval_seconds ?? 0) || 0
  drawer.openlist_copy_batch_size = Number(row.strategy?.openlist_copy_batch_size ?? 10) || 10
  syncDrawerAddition(drawer.addition)
}

function syncDrawerAddition(value: any) {
  const base: any = value && typeof value === 'object' && !Array.isArray(value) ? clone(value) : {}
  for (const plugin of activePlugins.value) {
    const key = plugin.plugin_key
    const defaultCfg = clone(plugin.default_task_config || {})
    const currentCfg: any = base[key]
    if (!currentCfg || typeof currentCfg !== 'object' || Array.isArray(currentCfg)) {
      base[key] = defaultCfg
      continue
    }
    for (const [k, v] of Object.entries(defaultCfg)) {
      if (!(k in currentCfg)) currentCfg[k] = clone(v)
    }
    for (const field of plugin.task_config_fields || []) {
      const fieldKey = String((field as any).key || '').trim()
      if (!fieldKey) continue
      if (fieldKey in currentCfg) continue
      if ((field as any).default !== undefined) currentCfg[fieldKey] = clone((field as any).default)
    }
  }
  drawer.addition = base
}

async function submitDrawer() {
  if (!drawer.name.trim()) {
    ElMessage.error('请输入任务名称')
    return
  }
  if (
    (isNetdiskType(drawer.sourceType) && isOpenListType(drawer.targetType)) ||
    (isOpenListType(drawer.sourceType) && isNetdiskType(drawer.targetType))
  ) {
    ElMessage.error('暂不支持网盘与 OpenList 混合同步')
    return
  }
  if (isNetdiskType(drawer.sourceType) && !drawer.sourceAccountId) {
    ElMessage.error('请选择源网盘账号')
    return
  }
  if (isNetdiskType(drawer.targetType) && !drawer.targetAccountId) {
    ElMessage.error('请选择目标网盘账号')
    return
  }
  submitting.value = true
  try {
    const payload = {
      name: drawer.name.trim(),
      enabled: Boolean(drawer.enabled),
      mode: drawer.mode,
      source: {
        type: String(drawer.sourceType),
        path: String(drawer.sourcePath || ''),
        account_id: isNetdiskType(drawer.sourceType) ? Number(drawer.sourceAccountId) || null : null,
      },
      target: {
        type: String(drawer.targetType),
        path: String(drawer.targetPath || ''),
        account_id: isNetdiskType(drawer.targetType) ? Number(drawer.targetAccountId) || null : null,
      },
      drama_task_uids: [...(drawer.dramaTaskUids || [])],
      addition: clone(drawer.addition || {}),
      strategy: {
        overwrite: Boolean(drawer.overwrite),
        one_way_delete_extras: Boolean(drawer.one_way_delete_extras),
        force_refresh: Boolean(drawer.force_refresh),
        concurrency: Number(drawer.concurrency) || 1,
        request_interval_seconds: Number(drawer.request_interval_seconds) || 0,
        openlist_copy_batch_size: Number(drawer.openlist_copy_batch_size) || 10,
      },
    }
    if (drawer.editing && drawer.id > 0) {
      await updateSyncTask(drawer.id, payload)
      ElMessage.success('已保存')
    } else {
      await createSyncTask(payload)
      ElMessage.success('已创建')
    }
    drawer.visible = false
    await loadData()
  } finally {
    submitting.value = false
  }
}

async function confirmDelete(row: SyncTaskItem) {
  await ElMessageBox.confirm(`确定删除同步任务「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteSyncTask(row.id)
  ElMessage.success('已删除')
  await loadData()
}

function parseSseBlock(block: string) {
  const lines = block.split('\n')
  let eventType = ''
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith('event:')) eventType = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  return { eventType, dataStr: dataLines.join('\n') }
}

function appendRunLine(text: string) {
  runLogDialog.content += `${text}\n`
  scrollRunLogToBottom()
}

function scrollRunLogToBottom() {
  nextTick(() => {
    const el = runLogPre.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

watch(
  () => runLogDialog.visible,
  (v) => {
    if (v) scrollRunLogToBottom()
  },
)

watch(
  () => runLogDialog.content,
  () => {
    if (!runLogDialog.visible) return
    scrollRunLogToBottom()
  },
)

function resetRunFileStats() {
  runFileStats.total_files = 0
  runFileStats.done_files = 0
  runFileStats.copied_files = 0
  runFileStats.deleted_files = 0
  runFileStats.skipped_files = 0
  runFileStats.failed_files = 0
  runFilePage.loading = false
  runFilePage.total = 0
  runFilePage.page = 1
  runFilePage.items = []
  runFilePage.executionId = 0
  runFileLiveItems.value = []
  runFileTreeExpandedKeys.value = []
}

function mapRunFileRow(row: SyncExecutionFileItem | SyncFileEvent | any): SyncFileEvent {
  return {
    ts: String(row?.updated_at || row?.created_at || row?.ts || ''),
    action: String(row?.action || ''),
    status: String(row?.status || ''),
    path: String(row?.path || ''),
    size: row?.size != null ? Number(row.size) : undefined,
    message: row?.message != null ? String(row.message) : undefined,
  }
}

function updateRunFilePageEvent(item: SyncFileEvent) {
  const key = String(item.path || '')
  if (!key) return
  const idx = runFilePage.items.findIndex((row) => String(row.path || '') === key)
  if (idx < 0) return
  const prev = runFilePage.items[idx]
  runFilePage.items.splice(idx, 1, {
    ...prev,
    ...item,
    size: item.size === undefined ? prev.size : item.size,
    message: item.message === undefined ? prev.message : item.message,
  })
}

function upsertRunFileLiveEvent(item: SyncFileEvent) {
  const key = String(item.path || '')
  if (!key) return
  const rows = [...runFileLiveItems.value]
  const idx = rows.findIndex((row) => String(row.path || '') === key)
  if (idx < 0) {
    rows.unshift(item)
    runFileLiveItems.value = rows.slice(0, 200)
    return
  }
  const prev = rows[idx]
  rows.splice(idx, 1)
  rows.unshift({
    ...prev,
    ...item,
    size: item.size === undefined ? prev.size : item.size,
    message: item.message === undefined ? prev.message : item.message,
  })
  runFileLiveItems.value = rows.slice(0, 200)
}

function applyStatsObject(stats: any) {
  if (!stats || typeof stats !== 'object') return
  if (stats.total_files != null) runFileStats.total_files = Number(stats.total_files) || 0
  if (stats.done_files != null) runFileStats.done_files = Number(stats.done_files) || 0
  if (stats.copied_files != null) runFileStats.copied_files = Number(stats.copied_files) || 0
  if (stats.deleted_files != null) runFileStats.deleted_files = Number(stats.deleted_files) || 0
  if (stats.skipped_files != null) runFileStats.skipped_files = Number(stats.skipped_files) || 0
  if (stats.failed_files != null) runFileStats.failed_files = Number(stats.failed_files) || 0
}

function applyProgressPayload(payload: any) {
  if (!payload || typeof payload !== 'object') return
  if (payload.total_files != null) runFileStats.total_files = Number(payload.total_files) || 0
  if (payload.done_files != null) runFileStats.done_files = Number(payload.done_files) || 0
  if (payload.copied_files != null) runFileStats.copied_files = Number(payload.copied_files) || 0
  if (payload.deleted_files != null) runFileStats.deleted_files = Number(payload.deleted_files) || 0
  if (payload.skipped_files != null) runFileStats.skipped_files = Number(payload.skipped_files) || 0
  if (payload.failed_files != null) runFileStats.failed_files = Number(payload.failed_files) || 0

  const evt = payload.event
  if (evt && typeof evt === 'object') {
    const item = mapRunFileRow(evt)
    if (item.path) {
      upsertRunFileLiveEvent(item)
      updateRunFilePageEvent(item)
    }
  }
}

function mergeExecutionSnapshot(syncTaskId: number, exe: SyncExecutionItem | null | undefined) {
  if (!exe || !syncTaskId) return
  const next = new Map(executionsMap.value)
  const list = [...(next.get(syncTaskId) || [])]
  const idx = list.findIndex((x) => Number(x?.id) === Number(exe.id))
  if (idx >= 0) list.splice(idx, 1, exe)
  else list.unshift(exe)
  list.sort((a, b) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || '')))
  next.set(syncTaskId, list)
  executionsMap.value = next
}

async function loadExecutionFilesPage(syncTaskId: number, executionId: number, options?: { resetPage?: boolean }) {
  if (!syncTaskId || !executionId) {
    runFilePage.items = []
    runFilePage.total = 0
    runFilePage.executionId = 0
    return
  }

  if (options?.resetPage) runFilePage.page = 1

  const requestSeq = ++runFilePageRequestSeq
  runFilePage.loading = true
  try {
    const offset = Math.max(0, (Number(runFilePage.page) - 1) * Number(runFilePage.pageSize))
    const data = await fetchSyncExecutionFiles(syncTaskId, executionId, {
      offset,
      limit: Number(runFilePage.pageSize) || 100,
    })
    if (requestSeq !== runFilePageRequestSeq) return

    const total = Number(data?.total) || 0
    const size = Number(data?.limit) || Number(runFilePage.pageSize) || 100
    const maxPage = total > 0 ? Math.ceil(total / size) : 1
    if (runFilePage.page > maxPage) {
      runFilePage.page = maxPage
      return await loadExecutionFilesPage(syncTaskId, executionId)
    }

    runFilePage.total = total
    runFilePage.executionId = executionId
    runFilePage.items = Array.isArray(data?.items) ? data.items.map((row) => mapRunFileRow(row)).filter((row) => row.path) : []
  } finally {
    if (requestSeq === runFilePageRequestSeq) runFilePage.loading = false
  }
}

async function refreshLatestExecution(syncTaskId: number, options?: { minStartedAt?: string }) {
  const exe = await fetchSyncExecutionLatest(syncTaskId, {
    max_log_chars: 200000,
    min_started_at: options?.minStartedAt || undefined,
  })
  if (!exe) return null
  mergeExecutionSnapshot(syncTaskId, exe)
  runLogDialog.status = String(exe.status || '')
  runLogDialog.stage = String(exe.stage || '')
  runLogDialog.message = String(exe.message || '')
  runLogDialog.startedAt = String(exe.started_at || '')
  runLogDialog.executionId = Number(exe.id) || 0
  if (exe.run_log) runLogDialog.content = String(exe.run_log || '')
  applyStatsObject(exe.stats)
  if (exe.id) {
    const currentExecutionId = Number(exe.id) || 0
    const needResetPage = currentExecutionId !== Number(runFilePage.executionId || 0)
    await loadExecutionFilesPage(syncTaskId, currentExecutionId, { resetPage: needResetPage })
  }
  return exe
}

async function recoverRunDialogFromBackend(syncTaskId: number) {
  const minStartedAt = String(runLogDialog.startedAt || '')
  const exe = await refreshLatestExecution(syncTaskId, {
    minStartedAt: minStartedAt || undefined,
  }).catch(() => null)
  if (!exe) return false
  const status = String(exe.status || '')
  if (status === 'running' && !exe.finished_at) {
    runLogDialog.status = 'running'
    runLogDialog.message = String(exe.message || '')
    startRunPoll(syncTaskId)
    return true
  }
  return false
}

function stopRunPoll() {
  if (runPollTimer) {
    clearTimeout(runPollTimer)
    runPollTimer = null
  }
  runPollInFlight = false
}

function startRunPoll(syncTaskId: number) {
  stopRunPoll()
  runPollDelayMs = 3000

  const schedule = (delayMs: number) => {
    if (runPollTimer) clearTimeout(runPollTimer)
    runPollTimer = setTimeout(async () => {
      if (!runLogDialog.visible) return
      if (runLogDialog.syncTaskId !== syncTaskId) return
      if (runLogController) return schedule(5000)
      if (runPollInFlight) return schedule(runPollDelayMs)

      runPollInFlight = true
      const t0 = Date.now()
      const exe = await refreshLatestExecution(syncTaskId).catch(() => null)
      const cost = Date.now() - t0
      runPollInFlight = false

      if (!runLogDialog.visible) return
      if (runLogDialog.syncTaskId !== syncTaskId) return

      if (exe && String(exe.status || '') !== 'running') {
        stopRunPoll()
        await loadData()
        return
      }

      let nextDelay = 3000
      if (cost >= 2500) nextDelay = 10000
      else if (cost >= 1500) nextDelay = 8000
      else if (cost >= 800) nextDelay = 5000
      runPollDelayMs = nextDelay
      schedule(nextDelay)
    }, delayMs)
  }

  schedule(0)
}

const runFileTreeData = computed(() => {
  const allPaths = runFileDisplayItems.value.map((e) => String(e.path || '')).filter(Boolean)
  const allLocal = allPaths.length > 0 && allPaths.every((p) => p === 'data/sync' || p.startsWith('data/sync/'))
  const rootLabel = allLocal ? '/data/sync' : '/'
  const stripPrefix = allLocal ? 'data/sync/' : ''

  const root: any[] = []
  const dirMap = new Map<string, any>()

  function ensureDir(path: string) {
    const key = path || rootLabel
    const hit = dirMap.get(key)
    if (hit) return hit
    const label = !path ? rootLabel : path.split('/').filter(Boolean).pop() || path
    const node = { key: `dir:${key}`, kind: 'dir', label, children: [] as any[] }
    dirMap.set(key, node)
    if (!path) {
      root.push(node)
      return node
    }
    const parts = path.split('/').filter(Boolean)
    parts.pop()
    const parentPath = parts.join('/')
    const parent = ensureDir(parentPath)
    parent.children.push(node)
    return node
  }

  ensureDir('')

  for (const e of runFileDisplayItems.value) {
    let p = String(e.path || '').replace(/^\/+/, '')
    if (stripPrefix && p.startsWith(stripPrefix)) p = p.slice(stripPrefix.length)
    const segs = p.split('/').filter(Boolean)
    const fileName = segs.pop() || String(e.path || '')
    const dirPath = segs.join('/')
    const dir = ensureDir(dirPath)
    dir.children.push({
      key: `file:${e.path}`,
      kind: 'file',
      label: fileName,
      status: e.status,
    })
  }

  return root
})

watch(
  () => runFileTreeData.value,
  (rows) => {
    const firstKey = (Array.isArray(rows) && rows[0] && (rows[0] as any).key) ? String((rows[0] as any).key) : ''
    if (firstKey && runFileTreeExpandedKeys.value.length === 0) {
      runFileTreeExpandedKeys.value = [firstKey]
    }
    nextTick(() => {
      const tree = runFileTreeRef.value as any
      if (tree && typeof tree.setExpandedKeys === 'function') {
        tree.setExpandedKeys(runFileTreeExpandedKeys.value)
      }
    })
  },
  { deep: true },
)

function onRunFileTreeExpand(data: any) {
  const key = String(data?.key || '')
  if (!key) return
  const set = new Set(runFileTreeExpandedKeys.value)
  set.add(key)
  runFileTreeExpandedKeys.value = Array.from(set)
}

function onRunFileTreeCollapse(data: any) {
  const key = String(data?.key || '')
  if (!key) return
  runFileTreeExpandedKeys.value = runFileTreeExpandedKeys.value.filter((k) => k !== key)
}

async function refreshRunFilePage() {
  const syncTaskId = Number(runLogDialog.syncTaskId) || 0
  const executionId = Number(runLogDialog.executionId || runFilePage.executionId) || 0
  if (!syncTaskId || !executionId) return
  await loadExecutionFilesPage(syncTaskId, executionId)
}

async function onRunFilePageChange(page: number) {
  runFilePage.page = Math.max(1, Number(page) || 1)
  await refreshRunFilePage().catch(() => null)
}

async function onRunFilePageSizeChange(size: number) {
  runFilePage.pageSize = Math.max(20, Number(size) || 100)
  runFilePage.page = 1
  await refreshRunFilePage().catch(() => null)
}

async function onRunLogDialogClosed() {
  stopRunPoll()
  if (runLogController) {
    runLogClosing = true
    runLogController.abort()
    runLogController = null
  }
  await loadData().catch(() => null)
}

async function runSync(row: SyncTaskItem) {
  if (isDbRunning(row.id)) {
    runLogDialog.visible = true
    runLogDialog.title = `执行日志：${row.name}`
    runLogDialog.syncTaskId = row.id
    runLogDialog.executionId = 0
    runLogDialog.status = 'running'
    runLogDialog.stage = ''
    runLogDialog.message = ''
    runLogDialog.startedAt = ''
    resetRunFileStats()
    stopRunPoll()
    await refreshLatestExecution(row.id).catch(() => null)
    startRunPoll(row.id)
    return
  }

  if (anyTaskRunning()) {
    runLogDialog.visible = true
    ElMessage.warning('有同步任务正在执行，请先查看当前执行日志')
    return
  }

  stopRunPoll()
  if (runLogController) runLogController.abort()
  runLogController = new AbortController()
  runLogDialog.visible = true
  runLogDialog.title = `执行日志：${row.name}`
  runLogDialog.status = 'running'
  runLogDialog.stage = ''
  runLogDialog.message = ''
  runLogDialog.content = ''
  runLogDialog.syncTaskId = row.id
  runLogDialog.executionId = 0
  runLogDialog.startedAt = ''
  resetRunFileStats()
  runFileView.value = 'list'

  try {
    const headers: Record<string, string> = {}
    if (auth.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`
    const response = await fetch(`/api/sync-tasks/${row.id}/run/stream`, {
      method: 'POST',
      headers,
      signal: runLogController.signal,
    })
    if (!response.ok) {
      if (response.status === 409) {
        await loadData()
        return await runSync(row)
      }
      if (await recoverRunDialogFromBackend(row.id)) {
        ElMessage.warning('流式连接已中断，已切换为轮询状态')
        return
      }
      const text = await response.text().catch(() => '')
      runLogDialog.status = 'failed'
      runLogDialog.message = text || `HTTP ${response.status}`
      ElMessage.error(runLogDialog.message || '执行失败')
      return
    }
    const reader = response.body?.getReader()
    if (!reader) {
      runLogDialog.status = 'failed'
      runLogDialog.message = '响应不支持流式读取'
      ElMessage.error(runLogDialog.message)
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let loadedOnce = false
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        if (!part.trim()) continue
        const parsed = parseSseBlock(part)
        if (!parsed.eventType) continue
        let data: any = null
        try {
          data = parsed.dataStr ? JSON.parse(parsed.dataStr) : null
        } catch {
          data = null
        }
        if (parsed.eventType === 'init') {
          runLogDialog.status = 'running'
          runLogDialog.startedAt = String(data?.started_at || '')
          if (!loadedOnce) {
            loadedOnce = true
            ;(async () => {
              for (let i = 0; i < 10; i += 1) {
                const exe = await refreshLatestExecution(row.id, {
                  minStartedAt: String(runLogDialog.startedAt || data?.started_at || ''),
                }).catch(() => null)
                if (exe && exe.id) break
                await new Promise((r) => setTimeout(r, 200))
              }
            })()
          }
          continue
        }
        if (parsed.eventType === 'stage') {
          runLogDialog.stage = String(data?.stage || '')
          continue
        }
        if (parsed.eventType === 'log') {
          appendRunLine(String(data?.line ?? ''))
          continue
        }
        if (parsed.eventType === 'progress') {
          applyProgressPayload(data)
          continue
        }
        if (parsed.eventType === 'done') {
          const exe = data?.execution || null
          const eid = Number(exe?.id) || 0
          const status = String(data?.status || '')
          if (status === 'failed' && !eid && await recoverRunDialogFromBackend(row.id)) {
            ElMessage.warning('执行流异常，已切换为轮询状态')
            runLogController = null
            return
          }
          runLogDialog.status = status
          runLogDialog.message = String(data?.message || '')
          if (eid) runLogDialog.executionId = eid
          if (!runLogDialog.stage) {
            const s = String(exe?.stage || '')
            if (s) runLogDialog.stage = s
          }
          if (!String(runLogDialog.content || '').trim()) {
            const full = String(exe?.run_log || '')
            if (full) runLogDialog.content = full
          }
          applyStatsObject(exe?.stats || null)
          if (runLogDialog.status === 'success') ElMessage.success('同步已完成')
          else if (runLogDialog.status === 'aborted') ElMessage.warning(runLogDialog.message || '已停止')
          else ElMessage.error(runLogDialog.message || '同步失败')
          await loadData()
          runLogController = null
          return
        }
      }
    }
    if (runLogDialog.status === 'running') {
      if (await recoverRunDialogFromBackend(row.id)) {
        ElMessage.warning('流式连接已结束，已切换为轮询状态')
        return
      }
      await loadData()
    }
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      if (runLogClosing) return
      return
    }
    if (await recoverRunDialogFromBackend(row.id)) {
      ElMessage.warning('流式连接异常，已切换为轮询状态')
      return
    }
    runLogDialog.status = 'failed'
    runLogDialog.message = e?.message || String(e || '')
    ElMessage.error(runLogDialog.message || '执行失败')
  } finally {
    runLogClosing = false
    if (runLogDialog.status !== 'running') {
      runLogController = null
      runLogDialog.syncTaskId = 0
      runLogDialog.executionId = 0
      runLogDialog.startedAt = ''
    }
  }
}

async function cancelRunTask() {
  if (runLogDialog.status !== 'running') return
  if (String(runLogDialog.stage || '') === 'aborting') return
  const syncTaskId = Number(runLogDialog.syncTaskId) || 0
  const executionId = Number(runLogDialog.executionId || runFilePage.executionId) || 0
  if (!syncTaskId || !executionId) {
    ElMessage.warning('尚未获取执行ID，请稍后再试')
    return
  }
  try {
    await cancelSyncExecution(syncTaskId, executionId, { message: '用户停止' })
    runLogDialog.stage = 'aborting'
    runLogDialog.message = '已请求停止'
    ElMessage.success('已请求停止')
  } catch (e: any) {
    ElMessage.error(e?.message || '停止失败')
  }
}

watch(
  () => drawer.sourceType,
  (tp) => {
    if (tp === 'netdisk') {
      drawer.sourcePath = normalizeNetdiskPath(drawer.sourcePath)
      return
    }
    drawer.sourceAccountId = null
    drawer.sourcePath = tp === 'local' ? normalizeLocalRelative(drawer.sourcePath) : normalizeOpenListPath(drawer.sourcePath)
  },
)

watch(
  () => drawer.targetType,
  (tp) => {
    if (tp === 'netdisk') {
      drawer.targetPath = normalizeNetdiskPath(drawer.targetPath)
      return
    }
    drawer.targetAccountId = null
    drawer.targetPath = tp === 'local' ? normalizeLocalRelative(drawer.targetPath) : normalizeOpenListPath(drawer.targetPath)
  },
)

watch(
  () => drawer.sourceAccountId,
  () => {
    if (drawer.sourceType !== 'netdisk') return
    if (!drawer.sourceAccountId) drawer.sourcePath = '/'
    else syncNetdiskEndpointPath('source').catch(() => null)
    if (pathPicker.visible && pathPicker.endpoint === 'source' && pathPicker.endpointType === 'netdisk') {
      pathPicker.dirPath = normalizeNetdiskPath(drawer.sourcePath || '/')
      refreshPathPicker().catch(() => null)
    }
  },
)

watch(
  () => drawer.targetAccountId,
  () => {
    if (drawer.targetType !== 'netdisk') return
    if (!drawer.targetAccountId) drawer.targetPath = '/'
    else syncNetdiskEndpointPath('target').catch(() => null)
    if (pathPicker.visible && pathPicker.endpoint === 'target' && pathPicker.endpointType === 'netdisk') {
      pathPicker.dirPath = normalizeNetdiskPath(drawer.targetPath || '/')
      refreshPathPicker().catch(() => null)
    }
  },
)

onMounted(loadData)
</script>

<template>
  <div class="section-header">
      <div class="section-header__title">
        <h2>同步任务</h2>
      </div>
      <div class="toolbar__right">
        <el-text class="mx-1" type="primary">注：同步任务由追剧任务运行后自动触发或手动运行</el-text>
        <el-button type="primary" :disabled="!canWrite" @click="openCreate">新建同步任务</el-button>
      </div>
  </div>
  <br>
  <div style="display: flex; flex-direction: column; gap: 12px">
    <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center; justify-content: space-between">
      <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center">
        <el-input v-model="filters.keyword" placeholder="搜索名称/端点" clearable :style="{ width: isMobile ? '100%' : '240px' }" />
        <el-select v-model="filters.enabled" :style="{ width: isMobile ? '100%' : '140px' }">
          <el-option label="全部" value="all" />
          <el-option label="启用" value="enabled" />
          <el-option label="禁用" value="disabled" />
        </el-select>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div v-if="isMobile" style="display: flex; flex-direction: column; gap: 10px">
      <el-card v-for="row in filteredTasks" :key="row.id" shadow="never">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px">
          <div style="min-width: 0">
            <div style="font-size: 15px; font-weight: 600; line-height: 1.2; word-break: break-all">{{ row.name }}</div>
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px">
              <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
              <el-tag :type="row.mode === 'two_way' ? 'warning' : 'info'" effect="plain">{{ modeText(row.mode) }}</el-tag>
            </div>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; align-items: flex-end">
            <el-button
              v-if="canRun"
              size="small"
              text
              bg
              type="primary"
              :disabled="!canRun || (anyTaskRunning() && !isDbRunning(row.id))"
              @click="runSync(row)"
            >
              {{ isDbRunning(row.id) ? '日志' : '执行' }}
            </el-button>
            <el-button
              v-if="canRun && isDbRunning(row.id)"
              size="small"
              text
              bg
              type="danger"
              :disabled="!canRun || isDbAborting(row.id)"
              @click="confirmStopTask(row)"
            >
              {{ isDbAborting(row.id) ? '停止中' : '停止' }}
            </el-button>
          </div>
        </div>

        <div style="margin-top: 10px; display: grid; grid-template-columns: 72px 1fr; row-gap: 8px; column-gap: 10px; font-size: 13px">
          <div style="color: var(--el-text-color-secondary)">源</div>
          <div style="word-break: break-all">{{ endpointText(row.source) }}</div>
          <div style="color: var(--el-text-color-secondary)">目标</div>
          <div style="word-break: break-all">{{ endpointText(row.target) }}</div>
          <div style="color: var(--el-text-color-secondary)">更新时间</div>
          <div>{{ String(row.updated_at || '').slice(0, 19).replace('T', ' ') || '-' }}</div>
        </div>

        <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter)">
          <div style="font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px">最近执行</div>
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
            <template v-if="isDbRunning(row.id)">
              <el-tag type="warning" effect="plain">{{ isDbAborting(row.id) ? '停止中' : '运行中' }}</el-tag>
              <span style="color: var(--el-text-color-secondary)">
                {{ String(lastExecution(row.id)?.started_at || '').slice(0, 19).replace('T', ' ') || '-' }}
              </span>
            </template>
            <template v-else-if="lastExecution(row.id)">
              <el-tag
                :type="lastExecution(row.id)?.status === 'success' ? 'success' : lastExecution(row.id)?.status === 'failed' ? 'danger' : 'info'"
                effect="plain"
              >
                {{ lastExecution(row.id)?.status }}
              </el-tag>
              <span style="color: var(--el-text-color-secondary)">
                {{ String(lastExecution(row.id)?.started_at || '').slice(0, 19).replace('T', ' ') }}
              </span>
            </template>
            <span v-else style="color: var(--el-text-color-secondary)">-</span>
          </div>
        </div>

        <div style="margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap">
          <el-button size="small" text bg :disabled="!canWrite || anyTaskRunning() || isDbRunning(row.id)" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" text bg type="danger" :disabled="!canWrite || anyTaskRunning() || isDbRunning(row.id)" @click="confirmDelete(row)">
            删除
          </el-button>
        </div>
      </el-card>
    </div>

    <el-table v-else :data="filteredTasks" v-loading="loading" row-key="id" stripe>
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column label="启用" width="70">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="模式" width="70">
        <template #default="{ row }">
          <el-tag :type="row.mode === 'two_way' ? 'warning' : 'info'">{{ modeText(row.mode) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="源" min-width="150">
        <template #default="{ row }">
          <span>{{ endpointText(row.source) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="目标" min-width="150">
        <template #default="{ row }">
          <span>{{ endpointText(row.target) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最近执行" min-width="160">
        <template #default="{ row }">
          <template v-if="isDbRunning(row.id)">
            <el-tag type="warning">{{ isDbAborting(row.id) ? '停止中' : '运行中' }}</el-tag>
            <span style="margin-left: 8px; color: var(--el-text-color-secondary)">
              {{ String(lastExecution(row.id)?.started_at || '').slice(0, 19).replace('T', ' ') || '-' }}
            </span>
          </template>
          <template v-else-if="lastExecution(row.id)">
            <el-tag :type="lastExecution(row.id)?.status === 'success' ? 'success' : lastExecution(row.id)?.status === 'failed' ? 'danger' : 'info'">
              {{ lastExecution(row.id)?.status }}
            </el-tag>
            <span style="margin-left: 8px; color: var(--el-text-color-secondary)">{{ String(lastExecution(row.id)?.started_at || '').slice(0, 19).replace('T', ' ') }}</span>
          </template>
          <span v-else style="color: var(--el-text-color-secondary)">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" min-width="160">
        <template #default="{ row }">
          <span>{{ String(row.updated_at || '').slice(0, 19).replace('T', ' ') }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <div style="display: flex; gap: 6px; flex-wrap: wrap">
            <el-button
              size="small"
              type="primary"
              :disabled="!canRun || (anyTaskRunning() && !isDbRunning(row.id))"
              @click="runSync(row)"
            >
              {{ isDbRunning(row.id) ? '查看日志' : '执行' }}
            </el-button>
            <el-button
              v-if="isDbRunning(row.id)"
              size="small"
              type="danger"
              :disabled="!canRun || isDbAborting(row.id)"
              @click="confirmStopTask(row)"
            >
              {{ isDbAborting(row.id) ? '停止中' : '停止' }}
            </el-button>
            <el-button size="small" :disabled="!canWrite || anyTaskRunning() || isDbRunning(row.id)" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" :disabled="!canWrite || anyTaskRunning() || isDbRunning(row.id)" @click="confirmDelete(row)">
              删除
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer.visible" :title="drawer.editing ? '编辑同步任务' : '新建同步任务'" :size="isMobile ? '100%' : '900px'">
      <div style="display: flex; flex-direction: column; gap: 12px">
        <el-form label-position="top">
          <el-form-item label="任务名称">
            <el-input v-model="drawer.name" placeholder="例如：媒体库同步" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="drawer.enabled" />
          </el-form-item>
          <el-form-item label="模式">
            <el-radio-group v-model="drawer.mode">
              <el-radio-button label="one_way">单向</el-radio-button>
              <el-radio-button label="two_way" disabled>双向</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-divider content-position="left">源端点</el-divider>
          <el-form-item label="类型">
            <el-select v-model="drawer.sourceType" :style="{ width: isMobile ? '100%' : '180px' }">
              <el-option label="OpenList" value="openlist" :disabled="isTypeOptionDisabled('source', 'openlist')" />
              <el-option label="本地" value="local" />
              <el-option label="网盘" value="netdisk" :disabled="isTypeOptionDisabled('source', 'netdisk')" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="drawer.sourceType === 'netdisk'" label="网盘账号">
            <el-select v-model="drawer.sourceAccountId" filterable clearable placeholder="选择源网盘账号" style="width: 100%">
              <el-option v-for="item in availableNetdiskAccounts" :key="item.id" :label="`${item.name} (${item.drive_type})`" :value="item.id" />
            </el-select>
            <div style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 6px">仅允许选择该账号 302_path 下的目录。</div>
          </el-form-item>
          <el-form-item label="路径">
            <el-input
              v-model="drawer.sourcePath"
              :placeholder="drawer.sourceType === 'netdisk' ? '网盘: /目录路径' : drawer.sourceType === 'local' ? '相对 data/sync 的路径' : 'OpenList: /xxx'"
            >
              <template #append>
                <el-button @click="openPathPicker('source')">选择</el-button>
              </template>
            </el-input>
          </el-form-item>

          <el-divider content-position="left">目标端点</el-divider>
          <el-form-item label="类型">
            <el-select v-model="drawer.targetType" :style="{ width: isMobile ? '100%' : '180px' }">
              <el-option label="OpenList" value="openlist" :disabled="isTypeOptionDisabled('target', 'openlist')" />
              <el-option label="本地" value="local" />
              <el-option label="网盘" value="netdisk" :disabled="isTypeOptionDisabled('target', 'netdisk')" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="drawer.targetType === 'netdisk'" label="网盘账号">
            <el-select v-model="drawer.targetAccountId" filterable clearable placeholder="选择目标网盘账号" style="width: 100%">
              <el-option v-for="item in availableNetdiskAccounts" :key="item.id" :label="`${item.name} (${item.drive_type})`" :value="item.id" />
            </el-select>
            <div style="color: var(--el-text-color-secondary); font-size: 12px; margin-top: 6px">仅允许选择该账号 302_path 下的目录。</div>
          </el-form-item>
          <el-form-item label="路径">
            <el-input
              v-model="drawer.targetPath"
              :placeholder="drawer.targetType === 'netdisk' ? '网盘: /目录路径' : drawer.targetType === 'local' ? '相对 data/sync 的路径' : 'OpenList: /xxx'"
            >
              <template #append>
                <el-button @click="openPathPicker('target')">选择</el-button>
              </template>
            </el-input>
          </el-form-item>

          <el-divider content-position="left">关联追剧任务</el-divider>
          <el-form-item label="追剧任务">
            <template v-if="isMobile">
              <el-select v-model="drawer.dramaTaskUids" multiple filterable clearable style="width: 100%" placeholder="选择追剧任务">
                <el-option v-for="t in dramaTasks" :key="t.task_uid" :label="t.taskname" :value="t.task_uid" :disabled="!t.enabled" />
              </el-select>
            </template>
            <template v-else>
              <div style="overflow-x: auto">
                <el-transfer
                  v-model="drawer.dramaTaskUids"
                  :data="dramaTransferData"
                  filterable
                  filter-placeholder="搜索追剧任务"
                  :titles="['可选', '已关联']"
                  :style="transferStyle"
                />
              </div>
            </template>
          </el-form-item>

          <el-divider content-position="left">策略</el-divider>
          <el-form-item label="覆盖模式">
            <el-switch v-model="drawer.overwrite" />
          </el-form-item>
          <el-form-item label="单向删除多余文件">
            <el-switch v-model="drawer.one_way_delete_extras" />
          </el-form-item>
          <el-form-item label="强制刷新目录">
            <el-switch v-model="drawer.force_refresh" />
          </el-form-item>
          <el-form-item label="并发数量（Local<->Local同步使用）">
            <el-input-number v-model="drawer.concurrency" :min="1" :max="32" :style="{ width: isMobile ? '100%' : '' }" />
          </el-form-item>
          <el-form-item label="请求间隔秒">
            <el-input-number v-model="drawer.request_interval_seconds" :min="0" :max="5" :step="0.1" :style="{ width: isMobile ? '100%' : '' }" />
          </el-form-item>
          <el-form-item label="OpenList copy 批量大小">
            <el-input-number v-model="drawer.openlist_copy_batch_size" :min="1" :max="5000" :step="50" :style="{ width: isMobile ? '100%' : '' }" />
          </el-form-item>

          <el-divider content-position="left">插件选项（同步任务）</el-divider>
          <div v-if="!activePlugins.length" style="color: var(--el-text-color-secondary); margin-bottom: 12px">暂无同步插件。</div>
          <div v-else style="display: flex; flex-direction: column; gap: 10px">
            <div v-for="plugin in activePlugins" :key="plugin.plugin_key" style="border: 1px solid var(--el-border-color); border-radius: 8px; padding: 10px 12px">
              <div style="font-weight: 600; margin-bottom: 6px">{{ plugin.plugin_key }}</div>
              <el-form-item v-for="field in plugin.task_config_fields || []" :key="field.key" :label="field.label || field.key">
                <el-switch
                  v-if="field.input_type === 'switch'"
                  v-model="drawer.addition[plugin.plugin_key][field.key]"
                  active-text="开启"
                  inactive-text="关闭"
                />
                <el-input-number
                  v-else-if="field.input_type === 'number'"
                  v-model="drawer.addition[plugin.plugin_key][field.key]"
                  style="width: 100%"
                />
                <el-input
                  v-else-if="field.input_type === 'textarea'"
                  v-model="drawer.addition[plugin.plugin_key][field.key]"
                  type="textarea"
                  :rows="field.secret ? 4 : 3"
                  :placeholder="field.placeholder || ''"
                />
                <el-input
                  v-else
                  v-model="drawer.addition[plugin.plugin_key][field.key]"
                  :type="field.input_type === 'password' ? 'password' : 'text'"
                  :placeholder="field.placeholder || ''"
                  :show-password="field.input_type === 'password'"
                />
                <div v-if="field.description" style="color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.4; margin-top: 6px">
                  {{ field.description }}
                </div>
              </el-form-item>
            </div>
          </div>
        </el-form>

        <div style="display: flex; gap: 10px; justify-content: flex-end">
          <el-button @click="drawer.visible = false">取消</el-button>
          <el-button type="primary" :loading="submitting" :disabled="!canWrite" @click="submitDrawer">保存</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="pathPicker.visible" title="选择目录" :width="dialogWidth" :top="dialogTop" :fullscreen="isMobile">
      <div style="margin-bottom: 12px">
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
          <el-button :loading="pathPicker.loading" @click="refreshPathPicker">刷新</el-button>
          <el-button @click="pickerGoRoot">根目录</el-button>
          <el-button v-if="pathPicker.paths.length" @click="pickerGoBack">返回上级</el-button>
          <el-button type="primary" @click="useCurrentPickerPath(false)">使用当前文件夹</el-button>
          <el-button v-if="drawer.name.trim()" type="primary" @click="useCurrentPickerPath(true)">使用当前文件夹/{{ drawer.name.trim() }}</el-button>
          <el-tag type="info">{{
            pathPicker.endpointType === 'openlist' ? 'OpenList' : pathPicker.endpointType === 'netdisk' ? '网盘' : '本地 data/sync'
          }}</el-tag>
          <el-tag v-if="pathPicker.endpointType === 'netdisk' && endpointAccount(pathPicker.endpoint)" type="success">
            {{ endpointAccount(pathPicker.endpoint)?.name }}
          </el-tag>
          <el-tag v-if="pathPicker.endpointType === 'netdisk'" type="warning">
            限制在 {{ currentNetdiskBasePath() }}
          </el-tag>
          <el-tag v-if="!pathPicker.exists" type="danger">不存在</el-tag>
        </div>
        <div style="color: var(--el-text-color-secondary); margin-top: 10px">
          当前路径：{{
            pathPicker.endpointType === 'openlist'
              ? normalizeOpenListPath(pathPicker.dirPath)
              : pathPicker.endpointType === 'netdisk'
                ? clampNetdiskPathToBase(pathPicker.dirPath, currentNetdiskBasePath())
                : pathPicker.dirPath
                  ? `data/sync/${pathPicker.dirPath}`
                  : 'data/sync'
          }}
        </div>
        <el-breadcrumb v-if="pathPicker.paths.length" separator="/" style="margin-top: 10px">
          <el-breadcrumb-item>
            <a href="#" @click.prevent="pickerGoRoot">{{
              pathPicker.endpointType === 'local'
                ? 'data/sync'
                : pathPicker.endpointType === 'netdisk'
                  ? currentNetdiskBasePath()
                  : '/'
            }}</a>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-for="(p, idx) in pathPicker.paths" :key="p.path">
            <a v-if="idx !== pathPicker.paths.length - 1" href="#" @click.prevent="pickCrumb(p.path)">{{ p.name }}</a>
            <span v-else style="color: var(--el-text-color-secondary)">{{ p.name }}</span>
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>

      <el-table
        :data="pathPicker.items"
        v-loading="pathPicker.loading"
        size="small"
        style="width: 100%"
        :height="isMobile ? '60vh' : 420"
        @row-click="enterPickerDir"
        @sort-change="onPickerSortChange"
      >
        <el-table-column prop="name" label="文件名" min-width="360" sortable="custom">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.is_dir" size="small" type="info" style="margin-left: 8px">目录</el-tag>
            <el-tag v-else size="small" type="success" style="margin-left: 8px">文件</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="130">
          <template #default="{ row }">
            <span v-if="row.is_dir">-</span>
            <span v-else>{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="修改日期" width="170" sortable="custom">
          <template #default="{ row }">
            <span>{{ formatTs(row.updated_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog
      v-model="runLogDialog.visible"
      :title="runLogDialog.title"
      :width="dialogWidth"
      :top="dialogTop"
      :fullscreen="isMobile"
      @closed="onRunLogDialogClosed"
    >
      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px">
        <el-tag :type="runLogDialog.status === 'success' ? 'success' : runLogDialog.status === 'failed' ? 'danger' : runLogDialog.status === 'aborted' ? 'warning' : 'info'">
          {{ runLogDialog.status || 'unknown' }}
        </el-tag>
        <span style="color: var(--el-text-color-secondary)">阶段：{{ runLogDialog.stage || '-' }}</span>
        <span style="color: var(--el-text-color-secondary)">结果：{{ runLogDialog.message || '-' }}</span>
        <el-button size="small" :disabled="runLogDialog.status !== 'running' || runLogDialog.stage === 'aborting'" @click="cancelRunTask">停止任务</el-button>
      </div>

      <div :style="runStatsGridStyle">
        <div style="background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 12px">
          <div style="color: var(--el-text-color-secondary); font-size: 12px">总文件</div>
          <div style="font-size: 22px; font-weight: 600">{{ runFileStats.total_files }}</div>
        </div>
        <div style="background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 12px">
          <div style="color: var(--el-text-color-secondary); font-size: 12px">已同步</div>
          <div style="font-size: 22px; font-weight: 600">{{ runFileStats.copied_files + runFileStats.deleted_files }}</div>
        </div>
        <div style="background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 12px">
          <div style="color: var(--el-text-color-secondary); font-size: 12px">已跳过</div>
          <div style="font-size: 22px; font-weight: 600">{{ runFileStats.skipped_files }}</div>
        </div>
        <div style="background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 12px">
          <div style="color: var(--el-text-color-secondary); font-size: 12px">失败</div>
          <div style="font-size: 22px; font-weight: 600">{{ runFileStats.failed_files }}</div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px">
        <div style="color: var(--el-text-color-secondary)">
          {{ runFileStats.done_files }}/{{ runFileStats.total_files }} 文件
          <span v-if="runFilePage.total > 0">，当前显示 {{ runFileDisplayStart }}-{{ runFileDisplayEnd }}</span>
          <span v-else-if="runFileUsingLiveFallback">，当前显示流式实时文件状态</span>
        </div>
        <el-radio-group v-model="runFileView" size="small">
          <el-radio-button label="list">列表</el-radio-button>
          <el-radio-button label="tree">树形</el-radio-button>
        </el-radio-group>
      </div>
      <el-progress :percentage="toPercent(runFileStats.done_files, runFileStats.total_files)" :stroke-width="10" style="margin-bottom: 12px" />

      <div v-if="runFileView === 'list'">
        <el-table v-loading="runFilePage.loading" :data="runFileDisplayItems" size="small" style="width: 100%" :height="runEventsTableHeight">
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'success'" type="success" size="small">OK</el-tag>
              <el-tag v-else-if="row.status === 'syncing'" type="info" size="small">SYNC</el-tag>
              <el-tag v-else-if="row.status === 'pending'" type="info" size="small">PEND</el-tag>
              <el-tag v-else-if="row.status === 'skipped'" type="warning" size="small">SKIP</el-tag>
              <el-tag v-else-if="row.status === 'aborted'" type="warning" size="small">ABRT</el-tag>
              <el-tag v-else type="danger" size="small">FAIL</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="动作" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.action === 'copy'" type="info" size="small">copy</el-tag>
              <el-tag v-else-if="row.action === 'delete'" type="danger" size="small">delete</el-tag>
              <el-tag v-else type="info" size="small">{{ row.action || '-' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="path" label="路径" min-width="360" show-overflow-tooltip />
          <el-table-column label="大小" width="120">
            <template #default="{ row }">
              <span>{{ row.size != null ? formatSize(row.size) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="信息" min-width="160" show-overflow-tooltip />
        </el-table>
      </div>
      <div v-else>
        <div style="color: var(--el-text-color-secondary); font-size: 12px; margin-bottom: 8px">
          {{ runFileUsingLiveFallback ? '树形视图正在展示流式实时文件状态。' : '树形视图展示当前页文件明细。' }}
        </div>
        <el-tree
          ref="runFileTreeRef"
          :data="runFileTreeData"
          v-loading="runFilePage.loading"
          node-key="key"
          :expand-on-click-node="false"
          :default-expanded-keys="runFileTreeExpandedKeys"
          :style="runTreeStyle"
          @node-expand="onRunFileTreeExpand"
          @node-collapse="onRunFileTreeCollapse"
        >
          <template #default="{ data }">
            <span>{{ data.label }}</span>
            <el-tag
              v-if="data.kind === 'file'"
              size="small"
              :type="data.status === 'success' ? 'success' : data.status === 'skipped' || data.status === 'aborted' ? 'warning' : data.status === 'syncing' || data.status === 'pending' ? 'info' : 'danger'"
              style="margin-left: 8px"
            >
              {{
                data.status === 'success'
                  ? 'OK'
                  : data.status === 'skipped'
                    ? 'SKIP'
                    : data.status === 'aborted'
                      ? 'ABRT'
                      : data.status === 'syncing'
                        ? 'SYNC'
                        : data.status === 'pending'
                          ? 'PEND'
                          : 'FAIL'
              }}
            </el-tag>
          </template>
        </el-tree>
      </div>

      <div v-if="runFilePage.total > 0" style="display: flex; justify-content: flex-end; margin-top: 12px">
        <el-pagination
          background
          :current-page="runFilePage.page"
          :page-size="runFilePage.pageSize"
          :page-sizes="[50, 100, 200, 500]"
          :total="runFilePage.total"
          layout="total, sizes, prev, pager, next"
          @current-change="onRunFilePageChange"
          @size-change="onRunFilePageSizeChange"
        />
      </div>

      <el-divider content-position="left">原始日志</el-divider>
      <div
        ref="runLogPre"
        style="
          height: 78px;
          overflow-y: auto;
          padding: 8px 10px;
          border-radius: 8px;
          background: var(--el-fill-color-light);
          border: 1px solid var(--el-border-color-lighter);
        "
      >
        <pre style="margin: 0; font-size: 12px; line-height: 22px; white-space: pre-wrap; word-break: break-word">{{
          runLogDialog.content || ''
        }}</pre>
      </div>
    </el-dialog>
  </div>
</template>
