<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { RefreshCw, X, Trash2, Timer, Loader2, Copy, Download } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import {
  deleteTMDBCacheItem,
  fetchTMDBCacheItem,
  fetchTMDBCacheList,
  fetchTMDBCacheScheduler,
  fetchTMDBCacheStatus,
  patchTMDBCacheScheduler,
  purgeTMDBCache,
  refreshLinkedTasks,
  refreshTMDBCache,
  setTMDBCacheTTL,
} from '@/api/tmdbCache'
import type { TMDBCacheItem, TMDBCacheListItem, TMDBCacheSchedulerSetting, TMDBCacheStatus } from '@/types/tmdbCache'
import { validateCrontab5, validateTimezone } from '@/utils/cron'

const { toast } = useToast()

type MediaType = '' | 'movie' | 'tv'
type TTLUnit = 'minute' | 'hour' | 'day'

const PAYLOAD_PREVIEW_LIMIT = 50_000
const PAYLOAD_PRETTY_LIMIT = 200_000

const activeTab = ref<'list' | 'tools' | 'scheduler'>('list')

function fmtTime(value?: string | null) {
  if (!value) return '-'
  const s = String(value)
  const hasTz = /([zZ]|[+-]\d{2}:\d{2})$/.test(s)
  const d = new Date(hasTz ? s : `${s}Z`)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function toSeconds(value: number, unit: TTLUnit) {
  const v = Math.max(1, Math.floor(Number(value || 0)))
  if (unit === 'minute') return v * 60
  if (unit === 'hour') return v * 60 * 60
  return v * 24 * 60 * 60
}

const scheduler = reactive({
  loading: false,
  saving: false,
  data: {
    enabled: true,
    crontab: '0 */6 * * *',
    timezone: 'Asia/Shanghai',
    max_items_per_run: 200,
    only_refresh_linked_tasks: true,
    retention_days: 60,
  } as TMDBCacheSchedulerSetting,
})

const tools = reactive({
  refreshingLinked: false,
  purging: false,
  enabledOnly: true,
  maxItems: 200,
  force: true,
  retentionDays: 60,
})

const query = reactive({
  mediaType: '' as MediaType,
  keyword: '',
  status: '',
  expiredOnly: false,
})

const list = reactive({
  loading: false,
  configured: false,
  page: 1,
  pageSize: 20,
  total: 0,
  items: [] as TMDBCacheListItem[],
})

const quick = reactive({
  mediaType: 'tv' as Exclude<MediaType, ''>,
  tmdbId: null as number | null,
  loading: false,
  status: null as TMDBCacheStatus | null,
})

const drawer = reactive({
  visible: false,
  loading: false,
  row: null as TMDBCacheListItem | null,
  status: null as TMDBCacheStatus | null,
  tab: 'status' as 'status' | 'payload',
  payloadLoading: false,
  payloadItem: null as TMDBCacheItem | null,
})

const ttlDialog = reactive({
  visible: false,
  submitting: false,
  mediaType: '' as Exclude<MediaType, ''>,
  tmdbId: 0,
  value: 6,
  unit: 'hour' as TTLUnit,
})

const deleteDialog = reactive({
  visible: false,
  deleting: false,
  row: null as TMDBCacheListItem | null,
})

const listTotalPages = computed(() => Math.max(1, Math.ceil(list.total / list.pageSize)))
const filterActive = computed(() => Boolean(query.mediaType || query.keyword || query.status || query.expiredOnly))

async function loadScheduler() {
  scheduler.loading = true
  try {
    scheduler.data = await fetchTMDBCacheScheduler()
  } finally {
    scheduler.loading = false
  }
}

async function saveScheduler() {
  const cronCheck = validateCrontab5(String(scheduler.data.crontab || ''))
  if (!cronCheck.ok) {
    toast.error(cronCheck.message)
    return
  }
  const tzCheck = validateTimezone(String(scheduler.data.timezone || ''))
  if (!tzCheck.ok) {
    toast.error(tzCheck.message)
    return
  }
  scheduler.data.crontab = cronCheck.normalized || scheduler.data.crontab
  scheduler.data.timezone = tzCheck.normalized || scheduler.data.timezone
  scheduler.saving = true
  try {
    scheduler.data = await patchTMDBCacheScheduler({
      enabled: scheduler.data.enabled,
      crontab: scheduler.data.crontab,
      timezone: scheduler.data.timezone,
      max_items_per_run: scheduler.data.max_items_per_run,
      only_refresh_linked_tasks: scheduler.data.only_refresh_linked_tasks,
      retention_days: scheduler.data.retention_days,
    })
    toast.success('已保存')
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '保存失败')
  } finally {
    scheduler.saving = false
  }
}

