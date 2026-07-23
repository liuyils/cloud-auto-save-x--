<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelDL302CasTask,
  fetchDL302CasTask,
  fetchDL302CasTaskItems,
  fetchDL302CasTasks,
  fetchDL302Config,
  fetchDL302SupportedDrivers,
  generateDL302Strm,
  patchDL302Config,
  pauseDL302CasTask,
  resumeDL302CasTask,
  submitDL302CasTask,
} from '@/api/dl302'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { DL302CASTask, DL302CASTaskItem, DL302Config, DL302SupportedAccount, DL302SupportedDriver, DL302StrmGenerateResult, ProxyTarget } from '@/types/dl302'
import { formatBytes } from '@/utils/capacity'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const loading = ref(false)
const activeTab = ref('drivers')
const drivers = ref<DL302SupportedDriver[]>([])
const casSubmitting = reactive<Record<number, boolean>>({})
const casTaskLists = reactive<Record<number, DL302CASTask[]>>({})
const casTaskItems = reactive<Record<string, DL302CASTaskItem[]>>({})
const casSelectedTaskId = reactive<Record<number, string>>({})
const casTaskLoading = reactive<Record<number, boolean>>({})
const casItemLoading = reactive<Record<string, boolean>>({})
const casActionLoading = reactive<Record<string, boolean>>({})
const casItemRequestMap = new Map<string, Promise<DL302CASTaskItem[]>>()
const casDialog = reactive({
  visible: false,
  accountId: 0,
  search: '',
  status: 'all',
  page: 1,
  pageSize: 10,
})
let casPollTimer: number | null = null
let casPollInFlight = false

const settings = reactive({
  proxy_url: '',
  proxy_path_offset: -1,
  intranet_cidrs_text: '',
  auto_balance: false,
  cas_root_dir: '',
  cas_workers: 4,
  strm_enabled: false,
  strm_mode: 'auto' as 'auto' | 'independent',
  strm_root_dir: '/strm',
  strm_prefix_url: '',
  strm_include_cas_root_dir: false,
  strm_source_priority: 'video_first' as 'video_first' | 'cas_first',
  savingProxy: false,
  generatingStrm: false,
})

const strmSummary = reactive({
  enabled: false,
  mode: 'auto' as 'auto' | 'independent',
  prefix_ready: false,
  root_exists: false,
  source_account_count: 0,
  path_ready_account_count: 0,
  path_missing_account_count: 0,
  generated_file_count: 0,
  generated_dir_count: 0,
})

// --- Proxy Targets ---
const PROXY_TYPE_OPTIONS = [
  { value: 'fnos', label: '飞牛影视' },
  { value: 'emby', label: 'Emby' },
  { value: 'jellyfin', label: 'Jellyfin' },
  { value: 'generic', label: '通用透传' },
]
const proxyTargets = ref<(ProxyTarget & { _key: number })[]>([])
let proxyTargetKeySeq = 0

function addProxyTarget() {
  proxyTargets.value.push({
    id: '',
    name: '',
    type: 'generic',
    target_url: '',
    listen_addr: '',
    path_offset: 0,
    enabled: true,
    _key: ++proxyTargetKeySeq,
  })
}

function removeProxyTarget(index: number) {
  proxyTargets.value.splice(index, 1)
}

function applyConfig(data: DL302Config) {
  settings.proxy_url = String(data.proxy_url || '')
  settings.proxy_path_offset = Number.isFinite(Number(data.proxy_path_offset)) ? Number(data.proxy_path_offset) : -1
  settings.intranet_cidrs_text = Array.isArray(data.intranet_cidrs) ? data.intranet_cidrs.filter(Boolean).join('\n') : ''
  settings.auto_balance = Boolean(data.auto_balance)
  settings.cas_root_dir = String(data.cas_root_dir || '')
  settings.cas_workers = Number.isFinite(Number(data.cas_workers)) && Number(data.cas_workers) > 0 ? Number(data.cas_workers) : 4
  settings.strm_enabled = Boolean(data.strm_enabled)
  settings.strm_mode = data.strm_mode === 'independent' ? 'independent' : 'auto'
  settings.strm_root_dir = String(data.strm_root_dir || '/strm')
  settings.strm_prefix_url = String(data.strm_prefix_url || '')
  settings.strm_include_cas_root_dir = Boolean(data.strm_include_cas_root_dir)
  settings.strm_source_priority = data.strm_source_priority === 'cas_first' ? 'cas_first' : 'video_first'
  strmSummary.enabled = Boolean(data.strm_summary?.enabled)
  strmSummary.mode = data.strm_summary?.mode === 'independent' ? 'independent' : 'auto'
  strmSummary.prefix_ready = Boolean(data.strm_summary?.prefix_ready)
  strmSummary.root_exists = Boolean(data.strm_summary?.root_exists)
  strmSummary.source_account_count = Number(data.strm_summary?.source_account_count || 0)
  strmSummary.path_ready_account_count = Number(data.strm_summary?.path_ready_account_count || 0)
  strmSummary.path_missing_account_count = Number(data.strm_summary?.path_missing_account_count || 0)
  strmSummary.generated_file_count = Number(data.strm_summary?.generated_file_count || 0)
  strmSummary.generated_dir_count = Number(data.strm_summary?.generated_dir_count || 0)
  // proxy targets
  if (Array.isArray(data.proxy_targets)) {
    proxyTargets.value = data.proxy_targets.map((t) => ({ ...t, _key: ++proxyTargetKeySeq }))
  }
}

