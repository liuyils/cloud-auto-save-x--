<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  title?: string
  description?: string
  icon?: Component
}>()
</script>

<template>
  <section class="glass-card transition-shadow hover:shadow-md sm:p-6">
    <header v-if="title || $slots.header || $slots.actions" class="mb-5 flex items-start gap-3">
      <div
        v-if="icon"
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
      >
        <component :is="icon" class="h-5 w-5" />
      </div>
      <div class="min-w-0 flex-1">
        <h3 v-if="title" class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ title }}</h3>
        <p v-if="description" class="mt-0.5 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">{{ description }}</p>
        <slot name="header" />
      </div>
      <div v-if="$slots.actions" class="shrink-0">
        <slot name="actions" />
      </div>
    </header>
    <div class="space-y-4">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="mt-5 flex flex-wrap items-center gap-3 border-t border-[hsl(var(--border))] pt-4">
      <slot name="footer" />
    </footer>
  </section>
</template>
