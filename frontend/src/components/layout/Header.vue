<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Menu } from 'lucide-vue-next'

defineProps<{
  onMenuClick: () => void
}>()

const route = useRoute()

const pageTitle = computed(() => {
  return (route.meta?.title as string) || 'CAS-X'
})
</script>

<template>
  <header
    class="flex h-14 items-center gap-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 md:px-6"
  >
    <!-- Mobile: hamburger button -->
    <button
      class="rounded p-1.5 text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] md:hidden"
      @click="onMenuClick"
    >
      <Menu :size="22" />
    </button>

    <!-- Mobile: app name -->
    <span class="text-sm font-semibold text-[hsl(var(--foreground))] md:hidden">
      CAS-X
    </span>

    <!-- Desktop: page title -->
    <h1 class="hidden text-lg font-semibold text-[hsl(var(--foreground))] md:block">
      {{ pageTitle }}
    </h1>
  </header>
</template>
