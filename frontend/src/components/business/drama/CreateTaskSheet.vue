<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  X, Eye, Loader2, ChevronDown, ChevronUp, Folder, FolderOpen, Search,
  Play, ArrowUp, FileText, ChevronLeft, ChevronRight, RefreshCw,
} from 'lucide-vue-next'
import { previewShare, previewShareBatch, browseDrive, fetchTasks } from '@/api/tasks'
import { fetchTaskSuggestions } from '@/api/resourceSearch'
import type { TaskSuggestionItem } from '@/types/resourceSearch'
import { searchTMDB, fetchTMDBDetail } from '@/api/media'
import { useToast } from '@/composables/useToast'
import { useCreateTaskMutation, useUpdateTaskMutation } from '@/hooks/mutations/tasks'
import { useDriveAccountsQuery, usePluginsQuery } from '@/hooks/queries/extensions'
import { useSyncTasksQuery } from '@/hooks/queries/sync'
import { useTasksQuery, useMagicRegexQuery } from '@/hooks/queries/tasks'
import { detectDriveTypeByUrl } from '@/utils/driveType'
import type { TaskItem, SharePreviewItem, DriveBrowseItem } from '@/types/tasks'
import type { TMDBBrief } from '@/types/media'

const props = defineProps<{
  open: boolean
  editTask?: TaskItem
  presetTmdb?: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string } | null
}>()

const emit = defineEmits<{
  close: []
  'run-once': [payload: Record<string, any>]
}>()

const { toast } = useToast()
const createMutation = useCreateTaskMutation()
const updateMutation = useUpdateTaskMutation()
const { data: accountsData } = useDriveAccountsQuery()
const { data: syncTasksData } = useSyncTasksQuery()
const { data: pluginsData } = usePluginsQuery()
const { data: tasksData } = useTasksQuery()
const { data: magicRegexData } = useMagicRegexQuery()

const plugins = computed(() =>
  (pluginsData.value || []).filter((p) => p.enabled && p.task_config_fields && p.task_config_fields.length > 0),
)

const activeAccounts = computed(() =>
  (accountsData.value || []).filter((a) => a.enabled && a.runtime_status === 'active'),
)
const syncTasks = computed(() => syncTasksData.value || [])

const isEditing = computed(() => Boolean(props.editTask?.id))
const title = computed(() => (isEditing.value ? '编辑追剧任务' : '新建追剧任务'))

// Form state
const state = reactive({
  taskname: '',
  shareurl: '',
  savepath: '',
  account_choice: '__AUTO__' as string,
  tmdb_id: null as number | null,
  tmdb_media_type: 'tv' as 'tv' | 'movie',
  pattern: '',
  replace: '',
  ignore_extension: true,
  runweek_mode: 'manual' as 'auto' | 'manual',
  runweek: [] as number[],
  enddate: '',
  enabled: true,
  auto_update_115_shareurl: true,
  sync_task_uids: [] as string[],
  sort_index: 1 as number | null,
  startfid: '',
  update_subdir: '',
  update_subdir_resave_mode: 'none' as 'none' | 'resave' | 'resave_all',
  addition: {} as Record<string, Record<string, any>>,
})

// Preview state
const previewing = ref(false)
const previewError = ref('')
const previewItems = ref<SharePreviewItem[]>([])
const previewTotal = ref(0)
const showPreviewModal = ref(false)
const previewPage = ref(1)
const previewPageSize = 20
const previewDirStack = ref<{ pdir_fid: string; name: string }[]>([])
const previewTotalPages = computed(() => Math.max(1, Math.ceil(previewItems.value.length / previewPageSize)))
const previewPageItems = computed(() => {
  const start = (previewPage.value - 1) * previewPageSize
  return previewItems.value.slice(start, start + previewPageSize)
})

// Path browser state
const showPathBrowser = ref(false)
const browsePath = ref('/')
const browseItems = ref<DriveBrowseItem[]>([])
const browseLoading = ref(false)
const browseError = ref('')

// TMDB search state
const showTmdbSearch = ref(false)
const tmdbQuery = ref('')
const tmdbSearching = ref(false)
const tmdbResults = ref<TMDBBrief[]>([])

// StartFID picker state
const showStartfidPicker = ref(false)
const startfidItems = ref<SharePreviewItem[]>([])
const startfidLoading = ref(false)
const startfidError = ref('')

// UI state
const advancedOpen = ref(false)
const submitting = ref(false)

// Auto-preview state
const previewHint = ref('')
const autoPreviewTimer = ref<any>(null)
const autoLocateRunId = ref(0)
const savepathTouched = ref(false)
const savepathLastApplied = ref('')
const tmdbDetailCache = ref<Record<string, any>>({})
const isInitializing = ref(false)

// Resource search suggestions state
const taskSuggestions = reactive({
  visible: false,
  loading: false,
  items: [] as TaskSuggestionItem[],
  searchTimer: null as ReturnType<typeof setTimeout> | null,
  message: '',
})

// Plugin expand state
const expandedPlugins = ref(new Set<string>())
function togglePluginExpand(key: string) {
  if (expandedPlugins.value.has(key)) expandedPlugins.value.delete(key)
  else expandedPlugins.value.add(key)
}
function isPluginEnabled(key: string): boolean {
  return key in state.addition
}
function togglePluginEnabled(key: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    const plugin = plugins.value.find(p => p.plugin_key === key)
    if (plugin) {
      state.addition = { ...state.addition, [key]: { ...(plugin.default_task_config || {}) } }
    } else {
      state.addition = { ...state.addition, [key]: {} }
    }
  } else {
    const { [key]: _, ...rest } = state.addition
    state.addition = rest
  }
}

// Builtin rename rules —— 从后端 /tasks/magic-regex 拉取「生效值」，
// 这样在「设置 → 重命名规则」里对内置规则的覆盖能被追剧任务正确引用，而非写死的默认值。
const builtinRules = computed(() => {
  const fetched = (magicRegexData.value?.rules || []).map((r) => ({
    label: r.label ? `${r.label}（${r.key}）` : r.key,
    pattern: r.pattern || '',
    replace: r.replace || '',
  }))
  return [{ label: '自定义 / 不使用', pattern: '', replace: '' }, ...fetched]
})
// 依据当前 pattern/replace 反查命中的内置规则，便于编辑已有任务时回显选择
const selectedRuleIdx = computed(() => {
  const rules = builtinRules.value
  const p = state.pattern || ''
  const r = state.replace || ''
  if (!p && !r) return 0
  const idx = rules.findIndex((rule, i) => i > 0 && rule.pattern === p && rule.replace === r)
  return idx >= 0 ? idx : 0
})

function applyBuiltinRule(event: Event) {
  const idx = Number((event.target as HTMLSelectElement).value)
  const rules = builtinRules.value
  if (idx >= 0 && idx < rules.length) {
    state.pattern = rules[idx].pattern
    state.replace = rules[idx].replace
  }
}

// Weekday options
const weekdays = [
  { value: 1, label: '一' },
  { value: 2, label: '二' },
  { value: 3, label: '三' },
  { value: 4, label: '四' },
  { value: 5, label: '五' },
  { value: 6, label: '六' },
  { value: 7, label: '日' },
]

// Helpers
function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + 'MB'
  return (bytes / 1073741824).toFixed(2) + 'GB'
}

function formatTime(ts: any): string {
  if (!ts) return '-'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return '-'
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch { return '-' }
}

