<script setup lang="ts">
import { computed } from 'vue'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Play, Square, Trash2, Pencil, Power, FolderInput, FolderOutput, FileText } from 'lucide-vue-next'
import type { SyncTaskItem } from '@/types/syncTasks'

interface Props {
  task: SyncTaskItem
  selected?: boolean
  running?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  running: false,
})

const emit = defineEmits<{
  select: [task: SyncTaskItem]
  run: [task: SyncTaskItem]
  stop: [task: SyncTaskItem]
  edit: [task: SyncTaskItem]
  delete: [task: SyncTaskItem]
  toggle: [task: SyncTaskItem]
  viewLog: [task: SyncTaskItem]
}>()

const statusLabel = computed(() => {
  if (props.running) return '运行中'
  if (!props.task.enabled) return '已禁用'
  return '空闲'
})

const statusClass = computed(() => {
  if (props.running)
    return 'border-transparent bg-[hsl(var(--chart-2))]/15 text-[hsl(var(--chart-2))]'
  if (!props.task.enabled)
    return 'border-transparent bg-[hsl(var(--destructive))]/15 text-[hsl(var(--destructive))]'
  return 'border-transparent bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
})

function typeTag(type: string) {
  if (type === 'local') return '本地'
  if (type === 'netdisk') return '网盘'
  return 'OpenList'
}

function endpointPath(ep: { type: string; path: string; account_name?: string | null }) {
  const account = ep.account_name ? `[${ep.account_name}]` : ''
  return `${account} ${ep.path}`
}

const modeLabel = computed(() => props.task.mode === 'one_way' ? '单向' : '双向')

const lastTime = computed(() => {
  if (!props.task.updated_at) return '—'
  try {
    const d = new Date(props.task.updated_at)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return '—'
  }
})
</script>

<template>
  <Card
    class="flex flex-col gap-3 p-4 cursor-pointer transition-all hover:shadow-md"
    :class="[
      selected ? 'ring-2 ring-[hsl(var(--primary))]' : '',
      !task.enabled && !running ? 'grayscale-[60%] opacity-70' : '',
    ]"
    @click="emit('select', task)"
  >
    <!-- Row 1: Name + Status -->
    <div class="flex items-center justify-between gap-2">
      <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] line-clamp-1 flex-1 min-w-0">
        {{ task.name }}
      </h3>
      <div class="flex items-center gap-1.5 flex-shrink-0">
        <!-- Pulse dot for running -->
        <span
          v-if="running"
          class="relative flex h-2 w-2"
        >
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-[hsl(var(--chart-2))] opacity-75" />
          <span class="relative inline-flex rounded-full h-2 w-2 bg-[hsl(var(--chart-2))]" />
        </span>
        <Badge :class="statusClass" class="text-[10px] px-1.5 py-0">
          {{ statusLabel }}
        </Badge>
      </div>
    </div>

    <!-- Row 2: Source path -->
    <div class="space-y-1 text-xs text-[hsl(var(--muted-foreground))]">
      <div class="flex items-center gap-1.5 min-w-0">
        <FolderOutput class="h-3.5 w-3.5 flex-shrink-0 text-[hsl(var(--chart-1))]" />
        <span class="inline-flex items-center px-1 py-0 rounded text-[10px] font-medium bg-[hsl(var(--chart-1))]/10 text-[hsl(var(--chart-1))]">
          {{ typeTag(task.source.type) }}
        </span>
        <span class="truncate flex-1 min-w-0" :title="task.source.path">{{ endpointPath(task.source) }}</span>
      </div>
      <!-- Row 3: Target path -->
      <div class="flex items-center gap-1.5 min-w-0">
        <FolderInput class="h-3.5 w-3.5 flex-shrink-0 text-[hsl(var(--chart-4))]" />
        <span class="inline-flex items-center px-1 py-0 rounded text-[10px] font-medium bg-[hsl(var(--chart-4))]/10 text-[hsl(var(--chart-4))]">
          {{ typeTag(task.target.type) }}
        </span>
        <span class="truncate flex-1 min-w-0" :title="task.target.path">{{ endpointPath(task.target) }}</span>
      </div>
    </div>

    <!-- Row 4: Metadata compact line -->
    <div class="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
      <span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-[hsl(var(--muted))]">
        {{ modeLabel }}
      </span>
      <span class="text-[hsl(var(--border))]">│</span>
      <span>并发: {{ task.strategy.concurrency }}</span>
      <span class="text-[hsl(var(--border))]">│</span>
      <span>最近: {{ lastTime }}</span>
    </div>

    <!-- Row 5: Actions -->
    <div class="flex items-center gap-1 pt-1 border-t border-[hsl(var(--border))]">
      <Button
        v-if="running"
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        title="停止"
        @click.stop="emit('stop', task)"
      >
        <Square class="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />
      </Button>
      <Button
        v-else
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        title="运行"
        @click.stop="emit('run', task)"
      >
        <Play class="h-3.5 w-3.5 text-[hsl(var(--chart-2))]" />
      </Button>
      <Button
        v-if="running"
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        title="查看日志"
        @click.stop="emit('viewLog', task)"
      >
        <FileText class="h-3.5 w-3.5 text-[hsl(var(--chart-1))]" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        title="编辑"
        @click.stop="emit('edit', task)"
      >
        <Pencil class="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        :title="task.enabled ? '禁用' : '启用'"
        @click.stop="emit('toggle', task)"
      >
        <Power class="h-3.5 w-3.5" :class="task.enabled ? 'text-[hsl(var(--chart-2))]' : 'text-[hsl(var(--muted-foreground))]'" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7 text-[hsl(var(--destructive))] hover:text-red-600"
        title="删除"
        @click.stop="emit('delete', task)"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </Button>
    </div>
  </Card>
</template>
