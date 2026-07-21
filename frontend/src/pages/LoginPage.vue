<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LogIn, CloudCog, Eye, EyeOff } from 'lucide-vue-next'

import { useAuthStore } from '@/stores/auth'
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  error.value = ''
  if (!username.value.trim()) {
    error.value = '请输入用户名'
    return
  }
  if (!password.value) {
    error.value = '请输入密码'
    return
  }

  loading.value = true
  try {
    await authStore.login(username.value.trim(), password.value)
    router.replace('/')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '登录失败，请检查用户名或密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div
    class="flex min-h-screen items-center justify-center p-4"
    style="background: linear-gradient(135deg, hsl(var(--primary) / 0.08) 0%, hsl(var(--background)) 50%, hsl(var(--primary) / 0.05) 100%)"
  >
    <div class="w-full max-w-sm">
      <!-- Logo & Title -->
      <div class="mb-8 text-center">
        <div
          class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl"
          style="background: hsl(var(--primary) / 0.1)"
        >
          <CloudCog class="h-8 w-8" style="color: hsl(var(--primary))" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight" style="color: hsl(var(--foreground))">
          Cloud Auto Save X
        </h1>
        <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">
          网盘自动转存管理系统
        </p>
      </div>

      <!-- Login Card -->
      <Card class="glass-card border-0 p-0 shadow-xl">
        <CardHeader class="pb-4">
          <h2 class="text-center text-lg font-semibold" style="color: hsl(var(--foreground))">
            👋 欢迎回来
          </h2>
        </CardHeader>

        <CardContent>
          <form class="space-y-4" @submit.prevent="handleLogin">
            <!-- Error -->
            <div
              v-if="error"
              class="rounded-md px-3 py-2 text-sm"
              style="background: hsl(var(--destructive) / 0.1); color: hsl(var(--destructive))"
            >
              {{ error }}
            </div>

            <!-- Username -->
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">
                用户名
              </label>
              <Input
                v-model="username"
                placeholder="请输入用户名"
                autocomplete="username"
                :disabled="loading"
              />
            </div>

            <!-- Password -->
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">
                密码
              </label>
              <div class="relative">
                <Input
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  class="pr-10"
                  :disabled="loading"
                  @keyup.enter="handleLogin"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 transition-colors"
                  style="color: hsl(var(--muted-foreground))"
                  tabindex="-1"
                  @click="showPassword = !showPassword"
                >
                  <Eye v-if="!showPassword" class="h-4 w-4" />
                  <EyeOff v-else class="h-4 w-4" />
                </button>
              </div>
            </div>

            <!-- Submit -->
            <Button
              type="submit"
              class="w-full"
              :disabled="loading"
            >
              <LogIn v-if="!loading" class="mr-2 h-4 w-4" />
              <svg
                v-else
                class="mr-2 h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  class="opacity-25"
                  cx="12" cy="12" r="10"
                  stroke="currentColor"
                  stroke-width="4"
                />
                <path
                  class="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              {{ loading ? '登录中...' : '登录' }}
            </Button>
          </form>
        </CardContent>

        <CardFooter class="justify-center pt-0">
          <p class="text-xs" style="color: hsl(var(--muted-foreground))">
            Cloud Auto Save X &copy; {{ new Date().getFullYear() }}
          </p>
        </CardFooter>
      </Card>
    </div>
  </div>
</template>
