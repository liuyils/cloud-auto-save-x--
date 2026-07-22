<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
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
  Plus,
  HardDrive,
  Pencil,
  Trash2,
  Radar,
  Power,
  Star,
  RotateCw,
  RefreshCw,
  CalendarCheck,
  QrCode,
  ShieldCheck,
  Database,
  Save,
  AlertTriangle,
} from 'lucide-vue-next'
import { useDriveAccountsQuery, useDriveTypesQuery, useDriveAccountProbeSchedulerQuery } from '@/hooks/queries/extensions'
import {
  useCreateDriveAccountMutation,
  useUpdateDriveAccountMutation,
  useDeleteDriveAccountMutation,
  useSetDriveAccountDefaultMutation,
  useRefreshDriveAccountProfilesMutation,
  useRefreshDriveAccountLsdirCacheMutation,
  usePatchDriveAccountProbeSchedulerMutation,
} from '@/hooks/mutations/extensions'
import { probeDriveAccount, setDriveAccountStatus, signInDriveAccount, getDriveAccountSignInJob } from '@/api/extensions'
import { useQueryClient } from '@tanstack/vue-query'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { DRIVE_ACCOUNT_WRITE } from '@/constants/permissions'
import { parseAuthChallenge, extractErrorMessage, supportsTvQrcodeAuth } from '@/lib/driveAuth'
import { formatBytes, formatPercent, formatDateTime } from '@/lib/capacity'
import { validateCrontab5, validateTimezone } from '@/lib/cron'
import DriveAccountSheet from './DriveAccountSheet.vue'
import DriveAccountAuthDialog from './DriveAccountAuthDialog.vue'
import type { DriveAccountItem, DriveAccountAuthChallenge } from '@/types/extensions'

const { toast } = useToast()
const queryClient = useQueryClient()
const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(DRIVE_ACCOUNT_WRITE))

const { data: accounts, isLoading, isFetching, refetch: refetchAccounts } = useDriveAccountsQuery()
const { data: driveTypes } = useDriveTypesQuery()
const { data: scheduler, isLoading: schedulerLoading } = useDriveAccountProbeSchedulerQuery()

const createMutation = useCreateDriveAccountMutation()
const updateMutation = useUpdateDriveAccountMutation()
const deleteMutation = useDeleteDriveAccountMutation()
const defaultMutation = useSetDriveAccountDefaultMutation()
const refreshProfilesMutation = useRefreshDriveAccountProfilesMutation()
const refreshCacheMutation = useRefreshDriveAccountLsdirCacheMutation()
const schedulerMutation = usePatchDriveAccountProbeSchedulerMutation()

// --- per-account loading sets ---
const probingIds = ref<Set<number>>(new Set())
const signingIds = ref<Set<number>>(new Set())
const cacheRefreshingIds = ref<Set<number>>(new Set())

// --- Sheet state ---
const sheetOpen = ref(false)
const editingAccount = ref<DriveAccountItem | null>(null)
const submitting = ref(false)

// --- Auth dialog state ---
const authDialog = reactive({
  open: false,
  accountId: 0,
  accountName: '',
  driveType: '',
  challenge: null as DriveAccountAuthChallenge | null,
  startQrcode: false,
})

// --- Delete dialog ---
const deleteDialogOpen = ref(false)
const deletingAccount = ref<DriveAccountItem | null>(null)
const deleting = ref(false)

// --- Cache refresh dialog ---
const cacheDialogOpen = ref(false)
const cacheDialogAccount = ref<DriveAccountItem | null>(null)

// --- Probe scheduler form ---
const schedulerForm = reactive({
  enabled: true,
  crontab: '0 4 * * *',
  timezone: 'Asia/Shanghai',
  enabled_only: true,
})
const schedulerSaving = ref(false)

// keep form in sync with server data
watch(
  scheduler,
  (val) => {
    if (!val) return
    schedulerForm.enabled = Boolean(val.enabled)
    schedulerForm.crontab = String(val.crontab || '0 4 * * *')
    schedulerForm.timezone = String(val.timezone || 'Asia/Shanghai')
    schedulerForm.enabled_only = Boolean(val.enabled_only)
  },
  { immediate: true },
)

// --- Filters ---
const filters = reactive({
  keyword: '',
  drive_type: '',
  status: 'all' as 'all' | 'enabled' | 'disabled',
  warnings_only: false,
})

