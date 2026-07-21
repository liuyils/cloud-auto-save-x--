<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { SettingCard } from '@/components/ui/setting-card'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import {
  Save,
  FolderOutput,
  Play,
  Pause,
  XCircle,
  RefreshCw,
  Zap,
  ListChecks,
  Database,
  Server,
  Globe,
  FileCode2,
  HardDrive,
} from 'lucide-vue-next'
import {
  fetchDL302SupportedDrivers,
  fetchDL302Config,
  patchDL302Config,
  generateDL302Strm,
  submitDL302CasTask,
  fetchDL302CasTask,
  pauseDL302CasTask,
  resumeDL302CasTask,
  cancelDL302CasTask,
} from '@/api/dl302'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { TASK_WRITE } from '@/constants/permissions'
import { extractErrorMessage } from '@/lib/driveAuth'
import { formatBytes } from '@/lib/capacity'
import {
  casStatusText,
  casStatusClass,
  buildCasSummary,
  accountCasBasePath,
  canGenerateCas,
  canPauseTask,
  canResumeTask,
  canCancelTask,
  isTaskActive,
  taskPercent,
  taskProgressText,
} from '@/lib/dl302'
import Dl302CasTaskDialog from './Dl302CasTaskDialog.vue'
import type { DL302Config, DL302CASTask, DL302SupportedAccount, DL302SupportedDriver, DL302StrmGenerateResult } from '@/types/dl302'

const { toast } = useToast()
const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const TABS = [
  { key: 'cas', label: 'CAS 管理', icon: Database },
  { key: 'proxy', label: '反代设置', icon: Server },
  { key: 'dl302', label: '302 设置', icon: Globe },
  { key: 'strm', label: 'STRM 管理', icon: FileCode2 },
] as const
const activeTab = ref<'cas' | 'proxy' | 'dl302' | 'strm'>('cas')

const loading = ref(false)
const drivers = ref<DL302SupportedDriver[]>([])

