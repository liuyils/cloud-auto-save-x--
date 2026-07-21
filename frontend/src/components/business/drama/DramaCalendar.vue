<script setup lang="ts">
import { ref, computed, reactive, watch } from 'vue'
import { ChevronLeft, ChevronRight, CalendarDays, LayoutGrid, CalendarRange } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useTasksQuery } from '@/hooks/queries/tasks'
import { fetchTMDBDetail } from '@/api/media'
import type { TMDBDetail } from '@/types/media'
import type { TaskItem } from '@/types/tasks'

// ── Types ──
type WeekdayKey = 1 | 2 | 3 | 4 | 5 | 6 | 7

type CalendarEntry = {
  taskId: number
  tmdbId: number | null
  task: TaskItem
  title: string
  posterUrl: string
  episodeInfo: string
  progressPercent: number | null
}

// ── Constants ──
const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w200'

const weekdayLabels: Array<{ key: WeekdayKey; label: string; short: string }> = [
  { key: 1, label: '周一', short: '一' },
  { key: 2, label: '周二', short: '二' },
  { key: 3, label: '周三', short: '三' },
  { key: 4, label: '周四', short: '四' },
  { key: 5, label: '周五', short: '五' },
  { key: 6, label: '周六', short: '六' },
  { key: 7, label: '周日', short: '日' },
]

