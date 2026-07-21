<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  CloudCog, UserPlus, HardDrive, PartyPopper,
  ChevronRight, Check, SkipForward, Eye, EyeOff,
} from 'lucide-vue-next'

import { initAdmin } from '@/api/setup'
import { createDriveAccount, fetchDriveTypes } from '@/api/extensions'
import type { ConfigFieldItem, DriveTypeItem } from '@/types/extensions'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'
import { Card, CardContent } from '@/components/ui/card'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'

const router = useRouter()
const authStore = useAuthStore()
const setupStore = useSetupStore()

const currentStep = ref(1)

// Step 1 state
const adminUsername = ref('')
const adminPassword = ref('')
const adminConfirmPassword = ref('')
const showPassword = ref(false)
const showConfirmPassword = ref(false)

// Step 2 state — drive types & their config fields come from the backend,
// so the wizard always matches the real "add account" form (Cookie / TV
// credentials / account-password / toggles, etc.), not a hardcoded subset.
const driveTypes = ref<DriveTypeItem[]>([])
const driveTypesLoading = ref(false)
const selectedDriveType = ref('')
const driveConfig = ref<Record<string, any>>({})
const driveAccountName = ref('')

const currentDriveType = computed(
  () => driveTypes.value.find((item) => item.code === selectedDriveType.value) || null,
)
const currentDriveFields = computed<ConfigFieldItem[]>(() => currentDriveType.value?.config_fields || [])

function cloneConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

// Keep in sync with DriveAccountsSection: a new account needs at least one
// meaningful login parameter filled in.
function hasAnyConfigValue(config: Record<string, any>) {
  return Object.values(config || {}).some((value) => {
    if (typeof value === 'boolean') return value
    if (typeof value === 'number') return !Number.isNaN(value)
    return String(value ?? '').trim() !== ''
  })
}

const step2Valid = computed(() => Boolean(selectedDriveType.value) && hasAnyConfigValue(driveConfig.value))

async function loadDriveTypes() {
  if (driveTypes.value.length || driveTypesLoading.value) return
  driveTypesLoading.value = true
  try {
    driveTypes.value = await fetchDriveTypes()
  } catch {
    // ignore — the user can still finish setup and add drives later in settings
  } finally {
    driveTypesLoading.value = false
  }
}

watch(selectedDriveType, (value) => {
  const target = driveTypes.value.find((item) => item.code === value)
  driveConfig.value = cloneConfig(target?.default_config || {})
})

// shared state
const loading = ref(false)
const error = ref('')
const step2Added = ref(false)

const step1Valid = computed(() => {
  return (
    adminUsername.value.trim().length > 0 &&
    isPasswordValid(adminPassword.value) &&
    adminPassword.value === adminConfirmPassword.value
  )
})

// Keep in sync with backend `ensure_password_policy`:
// at least 8 chars and contains a special (non-alphanumeric) character.
function isPasswordValid(pwd: string) {
  return pwd.length >= 8 && /[^a-zA-Z0-9]/.test(pwd)
}

const step1Error = computed(() => {
  if (!adminUsername.value.trim() && !adminPassword.value) return ''
  if (adminPassword.value && !isPasswordValid(adminPassword.value))
    return '密码至少 8 位，且需包含特殊字符'
  if (adminConfirmPassword.value && adminPassword.value !== adminConfirmPassword.value)
    return '两次输入的密码不一致'
  return ''
})

const stepItems = computed(() => [
  { step: 1, label: '创建管理员', icon: UserPlus },
  { step: 2, label: '添加网盘', icon: HardDrive },
  { step: 3, label: '完成', icon: PartyPopper },
])

async function handleStep1Next() {
  if (!step1Valid.value) return
  error.value = ''
  loading.value = true
  try {
    const data = await initAdmin({
      username: adminUsername.value.trim(),
      password: adminPassword.value,
    })
    await authStore.afterLogin(data)
    setupStore.markInitialized()
    await loadDriveTypes()
    currentStep.value = 2
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '创建管理员失败'
  } finally {
    loading.value = false
  }
}

async function handleAddDriveAccount() {
  if (!step2Valid.value) return
  error.value = ''
  loading.value = true
  try {
    await createDriveAccount({
      name: driveAccountName.value.trim() || currentDriveType.value?.drive_name || selectedDriveType.value,
      drive_type: selectedDriveType.value,
      config: cloneConfig(driveConfig.value),
      enabled: true,
      is_default: true,
    })
    step2Added.value = true
    currentStep.value = 3
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '添加网盘账号失败'
  } finally {
    loading.value = false
  }
}

function skipStep2() {
  currentStep.value = 3
}

function enterSystem() {
  router.replace('/')
}

// Defense in depth: if the system is already initialized, the wizard must not
// be usable. Redirect away immediately (the router guard also enforces this).
onMounted(async () => {
  try {
    await setupStore.refreshStatus(true)
    if (setupStore.initialized) {
      router.replace('/')
    }
  } catch {
    // ignore — guard will handle redirects
  }
})
</script>

