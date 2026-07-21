<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center gap-4 p-4"
    style="background: linear-gradient(135deg, hsl(var(--destructive) / 0.08) 0%, hsl(var(--background)) 50%, hsl(var(--primary) / 0.05) 100%)"
  >
    <div class="glass-card flex flex-col items-center gap-3 px-10 py-10 text-center">
      <div class="text-6xl">🚫</div>
      <h1 class="text-5xl font-bold text-[hsl(var(--destructive))]">403</h1>
      <p class="text-lg text-[hsl(var(--muted-foreground))]">抱歉，您没有权限访问此页面</p>
      <button
        class="mt-2 rounded-full bg-[hsl(var(--primary))] px-5 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
        @click="router.push('/')"
      >
        🏠 返回首页
      </button>
    </div>
  </div>
</template>
