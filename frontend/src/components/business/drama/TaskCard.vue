<script setup lang="ts">
import { computed } from 'vue'
import type { TaskItem } from '@/types/tasks'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Play, Zap, Pencil, Trash2, Power } from 'lucide-vue-next'

const props = defineProps<{
  task: TaskItem
}>()

const emit = defineEmits<{
  run: [task: TaskItem]
  'run-once': [task: TaskItem]
  edit: [task: TaskItem]
  delete: [task: TaskItem]
  'toggle-status': [task: TaskItem]
}>()

function statusLabel(task: TaskItem) {
  if (!task.enabled) return '暂停'
  if (task.shareurl_ban) return '错误'
  return '运行中'
}

function statusVariant(task: TaskItem) {
  if (!task.enabled) return 'secondary'
  if (task.shareurl_ban) return 'destructive'
  return 'default'
}

function statusClass(task: TaskItem) {
  if (!task.enabled) return 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
  if (task.shareurl_ban) return 'bg-red-100 text-red-700 border-red-200'
  return 'bg-green-100 text-green-700 border-green-200'
}

function truncate(str: string | undefined | null, len = 40) {
  if (!str) return '-'
  return str.length > len ? str.slice(0, len) + '...' : str
}

function formatTime(dateStr: string | undefined | null) {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

function lastRunTime(task: TaskItem) {
  const execs = task.executions || []
  if (!execs.length) return '-'
  const last = execs[execs.length - 1]
  return formatTime(last.started_at)
}

const isEnded = computed(() => props.task.tmdb_is_ended === true || props.task.extra?.ended === true)
const progressText = computed(() => {
  const p = props.task.drama_update_progress
  if (!p?.tmdb_episode) return ''
  return `更新至 第${p.tmdb_episode}集`
})
</script>

<template>
  <Card class="flex flex-col gap-3 p-4">
    <!-- Top: name + status -->
    <div class="flex items-start justify-between gap-2">
      <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] line-clamp-1 flex-1">
        {{ task.taskname }}
      </h3>
      <div class="flex items-center gap-1.5 flex-shrink-0">
        <Badge
          v-if="isEnded"
          class="bg-emerald-100 text-emerald-700 border-emerald-200 text-[10px] px-1.5 py-0"
          variant="outline"
        >
          已完结
        </Badge>
        <Badge :variant="statusVariant(task)" :class="statusClass(task)">
          {{ statusLabel(task) }}
        </Badge>
      </div>
    </div>

    <!-- Progress info -->
    <div v-if="progressText" class="text-xs text-[hsl(var(--muted-foreground))]">
      <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]">
        {{ progressText }}
      </span>
    </div>

    <!-- Middle: source + savepath -->
    <div class="space-y-1 text-xs text-[hsl(var(--muted-foreground))]">
      <div class="truncate" :title="task.shareurl">
        <span class="font-medium">来源：</span>{{ truncate(task.shareurl, 36) }}
      </div>
      <div class="truncate" :title="task.savepath">
        <span class="font-medium">保存：</span>{{ task.savepath || '-' }}
      </div>
    </div>

    <!-- Bottom: time + actions -->
    <div class="flex items-center justify-between pt-1 border-t border-[hsl(var(--border))]">
      <span class="text-xs text-[hsl(var(--muted-foreground))]">
        {{ lastRunTime(task) }}
      </span>
      <div class="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          class="h-7 w-7"
          title="运行"
          @click="emit('run', task)"
        >
          <Play class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-7 w-7"
          title="运行一次（不保存）"
          @click.stop="$emit('run-once', task)"
        >
          <Zap class="h-3.5 w-3.5" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          class="h-7 w-7"
          :title="task.enabled ? '暂停' : '启用'"
          @click="emit('toggle-status', task)"
        >
          <Power class="h-3.5 w-3.5" :class="task.enabled ? 'text-green-500' : 'text-[hsl(var(--muted-foreground))]'" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-7 w-7"
          title="编辑"
          @click="emit('edit', task)"
        >
          <Pencil class="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-7 w-7 text-red-500 hover:text-red-600"
          title="删除"
          @click="emit('delete', task)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  </Card>
</template>