<template>
  <div
    class="flex min-h-screen items-center justify-center p-4"
    style="background: linear-gradient(135deg, hsl(var(--primary) / 0.06) 0%, hsl(var(--background)) 50%, hsl(var(--primary) / 0.04) 100%)"
  >
    <div class="w-full max-w-lg">
      <!-- Logo -->
      <div class="mb-6 text-center">
        <div
          class="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl"
          style="background: hsl(var(--primary) / 0.1)"
        >
          <CloudCog class="h-7 w-7" style="color: hsl(var(--primary))" />
        </div>
        <h1 class="text-xl font-bold tracking-tight" style="color: hsl(var(--foreground))">
          Cloud Auto Save X
        </h1>
        <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">🚀 初始化向导</p>
      </div>

      <!-- Step Indicator -->
      <div class="mb-6 flex items-center justify-center gap-0">
        <template v-for="(item, idx) in stepItems" :key="item.step">
          <div class="flex items-center gap-2">
            <div
              class="flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-all"
              :style="{
                background: currentStep >= item.step ? 'hsl(var(--primary))' : 'hsl(var(--muted))',
                color: currentStep >= item.step ? 'hsl(var(--primary-foreground))' : 'hsl(var(--muted-foreground))',
              }"
            >
              <Check v-if="currentStep > item.step" class="h-4 w-4" />
              <span v-else>{{ item.step }}</span>
            </div>
            <span
              class="hidden text-sm font-medium sm:inline"
              :style="{ color: currentStep >= item.step ? 'hsl(var(--foreground))' : 'hsl(var(--muted-foreground))' }"
            >
              {{ item.label }}
            </span>
          </div>
          <div
            v-if="idx < stepItems.length - 1"
            class="mx-3 h-px w-8 sm:w-12"
            :style="{ background: currentStep > item.step ? 'hsl(var(--primary))' : 'hsl(var(--border))' }"
          />
        </template>
      </div>

      <!-- Content Card -->
      <Card class="glass-card border-0 p-0 shadow-xl">
        <CardContent class="p-6">
          <!-- Error -->
          <div
            v-if="error"
            class="mb-4 rounded-md px-3 py-2 text-sm"
            style="background: hsl(var(--destructive) / 0.1); color: hsl(var(--destructive))"
          >
            {{ error }}
          </div>

          <!-- Step 1: Create Admin -->
          <div v-if="currentStep === 1" class="space-y-4">
            <div class="text-center">
              <h2 class="text-lg font-semibold" style="color: hsl(var(--foreground))">👤 创建管理员账号</h2>
              <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">设置您的管理员用户名和密码</p>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">用户名</label>
              <Input v-model="adminUsername" placeholder="请输入管理员用户名" :disabled="loading" />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">密码</label>
              <div class="relative">
                <Input
                  v-model="adminPassword"
                  :type="showPassword ? 'text' : 'password'"
                  placeholder="请输入密码（至少 8 位，含特殊字符）"
                  class="pr-10"
                  :disabled="loading"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2"
                  style="color: hsl(var(--muted-foreground))"
                  tabindex="-1"
                  @click="showPassword = !showPassword"
                >
                  <Eye v-if="!showPassword" class="h-4 w-4" />
                  <EyeOff v-else class="h-4 w-4" />
                </button>
              </div>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">确认密码</label>
              <div class="relative">
                <Input
                  v-model="adminConfirmPassword"
                  :type="showConfirmPassword ? 'text' : 'password'"
                  placeholder="请再次输入密码"
                  class="pr-10"
                  :disabled="loading"
                  @keyup.enter="handleStep1Next"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2"
                  style="color: hsl(var(--muted-foreground))"
                  tabindex="-1"
                  @click="showConfirmPassword = !showConfirmPassword"
                >
                  <Eye v-if="!showConfirmPassword" class="h-4 w-4" />
                  <EyeOff v-else class="h-4 w-4" />
                </button>
              </div>
            </div>

            <p
              v-if="step1Error"
              class="text-sm"
              style="color: hsl(var(--destructive))"
            >
              {{ step1Error }}
            </p>

            <Button
              class="w-full"
              :disabled="!step1Valid || loading"
              @click="handleStep1Next"
            >
              <template v-if="loading">
                <svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                创建中...
              </template>
              <template v-else>
                下一步
                <ChevronRight class="ml-1 h-4 w-4" />
              </template>
            </Button>
          </div>

          <!-- Step 2: Add Drive Account -->
          <div v-if="currentStep === 2" class="space-y-4">
            <div class="text-center">
              <h2 class="text-lg font-semibold" style="color: hsl(var(--foreground))">💾 添加网盘账号</h2>
              <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">选择网盘类型并填写凭证，您也可以稍后配置</p>
            </div>

            <!-- Drive type selection -->
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">网盘类型</label>
              <div v-if="driveTypesLoading" class="text-sm" style="color: hsl(var(--muted-foreground))">加载网盘类型中...</div>
              <div
                v-else-if="!driveTypes.length"
                class="rounded-md px-3 py-2 text-sm"
                style="background: hsl(var(--muted)); color: hsl(var(--muted-foreground))"
              >
                未获取到网盘类型，可跳过此步，稍后在“网盘账号”页面添加。
              </div>
              <select
                v-else
                v-model="selectedDriveType"
                :disabled="loading"
                class="flex h-10 w-full rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                :style="{ borderColor: 'hsl(var(--input))', background: 'hsl(var(--background))', color: 'hsl(var(--foreground))' }"
              >
                <option value="" disabled>请选择网盘类型</option>
                <option v-for="dt in driveTypes" :key="dt.code" :value="dt.code">{{ dt.drive_name }}</option>
              </select>
            </div>

            <div v-if="selectedDriveType" class="space-y-4">
              <div class="space-y-2">
                <label class="text-sm font-medium" style="color: hsl(var(--foreground))">账号名称（可选）</label>
                <Input
                  v-model="driveAccountName"
                  placeholder="给账号起个名字"
                  :disabled="loading"
                />
              </div>

              <!-- Dynamic login config fields (matches real add-account form) -->
              <div v-for="field in currentDriveFields" :key="field.key" class="space-y-2">
                <label class="text-sm font-medium" style="color: hsl(var(--foreground))">
                  {{ field.label || field.key }}
                </label>

                <!-- Switch -->
                <label
                  v-if="field.input_type === 'switch'"
                  class="flex items-center gap-2 text-sm"
                  style="color: hsl(var(--foreground))"
                >
                  <input
                    type="checkbox"
                    v-model="driveConfig[field.key]"
                    class="h-4 w-4 rounded"
                    style="accent-color: hsl(var(--primary))"
                    :disabled="loading"
                  />
                  <span>{{ driveConfig[field.key] ? '开启' : '关闭' }}</span>
                </label>

                <!-- Number -->
                <Input
                  v-else-if="field.input_type === 'number'"
                  v-model="driveConfig[field.key]"
                  type="number"
                  :placeholder="field.placeholder || ''"
                  :disabled="loading"
                />

                <!-- Textarea -->
                <textarea
                  v-else-if="field.input_type === 'textarea'"
                  v-model="driveConfig[field.key]"
                  :rows="field.secret ? 4 : 3"
                  class="flex w-full rounded-md border px-3 py-2 text-sm ring-offset-[hsl(var(--background))] placeholder:text-[hsl(var(--muted-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
                  :style="{ borderColor: 'hsl(var(--input))', background: 'hsl(var(--background))', color: 'hsl(var(--foreground))' }"
                  :placeholder="field.placeholder || ''"
                  :disabled="loading"
                />

                <!-- Password / Text -->
                <Input
                  v-else
                  v-model="driveConfig[field.key]"
                  :type="field.input_type === 'password' ? 'password' : 'text'"
                  :placeholder="field.placeholder || ''"
                  :disabled="loading"
                />

                <p v-if="field.description" class="text-xs" style="color: hsl(var(--muted-foreground))">
                  {{ field.description }}
                </p>
              </div>
            </div>

            <div class="flex gap-3">
              <Button variant="outline" class="flex-1" @click="skipStep2">
                <SkipForward class="mr-1 h-4 w-4" />
                跳过此步
              </Button>
              <Button
                class="flex-1"
                :disabled="!step2Valid || loading"
                @click="handleAddDriveAccount"
              >
                <template v-if="loading">
                  <svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  添加中...
                </template>
                <template v-else>
                  添加并继续
                  <ChevronRight class="ml-1 h-4 w-4" />
                </template>
              </Button>
            </div>
          </div>

          <!-- Step 3: Complete -->
          <div v-if="currentStep === 3" class="space-y-6 text-center">
            <div
              class="mx-auto flex h-20 w-20 items-center justify-center rounded-full"
              style="background: hsl(var(--primary) / 0.1)"
            >
              <PartyPopper class="h-10 w-10" style="color: hsl(var(--primary))" />
            </div>

            <div>
              <h2 class="text-xl font-semibold" style="color: hsl(var(--foreground))">
                🎉 初始化完成！
              </h2>
              <p class="mt-2 text-sm" style="color: hsl(var(--muted-foreground))">
                {{ step2Added ? '管理员账号和网盘已配置完成。' : '管理员账号已创建，您可以稍后在设置中添加网盘账号。' }}
              </p>
              <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">
                欢迎使用 Cloud Auto Save X！
              </p>
            </div>

            <Button class="w-full" size="lg" @click="enterSystem">
              进入系统
              <ChevronRight class="ml-1 h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
