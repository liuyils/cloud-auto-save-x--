<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Home,
  Search,
  Film,
  RefreshCw,
  HardDrive,
  Globe,
  Settings,
  Users,
} from 'lucide-vue-next'
import { TASK_READ, SYNC_READ, USER_READ, DRIVE_ACCOUNT_READ } from '@/constants/permissions'

const route = useRoute()
const router = useRouter()

// Reactive user permissions (mirrors Sidebar behaviour)
const userPermissions = ref<string[]>([])

async function loadAuthInfo() {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const authStore = useAuthStore()
    if (authStore.user) userPermissions.value = authStore.permissions
  } catch {
    // auth store not available
  }
}

onMounted(() => {
  loadAuthInfo()
})

const navItems = computed(() => {
  const items = [
    { path: '/', label: '首页', icon: Home, permission: null as string | null, tour: 'nav-home' },
    { path: '/discover', label: '发现', icon: Search, permission: TASK_READ, tour: 'nav-discover' },
    { path: '/tasks', label: '任务', icon: Film, permission: TASK_READ, tour: 'nav-tasks' },
    { path: '/sync', label: '同步', icon: RefreshCw, permission: SYNC_READ, tour: 'nav-sync' },
    { path: '/drives', label: '网盘', icon: HardDrive, permission: DRIVE_ACCOUNT_READ, tour: 'nav-drives' },
    { path: '/dl302', label: '302', icon: Globe, permission: null, tour: 'nav-dl302' },
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
}
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-40 flex items-center overflow-x-auto overscroll-x-contain border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] px-1 pb-[env(safe-area-inset-bottom)] md:hidden"
    style="height: 56px"
  >
    <button
      v-for="item in navItems"
      :key="item.path"
      :data-tour="item.tour"
      class="flex min-w-[3.5rem] shrink-0 flex-1 flex-col items-center justify-center gap-0.5 py-1 transition"
      :class="
        isActive(item.path)
          ? 'text-[hsl(var(--primary))]'
          : 'text-[hsl(var(--muted-foreground))]'
      "
      @click="navigate(item.path)"
    >
      <component :is="item.icon" :size="20" />
      <span class="text-[10px] font-medium">{{ item.label }}</span>
    </button>
  </nav>
</template>
