<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Home,
  Search,
  Film,
  RefreshCw,
  HardDrive,
  Globe,
  Settings,
  Users,
  LogOut,
  ChevronLeft,
  Sun,
  Moon,
  ArrowUpCircle,
  HelpCircle,
} from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import { useOnboarding } from '@/composables/useOnboarding'
import { getHealth } from '@/api/health'
import { TASK_READ, SYNC_READ, USER_READ, DRIVE_ACCOUNT_READ } from '@/constants/permissions'

const props = defineProps<{
  collapsed: boolean
  onToggle: () => void
  hideHeader?: boolean
  onNavigate?: () => void
}>()

const router = useRouter()
const route = useRoute()
const { theme, toggleTheme } = useTheme()
const { start: startOnboarding } = useOnboarding()

function openGuide() {
  startOnboarding()
  // Close the mobile drawer (if any) so the tour is not hidden behind it.
  props.onNavigate?.()
}

// Reactive state for user info (updated when store is available)
const userPermissions = ref<string[]>([])
const userName = ref('用户')

async function loadAuthInfo() {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const authStore = useAuthStore()
    if (authStore.user) {
      userName.value = authStore.user.username || '用户'
      userPermissions.value = authStore.permissions
    }
  } catch {
    // auth store not available
  }
}

// --- Version & update check ---
const buildTag = ref<string | null>(null)
const buildSha = ref<string | null>(null)
const latestTag = ref<string | null>(null)
const UPDATE_URL = 'https://github.com/ozoo0/cloud-auto-save-x/releases'

const showUpdateBadge = computed(() => {
  const current = (buildTag.value || '').trim() || 'dev'
  const latest = (latestTag.value || '').trim()
  return Boolean(latest && latest !== current)
})

const versionText = computed(() => {
  const tag = (buildTag.value || '').trim() || 'dev'
  const sha = (buildSha.value || '').trim()
  if (sha) return `${tag} (${sha.slice(0, 7)})`
  return tag
})

async function checkNewVersion() {
  try {
    const res = await fetch('https://api.github.com/repos/ozoo0/cloud-auto-save-x/tags', {
      method: 'GET',
      headers: { Accept: 'application/vnd.github+json' },
    })
    if (!res.ok) return
    const data = (await res.json()) as Array<{ name?: string }>
    const tag = String(data?.[0]?.name || '').trim()
    latestTag.value = tag || null
  } catch {
    latestTag.value = null
  }
}

function openUpdatePage() {
  if (!showUpdateBadge.value) return
  window.open(UPDATE_URL, '_blank')
}

onMounted(async () => {
  loadAuthInfo()
  try {
    const health = await getHealth()
    buildTag.value = health.build_tag || 'dev'
    buildSha.value = health.build_sha || null
  } catch {
    buildTag.value = 'dev'
    buildSha.value = null
  }
  await checkNewVersion()
})

const navItems = computed(() => {
  const items = [
    { path: '/', label: '追剧首页', icon: Home, permission: null, tour: 'nav-home' },
    { path: '/discover', label: '影视发现', icon: Search, permission: TASK_READ, tour: 'nav-discover' },
    { path: '/tasks', label: '追剧任务', icon: Film, permission: TASK_READ, tour: 'nav-tasks' },
    { path: '/sync', label: '同步', icon: RefreshCw, permission: SYNC_READ, tour: 'nav-sync' },
    { path: '/drives', label: '网盘账号', icon: HardDrive, permission: DRIVE_ACCOUNT_READ, tour: 'nav-drives' },
    { path: '/dl302', label: '302 代理', icon: Globe, permission: null, tour: 'nav-dl302' },
    { path: '/settings', label: '设置', icon: Settings, permission: null, tour: 'nav-settings' },
    { path: '/users', label: '用户', icon: Users, permission: USER_READ, tour: 'nav-users' },
  ]

  return items.filter((item) => {
    if (!item.permission) return true
    if (userPermissions.value.length === 0) return true
    return userPermissions.value.includes(item.permission)
  })
})

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function navigate(path: string) {
  router.push(path)
  props.onNavigate?.()
}

async function handleLogout() {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const authStore = useAuthStore()
    await authStore.logout()
  } catch {
    // ignore
  }
  router.push('/login')
}
</script>

