<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshCw, ChevronRight } from 'lucide-vue-next'
import { fetchCapacityOverview, fetchDramaOverview } from '@/api/dashboard'
import { refreshDriveAccountProfiles } from '@/api/extensions'
import { fetchTMDBDetail } from '@/api/media'
import { useTasksQuery } from '@/hooks/queries/tasks'
import { useToast } from '@/composables/useToast'
import { formatBytes, formatPercent, formatDateTime } from '@/lib/capacity'
import type { CapacityOverview, DramaOverview } from '@/types/dashboard'
import type { TMDBDetail } from '@/types/media'
import type { TaskItem } from '@/types/tasks'

const router = useRouter()
const { toast } = useToast()

const dtfBeijing = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

// ── State ──
const dramaDays = ref(30)
const dramaLoading = ref(false)
const dramaRefreshing = ref(false)
const dramaOverview = ref<DramaOverview | null>(null)

const capacityLoading = ref(false)
const capacityRefreshing = ref(false)
const capacityOverview = ref<CapacityOverview | null>(null)

const tmdbDetailsById = reactive<Record<number, TMDBDetail | null | undefined>>({})
const tmdbDetailPromises = reactive<Record<number, Promise<TMDBDetail | null> | undefined>>({})

const { data: allTasks } = useTasksQuery()
const dramaTasks = computed<TaskItem[]>(() => (allTasks.value || []).filter((t) => t.task_type === 'drama'))

// ── Helpers ──
function beijingDateStr(d: Date) {
  return dtfBeijing.format(d)
}
function addDays(d: Date, delta: number) {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + delta)
  return copy
}

async function runWithConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>) {
  const queue = [...items]
  const runOne = async () => {
    while (queue.length) {
      const it = queue.shift()
      if (it === undefined) return
      await worker(it)
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, limit) }, () => runOne()))
}

async function loadTMDBDetails() {
  const ids = Array.from(
    new Set(
      dramaTasks.value
        .filter((t) => String(t.tmdb_media_type || '').toLowerCase() === 'tv')
        .map((t) => Number(t.tmdb_id) || 0)
        .filter((n) => Number.isFinite(n) && n > 0),
    ),
  )
  if (!ids.length) return
  await runWithConcurrency(ids, 4, async (id) => {
    if (tmdbDetailsById[id] !== undefined) return
    if (!tmdbDetailPromises[id]) {
      tmdbDetailPromises[id] = fetchTMDBDetail('tv', id)
        .then((data) => data)
        .catch(() => null)
    }
    tmdbDetailsById[id] = await tmdbDetailPromises[id]
  })
}

async function loadDrama() {
  dramaLoading.value = true
  try {
    dramaOverview.value = await fetchDramaOverview(dramaDays.value)
    await loadTMDBDetails()
  } finally {
    dramaLoading.value = false
  }
}

async function loadCapacity() {
  capacityLoading.value = true
  try {
    capacityOverview.value = await fetchCapacityOverview()
  } finally {
    capacityLoading.value = false
  }
}

async function handleRefreshDrama() {
  dramaRefreshing.value = true
  try {
    await loadDrama()
    toast.success('追剧数据已刷新 🔄')
  } finally {
    dramaRefreshing.value = false
  }
}

async function handleRefreshCapacity() {
  capacityRefreshing.value = true
  try {
    await refreshDriveAccountProfiles()
    await loadCapacity()
    toast.success('容量快照已刷新 💾')
  } catch (e: any) {
    toast.error(e?.message || '刷新容量失败')
  } finally {
    capacityRefreshing.value = false
  }
}

// ── Derived metrics ──
const activeTaskCount = computed(() => dramaTasks.value.filter((t) => t.enabled).length)

const contentSummary = computed(() => {
  const today = new Date()
  const todayStr = beijingDateStr(today)
  const next7Str = beijingDateStr(addDays(today, 7))
  let todayCount = 0
  let next7dCount = 0
  for (const task of dramaTasks.value) {
    const tmdbId = Number(task.tmdb_id) || 0
    if (!tmdbId) continue
    const data: any = tmdbDetailsById[tmdbId]?.data || null
    const airDate = String(data?.next_episode_to_air?.air_date || '').trim()
    if (!airDate) continue
    if (airDate === todayStr) todayCount += 1
    if (airDate >= todayStr && airDate <= next7Str) next7dCount += 1
  }
  return { today_count: todayCount, next7d_count: next7dCount }
})