const form = reactive({
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

const savingProxy = ref(false)
const savingDl302 = ref(false)
const savingCas = ref(false)
const savingStrm = ref(false)
const generatingStrm = ref(false)

const casSubmitting = reactive<Record<number, boolean>>({})
const casActionLoading = reactive<Record<string, boolean>>({})

const taskDialog = reactive({ open: false, accountId: 0, accountName: '' })
const fastComputeDialog = reactive({ open: false, account: null as DL302SupportedAccount | null })

let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollInFlight = false
let pollDelayMs = 3000
let pollSession = 0

function applyConfig(data: DL302Config) {
  form.proxy_url = String(data.proxy_url || '')
  form.proxy_path_offset = Number.isFinite(Number(data.proxy_path_offset)) ? Number(data.proxy_path_offset) : -1
  form.intranet_cidrs_text = Array.isArray(data.intranet_cidrs) ? data.intranet_cidrs.filter(Boolean).join('\n') : ''
  form.auto_balance = Boolean(data.auto_balance)
  form.cas_root_dir = String(data.cas_root_dir || '')
  form.cas_workers = Number(data.cas_workers) > 0 ? Number(data.cas_workers) : 4
  form.strm_enabled = Boolean(data.strm_enabled)
  form.strm_mode = data.strm_mode === 'independent' ? 'independent' : 'auto'
  form.strm_root_dir = String(data.strm_root_dir || '/strm')
  form.strm_prefix_url = String(data.strm_prefix_url || '')
  form.strm_include_cas_root_dir = Boolean(data.strm_include_cas_root_dir)
  form.strm_source_priority = data.strm_source_priority === 'cas_first' ? 'cas_first' : 'video_first'
  const s = data.strm_summary
  strmSummary.enabled = Boolean(s?.enabled)
  strmSummary.mode = s?.mode === 'independent' ? 'independent' : 'auto'
  strmSummary.prefix_ready = Boolean(s?.prefix_ready)
  strmSummary.root_exists = Boolean(s?.root_exists)
  strmSummary.source_account_count = Number(s?.source_account_count || 0)
  strmSummary.path_ready_account_count = Number(s?.path_ready_account_count || 0)
  strmSummary.path_missing_account_count = Number(s?.path_missing_account_count || 0)
  strmSummary.generated_file_count = Number(s?.generated_file_count || 0)
  strmSummary.generated_dir_count = Number(s?.generated_dir_count || 0)
}

async function loadPage() {
  stopPoller()
  loading.value = true
  try {
    const [driverData, configData] = await Promise.all([fetchDL302SupportedDrivers(), fetchDL302Config()])
    drivers.value = driverData
    applyConfig(configData)
    startPoller()
  } catch (e) {
    toast.error(extractErrorMessage(e, '加载失败'))
  } finally {
    loading.value = false
  }
}

async function refreshConfig() {
  try {
    applyConfig(await fetchDL302Config())
  } catch {
    // ignore
  }
}

// --- CAS driver helpers ---
function flattenAccounts(): DL302SupportedAccount[] {
  return drivers.value.flatMap((d) => d.accounts || [])
}
function currentTask(account: DL302SupportedAccount): DL302CASTask | null {
  return account.cas_task || null
}
function updateAccountTask(accountId: number, task: DL302CASTask | null) {
  for (const driver of drivers.value) {
    const account = (driver.accounts || []).find((a) => a.account_id === accountId)
    if (account) {
      account.cas_task = task
      return
    }
  }
}

// --- polling running tasks (account cards) ---
function nextPollDelay(elapsedMs: number, failed: boolean) {
  if (failed) return 8000
  if (elapsedMs > 2500) return 8000
  if (elapsedMs > 1500) return 5000
  if (elapsedMs > 800) return 5000
  return 3000
}

function clearPollerTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function startPoller() {
  if (!flattenAccounts().some((a) => isTaskActive(currentTask(a)?.status))) {
    stopPoller()
    return
  }
  pollSession += 1
  pollDelayMs = 3000
  scheduleNextPoll(0, pollSession)
}

function stopPoller() {
  pollSession += 1
  clearPollerTimer()
  pollInFlight = false
  pollDelayMs = 3000
}

function scheduleNextPoll(delayMs: number, session = pollSession) {
  clearPollerTimer()
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
      shouldContinue = await pollRunningOnce(session)
    } catch {
      failed = true
      shouldContinue = true
    } finally {
      pollInFlight = false
      if (session !== pollSession) return
      if (!shouldContinue) {
        stopPoller()
        return
      }
      pollDelayMs = nextPollDelay(Date.now() - startedAt, failed)
      scheduleNextPoll(pollDelayMs, session)
    }
  }, delayMs)
}

async function pollRunningOnce(session: number) {
  const targets = flattenAccounts().filter((a) => isTaskActive(currentTask(a)?.status))
  if (!targets.length) {
    return false
  }
  await Promise.all(
    targets.map(async (a) => {
      const task = currentTask(a)
      if (!task?.task_id) return
      try {
        const latest = await fetchDL302CasTask(task.task_id)
        if (session !== pollSession) return
        updateAccountTask(a.account_id, latest)
      } catch {
        // ignore during polling
      }
    }),
  )
  if (session !== pollSession) return false
  return flattenAccounts().some((a) => isTaskActive(currentTask(a)?.status))
}

// --- CAS actions ---
function handleGenerateCas(account: DL302SupportedAccount) {
  if (!canWrite.value || !canGenerateCas(account)) return
  if (account.drive_type === 'cloud139') {
    fastComputeDialog.account = account
    fastComputeDialog.open = true
    return
  }
  void doGenerate(account, false)
}
async function doGenerate(account: DL302SupportedAccount, fastCompute: boolean) {
  casSubmitting[account.account_id] = true
  try {
    const result = await submitDL302CasTask(account.account_id, { fast_compute: fastCompute })
    updateAccountTask(account.account_id, result.task)
    toast.success(result.message || 'CAS 任务已提交')
    startPoller()
  } catch (e) {
    toast.error(extractErrorMessage(e, '提交 CAS 任务失败'))
  } finally {
    casSubmitting[account.account_id] = false
  }
}
function confirmFastCompute(fastCompute: boolean) {
  const account = fastComputeDialog.account
  fastComputeDialog.open = false
  fastComputeDialog.account = null
  if (account) void doGenerate(account, fastCompute)
}