const driveTypesList = computed(() => driveTypes.value || [])
const accountList = computed(() => accounts.value || [])

function getDriveTypeName(code: string) {
  return driveTypesList.value.find((item) => item.code === code)?.drive_name || code
}

function isWarning(account: DriveAccountItem) {
  return (account.usage_ratio || 0) >= (account.capacity_warning_threshold || 100) / 100
}

const filteredAccounts = computed(() =>
  accountList.value.filter((item) => {
    const kw = filters.keyword.trim().toLowerCase()
    const matchesKeyword =
      !kw ||
      [item.name, item.profile?.nickname, item.profile?.username].some((v) =>
        String(v || '').toLowerCase().includes(kw),
      )
    const matchesDrive = !filters.drive_type || item.drive_type === filters.drive_type
    const matchesStatus =
      filters.status === 'all' ||
      (filters.status === 'enabled' && item.enabled) ||
      (filters.status === 'disabled' && !item.enabled)
    const matchesWarning = !filters.warnings_only || isWarning(item)
    return matchesKeyword && matchesDrive && matchesStatus && matchesWarning
  }),
)

const summary = computed(() => ({
  account_count: accountList.value.length,
  enabled_count: accountList.value.filter((i) => i.enabled).length,
  default_count: accountList.value.filter((i) => i.is_default).length,
  warning_count: accountList.value.filter((i) => isWarning(i)).length,
}))

// --- status display (FIX: backend uses 'active', not 'ok') ---
function getStatusMeta(account: DriveAccountItem): { dot: string; label: string; text: string } {
  if (!account.enabled) return { dot: 'bg-gray-400', label: '已禁用', text: 'text-[hsl(var(--muted-foreground))]' }
  const st = String(account.runtime_status || '').trim().toLowerCase()
  if (st === 'active') return { dot: 'bg-green-500', label: '在线', text: 'text-green-600 dark:text-green-400' }
  if (st === 'error') return { dot: 'bg-red-500', label: '异常', text: 'text-red-500' }
  if (st === 'inactive') return { dot: 'bg-amber-500', label: '离线', text: 'text-amber-600 dark:text-amber-400' }
  return { dot: 'bg-gray-400', label: '未探测', text: 'text-[hsl(var(--muted-foreground))]' }
}

function hasAnyConfigValue(config: Record<string, any>) {
  return Object.values(config || {}).some((value) => {
    if (typeof value === 'boolean') return value
    if (typeof value === 'number') return !Number.isNaN(value)
    return String(value ?? '').trim() !== ''
  })
}

function invalidateAccounts() {
  queryClient.invalidateQueries({ queryKey: ['drive-accounts'] })
}

// --- Sheet ---
function openCreateSheet() {
  editingAccount.value = null
  sheetOpen.value = true
}
function openEditSheet(account: DriveAccountItem) {
  editingAccount.value = account
  sheetOpen.value = true
}
function closeSheet() {
  sheetOpen.value = false
  editingAccount.value = null
}

async function handleSave(payload: {
  name: string
  drive_type: string
  config: Record<string, any>
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold: number
}) {
  if (!editingAccount.value && !hasAnyConfigValue(payload.config)) {
    toast.error('请填写当前网盘所需的登录参数')
    return
  }
  submitting.value = true
  try {
    if (editingAccount.value) {
      await updateMutation.mutateAsync({
        accountId: editingAccount.value.id,
        payload: {
          name: payload.name,
          config: payload.config,
          enabled: payload.enabled,
          is_default: payload.is_default,
          capacity_warning_threshold: payload.capacity_warning_threshold,
        },
      })
      toast.success('账号已更新')
      closeSheet()
    } else {
      const created = await createMutation.mutateAsync(payload)
      closeSheet()
      toast.success('账号已创建，正在探测...')
      try {
        await probeDriveAccount(created.id, { silentToast: true })
        toast.success('探测完成')
        invalidateAccounts()
      } catch (e) {
        const challenge = parseAuthChallenge(e)
        if (challenge) {
          invalidateAccounts()
          toast.info('该账号需要二次认证，请继续完成验证')
          openAuthByChallenge(created.id, payload.name, payload.drive_type, challenge)
          return
        }
        toast.info('账号已创建，但探测失败，请稍后重试')
        invalidateAccounts()
      }
    }
  } catch (e) {
    toast.error(extractErrorMessage(e))
  } finally {
    submitting.value = false
  }
}

