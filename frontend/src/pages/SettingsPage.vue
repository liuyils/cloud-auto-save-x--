<script setup lang="ts">
import { ref, watch, markRaw, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { Puzzle, Bell, Database, ScrollText, Clapperboard, Wand2, ArrowLeftRight, Search, FolderTree } from 'lucide-vue-next'
import PluginsSection from '@/components/business/settings/PluginsSection.vue'
import NotificationsSection from '@/components/business/settings/NotificationsSection.vue'
import CacheSection from '@/components/business/settings/CacheSection.vue'
import AuditLogSection from '@/components/business/settings/AuditLogSection.vue'
import TmdbSection from '@/components/business/settings/system/TmdbSection.vue'
import MagicRegexSection from '@/components/business/settings/system/MagicRegexSection.vue'
import TransferSection from '@/components/business/settings/system/TransferSection.vue'
import ResourceSearchSection from '@/components/business/settings/system/ResourceSearchSection.vue'
import OpenListSection from '@/components/business/settings/system/OpenListSection.vue'

type SettingsCategory = {
  key: string
  label: string
  emoji: string
  icon: Component
  component: Component
}

const categories: SettingsCategory[] = [
  { key: 'plugins', label: '插件管理', emoji: '🧩', icon: markRaw(Puzzle), component: markRaw(PluginsSection) },
  { key: 'notifications', label: '通知配置', emoji: '🔔', icon: markRaw(Bell), component: markRaw(NotificationsSection) },
  { key: 'tmdb', label: 'TMDB 设置', emoji: '🎬', icon: markRaw(Clapperboard), component: markRaw(TmdbSection) },
  { key: 'magic_regex', label: '重命名规则', emoji: '✨', icon: markRaw(Wand2), component: markRaw(MagicRegexSection) },
  { key: 'transfer', label: '转存设置', emoji: '🔀', icon: markRaw(ArrowLeftRight), component: markRaw(TransferSection) },
  { key: 'resource_search', label: '资源搜索', emoji: '🔎', icon: markRaw(Search), component: markRaw(ResourceSearchSection) },
  { key: 'openlist', label: 'OpenList', emoji: '🗂️', icon: markRaw(FolderTree), component: markRaw(OpenListSection) },
  { key: 'cache', label: '缓存管理', emoji: '💾', icon: markRaw(Database), component: markRaw(CacheSection) },
  { key: 'audit', label: '审计日志', emoji: '📜', icon: markRaw(ScrollText), component: markRaw(AuditLogSection) },
]

const route = useRoute()
const validKeys = categories.map((c) => c.key)

function resolveKey(value: unknown): string {
  const key = String(value || '')
  return validKeys.includes(key) ? key : 'plugins'
}

// Support deep-linking to a section via `?section=tmdb` (used by the onboarding
// tour to open the TMDB settings and spotlight the API Key input).
const activeKey = ref(resolveKey(route.query.section))

watch(
  () => route.query.section,
  (value) => {
    const key = String(value || '')
    if (validKeys.includes(key)) activeKey.value = key
  },
)

const activeCategory = () => categories.find((c) => c.key === activeKey.value)!
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="border-b border-[hsl(var(--border))] px-6 pt-5 pb-4">
      <h1 class="text-2xl font-bold text-[hsl(var(--foreground))]">⚙️ 设置</h1>
    </div>

    <!-- Mobile: horizontal scroll tabs -->
    <div class="flex overflow-x-auto overscroll-x-contain border-b border-[hsl(var(--border))] px-4 md:hidden">
      <button
        v-for="cat in categories"
        :key="cat.key"
        class="relative flex shrink-0 items-center gap-1.5 px-3 py-3 text-sm font-medium whitespace-nowrap transition-colors"
        :class="activeKey === cat.key
          ? 'text-[hsl(var(--primary))]'
          : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
        @click="activeKey = cat.key"
      >
        <component :is="cat.icon" class="h-4 w-4" />
        {{ cat.label }}
        <span
          v-if="activeKey === cat.key"
          class="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-[hsl(var(--primary))]"
        />
      </button>
    </div>

    <!-- Content area -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Desktop: left sidebar nav -->
      <aside class="hidden w-[200px] shrink-0 border-r border-[hsl(var(--border))] md:block">
        <nav class="flex flex-col gap-0.5 p-3">
          <button
            v-for="cat in categories"
            :key="cat.key"
            class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="activeKey === cat.key
              ? 'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]'
              : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]'"
            @click="activeKey = cat.key"
          >
            <component :is="cat.icon" class="h-4 w-4" />
            {{ cat.label }}
          </button>
        </nav>
      </aside>

      <!-- Right content -->
      <main class="flex-1 overflow-y-auto p-6">
        <component :is="activeCategory().component" />
      </main>
    </div>
  </div>
</template>
