<script setup lang="ts">
import { computed, onMounted, reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, Search, X, Trash2, Eraser, MemoryStick, Loader2 } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import {
  clearInvalidShareLinks,
  clearSharePreviewBatchMemoryCache,
  deleteInvalidShareLink,
  deleteSharePreviewBatchCacheItem,
  fetchInvalidShareLinksList,
  fetchSharePreviewBatchCacheList,
  purgeSharePreviewBatchCache,
} from '@/api/shareLinkCache'
import type { InvalidShareLinkListItem, SharePreviewBatchCacheListItem } from '@/types/shareLinkCache'

const { toast } = useToast()

type OkFilter = 'all' | 'ok' | 'fail'
const activeTab = ref<'cache' | 'invalid'>('cache')

const cache = reactive({
  loading: false,
  busy: false,
  items: [] as SharePreviewBatchCacheListItem[],
  total: 0,
  query: {
    page: 1,
    page_size: 20,
    q: '',
    drive_type: '',
    ok: 'all' as OkFilter,
    expired_only: false,
  },
})

const invalid = reactive({
  loading: false,
  busy: false,
  items: [] as InvalidShareLinkListItem[],
  total: 0,
  query: {
    page: 1,
    page_size: 20,
    q: '',
    drive_type: '',
  },
})

const cacheOkParam = computed(() => {
  if (cache.query.ok === 'ok') return true
  if (cache.query.ok === 'fail') return false
  return undefined
})

const cacheTotalPages = computed(() => Math.max(1, Math.ceil(cache.total / cache.query.page_size)))
const invalidTotalPages = computed(() => Math.max(1, Math.ceil(invalid.total / invalid.query.page_size)))

function fmtTime(value?: string | null) {
  if (!value) return '-'
  const s = String(value)
  const hasTz = /([zZ]|[+-]\d{2}:\d{2})$/.test(s)
  const d = new Date(hasTz ? s : `${s}Z`)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('zh-CN', { hour12: false })
}

async function loadCache() {
  cache.loading = true
  try {
    const data = await fetchSharePreviewBatchCacheList({
      page: cache.query.page,
      page_size: cache.query.page_size,
      q: cache.query.q || undefined,
      drive_type: cache.query.drive_type || undefined,
      ok: cacheOkParam.value,
      expired_only: cache.query.expired_only || undefined,
    })
    cache.items = data.items || []
    cache.total = data.total || 0
  } finally {
    cache.loading = false
  }
}

async function loadInvalid() {
  invalid.loading = true
  try {
    const data = await fetchInvalidShareLinksList({
      page: invalid.query.page,
      page_size: invalid.query.page_size,
      q: invalid.query.q || undefined,
      drive_type: invalid.query.drive_type || undefined,
    })
    invalid.items = data.items || []
    invalid.total = data.total || 0
  } finally {
    invalid.loading = false
  }
}

function searchCache() {
  cache.query.page = 1
  loadCache()
}
function searchInvalid() {
  invalid.query.page = 1
  loadInvalid()
}

function resetCacheFilters() {
  cache.query.q = ''
  cache.query.drive_type = ''
  cache.query.ok = 'all'
  cache.query.expired_only = false
  cache.query.page = 1
  loadCache()
}
function resetInvalidFilters() {
  invalid.query.q = ''
  invalid.query.drive_type = ''
  invalid.query.page = 1
  loadInvalid()
}

const cacheFilterActive = computed(
  () => Boolean(cache.query.q || cache.query.drive_type || cache.query.ok !== 'all' || cache.query.expired_only),
)
const invalidFilterActive = computed(() => Boolean(invalid.query.q || invalid.query.drive_type))

async function handleDeleteCacheItem(shareurl: string) {
  try {
    const out = await deleteSharePreviewBatchCacheItem({ shareurl })
    toast.success(`已删除 ${out.deleted || 0} 条`)
    await loadCache()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '删除失败')
  }
}

async function handleDeleteInvalidItem(shareurl: string) {
  try {
    const out = await deleteInvalidShareLink({ shareurl })
    toast.success(`已删除 ${out.deleted || 0} 条`)
    await loadInvalid()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '删除失败')
  }
}

async function runCacheAction(kind: 'expired' | 'history' | 'memory') {
  cache.busy = true
  try {
    if (kind === 'memory') {
      const out = await clearSharePreviewBatchMemoryCache()
      if (out.cleared) toast.success('已清空进程内缓存（仅对当前后端进程生效）')
      return
    }
    const out = await purgeSharePreviewBatchCache({
      expired_only: kind === 'expired',
      retention_seconds: 0,
    })
    toast.success(`已清理 ${out.deleted || 0} 条${kind === 'expired' ? '过期' : '历史'}缓存`)
    await loadCache()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '操作失败')
  } finally {
    cache.busy = false
  }
}

