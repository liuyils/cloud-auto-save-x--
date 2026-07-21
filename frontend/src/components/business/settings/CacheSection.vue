<script setup lang="ts">
import { ref, markRaw, type Component } from 'vue'
import { Database, Film, Link } from 'lucide-vue-next'
import ProxyImageCachePanel from '@/components/business/settings/cache/ProxyImageCachePanel.vue'
import ShareLinkCachePanel from '@/components/business/settings/cache/ShareLinkCachePanel.vue'
import TmdbCachePanel from '@/components/business/settings/cache/TmdbCachePanel.vue'

type CacheTab = {
  key: string
  label: string
  icon: Component
  component: Component
}

const tabs: CacheTab[] = [
  { key: 'proxy', label: '代理图片缓存', icon: markRaw(Database), component: markRaw(ProxyImageCachePanel) },
  { key: 'share', label: '分享链接缓存', icon: markRaw(Link), component: markRaw(ShareLinkCachePanel) },
  { key: 'tmdb', label: 'TMDB 缓存', icon: markRaw(Film), component: markRaw(TmdbCachePanel) },
]

const activeKey = ref('proxy')
const activeTab = () => tabs.find((t) => t.key === activeKey.value)!
</script>

<template>
  <div>
    <div class="mb-5">
      <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">💾 缓存管理</h2>
      <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">查看与管理各类缓存：代理图片、分享链接、TMDB 详情。</p>
    </div>

    <!-- Tabs -->
    <div class="mb-6 flex overflow-x-auto overscroll-x-contain">
      <div class="inline-flex gap-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-1">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="flex shrink-0 items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-all"
          :class="activeKey === tab.key
            ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="activeKey = tab.key"
        >
          <component :is="tab.icon" class="h-4 w-4" />
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- Active panel -->
    <component :is="activeTab().component" />
  </div>
</template>