const monthSuccessCount = computed(() => dramaOverview.value?.summary.monthly_success_count || 0)

const taskSuccessRate = computed(() => {
  const s = dramaOverview.value?.summary
  if (!s) return dramaTasks.value.length ? 1 : null
  const success = Number(s.execution_success) || 0
  const failed = Number(s.execution_failed) || 0
  const total = success + failed
  return total ? success / total : 1
})

const successRateText = computed(() => {
  const v = taskSuccessRate.value
  if (v === null || v === undefined || Number.isNaN(v)) return '--'
  return formatPercent(v)
})

const updateProgressSummary = computed(() => {
  const tasks = dramaTasks.value.filter((t) => t.tmdb_id && String(t.tmdb_media_type || '').toLowerCase() === 'tv')
  const linked = tasks.length
  let latest = 0
  let behind = 0
  let unknown = 0
  for (const task of tasks) {
    const p = task.drama_update_progress
    if (!p || !p.available) {
      unknown += 1
      continue
    }
    if (p.is_latest) {
      latest += 1
      continue
    }
    const n = typeof p.behind_episodes === 'number' ? p.behind_episodes : null
    if (n === null) {
      unknown += 1
      continue
    }
    if (n <= 0) latest += 1
    else behind += 1
  }
  const ratio = linked > 0 ? latest / linked : null
  return { linked, latest, behind, unknown, ratio }
})

const updateProgressText = computed(() => {
  const r = updateProgressSummary.value.ratio
  return r === null ? '--' : formatPercent(r)
})

const capacityUsageText = computed(() =>
  capacityOverview.value ? formatPercent(capacityOverview.value.summary.usage_ratio) : '--',
)

const capacitySpaceText = computed(() => {
  const s = capacityOverview.value?.summary
  if (!s) return '--'
  const used = formatBytes(s.total_used_space)
  const total = formatBytes(s.total_space)
  if (used === '--' || total === '--') return '--'
  return `${used} / ${total}`
})

const warningCount = computed(() => capacityOverview.value?.warning_accounts.length || 0)

// ── Recent updates & upcoming ──
function titleFromTask(task: TaskItem) {
  const tmdbId = Number(task.tmdb_id) || 0
  const data: any = tmdbId ? tmdbDetailsById[tmdbId]?.data || null : null
  return String(data?.name || data?.title || '').trim() || String(task.taskname || '').trim() || `任务 #${task.id}`
}

function episodeLabelFromDetail(data: any, kind: 'last' | 'next') {
  const source = kind === 'next' ? data?.next_episode_to_air : data?.last_episode_to_air
  const season = Number(source?.season_number) || 0
  const ep = Number(source?.episode_number) || 0
  if (season > 0 && ep > 0) return `S${String(season).padStart(2, '0')}E${String(ep).padStart(2, '0')}`
  return ''
}

