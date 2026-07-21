<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Film, ArrowRight, Star, Plus, Pencil } from 'lucide-vue-next'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import DramaCalendar from '@/components/business/drama/DramaCalendar.vue'
import DramaDashboard from '@/components/business/drama/DramaDashboard.vue'
import CreateTaskSheet from '@/components/business/drama/CreateTaskSheet.vue'
import StreamLogDialog from '@/components/business/common/StreamLogDialog.vue'
import { useMediaDiscoverQuery, useDoubanListQuery } from '@/hooks/queries/media'
import { useTasksQuery } from '@/hooks/queries/tasks'
import type { DoubanCategory, DoubanListItem } from '@/types/media'
import type { TaskItem } from '@/types/tasks'

const router = useRouter()

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

// Whether a hot item already has a drama task (edit vs add button state).
function itemTracked(item: DoubanListItem): boolean {
  const id = Number(item.tmdb?.id) || 0
  if (!id) return false
  const mt = String(item.tmdb?.media_type || 'tv').toLowerCase()
  return !!findExistingTask(id, mt)
}

// --- Compact discover entry ---
const searchInput = ref('')

const { data: categoriesData } = useMediaDiscoverQuery()
const categories = computed<DoubanCategory[]>(() => categoriesData.value?.categories || [])

const hotCategory = ref('')
const hotSub = ref('')
const hotStart = ref(0)
watch(categories, (cats) => {
  if (cats.length > 0 && !hotCategory.value) hotCategory.value = cats[0].key
}, { immediate: true })

const currentHotCategory = computed(() => categories.value.find((c) => c.key === hotCategory.value) || null)

const { data: hotData, isLoading: hotLoading } = useDoubanListQuery(hotCategory, hotSub, hotStart, 14)
const hotItems = computed<DoubanListItem[]>(() => hotData.value?.items || [])

function bestPoster(item: DoubanListItem) {
  const url = String(item.pic?.normal || '').trim()
  if (!url) return ''
  if (!/^https?:\/\//i.test(url)) return url
  return `/api/media/proxy-image?url=${encodeURIComponent(url)}`
}

function goDiscover() {
  const q = searchInput.value.trim()
  router.push({ path: '/discover', query: q ? { q } : {} })
}

// --- One-click add to drama ---
const sheetOpen = ref(false)
const editingTask = ref<TaskItem | undefined>(undefined)
const presetTmdb = ref<{ tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string } | null>(null)

const showStreamLog = ref(false)
const streamLogUrl = ref('')
const streamLogTitle = ref('执行日志')
const streamLogMethod = ref<'GET' | 'POST'>('GET')
const streamLogBody = ref<Record<string, any> | null>(null)

function handleAddFromDouban(item: DoubanListItem) {
  let payload: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string }
  if (item.tmdb?.id) {
    const mt = String(item.tmdb.media_type || 'tv').toLowerCase()
    payload = { tmdb_id: Number(item.tmdb.id), tmdb_media_type: mt === 'movie' ? 'movie' : 'tv', taskname: item.title || '' }
  } else {
    const mt = String(currentHotCategory.value?.media_type || 'tv').toLowerCase()
    payload = { tmdb_id: 0, tmdb_media_type: mt === 'movie' ? 'movie' : 'tv', taskname: item.title || '' }
  }
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
  <div class="flex h-full flex-col overflow-y-auto">
    <!-- ===== Discover entry (portal) ===== -->
    <section class="border-b border-[hsl(var(--border))] bg-gradient-to-b from-[hsl(var(--primary))]/5 to-transparent px-6 pt-6 pb-5">
      <div class="mx-auto max-w-6xl">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 class="text-2xl font-bold text-[hsl(var(--foreground))]">影视发现</h1>
            <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">搜索或浏览影视，一键加入追剧</p>
          </div>
          <button
            class="inline-flex items-center gap-1 text-sm font-medium text-[hsl(var(--primary))] hover:underline"
            @click="router.push('/discover')"
          >
            查看全部
            <ArrowRight class="h-4 w-4" />
          </button>
        </div>

        <!-- Search -->
        <div class="mt-4 flex items-center gap-2">
          <div class="relative w-full max-w-lg">
            <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
            <Input
              v-model="searchInput"
              placeholder="搜索影视（TMDB）..."
              class="pl-9"
              @keydown.enter="goDiscover"
            />
          </div>
          <Button @click="goDiscover">搜索</Button>
        </div>

        <!-- Hot row -->
        <div class="mt-5">
          <div class="mb-2 flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground))]">
            <Star class="h-4 w-4 text-amber-500" />
            热门推荐
          </div>
          <div v-if="hotLoading && !hotItems.length" class="flex gap-3 overflow-hidden">
            <div v-for="i in 8" :key="i" class="w-[120px] shrink-0 space-y-2">
              <div class="aspect-[2/3] animate-pulse rounded-lg bg-[hsl(var(--muted))]" />
              <div class="h-3 w-3/4 animate-pulse rounded bg-[hsl(var(--muted))]" />
            </div>
          </div>
          <div v-else class="flex gap-3 overflow-x-auto overscroll-x-contain pb-2">
            <div
              v-for="item in hotItems"
              :key="item.id"
              class="group w-[120px] shrink-0"
            >
              <div class="relative aspect-[2/3] overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
                <img
                  v-if="bestPoster(item)"
                  :src="bestPoster(item)"
                  :alt="item.title"
                  class="h-full w-full object-cover transition-transform group-hover:scale-105"
                  loading="lazy"
                />
                <div v-else class="flex h-full items-center justify-center">
                  <Film class="h-7 w-7 text-[hsl(var(--muted-foreground))]/40" />
                </div>
                <!-- Add overlay (visible on hover + always on touch devices) -->
                <div class="absolute inset-0 flex items-end justify-center pb-3 bg-gradient-to-t from-black/60 via-black/20 to-transparent opacity-0 transition-opacity group-hover:opacity-100 [@media(hover:none)]:opacity-100">
                  <Button
                    size="sm"
                    class="h-7 gap-1 border-0 bg-white px-2.5 text-xs text-black shadow-lg hover:bg-white/90"
                    @click.stop="handleAddFromDouban(item)"
                  >
                    <component :is="itemTracked(item) ? Pencil : Plus" class="h-3.5 w-3.5" />
                    {{ itemTracked(item) ? '编辑' : '追剧' }}
                  </Button>
                </div>
              </div>
              <p class="mt-1.5 truncate text-xs font-medium text-[hsl(var(--foreground))]">{{ item.title }}</p>
              <div class="flex items-center gap-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                <span v-if="item.rating?.value" class="font-medium text-amber-500">{{ item.rating.value }}</span>
                <span v-if="item.year">{{ item.year }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== Dashboard overview ===== -->
    <section class="px-6 pt-6">
      <div class="mx-auto max-w-6xl">
        <DramaDashboard />
      </div>
    </section>

    <!-- ===== Calendar (main content) ===== -->
    <section class="flex-1 px-6 py-6">
      <div class="mx-auto max-w-6xl">
        <h2 class="mb-4 text-xl font-bold text-[hsl(var(--foreground))]">🗓️ 追剧日历</h2>
        <DramaCalendar />
      </div>
    </section>

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
