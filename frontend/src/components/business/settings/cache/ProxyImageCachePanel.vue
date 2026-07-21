<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, Eraser, Trash2, Loader2 } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { clearProxyImageCache, fetchProxyImageCacheStats, purgeProxyImageCache } from '@/api/proxyImageCache'

const { toast } = useToast()
const queryClient = useQueryClient()

const { data: stats, isLoading, isFetching, refetch } = useQuery({
  queryKey: ['cache', 'proxy-image-stats'],
  queryFn: () => fetchProxyImageCacheStats(),
})

const purging = ref(false)
const clearing = ref(false)

function formatBytes(value: number | undefined) {
  const bytes = Number(value || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let num = bytes
  let idx = 0
  while (num >= 1024 && idx < units.length - 1) {
    num /= 1024
    idx += 1
  }
  return `${num.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`
}

async function invalidate() {
  await queryClient.invalidateQueries({ queryKey: ['cache'] })
}

async function handlePurge() {
  purging.value = true
  try {
    const out = await purgeProxyImageCache()
    toast.success(`已清理 ${out.deleted_files || 0} 项（${formatBytes(out.deleted_bytes || 0)}）`)
    await invalidate()
    await refetch()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '清理失败')
  } finally {
    purging.value = false
  }
}

async function handleClear() {
  if (!confirm('确认清空代理图片缓存目录？此操作不可恢复。')) return
  clearing.value = true
  try {
    const out = await clearProxyImageCache()
    toast.success(`已清空 ${out.deleted_files || 0} 项（${formatBytes(out.deleted_bytes || 0)}）`)
    await invalidate()
    await refetch()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '清空失败')
  } finally {
    clearing.value = false
  }
}

const rows = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: '缓存目录', value: s.cache_dir || '-', mono: true },
    { label: 'TTL（秒）', value: String(s.ttl_seconds ?? 0) },
    { label: '单文件上限', value: formatBytes(s.max_file_bytes) },
    { label: '总容量上限', value: formatBytes(s.max_total_bytes) },
    { label: '文件数', value: String(s.total_files ?? 0) },
    { label: '占用空间', value: formatBytes(s.total_bytes) },
    { label: '过期文件', value: String(s.stale_files ?? 0) },
  ]
})
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">🖼️ 代理图片缓存</h3>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">影视发现海报/图片代理的本地磁盘缓存。</p>
      </div>
      <div class="flex items-center gap-2">
        <Badge :variant="stats?.enabled ? 'default' : 'secondary'" class="text-[10px]">
          {{ stats?.enabled ? '已启用' : '已禁用' }}
        </Badge>
        <Button variant="outline" size="sm" :disabled="isFetching" @click="refetch()">
          <RefreshCw class="mr-1 h-3.5 w-3.5" :class="{ 'animate-spin': isFetching }" />
          刷新
        </Button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
    </div>

    <template v-else>
      <!-- Stats -->
      <div class="overflow-hidden rounded-lg border border-[hsl(var(--border))]">
        <table class="w-full text-sm">
          <tbody>
            <tr
              v-for="(row, idx) in rows"
              :key="row.label"
              class="border-b border-[hsl(var(--border))] last:border-b-0"
              :class="idx % 2 === 1 ? 'bg-[hsl(var(--muted))]/30' : ''"
            >
              <td class="w-40 px-3 py-2 font-medium text-[hsl(var(--muted-foreground))]">{{ row.label }}</td>
              <td
                class="break-all px-3 py-2 text-[hsl(var(--foreground))]"
                :class="row.mono ? 'font-mono text-xs' : ''"
              >
                {{ row.value }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Actions -->
      <div class="flex flex-wrap justify-end gap-2">
        <Button variant="outline" size="sm" :disabled="purging" @click="handlePurge">
          <Loader2 v-if="purging" class="mr-1 h-3.5 w-3.5 animate-spin" />
          <Eraser v-else class="mr-1 h-3.5 w-3.5" />
          清理过期
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="text-red-500 hover:text-red-600"
          :disabled="clearing"
          @click="handleClear"
        >
          <Loader2 v-if="clearing" class="mr-1 h-3.5 w-3.5 animate-spin" />
          <Trash2 v-else class="mr-1 h-3.5 w-3.5" />
          一键清空
        </Button>
      </div>
    </template>
  </div>
</template>