// ── State ──
const viewMode = ref<'week' | 'month'>('week')
const weekOffset = ref(0)
const monthCursor = ref(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
const selectedMonthDate = ref<string>('')

// TMDB detail cache (reactive)
const detailsById = reactive<Record<number, TMDBDetail | undefined>>({})
const tmdbLoading = ref(false)

const { data: tasks, isLoading: tasksLoading } = useTasksQuery()

// ── Utility functions ──
function parseDateOnly(yyyyMMdd: string): Date | null {
  const s = String(yyyyMMdd || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null
  const [y, m, d] = s.split('-').map((x) => Number(x))
  const dt = new Date(y, (m || 1) - 1, d || 1)
  return Number.isNaN(dt.getTime()) ? null : dt
}

function dateOnly(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function formatYYYYMMDD(d: Date): string {
  const y = String(d.getFullYear())
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatMMDD(d: Date): string {
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function isoWeekdayFromDate(d: Date): WeekdayKey {
  const js = d.getDay()
  return (((js + 6) % 7) + 1) as WeekdayKey
}

function normalizeWeekdays(value: any): WeekdayKey[] {
  const arr = Array.isArray(value) ? value : []
  const days = arr.map((x: any) => Number(x)).filter((x: number) => x >= 1 && x <= 7) as WeekdayKey[]
  return Array.from(new Set(days)).sort((a, b) => a - b) as WeekdayKey[]
}

function isToday(date: Date): boolean {
  const now = new Date()
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
}

// ── TMDB helpers ──
function tvTotalEpisodesFromDetail(data: any): number | null {
  const n = data?.number_of_episodes
  if (typeof n === 'number' && n > 0) return n
  const seasons = Array.isArray(data?.seasons) ? data.seasons : []
  const sum = seasons
    .filter((s: any) => s && Number(s.season_number) > 0)
    .reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  return sum > 0 ? sum : null
}

function tvAiredEpisodesFromDetail(data: any, total: number | null): number | null {
  const status = String(data?.status || '').toLowerCase()
  if (status === 'ended' && total && total > 0) return total
  const last = data?.last_episode_to_air
  if (!last) return null
  const seasonNumber = Number(last.season_number) || 0
  const episodeNumber = Number(last.episode_number) || 0
  if (seasonNumber <= 0 || episodeNumber <= 0) return null
  const seasons = Array.isArray(data?.seasons) ? data.seasons : []
  const prev = seasons
    .filter((s: any) => s && Number(s.season_number) > 0 && Number(s.season_number) < seasonNumber)
    .reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  const aired = prev + episodeNumber
  return aired > 0 ? aired : null
}

function displayTitle(task: TaskItem, detail: TMDBDetail | undefined): string {
  const data = detail?.data || {}
  const name = String(data?.name || data?.title || '').trim()
  return name || String(task.taskname || '').trim() || `任务 #${task.id}`
}

function posterUrlFromDetail(detail: TMDBDetail | undefined): string {
  const p = String(detail?.data?.poster_path || '').trim()
  return p ? `${TMDB_IMAGE_BASE}${p}` : ''
}

function nextAirDateFromDetail(detail: TMDBDetail | undefined): string | null {
  const d = detail?.data?.next_episode_to_air?.air_date
  return String(d || '').trim() || null
}

function episodeInfoFromDetail(task: TaskItem, detail: TMDBDetail | undefined): string {
  const data = detail?.data
  if (!data) {
    const progress = task.drama_update_progress
    if (progress?.behind_episodes) return `落后 ${progress.behind_episodes} 集`
    return ''
  }
  const next = data.next_episode_to_air
  const last = data.last_episode_to_air
  if (next?.episode_number) {
    const sn = Number(next.season_number) || 0
    const en = Number(next.episode_number) || 0
    return sn > 0 ? `S${sn}E${en}` : `第${en}集`
  }
  if (last?.episode_number) {
    const sn = Number(last.season_number) || 0
    const en = Number(last.episode_number) || 0
    return sn > 0 ? `更新到 S${sn}E${en}` : `更新到 第${en}集`
  }
  const total = tvTotalEpisodesFromDetail(data)
  const aired = tvAiredEpisodesFromDetail(data, total)
  if (aired != null && total != null) return `${aired}/${total}`
  if (aired != null) return `已播 ${aired} 集`
  return ''
}

function progressPercentFromDetail(data: any): number | null {
  const total = tvTotalEpisodesFromDetail(data)
  const aired = tvAiredEpisodesFromDetail(data, total)
  if (aired == null || total == null || total <= 0) return null
  return Math.max(0, Math.min(100, Math.floor((aired / total) * 100)))
}

// ── Week logic ──
// Week starts from TODAY (not Monday), showing today + next 6 days.
function getWeekStart(offset: number): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset * 7)
}

function weekdayLabelOf(d: Date): string {
  return weekdayLabels[isoWeekdayFromDate(d) - 1]?.label || ''
}

const weekStart = computed(() => getWeekStart(weekOffset.value))

const weekDates = computed(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    return d
  }),
)

const weekLabel = computed(() => {
  const s = weekDates.value[0]
  const e = weekDates.value[6]
  return `${formatMMDD(s)} — ${formatMMDD(e)}`
})

// ── Enabled drama tasks ──
const enabledDramaTasks = computed(() =>
  (tasks.value || []).filter((t) => t.task_type === 'drama' && t.enabled),
)

// ── Load TMDB details ──
async function loadTMDBDetails() {
  const tvTasks = enabledDramaTasks.value.filter(
    (t) => t.tmdb_id && String(t.tmdb_media_type || '').toLowerCase() === 'tv',
  )
  const ids = Array.from(new Set(tvTasks.map((t) => Number(t.tmdb_id) || 0).filter((x) => x > 0)))
  if (!ids.length) return

  tmdbLoading.value = true
  try {
    await Promise.all(
      ids.map(async (id) => {
        if (detailsById[id]) return
        try {
          detailsById[id] = await fetchTMDBDetail('tv', id)
        } catch {
          // ignore
        }
      }),
    )
  } finally {
    tmdbLoading.value = false
  }
}

// Watch tasks and load TMDB details when available
watch(
  () => tasks.value,
  () => {
    if (tasks.value?.length) loadTMDBDetails()
  },
  { immediate: true },
)

// ── Schedule computation ──
type ScheduleItem = {
  task: TaskItem
  tmdbId: number | null
  title: string
  posterUrl: string
  episodeInfo: string
  progressPercent: number | null
  weekdays: WeekdayKey[]
  nextAirDate: string | null
}

const schedules = computed<ScheduleItem[]>(() => {
  const list: ScheduleItem[] = []
  for (const task of enabledDramaTasks.value) {
    const tmdbId = Number(task.tmdb_id) || 0
    const mt = String(task.tmdb_media_type || '').toLowerCase()
    const detail = mt === 'tv' && tmdbId > 0 ? detailsById[tmdbId] : undefined

    // Determine weekdays
    const tmdbWeekdays = normalizeWeekdays(detail?.update_weekdays || detail?.episode_weekdays)
    const runWeekdays = normalizeWeekdays((task.extra as any)?.runweek)

    // Also try to infer from next_episode_to_air
    let airDateWeekdays: WeekdayKey[] = []
    const airDate = nextAirDateFromDetail(detail)
    if (airDate) {
      const d = parseDateOnly(airDate)
      if (d) airDateWeekdays = [isoWeekdayFromDate(d)]
    }

    const days = tmdbWeekdays.length ? tmdbWeekdays : airDateWeekdays.length ? airDateWeekdays : runWeekdays
    if (!days.length) continue

    list.push({
      task,
      tmdbId: mt === 'tv' && tmdbId > 0 ? tmdbId : null,
      title: displayTitle(task, detail),
      posterUrl: posterUrlFromDetail(detail),
      episodeInfo: episodeInfoFromDetail(task, detail),
      progressPercent: detail?.data ? progressPercentFromDetail(detail.data) : null,
      weekdays: days,
      nextAirDate: airDate,
    })
  }
  return list
})

// ── Week entries (grouped by date) ──
const weekEntriesByDate = computed(() => {
  const by = new Map<string, CalendarEntry[]>()
  const start = dateOnly(weekDates.value[0])
  const end = dateOnly(weekDates.value[6])

  for (const s of schedules.value) {
    for (const d of weekDates.value) {
      const dd = dateOnly(d)
      if (dd.getTime() < start.getTime() || dd.getTime() > end.getTime()) continue
      const wd = isoWeekdayFromDate(d)
      if (!s.weekdays.includes(wd)) continue

      const key = formatYYYYMMDD(d)
      if (!by.has(key)) by.set(key, [])
      const list = by.get(key)!
      if (list.some((e) => e.taskId === s.task.id)) continue
      list.push({
        taskId: s.task.id,
        tmdbId: s.tmdbId,
        task: s.task,
        title: s.title,
        posterUrl: s.posterUrl,
        episodeInfo: s.episodeInfo,
        progressPercent: s.progressPercent,
      })
    }
  }

  return by
})

// ── Month logic ──
function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}
function endOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0)
}
function addMonths(d: Date, delta: number) {
  return new Date(d.getFullYear(), d.getMonth() + delta, 1)
}

