<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick, type Component } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Rocket, Home, Search, Film, RefreshCw, HardDrive, Globe, Settings,
  Clapperboard, PartyPopper, ChevronLeft, ChevronRight, X, ArrowRight, Check,
} from 'lucide-vue-next'

import { useOnboarding } from '@/composables/useOnboarding'

const router = useRouter()
const route = useRoute()
const { isOpen, stepIndex, maybeAutoStart, next, prev, skip } = useOnboarding()

type TourStep = {
  key: string
  icon: Component
  emoji: string
  title: string
  desc: string
  bullets?: string[]
  /** data-tour anchor of the real menu item to spotlight (see Sidebar/MobileNav). */
  target?: string
  /** route to open when clicking "前往该页面". */
  to?: string
  /** route to open automatically when the step becomes active (deep-link). */
  autoNavigate?: string
  tip?: string
}

// Content mirrors the real navigation (Sidebar.vue / MobileNav.vue) and the
// settings sections (SettingsPage.vue), so the spotlight always lines up with
// what users actually see in the menu.
const steps: TourStep[] = [
  {
    key: 'welcome',
    icon: Rocket,
    emoji: '🚀',
    title: '欢迎使用 Cloud Auto Save X',
    desc: '这是一套「网盘自动追剧 + 转存 + 同步 + 302 直链」一体化系统。接下来会依次高亮左侧菜单，带你认识每个页面的作用与开始前的关键配置。',
    bullets: [
      '自动监控分享链接更新并转存新剧集',
      '自动重命名、生成 STRM，供播放器直连',
      '多网盘账号统一管理，支持负载均衡',
    ],
  },
  {
    key: 'home',
    icon: Home,
    emoji: '🏠',
    title: '追剧首页',
    desc: '追剧总览大盘：集中查看所有追剧任务的更新进度、最近入库剧集与运行状态，一眼掌握全局。',
    target: 'nav-home',
    to: '/',
  },
  {
    key: 'discover',
    icon: Search,
    emoji: '🔍',
    title: '影视发现',
    desc: '浏览 TMDB / 豆瓣的热门影视，找到想追的剧后可一键创建追剧任务并自动关联刮削信息。',
    target: 'nav-discover',
    to: '/discover',
    tip: '此页依赖 TMDB Key（见最后一步）。',
  },
  {
    key: 'tasks',
    icon: Film,
    emoji: '🎬',
    title: '追剧任务',
    desc: '系统的核心：为每部剧配置分享链接与保存目录，系统定时检查更新、转存新集、按规则重命名并生成 STRM。',
    target: 'nav-tasks',
    to: '/tasks',
  },
  {
    key: 'sync',
    icon: RefreshCw,
    emoji: '🔄',
    title: '同步',
    desc: '在网盘目录之间做同步 / 复制流水线（支持 dl302 秒传），可与追剧任务联动分发入库内容。',
    target: 'nav-sync',
    to: '/sync',
  },
  {
    key: 'drives',
    icon: HardDrive,
    emoji: '💾',
    title: '网盘账号',
    desc: '添加并管理网盘账号（夸克 / UC / 115 / 天翼 / 阿里 / 移动云盘等）。这是所有功能的前提，请先配置好账号。',
    target: 'nav-drives',
    to: '/drives',
    tip: '不同网盘登录方式不同：Cookie、扫码、账号密码等。',
  },
  {
    key: 'dl302',
    icon: Globe,
    emoji: '🌐',
    title: '302 代理',
    desc: '为播放 / 下载提供 302 直链代理与负载均衡，配合 STRM 可让播放器直连网盘资源。',
    target: 'nav-dl302',
    to: '/dl302',
  },
  {
    key: 'settings',
    icon: Settings,
    emoji: '⚙️',
    title: '设置中心',
    desc: '集中配置系统各项能力：插件、通知、TMDB、重命名规则、转存、资源搜索、OpenList、缓存、审计日志。',
    target: 'nav-settings',
    to: '/settings',
  },
  {
    key: 'tmdb',
    icon: Clapperboard,
    emoji: '🔑',
    title: '第一步：配置 TMDB Key',
    desc: '已为你打开「设置 → TMDB 设置」。影视发现与追剧刮削都依赖 TMDB，请在高亮的输入框填入你的 API Key 并保存。',
    target: 'tmdb-api-key',
    autoNavigate: '/settings?section=tmdb',
    to: '/settings?section=tmdb',
    tip: '没有 Key？可在 themoviedb.org 免费注册申请。',
  },
  {
    key: 'done',
    icon: PartyPopper,
    emoji: '🎉',
    title: '开始使用',
    desc: '记住这份「快速开始清单」，跑通第一部剧只需三步：',
    bullets: [
      '① 设置 → TMDB 设置：填入 API Key',
      '② 网盘账号：添加并启用一个账号',
      '③ 影视发现 / 追剧任务：创建你的第一个追剧任务',
    ],
  },
]

