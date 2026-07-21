<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import MediaDiscover from '@/components/business/drama/MediaDiscover.vue'
import CreateTaskSheet from '@/components/business/drama/CreateTaskSheet.vue'
import StreamLogDialog from '@/components/business/common/StreamLogDialog.vue'
import { useTasksQuery } from '@/hooks/queries/tasks'
import type { TaskItem } from '@/types/tasks'

const route = useRoute()
const initialQuery = computed(() => String(route.query.q || ''))

const { data: tasks } = useTasksQuery()

// Find an existing drama task already bound to the given TMDB id + media type.
function findExistingTask(tmdbId: number, mediaType: string): TaskItem | undefined {
  if (!tmdbId) return undefined
  return (tasks.value || []).find(
    (t) =>
      t.task_type === 'drama' &&
      Number(t.tmdb_id) === tmdbId &&
      String(t.tmdb_media_type || '').toLowerCase() === mediaType,
  )
}

// Set of "mediaType:tmdbId" for tasks already tracked (drives edit vs add button).
const trackedKeys = computed(() => {
  const s = new Set<string>()
  for (const t of tasks.value || []) {
    if (t.task_type !== 'drama') continue
    const id = Number(t.tmdb_id) || 0
    if (id <= 0) continue
    const mt = String(t.tmdb_media_type || '').toLowerCase()
    if (mt) s.add(`${mt}:${id}`)
  }
  return s
})

// Create task sheet
const sheetOpen = ref(false)
const editingTask = ref<TaskItem | undefined>(undefined)
const presetTmdb = ref<{ tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string } | null>(null)

// Stream log
const showStreamLog = ref(false)
const streamLogUrl = ref('')
const streamLogTitle = ref('执行日志')
const streamLogMethod = ref<'GET' | 'POST'>('GET')
const streamLogBody = ref<Record<string, any> | null>(null)

function openCreateWithTMDB(payload: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string }) {
  const existing = findExistingTask(payload.tmdb_id, payload.tmdb_media_type)
  if (existing) {
    // Already tracked → open the existing task for editing instead of creating a new one.
    presetTmdb.value = null
    editingTask.value = existing
  } else {
    editingTask.value = undefined
    presetTmdb.value = payload
  }
  sheetOpen.value = true
}

function handleSheetClose() {
  sheetOpen.value = false
  editingTask.value = undefined
  presetTmdb.value = null
}

function handleRunOnce(payload: Record<string, any>) {
  streamLogTitle.value = `运行一次：${payload.taskname || '任务'}`
  streamLogUrl.value = '/api/tasks/run/stream'
  streamLogMethod.value = 'POST'
  streamLogBody.value = payload
  showStreamLog.value = true
  sheetOpen.value = false
  editingTask.value = undefined
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="border-b border-[hsl(var(--border))] px-6 pt-5 pb-4">
      <h1 class="text-2xl font-bold text-[hsl(var(--foreground))]">🔍 影视发现</h1>
      <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">浏览豆瓣分类或搜索 TMDB，一键加入追剧</p>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-6">
      <div class="mx-auto max-w-6xl">
        <MediaDiscover :initial-query="initialQuery" :tracked-keys="trackedKeys" @add-task="openCreateWithTMDB" />
      </div>
    </div>

    <!-- Create/Edit Task Sheet -->
    <CreateTaskSheet
      :open="sheetOpen"
      :edit-task="editingTask"
      :preset-tmdb="presetTmdb"
      @close="handleSheetClose"
      @run-once="handleRunOnce"
    />

    <!-- Stream Log Dialog -->
    <StreamLogDialog
      v-model:visible="showStreamLog"
      :url="streamLogUrl"
      :title="streamLogTitle"
      :method="streamLogMethod"
      :body="streamLogBody"
    />
  </div>
</template>