const monthTitle = computed(() => {
  const d = monthCursor.value
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
})

const monthGridDates = computed(() => {
  const first = startOfMonth(monthCursor.value)
  const last = endOfMonth(monthCursor.value)
  const start = new Date(first)
  start.setDate(start.getDate() - (isoWeekdayFromDate(start) - 1))
  const end = new Date(last)
  end.setDate(end.getDate() + (7 - isoWeekdayFromDate(end)))
  const out: Date[] = []
  const d = new Date(start)
  while (d.getTime() <= end.getTime()) {
    out.push(new Date(d))
    d.setDate(d.getDate() + 1)
  }
  return out
})

const monthEntriesByDate = computed(() => {
  const cur = monthCursor.value
  const by = new Map<string, CalendarEntry[]>()
  const mStart = startOfMonth(cur)
  const mEnd = endOfMonth(cur)

  for (const s of schedules.value) {
    for (const d of monthGridDates.value) {
      if (d.getFullYear() !== cur.getFullYear() || d.getMonth() !== cur.getMonth()) continue
      const wd = isoWeekdayFromDate(d)
      if (!s.weekdays.includes(wd)) continue
      if (d.getTime() < mStart.getTime() || d.getTime() > mEnd.getTime()) continue

      const key = formatYYYYMMDD(d)
      if (!by.has(key)) by.set(key, [])
      const list = by.get(key)!
      if (list.some((e) => e.taskId === s.task.id)) continue
      list.push({
        taskId: s.task.id,
        tmdbId: s.tmdbId,
        task: s.task,
        title: s.title,
        posterUrl: s.posterUrl,
        episodeInfo: s.episodeInfo,
        progressPercent: s.progressPercent,
      })
    }
  }

  return by
})