const total = steps.length
const current = computed(() => steps[stepIndex.value] ?? steps[0])
const isFirst = computed(() => stepIndex.value === 0)
const isLast = computed(() => stepIndex.value === total - 1)

// --- Spotlight geometry ---
const PAD = 6
const GAP = 14
const tooltipEl = ref<HTMLElement | null>(null)
const currentRect = ref<DOMRect | null>(null)
// Four dark panels around the highlighted target (default: single full overlay).
const panelStyles = ref<Record<string, string>[]>([{ top: '0px', left: '0px', width: '100%', height: '100%' }])
const ringStyle = ref<Record<string, string> | null>(null)
const tooltipStyle = ref<Record<string, string>>({ top: '50%', left: '50%' })

function clamp(v: number, min: number, max: number) {
  return Math.min(Math.max(v, min), max)
}

function getTargetEl(): HTMLElement | null {
  const key = steps[stepIndex.value]?.target
  if (!key) return null
  const nodes = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${key}"]`))
  // Multiple anchors may exist (desktop sidebar + mobile bottom nav) — pick the visible one.
  return nodes.find((el) => {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  }) || null
}

function setCentered() {
  currentRect.value = null
  panelStyles.value = [{ top: '0px', left: '0px', width: '100%', height: '100%' }]
  ringStyle.value = null
  nextTick(() => positionTooltip(null))
}

function buildSpotlight(r: DOMRect) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const t = Math.max(0, r.top - PAD)
  const b = Math.min(vh, r.bottom + PAD)
  const l = Math.max(0, r.left - PAD)
  const rr = Math.min(vw, r.right + PAD)
  panelStyles.value = [
    { top: '0px', left: '0px', width: '100%', height: `${t}px` }, // top
    { top: `${b}px`, left: '0px', width: '100%', height: `${Math.max(0, vh - b)}px` }, // bottom
    { top: `${t}px`, left: '0px', width: `${l}px`, height: `${Math.max(0, b - t)}px` }, // left
    { top: `${t}px`, left: `${rr}px`, width: `${Math.max(0, vw - rr)}px`, height: `${Math.max(0, b - t)}px` }, // right
  ]
  ringStyle.value = {
    top: `${t}px`,
    left: `${l}px`,
    width: `${Math.max(0, rr - l)}px`,
    height: `${Math.max(0, b - t)}px`,
  }
  currentRect.value = r
}