async function loadPage() {
  loading.value = true
  try {
    const [driverData, configData] = await Promise.all([fetchDL302SupportedDrivers(), fetchDL302Config()])
    drivers.value = driverData
    applyConfig(configData)
    ensureCasPoller()
  } finally {
    loading.value = false
  }
}

function flattenAccounts() {
  return drivers.value.flatMap((driver) => driver.accounts || [])
}

function updateAccountTask(accountId: number, task: DL302CASTask | null | undefined) {
  for (const driver of drivers.value) {
    const account = (driver.accounts || []).find((item) => item.account_id === accountId)
    if (account) {
      account.cas_task = task || null
      return
    }
  }
}

function currentTask(account: DL302SupportedAccount) {
  return account.cas_task || casTaskLists[account.account_id]?.[0] || null
}

function selectedTask(account: DL302SupportedAccount) {
  const selectedId = casSelectedTaskId[account.account_id]
  if (selectedId) {
    const matched = (casTaskLists[account.account_id] || []).find((item) => item.task_id === selectedId)
    if (matched) return matched
  }
  return currentTask(account)
}

const dialogAccount = computed(() => flattenAccounts().find((item) => item.account_id === casDialog.accountId) || null)
const dialogAccountId = computed(() => dialogAccount.value?.account_id || 0)

const selectedDialogTask = computed(() => {
  const account = dialogAccount.value
  if (!account) return null
  return selectedTask(account)
})

const filteredDialogTaskItems = computed(() => {
  const taskId = selectedDialogTask.value?.task_id || ''
  const keyword = String(casDialog.search || '').trim().toLowerCase()
  const status = String(casDialog.status || 'all')
  return (casTaskItems[taskId] || []).filter((item) => {
    if (status !== 'all' && item.status !== status) return false
    if (!keyword) return true
    return [item.name, item.file_path, item.stage, item.last_error, item.rapid_drive_types]
      .map((value) => String(value || '').toLowerCase())
      .some((value) => value.includes(keyword))
  })
})

const dialogPageCount = computed(() => {
  const total = filteredDialogTaskItems.value.length
  const size = Math.max(1, Number(casDialog.pageSize || 10))
  return Math.max(1, Math.ceil(total / size))
})

const dialogCurrentPage = computed(() => {
  const page = Math.max(1, Number(casDialog.page || 1))
  return Math.min(page, dialogPageCount.value)
})

const pagedDialogTaskItems = computed(() => {
  const start = (dialogCurrentPage.value - 1) * casDialog.pageSize
  return filteredDialogTaskItems.value.slice(start, start + casDialog.pageSize)
})

function casStatusTagType(status?: string | null) {
  if (status === 'done') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  if (status === 'running' || status === 'pending' || status === 'pausing') return 'warning'
  return 'info'
}

function casStatusText(status?: string | null) {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '待执行'
  if (status === 'pausing') return '暂停中'
  if (status === 'paused') return '已暂停'
  if (status === 'done') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已停止'
  return '未创建'
}

function casStatusLabel(account: DL302SupportedAccount) {
  return casStatusText(currentTask(account)?.status || '')
}

function accountCasBasePath(account: DL302SupportedAccount) {
  return String(account.strm_scan_base_path || account.media_base_path || '').trim()
}

function canGenerateCas(account: DL302SupportedAccount) {
  return Boolean(accountCasBasePath(account))
}

function buildCasSummary(account: DL302SupportedAccount) {
  if (!canGenerateCas(account)) return '未配置 STRM 扫描路径。'
  const task = currentTask(account)
  if (!task) return '尚未创建 CAS 任务。'
  const processed = taskProcessedItems(task)
  if (task.status === 'running' || task.status === 'pending' || task.status === 'pausing') {
    return `任务 ${task.task_id.slice(0, 8)} 处理中：已处理 ${processed}/${task.total_items}，字节 ${formatBytes(task.done_bytes)}/${formatBytes(task.total_bytes || 0)}`
  }
  if (task.status === 'paused') return `任务已暂停：已处理 ${processed}/${task.total_items}`
  if (task.status === 'failed') return task.last_error || 'CAS 任务失败。'
  if (task.status === 'cancelled') return `任务已停止：已处理 ${processed}/${task.total_items}`
  if (task.status === 'done') return `任务完成：完成 ${task.done_items}，跳过 ${task.skipped_items}，失败 ${task.failed_items}`
  return '尚未创建 CAS 任务。'
}

function taskProcessedItems(task?: DL302CASTask | null) {
  if (!task) return 0
  return Number(task.done_items || 0) + Number(task.skipped_items || 0) + Number(task.failed_items || 0)
}

function taskProgressText(task?: DL302CASTask | null) {
  if (!task) return '0/0'
  return `${taskProcessedItems(task)}/${task.total_items}`
}

function taskOptionLabel(task: DL302CASTask) {
  return `${task.task_id.slice(0, 8)} · ${casStatusText(task.status)}`
}

function taskPercent(task?: DL302CASTask | null) {
  if (!task || !task.total_items) return 0
  return Math.min(100, Math.round((taskProcessedItems(task) / task.total_items) * 100))
}

function itemPercent(item: DL302CASTaskItem) {
  const total = Number(item.stage_total || item.size || 0)
  const done = Number(item.stage_done || 0)
  if (!total) return done > 0 ? 1 : 0
  return Math.min(100, Math.round((done / total) * 100))
}

function formatStageProgress(item: DL302CASTaskItem) {
  const total = Number(item.stage_total || item.size || 0)
  const done = Number(item.stage_done || 0)
  if (!total) return done > 0 ? formatBytes(done) : '-'
  return `${formatBytes(done)} / ${formatBytes(total)}`
}