const monthCells = computed(() => {
  const cur = monthCursor.value
  const todayKey = formatYYYYMMDD(new Date())
  return monthGridDates.value.map((d) => {
    const key = formatYYYYMMDD(d)
    const list = monthEntriesByDate.value.get(key) || []
    const inMonth = d.getFullYear() === cur.getFullYear() && d.getMonth() === cur.getMonth()
    const display = list.slice(0, 3)
    return {
      key,
      date: d,
      day: d.getDate(),
      inMonth,
      isToday: key === todayKey,
      items: display,
      total: list.length,
      more: Math.max(0, list.length - 3),
    }
  })
})

// Selected date detail for month view
const selectedMonthItems = computed(() =>
  selectedMonthDate.value ? monthEntriesByDate.value.get(selectedMonthDate.value) || [] : [],
)

const selectedMonthTitle = computed(() => {
  if (!selectedMonthDate.value) return ''
  const d = parseDateOnly(selectedMonthDate.value)
  return d ? `${d.getMonth() + 1}月${d.getDate()}日` : ''
})

function selectMonthCell(key: string) {
  selectedMonthDate.value = selectedMonthDate.value === key ? '' : key
}

// ── Navigation ──
function prevWeek() { weekOffset.value-- }
function nextWeek() { weekOffset.value++ }
function goToday() {
  weekOffset.value = 0
  monthCursor.value = new Date(new Date().getFullYear(), new Date().getMonth(), 1)
}
function prevMonth() { monthCursor.value = addMonths(monthCursor.value, -1) }
function nextMonth() { monthCursor.value = addMonths(monthCursor.value, 1) }

// ── Loading state ──
const isLoading = computed(() => tasksLoading.value || tmdbLoading.value)

// ── Total tracked shows ──
const totalShows = computed(() => schedules.value.length)
</script>