function positionTooltip(r: DOMRect | null) {
  const el = tooltipEl.value
  if (!el) return
  const tw = el.offsetWidth
  const th = el.offsetHeight
  const vw = window.innerWidth
  const vh = window.innerHeight

  if (!r) {
    tooltipStyle.value = { top: `${Math.max(12, (vh - th) / 2)}px`, left: `${Math.max(12, (vw - tw) / 2)}px` }
    return
  }

  let top: number
  let left: number
  const spaceRight = vw - r.right
  const spaceLeft = r.left
  const spaceBottom = vh - r.bottom

  if (spaceRight >= tw + GAP + 8) {
    // Place to the right — natural for the left-hand sidebar.
    left = r.right + GAP
    top = clamp(r.top, 12, vh - th - 12)
  } else if (spaceLeft >= tw + GAP + 8) {
    left = r.left - GAP - tw
    top = clamp(r.top, 12, vh - th - 12)
  } else if (spaceBottom >= th + GAP + 8) {
    top = r.bottom + GAP
    left = clamp(r.left + r.width / 2 - tw / 2, 12, vw - tw - 12)
  } else {
    // Place above — natural for the mobile bottom nav.
    top = r.top - GAP - th
    left = clamp(r.left + r.width / 2 - tw / 2, 12, vw - tw - 12)
  }

  tooltipStyle.value = { top: `${Math.max(12, top)}px`, left: `${Math.max(12, left)}px` }
}

function applyLayout(el: HTMLElement | null) {
  if (!el) {
    setCentered()
    return
  }
  el.scrollIntoView({ block: 'nearest', inline: 'center' })
  requestAnimationFrame(() => {
    const r = el.getBoundingClientRect()
    buildSpotlight(r)
    nextTick(() => positionTooltip(r))
  })
}

let retryTimer: ReturnType<typeof setTimeout> | null = null

function updateLayout(attempt = 0) {
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (!isOpen.value) return
  const step = steps[stepIndex.value]
  const el = getTargetEl()
  // The target may live on a freshly-navigated page (e.g. the TMDB API Key
  // input) that hasn't mounted yet — retry briefly before falling back to a
  // centered card so the tour never gets stuck.
  if (step?.target && !el && attempt < 25) {
    retryTimer = setTimeout(() => updateLayout(attempt + 1), 100)
    return
  }
  applyLayout(el)
}

function handleNext() {
  next(total)
}

function handleGoToPage() {
  const to = current.value.to
  if (to) router.push(to)
  // Keep the tour open so the highlight/steps continue after navigation.
  nextTick(updateLayout)
}

function onKeydown(e: KeyboardEvent) {
  if (!isOpen.value) return
  if (e.key === 'Escape') skip()
  else if (e.key === 'ArrowRight') handleNext()
  else if (e.key === 'ArrowLeft') prev()
}

function onViewportChange() {
  if (isOpen.value) updateLayout(0)
}

async function tryAutoStart() {
  let userId: number | null = null
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const authStore = useAuthStore()
    userId = authStore.user?.id ?? null
  } catch {
    // auth store not ready — fall back to anon key
  }
  maybeAutoStart(userId)
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
  tryAutoStart()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  if (retryTimer) clearTimeout(retryTimer)
  if (typeof document !== 'undefined') document.body.style.overflow = ''
})

// Recompute spotlight whenever the tour opens or the step changes; steps may
// also deep-link to a page/section before highlighting their target.
watch([isOpen, stepIndex], ([open]) => {
  if (typeof document !== 'undefined') document.body.style.overflow = open ? 'hidden' : ''
  if (!open) return
  const step = steps[stepIndex.value]
  if (step?.autoNavigate && route.fullPath !== step.autoNavigate) {
    router.push(step.autoNavigate)
  }
  nextTick(() => requestAnimationFrame(() => updateLayout(0)))
})
</script>