async function handleClearInvalidAll() {
  if (!confirm('确认清空所有「永久异常 shareurl」？这会影响资源搜索/修复的失效过滤。')) return
  invalid.busy = true
  try {
    const out = await clearInvalidShareLinks({})
    toast.success(`已清空 ${out.deleted || 0} 条`)
    await loadInvalid()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '清空失败')
  } finally {
    invalid.busy = false
  }
}

function cachePrev() {
  if (cache.query.page > 1) {
    cache.query.page--
    loadCache()
  }
}
function cacheNext() {
  if (cache.query.page < cacheTotalPages.value) {
    cache.query.page++
    loadCache()
  }
}
function invalidPrev() {
  if (invalid.query.page > 1) {
    invalid.query.page--
    loadInvalid()
  }
}
function invalidNext() {
  if (invalid.query.page < invalidTotalPages.value) {
    invalid.query.page++
    loadInvalid()
  }
}

const OK_OPTIONS: { label: string; value: OkFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '成功', value: 'ok' },
  { label: '失败', value: 'fail' },
]

onMounted(() => {
  loadCache()
  loadInvalid()
})
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">🔗 分享链接缓存</h3>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">分享预览批量缓存与永久异常 shareurl 管理。</p>
      </div>
      <Button
        variant="outline"
        size="sm"
        :disabled="cache.loading || invalid.loading"
        @click="activeTab === 'cache' ? loadCache() : loadInvalid()"
      >
        <RefreshCw class="mr-1 h-3.5 w-3.5" :class="{ 'animate-spin': cache.loading || invalid.loading }" />
        刷新
      </Button>
    </div>

    <!-- Sub tabs -->
    <div class="flex">
      <div class="inline-flex gap-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-1">
        <button
          v-for="tab in [{ key: 'cache', label: '预览缓存' }, { key: 'invalid', label: '永久异常' }]"
          :key="tab.key"
          class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-all"
          :class="activeTab === tab.key
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="activeTab = (tab.key as 'cache' | 'invalid')"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- ========== 预览缓存 ========== -->
    <div v-show="activeTab === 'cache'" class="space-y-4">
      <!-- Filters -->
      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-full sm:w-72">
          <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <Input v-model="cache.query.q" placeholder="搜索 shareurl..." class="h-8 pl-8 text-sm" @keyup.enter="searchCache" />
        </div>
        <Input v-model="cache.query.drive_type" placeholder="drive_type（可选）" class="h-8 w-full text-sm sm:w-44" @keyup.enter="searchCache" />
        <div class="flex rounded-md border border-[hsl(var(--border))]">
          <button
            v-for="opt in OK_OPTIONS"
            :key="opt.value"
            class="px-3 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md"
            :class="cache.query.ok === opt.value
              ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
              : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]'"
            @click="cache.query.ok = opt.value; searchCache()"
          >
            {{ opt.label }}
          </button>
        </div>
        <label class="flex cursor-pointer items-center gap-1.5 text-sm text-[hsl(var(--foreground))]">
          <input type="checkbox" v-model="cache.query.expired_only" class="h-3.5 w-3.5 rounded border-[hsl(var(--border))]" @change="searchCache" />
          仅过期
        </label>
        <Button size="sm" class="h-8 text-xs" :disabled="cache.loading" @click="searchCache">查询</Button>
        <Button v-if="cacheFilterActive" variant="ghost" size="sm" class="h-8 text-xs" @click="resetCacheFilters">
          <X class="mr-1 h-3 w-3" /> 清除筛选
        </Button>
      </div>

      <!-- Bulk actions -->
      <div class="flex flex-wrap justify-end gap-2">
        <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="cache.busy" @click="runCacheAction('memory')">
          <MemoryStick class="mr-1 h-3.5 w-3.5" /> 清空内存缓存
        </Button>
        <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="cache.busy" @click="runCacheAction('expired')">
          <Eraser class="mr-1 h-3.5 w-3.5" /> 清理过期
        </Button>
        <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="cache.busy" @click="runCacheAction('history')">
          <Trash2 class="mr-1 h-3.5 w-3.5" /> 清理历史
        </Button>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto overscroll-x-contain rounded-lg border border-[hsl(var(--border))]">
        <table class="w-full min-w-[840px] text-sm">
          <thead>
            <tr class="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">shareurl</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">drive_type</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">结果</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">message</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">expires_at</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">hit</th>
              <th class="px-3 py-2 text-right font-medium text-[hsl(var(--muted-foreground))]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="cache.loading"><td colspan="7" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">加载中...</td></tr>
            <tr v-else-if="cache.items.length === 0"><td colspan="7" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">暂无缓存数据</td></tr>
            <tr v-for="row in cache.items" :key="row.shareurl" class="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--muted))]/30">
              <td class="max-w-[280px] truncate px-3 py-2 font-mono text-xs text-[hsl(var(--foreground))]" :title="row.shareurl">{{ row.shareurl }}</td>
              <td class="px-3 py-2 text-[hsl(var(--foreground))]">{{ row.drive_type || '-' }}</td>
              <td class="px-3 py-2">
                <Badge :variant="row.ok ? 'default' : 'destructive'" class="text-[10px]">{{ row.ok ? 'OK' : 'FAIL' }}</Badge>
              </td>
              <td class="max-w-[220px] truncate px-3 py-2 text-[hsl(var(--muted-foreground))]" :title="row.message || ''">{{ row.message || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ fmtTime(row.expires_at) }}</td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.hit_count ?? 0 }}</td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-red-500 hover:text-red-600" @click="handleDeleteCacheItem(row.shareurl)">
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between">
        <span class="text-xs text-[hsl(var(--muted-foreground))]">共 {{ cache.total }} 条，第 {{ cache.query.page }}/{{ cacheTotalPages }} 页</span>
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="cache.query.page <= 1" @click="cachePrev">上一页</Button>
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="cache.query.page >= cacheTotalPages" @click="cacheNext">下一页</Button>
        </div>
      </div>
    </div>

    <!-- ========== 永久异常 ========== -->
    <div v-show="activeTab === 'invalid'" class="space-y-4">
      <!-- Filters -->
      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-full sm:w-72">
          <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <Input v-model="invalid.query.q" placeholder="搜索 shareurl..." class="h-8 pl-8 text-sm" @keyup.enter="searchInvalid" />
        </div>
        <Input v-model="invalid.query.drive_type" placeholder="drive_type（可选）" class="h-8 w-full text-sm sm:w-44" @keyup.enter="searchInvalid" />
        <Button size="sm" class="h-8 text-xs" :disabled="invalid.loading" @click="searchInvalid">查询</Button>
        <Button v-if="invalidFilterActive" variant="ghost" size="sm" class="h-8 text-xs" @click="resetInvalidFilters">
          <X class="mr-1 h-3 w-3" /> 清除筛选
        </Button>
        <div class="flex-1" />
        <Button variant="outline" size="sm" class="h-8 text-xs text-red-500 hover:text-red-600" :disabled="invalid.busy" @click="handleClearInvalidAll">
          <Loader2 v-if="invalid.busy" class="mr-1 h-3.5 w-3.5 animate-spin" />
          <Trash2 v-else class="mr-1 h-3.5 w-3.5" />
          清空全部
        </Button>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto overscroll-x-contain rounded-lg border border-[hsl(var(--border))]">
        <table class="w-full min-w-[760px] text-sm">
          <thead>
            <tr class="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">shareurl</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">drive_type</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">message</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">hit</th>
              <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">updated_at</th>
              <th class="px-3 py-2 text-right font-medium text-[hsl(var(--muted-foreground))]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="invalid.loading"><td colspan="6" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">加载中...</td></tr>
            <tr v-else-if="invalid.items.length === 0"><td colspan="6" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">暂无异常记录</td></tr>
            <tr v-for="row in invalid.items" :key="row.shareurl" class="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--muted))]/30">
              <td class="max-w-[300px] truncate px-3 py-2 font-mono text-xs text-[hsl(var(--foreground))]" :title="row.shareurl">{{ row.shareurl }}</td>
              <td class="px-3 py-2 text-[hsl(var(--foreground))]">{{ row.drive_type || '-' }}</td>
              <td class="max-w-[240px] truncate px-3 py-2 text-[hsl(var(--muted-foreground))]" :title="row.message || ''">{{ row.message || '-' }}</td>
              <td class="px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ row.hit_count ?? 0 }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-[hsl(var(--muted-foreground))]">{{ fmtTime(row.updated_at) }}</td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-red-500 hover:text-red-600" @click="handleDeleteInvalidItem(row.shareurl)">
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between">
        <span class="text-xs text-[hsl(var(--muted-foreground))]">共 {{ invalid.total }} 条，第 {{ invalid.query.page }}/{{ invalidTotalPages }} 页</span>
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="invalid.query.page <= 1" @click="invalidPrev">上一页</Button>
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="invalid.query.page >= invalidTotalPages" @click="invalidNext">下一页</Button>
        </div>
      </div>
    </div>
  </div>
</template>