<template>
  <div class="space-y-4">
    <!-- Top bar: view toggle + navigation -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <!-- View toggle -->
      <div class="inline-flex items-center rounded-lg border border-[hsl(var(--border))] overflow-hidden">
        <button
          class="px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1.5"
          :class="viewMode === 'week'
            ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
            : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'"
          @click="viewMode = 'week'"
        >
          <CalendarRange class="h-3.5 w-3.5" />
          周视图
        </button>
        <button
          class="px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1.5"
          :class="viewMode === 'month'
            ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
            : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'"
          @click="viewMode = 'month'"
        >
          <LayoutGrid class="h-3.5 w-3.5" />
          月视图
        </button>
      </div>

      <!-- Week navigation -->
      <div v-if="viewMode === 'week'" class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="prevWeek">
          <ChevronLeft class="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" @click="goToday">今天</Button>
        <Button variant="outline" size="sm" @click="nextWeek">
          <ChevronRight class="h-4 w-4" />
        </Button>
        <span class="text-sm font-medium text-[hsl(var(--foreground))] ml-2">{{ weekLabel }}</span>
      </div>

      <!-- Month navigation -->
      <div v-else class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="prevMonth">
          <ChevronLeft class="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" @click="goToday">今天</Button>
        <Button variant="outline" size="sm" @click="nextMonth">
          <ChevronRight class="h-4 w-4" />
        </Button>
        <span class="text-sm font-medium text-[hsl(var(--foreground))] ml-2">{{ monthTitle }}</span>
      </div>
    </div>

    <!-- Loading skeleton -->
    <div v-if="isLoading && !schedules.length" class="space-y-3">
      <div class="grid grid-cols-7 gap-2">
        <div v-for="i in 7" :key="i" class="h-48 animate-pulse rounded-lg bg-[hsl(var(--muted))]" />
      </div>
    </div>

    <!-- ═══════════ WEEK VIEW (Timeline) ═══════════ -->
    <div v-else-if="viewMode === 'week'" class="flex flex-col gap-2">
      <div
        v-for="(date, idx) in weekDates"
        :key="formatYYYYMMDD(date)"
        class="flex items-stretch rounded-lg border bg-[hsl(var(--card))] overflow-hidden transition-all"
        :class="isToday(weekDates[idx])
          ? 'border-[hsl(var(--primary))] ring-2 ring-[hsl(var(--primary)/.2)] shadow-sm'
          : 'border-[hsl(var(--border))]'"
      >
        <!-- Left: date label -->
        <div
          class="flex flex-col items-center justify-center px-3 py-3 min-w-[4.5rem] border-r"
          :class="isToday(weekDates[idx])
            ? 'border-[hsl(var(--primary)/.3)] bg-[hsl(var(--primary)/.08)]'
            : 'border-[hsl(var(--border)/.5)] bg-[hsl(var(--muted)/.3)]'"
        >
          <span
            class="text-xs font-semibold"
            :class="isToday(weekDates[idx])
              ? 'text-[hsl(var(--primary))]'
              : 'text-[hsl(var(--muted-foreground))]'"
          >
            {{ weekdayLabelOf(date) }}
          </span>
          <span
            class="text-lg tabular-nums leading-tight"
            :class="isToday(weekDates[idx])
              ? 'font-bold text-[hsl(var(--primary))]'
              : 'text-[hsl(var(--foreground))]'"
          >
            {{ weekDates[idx].getDate() }}
          </span>
          <span
            v-if="isToday(weekDates[idx])"
            class="text-[10px] font-medium text-[hsl(var(--primary))] mt-0.5"
          >
            今天
          </span>
        </div>

        <!-- Right: poster cards horizontal scroll -->
        <div class="flex-1 flex items-center gap-3 p-3 overflow-x-auto">
          <div
            v-for="entry in (weekEntriesByDate.get(formatYYYYMMDD(weekDates[idx])) || [])"
            :key="entry.taskId"
            class="flex items-center gap-2.5 p-2 rounded-lg cursor-pointer hover:bg-[hsl(var(--accent))] transition-colors group flex-shrink-0"
          >
            <!-- Poster -->
            <div class="relative w-12 h-[4.5rem] sm:w-14 sm:h-[5.25rem] rounded overflow-hidden bg-[hsl(var(--muted))] flex-shrink-0">
              <img
                v-if="entry.posterUrl"
                :src="entry.posterUrl"
                :alt="entry.title"
                class="w-full h-full object-cover"
                loading="lazy"
              />
              <div
                v-else
                class="w-full h-full flex items-center justify-center text-lg font-bold text-[hsl(var(--muted-foreground))]"
                :style="{ background: `hsl(var(--primary) / 0.15)` }"
              >
                {{ entry.title[0] || '?' }}
              </div>
              <!-- Progress bar overlay at bottom -->
              <div
                v-if="entry.progressPercent != null"
                class="absolute bottom-0 left-0 right-0 h-1 bg-[hsl(var(--muted)/.5)]"
              >
                <div
                  class="h-full bg-emerald-500 rounded-r"
                  :style="{ width: `${entry.progressPercent}%` }"
                />
              </div>
            </div>
            <!-- Title + episode -->
            <div class="flex flex-col gap-0.5 min-w-0">
              <span class="text-xs sm:text-sm font-medium truncate max-w-[8rem] text-[hsl(var(--foreground))]">
                {{ entry.title }}
              </span>
              <span v-if="entry.episodeInfo" class="text-[10px] sm:text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[8rem]">
                {{ entry.episodeInfo }}
              </span>
            </div>
          </div>

          <!-- Empty state -->
          <div
            v-if="!(weekEntriesByDate.get(formatYYYYMMDD(weekDates[idx])) || []).length"
            class="flex items-center justify-center py-2"
          >
            <span class="text-xs text-[hsl(var(--muted-foreground)/.5)]">无更新</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════ MONTH VIEW ═══════════ -->
    <div v-else class="space-y-2">
      <!-- Weekday headers -->
      <div class="grid grid-cols-7 gap-1">
        <div
          v-for="w in weekdayLabels"
          :key="w.key"
          class="text-center text-xs font-medium text-[hsl(var(--muted-foreground))] py-1"
        >
          {{ w.label }}
        </div>
      </div>

      <!-- Calendar grid -->
      <div class="grid grid-cols-7 gap-1">
        <div
          v-for="cell in monthCells"
          :key="cell.key"
          class="min-h-[5.5rem] sm:min-h-[7rem] rounded-lg border p-1.5 flex flex-col gap-1 cursor-pointer transition-all"
          :class="[
            !cell.inMonth ? 'opacity-30 border-transparent' : '',
            cell.isToday ? 'border-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary)/.2)] bg-[hsl(var(--primary)/.03)]' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]',
            selectedMonthDate === cell.key ? 'ring-2 ring-[hsl(var(--primary)/.4)]' : '',
          ]"
          @click="selectMonthCell(cell.key)"
        >
          <!-- Day number -->
          <div class="flex items-center justify-between">
            <span
              class="text-xs font-semibold tabular-nums"
              :class="cell.isToday ? 'text-[hsl(var(--primary))]' : 'text-[hsl(var(--foreground))]' "
            >
              {{ cell.day }}
            </span>
            <span
              v-if="cell.total > 0"
              class="text-[9px] px-1 rounded-full bg-[hsl(var(--primary)/.1)] text-[hsl(var(--primary))] font-medium"
            >
              {{ cell.total }}
            </span>
          </div>

          <!-- Mini posters (desktop) -->
          <div class="hidden sm:flex flex-col gap-0.5 flex-1 overflow-hidden">
            <div
              v-for="item in cell.items"
              :key="item.taskId"
              class="flex items-center gap-1 min-w-0"
            >
              <div class="w-4 h-5 rounded-sm overflow-hidden flex-shrink-0 bg-[hsl(var(--muted))]">
                <img v-if="item.posterUrl" :src="item.posterUrl" class="w-full h-full object-cover" loading="lazy" />
                <div v-else class="w-full h-full flex items-center justify-center text-[7px] font-bold bg-[hsl(var(--primary)/.15)]">
                  {{ item.title[0] }}
                </div>
              </div>
              <span class="text-[10px] truncate text-[hsl(var(--foreground))]">{{ item.title }}</span>
            </div>
            <span v-if="cell.more > 0" class="text-[9px] text-[hsl(var(--primary))] font-medium">
              +{{ cell.more }} 更多
            </span>
          </div>

          <!-- Mobile: just dot indicator -->
          <div class="sm:hidden flex items-center gap-0.5 mt-auto">
            <div
              v-if="cell.total > 0"
              class="w-1.5 h-1.5 rounded-full bg-[hsl(var(--primary))]"
            />
          </div>
        </div>
      </div>

      <!-- Selected date detail panel (month view) -->
      <Transition name="slide-down">
        <div
          v-if="selectedMonthDate && selectedMonthItems.length"
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 space-y-2"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ selectedMonthTitle }}</span>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ selectedMonthItems.length }} 部更新</span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
            <div
              v-for="entry in selectedMonthItems"
              :key="entry.taskId"
              class="flex flex-col items-center gap-1 p-2 rounded-lg hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <div class="relative w-14 h-20 sm:w-16 sm:h-24 rounded overflow-hidden bg-[hsl(var(--muted))]">
                <img v-if="entry.posterUrl" :src="entry.posterUrl" class="w-full h-full object-cover" loading="lazy" />
                <div
                  v-else
                  class="w-full h-full flex items-center justify-center text-xl font-bold text-[hsl(var(--muted-foreground))]"
                  :style="{ background: `hsl(var(--primary) / 0.15)` }"
                >
                  {{ entry.title[0] || '?' }}
                </div>
                <div
                  v-if="entry.progressPercent != null"
                  class="absolute bottom-0 left-0 right-0 h-1 bg-[hsl(var(--muted)/.5)]"
                >
                  <div class="h-full bg-emerald-500" :style="{ width: `${entry.progressPercent}%` }" />
                </div>
              </div>
              <span class="text-[10px] sm:text-xs text-center font-medium truncate w-full">{{ entry.title }}</span>
              <span v-if="entry.episodeInfo" class="text-[9px] text-[hsl(var(--muted-foreground))] truncate w-full text-center">
                {{ entry.episodeInfo }}
              </span>
            </div>
          </div>
        </div>
        <div
          v-else-if="selectedMonthDate"
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-center text-sm text-[hsl(var(--muted-foreground))]"
        >
          {{ selectedMonthTitle }} 当天无更新
        </div>
      </Transition>
    </div>

    <!-- Summary -->
    <div class="flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))] pt-1">
      <CalendarDays class="h-3.5 w-3.5" />
      <span>共 {{ totalShows }} 部在追剧集</span>
    </div>
  </div>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.2s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