// Sync state from editTask
watch(
  () => [props.open, props.editTask, props.presetTmdb] as const,
  ([open, task, preset]) => {
    if (!open) return
    if (task) {
      isInitializing.value = true
      state.taskname = task.taskname || ''
      state.shareurl = task.shareurl || ''
      state.savepath = task.savepath || ''
      state.account_choice = task.account_name ? String(task.account_name) : '__AUTO__'
      state.tmdb_id = task.tmdb_id ?? null
      state.tmdb_media_type = (task.tmdb_media_type as 'tv' | 'movie') || 'tv'
      state.pattern = task.pattern || ''
      state.replace = task.replace || ''
      state.ignore_extension = task.ignore_extension
      state.sort_index = task.sort_index ?? null
      state.startfid = task.startfid || ''
      state.update_subdir = task.update_subdir || ''
      state.enddate = task.enddate || ''
      state.enabled = task.enabled
      state.auto_update_115_shareurl = Boolean(task.extra?.auto_update_115_shareurl ?? true)
      state.update_subdir_resave_mode = String(task.extra?.update_subdir_resave_mode || 'none') as any
      const extra = task.extra || {}
      state.runweek_mode = String((extra as any).runweek_mode || 'manual') === 'auto' ? 'auto' : 'manual'
      const rw = Array.isArray((extra as any).runweek) ? (extra as any).runweek : []
      state.runweek = rw.map((x: any) => Number(x)).filter((x: number) => x >= 1 && x <= 7)
      const taskUid = String(task.task_uid || '').trim()
      state.sync_task_uids = taskUid
        ? syncTasks.value
            .filter((st) => Array.isArray(st.drama_task_uids) && st.drama_task_uids.includes(taskUid))
            .map((st) => String(st.uid || '').trim())
            .filter(Boolean)
        : []
      // Load addition from task
      initAdditionFromTask(task.addition)
      nextTick(() => { isInitializing.value = false })
    } else {
      resetForm()
      if (preset) {
        state.taskname = preset.taskname || ''
        state.tmdb_id = preset.tmdb_id || null
        state.tmdb_media_type = preset.tmdb_media_type || 'tv'
      }
      initAdditionDefaults()
    }
    previewItems.value = []
    previewError.value = ''
    previewTotal.value = 0
    showPathBrowser.value = false
    showTmdbSearch.value = false
    showStartfidPicker.value = false
    showPreviewModal.value = false
    previewPage.value = 1
    savepathTouched.value = Boolean(task)
    savepathLastApplied.value = ''
    autoLocateRunId.value += 1
    // 清空搜索建议
    taskSuggestions.visible = false
    taskSuggestions.items = []
    taskSuggestions.message = ''
    taskSuggestions.loading = false
  },
  { immediate: true },
)

function resetForm() {
  state.taskname = ''
  state.shareurl = ''
  state.savepath = ''
  state.account_choice = '__AUTO__'
  state.tmdb_id = null
  state.tmdb_media_type = 'tv'
  state.pattern = ''
  state.replace = ''
  state.ignore_extension = true
  state.runweek_mode = 'manual'
  state.runweek = []
  state.enddate = ''
  state.enabled = true
  state.auto_update_115_shareurl = true
  state.sync_task_uids = []
  state.sort_index = 1
  state.startfid = ''
  state.update_subdir = ''
  state.update_subdir_resave_mode = 'none'
  state.addition = {}
  advancedOpen.value = false
}

function initAdditionDefaults() {
  const addition: Record<string, Record<string, any>> = {}
  for (const plugin of plugins.value) {
    addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}) }
  }
  state.addition = addition
}

function initAdditionFromTask(taskAddition: Record<string, any> | undefined | null) {
  const addition: Record<string, Record<string, any>> = {}
  for (const plugin of plugins.value) {
    if (taskAddition && taskAddition[plugin.plugin_key]) {
      addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}), ...taskAddition[plugin.plugin_key] }
    } else {
      addition[plugin.plugin_key] = { ...(plugin.default_task_config || {}) }
    }
  }
  state.addition = addition
}

// Watch savepath manual edits
watch(() => state.savepath, (newVal) => {
  if (newVal && newVal !== savepathLastApplied.value) {
    savepathTouched.value = true
  }
})

// ===== Share URL Helpers =====
function isCloud139HashShareurl(shareurl: string) {
  return /^https?:\/\/(?:yun|caiyun)\.139\.com/i.test(String(shareurl || '').trim())
}

