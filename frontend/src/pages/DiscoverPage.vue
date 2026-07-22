<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MediaDiscover from '@/components/business/drama/MediaDiscover.vue'
import DramaTaskLauncher from '@/components/business/drama/DramaTaskLauncher.vue'
import { useDramaTaskLauncher } from '@/composables/useDramaTaskLauncher'
import type { DramaTaskPreset } from '@/types/dramaLauncher'

const route = useRoute()
const initialQuery = computed(() => String(route.query.q || ''))
const launcher = useDramaTaskLauncher()

function openCreateWithTMDB(payload: DramaTaskPreset) {
  launcher.openFromPreset(payload)
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
        <MediaDiscover :initial-query="initialQuery" :tracked-keys="launcher.trackedKeys.value" @add-task="openCreateWithTMDB" />
      </div>
    </div>

    <DramaTaskLauncher :launcher="launcher" />
  </div>
</template>