// --- Delete ---
function openDeleteDialog(account: DriveAccountItem) {
  deletingAccount.value = account
  deleteDialogOpen.value = true
}
async function confirmDelete() {
  if (!deletingAccount.value) return
  deleting.value = true
  try {
    await deleteMutation.mutateAsync(deletingAccount.value.id)
    toast.success('账号已删除')
    deleteDialogOpen.value = false
    deletingAccount.value = null
  } catch (e) {
    toast.error(extractErrorMessage(e, '删除失败'))
  } finally {
    deleting.value = false
  }
}

// --- Probe (with auth challenge handling) ---
async function handleProbe(account: DriveAccountItem) {
  probingIds.value = new Set(probingIds.value).add(account.id)
  try {
    await probeDriveAccount(account.id, { silentToast: true })
    toast.success('账号已探测并刷新快照')
    invalidateAccounts()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      invalidateAccounts()
      toast.info('该账号需要二次认证，请继续完成验证')
      openAuthByChallenge(account.id, account.name, account.drive_type, challenge)
      return
    }
    toast.error(extractErrorMessage(e, '探测失败'))
  } finally {
    const next = new Set(probingIds.value)
    next.delete(account.id)
    probingIds.value = next
  }
}

// --- Toggle status (with auth challenge handling) ---
async function handleToggleStatus(account: DriveAccountItem) {
  const newEnabled = !account.enabled
  try {
    await setDriveAccountStatus(account.id, newEnabled, { silentToast: true })
    toast.success(newEnabled ? '已启用' : '已禁用')
    invalidateAccounts()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      invalidateAccounts()
      toast.info('该账号需要二次认证，请继续完成验证')
      openAuthByChallenge(account.id, account.name, account.drive_type, challenge)
      return
    }
    toast.error(extractErrorMessage(e))
  }
}

// --- Set default ---
async function handleSetDefault(account: DriveAccountItem) {
  try {
    await defaultMutation.mutateAsync(account.id)
    toast.success('该驱动默认账号已更新')
  } catch (e) {
    toast.error(extractErrorMessage(e))
  }
}

// --- Sign in (async job polling) ---
async function handleSignIn(account: DriveAccountItem) {
  signingIds.value = new Set(signingIds.value).add(account.id)
  try {
    const result = await signInDriveAccount(account.id, { silentToast: true })
    if (result?.async && result?.job_id) {
      toast.info('签到任务已提交，后台执行中')
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
        const job = await getDriveAccountSignInJob(String(result.job_id))
        const status = String(job?.status ?? '')
        if (status === 'pending' || status === 'running') continue
        if (status === 'succeeded') {
          const message = job?.result?.raw?.summary_message ?? job?.message ?? job?.result?.message ?? '签到成功'
          toast.success(String(message))
          invalidateAccounts()
          return
        }
        throw new Error(String(job?.message ?? job?.error?.message ?? '签到失败'))
      }
    }
    toast.success(result?.message ? String(result.message) : '签到成功')
    invalidateAccounts()
  } catch (e) {
    toast.error(extractErrorMessage(e, '签到失败'))
  } finally {
    const next = new Set(signingIds.value)
    next.delete(account.id)
    signingIds.value = next
  }
}

// --- Refresh all profiles ---
async function handleRefreshProfiles() {
  try {
    await refreshProfilesMutation.mutateAsync()
    toast.success('全部账号容量快照已刷新')
  } catch (e) {
    toast.error(extractErrorMessage(e, '刷新失败'))
  }
}

// --- lsdir cache refresh ---
function openCacheDialog(account: DriveAccountItem) {
  if (!account.has_302_path) return
  cacheDialogAccount.value = account
  cacheDialogOpen.value = true
}
async function confirmCacheRefresh(rescanStatic: boolean) {
  const account = cacheDialogAccount.value
  if (!account) return
  cacheDialogOpen.value = false
  cacheRefreshingIds.value = new Set(cacheRefreshingIds.value).add(account.id)
  try {
    const result = await refreshCacheMutation.mutateAsync({ accountId: account.id, rescanStatic })
    if (result.reason === 'running') {
      toast.info('缓存刷新任务已在后台执行中，完成后会自动触发 STRM 对账')
    } else if (result.static_requested && result.static_queued) {
      toast.success('普通缓存与静态目录重扫任务已提交，完成后会自动触发 STRM 对账')
    } else if (result.static_requested && !result.static_queued) {
      toast.info(`普通缓存刷新已提交，完成后会自动触发 STRM 对账；静态目录未重扫：${result.static_skipped_reason || '未配置静态目录'}`)
    } else {
      toast.success('缓存刷新任务已提交，完成后会自动触发 STRM 对账')
    }
  } catch (e) {
    toast.error(extractErrorMessage(e, '刷新缓存失败'))
  } finally {
    const next = new Set(cacheRefreshingIds.value)
    next.delete(account.id)
    cacheRefreshingIds.value = next
    cacheDialogAccount.value = null
  }
}