function isTaskActive(status?: string | null) {
  return status === 'running' || status === 'pending' || status === 'pausing'
}

function canPauseTask(task?: DL302CASTask | null) {
  if (!task) return false
  return task.status === 'running' || task.status === 'pending'
}

function canResumeTask(task?: DL302CASTask | null) {
  if (!task) return false
  return task.status === 'paused' || task.status === 'failed'
}

function canCancelTask(task?: DL302CASTask | null) {
  if (!task) return false
  return task.status === 'running' || task.status === 'pending' || task.status === 'pausing' || task.status === 'failed' || task.status === 'paused'
}

function itemStatusTagType(status?: string | null) {
  if (status === 'done' || status === 'skipped') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  if (status === 'running') return 'warning'
  return 'info'
}

function itemStatusLabel(status?: string | null) {
  if (status === 'running') return '处理中'
  if (status === 'pending') return '待处理'
  if (status === 'done') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '已跳过'
  if (status === 'cancelled') return '已取消'
  return '未知'
}

async function loadAccountTasks(accountId: number) {
  casTaskLoading[accountId] = true
  try {
    const result = await fetchDL302CasTasks(accountId)
    casTaskLists[accountId] = result.tasks || []
    if (!casSelectedTaskId[accountId] && casTaskLists[accountId]?.length) {
      casSelectedTaskId[accountId] = casTaskLists[accountId][0].task_id
    }
    updateAccountTask(accountId, casTaskLists[accountId]?.[0] || null)
    if (casSelectedTaskId[accountId]) {
      await loadTaskItems(casSelectedTaskId[accountId])
    }
  } finally {
    casTaskLoading[accountId] = false
  }
}

async function loadTaskItems(taskId: string, options: { silent?: boolean } = {}) {
  if (!taskId) return []
  const existing = casItemRequestMap.get(taskId)
  if (existing) {
    return await existing
  }
  casItemLoading[taskId] = true
  let requestPromise: Promise<DL302CASTaskItem[]>
  requestPromise = fetchDL302CasTaskItems(taskId)
    .then((items) => {
      casTaskItems[taskId] = items
      return items
    })
    .catch((error) => {
      if (!options.silent) throw error
      console.warn('[DL302] loadTaskItems failed during polling', taskId, error)
      return casTaskItems[taskId] || []
    })
    .finally(() => {
      if (casItemRequestMap.get(taskId) === requestPromise) {
        casItemRequestMap.delete(taskId)
      }
      casItemLoading[taskId] = false
    })
  casItemRequestMap.set(taskId, requestPromise)
  return await requestPromise
}

async function selectTask(accountId: number, taskId: string) {
  casSelectedTaskId[accountId] = taskId
  casDialog.page = 1
  await loadTaskItems(taskId)
}

function isDialogAccount(accountId: number) {
  return casDialog.visible && casDialog.accountId === accountId
}

async function openTaskDialog(account: DL302SupportedAccount) {
  casDialog.visible = true
  casDialog.accountId = account.account_id
  casDialog.search = ''
  casDialog.status = 'all'
  casDialog.page = 1
  casDialog.pageSize = 10
  await loadAccountTasks(account.account_id)
}

function closeTaskDialog() {
  casDialog.visible = false
}

function handleDialogFilterChange() {
  casDialog.page = 1
}

function handleDialogPageChange(page: number) {
  casDialog.page = page
}

function handleDialogPageSizeChange(size: number) {
  casDialog.pageSize = size
  casDialog.page = 1
}

async function pollRunningCasStatuses() {
  if (casPollInFlight) return
  casPollInFlight = true
  try {
    const targets = flattenAccounts().filter((item) => isTaskActive(currentTask(item)?.status))
    if (!targets.length) {
      await pollSelectedDialogTaskItems()
      stopCasPoller()
      return
    }
    const results = await Promise.all(
      targets.map(async (item) => {
        const task = currentTask(item)
        if (!task?.task_id) return null
        try {
          const latest = await fetchDL302CasTask(task.task_id)
          return { accountId: item.account_id, task: latest }
        } catch {
          return null
        }
      }),
    )
    for (const item of results.filter(Boolean)) {
      updateAccountTask(item!.accountId, item!.task)
      const accountId = item!.accountId
      const taskId = item!.task?.task_id
      if (accountId && casTaskLists[accountId]) {
        casTaskLists[accountId] = casTaskLists[accountId].map((task) => (task.task_id === taskId ? item!.task : task))
        if (casTaskLists[accountId].length && casTaskLists[accountId][0].task_id === taskId) {
          casTaskLists[accountId][0] = item!.task
        }
      }
    }
    await pollSelectedDialogTaskItems()
    if (!flattenAccounts().some((item) => isTaskActive(currentTask(item)?.status))) {
      stopCasPoller()
    }
  } finally {
    casPollInFlight = false
  }
}

async function pollSelectedDialogTaskItems() {
  if (!casDialog.visible) return
  const task = selectedDialogTask.value
  if (!task?.task_id || !isTaskActive(task.status)) return
  await loadTaskItems(task.task_id, { silent: true })
}

function ensureCasPoller() {
  if (!flattenAccounts().some((item) => isTaskActive(currentTask(item)?.status))) {
    stopCasPoller()
    return
  }
  if (casPollTimer !== null) return
  casPollTimer = window.setInterval(() => {
    void pollRunningCasStatuses().catch((error) => {
      console.warn('[DL302] CAS poll failed', error)
    })
  }, 3000)
}