<template>
  <Teleport to="body">
    <Transition name="onboarding-fade">
      <div v-if="isOpen" class="pointer-events-none fixed inset-0 z-[100]" role="dialog" aria-modal="true">
        <!-- Dark panels around the highlighted target (click to skip) -->
        <div
          v-for="(p, i) in panelStyles"
          :key="i"
          class="pointer-events-auto fixed bg-black/60"
          :style="{ ...p, transition: 'all .2s ease' }"
          @click="skip"
        />

        <!-- Highlight ring on the real menu item -->
        <div
          v-if="ringStyle"
          class="pointer-events-none fixed rounded-lg"
          :style="{
            ...ringStyle,
            transition: 'all .2s ease',
            border: '2px solid hsl(var(--primary))',
            boxShadow: '0 0 0 4px hsl(var(--primary) / 0.25)',
          }"
        />

        <!-- Tooltip card -->
        <div
          ref="tooltipEl"
          class="pointer-events-auto fixed z-[102] w-[min(340px,calc(100vw-24px))] overflow-hidden rounded-xl shadow-2xl"
          style="background: hsl(var(--card)); border: 1px solid hsl(var(--border)); transition: top .2s ease, left .2s ease"
          :style="tooltipStyle"
        >
          <!-- Close -->
          <button
            class="absolute right-2.5 top-2.5 z-10 rounded-md p-1 transition-colors hover:bg-[hsl(var(--muted))]"
            style="color: hsl(var(--muted-foreground))"
            aria-label="关闭引导"
            @click="skip"
          >
            <X class="h-4 w-4" />
          </button>

          <!-- Body -->
          <div class="px-5 pt-5 pb-4">
            <div class="mb-2 flex items-center gap-2.5">
              <div
                class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
                style="background: hsl(var(--primary) / 0.12)"
              >
                <component :is="current.icon" class="h-5 w-5" style="color: hsl(var(--primary))" />
              </div>
              <h2 class="text-base font-bold tracking-tight" style="color: hsl(var(--foreground))">
                {{ current.emoji }} {{ current.title }}
              </h2>
            </div>

            <p class="text-sm leading-relaxed" style="color: hsl(var(--muted-foreground))">
              {{ current.desc }}
            </p>

            <ul v-if="current.bullets?.length" class="mt-3 space-y-1.5">
              <li
                v-for="(b, i) in current.bullets"
                :key="i"
                class="flex items-start gap-2 text-sm"
                style="color: hsl(var(--foreground))"
              >
                <Check class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: hsl(var(--primary))" />
                <span>{{ b }}</span>
              </li>
            </ul>

            <div
              v-if="current.tip"
              class="mt-3 rounded-md px-3 py-2 text-xs"
              style="background: hsl(var(--muted)); color: hsl(var(--muted-foreground))"
            >
              💡 {{ current.tip }}
            </div>

            <button
              v-if="current.to"
              class="mt-3 inline-flex items-center gap-1 text-sm font-medium transition-opacity hover:opacity-80"
              style="color: hsl(var(--primary))"
              @click="handleGoToPage"
            >
              前往该页面
              <ArrowRight class="h-4 w-4" />
            </button>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between gap-3 border-t px-5 py-3" style="border-color: hsl(var(--border))">
            <span class="text-xs tabular-nums" style="color: hsl(var(--muted-foreground))">
              {{ stepIndex + 1 }} / {{ total }}
            </span>

            <div class="flex items-center gap-2">
              <button
                v-if="!isFirst"
                class="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors hover:bg-[hsl(var(--muted))]"
                style="color: hsl(var(--muted-foreground))"
                @click="prev"
              >
                <ChevronLeft class="h-4 w-4" />
                上一步
              </button>
              <button
                v-else
                class="rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors hover:bg-[hsl(var(--muted))]"
                style="color: hsl(var(--muted-foreground))"
                @click="skip"
              >
                跳过
              </button>

              <button
                class="inline-flex items-center gap-1 rounded-md px-3.5 py-1.5 text-sm font-semibold shadow-sm transition-opacity hover:opacity-90"
                style="background: hsl(var(--primary)); color: hsl(var(--primary-foreground))"
                @click="handleNext"
              >
                {{ isLast ? '完成' : '下一步' }}
                <ChevronRight v-if="!isLast" class="h-4 w-4" />
                <Check v-else class="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.onboarding-fade-enter-active,
.onboarding-fade-leave-active {
  transition: opacity 0.2s ease;
}
.onboarding-fade-enter-from,
.onboarding-fade-leave-to {
  opacity: 0;
}
</style>