async function loadList() {
  list.loading = true
  try {
    const data = await fetchTMDBCacheList({
      page: list.page,
      page_size: list.pageSize,
      media_type: query.mediaType || undefined,
      q: query.keyword || undefined,
      status: query.status || undefined,
      expired_only: query.expiredOnly || undefined,
    })
    list.configured = Boolean(data.configured)
    list.total = Number(data.total || 0)
    list.items = data.items || []
  } finally {
    list.loading = false
  }
}

function searchList() {
  list.page = 1
  loadList()
}

function resetFilters() {
  query.mediaType = ''
  query.keyword = ''
  query.status = ''
  query.expiredOnly = false
  list.page = 1
  loadList()
}

function listPrev() {
  if (list.page > 1) {
    list.page--
    loadList()
  }
}
function listNext() {
  if (list.page < listTotalPages.value) {
    list.page++
    loadList()
  }
}

async function refreshAll() {
  await Promise.all([loadScheduler(), loadList()])
}

async function runRefreshLinkedTasks() {
  tools.refreshingLinked = true
  try {
    const out = await refreshLinkedTasks({
      enabled_only: tools.enabledOnly,
      max_items: tools.maxItems,
      force: tools.force,
    })
    if (!out) {
      toast.error('刷新失败：接口返回为空')
      return
    }
    if (!out.configured) {
      toast.error('TMDB 未配置，请先在「TMDB 设置」中配置 API Key')
      return
    }
    toast.success(`刷新完成：已刷新 ${out.refreshed}/${out.targets}`)
    await loadList()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '刷新失败')
  } finally {
    tools.refreshingLinked = false
  }
}

async function runPurge() {
  if (!confirm(`确认清理冷数据？保留天数：${tools.retentionDays}`)) return
  tools.purging = true
  try {
    const out = await purgeTMDBCache({ retention_days: tools.retentionDays })
    toast.success(`清理完成：已删除 ${out.deleted}`)
    await loadList()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '清理失败')
  } finally {
    tools.purging = false
  }
}

async function quickQuery() {
  if (!quick.tmdbId) return
  quick.loading = true
  try {
    quick.status = await fetchTMDBCacheStatus({ media_type: quick.mediaType, tmdb_id: quick.tmdbId })
  } finally {
    quick.loading = false
  }
}

async function quickRefresh() {
  if (!quick.tmdbId) return
  quick.loading = true
  try {
    const out = await refreshTMDBCache({ media_type: quick.mediaType, tmdb_id: quick.tmdbId, force: true, async_refresh: false })
    quick.status = out.status
    toast.success('已刷新')
    await loadList()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '刷新失败')
  } finally {
    quick.loading = false
  }
}

async function openDrawer(row: TMDBCacheListItem) {
  drawer.visible = true
  drawer.row = row
  drawer.status = null
  drawer.tab = 'status'
  drawer.payloadLoading = false
  drawer.payloadItem = null
  drawer.loading = true
  try {
    drawer.status = await fetchTMDBCacheStatus({ media_type: row.media_type, tmdb_id: row.tmdb_id })
  } finally {
    drawer.loading = false
  }
}