function stopCasPoller() {
  if (casPollTimer !== null) {
    window.clearInterval(casPollTimer)
    casPollTimer = null
  }
}

async function handleGenerateCas(account: DL302SupportedAccount) {
  if (!canWrite.value || !canGenerateCas(account)) return
  let fastCompute = false
  if (account.drive_type === 'cloud139') {
    try {
      await ElMessageBox.confirm(
        '启用后会优先通过云端目录列表返回的 SHA256(contentHash) 生成 CAS，能显著减少下载+本地哈希；拿不到 hash 时会自动回退原流程。',
        '使用快速计算能力？',
        {
          confirmButtonText: '使用快速计算',
          cancelButtonText: '按原方式',
          type: 'warning',
          distinguishCancelAndClose: true,
        },
      )
      fastCompute = true
    } catch {
      fastCompute = false
    }
  }
  casSubmitting[account.account_id] = true
  try {
    const result = await submitDL302CasTask(account.account_id, { fast_compute: fastCompute })
    updateAccountTask(account.account_id, result.task)
    if (isDialogAccount(account.account_id)) {
      await loadAccountTasks(account.account_id)
    }
    ElMessage.success(result.message || 'CAS 任务已提交')
    ensureCasPoller()
  } finally {
    casSubmitting[account.account_id] = false
  }
}

async function handlePauseCas(account: DL302SupportedAccount) {
  const task = currentTask(account)
  if (!task?.task_id || !canWrite.value) return
  casActionLoading[task.task_id] = true
  try {
    const latest = await pauseDL302CasTask(task.task_id)
    updateAccountTask(account.account_id, latest)
    if (isDialogAccount(account.account_id)) await loadAccountTasks(account.account_id)
    ElMessage.success('已请求暂停')
    ensureCasPoller()
  } finally {
    casActionLoading[task.task_id] = false
  }
}

async function handleResumeCas(account: DL302SupportedAccount) {
  const task = currentTask(account)
  if (!task?.task_id || !canWrite.value) return
  casActionLoading[task.task_id] = true
  try {
    const latest = await resumeDL302CasTask(task.task_id)
    updateAccountTask(account.account_id, latest)
    if (isDialogAccount(account.account_id)) await loadAccountTasks(account.account_id)
    ElMessage.success('任务已继续')
    ensureCasPoller()
  } finally {
    casActionLoading[task.task_id] = false
  }
}

async function handleCancelCas(account: DL302SupportedAccount) {
  const task = currentTask(account)
  if (!task?.task_id || !canWrite.value) return
  casActionLoading[task.task_id] = true
  try {
    const latest = await cancelDL302CasTask(task.task_id)
    updateAccountTask(account.account_id, latest)
    if (isDialogAccount(account.account_id)) await loadAccountTasks(account.account_id)
    ElMessage.success('任务已停止')
  } finally {
    casActionLoading[task.task_id] = false
  }
}

watch(
  () => [filteredDialogTaskItems.value.length, casDialog.pageSize],
  () => {
    if (casDialog.page > dialogPageCount.value) {
      casDialog.page = dialogPageCount.value
    }
  },
)

function parseCIDRText(text: string): string[] | null {
  const parts = String(text || '')
    .replaceAll('\r\n', '\n')
    .replaceAll('\n', ',')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
  if (!parts.length) return null
  return Array.from(new Set(parts))
}

async function saveProxySettings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const targets = proxyTargets.value.map(({ _key, ...rest }) => rest)
    const data = await patchDL302Config({
      proxy_url: settings.proxy_url ? String(settings.proxy_url).trim() : null,
      proxy_path_offset: Number(settings.proxy_path_offset),
      intranet_cidrs: parseCIDRText(settings.intranet_cidrs_text),
      auto_balance: Boolean(settings.auto_balance),
      strm_enabled: Boolean(settings.strm_enabled),
      strm_mode: settings.strm_mode,
      strm_root_dir: String(settings.strm_root_dir || '').trim() || '/strm',
      strm_prefix_url: settings.strm_prefix_url ? String(settings.strm_prefix_url).trim() : null,
      strm_include_cas_root_dir: Boolean(settings.strm_include_cas_root_dir),
      strm_source_priority: settings.strm_source_priority,
      proxy_targets: targets.length > 0 ? targets : null,
    })
    applyConfig(data)
    ElMessage.success('反代设置已保存，已触发 dl302 重载')
  } finally {
    settings.savingProxy = false
  }
}

async function saveStrmSettings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const data = await patchDL302Config({
      strm_enabled: Boolean(settings.strm_enabled),
      strm_mode: settings.strm_mode,
      strm_root_dir: String(settings.strm_root_dir || '').trim() || '/strm',
      strm_prefix_url: settings.strm_prefix_url ? String(settings.strm_prefix_url).trim() : null,
      strm_include_cas_root_dir: Boolean(settings.strm_include_cas_root_dir),
      strm_source_priority: settings.strm_source_priority,
    })
    applyConfig(data)
    ElMessage.success('STRM 设置已保存')
  } finally {
    settings.savingProxy = false
  }
}

async function saveDL302Settings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const data = await patchDL302Config({
      auto_balance: Boolean(settings.auto_balance),
    })
    applyConfig(data)
    ElMessage.success('302 设置已保存，已触发 dl302 重载')
  } finally {
    settings.savingProxy = false
  }
}

async function saveCasSettings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const data = await patchDL302Config({
      cas_root_dir: settings.cas_root_dir ? String(settings.cas_root_dir).trim() : null,
      cas_workers: Number(settings.cas_workers) > 0 ? Number(settings.cas_workers) : 4,
    })
    applyConfig(data)
    ElMessage.success('CAS 设置已保存')
  } finally {
    settings.savingProxy = false
  }
}