<template>
  <aside
    class="flex h-full flex-col bg-[hsl(var(--card))] transition-all duration-300"
    :class="[hideHeader ? 'w-full' : (collapsed ? 'w-16' : 'w-60'), hideHeader ? '' : 'border-r border-[hsl(var(--border))]']"
  >
    <!-- Logo / App name -->
    <div v-if="!hideHeader" class="flex h-14 items-center justify-between px-4">
      <div class="flex items-center gap-2 overflow-hidden">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))] text-sm font-bold text-[hsl(var(--primary-foreground))]">
          C
        </div>
        <span
          v-if="!collapsed"
          class="whitespace-nowrap text-sm font-semibold text-[hsl(var(--foreground))]"
        >
          CAS-X
        </span>
      </div>
      <button
        v-if="!collapsed"
        class="rounded p-1 text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
        @click="onToggle"
      >
        <ChevronLeft :size="18" />
      </button>
      <button
        v-else
        class="mx-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
        @click="onToggle"
      >
        <ChevronLeft :size="18" class="rotate-180" />
      </button>
    </div>

    <!-- Nav items -->
    <nav class="mt-2 flex flex-1 flex-col gap-1 px-2">
      <button
        v-for="item in navItems"
        :key="item.path"
        :data-tour="item.tour"
        class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition"
        :class="
          isActive(item.path)
            ? 'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]'
            : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]'
        "
        :title="collapsed ? item.label : undefined"
        @click="navigate(item.path)"
      >
        <component :is="item.icon" :size="20" class="flex-shrink-0" />
        <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
      </button>
    </nav>

    <!-- Bottom section -->
    <div class="border-t border-[hsl(var(--border))] p-2">
      <!-- Guide / product tour -->
      <button
        class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
        :title="collapsed ? '使用引导' : undefined"
        @click="openGuide"
      >
        <HelpCircle :size="20" class="flex-shrink-0" />
        <span v-if="!collapsed">使用引导</span>
      </button>

      <!-- Theme toggle -->
      <button
        class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
        :title="collapsed ? (theme === 'dark' ? '浅色模式' : '深色模式') : undefined"
        @click="toggleTheme"
      >
        <Moon v-if="theme === 'dark'" :size="20" class="flex-shrink-0" />
        <Sun v-else :size="20" class="flex-shrink-0" />
        <span v-if="!collapsed">{{ theme === 'dark' ? '深色模式' : '浅色模式' }}</span>
      </button>

      <!-- Version -->
      <button
        class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition"
        :class="showUpdateBadge
          ? 'text-orange-500 hover:bg-orange-500/10'
          : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]'"
        :title="showUpdateBadge ? `当前版本：${versionText}，发现新版本：${latestTag}，点击前往更新` : `当前版本：${versionText}`"
        @click="openUpdatePage"
      >
        <ArrowUpCircle v-if="showUpdateBadge" :size="20" class="flex-shrink-0" />
        <span v-else class="flex-shrink-0 text-base leading-none font-semibold text-[hsl(var(--muted-foreground))]">v</span>
        <span v-if="!collapsed" class="flex min-w-0 flex-col items-start leading-tight">
          <span class="truncate text-xs">{{ versionText }}</span>
          <span v-if="showUpdateBadge" class="truncate text-xs font-semibold text-orange-500">最新 {{ latestTag }}</span>
        </span>
      </button>

      <!-- User + Logout -->
      <div class="mt-1 flex items-center gap-2 px-3 py-2">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-xs font-medium text-[hsl(var(--secondary-foreground))]">
          {{ userName.charAt(0).toUpperCase() }}
        </div>
        <div v-if="!collapsed" class="flex flex-1 items-center justify-between overflow-hidden">
          <span class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ userName }}</span>
          <button
            class="rounded p-1 text-[hsl(var(--muted-foreground))] transition hover:text-[hsl(var(--destructive))]"
            @click="handleLogout"
          >
            <LogOut :size="16" />
          </button>
        </div>
        <button
          v-if="collapsed"
          class="mx-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition hover:text-[hsl(var(--destructive))]"
          title="退出登录"
          @click="handleLogout"
        >
          <LogOut :size="16" />
        </button>
      </div>
    </div>
  </aside>
</template>
