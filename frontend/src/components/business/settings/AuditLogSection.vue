<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, Search, X } from 'lucide-vue-next'
import { fetchAuditLogs } from '@/api/audit'
import type { AuditLogItem } from '@/types/audit'

const loading = ref(false)
const items = ref<AuditLogItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 20,
  q: '',
  action: '',
  success: 'all' as 'all' | 'success' | 'failed',
})

const successParam = computed(() => {
  if (query.success === 'success') return true
  if (query.success === 'failed') return false
  return undefined
})

const totalPages = computed(() => Math.ceil(total.value / query.page_size))

async function loadData() {
  loading.value = true
  try {
    const data = await fetchAuditLogs({
      page: query.page,
      page_size: query.page_size,
      q: query.q || undefined,
      action: query.action || undefined,
      success: successParam.value,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  query.q = ''
  query.action = ''
  query.success = 'all'
  query.page = 1
  loadData()
}

function prevPage() {
  if (query.page > 1) {
    query.page--
    loadData()
  }
}

function nextPage() {
  if (query.page < totalPages.value) {
    query.page++
    loadData()
  }
}

function formatTime(dt: string) {
  if (!dt) return '-'
  const d = new Date(dt)
  return d.toLocaleString('zh-CN', { hour12: false })
}

// Initial load
loadData()
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-5 flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">📜 审计日志</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">查看系统操作记录</p>
      </div>
      <Button variant="outline" size="sm" :disabled="loading" @click="loadData">
        <RefreshCw class="mr-1 h-3.5 w-3.5" :class="{ 'animate-spin': loading }" />
        刷新
      </Button>
    </div>

    <!-- Filter bar -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <!-- Keyword search -->
      <div class="relative w-full sm:w-64">
        <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
        <Input
          v-model="query.q"
          placeholder="搜索操作/用户/详情..."
          class="h-8 pl-8 text-sm"
          @keyup.enter="() => { query.page = 1; loadData() }"
        />
      </div>

      <!-- Action filter -->
      <Input
        v-model="query.action"
        placeholder="操作类型"
        class="h-8 w-full text-sm sm:w-40"
        @keyup.enter="() => { query.page = 1; loadData() }"
      />

      <!-- Status segmented -->
      <div class="flex rounded-md border border-[hsl(var(--border))]">
        <button
          v-for="opt in [
            { label: '全部', value: 'all' },
            { label: '成功', value: 'success' },
            { label: '失败', value: 'failed' },
          ]"
          :key="opt.value"
          class="px-3 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md"
          :class="query.success === opt.value
            ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
            : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]'"
          @click="() => { query.success = opt.value as any; query.page = 1; loadData() }"
        >
          {{ opt.label }}
        </button>
      </div>

      <!-- Reset -->
      <Button v-if="query.q || query.action || query.success !== 'all'" variant="ghost" size="sm" class="h-8 text-xs" @click="resetFilters">
        <X class="mr-1 h-3 w-3" />
        清除筛选
      </Button>
    </div>

    <!-- Table -->
    <div class="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">时间</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">用户</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">操作</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">目标</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">状态</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">IP</th>
            <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">详情</th>
          </tr>
        </thead>
        <tbody>
          <!-- Loading -->
          <tr v-if="loading">
            <td colspan="7" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">
              加载中...
            </td>
          </tr>
          <!-- Empty -->
          <tr v-else-if="items.length === 0">
            <td colspan="7" class="px-3 py-8 text-center text-[hsl(var(--muted-foreground))]">
              暂无日志记录
            </td>
          </tr>
          <!-- Rows -->
          <tr
            v-for="row in items"
            :key="row.id"
            class="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--muted)/.5)]"
          >
            <td class="whitespace-nowrap px-3 py-2 text-[hsl(var(--foreground))]">
              {{ formatTime(row.created_at) }}
            </td>
            <td class="px-3 py-2 text-[hsl(var(--foreground))]">
              {{ row.actor_username || (row.actor_user_id ? `#${row.actor_user_id}` : '-') }}
            </td>
            <td class="px-3 py-2">
              <code class="rounded bg-[hsl(var(--muted))] px-1.5 py-0.5 text-xs text-[hsl(var(--foreground))]">
                {{ row.action }}
              </code>
            </td>
            <td class="px-3 py-2 text-[hsl(var(--foreground))]">
              <span>{{ row.target_type || '-' }}</span>
              <span v-if="row.target_id" class="text-[hsl(var(--muted-foreground))]">:{{ row.target_id }}</span>
            </td>
            <td class="px-3 py-2">
              <Badge :variant="row.success ? 'default' : 'destructive'" class="text-xs">
                {{ row.success ? '成功' : '失败' }}
              </Badge>
            </td>
            <td class="whitespace-nowrap px-3 py-2 text-[hsl(var(--muted-foreground))]">
              {{ row.ip || '-' }}
            </td>
            <td class="max-w-[240px] truncate px-3 py-2 text-[hsl(var(--muted-foreground))]" :title="row.detail || ''">
              {{ row.detail || '-' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="mt-4 flex items-center justify-between">
      <span class="text-xs text-[hsl(var(--muted-foreground))]">
        共 {{ total }} 条，第 {{ query.page }}/{{ totalPages || 1 }} 页
      </span>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="query.page <= 1" @click="prevPage">
          上一页
        </Button>
        <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="query.page >= totalPages" @click="nextPage">
          下一页
        </Button>
      </div>
    </div>
  </div>
</template>