function timeAgoFromIso(iso?: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
  if (s < 60) return `${s}秒前`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}小时前`
  return `${Math.floor(h / 24)}天前`
}

function relativeDayLabel(isoDate: string) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const d = new Date(`${isoDate}T00:00:00`)
  if (Number.isNaN(d.getTime())) return isoDate
  const diff = Math.round((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff === 2) return '后天'
  if (diff > 2) return `${diff}天后`
  return isoDate
}

const recentSuccesses = computed(() => {
  const items: Array<{ task: TaskItem; started_at: string; adapter_snapshot: Record<string, any> }> = []
  for (const task of dramaTasks.value) {
    for (const ex of task.executions || []) {
      if (String(ex.status || '').toLowerCase() !== 'success') continue
      items.push({ task, started_at: String(ex.started_at), adapter_snapshot: ex.adapter_snapshot || {} })
    }
  }
  items.sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
  return items.slice(0, 4)
})

const upcomingAiring = computed(() => {
  const today = beijingDateStr(new Date())
  const maxDate = beijingDateStr(addDays(new Date(), 7))
  const items: Array<{ task: TaskItem; air_date: string; episode: string }> = []
  for (const task of dramaTasks.value) {
    if (!task.enabled) continue
    if (String(task.tmdb_media_type || '').toLowerCase() !== 'tv') continue
    const tmdbId = Number(task.tmdb_id) || 0
    if (!tmdbId) continue
    const data: any = tmdbDetailsById[tmdbId]?.data || null
    const airDate = String(data?.next_episode_to_air?.air_date || '').trim()
    if (!airDate || airDate < today || airDate > maxDate) continue
    items.push({ task, air_date: airDate, episode: episodeLabelFromDetail(data, 'next') })
  }
  items.sort((a, b) => String(a.air_date).localeCompare(String(b.air_date)))
  return items.slice(0, 5)
})

const failures = computed(() => dramaOverview.value?.recent_failures || [])
const displayFailures = computed(() => failures.value.slice(0, 3))

watch(dramaDays, () => loadDrama())
watch(dramaTasks, () => loadTMDBDetails())

onMounted(() => {
  loadDrama()
  loadCapacity()
})
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-xl font-bold text-[hsl(var(--foreground))]">📊 追剧大盘</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
          活跃 {{ activeTaskCount }} · 7 日更新 {{ contentSummary.next7d_count }} · 成功率 {{ successRateText }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <div class="inline-flex rounded-full bg-[hsl(var(--muted))] p-0.5 text-xs">
          <button
            v-for="d in [7, 30]"
            :key="d"
            class="rounded-full px-3 py-1 font-medium transition"
            :class="dramaDays === d
              ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
              : 'text-[hsl(var(--muted-foreground))]'"
            @click="dramaDays = d"
          >
            近{{ d }}天
          </button>
        </div>
        <button
          class="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] transition hover:text-[hsl(var(--foreground))]"
          title="刷新追剧数据"
          @click="handleRefreshDrama"
        >
          <RefreshCw :size="15" :class="dramaRefreshing ? 'animate-spin' : ''" />
        </button>
      </div>
    </div>

    <!-- Metric tiles -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">📺</span>
          <span class="glass-tile__label">活跃订阅</span>
        </div>
        <div class="glass-tile__value">{{ activeTaskCount }}</div>
        <div class="glass-tile__hint">
          <template v-if="dramaOverview?.summary.unknown_schedule_count">
            ⚠️ 未配置更新日 {{ dramaOverview.summary.unknown_schedule_count }}
          </template>
          <template v-else>✅ 更新日完整</template>
        </div>
      </div>

      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">✨</span>
          <span class="glass-tile__label">本月新增</span>
        </div>
        <div class="glass-tile__value">{{ monthSuccessCount }}</div>
        <div class="glass-tile__hint">🎬 本月成功执行</div>
      </div>

      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">💾</span>
          <span class="glass-tile__label">空间使用率</span>
        </div>
        <div class="glass-tile__value">{{ capacityUsageText }}</div>
        <div class="glass-tile__hint">
          <template v-if="capacityOverview">{{ capacitySpaceText }}</template>
          <template v-else>汇总容量</template>
        </div>
      </div>

      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">✅</span>
          <span class="glass-tile__label">任务成功率</span>
        </div>
        <div class="glass-tile__value">{{ successRateText }}</div>
        <div class="glass-tile__hint">
          <template v-if="dramaOverview">
            ✔ {{ dramaOverview.summary.execution_success }} · ✖ {{ dramaOverview.summary.execution_failed }}
          </template>
          <template v-else>暂无记录</template>
        </div>
      </div>

      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">🎯</span>
          <span class="glass-tile__label">最新比例</span>
        </div>
        <div class="glass-tile__value">{{ updateProgressText }}</div>
        <div class="glass-tile__hint">
          <template v-if="updateProgressSummary.linked">
            🆕 {{ updateProgressSummary.latest }} · ⏳ {{ updateProgressSummary.behind }}
          </template>
          <template v-else>已关联 TMDB</template>
        </div>
      </div>
    </div>

    <!-- Updates + Upcoming -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <!-- Recent updates (span 2) -->
      <div class="glass-card lg:col-span-2">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="flex items-center gap-1.5 text-sm font-semibold text-[hsl(var(--foreground))]">
            🔔 最近更新
          </h3>
          <button
            class="inline-flex items-center gap-0.5 text-xs font-medium text-[hsl(var(--primary))] hover:underline"
            @click="router.push('/tasks')"
          >
            追剧任务 <ChevronRight :size="14" />
          </button>
        </div>

        <div v-if="!recentSuccesses.length" class="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
          🍿 暂无成功记录，运行一次任务后再查看
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="item in recentSuccesses"
            :key="`${item.task.id}-${item.started_at}`"
            class="flex items-center justify-between gap-3 rounded-xl bg-[hsl(var(--muted)/.4)] px-3 py-2.5"
          >
            <div class="flex min-w-0 items-center gap-2">
              <span class="text-base">📺</span>
              <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ titleFromTask(item.task) }}</span>
            </div>
            <div class="flex flex-shrink-0 items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
              <span>{{ timeAgoFromIso(item.started_at) }}</span>
              <span class="rounded-full bg-green-500/15 px-2 py-0.5 font-medium text-green-600 dark:text-green-400">成功</span>
            </div>
          </div>
        </div>

        <!-- Failures -->
        <div v-if="failures.length" class="mt-3 rounded-xl border border-red-500/20 bg-red-500/5 p-3">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-xs font-semibold text-red-600 dark:text-red-400">⚠️ 近期失败 {{ failures.length }} 条</span>
            <button
              class="text-xs font-medium text-[hsl(var(--primary))] hover:underline"
              @click="router.push('/tasks')"
            >
              查看
            </button>
          </div>
          <div class="space-y-1.5">
            <div
              v-for="f in displayFailures"
              :key="`${f.task_id}-${f.started_at}`"
              class="flex items-center justify-between gap-2 text-xs"
            >
              <span class="truncate font-medium text-[hsl(var(--foreground))]">{{ f.taskname }}</span>
              <span class="flex-shrink-0 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(f.started_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Upcoming -->
      <div class="glass-card">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">🗓️ 即将播出</h3>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">7 天 · {{ upcomingAiring.length }} 部</span>
        </div>
        <div v-if="!upcomingAiring.length" class="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
          😴 未来 7 天暂无更新
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="it in upcomingAiring"
            :key="`${it.task.id}-${it.air_date}`"
            class="flex items-center justify-between gap-2 rounded-xl bg-[hsl(var(--muted)/.4)] px-3 py-2.5"
          >
            <div class="flex min-w-0 items-center gap-2">
              <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ titleFromTask(it.task) }}</span>
              <span
                v-if="it.episode"
                class="flex-shrink-0 rounded-full bg-[hsl(var(--primary)/.12)] px-1.5 py-0.5 text-[10px] font-semibold text-[hsl(var(--primary))]"
              >
                {{ it.episode }}
              </span>
            </div>
            <span class="flex-shrink-0 text-xs font-medium text-[hsl(var(--muted-foreground))]">{{ relativeDayLabel(it.air_date) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Capacity overview -->
    <div class="glass-card">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 class="flex items-center gap-1.5 text-sm font-semibold text-[hsl(var(--foreground))]">💽 容量管理</h3>
        <div class="flex items-center gap-2 text-xs">
          <span
            class="rounded-full px-2 py-0.5 font-medium"
            :class="warningCount
              ? 'bg-red-500/15 text-red-600 dark:text-red-400'
              : 'bg-green-500/15 text-green-600 dark:text-green-400'"
          >
            {{ warningCount ? `⚠️ 预警 ${warningCount}` : '✅ 无预警' }}
          </span>
          <span class="text-[hsl(var(--muted-foreground))]">🕐 {{ formatDateTime(capacityOverview?.updated_at) }}</span>
          <button
            class="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] transition hover:text-[hsl(var(--foreground))]"
            title="刷新容量"
            @click="handleRefreshCapacity"
          >
            <RefreshCw :size="13" :class="capacityRefreshing ? 'animate-spin' : ''" />
          </button>
        </div>
      </div>

      <div v-if="!capacityOverview" class="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        📭 暂无容量数据，点击刷新后查看
      </div>
      <div v-else class="space-y-4">
        <!-- Total usage -->
        <div>
          <div class="mb-1.5 flex items-center justify-between text-sm">
            <span class="text-[hsl(var(--muted-foreground))]">总占用 {{ capacitySpaceText }}</span>
            <span class="font-semibold text-[hsl(var(--foreground))]">{{ capacityUsageText }}</span>
          </div>
          <div class="h-2.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
            <div
              class="h-full rounded-full transition-all"
              :class="(capacityOverview.summary.usage_ratio || 0) >= 0.85 ? 'bg-red-500' : 'bg-green-500'"
              :style="{ width: `${Math.min(100, Math.round((capacityOverview.summary.usage_ratio || 0) * 100))}%` }"
            />
          </div>
        </div>

        <!-- Account count chips -->
        <div class="grid grid-cols-3 gap-3">
          <div class="rounded-xl bg-[hsl(var(--muted)/.4)] px-3 py-2.5 text-center">
            <div class="text-lg font-bold text-[hsl(var(--foreground))]">{{ capacityOverview.summary.account_count }}</div>
            <div class="text-[11px] text-[hsl(var(--muted-foreground))]">👤 账号总数</div>
          </div>
          <div class="rounded-xl bg-[hsl(var(--muted)/.4)] px-3 py-2.5 text-center">
            <div class="text-lg font-bold text-[hsl(var(--foreground))]">{{ capacityOverview.summary.capacity_account_count }}</div>
            <div class="text-[11px] text-[hsl(var(--muted-foreground))]">📊 支持容量</div>
          </div>
          <div class="rounded-xl bg-[hsl(var(--muted)/.4)] px-3 py-2.5 text-center">
            <div class="text-lg font-bold" :class="warningCount ? 'text-red-500' : 'text-[hsl(var(--foreground))]'">{{ warningCount }}</div>
            <div class="text-[11px] text-[hsl(var(--muted-foreground))]">⚠️ 预警账号</div>
          </div>
        </div>

        <!-- Warning accounts list -->
        <div v-if="capacityOverview.warning_accounts.length" class="space-y-2">
          <div
            v-for="acc in capacityOverview.warning_accounts"
            :key="acc.id"
            class="rounded-xl border border-red-500/20 bg-red-500/5 px-3 py-2"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ acc.name }}</span>
              <span class="flex-shrink-0 text-xs font-semibold text-red-500">{{ formatPercent(acc.usage_ratio) }}</span>
            </div>
            <div class="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">
              {{ formatBytes(acc.used_space) }} / {{ formatBytes(acc.total_space) }}
            </div>
          </div>
        </div>

        <button
          class="w-full rounded-xl bg-[hsl(var(--muted)/.4)] py-2 text-xs font-medium text-[hsl(var(--primary))] transition hover:bg-[hsl(var(--muted)/.6)]"
          @click="router.push('/drives')"
        >
          管理网盘账号 →
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.glass-tile {
  border-radius: 1rem;
  border: 1px solid hsl(var(--border) / 0.6);
  background: hsl(var(--card) / 0.6);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  padding: 0.85rem 1rem;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.glass-tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.08);
}
.glass-tile__top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.glass-tile__emoji {
  font-size: 1rem;
  line-height: 1;
}
.glass-tile__label {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}
.glass-tile__value {
  margin-top: 0.35rem;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.1;
  color: hsl(var(--foreground));
}
.glass-tile__hint {
  margin-top: 0.25rem;
  font-size: 0.7rem;
  color: hsl(var(--muted-foreground));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.glass-card {
  border-radius: 1.15rem;
  border: 1px solid hsl(var(--border) / 0.6);
  background: hsl(var(--card) / 0.6);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  padding: 1.1rem 1.25rem;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
}
</style>