async function loadDrawerPayload() {
  const row = drawer.row
  if (!row) return
  if (drawer.payloadLoading || drawer.payloadItem) return
  drawer.payloadLoading = true
  try {
    drawer.payloadItem = await fetchTMDBCacheItem({ media_type: row.media_type, tmdb_id: row.tmdb_id })
  } finally {
    drawer.payloadLoading = false
  }
}

const drawerPayloadRaw = computed(() => String(drawer.payloadItem?.payload_json || ''))
const drawerPayloadSize = computed(() => drawerPayloadRaw.value.length)
const drawerPayloadTooLarge = computed(() => drawerPayloadSize.value > PAYLOAD_PRETTY_LIMIT)
const drawerPayloadText = computed(() => {
  const raw = drawerPayloadRaw.value.trim()
  if (!raw) return ''
  if (drawerPayloadTooLarge.value) {
    if (raw.length <= PAYLOAD_PREVIEW_LIMIT) return raw
    return `${raw.slice(0, PAYLOAD_PREVIEW_LIMIT)}\n...（已截断，仅展示前 ${PAYLOAD_PREVIEW_LIMIT} 字符；建议使用「下载」查看全文）`
  }
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
})

async function copyDrawerPayloadRaw() {
  const text = String(drawerPayloadRaw.value || '')
  if (!text) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    toast.success('缓存数据已复制')
  } catch {
    toast.error('复制失败')
  }
}