async function runTaskAction(
  account: DL302SupportedAccount,
  action: 'pause' | 'resume' | 'cancel',
) {
  const task = currentTask(account)
  if (!task?.task_id || !canWrite.value) return
  casActionLoading[task.task_id] = true
  try {
    let latest: DL302CASTask
    if (action === 'pause') latest = await pauseDL302CasTask(task.task_id)
    else if (action === 'resume') latest = await resumeDL302CasTask(task.task_id)
    else latest = await cancelDL302CasTask(task.task_id)
    updateAccountTask(account.account_id, latest)
    toast.success(action === 'pause' ? '已请求暂停' : action === 'resume' ? '任务已继续' : '任务已停止')
    startPoller()
  } catch (e) {
    toast.error(extractErrorMessage(e, '操作失败'))
  } finally {
    casActionLoading[task.task_id] = false
  }
}

function openTaskDialog(account: DL302SupportedAccount) {
  taskDialog.accountId = account.account_id
  taskDialog.accountName = account.account_name
  taskDialog.open = true
}

// --- CIDR parse ---
function parseCIDRText(text: string): string[] | null {
  const parts = String(text || '')
    .split(/[\r\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!parts.length) return null
  return Array.from(new Set(parts))
}

// --- section saves ---
async function saveProxy() {
  if (!canWrite.value) return
  savingProxy.value = true
  try {
    const data = await patchDL302Config({
      proxy_url: form.proxy_url ? form.proxy_url.trim() : null,
      proxy_path_offset: Number(form.proxy_path_offset),
      intranet_cidrs: parseCIDRText(form.intranet_cidrs_text),
    })
    applyConfig(data)
    toast.success('反代设置已保存，已触发 dl302 重载')
  } catch (e) {
    toast.error(extractErrorMessage(e, '保存失败'))
  } finally {
    savingProxy.value = false
  }
}
async function saveDl302() {
  if (!canWrite.value) return
  savingDl302.value = true
  try {
    const data = await patchDL302Config({
      auto_balance: Boolean(form.auto_balance),
    })
    applyConfig(data)
    toast.success('302 设置已保存，已触发 dl302 重载')
  } catch (e) {
    toast.error(extractErrorMessage(e, '保存失败'))
  } finally {
    savingDl302.value = false
  }
}
async function saveCas() {
  if (!canWrite.value) return
  savingCas.value = true
  try {
    const data = await patchDL302Config({
      cas_root_dir: form.cas_root_dir ? form.cas_root_dir.trim() : null,
      cas_workers: Number(form.cas_workers) > 0 ? Number(form.cas_workers) : 4,
    })
    applyConfig(data)
    toast.success('CAS 设置已保存')
  } catch (e) {
    toast.error(extractErrorMessage(e, '保存失败'))
  } finally {
    savingCas.value = false
  }
}
async function saveStrm() {
  if (!canWrite.value) return
  savingStrm.value = true
  try {
    const data = await patchDL302Config({
      strm_enabled: Boolean(form.strm_enabled),
      strm_mode: form.strm_mode,
      strm_root_dir: form.strm_root_dir.trim() || '/strm',
      strm_prefix_url: form.strm_prefix_url ? form.strm_prefix_url.trim() : null,
      strm_include_cas_root_dir: Boolean(form.strm_include_cas_root_dir),
      strm_source_priority: form.strm_source_priority,
    })
    applyConfig(data)
    toast.success('STRM 设置已保存')
  } catch (e) {
    toast.error(extractErrorMessage(e, '保存失败'))
  } finally {
    savingStrm.value = false
  }
}
async function handleGenerateStrm() {
  if (!canWrite.value) return
  generatingStrm.value = true
  try {
    const result: DL302StrmGenerateResult = await generateDL302Strm({ mode: form.strm_mode, persist_prefix_if_empty: true })
    await refreshConfig()
    const detail = `模式：${result.mode === 'independent' ? '独立' : '自动'}，文件：${result.generated_files}，目录：${result.generated_dirs}，跳过账号：${result.skipped_accounts}`
    toast.success(result.message ? `${result.message}，${detail}` : detail)
  } catch (e) {
    toast.error(extractErrorMessage(e, '生成 STRM 失败'))
  } finally {
    generatingStrm.value = false
  }
}

onMounted(loadPage)
onBeforeUnmount(stopPoller)
</script>

<template>
  <div class="mx-auto max-w-5xl">
    <!-- Header -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-xl font-bold text-[hsl(var(--foreground))]">🌐 302 代理</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">DL302 直连 / 反代、CAS 秒传与 STRM 生成</p>
      </div>
      <Button variant="outline" size="sm" :disabled="loading" @click="loadPage">
        <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': loading }" />
        刷新页面
      </Button>
    </div>

    <!-- Tabs -->
    <div class="mb-6 flex overflow-x-auto overscroll-x-contain">
      <div class="inline-flex gap-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-1">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          class="flex shrink-0 items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-all"
          :class="activeTab === tab.key
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="activeTab = tab.key"
        >
          <component :is="tab.icon" class="h-4 w-4" />
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="space-y-4">
      <Skeleton v-for="i in 4" :key="i" class="h-28 w-full rounded-xl" />
    </div>

    <template v-else>
      <!-- ================= CAS 管理 ================= -->
      <div v-show="activeTab === 'cas'" class="space-y-6">
        <div class="rounded-xl border border-[hsl(var(--primary))]/20 bg-[hsl(var(--primary))]/5 p-4 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">
          「生成 CAS 数据」会复用账号配置中的 <b class="text-[hsl(var(--foreground))]">STRM 扫描路径</b> 作为扫描目录，仅处理目录缓存里缺少 rapid record 的视频文件；生成后按目录树在本地临时目录生成 <code class="rounded bg-[hsl(var(--muted))] px-1">.cas</code> 文件并上传到该账号网盘的 <b class="text-[hsl(var(--foreground))]">CAS 文件生成目录</b>。<br />
          302 直连需保留端口 <b class="text-[hsl(var(--foreground))]">5115 / 9000</b>；5115 为统一代理端口，不建议直接暴露公网，推荐用反代代理 <code class="rounded bg-[hsl(var(--muted))] px-1">/dl</code>。
        </div>

        <!-- CAS settings -->
        <SettingCard title="CAS 设置" description="CAS 秒传数据生成的全局参数" :icon="Database">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">CAS 文件生成目录</label>
              <Input v-model="form.cas_root_dir" placeholder="/cas" :disabled="!canWrite" />
              <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">上传到网盘的统一目录，所有驱动共用。</p>
            </div>
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">CAS 并发 Worker</label>
              <Input v-model="form.cas_workers" type="number" placeholder="4" :disabled="!canWrite" />
              <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">并发数（1-32），与复制任务独立，默认 4。</p>
            </div>
          </div>
          <template #footer>
            <Button size="sm" :disabled="!canWrite || savingCas" @click="saveCas">
              <Save class="mr-1 h-4 w-4" />
              {{ savingCas ? '保存中...' : '保存 CAS 设置' }}
            </Button>
          </template>
        </SettingCard>

        <!-- Driver groups -->
        <div class="space-y-5">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">驱动账号</h3>
          <div v-if="!drivers.length" class="rounded-xl border border-dashed border-[hsl(var(--border))] py-12 text-center text-sm text-[hsl(var(--muted-foreground))]">暂无支持 302 的驱动账号</div>
          <div v-for="driver in drivers" :key="driver.code" class="space-y-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ driver.drive_name }}</span>
              <span class="rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                账号 {{ driver.account_count }} · 启用 {{ driver.enabled_count }} · 默认 {{ driver.default_account_name || '-' }}
              </span>
            </div>
            <div v-if="driver.accounts?.length" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <div v-for="account in driver.accounts" :key="account.account_id" class="flex flex-col gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-sm transition-shadow hover:shadow-md">
                <!-- header -->
                <div class="flex items-start gap-3">
                  <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]">
                    <HardDrive class="h-4 w-4" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{{ account.account_name }}</span>
                      <span v-if="account.is_default" class="shrink-0 rounded-full bg-[hsl(var(--secondary))] px-1.5 py-0 text-[10px] text-[hsl(var(--secondary-foreground))]">默认</span>
                    </div>
                    <div class="truncate text-xs text-[hsl(var(--muted-foreground))]">{{ account.nickname || account.username || '未命名账号' }} · {{ account.drive_name }}</div>
                  </div>
                </div>
                <!-- status pills -->
                <div class="flex flex-wrap gap-1.5">
                  <span class="rounded-full px-2 py-0.5 text-[11px]" :class="account.enabled ? 'bg-green-500/15 text-green-600 dark:text-green-400' : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'">
                    {{ account.enabled ? '启用' : '禁用' }}
                  </span>
                  <span class="rounded-full px-2 py-0.5 text-[11px]" :class="account.runtime_status === 'active' ? 'bg-green-500/15 text-green-600 dark:text-green-400' : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'">
                    {{ account.runtime_status === 'active' ? '在线' : (account.runtime_status || '未探测') }}
                  </span>
                  <span class="rounded-full px-2 py-0.5 text-[11px]" :class="casStatusClass(currentTask(account)?.status)">
                    {{ casStatusText(currentTask(account)?.status) }}
                  </span>
                </div>
                <!-- path + summary -->
                <div class="space-y-1 text-xs">
                  <div class="text-[hsl(var(--muted-foreground))]">STRM 扫描路径</div>
                  <code class="block truncate rounded-md bg-[hsl(var(--muted))] px-2 py-1 text-[11px] text-[hsl(var(--foreground))]" :title="accountCasBasePath(account) || '未配置'">
                    {{ accountCasBasePath(account) || '未配置' }}
                  </code>
                  <p class="pt-0.5 leading-relaxed text-[hsl(var(--muted-foreground))]">{{ buildCasSummary(account, currentTask(account)) }}</p>
                </div>
                <!-- progress -->
                <div v-if="canGenerateCas(account) && currentTask(account)" class="space-y-1">
                  <div class="h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                    <div class="h-full rounded-full bg-[hsl(var(--primary))] transition-all" :style="{ width: `${taskPercent(currentTask(account))}%` }" />
                  </div>
                  <div class="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))]">
                    <span>进度 {{ taskProgressText(currentTask(account)) }}</span>
                    <span>{{ formatBytes(currentTask(account)?.done_bytes || 0) }} / {{ formatBytes(currentTask(account)?.total_bytes || 0) }}</span>
                  </div>
                </div>
                <!-- actions -->
                <div class="mt-auto flex flex-wrap items-center gap-1 border-t border-[hsl(var(--border))] pt-3">
                  <Button
                    v-if="canGenerateCas(account)"
                    size="sm"
                    class="h-7 px-2 text-xs"
                    :disabled="!canWrite || Boolean(casSubmitting[account.account_id])"
                    @click="handleGenerateCas(account)"
                  >
                    <Zap class="mr-1 h-3 w-3" />
                    {{ casSubmitting[account.account_id] ? '提交中' : '生成 CAS' }}
                  </Button>
                  <Button v-if="canPauseTask(currentTask(account))" variant="ghost" size="sm" class="h-7 px-2 text-xs" :disabled="!canWrite" @click="runTaskAction(account, 'pause')">
                    <Pause class="mr-1 h-3 w-3" />暂停
                  </Button>
                  <Button v-if="canResumeTask(currentTask(account))" variant="ghost" size="sm" class="h-7 px-2 text-xs" :disabled="!canWrite" @click="runTaskAction(account, 'resume')">
                    <Play class="mr-1 h-3 w-3" />继续
                  </Button>
                  <Button v-if="canCancelTask(currentTask(account))" variant="ghost" size="sm" class="h-7 px-2 text-xs text-red-500 hover:text-red-600" :disabled="!canWrite" @click="runTaskAction(account, 'cancel')">
                    <XCircle class="mr-1 h-3 w-3" />停止
                  </Button>
                  <div class="flex-1" />
                  <Button v-if="canGenerateCas(account)" variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="openTaskDialog(account)">
                    <ListChecks class="mr-1 h-3 w-3" />管理任务
                  </Button>
                  <span v-else class="text-[11px] text-[hsl(var(--muted-foreground))]">未配置扫描路径</span>
                </div>
              </div>
            </div>
            <div v-else class="rounded-xl border border-dashed border-[hsl(var(--border))] py-6 text-center text-xs text-[hsl(var(--muted-foreground))]">当前驱动下暂无账号</div>
          </div>
        </div>
      </div>

      <!-- ================= 反代设置 ================= -->
      <div v-show="activeTab === 'proxy'" class="max-w-3xl">
        <SettingCard title="反代设置" description="dl302 反向代理相关参数，保存后自动触发 dl302 重载" :icon="Server">
          <div>
            <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">ProxyURL</label>
            <Input v-model="form.proxy_url" placeholder="http://127.0.0.1:5666" :disabled="!canWrite" />
            <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">反代目标地址。</p>
          </div>
          <div>
            <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">飞牛影视路径偏移</label>
            <Input v-model="form.proxy_path_offset" type="number" placeholder="-1" :disabled="!canWrite" />
            <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">影响代理重写时目录回退层级，通常为负数。</p>
          </div>
          <div>
            <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">内网网段 (CIDR)</label>
            <textarea
              v-model="form.intranet_cidrs_text"
              rows="6"
              :disabled="!canWrite"
              placeholder="10.0.0.0/8&#10;172.16.0.0/12&#10;192.168.0.0/16&#10;127.0.0.0/8&#10;::1/128"
              class="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 font-mono text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-50"
            />
            <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">每行一个网段，命中内网直连绕过代理。</p>
          </div>
          <template #footer>
            <Button size="sm" :disabled="!canWrite || savingProxy" @click="saveProxy">
              <Save class="mr-1 h-4 w-4" />
              {{ savingProxy ? '保存中...' : '保存反代设置' }}
            </Button>
          </template>
        </SettingCard>
      </div>

      <!-- ================= 302 设置 ================= -->
      <div v-show="activeTab === 'dl302'" class="max-w-3xl">
        <SettingCard title="302 设置" description="302 直连解析行为，保存后自动触发 dl302 重载" :icon="Globe">
          <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-[hsl(var(--foreground))]">自动均衡</div>
              <p class="mt-1 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">
                开启后：同一驱动多账号时，任意账号能解析播放该路径就自动切换到可用账号并优先复用；关闭后：仅用当前账号解析，失效则直接失败。
              </p>
            </div>
            <ToggleSwitch v-model="form.auto_balance" :disabled="!canWrite" />
          </div>
          <template #footer>
            <Button size="sm" :disabled="!canWrite || savingDl302" @click="saveDl302">
              <Save class="mr-1 h-4 w-4" />
              {{ savingDl302 ? '保存中...' : '保存 302 设置' }}
            </Button>
          </template>
        </SettingCard>
      </div>

      <!-- ================= STRM 管理 ================= -->
      <div v-show="activeTab === 'strm'" class="space-y-6">
        <!-- metrics -->
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div class="glass-tile">
            <div class="glass-tile__top">
              <span class="glass-tile__emoji">📡</span>
              <span class="glass-tile__label">生成状态</span>
            </div>
            <div class="glass-tile__value" :class="strmSummary.enabled ? 'text-green-600 dark:text-green-400' : ''">{{ strmSummary.enabled ? '开启' : '关闭' }}</div>
          </div>
          <div class="glass-tile">
            <div class="glass-tile__top">
              <span class="glass-tile__emoji">⚙️</span>
              <span class="glass-tile__label">生成模式</span>
            </div>
            <div class="glass-tile__value">{{ strmSummary.mode === 'independent' ? '独立' : '自动' }}</div>
          </div>
          <div class="glass-tile">
            <div class="glass-tile__top">
              <span class="glass-tile__emoji">🔗</span>
              <span class="glass-tile__label">可参与账号</span>
            </div>
            <div class="glass-tile__value">{{ strmSummary.path_ready_account_count }} <span class="text-sm font-normal text-[hsl(var(--muted-foreground))]">/ {{ strmSummary.source_account_count }}</span></div>
          </div>
          <div class="glass-tile">
            <div class="glass-tile__top">
              <span class="glass-tile__emoji">📄</span>
              <span class="glass-tile__label">已生成文件</span>
            </div>
            <div class="glass-tile__value">{{ strmSummary.generated_file_count }}</div>
          </div>
        </div>

        <SettingCard title="STRM 生成" description="自动生成媒体库可播放的 .strm 文件" :icon="FileCode2">
          <!-- toggles -->
          <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-[hsl(var(--foreground))]">开启生成 STRM</div>
              <p class="mt-1 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">扫描/缓存巡检完成时自动对账生成，默认复用各账号 STRM 扫描路径，为空回退到缓存路径。缺少源路径账号：{{ strmSummary.path_missing_account_count }}。</p>
            </div>
            <ToggleSwitch v-model="form.strm_enabled" :disabled="!canWrite" />
          </div>
          <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-[hsl(var(--foreground))]">包含 CAS 文件目录</div>
              <p class="mt-1 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">仅对已配置 STRM 扫描路径的账号，额外扫描 CAS 文件生成目录，为 .cas 文件补充生成 STRM。</p>
            </div>
            <ToggleSwitch v-model="form.strm_include_cas_root_dir" :disabled="!canWrite" />
          </div>

          <!-- segmented options -->
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">源优先级</label>
              <div class="flex gap-2">
                <button class="flex-1 rounded-md border px-3 py-1.5 text-sm transition-colors" :class="form.strm_source_priority === 'video_first' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'" :disabled="!canWrite" @click="form.strm_source_priority = 'video_first'">视频优先</button>
                <button class="flex-1 rounded-md border px-3 py-1.5 text-sm transition-colors" :class="form.strm_source_priority === 'cas_first' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'" :disabled="!canWrite" @click="form.strm_source_priority = 'cas_first'">CAS 优先</button>
              </div>
            </div>
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">生成模式</label>
              <div class="flex gap-2">
                <button class="flex-1 rounded-md border px-3 py-1.5 text-sm transition-colors" :class="form.strm_mode === 'auto' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'" :disabled="!canWrite" @click="form.strm_mode = 'auto'">自动</button>
                <button class="flex-1 rounded-md border px-3 py-1.5 text-sm transition-colors" :class="form.strm_mode === 'independent' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'" :disabled="!canWrite" @click="form.strm_mode = 'independent'">独立</button>
              </div>
            </div>
          </div>
          <p class="text-xs text-[hsl(var(--muted-foreground))]">自动：合并所有账号结果，链接统一指向 /dl/auto；独立：按账号名生成一级目录，链接带 account 参数。</p>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">STRM 生成目录</label>
              <Input v-model="form.strm_root_dir" placeholder="/strm" :disabled="!canWrite" />
              <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">生成目录状态：{{ strmSummary.root_exists ? '已存在' : '不存在' }}，已生成目录：{{ strmSummary.generated_dir_count }}。</p>
            </div>
            <div>
              <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">前缀 URL</label>
              <Input v-model="form.strm_prefix_url" placeholder="http://192.168.1.10:9978" :disabled="!canWrite" />
              <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">前缀 URL：{{ strmSummary.prefix_ready ? '已就绪' : '未就绪' }}，留空访问时自动回填。</p>
            </div>
          </div>

          <template #footer>
            <Button size="sm" :disabled="!canWrite || savingStrm" @click="saveStrm">
              <Save class="mr-1 h-4 w-4" />
              {{ savingStrm ? '保存中...' : '保存 STRM 设置' }}
            </Button>
            <Button variant="outline" size="sm" :disabled="!canWrite || generatingStrm" @click="handleGenerateStrm">
              <FolderOutput class="mr-1 h-4 w-4" />
              {{ generatingStrm ? '生成中...' : '立即生成 STRM' }}
            </Button>
          </template>
        </SettingCard>
      </div>
    </template>

    <!-- CAS task dialog -->
    <Dl302CasTaskDialog
      :open="taskDialog.open"
      :account-id="taskDialog.accountId"
      :account-name="taskDialog.accountName"
      @close="taskDialog.open = false"
    />

    <!-- cloud139 fast compute confirm -->
    <AlertDialog :open="fastComputeDialog.open" @update:open="(v: boolean) => { if (!v) { fastComputeDialog.open = false; fastComputeDialog.account = null } }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>使用快速计算能力？</AlertDialogTitle>
          <AlertDialogDescription>
            启用后会优先通过云端目录列表返回的 SHA256(contentHash) 生成 CAS，显著减少下载 + 本地哈希；拿不到 hash 时会自动回退原流程。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="fastComputeDialog.open = false; fastComputeDialog.account = null">取消</AlertDialogCancel>
          <Button variant="outline" size="sm" @click="confirmFastCompute(false)">按原方式</Button>
          <Button size="sm" @click="confirmFastCompute(true)">使用快速计算</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