// --- Auth dialog helpers ---
function openAuthByChallenge(
  accountId: number,
  accountName: string,
  driveType: string,
  challenge: DriveAccountAuthChallenge,
) {
  authDialog.accountId = accountId
  authDialog.accountName = accountName
  authDialog.driveType = driveType
  authDialog.challenge = challenge
  authDialog.startQrcode = false
  authDialog.open = true
}
function openAuth(account: DriveAccountItem, startQrcode = false) {
  authDialog.accountId = account.id
  authDialog.accountName = account.name
  authDialog.driveType = account.drive_type
  authDialog.challenge = null
  authDialog.startQrcode = startQrcode
  authDialog.open = true
}
function closeAuthDialog() {
  authDialog.open = false
  authDialog.challenge = null
  authDialog.startQrcode = false
}
function handleAuthSuccess() {
  closeAuthDialog()
  invalidateAccounts()
}

// --- Probe scheduler save ---
async function saveScheduler() {
  if (!canWrite.value) return
  const cronCheck = validateCrontab5(schedulerForm.crontab)
  if (!cronCheck.ok) {
    toast.error(cronCheck.message)
    return
  }
  const tzCheck = validateTimezone(schedulerForm.timezone)
  if (!tzCheck.ok) {
    toast.error(tzCheck.message)
    return
  }
  schedulerSaving.value = true
  try {
    await schedulerMutation.mutateAsync({
      enabled: schedulerForm.enabled,
      crontab: cronCheck.normalized || schedulerForm.crontab,
      timezone: tzCheck.normalized || schedulerForm.timezone,
      enabled_only: schedulerForm.enabled_only,
    })
    toast.success('调度配置已保存')
  } catch (e) {
    toast.error(extractErrorMessage(e, '保存失败'))
  } finally {
    schedulerSaving.value = false
  }
}
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">💽 网盘账号</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">管理已绑定的网盘账号、探测状态与自动调度</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="isFetching" @click="refetchAccounts()">
          <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': isFetching }" />
          刷新列表
        </Button>
        <Button variant="outline" size="sm" :disabled="refreshProfilesMutation.isPending.value" @click="handleRefreshProfiles">
          <RotateCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': refreshProfilesMutation.isPending.value }" />
          刷新全部容量
        </Button>
        <Button v-if="canWrite" size="sm" @click="openCreateSheet">
          <Plus class="mr-1 h-4 w-4" />
          添加账号
        </Button>
      </div>
    </div>

    <!-- Summary metrics -->
    <div class="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">👤</span>
          <span class="glass-tile__label">账号总数</span>
        </div>
        <div class="glass-tile__value">{{ summary.account_count }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">✅</span>
          <span class="glass-tile__label">启用账号</span>
        </div>
        <div class="glass-tile__value text-green-600 dark:text-green-400">{{ summary.enabled_count }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">⭐</span>
          <span class="glass-tile__label">默认账号（按驱动）</span>
        </div>
        <div class="glass-tile__value">{{ summary.default_count }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">⚠️</span>
          <span class="glass-tile__label">预警账号</span>
        </div>
        <div class="glass-tile__value" :class="summary.warning_count ? 'text-red-500' : ''">
          {{ summary.warning_count }}
        </div>
      </div>
    </div>

    <!-- Filters -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <Input v-model="filters.keyword" placeholder="搜索账号名 / 昵称" class="w-full sm:w-56" />
      <select
        v-model="filters.drive_type"
        class="h-9 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
      >
        <option value="">全部类型</option>
        <option v-for="item in driveTypesList" :key="item.code" :value="item.code">{{ item.drive_name }}</option>
      </select>
      <div class="flex gap-1 rounded-md border border-[hsl(var(--border))] p-0.5">
        <button
          v-for="opt in [
            { label: '全部', value: 'all' },
            { label: '启用', value: 'enabled' },
            { label: '禁用', value: 'disabled' },
          ]"
          :key="opt.value"
          class="rounded px-3 py-1 text-sm transition-colors"
          :class="filters.status === opt.value
            ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="filters.status = opt.value as any"
        >
          {{ opt.label }}
        </button>
      </div>
      <label class="flex cursor-pointer items-center gap-2 text-sm text-[hsl(var(--foreground))]">
        <button
          class="relative h-5 w-9 rounded-full transition-colors"
          :class="filters.warnings_only ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
          @click="filters.warnings_only = !filters.warnings_only"
        >
          <span class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform" :class="filters.warnings_only ? 'left-[18px]' : 'left-0.5'" />
        </button>
        仅看预警
      </label>
    </div>

    <!-- Probe scheduler -->
    <div class="mb-6 rounded-lg border border-[hsl(var(--border))] p-4">
      <div class="mb-3 flex items-center gap-2">
        <CalendarCheck class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">自动探测 / 签到调度</h3>
      </div>
      <div v-if="schedulerLoading" class="flex flex-wrap gap-3">
        <Skeleton class="h-9 w-40 rounded-md" />
        <Skeleton class="h-9 w-40 rounded-md" />
      </div>
      <div v-else class="flex flex-wrap items-center gap-4">
        <label class="flex cursor-pointer items-center gap-2 text-sm text-[hsl(var(--foreground))]">
          <button
            class="relative h-5 w-9 rounded-full transition-colors"
            :class="schedulerForm.enabled ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
            @click="schedulerForm.enabled = !schedulerForm.enabled"
          >
            <span class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform" :class="schedulerForm.enabled ? 'left-[18px]' : 'left-0.5'" />
          </button>
          启用调度
        </label>
        <div class="flex items-center gap-2">
          <span class="text-sm text-[hsl(var(--muted-foreground))]">Crontab</span>
          <Input v-model="schedulerForm.crontab" placeholder="0 4 * * *" class="w-40" />
        </div>
        <div class="flex items-center gap-2">
          <span class="text-sm text-[hsl(var(--muted-foreground))]">时区</span>
          <Input v-model="schedulerForm.timezone" placeholder="Asia/Shanghai" class="w-40" />
        </div>
        <label class="flex cursor-pointer items-center gap-2 text-sm text-[hsl(var(--foreground))]">
          <button
            class="relative h-5 w-9 rounded-full transition-colors"
            :class="schedulerForm.enabled_only ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
            @click="schedulerForm.enabled_only = !schedulerForm.enabled_only"
          >
            <span class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform" :class="schedulerForm.enabled_only ? 'left-[18px]' : 'left-0.5'" />
          </button>
          仅启用账号
        </label>
        <Button size="sm" :disabled="!canWrite || schedulerSaving" @click="saveScheduler">
          <Save class="mr-1 h-4 w-4" />
          {{ schedulerSaving ? '保存中...' : '保存' }}
        </Button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Skeleton v-for="i in 6" :key="i" class="h-56 w-full rounded-lg" />
    </div>

    <!-- Empty -->
    <div
      v-else-if="!filteredAccounts.length"
      class="flex flex-col items-center justify-center py-16"
    >
      <div class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--muted))]">
        <HardDrive class="h-6 w-6 text-[hsl(var(--muted-foreground))]" />
      </div>
      <p class="text-sm text-[hsl(var(--muted-foreground))]">
        {{ accountList.length ? '当前筛选条件下没有账号' : '暂无网盘账号' }}
      </p>
      <Button v-if="canWrite && !accountList.length" variant="outline" size="sm" class="mt-4" @click="openCreateSheet">
        <Plus class="mr-1 h-4 w-4" />
        添加第一个账号
      </Button>
    </div>

    <!-- Account grid -->
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card v-for="account in filteredAccounts" :key="account.id" class="overflow-hidden">
        <CardContent class="p-4">
          <!-- Top row -->
          <div class="flex items-start gap-3">
            <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--muted))]">
              <HardDrive class="h-5 w-5 text-[hsl(var(--muted-foreground))]" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-sm font-semibold text-[hsl(var(--foreground))]">{{ account.name }}</span>
                <span
                  v-if="account.is_default"
                  class="inline-flex shrink-0 items-center gap-0.5 rounded-full border border-amber-400/40 bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400"
                >
                  <Star class="h-2.5 w-2.5 fill-current" />
                  默认
                </span>
              </div>
              <div class="truncate text-xs text-[hsl(var(--muted-foreground))]">
                <span>{{ account.profile?.nickname || account.profile?.username || '未命名账号' }}</span>
                · {{ getDriveTypeName(account.drive_type) }}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              <span class="h-2 w-2 rounded-full" :class="getStatusMeta(account).dot" />
              <span class="text-xs" :class="getStatusMeta(account).text">{{ getStatusMeta(account).label }}</span>
            </div>
          </div>

          <!-- Capacity -->
          <div class="mt-3">
            <template v-if="account.total_space && account.total_space > 0">
              <div class="mb-1 flex items-center justify-between text-xs">
                <span class="text-[hsl(var(--muted-foreground))]">
                  {{ formatBytes(account.used_space) }} / {{ formatBytes(account.total_space) }}
                </span>
                <span :class="isWarning(account) ? 'font-medium text-red-500' : 'text-[hsl(var(--muted-foreground))]'">
                  {{ formatPercent(account.usage_ratio) }}
                </span>
              </div>
              <div class="h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                <div
                  class="h-full rounded-full transition-all"
                  :class="isWarning(account) ? 'bg-red-500' : 'bg-[hsl(var(--primary))]'"
                  :style="{ width: `${Math.min(100, Math.round((account.usage_ratio || 0) * 100))}%` }"
                />
              </div>
              <div class="mt-1 text-[10px] text-[hsl(var(--muted-foreground))]">预警阈值 {{ account.capacity_warning_threshold }}%</div>
            </template>
            <div v-else class="text-xs text-[hsl(var(--muted-foreground))]">容量：未知（可执行探测）</div>
          </div>

          <!-- lsdir cache (always reserve the line to keep cards aligned) -->
          <div class="mt-2 flex min-h-[16px] flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
            <template v-if="account.has_302_path">
              <span class="truncate" :title="account.lsdir_cache_base_path || account.config?.['302_path'] || '-'">
                缓存路径：{{ account.lsdir_cache_base_path || account.config?.['302_path'] || '-' }}
              </span>
              <span>缓存文件：{{ account.lsdir_cache_file_total ?? 0 }}</span>
            </template>
            <span v-else aria-hidden="true">&nbsp;</span>
          </div>

          <!-- footer meta -->
          <div class="mt-2 flex items-center justify-between text-[11px] text-[hsl(var(--muted-foreground))]">
            <span>最近刷新：{{ formatDateTime(account.profile_updated_at || account.last_checked_at) }}</span>
            <span v-if="account.probe_fail_count" class="text-amber-600 dark:text-amber-400">失败 {{ account.probe_fail_count }} 次</span>
          </div>

          <!-- last error -->
          <div
            v-if="getStatusMeta(account).label === '异常' && account.last_error"
            class="mt-2 truncate text-xs text-red-500"
            :title="account.last_error"
          >
            {{ account.last_error }}
          </div>

          <!-- Actions -->
          <div class="mt-3 flex flex-wrap items-center gap-1 border-t border-[hsl(var(--border))] pt-3">
            <Button variant="ghost" size="sm" class="h-7 px-2 text-xs" :disabled="probingIds.has(account.id)" @click="handleProbe(account)">
              <Radar class="mr-1 h-3 w-3" :class="{ 'animate-spin': probingIds.has(account.id) }" />
              {{ probingIds.has(account.id) ? '探测中' : '探测' }}
            </Button>
            <Button variant="ghost" size="sm" class="h-7 px-2 text-xs" :disabled="signingIds.has(account.id)" @click="handleSignIn(account)">
              <CalendarCheck class="mr-1 h-3 w-3" />
              {{ signingIds.has(account.id) ? '签到中' : '签到' }}
            </Button>
            <Button v-if="canWrite" variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="openAuth(account, supportsTvQrcodeAuth(account.drive_type))">
              <component :is="supportsTvQrcodeAuth(account.drive_type) ? QrCode : ShieldCheck" class="mr-1 h-3 w-3" />
              {{ supportsTvQrcodeAuth(account.drive_type) ? 'TV 扫码' : '认证' }}
            </Button>
            <Button
              v-if="canWrite && account.has_302_path"
              variant="ghost"
              size="sm"
              class="h-7 px-2 text-xs"
              :disabled="cacheRefreshingIds.has(account.id)"
              @click="openCacheDialog(account)"
            >
              <Database class="mr-1 h-3 w-3" />
              {{ cacheRefreshingIds.has(account.id) ? '刷新中' : '刷新缓存' }}
            </Button>
            <Button v-if="canWrite" variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="handleToggleStatus(account)">
              <Power class="mr-1 h-3 w-3" />
              {{ account.enabled ? '禁用' : '启用' }}
            </Button>
            <Button v-if="canWrite && !account.is_default" variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="handleSetDefault(account)">
              <Star class="mr-1 h-3 w-3" />
              设为默认
            </Button>
            <div class="flex-1" />
            <Button v-if="canWrite" variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="openEditSheet(account)">
              <Pencil class="h-3 w-3" />
            </Button>
            <Button v-if="canWrite" variant="ghost" size="sm" class="h-7 px-2 text-xs text-red-500 hover:text-red-600" @click="openDeleteDialog(account)">
              <Trash2 class="h-3 w-3" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Sheet -->
    <DriveAccountSheet
      :open="sheetOpen"
      :edit-account="editingAccount"
      :drive-types="driveTypesList"
      :submitting="submitting"
      @close="closeSheet"
      @save="handleSave"
    />

    <!-- Auth dialog -->
    <DriveAccountAuthDialog
      :open="authDialog.open"
      :account-id="authDialog.accountId"
      :account-name="authDialog.accountName"
      :drive-type="authDialog.driveType"
      :initial-challenge="authDialog.challenge"
      :start-qrcode="authDialog.startQrcode"
      @close="closeAuthDialog"
      @success="handleAuthSuccess"
    />

    <!-- Delete dialog -->
    <AlertDialog :open="deleteDialogOpen" @update:open="(v: boolean) => { if (!v) { deleteDialogOpen = false; deletingAccount = null } }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认删除</AlertDialogTitle>
          <AlertDialogDescription>
            删除后不可恢复：该账号的配置、容量快照与相关状态信息将被永久移除。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div v-if="deletingAccount" class="space-y-2 rounded-lg border border-[hsl(var(--border))] p-3 text-sm">
          <div class="flex items-center justify-between">
            <span class="text-[hsl(var(--muted-foreground))]">账号名</span>
            <span class="font-medium text-[hsl(var(--foreground))]">{{ deletingAccount.name }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-[hsl(var(--muted-foreground))]">网盘类型</span>
            <span class="text-[hsl(var(--foreground))]">{{ getDriveTypeName(deletingAccount.drive_type) }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-[hsl(var(--muted-foreground))]">状态</span>
            <div class="flex items-center gap-1.5">
              <Badge :variant="deletingAccount.enabled ? 'default' : 'secondary'" class="px-1.5 py-0 text-[10px]">
                {{ deletingAccount.enabled ? '启用' : '禁用' }}
              </Badge>
              <Badge v-if="deletingAccount.is_default" variant="secondary" class="px-1.5 py-0 text-[10px]">默认</Badge>
            </div>
          </div>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel @click="deleteDialogOpen = false; deletingAccount = null">取消</AlertDialogCancel>
          <AlertDialogAction
            class="bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] hover:bg-[hsl(var(--destructive))]/90"
            :disabled="deleting"
            @click="confirmDelete"
          >
            {{ deleting ? '删除中...' : '删除' }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <!-- Cache refresh dialog -->
    <AlertDialog :open="cacheDialogOpen" @update:open="(v: boolean) => { if (!v) { cacheDialogOpen = false; cacheDialogAccount = null } }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle class="flex items-center gap-2">
            <AlertTriangle class="h-4 w-4 text-amber-500" />
            刷新 lsdir 缓存
          </AlertDialogTitle>
          <AlertDialogDescription>
            是否同时重扫静态 lsdir 目录？默认只刷新普通缓存；只有确认后才会强制重新扫描静态目录。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cacheDialogOpen = false; cacheDialogAccount = null">取消</AlertDialogCancel>
          <Button variant="outline" size="sm" @click="confirmCacheRefresh(false)">仅刷新普通缓存</Button>
          <Button size="sm" @click="confirmCacheRefresh(true)">重扫静态目录</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