function downloadDrawerPayload() {
  const raw = String(drawerPayloadRaw.value || '')
  if (!raw) return
  const name = drawer.row ? `${drawer.row.media_type}-${drawer.row.tmdb_id}.json` : 'tmdb-cache.json'
  const blob = new Blob([raw], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function openTTLDialog(row: TMDBCacheListItem) {
  ttlDialog.mediaType = row.media_type as Exclude<MediaType, ''>
  ttlDialog.tmdbId = row.tmdb_id
  ttlDialog.value = 6
  ttlDialog.unit = 'hour'
  ttlDialog.visible = true
}

async function submitTTL() {
  ttlDialog.submitting = true
  try {
    const out = await setTMDBCacheTTL({
      media_type: ttlDialog.mediaType,
      tmdb_id: ttlDialog.tmdbId,
      ttl_seconds: toSeconds(ttlDialog.value, ttlDialog.unit),
    })
    if (!out.updated) {
      toast.info('未找到缓存条目（可能尚未写入缓存）')
      return
    }
    toast.success('已更新 TTL')
    ttlDialog.visible = false
    await loadList()
    if (drawer.visible && drawer.row && drawer.row.tmdb_id === ttlDialog.tmdbId && drawer.row.media_type === ttlDialog.mediaType) {
      drawer.status = await fetchTMDBCacheStatus({ media_type: ttlDialog.mediaType, tmdb_id: ttlDialog.tmdbId })
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '更新失败')
  } finally {
    ttlDialog.submitting = false
  }
}

async function refreshRow(row: TMDBCacheListItem) {
  try {
    await refreshTMDBCache({ media_type: row.media_type, tmdb_id: row.tmdb_id, force: true, async_refresh: false })
    toast.success('已刷新')
    await loadList()
    if (drawer.visible && drawer.row && drawer.row.tmdb_id === row.tmdb_id && drawer.row.media_type === row.media_type) {
      drawer.status = await fetchTMDBCacheStatus({ media_type: row.media_type, tmdb_id: row.tmdb_id })
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '刷新失败')
  }
}

function openDeleteDialog(row: TMDBCacheListItem) {
  deleteDialog.row = row
  deleteDialog.visible = true
}
function closeDeleteDialog() {
  if (deleteDialog.deleting) return
  deleteDialog.visible = false
  deleteDialog.row = null
}
async function confirmDelete() {
  const row = deleteDialog.row
  if (!row) return
  deleteDialog.deleting = true
  try {
    const out = await deleteTMDBCacheItem({ media_type: row.media_type, tmdb_id: row.tmdb_id })
    toast.success(`已删除 ${out.deleted}`)
    if (drawer.visible && drawer.row && drawer.row.tmdb_id === row.tmdb_id && drawer.row.media_type === row.media_type) {
      drawer.visible = false
    }
    closeDeleteDialog()
    await loadList()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '删除失败')
  } finally {
    deleteDialog.deleting = false
  }
}

const MEDIA_OPTIONS: { label: string; value: MediaType }[] = [
  { label: '全部', value: '' },
  { label: 'tv', value: 'tv' },
  { label: 'movie', value: 'movie' },
]
const TTL_UNITS: { label: string; value: TTLUnit }[] = [
  { label: '分钟', value: 'minute' },
  { label: '小时', value: 'hour' },
  { label: '天', value: 'day' },
]

watch(
  () => drawer.tab,
  (tab) => {
    if (tab === 'payload') loadDrawerPayload()
  },
)

onMounted(refreshAll)
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">🎬 TMDB 缓存</h3>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">TMDB 详情缓存（任务统计/追剧信息复用），支持定时刷新、批量刷新与冷数据清理。</p>
      </div>
      <div class="flex items-center gap-2">
        <Badge v-if="!list.configured" variant="secondary" class="text-[10px]">TMDB 未配置</Badge>
        <Button variant="outline" size="sm" :disabled="list.loading || scheduler.loading" @click="refreshAll">
          <RefreshCw class="mr-1 h-3.5 w-3.5" :class="{ 'animate-spin': list.loading || scheduler.loading }" />
          刷新
        </Button>
      </div>
    </div>

    <!-- Sub tabs -->
    <div class="flex">
      <div class="inline-flex gap-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-1">
        <button
          v-for="tab in [{ key: 'list', label: '缓存列表' }, { key: 'tools', label: '工具' }, { key: 'scheduler', label: '定时刷新' }]"
          :key="tab.key"
          class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-all"
          :class="activeTab === tab.key
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="activeTab = (tab.key as 'list' | 'tools' | 'scheduler')"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- ========== 缓存列表 ========== -->
    <div v-show="activeTab === 'list'" class="space-y-4">
      <div class="flex flex-wrap items-center gap-3">
        <div class="flex rounded-md border border-[hsl(var(--border))]">
          <button
            v-for="opt in MEDIA_OPTIONS"
            :key="opt.value || 'all'"
            class="px-3 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md"
            :class="query.mediaType === opt.value
              ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
              : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]'"
            @click="query.mediaType = opt.value; searchList()"
          >
            {{ opt.label }}
          </button>
        </div>
        <Input v-model="query.keyword" placeholder="标题关键词" class="h-8 w-full text-sm sm:w-48" @keyup.enter="searchList" />
        <Input v-model="query.status" placeholder="status（精确匹配）" class="h-8 w-full text-sm sm:w-44" @keyup.enter="searchList" />
        <label class="flex cursor-pointer items-center gap-1.5 text-sm text-[hsl(var(--foreground))]">
          <input type="checkbox" v-model="query.expiredOnly" class="h-3.5 w-3.5 rounded border-[hsl(var(--border))]" @change="searchList" />
          仅过期
        </label>
        <Button size="sm" class="h-8 text-xs" :disabled="list.loading" @click="searchList">查询</Button>
        <Button v-if="filterActive" variant="ghost" size="sm" class="h-8 text-xs" @click="resetFilters">
          <X class="mr-1 h-3 w-3" /> 重置
        </Button>
      </div>

      <div class="overflow-x-auto overscroll-x-contain rounded-lg border border-[hsl(var(--border))]">
        <table class="w-full min-w-[820px] text-sm">
          <thead>
            <tr class="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">类型</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">ID</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">标题</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">年</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">状态</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">expires_at</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">fail</th>
              <th class="px-3 py-2 text-right font-medium text-[hsl(var(--muted-foreground))]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="list.loading"><td colspan="8" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">加载中...</td></tr>
            <tr v-else-if="list.items.length === 0"><td colspan="8" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">暂无缓存数据</td></tr>
            <tr
              v-for="row in list.items"
              :key="`${row.media_type}:${row.tmdb_id}`"
              class="cursor-pointer border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--muted))]/30"
              @dblclick="openDrawer(row)"
            >
              <td class="px-3 py-2 text-[hsl(var(--foreground))]">{{ row.media_type }}</td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.tmdb_id }}</td>
              <td class="px-3 py-2">
                <div class="font-medium text-[hsl(var(--foreground))]">{{ row.display_title || '-' }}</div>
                <div class="text-xs text-[hsl(var(--muted-foreground))]">{{ row.original_title || '' }}</div>
              </td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.year || '-' }}</td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.status || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ fmtTime(row.expires_at) }}</td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.fail_count || 0 }}</td>
              <td class="px-3 py-2 text-right">
                <div class="flex justify-end gap-1">
                  <Button variant="ghost" size="sm" class="h-7 px-2 text-xs" @click.stop="openDrawer(row)">详情</Button>
                  <Button variant="ghost" size="sm" class="h-7 w-7 p-0" title="强制刷新" @click.stop="refreshRow(row)"><RefreshCw class="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" class="h-7 w-7 p-0" title="设置 TTL" @click.stop="openTTLDialog(row)"><Timer class="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-red-500 hover:text-red-600" title="删除" @click.stop="openDeleteDialog(row)"><Trash2 class="h-3.5 w-3.5" /></Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between">
        <span class="text-xs text-[hsl(var(--muted-foreground))]">共 {{ list.total }} 条，第 {{ list.page }}/{{ listTotalPages }} 页</span>
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="list.page <= 1" @click="listPrev">上一页</Button>
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="list.page >= listTotalPages" @click="listNext">下一页</Button>
        </div>
      </div>
    </div>

    <!-- ========== 工具 ========== -->
    <div v-show="activeTab === 'tools'" class="space-y-4">
      <!-- Refresh linked -->
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <div class="text-sm font-semibold text-[hsl(var(--foreground))]">刷新任务关联缓存</div>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">从任务中提取已关联的 TMDB 条目并刷新其详情缓存。</p>
        <div class="mt-4 flex flex-wrap items-end gap-4">
          <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
            <ToggleSwitch v-model="tools.enabledOnly" /> 仅启用任务
          </label>
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">最多条目</div>
            <Input v-model.number="tools.maxItems" type="number" min="1" max="2000" class="h-8 w-28 text-sm" />
          </div>
          <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))]">
            <ToggleSwitch v-model="tools.force" /> 强制刷新
          </label>
          <Button size="sm" class="h-8 text-xs" :disabled="tools.refreshingLinked" @click="runRefreshLinkedTasks">
            <Loader2 v-if="tools.refreshingLinked" class="mr-1 h-3.5 w-3.5 animate-spin" />
            执行
          </Button>
        </div>
      </div>

      <!-- Purge cold -->
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <div class="text-sm font-semibold text-[hsl(var(--foreground))]">清理冷数据</div>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">删除长期未访问的缓存条目（保留近 N 天）。</p>
        <div class="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">保留天数</div>
            <Input v-model.number="tools.retentionDays" type="number" min="1" max="3650" class="h-8 w-28 text-sm" />
          </div>
          <Button variant="outline" size="sm" class="h-8 text-xs text-red-500 hover:text-red-600" :disabled="tools.purging" @click="runPurge">
            <Loader2 v-if="tools.purging" class="mr-1 h-3.5 w-3.5 animate-spin" />
            <Trash2 v-else class="mr-1 h-3.5 w-3.5" />
            清理
          </Button>
        </div>
      </div>

      <!-- Quick locate -->
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <div class="text-sm font-semibold text-[hsl(var(--foreground))]">快速定位（按 tmdb_id）</div>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">用于排查单个条目的缓存状态，支持查询与强制刷新。</p>
        <div class="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">类型</div>
            <div class="flex rounded-md border border-[hsl(var(--border))]">
              <button
                v-for="mt in ['tv', 'movie']"
                :key="mt"
                class="px-3 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md"
                :class="quick.mediaType === mt
                  ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                  : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]'"
                @click="quick.mediaType = (mt as 'tv' | 'movie')"
              >
                {{ mt }}
              </button>
            </div>
          </div>
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">tmdb_id</div>
            <Input
              type="number"
              min="1"
              class="h-8 w-32 text-sm"
              :model-value="quick.tmdbId ?? ''"
              @update:model-value="(v) => (quick.tmdbId = v === '' || v == null ? null : Number(v))"
              @keyup.enter="quickQuery"
            />
          </div>
          <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="quick.loading || !quick.tmdbId" @click="quickQuery">查询</Button>
          <Button size="sm" class="h-8 text-xs" :disabled="quick.loading || !quick.tmdbId" @click="quickRefresh">强刷</Button>
        </div>
        <div v-if="quick.status" class="mt-3 space-y-1 rounded-lg bg-[hsl(var(--muted))]/40 p-3 text-xs text-[hsl(var(--muted-foreground))]">
          <div>configured：{{ quick.status.configured ? 'true' : 'false' }} / exists：{{ quick.status.exists ? 'true' : 'false' }}</div>
          <div v-if="quick.status.display_title">标题：{{ quick.status.display_title }}（{{ quick.status.year || '-' }}）</div>
          <div v-if="quick.status.expires_at">expires_at：{{ fmtTime(quick.status.expires_at) }}</div>
          <div v-if="quick.status.last_error" class="text-red-500">last_error：{{ quick.status.last_error }}</div>
        </div>
      </div>
    </div>

    <!-- ========== 定时刷新 ========== -->
    <div v-show="activeTab === 'scheduler'" class="space-y-4">
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <div class="mb-4 flex items-center justify-between">
          <div class="text-sm font-semibold text-[hsl(var(--foreground))]">定时刷新设置</div>
          <Button size="sm" class="h-8 text-xs" :disabled="scheduler.saving" @click="saveScheduler">
            <Loader2 v-if="scheduler.saving" class="mr-1 h-3.5 w-3.5 animate-spin" />
            保存
          </Button>
        </div>
        <div class="space-y-4">
          <div class="flex items-center justify-between rounded-md bg-[hsl(var(--muted))]/40 px-3 py-2">
            <span class="text-sm font-medium text-[hsl(var(--foreground))]">启用</span>
            <ToggleSwitch v-model="scheduler.data.enabled" />
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">crontab</label>
              <Input v-model="scheduler.data.crontab" placeholder="0 */6 * * *" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">timezone</label>
              <Input v-model="scheduler.data.timezone" placeholder="Asia/Shanghai" />
            </div>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">每次最多刷新条目</label>
              <Input v-model.number="scheduler.data.max_items_per_run" type="number" min="1" max="2000" />
            </div>
            <div class="flex items-center justify-between rounded-md bg-[hsl(var(--muted))]/40 px-3 py-2">
              <span class="text-sm font-medium text-[hsl(var(--foreground))]">仅刷新任务关联条目</span>
              <ToggleSwitch v-model="scheduler.data.only_refresh_linked_tasks" />
            </div>
          </div>
          <div class="sm:w-1/2 sm:pr-2">
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">冷数据保留天数</label>
            <Input v-model.number="scheduler.data.retention_days" type="number" min="1" max="3650" />
          </div>
        </div>
      </div>
    </div>

    <!-- ========== Detail drawer ========== -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="drawer.visible" class="fixed inset-0 z-50 flex">
          <div class="absolute inset-0 bg-black/50" @click="drawer.visible = false" />
          <div class="relative z-10 ml-auto flex h-full w-full flex-col bg-[hsl(var(--card))] shadow-xl sm:w-[720px]">
            <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
              <div>
                <div class="text-base font-semibold text-[hsl(var(--foreground))]">{{ drawer.row?.display_title || '缓存详情' }}</div>
                <div class="text-xs text-[hsl(var(--muted-foreground))]">{{ drawer.row?.media_type }}:{{ drawer.row?.tmdb_id }}</div>
              </div>
              <Button variant="ghost" size="sm" class="h-7 w-7 p-0" @click="drawer.visible = false"><X class="h-4 w-4" /></Button>
            </div>

            <div class="flex-1 overflow-y-auto px-5 py-4">
              <div v-if="drawer.row" class="mb-4 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" class="h-8 text-xs" @click="refreshRow(drawer.row)"><RefreshCw class="mr-1 h-3.5 w-3.5" /> 强制刷新</Button>
                <Button variant="outline" size="sm" class="h-8 text-xs" @click="openTTLDialog(drawer.row)"><Timer class="mr-1 h-3.5 w-3.5" /> 设置 TTL</Button>
                <Button variant="outline" size="sm" class="h-8 text-xs text-red-500 hover:text-red-600" @click="openDeleteDialog(drawer.row)"><Trash2 class="mr-1 h-3.5 w-3.5" /> 删除</Button>
              </div>

              <div class="mb-4 flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-1">
                <button
                  v-for="t in [{ key: 'status', label: '状态' }, { key: 'payload', label: '缓存数据' }]"
                  :key="t.key"
                  class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-all"
                  :class="drawer.tab === t.key
                    ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
                    : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
                  @click="drawer.tab = (t.key as 'status' | 'payload')"
                >
                  {{ t.label }}
                </button>
              </div>

              <!-- Status -->
              <div v-show="drawer.tab === 'status'">
                <div v-if="drawer.loading" class="text-sm text-[hsl(var(--muted-foreground))]">加载中...</div>
                <div v-else-if="drawer.status" class="overflow-hidden rounded-lg border border-[hsl(var(--border))]">
                  <table class="w-full text-sm">
                    <tbody>
                      <tr v-for="kv in [
                        { k: 'configured', v: drawer.status.configured ? 'true' : 'false' },
                        { k: 'exists', v: drawer.status.exists ? 'true' : 'false' },
                        { k: 'fetched_at', v: fmtTime(drawer.status.fetched_at) },
                        { k: 'expires_at', v: fmtTime(drawer.status.expires_at) },
                        { k: 'last_accessed_at', v: fmtTime(drawer.status.last_accessed_at) },
                        { k: 'refresh_in_progress', v: drawer.status.refresh_in_progress ? 'true' : 'false' },
                        { k: 'fail_count', v: String(drawer.status.fail_count || 0) },
                      ]" :key="kv.k" class="border-b border-[hsl(var(--border))] last:border-b-0">
                        <td class="w-44 px-3 py-2 font-medium text-[hsl(var(--muted-foreground))]">{{ kv.k }}</td>
                        <td class="px-3 py-2 text-[hsl(var(--foreground))]">{{ kv.v }}</td>
                      </tr>
                      <tr v-if="drawer.status.last_error">
                        <td class="w-44 px-3 py-2 font-medium text-[hsl(var(--muted-foreground))]">last_error</td>
                        <td class="break-all px-3 py-2 text-red-500">{{ drawer.status.last_error }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Payload -->
              <div v-show="drawer.tab === 'payload'">
                <div class="mb-3 flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="drawer.payloadLoading" @click="loadDrawerPayload">
                    <Loader2 v-if="drawer.payloadLoading" class="mr-1 h-3.5 w-3.5 animate-spin" /> 加载
                  </Button>
                  <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="!drawerPayloadRaw" @click="copyDrawerPayloadRaw"><Copy class="mr-1 h-3.5 w-3.5" /> 复制原始</Button>
                  <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="!drawerPayloadRaw" @click="downloadDrawerPayload"><Download class="mr-1 h-3.5 w-3.5" /> 下载</Button>
                  <Badge v-if="drawer.payloadItem?.update_weekdays?.length" variant="secondary" class="text-[10px]">更新星期：{{ drawer.payloadItem?.update_weekdays?.join(',') }}</Badge>
                </div>
                <div v-if="drawerPayloadTooLarge" class="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">缓存数据过大：仅展示截断预览以避免页面卡顿。</div>
                <div v-if="drawer.payloadLoading" class="text-sm text-[hsl(var(--muted-foreground))]">加载中...</div>
                <div v-else-if="drawer.status && !drawer.status.exists" class="text-sm text-[hsl(var(--muted-foreground))]">未找到缓存条目（可能尚未写入缓存）</div>
                <div v-else-if="drawerPayloadText" class="overflow-hidden rounded-lg border border-[hsl(var(--border))]">
                  <div class="border-b border-[hsl(var(--border))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">大小：{{ drawerPayloadSize }} 字符</div>
                  <pre class="max-h-[60vh] overflow-auto whitespace-pre-wrap p-3 text-xs leading-relaxed text-[hsl(var(--foreground))]">{{ drawerPayloadText }}</pre>
                </div>
                <div v-else class="text-sm text-[hsl(var(--muted-foreground))]">无缓存数据</div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ========== TTL dialog ========== -->
    <div v-if="ttlDialog.visible" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" @click.self="ttlDialog.visible = false">
      <div class="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-2xl">
        <h3 class="mb-4 text-base font-semibold text-[hsl(var(--foreground))]">设置 TTL</h3>
        <div class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">目标：{{ ttlDialog.mediaType }}:{{ ttlDialog.tmdbId }}</div>
        <div class="flex items-end gap-3">
          <div class="flex-1">
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">数值</label>
            <Input v-model.number="ttlDialog.value" type="number" min="1" max="3650" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">单位</label>
            <div class="flex rounded-md border border-[hsl(var(--border))]">
              <button
                v-for="u in TTL_UNITS"
                :key="u.value"
                class="px-3 py-2 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md"
                :class="ttlDialog.unit === u.value
                  ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                  : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]'"
                @click="ttlDialog.unit = u.value"
              >
                {{ u.label }}
              </button>
            </div>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" @click="ttlDialog.visible = false">取消</Button>
          <Button size="sm" :disabled="ttlDialog.submitting" @click="submitTTL">
            <Loader2 v-if="ttlDialog.submitting" class="mr-1 h-3.5 w-3.5 animate-spin" /> 保存
          </Button>
        </div>
      </div>
    </div>

    <!-- ========== Delete dialog ========== -->
    <div v-if="deleteDialog.visible" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" @click.self="closeDeleteDialog">
      <div class="w-full max-w-md rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-2xl">
        <h3 class="mb-2 text-base font-semibold text-[hsl(var(--foreground))]">删除缓存</h3>
        <div class="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">
          删除的是「TMDB 详情缓存」，不影响 TMDB 配置；下次访问详情接口会重新写入缓存。
        </div>
        <div v-if="deleteDialog.row" class="space-y-1 rounded-lg bg-[hsl(var(--muted))]/40 p-3 text-sm">
          <div><span class="text-[hsl(var(--muted-foreground))]">条目：</span>{{ deleteDialog.row.media_type }}:{{ deleteDialog.row.tmdb_id }}</div>
          <div><span class="text-[hsl(var(--muted-foreground))]">标题：</span>{{ deleteDialog.row.display_title || '-' }}</div>
          <div class="text-xs text-[hsl(var(--muted-foreground))]">expires_at：{{ fmtTime(deleteDialog.row.expires_at) }}</div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" :disabled="deleteDialog.deleting" @click="closeDeleteDialog">取消</Button>
          <Button variant="outline" size="sm" class="text-red-500 hover:text-red-600" :disabled="deleteDialog.deleting" @click="confirmDelete">
            <Loader2 v-if="deleteDialog.deleting" class="mr-1 h-3.5 w-3.5 animate-spin" /> 删除
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s ease;
}
.drawer-enter-active > div:last-child,
.drawer-leave-active > div:last-child {
  transition: transform 0.2s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from > div:last-child,
.drawer-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