function getShareurl(shareurl: string, dir?: { fid?: string; name?: string }) {
  const raw = String(shareurl || '').trim()
  const fid = String(dir?.fid || '').trim()
  if (isCloud139HashShareurl(raw)) {
    const [head, fragment = ''] = raw.split('#', 2)
    if (fragment) {
      const [fragPath, fragQuery = ''] = fragment.split('?', 2)
      const parts = fragQuery.split('&').map(x => String(x || '').trim()).filter(x => x && !x.startsWith('fid='))
      if (fid && !['0', 'root'].includes(fid)) parts.push(`fid=${encodeURIComponent(fid)}`)
      return `${head}#${parts.length ? `${fragPath}?${parts.join('&')}` : fragPath}`
    }
    let nextHead = head.replace(/([?&])fid=[^&#]*/g, '$1').replace(/[?&]+$/, '').replace('?&', '?')
    if (fid && !['0', 'root'].includes(fid)) {
      nextHead = `${nextHead}${nextHead.includes('?') ? '&' : '?'}fid=${encodeURIComponent(fid)}`
    }
    return nextHead
  }
  if (!fid || fid === '0') {
    const match = raw.match(/.*s\/[a-zA-Z0-9\-_]+(\?[^#]*)?/)
    return (match ? match[0] : raw.split('#')[0]).trim()
  }
  if (raw.includes(fid)) {
    const m = raw.match(new RegExp(`.*/${fid}[^/]*`))
    if (m?.[0]) return m[0]
  }
  if (raw.includes('#/list/share')) {
    return `${raw.split('#')[0]}#/list/share/${fid}`
  }
  return `${raw.split('#')[0]}#/list/share/${fid}`
}

function normalizeSavepath(value: string) {
  const s = String(value || '').trim()
  if (!s) return ''
  const normalized = `/${s}`.replace(/\/+/g, '/')
  return normalized.length > 1 ? normalized.replace(/\/+$/, '') : normalized
}

function cleanSavepathBase(savepath: string, taskname: string) {
  let p = normalizeSavepath(savepath)
  if (!p) return ''
  p = p.replace(/\/S\d{1,3}$/i, '')
  const name = String(taskname || '').trim()
  if (!name) return p
  const parts = p.split('/').filter(Boolean)
  const last = String(parts.at(-1) || '')
  if (!last) return p
  if (last === name) return normalizeSavepath(parts.slice(0, -1).join('/'))
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (new RegExp(`^${escaped}\\s*\\(\\d{4}\\)$`).test(last)) {
    return normalizeSavepath(parts.slice(0, -1).join('/'))
  }
  return p
}

function driveTypeForTask(task: TaskItem) {
  const acc = (accountsData.value || []).find(a => String(a.name) === String(task.account_name || ''))
  if (acc) return String(acc.drive_type || '').trim() || null
  const byUrl = detectDriveTypeByUrl(task.shareurl)
  return byUrl ? String(byUrl) : null
}

function currentDriveType() {
  if (state.account_choice !== '__AUTO__') {
    const acc = (accountsData.value || []).find(a => String(a.name) === state.account_choice)
    if (acc) return String(acc.drive_type || '').trim() || null
  }
  const dt = detectDriveTypeByUrl(state.shareurl)
  return dt ? String(dt) : null
}

function existingTaskCategory(task: TaskItem) {
  const savepath = normalizeSavepath(task.savepath)
  if (savepath.includes('/动漫')) return '动漫'
  if (savepath.includes('/综艺')) return '综艺'
  const mt = String(task.tmdb_media_type || '').toLowerCase()
  if (mt === 'movie') return '电影'
  if (mt === 'tv') return '电视剧'
  return ''
}

function categoryFromTmdb(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  if (mediaType === 'movie') return '电影'
  const genres = Array.isArray(detail?.genres) ? detail.genres : []
  const ids = new Set<number>()
  const names = new Set<string>()
  for (const g of genres) {
    const id = Number((g as any)?.id)
    if (Number.isFinite(id) && id > 0) ids.add(id)
    const n = String((g as any)?.name || '').trim().toLowerCase()
    if (n) names.add(n)
  }
  const hasAnime = ids.has(16) || Array.from(names).some(n => n.includes('animation') || n.includes('动画'))
  if (hasAnime) return '动漫'
  const varietyIds = new Set([10764, 10767, 10763])
  const hasVariety = Array.from(varietyIds).some(id => ids.has(id)) || Array.from(names).some(n => n.includes('reality') || n.includes('talk') || n.includes('真人秀') || n.includes('脱口秀'))
  if (hasVariety) return '综艺'
  return '电视剧'
}

function ensureCategorySegment(base: string, category: string) {
  const p = normalizeSavepath(base)
  const c = String(category || '').trim()
  if (!p || !c) return p
  const segs = p.split('/').filter(Boolean)
  if (segs.includes(c)) return p
  return normalizeSavepath(`${p}/${c}`)
}

function yearFromTmdbDetail(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  const raw = mediaType === 'movie' ? String(detail?.release_date || '') : String(detail?.first_air_date || '')
  if (raw.length >= 4 && /^\d{4}/.test(raw)) return Number(raw.slice(0, 4))
  return null
}

function appendYearSuffix(name: string, year: number | null) {
  const n = String(name || '').trim()
  if (!n) return ''
  if (!year || !Number.isFinite(year) || year < 1900 || year > 2100) return n
  if (/\(\d{4}\)\s*$/.test(n)) return n
  return `${n}(${year})`
}

async function getTmdbDetailForCurrent() {
  const id = Number(state.tmdb_id) || 0
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  if (id <= 0 || (mt !== 'movie' && mt !== 'tv')) return null
  const key = `${mt}:${id}`
  if (tmdbDetailCache.value[key]) return tmdbDetailCache.value[key]
  try {
    const detail = await fetchTMDBDetail(mt as any, id)
    tmdbDetailCache.value[key] = detail
    return detail
  } catch {
    tmdbDetailCache.value[key] = null
    return null
  }
}

async function autoFillSavepath(runId: number) {
  // Only fill savepath for new tasks when savepath is empty or was auto-applied
  if (isEditing.value) return
  if (savepathTouched.value) return
  const currentSave = String(state.savepath || '').trim()
  if (currentSave && currentSave !== savepathLastApplied.value) return

  const dt = currentDriveType()
  if (!dt) return

  // Load tasks
  let allTasks = tasksData.value
  if (!allTasks || !allTasks.length) {
    try {
      allTasks = await fetchTasks()
    } catch {
      return
    }
  }
  if (runId !== autoLocateRunId.value) return

  const candidates = (allTasks || []).filter(t => driveTypeForTask(t) === dt && String(t.savepath || '').trim())
  if (!candidates.length) return

  // Get TMDB detail for category/year
  const detail = await getTmdbDetailForCurrent()
  if (runId !== autoLocateRunId.value) return

  const mt = String(state.tmdb_media_type || '').toLowerCase()
  const category = categoryFromTmdb(mt, detail)
  const titleFromTmdb = String(detail?.name || detail?.title || '').trim()
  const baseNameSeg = String(state.taskname || '').trim() || titleFromTmdb
  const year = yearFromTmdbDetail(mt, detail)
  const nameSeg = appendYearSuffix(baseNameSeg, year)
  if (!nameSeg) return

  const filteredByCat = candidates.filter(t => existingTaskCategory(t) === category)
  const pool = filteredByCat.length ? filteredByCat : candidates

  const counts = new Map<string, number>()
  const firstIdx = new Map<string, number>()
  for (let i = 0; i < pool.length; i++) {
    const t = pool[i]
    const base = cleanSavepathBase(t.savepath, t.taskname)
    if (!base) continue
    counts.set(base, (counts.get(base) || 0) + 1)
    if (!firstIdx.has(base)) firstIdx.set(base, i)
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1]
    return (firstIdx.get(a[0]) || 0) - (firstIdx.get(b[0]) || 0)
  })
  const baseRoot = sorted[0]?.[0] || ''
  if (!baseRoot) return

  let root = ensureCategorySegment(baseRoot, category)
  root = normalizeSavepath(root)
  const suggested = normalizeSavepath(`${root}/${nameSeg}`)

  state.savepath = suggested
  savepathLastApplied.value = suggested
}

// Auto-preview: watch shareurl changes with debounce
watch(() => state.shareurl, (newUrl, oldUrl) => {
  if (isInitializing.value) return
  if (autoPreviewTimer.value) clearTimeout(autoPreviewTimer.value)
  if (!newUrl?.trim()) {
    previewHint.value = ''
    return
  }
  if (newUrl === oldUrl) return

  autoPreviewTimer.value = setTimeout(async () => {
    autoLocateRunId.value += 1
    const runId = autoLocateRunId.value
    previewHint.value = '正在自动定位...'

    try {
      const url = newUrl.trim()

      // Step 1: Use previewShareBatch to get pdir_fid
      const batchRes = await previewShareBatch({ shareurls: [url], account_name: state.account_choice !== '__AUTO__' ? state.account_choice : null })
      if (runId !== autoLocateRunId.value) return

      const row = (batchRes.items || []).find(x => String(x.shareurl || '').trim() === url)
      if (row && row.ok) {
        const fid = String((row as any).pdir_fid || (row as any).resolved_pdir_fid || '').trim()
        if (fid && fid !== '0' && fid !== 'root') {
          // Auto deep-in: rewrite shareurl with resolved pdir_fid
          const resolved = getShareurl(url, { fid })
          if (resolved !== url) {
            state.shareurl = resolved
            state.startfid = ''
            // The watch will re-trigger, so return here
            previewHint.value = '已自动定位到实际文件夹'
            return
          }
        }
      }

      // Step 2: Preview share to get file list
      const res = await previewShare(buildPreviewParams())
      if (runId !== autoLocateRunId.value) return

      if (res?.items?.length) {
        previewItems.value = res.items
        previewTotal.value = res.items.length

        // If there's only one directory, try auto-drilling
        const dirs = res.items.filter((i: any) => i.is_dir)
        if (dirs.length === 1 && res.items.length === 1) {
          const deepRes = await previewShare(buildPreviewParams({ pdir_fid: dirs[0].fid }))
          if (runId !== autoLocateRunId.value) return
          if (deepRes?.items?.length) {
            previewItems.value = deepRes.items
            previewTotal.value = deepRes.items.length
            // Rewrite shareurl to deep path
            const deepUrl = getShareurl(state.shareurl.trim(), { fid: dirs[0].fid })
            if (deepUrl !== state.shareurl.trim()) {
              state.shareurl = deepUrl
              previewHint.value = `已自动进入: ${dirs[0].name}`
              return
            }
          }
        }

        // Step 3: Auto-fill task name
        if (!state.taskname && res.items.length > 0) {
          // Use first item name or share name from response
          const firstDir = res.items.find((i: any) => i.is_dir)
          state.taskname = firstDir?.name || res.items[0]?.name || ''
        }

        previewHint.value = `已预览 ${previewTotal.value} 个文件`
      } else {
        previewHint.value = '链接无效或无文件'
      }

      // Step 4: Auto-fill savepath
      if (runId === autoLocateRunId.value) {
        autoFillSavepath(runId).catch(() => {})
      }
    } catch (e: any) {
      if (runId !== autoLocateRunId.value) return
      previewHint.value = '预览失败: ' + (e?.message || '网络错误')
    }
  }, 800)
})

// ===== Preview =====
function buildPreviewParams(overrides: Record<string, any> = {}) {
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : undefined
  return {
    shareurl: state.shareurl.trim(),
    account_name: accountName,
    max_items: 200,
    taskname: state.taskname || undefined,
    pattern: state.pattern || undefined,
    replace: state.replace || undefined,
    sort_index: state.sort_index ?? undefined,
    savepath: state.savepath || undefined,
    ignore_extension: state.ignore_extension ?? undefined,
    update_subdir: state.update_subdir || undefined,
    startfid: state.startfid || undefined,
    tmdb_id: state.tmdb_id ?? undefined,
    tmdb_media_type: state.tmdb_media_type || undefined,
    ...overrides,
  }
}

async function handlePreview() {
  const url = state.shareurl.trim()
  if (!url) return
  previewing.value = true
  previewError.value = ''
  previewItems.value = []
  previewTotal.value = 0
  previewDirStack.value = []
  try {
    const res = await previewShare(buildPreviewParams())
    const items = res.items || []
    previewTotal.value = items.length
    previewItems.value = items
    if (!state.taskname && items.length > 0) {
      state.taskname = items[0].name || ''
    }
    if (items.length > 0) {
      previewPage.value = 1
      showPreviewModal.value = true
    }
  } catch (e: any) {
    previewError.value = e?.message || '预览失败'
  } finally {
    previewing.value = false
  }
}

async function handlePreviewRefresh() {
  const pdirFid = previewDirStack.value.length > 0 ? previewDirStack.value[previewDirStack.value.length - 1].pdir_fid : undefined
  await loadPreviewDir(pdirFid)
}

async function loadPreviewDir(pdirFid?: string) {
  const url = state.shareurl.trim()
  if (!url) return
  previewing.value = true
  previewError.value = ''
  try {
    const res = await previewShare(buildPreviewParams({ pdir_fid: pdirFid || null }))
    const items = res.items || []
    previewTotal.value = items.length
    previewItems.value = items
    previewPage.value = 1
  } catch (e: any) {
    previewError.value = e?.message || '加载失败'
  } finally {
    previewing.value = false
  }
}

async function enterPreviewDir(item: SharePreviewItem) {
  previewDirStack.value.push({ pdir_fid: item.fid, name: item.name })
  await loadPreviewDir(item.fid)
}

function previewGoBack() {
  previewDirStack.value.pop()
  const last = previewDirStack.value.length > 0 ? previewDirStack.value[previewDirStack.value.length - 1].pdir_fid : undefined
  loadPreviewDir(last)
}

function pickCurrentShareFolder() {
  const current = previewDirStack.value.at(-1)
  if (current) {
    // Update startfid to null and record the pdir_fid in shareurl query
    state.startfid = ''
    // Build a new shareurl with pdir_fid appended
    const baseUrl = state.shareurl.trim()
    try {
      const url = new URL(baseUrl.startsWith('http') ? baseUrl : `https://x.com/${baseUrl}`)
      url.searchParams.set('fid', current.pdir_fid)
      state.shareurl = baseUrl.startsWith('http') ? url.toString() : `${url.pathname.slice(1)}${url.search}`
    } catch {
      // Fallback: just append ?fid=...
      const sep = baseUrl.includes('?') ? '&' : '?'
      state.shareurl = `${baseUrl}${sep}fid=${current.pdir_fid}`
    }
    toast.success(`已选择当前目录: ${current.name}`)
    showPreviewModal.value = false
  }
}

// ===== Path Browser =====
async function openPathBrowser() {
  showPathBrowser.value = true
  browsePath.value = state.savepath || '/'
  browseError.value = ''
  await loadBrowseDir(browsePath.value)
}

async function loadBrowseDir(dirPath: string) {
  browseLoading.value = true
  browseError.value = ''
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : null
  try {
    const data = await browseDrive({
      dir_path: dirPath,
      account_name: accountName,
      shareurl: state.shareurl || null,
      max_items: 200,
    })
    browsePath.value = data.dir_path || dirPath
    browseItems.value = data.items || []
  } catch (e: any) {
    browseError.value = e?.message || '浏览失败'
    browseItems.value = []
  } finally {
    browseLoading.value = false
  }
}

function enterDir(item: DriveBrowseItem) {
  const newPath = browsePath.value.endsWith('/')
    ? browsePath.value + item.name
    : browsePath.value + '/' + item.name
  loadBrowseDir(newPath)
}

function browseUp() {
  const parts = browsePath.value.replace(/\/+$/, '').split('/')
  parts.pop()
  const parent = parts.join('/') || '/'
  loadBrowseDir(parent)
}

function confirmPath() {
  state.savepath = browsePath.value
  showPathBrowser.value = false
}

function useCurrentPath(withTaskname: boolean) {
  const base = browsePath.value || '/'
  if (withTaskname && state.taskname?.trim()) {
    state.savepath = `${base}/${state.taskname.trim()}`.replace(/\/+/g, '/')
  } else {
    state.savepath = base
  }
  showPathBrowser.value = false
}

// ===== TMDB Search =====
let tmdbSearchTimer: ReturnType<typeof setTimeout> | null = null

function openTmdbSearch() {
  showTmdbSearch.value = !showTmdbSearch.value
  if (showTmdbSearch.value) {
    tmdbQuery.value = state.taskname || ''
    tmdbResults.value = []
    if (tmdbQuery.value.trim()) {
      doTmdbSearch()
    }
  }
}

// Watch tmdbQuery with debounce for auto-search
watch(tmdbQuery, (val) => {
  if (!showTmdbSearch.value) return
  if (tmdbSearchTimer) clearTimeout(tmdbSearchTimer)
  if (!val.trim()) return
  tmdbSearchTimer = setTimeout(() => doTmdbSearch(), 500)
})

async function doTmdbSearch() {
  const q = tmdbQuery.value.trim()
  if (!q) return
  tmdbSearching.value = true
  tmdbResults.value = []
  try {
    const data = await searchTMDB({ q, type: state.tmdb_media_type })
    tmdbResults.value = data.items || []
  } catch (e: any) {
    toast.error(e?.message || 'TMDB搜索失败')
  } finally {
    tmdbSearching.value = false
  }
}

function selectTmdb(item: TMDBBrief) {
  state.tmdb_id = item.id || null
  state.tmdb_media_type = (item.media_type as 'tv' | 'movie') || state.tmdb_media_type
  if (!state.taskname) {
    state.taskname = item.title || item.name || ''
  }
  showTmdbSearch.value = false
  toast.success(`已关联: ${item.title || item.name} (${item.id})`)
}

// ===== StartFID Picker =====
async function openStartfidPicker() {
  if (!state.shareurl.trim()) {
    toast.error('请先填写分享链接')
    return
  }
  showStartfidPicker.value = true
  startfidLoading.value = true
  startfidError.value = ''
  startfidItems.value = []
  try {
    const data = await previewShare(buildPreviewParams({ max_items: 500, startfid: null }))
    startfidItems.value = (data.items || []).filter((item) => !item.is_dir)
  } catch (e: any) {
    startfidError.value = e?.message || '获取文件列表失败'
  } finally {
    startfidLoading.value = false
  }
}

function selectStartfid(item: SharePreviewItem) {
  state.startfid = item.fid
  showStartfidPicker.value = false
  toast.success(`已选择起始文件: ${item.name}`)
}

// ===== Weekday =====
function toggleWeekday(day: number) {
  const idx = state.runweek.indexOf(day)
  if (idx === -1) {
    state.runweek.push(day)
    state.runweek.sort((a, b) => a - b)
  } else {
    state.runweek.splice(idx, 1)
  }
}

// ===== Build Payload =====
function buildPayload() {
  const accountName = state.account_choice !== '__AUTO__' ? state.account_choice : null
  const extra: Record<string, any> = {
    runweek_mode: state.runweek_mode,
    runweek: state.runweek_mode === 'auto' ? [] : [...state.runweek],
    update_subdir_resave_mode: state.update_subdir_resave_mode,
    auto_update_115_shareurl: Boolean(state.auto_update_115_shareurl),
  }
  return {
    task_type: 'drama',
    taskname: state.taskname.trim() || '未命名任务',
    shareurl: state.shareurl.trim(),
    savepath: state.savepath.trim(),
    sync_task_uids: [...state.sync_task_uids],
    pattern: state.pattern.trim() || null,
    replace: state.replace.trim() || null,
    enddate: state.enddate.trim() || null,
    ignore_extension: state.ignore_extension,
    sort_index: state.sort_index,
    startfid: state.startfid.trim() || null,
    account_name: accountName,
    update_subdir: state.update_subdir.trim() || null,
    tmdb_id: state.tmdb_id,
    tmdb_media_type: state.tmdb_id ? state.tmdb_media_type : null,
    enabled: state.enabled,
    addition: state.addition,
    extra,
  }
}

// ===== Submit =====
async function handleSubmit() {
  if (!state.shareurl.trim()) {
    toast.error('请填写分享链接')
    return
  }
  if (!state.savepath.trim()) {
    toast.error('请填写保存路径')
    return
  }

  const payload = buildPayload()
  submitting.value = true
  try {
    if (isEditing.value && props.editTask) {
      await updateMutation.mutateAsync({ taskId: props.editTask.id, payload })
    } else {
      await createMutation.mutateAsync(payload)
    }
    toast.success('保存成功')
    resetAndClose()
  } catch (e: any) {
    toast.error(e?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

// ===== Run Once =====
function handleRunOnce() {
  if (!state.shareurl.trim()) {
    toast.error('请填写分享链接')
    return
  }
  if (!state.savepath.trim()) {
    toast.error('请填写保存路径')
    return
  }
  const payload = buildPayload()
  emit('run-once', payload)
}

function resetAndClose() {
  resetForm()
  previewItems.value = []
  previewError.value = ''
  emit('close')
}

// ===== Resource Search Suggestions =====
function scheduleLightSearch() {
  if (!state.taskname?.trim() || state.taskname.trim().length < 2) {
    taskSuggestions.visible = false
    return
  }
  if (taskSuggestions.searchTimer) clearTimeout(taskSuggestions.searchTimer)
  taskSuggestions.searchTimer = setTimeout(() => searchSuggestions(0), 1000)
}

async function searchSuggestions(deep: 0 | 1) {
  const q = state.taskname?.trim()
  if (!q || q.length < 2) return

  taskSuggestions.loading = true
  taskSuggestions.visible = true
  taskSuggestions.message = ''
  try {
    const dt = currentDriveType()
    const res = await fetchTaskSuggestions(q, deep, dt)
    taskSuggestions.items = res?.data || []
    taskSuggestions.message = res?.message || ''
    // 搜索完成后自动验证链接有效性
    if (taskSuggestions.items.length) {
      verifySuggestions()
    }
  } catch {
    taskSuggestions.items = []
    taskSuggestions.message = '搜索失败'
  } finally {
    taskSuggestions.loading = false
  }
}

async function verifySuggestions() {
  const items = taskSuggestions.items
  if (!items.length) return

  // 按网盘类型分组
  const groups = new Map<string, Array<{ item: TaskSuggestionItem; url: string }>>()
  for (const item of items) {
    const url = item.shareurl
    if (!url) continue
    const dt = detectDriveTypeByUrl(url) || 'other'
    if (!groups.has(dt)) groups.set(dt, [])
    groups.get(dt)!.push({ item, url })
  }

  // 逐组并发验证，每组完成立即更新UI
  const promises = [...groups.values()].map(async (group) => {
    const urls = group.map(g => g.url)
    try {
      const res = await previewShareBatch({ shareurls: urls })
      if (res?.items) {
        for (const { item, url } of group) {
          const row = res.items.find((r: any) => r.shareurl === url || r.url === url)
          if (row) {
            item.verify = Boolean(row.ok)
            // 记录最大视频文件大小
            if (row.latest_video?.size) item.maxFileSize = row.latest_video.size
          } else {
            item.verify = false
          }
        }
      }
    } catch {
      // 该组验证失败，标记为未知
    }
    // 每组完成后触发响应式更新
    taskSuggestions.items = [...taskSuggestions.items]
  })

  await Promise.allSettled(promises)

  // 所有验证完成后，按大小排序并标记最大的
  markLargestAndSort()
}

function markLargestAndSort() {
  const items = taskSuggestions.items
  const verified = items.filter(i => i.verify === true && i.maxFileSize)

  // 清除旧的 max 标记
  for (const item of items) item.isLargest = false

  if (verified.length) {
    // 找到最大的
    verified.sort((a, b) => (b.maxFileSize || 0) - (a.maxFileSize || 0))
    verified[0].isLargest = true

    // 排序：有效的按大小降序排前面，失效的排后面
    taskSuggestions.items = [
      ...items.filter(i => i.verify === true).sort((a, b) => (b.maxFileSize || 0) - (a.maxFileSize || 0)),
      ...items.filter(i => i.verify !== true),
    ]
  }
}

function selectSuggestion(item: TaskSuggestionItem) {
  taskSuggestions.visible = false
  state.shareurl = item.shareurl // 填充分享链接，会触发自动定位
}

function hideSuggestionsDelayed() {
  setTimeout(() => {
    taskSuggestions.visible = false
  }, 200)
}

// ===== Helpers =====
function getTmdbTitle(item: TMDBBrief): string {
  return item.title || item.name || item.original_title || item.original_name || ''
}
function getTmdbYear(item: TMDBBrief): string {
  const d = item.release_date || item.first_air_date
  return d ? d.slice(0, 4) : ''
}
function getTmdbPoster(item: TMDBBrief): string {
  return item.poster_path ? `https://image.tmdb.org/t/p/w92${item.poster_path}` : ''
}
</script>

<template>
  <!-- ===== Preview Modal ===== -->
  <Teleport to="body">
    <div v-if="showPreviewModal" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/60" @click="showPreviewModal = false" />
      <div class="relative z-10 w-[720px] max-h-[80vh] rounded-lg bg-[hsl(var(--background))] shadow-xl flex flex-col">
        <div class="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))]">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">分享链接预览（共 {{ previewTotal }} 个文件）</h3>
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))]" @click="showPreviewModal = false">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>
        <!-- Toolbar -->
        <div class="flex items-center gap-2 px-5 py-2 border-b border-[hsl(var(--border))]">
          <button class="rounded p-1.5 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]" title="刷新" @click="handlePreviewRefresh" :disabled="previewing">
            <RefreshCw class="h-4 w-4" :class="previewing ? 'animate-spin' : ''" />
          </button>
          <button v-if="previewDirStack.length > 0" class="rounded p-1.5 hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))] flex items-center gap-1 text-xs" @click="previewGoBack">
            <ArrowUp class="h-3.5 w-3.5" /> 返回上级
          </button>
          <span v-if="previewDirStack.length > 0" class="text-xs text-[hsl(var(--muted-foreground))] truncate">/ {{ previewDirStack.map(d => d.name).join(' / ') }}</span>
          <div class="flex-1" />
          <Button size="sm" variant="default" @click="pickCurrentShareFolder" :disabled="!previewDirStack.length">
            使用当前文件夹
          </Button>
        </div>
        <!-- Table Header -->
        <div class="grid grid-cols-[1fr_80px_1fr_120px] gap-2 px-3 py-2 border-b-2 border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]">
          <span>名称</span><span>大小</span><span>重命名预览</span><span>时间</span>
        </div>
        <!-- Table Body -->
        <div class="flex-1 overflow-y-auto">
          <div
            v-for="(item, idx) in previewPageItems"
            :key="idx"
            class="grid grid-cols-[1fr_80px_1fr_120px] gap-2 items-center px-3 py-2 border-b border-[hsl(var(--border))] hover:bg-[hsl(var(--accent)/.5)] text-sm"
          >
            <div class="flex items-center gap-2 min-w-0">
              <component :is="item.is_dir ? Folder : FileText" class="h-4 w-4 shrink-0 text-[hsl(var(--muted-foreground))]" />
              <span class="truncate" :class="item.is_dir ? 'cursor-pointer text-[hsl(var(--primary))] hover:underline' : ''" @click="item.is_dir && enterPreviewDir(item)">{{ item.name }}</span>
            </div>
            <div class="text-[hsl(var(--muted-foreground))] text-xs">{{ item.is_dir ? (item.include_items || item.children_count || 0) + '项' : formatSize(item.size || 0) }}</div>
            <div class="truncate text-xs">
              <span v-if="item.file_name_re" class="text-green-600">{{ item.file_name_re }}</span>
              <span v-else-if="item.file_name_saved" class="text-[hsl(var(--muted-foreground))]">{{ item.file_name_saved }}</span>
              <span v-else-if="state.pattern" class="text-red-500">×</span>
              <span v-else class="text-[hsl(var(--muted-foreground))]">-</span>
            </div>
            <div class="text-[hsl(var(--muted-foreground))] text-xs">{{ formatTime(item.updated_at) }}</div>
          </div>
        </div>
        <!-- Pagination -->
        <div v-if="previewTotalPages > 1" class="flex items-center justify-center gap-3 px-5 py-3 border-t border-[hsl(var(--border))]">
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))] disabled:opacity-30" :disabled="previewPage <= 1" @click="previewPage--">
            <ChevronLeft class="h-4 w-4 text-[hsl(var(--foreground))]" />
          </button>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ previewPage }} / {{ previewTotalPages }}</span>
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))] disabled:opacity-30" :disabled="previewPage >= previewTotalPages" @click="previewPage++">
            <ChevronRight class="h-4 w-4 text-[hsl(var(--foreground))]" />
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Path Browser Modal ===== -->
  <Teleport to="body">
    <div v-if="showPathBrowser" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="showPathBrowser = false" />
      <div class="relative z-10 w-[600px] max-h-[80vh] rounded-lg bg-[hsl(var(--background))] shadow-xl flex flex-col">
        <div class="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))]">
          <h3 class="text-sm font-semibold text-[hsl(var(--foreground))]">浏览保存路径</h3>
          <button class="rounded p-1 hover:bg-[hsl(var(--accent))]" @click="showPathBrowser = false">
            <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </button>
        </div>
        <div class="px-5 py-3 border-b border-[hsl(var(--border))] flex items-center justify-between">
          <span class="text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[360px]">当前: {{ browsePath }}</span>
          <button class="text-xs text-[hsl(var(--primary))] hover:underline flex items-center gap-1 shrink-0" @click="browseUp">
            <ArrowUp class="h-3 w-3" /> 返回上级
          </button>
        </div>
        <div class="flex-1 overflow-y-auto px-5 py-3">
          <div v-if="browseLoading" class="flex items-center justify-center py-8">
            <Loader2 class="h-5 w-5 animate-spin text-[hsl(var(--muted-foreground))]" />
          </div>
          <div v-else-if="browseError" class="text-xs text-red-500 py-4 text-center">{{ browseError }}</div>
          <div v-else-if="browseItems.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-4 text-center">无文件或目录</div>
          <div v-else class="space-y-0.5">
            <div
              v-for="item in browseItems"
              :key="item.fid"
              class="flex items-center gap-2 px-2 py-2 rounded text-sm"
              :class="item.is_dir ? 'cursor-pointer hover:bg-[hsl(var(--accent))]' : 'opacity-80'"
              @click="item.is_dir && enterDir(item)"
            >
              <component
                :is="item.is_dir ? Folder : FileText"
                class="h-4 w-4 text-[hsl(var(--muted-foreground))] shrink-0"
              />
              <span class="truncate text-[hsl(var(--foreground))] flex-1 min-w-0">{{ item.file_name || item.name }}</span>
              <span class="shrink-0 text-[10px] text-[hsl(var(--muted-foreground))]">
                {{ item.is_dir ? `${item.include_items || 0}项` : formatSize(item.size || 0) || '-' }}
              </span>
            </div>
          </div>
        </div>
        <div class="px-5 py-3 border-t border-[hsl(var(--border))] flex gap-2">
          <Button size="sm" @click="useCurrentPath(false)">使用当前文件夹</Button>
          <Button v-if="state.taskname?.trim()" size="sm" variant="outline" @click="useCurrentPath(true)">
            当前文件夹/{{ state.taskname.trim() }}
          </Button>
          <div class="flex-1" />
          <Button size="sm" class="" @click="confirmPath">确认选择此路径</Button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ===== Main Sheet ===== -->
  <Teleport to="body">
    <Transition name="sheet-right">
      <div v-if="props.open" class="fixed inset-0 z-50 flex justify-end">
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/50 transition-opacity" @click="resetAndClose" />
        <!-- Panel -->
        <div class="relative z-10 flex h-full w-full max-w-lg flex-col bg-[hsl(var(--card))] shadow-xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
            <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">{{ title }}</h2>
            <button class="rounded p-1 hover:bg-[hsl(var(--accent))] transition-colors" @click="resetAndClose">
              <X class="h-5 w-5 text-[hsl(var(--muted-foreground))]" />
            </button>
          </div>

          <!-- Scrollable Form -->
          <div class="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            <!-- ===== 基础信息 ===== -->
            <section class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">
                基础信息
              </h3>

              <!-- 分享链接 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">
                  分享链接 <span class="text-red-500">*</span>
                </label>
                <div class="flex gap-2">
                  <Input v-model="state.shareurl" placeholder="粘贴分享链接..." class="flex-1" />
                  <Button variant="outline" size="sm" :disabled="!state.shareurl.trim() || previewing" @click="handlePreview">
                    <Loader2 v-if="previewing" class="h-4 w-4 animate-spin" />
                    <Eye v-else class="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <!-- 预览错误 -->
              <div v-if="previewError" class="rounded-md bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-400">
                {{ previewError }}
              </div>
              <!-- 预览提示（自动预览 / 手动预览） -->
              <div v-if="previewHint || previewItems.length > 0" class="flex items-center gap-2">
                <p class="text-xs text-[hsl(var(--muted-foreground))]">
                  {{ previewHint || `已预览 ${previewTotal} 个文件` }}
                </p>
                <button class="text-xs text-[hsl(var(--primary))] hover:underline" @click="showPreviewModal = true">
                  查看详情
                </button>
              </div>

              <!-- 任务名称 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">任务名称</label>
                <div class="relative">
                  <Input v-model="state.taskname" placeholder="可选，默认从预览自动提取"
                    @input="scheduleLightSearch"
                    @focus="state.taskname?.trim()?.length >= 2 && (taskSuggestions.visible = true)"
                    @blur="hideSuggestionsDelayed" />
                  <Button v-if="state.taskname?.trim()?.length >= 2"
                    size="sm" variant="ghost"
                    class="absolute right-1 top-1/2 -translate-y-1/2 h-7 text-xs"
                    :disabled="taskSuggestions.loading"
                    @click="searchSuggestions(1)">
                    <Search class="h-3 w-3 mr-1" />
                    搜索资源
                  </Button>
                </div>

                <!-- 搜索建议面板 -->
                <div v-if="taskSuggestions.visible && (taskSuggestions.items.length || taskSuggestions.loading || taskSuggestions.message)"
                  class="mt-1.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-md max-h-60 overflow-y-auto">
                  <!-- Loading -->
                  <div v-if="taskSuggestions.loading" class="flex items-center justify-center py-3 text-xs text-[hsl(var(--muted-foreground))]">
                    <Loader2 class="h-3.5 w-3.5 animate-spin mr-1.5" /> 搜索中...
                  </div>
                  <!-- 提示消息 -->
                  <div v-if="taskSuggestions.message" class="px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] border-b border-[hsl(var(--border))]">
                    {{ taskSuggestions.message }}
                  </div>
                  <!-- 结果列表 -->
                  <div v-for="(item, idx) in taskSuggestions.items" :key="idx"
                    class="px-3 py-2 cursor-pointer hover:bg-[hsl(var(--accent))] border-b border-[hsl(var(--border))] last:border-0"
                    @mousedown.prevent="selectSuggestion(item)">
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-sm font-medium truncate">{{ item.taskname }}</span>
                      <div class="flex items-center gap-1 shrink-0">
                        <Badge v-if="item.isLargest" variant="outline" class="text-[10px] bg-amber-50 text-amber-600 border-amber-200">最大</Badge>
                        <span v-if="item.maxFileSize" class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ formatSize(item.maxFileSize) }}</span>
                        <Badge v-if="item.verify === true" variant="outline" class="text-[10px] text-green-600 border-green-300">有效</Badge>
                        <Badge v-else-if="item.verify === false" variant="outline" class="text-[10px] text-red-500 border-red-300">失效</Badge>
                        <Badge v-if="item.source" variant="outline" class="text-[10px]">{{ item.source }}</Badge>
                      </div>
                    </div>
                    <!-- 链接可点击跳转 -->
                    <a :href="item.shareurl" target="_blank" rel="noopener"
                      class="text-xs text-[hsl(var(--primary))] hover:underline mt-0.5 block truncate"
                      @mousedown.stop @click.stop>{{ item.shareurl }}</a>
                    <div class="flex items-center gap-2 mt-0.5">
                      <span v-if="item.datetime" class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ item.datetime }}</span>
                      <span v-if="item.channel" class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ item.channel }}</span>
                    </div>
                  </div>
                  <!-- 无结果 -->
                  <div v-if="!taskSuggestions.loading && !taskSuggestions.items.length && !taskSuggestions.message" class="px-3 py-3 text-xs text-center text-[hsl(var(--muted-foreground))]">
                    无搜索结果
                  </div>
                </div>
              </div>

              <!-- 保存路径 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">
                  保存路径 <span class="text-red-500">*</span>
                </label>
                <div class="flex gap-2">
                  <Input v-model="state.savepath" placeholder="网盘保存路径，如 /我的追剧/海贼王" class="flex-1" />
                  <Button variant="outline" size="sm" @click="openPathBrowser">
                    <FolderOpen class="h-4 w-4 mr-1" />
                    浏览
                  </Button>
                </div>
              </div>

              <!-- 账号选择 -->
              <div>
                <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">账号选择</label>
                <select
                  v-model="state.account_choice"
                  class="flex h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-sm text-[hsl(var(--foreground))] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))]"
                >
                  <option value="__AUTO__">自动选择</option>
                  <option v-for="acc in activeAccounts" :key="acc.name" :value="acc.name">
                    {{ acc.name }}（{{ acc.drive_type }}）
                  </option>
                </select>
              </div>
            </section>

            <!-- ===== TMDB 关联 ===== -->
            <section class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">
                TMDB 关联（可选）
              </h3>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">TMDB ID</label>
                  <div class="flex gap-1.5">
                    <Input
                      :model-value="state.tmdb_id ?? ''"
                      type="number"
                      placeholder="如 12345"
                      class="flex-1"
                      @update:model-value="state.tmdb_id = $event ? Number($event) : null"
                    />
                    <Button variant="outline" size="sm" @click="openTmdbSearch">
                      <Search class="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">类型</label>
                  <select
                    v-model="state.tmdb_media_type"
                    class="flex h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-sm text-[hsl(var(--foreground))] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))]"
                  >
                    <option value="tv">剧集 (TV)</option>
                    <option value="movie">电影 (Movie)</option>
                  </select>
                </div>
              </div>

              <!-- TMDB 搜索面板 -->
              <div v-if="showTmdbSearch" class="rounded-md border border-[hsl(var(--border))] p-3 space-y-2">
                <Input
                  v-model="tmdbQuery"
                  placeholder="输入影视名称搜索TMDB..."
                  class="h-8 text-xs"
                  @keydown.enter="doTmdbSearch"
                />
                <div v-if="tmdbSearching" class="flex items-center justify-center py-3">
                  <Loader2 class="h-4 w-4 animate-spin text-[hsl(var(--muted-foreground))]" />
                </div>
                <div v-else-if="tmdbResults.length === 0 && tmdbQuery.trim()" class="text-xs text-[hsl(var(--muted-foreground))] py-2 text-center">
                  正在等待搜索结果...
                </div>
                <div v-else class="max-h-48 overflow-y-auto space-y-1">
                  <div
                    v-for="item in tmdbResults"
                    :key="item.id ?? item.name ?? ''"
                    class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-[hsl(var(--accent))]"
                    @click="selectTmdb(item)"
                  >
                    <img
                      v-if="getTmdbPoster(item)"
                      :src="getTmdbPoster(item)"
                      class="h-10 w-7 rounded object-cover shrink-0"
                      alt=""
                    />
                    <div v-else class="h-10 w-7 rounded bg-[hsl(var(--muted))] flex items-center justify-center shrink-0">
                      <Search class="h-3 w-3 text-[hsl(var(--muted-foreground))]" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <p class="text-xs font-medium text-[hsl(var(--foreground))] truncate">{{ getTmdbTitle(item) }}</p>
                      <p class="text-[10px] text-[hsl(var(--muted-foreground))]">
                        {{ getTmdbYear(item) }} · {{ item.media_type === 'movie' ? '电影' : '剧集' }} · ID: {{ item.id }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- ===== 重命名规则 ===== -->
            <section class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">
                重命名规则（可选）
              </h3>
              <!-- 内置规则选择 -->
              <div>
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">内置规则</label>
                <select
                  :value="selectedRuleIdx"
                  class="flex h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-sm text-[hsl(var(--foreground))] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))]"
                  @change="applyBuiltinRule"
                >
                  <option v-for="(rule, idx) in builtinRules" :key="idx" :value="idx">
                    {{ rule.label }}
                  </option>
                </select>
              </div>
              <div>
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">匹配正则 (pattern)</label>
                <Input v-model="state.pattern" placeholder="如 (.*)" />
              </div>
              <div>
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">替换字符串 (replace)</label>
                <Input v-model="state.replace" placeholder="如 $1" />
              </div>
              <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                <input v-model="state.ignore_extension" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                忽略扩展名
              </label>
            </section>

            <!-- ===== 插件选项（紧凑折叠式） ===== -->
            <section v-if="plugins.length > 0" class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">
                插件选项
              </h3>
              <div class="space-y-2">
                <div v-for="plugin in plugins" :key="plugin.plugin_key"
                  class="rounded-md border border-[hsl(var(--border))] overflow-hidden">
                  <!-- 标题行：点击展开/折叠 -->
                  <div class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[hsl(var(--accent)/.5)]"
                    @click="togglePluginExpand(plugin.plugin_key)">
                    <div class="flex items-center gap-2">
                      <ChevronRight class="h-3.5 w-3.5 transition-transform"
                        :class="expandedPlugins.has(plugin.plugin_key) ? 'rotate-90' : ''" />
                      <span class="text-sm">{{ plugin.plugin_key }}</span>
                    </div>
                    <!-- 启用开关（点击不冒泡） -->
                    <div @click.stop>
                      <input type="checkbox"
                        :checked="isPluginEnabled(plugin.plugin_key)"
                        @change="togglePluginEnabled(plugin.plugin_key, $event)"
                        class="h-4 w-4 rounded border-[hsl(var(--border))]" />
                    </div>
                  </div>
                  <!-- 展开内容 -->
                  <div v-if="expandedPlugins.has(plugin.plugin_key)" class="px-3 pb-3 space-y-2 border-t border-[hsl(var(--border))] bg-[hsl(var(--muted)/.3)]">
                    <div v-for="field in plugin.task_config_fields" :key="field.key" class="space-y-0.5 pt-2">
                      <label class="text-xs text-[hsl(var(--muted-foreground))]">{{ field.description || field.label || field.key }}</label>
                      <!-- switch -->
                      <div v-if="field.input_type === 'switch'" class="flex items-center">
                        <input type="checkbox"
                          :checked="state.addition[plugin.plugin_key]?.[field.key]"
                          class="h-4 w-4 rounded border-[hsl(var(--border))]"
                          @change="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: ($event.target as HTMLInputElement).checked }" />
                      </div>
                      <!-- number -->
                      <Input v-else-if="field.input_type === 'number'" type="number"
                        :model-value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        class="h-8 text-sm"
                        @update:model-value="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: $event ? Number($event) : null }" />
                      <!-- textarea -->
                      <textarea v-else-if="field.input_type === 'textarea'"
                        :value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        rows="2"
                        class="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1 text-sm"
                        @input="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: ($event.target as HTMLTextAreaElement).value }" />
                      <!-- text/password -->
                      <Input v-else
                        :type="field.input_type === 'password' ? 'password' : 'text'"
                        :model-value="state.addition[plugin.plugin_key]?.[field.key] ?? ''"
                        class="h-8 text-sm"
                        @update:model-value="state.addition[plugin.plugin_key] = { ...(state.addition[plugin.plugin_key] || {}), [field.key]: $event }" />
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- ===== 调度配置 ===== -->
            <section class="space-y-4">
              <h3 class="text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2">
                调度配置（可选）
              </h3>
              <div>
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">更新日模式</label>
                <select
                  v-model="state.runweek_mode"
                  class="flex h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-sm text-[hsl(var(--foreground))] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))]"
                >
                  <option value="auto">自动（TMDB）</option>
                  <option value="manual">手动</option>
                </select>
              </div>
              <div v-if="state.runweek_mode === 'manual'">
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">更新日（周几）</label>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="day in weekdays"
                    :key="day.value"
                    type="button"
                    class="h-8 w-8 rounded-md text-xs font-medium border transition-colors"
                    :class="state.runweek.includes(day.value)
                      ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-[hsl(var(--primary))]'
                      : 'bg-[hsl(var(--background))] text-[hsl(var(--foreground))] border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]'"
                    @click="toggleWeekday(day.value)"
                  >
                    {{ day.label }}
                  </button>
                </div>
              </div>
              <div>
                <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">截止日期</label>
                <Input v-model="state.enddate" type="date" />
              </div>
            </section>

            <!-- ===== 高级选项（折叠） ===== -->
            <section class="space-y-3">
              <button
                type="button"
                class="flex w-full items-center justify-between text-sm font-semibold text-[hsl(var(--foreground))] border-b border-[hsl(var(--border))] pb-2 hover:text-[hsl(var(--primary))] transition-colors"
                @click="advancedOpen = !advancedOpen"
              >
                <span>高级选项</span>
                <ChevronUp v-if="advancedOpen" class="h-4 w-4" />
                <ChevronDown v-else class="h-4 w-4" />
              </button>

              <div v-if="advancedOpen" class="space-y-4 pt-1">
                <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                  <input v-model="state.enabled" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                  启用任务
                </label>

                <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                  <input v-model="state.auto_update_115_shareurl" type="checkbox" class="h-4 w-4 rounded border-[hsl(var(--border))] text-[hsl(var(--primary))]" />
                  115自动换链
                </label>

                <!-- 关联同步任务 -->
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">关联同步任务</label>
                  <div v-if="syncTasks.length === 0" class="text-xs text-[hsl(var(--muted-foreground))]">暂无同步任务</div>
                  <div v-else class="max-h-32 overflow-y-auto space-y-1.5 rounded-md border border-[hsl(var(--border))] p-2">
                    <label
                      v-for="st in syncTasks"
                      :key="st.uid"
                      class="flex items-center gap-2 text-xs text-[hsl(var(--foreground))] cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        :checked="state.sync_task_uids.includes(st.uid)"
                        class="h-3.5 w-3.5 rounded border-[hsl(var(--border))]"
                        @change="
                          state.sync_task_uids.includes(st.uid)
                            ? state.sync_task_uids = state.sync_task_uids.filter(u => u !== st.uid)
                            : state.sync_task_uids = [...state.sync_task_uids, st.uid]
                        "
                      />
                      {{ st.name }}
                    </label>
                  </div>
                </div>

                <!-- 排序索引 -->
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">排序索引 (sort_index)</label>
                  <Input
                    :model-value="state.sort_index ?? ''"
                    type="number"
                    placeholder="排序优先级"
                    @update:model-value="state.sort_index = $event ? Number($event) : null"
                  />
                </div>

                <!-- 起始文件ID -->
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">起始文件ID (startfid)</label>
                  <div class="flex gap-2">
                    <Input v-model="state.startfid" placeholder="从此fid开始转存" class="flex-1" />
                    <Button variant="outline" size="sm" @click="openStartfidPicker" :disabled="!state.shareurl.trim()">
                      <FileText class="h-4 w-4 mr-1" />
                      选择
                    </Button>
                  </div>

                  <!-- StartFID 文件选择器 -->
                  <div v-if="showStartfidPicker" class="mt-2 rounded-md border border-[hsl(var(--border))] p-3">
                    <div v-if="startfidLoading" class="flex items-center justify-center py-3">
                      <Loader2 class="h-4 w-4 animate-spin text-[hsl(var(--muted-foreground))]" />
                    </div>
                    <div v-else-if="startfidError" class="text-xs text-red-500 py-2">{{ startfidError }}</div>
                    <div v-else-if="startfidItems.length === 0" class="text-xs text-[hsl(var(--muted-foreground))] py-2 text-center">
                      无文件可选
                    </div>
                    <div v-else class="max-h-40 overflow-y-auto space-y-0.5">
                      <div
                        v-for="item in startfidItems"
                        :key="item.fid"
                        class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-[hsl(var(--accent))] text-xs"
                        @click="selectStartfid(item)"
                      >
                        <span class="text-[hsl(var(--muted-foreground))]">📄</span>
                        <span class="truncate flex-1 text-[hsl(var(--foreground))]">{{ item.name }}</span>
                        <span v-if="item.size" class="text-[hsl(var(--muted-foreground))] shrink-0 text-[10px]">
                          {{ formatSize(item.size) }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 更新子目录 -->
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">更新子目录 (update_subdir)</label>
                  <Input v-model="state.update_subdir" placeholder="如 Season 1" />
                </div>

                <!-- 子目录重存模式 -->
                <div>
                  <label class="mb-1.5 block text-xs font-medium text-[hsl(var(--muted-foreground))]">子目录重存模式</label>
                  <select
                    v-model="state.update_subdir_resave_mode"
                    class="flex h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-sm text-[hsl(var(--foreground))] shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--ring))]"
                  >
                    <option value="none">不重存</option>
                    <option value="resave">重存新文件</option>
                    <option value="resave_all">全量重存</option>
                  </select>
                </div>
              </div>
            </section>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between border-t border-[hsl(var(--border))] px-6 py-4">
            <Button variant="outline" size="sm" @click="handleRunOnce" :disabled="submitting">
              <Play class="h-4 w-4 mr-1" />
              运行一次
            </Button>
            <div class="flex items-center gap-3">
              <Button variant="outline" size="sm" @click="resetAndClose">取消</Button>
              <Button size="sm" :disabled="submitting" @click="handleSubmit">
                <Loader2 v-if="submitting" class="mr-1.5 h-4 w-4 animate-spin" />
                {{ isEditing ? '保存修改' : '创建任务' }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet-right-enter-active,
.sheet-right-leave-active {
  transition: opacity 0.2s ease;
}
.sheet-right-enter-active > div:last-child,
.sheet-right-leave-active > div:last-child {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.sheet-right-enter-from,
.sheet-right-leave-to {
  opacity: 0;
}
.sheet-right-enter-from > div:last-child,
.sheet-right-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