function buildGenerateMessage(result: DL302StrmGenerateResult) {
  const parts = [
    `模式：${result.mode === 'independent' ? '独立模式' : '自动模式'}`,
    `文件：${result.generated_files}`,
    `目录：${result.generated_dirs}`,
    `跳过账号：${result.skipped_accounts}`,
  ]
  return parts.join('，')
}

async function generateStrm() {
  if (!canWrite.value) return
  settings.generatingStrm = true
  try {
    const result = await generateDL302Strm({
      mode: settings.strm_mode,
      persist_prefix_if_empty: true,
    })
    const latestConfig = await fetchDL302Config()
    applyConfig(latestConfig)
    ElMessage.success(result.message ? `${result.message}，${buildGenerateMessage(result)}` : buildGenerateMessage(result))
  } finally {
    settings.generatingStrm = false
  }
}

onMounted(loadPage)
onUnmounted(stopCasPoller)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>302代理</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadPage">刷新页面</el-button>
      </div>
    </div>

    <section class="glass-panel dashboard-section">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="CAS管理" name="drivers">
          <div class="tab-copy">
            展示当前 dl302 支持的账号驱动及其账号卡片。`生成CAS数据` 会复用账号配置中的 `STRM 扫描路径` 作为扫描目录，仅处理目录缓存里缺少 rapid record
            的视频文件；生成好秒传数据后，会按目录树在本地临时目录生成 `.cas` 文件，并上传到当前账号对应网盘的 `CAS 文件生成目录（网盘目录）`。<br>
            302 直连需要保留端口：5115/9000。5115 为统一代理端口，9000 为独立端口；不建议将 5115 直接暴露到公网，推荐使用反代服务代理 `/dl`。
          </div>
          <div class="form-card">
            <el-form label-width="150px">
              <el-form-item label="CAS 文件生成目录">
                <div class="form-field">
                  <el-input v-model="settings.cas_root_dir" placeholder="/cas" :disabled="!canWrite" />
                  <div class="form-field-hint">CAS 文件上传到网盘的统一目录；所有支持驱动共用这一目标路径。</div>
                  <div class="form-field-hint">生成时会按账号 `STRM 扫描路径` 的相对目录树，上传 `<原文件名>.cas` 到该目录下。</div>
                </div>
              </el-form-item>
              <el-form-item label="CAS 并发 Worker">
                <div class="form-field">
                  <el-input-number v-model="settings.cas_workers" :min="1" :max="32" :step="1" :disabled="!canWrite" />
                  <div class="form-field-hint">控制 CAS 生成任务的并发 worker 数量，与复制任务独立；默认 4。</div>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveCasSettings">
                  保存 CAS 设置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
          <div class="driver-group-list">
            <section v-for="driver in drivers" :key="driver.code" class="glass-panel driver-group">
              <div class="driver-group__header">
                <div>
                  <h3>{{ driver.drive_name }}</h3>
                  <div class="driver-group__meta">
                    编码：{{ driver.code }}，账号数：{{ driver.account_count }}，启用：{{ driver.enabled_count }}，默认账号：{{ driver.default_account_name || '-' }}
                  </div>
                </div>
              </div>
              <div v-if="driver.accounts?.length" class="driver-account-grid">
                <article v-for="account in driver.accounts" :key="account.account_id" class="driver-account-card">
                  <div class="driver-account-card__header">
                    <div>
                      <div class="driver-account-card__title">
                        <h4>{{ account.account_name }}</h4>
                        <el-tag v-if="account.is_default" type="success" effect="plain" round>默认</el-tag>
                      </div>
                      <div class="driver-account-card__meta">
                        {{ account.nickname || account.username || '未命名账号' }}（{{ account.drive_name }}）
                      </div>
                    </div>
                    <div class="driver-account-card__tags">
                      <el-tag :type="account.enabled ? 'success' : 'info'" effect="plain" round>
                        {{ account.enabled ? '启用' : '禁用' }}
                      </el-tag>
                      <el-tag :type="account.runtime_status === 'active' ? 'success' : 'info'" effect="plain" round>
                        {{ account.runtime_status || '未探测' }}
                      </el-tag>
                      <el-tag :type="casStatusTagType(currentTask(account)?.status)" effect="plain" round>
                        {{ casStatusLabel(account) }}
                      </el-tag>
                    </div>
                  </div>
                  <div class="driver-account-card__body">
                    <div class="driver-account-card__path">
                      <span class="driver-account-card__label">STRM 扫描路径</span>
                      <code>{{ accountCasBasePath(account) || '未配置' }}</code>
                    </div>
                    <div class="driver-account-card__summary">{{ buildCasSummary(account) }}</div>
                  </div>
                  <div class="driver-account-card__actions">
                    <el-button
                      v-if="canGenerateCas(account)"
                      type="primary"
                      :loading="Boolean(casSubmitting[account.account_id])"
                      :disabled="!canWrite"
                      @click="handleGenerateCas(account)"
                    >
                      生成CAS数据
                    </el-button>
                    <el-button
                      v-if="canPauseTask(currentTask(account))"
                      :loading="Boolean(currentTask(account)?.task_id && casActionLoading[currentTask(account)!.task_id])"
                      :disabled="!canWrite"
                      @click="handlePauseCas(account)"
                    >
                      暂停
                    </el-button>
                    <el-button
                      v-if="canResumeTask(currentTask(account))"
                      type="success"
                      :loading="Boolean(currentTask(account)?.task_id && casActionLoading[currentTask(account)!.task_id])"
                      :disabled="!canWrite"
                      @click="handleResumeCas(account)"
                    >
                      继续
                    </el-button>
                    <el-button
                      v-if="canCancelTask(currentTask(account))"
                      type="danger"
                      plain
                      :loading="Boolean(currentTask(account)?.task_id && casActionLoading[currentTask(account)!.task_id])"
                      :disabled="!canWrite"
                      @click="handleCancelCas(account)"
                    >
                      停止
                    </el-button>
                    <el-button
                      v-if="canGenerateCas(account)"
                      link
                      type="primary"
                      :disabled="Boolean(casTaskLoading[account.account_id])"
                      @click="openTaskDialog(account)"
                    >
                      管理任务
                    </el-button>
                    <el-tag v-else type="info" effect="plain" round>未配置 STRM 扫描路径</el-tag>
                  </div>
                  <div v-if="canGenerateCas(account) && currentTask(account)" class="cas-task-overview">
                    <el-progress :percentage="taskPercent(currentTask(account))" :stroke-width="8" />
                    <div class="cas-task-overview__meta">
                      <span>任务进度：{{ taskProgressText(currentTask(account)) }}</span>
                      <span>字节进度：{{ formatBytes(currentTask(account)?.done_bytes || 0) }}/{{ formatBytes(currentTask(account)?.total_bytes || 0) }}</span>
                    </div>
                  </div>
                </article>
              </div>
              <el-empty v-else description="当前驱动下暂无账号" />
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="反代设置" name="proxy">
          <div class="form-card">
            <!-- 多目标反代配置 -->
            <div style="margin-bottom: 20px;">
              <h4 style="margin-bottom: 10px; font-size: 14px; font-weight: 500;">反代目标列表</h4>
              <p style="color: #909399; font-size: 12px; margin-bottom: 12px;">配置多个反代目标，每个系统独立端口和处理方式。类型说明：飞牛影视＝响应改写，Emby/Jellyfin＝下载 302 拦截，通用透传＝纯代理。</p>
              <div v-if="proxyTargets.length === 0" style="padding: 20px; text-align: center; border: 1px dashed #ddd; border-radius: 6px; color: #909399; font-size: 13px;">
                暂无反代目标，点击下方按钮添加
              </div>
              <div v-for="(target, idx) in proxyTargets" :key="target._key" style="border: 1px solid #ebeef5; border-radius: 6px; padding: 12px; margin-bottom: 10px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                  <span style="font-size: 13px; font-weight: 500;">#{{ idx + 1 }} {{ target.name || '未命名' }}</span>
                  <el-button type="danger" size="small" text :disabled="!canWrite" @click="removeProxyTarget(idx)">删除</el-button>
                </div>
                <el-form label-width="80px" size="small">
                  <el-row :gutter="12">
                    <el-col :span="12">
                      <el-form-item label="名称">
                        <el-input v-model="target.name" placeholder="如：飞牛影视" :disabled="!canWrite" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="类型">
                        <el-select v-model="target.type" :disabled="!canWrite" style="width: 100%;">
                          <el-option v-for="opt in PROXY_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="目标地址">
                        <el-input v-model="target.target_url" placeholder="http://192.168.1.100:8096" :disabled="!canWrite" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="监听端口">
                        <el-input v-model="target.listen_addr" placeholder="5225" :disabled="!canWrite" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="路径偏移">
                        <el-input-number v-model="target.path_offset" :step="1" :disabled="!canWrite" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="启用">
                        <el-switch v-model="target.enabled" :disabled="!canWrite" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </el-form>
              </div>
              <el-button size="small" :disabled="!canWrite" @click="addProxyTarget">+ 添加反代目标</el-button>
            </div>

            <!-- 全局配置 -->
            <el-form label-width="150px">
              <el-form-item label="ProxyURL（兼容）">
                <div class="form-field">
                  <el-input v-model="settings.proxy_url" placeholder="http://127.0.0.1:5666" :disabled="!canWrite" />
                  <div class="form-field-hint">旧版单地址配置，当无反代目标时自动作为飞牛影视目标使用。</div>
                </div>
              </el-form-item>
              <el-form-item label="路径偏移（兼容）">
                <div class="form-field">
                  <el-input-number v-model="settings.proxy_path_offset" :step="1" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    飞牛影视的路径偏移配置，会影响代理重写时的目录回退层级，通常使用负数。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="内网网段(CIDR)">
                <div class="form-field">
                  <el-input
                    v-model="settings.intranet_cidrs_text"
                    type="textarea"
                    :rows="6"
                    placeholder="10.0.0.0/8&#10;172.16.0.0/12&#10;192.168.0.0/16&#10;127.0.0.0/8&#10;::1/128&#10;fc00::/7&#10;fe80::/10"
                    :disabled="!canWrite"
                  />
                  <div class="form-field-hint">每行一个网段，命中内网直连绕过代理（所有反代目标共享）。</div>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveProxySettings">
                  保存反代设置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="302设置" name="dl302">
          <div class="form-card">
            <el-form label-width="150px">
              <el-form-item label="自动均衡">
                <div class="form-field">
                  <el-switch v-model="settings.auto_balance" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    开启后：同一驱动存在多个账号时，只要任意账号能解析并播放该路径，就会自动切换到可用账号并继续解析；后续同一路径会优先复用该可用账号，减少反复尝试。
                  </div>
                  <div class="form-field-hint">
                    关闭后：指定账号仅使用当前账号解析；若该账号无资源或失效，将直接返回失败。
                  </div>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveDL302Settings">
                  保存 302 设置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="STRM管理" name="strm">
          <section class="metric-strip metric-strip--inner">
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">生成状态</div>
              <div class="metric-tile__value">{{ strmSummary.enabled ? '开启' : '关闭' }}</div>
              <div class="metric-tile__hint">当前 STRM 自动生成总开关</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">生成模式</div>
              <div class="metric-tile__value">{{ strmSummary.mode === 'independent' ? '独立' : '自动' }}</div>
              <div class="metric-tile__hint">当前正在使用的 STRM 生成模式</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">可参与账号</div>
              <div class="metric-tile__value">{{ strmSummary.path_ready_account_count }}</div>
              <div class="metric-tile__hint">已配置可用 STRM 源路径的账号</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">已生成文件</div>
              <div class="metric-tile__value">{{ strmSummary.generated_file_count }}</div>
              <div class="metric-tile__hint">当前模式 manifest 中记录的 STRM 文件数</div>
            </div>
          </section>

          <div class="form-card">
            <el-form label-width="150px">
              <el-divider content-position="left">STRM 管理</el-divider>
              <el-form-item label="开启生成 STRM">
                <div class="form-field">
                  <el-switch v-model="settings.strm_enabled" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    开启后会在驱动目录扫描/缓存巡检完成时自动对账生成。默认复用各账号驱动配置里的 `STRM 扫描路径`；为空时回退到 `缓存路径`。
                  </div>
                  <div class="form-field-hint">
                    可参与账号：{{ strmSummary.path_ready_account_count }} / {{ strmSummary.source_account_count }}，缺少源路径账号：{{
                      strmSummary.path_missing_account_count
                    }}。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="包含CAS文件目录">
                <div class="form-field">
                  <el-switch v-model="settings.strm_include_cas_root_dir" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    开启后，仅对“已配置 `STRM 扫描路径`”的账号，额外扫描 `CAS 文件生成目录`，为其中 `.cas` 文件补充生成 STRM。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="源优先级">
                <div class="form-field">
                  <el-radio-group v-model="settings.strm_source_priority" :disabled="!canWrite">
                    <el-radio value="video_first">视频文件优先</el-radio>
                    <el-radio value="cas_first">CAS 优先</el-radio>
                  </el-radio-group>
                  <div class="form-field-hint">
                    当 `STRM 扫描路径` 下的视频与 `CAS 文件生成目录` 下的 `.cas` 生成出同名 `.strm` 时，按这里的优先级决定最终写入哪个链接。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="生成模式">
                <div class="form-field">
                  <el-radio-group v-model="settings.strm_mode" :disabled="!canWrite">
                    <el-radio value="auto">自动模式</el-radio>
                    <el-radio value="independent">独立模式</el-radio>
                  </el-radio-group>
                  <div class="form-field-hint">
                    自动模式：合并所有可用账号结果，仅保留一份目录树，STRM 链接统一指向 `/dl/auto`。
                  </div>
                  <div class="form-field-hint">
                    独立模式：按账号名生成一级目录，STRM 链接使用对应驱动入口和 `account` 参数。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="STRM 生成目录">
                <div class="form-field">
                  <el-input v-model="settings.strm_root_dir" placeholder="/strm" :disabled="!canWrite" />
                  <div class="form-field-hint">STRM 文件输出目录；不存在会自动创建。</div>
                  <div class="form-field-hint">开启生成 STRM 状态下修改目录/模式时，会清理旧目录下旧产物并按新配置重建。</div>
                </div>
              </el-form-item>
              <el-form-item label="前缀 URL">
                <div class="form-field">
                  <el-input
                    v-model="settings.strm_prefix_url"
                    placeholder="例如：http://192.168.1.10:9978"
                    :disabled="!canWrite"
                  />
                  <div class="form-field-hint">用于生成 STRM 内的访问链接前缀；留空时访问页面会自动回填当前访问地址。</div>
                  <div class="form-field-hint">
                    前缀 URL：{{ strmSummary.prefix_ready ? '已就绪' : '未就绪' }}，生成目录状态：{{ strmSummary.root_exists ? '已存在' : '不存在' }}，已生成目录：{{
                      strmSummary.generated_dir_count
                    }}。
                  </div>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveStrmSettings">
                  保存 STRM 设置
                </el-button>
                <el-button type="success" :loading="settings.generatingStrm" :disabled="!canWrite" @click="generateStrm">
                  立即生成 STRM
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-dialog
      v-model="casDialog.visible"
      :title="dialogAccount ? `${dialogAccount.account_name} · CAS任务管理` : 'CAS任务管理'"
      width="min(1100px, 96vw)"
      destroy-on-close
      @closed="closeTaskDialog"
    >
      <div v-if="dialogAccount" class="cas-task-dialog">
        <div class="cas-task-dialog__toolbar">
          <div class="cas-task-dialog__toolbar-left">
            <el-select
              :model-value="selectedDialogTask?.task_id || ''"
              placeholder="选择任务"
              filterable
              style="width: 260px"
                :loading="Boolean(casTaskLoading[dialogAccountId])"
                @change="(value) => selectTask(dialogAccountId, String(value || ''))"
            >
              <el-option
                  v-for="task in casTaskLists[dialogAccountId] || []"
                :key="task.task_id"
                :label="taskOptionLabel(task)"
                :value="task.task_id"
              />
            </el-select>
            <el-input
              v-model="casDialog.search"
              clearable
              placeholder="搜索文件名、路径、阶段、错误"
              style="width: 280px"
              @input="handleDialogFilterChange"
              @clear="handleDialogFilterChange"
            />
            <el-select
              v-model="casDialog.status"
              style="width: 140px"
              @change="handleDialogFilterChange"
            >
              <el-option label="全部状态" value="all" />
              <el-option label="待处理" value="pending" />
              <el-option label="处理中" value="running" />
              <el-option label="已完成" value="done" />
              <el-option label="已跳过" value="skipped" />
              <el-option label="失败" value="failed" />
              <el-option label="已取消" value="cancelled" />
            </el-select>
          </div>
          <el-button :loading="Boolean(casTaskLoading[dialogAccountId])" @click="loadAccountTasks(dialogAccountId)">刷新任务</el-button>
        </div>

        <div v-if="selectedDialogTask" class="cas-task-detail">
          <div class="cas-task-detail__summary">
            <div>任务ID：{{ selectedDialogTask.task_id }}</div>
            <div>扫描目录：{{ selectedDialogTask.base_path || '-' }}</div>
            <div>
              状态：
              <el-tag size="small" :type="casStatusTagType(selectedDialogTask.status)" effect="plain">
                {{ casStatusText(selectedDialogTask.status || '') }}
              </el-tag>
            </div>
            <div>已处理 {{ taskProcessedItems(selectedDialogTask) }} / {{ selectedDialogTask.total_items }}</div>
            <div>字节进度 {{ formatBytes(selectedDialogTask.done_bytes || 0) }} / {{ formatBytes(selectedDialogTask.total_bytes || 0) }}</div>
            <div>
              完成 {{ selectedDialogTask.done_items || 0 }}，跳过 {{ selectedDialogTask.skipped_items || 0 }}，失败
              {{ selectedDialogTask.failed_items || 0 }}
            </div>
            <div v-if="selectedDialogTask.last_error" class="cas-task-detail__error">
              错误：{{ selectedDialogTask.last_error }}
            </div>
          </div>
          <div class="cas-task-item-list" v-loading="Boolean(selectedDialogTask.task_id && casItemLoading[selectedDialogTask.task_id])">
            <div class="cas-task-item-list__meta">
              <span>共 {{ filteredDialogTaskItems.length }} 条</span>
              <span>当前页 {{ pagedDialogTaskItems.length }} 条</span>
            </div>
            <div
              v-for="item in pagedDialogTaskItems"
              :key="item.id"
              class="cas-task-item"
            >
              <div class="cas-task-item__header">
                <div class="cas-task-item__name">{{ item.name || item.file_path }}</div>
                <el-tag size="small" :type="itemStatusTagType(item.status)" effect="plain">
                  {{ itemStatusLabel(item.status) }}
                </el-tag>
              </div>
              <div class="cas-task-item__path">{{ item.file_path }}</div>
              <div class="cas-task-item__meta">
                <span>阶段：{{ item.stage || '-' }}</span>
                <span>大小：{{ formatBytes(item.size) }}</span>
                <span>进度：{{ formatStageProgress(item) }}</span>
                <span v-if="item.rapid_drive_types">预热驱动：{{ item.rapid_drive_types }}</span>
              </div>
              <el-progress
                v-if="item.status === 'running' || item.stage_total > 0"
                :percentage="itemPercent(item)"
                :stroke-width="6"
              />
              <div v-if="item.last_error" class="cas-task-item__error">错误：{{ item.last_error }}</div>
            </div>
            <el-empty
              v-if="!casItemLoading[selectedDialogTask.task_id] && !filteredDialogTaskItems.length"
              description="当前筛选条件下暂无明细"
            />
          </div>
          <div v-if="filteredDialogTaskItems.length > 0" class="pagination-bar">
            <el-pagination
              :current-page="dialogCurrentPage"
              :page-size="casDialog.pageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="filteredDialogTaskItems.length"
              background
              layout="total, sizes, prev, pager, next"
              @current-change="handleDialogPageChange"
              @size-change="handleDialogPageSizeChange"
            />
          </div>
        </div>
        <el-empty v-else description="当前账号暂无 CAS 任务" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab-copy {
  margin-bottom: 16px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.driver-group-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.driver-group {
  padding: 18px;
}

.driver-group__header {
  margin-bottom: 16px;
}

.driver-group__header h3 {
  margin: 0 0 6px;
}

.driver-group__meta {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.driver-account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.driver-account-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  padding: 16px;
  background: color-mix(in srgb, var(--el-bg-color) 90%, transparent);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.driver-account-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.driver-account-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.driver-account-card__title h4 {
  margin: 0;
}

.driver-account-card__meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.driver-account-card__tags {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.driver-account-card__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.driver-account-card__path {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.driver-account-card__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.driver-account-card__summary {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.driver-account-card__actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.cas-task-overview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cas-task-overview__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cas-task-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cas-task-dialog__toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.cas-task-dialog__toolbar-left {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.cas-task-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cas-task-detail__summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.cas-task-detail__error,
.cas-task-item__error {
  color: var(--el-color-danger);
  font-size: 12px;
}

.cas-task-item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 220px;
  max-height: 58vh;
  overflow: auto;
  padding-right: 4px;
}

.cas-task-item-list__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cas-task-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: color-mix(in srgb, var(--el-fill-color-lighter) 40%, transparent);
}

.cas-task-item__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cas-task-item__name {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}

.cas-task-item__path,
.cas-task-item__meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  word-break: break-all;
}

.cas-task-item__meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

.metric-strip--inner {
  margin-bottom: 20px;
}

.form-card {
  max-width: 720px;
}

.form-field {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

@media (max-width: 768px) {
  .cas-task-dialog__toolbar,
  .cas-task-dialog__toolbar-left {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
