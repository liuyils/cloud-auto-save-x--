<script setup lang="ts">
import { computed, watch, reactive, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Eye, EyeOff, X } from 'lucide-vue-next'
import type { ConfigFieldItem, DriveAccountItem, DriveTypeItem } from '@/types/extensions'

interface Props {
  open: boolean
  editAccount?: DriveAccountItem | null
  driveTypes: DriveTypeItem[]
  submitting?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  editAccount: null,
  submitting: false,
})

const emit = defineEmits<{
  close: []
  save: [payload: {
    name: string
    drive_type: string
    config: Record<string, any>
    enabled: boolean
    is_default: boolean
    capacity_warning_threshold: number
  }]
}>()

const state = reactive({
  name: '',
  drive_type: '',
  configData: {} as Record<string, any>,
  enabled: true,
  is_default: false,
  capacity_warning_threshold: 85,
})
const revealedSecretFields = ref<Record<string, boolean>>({})

const isEditing = computed(() => Boolean(props.editAccount?.id))
const currentDriveType = computed(() => props.driveTypes.find((item) => item.code === state.drive_type) || null)
const currentDriveFields = computed<ConfigFieldItem[]>(() => currentDriveType.value?.config_fields || [])
const isTvCredentialDrive = computed(() => ['quark', 'uc'].includes(String(state.drive_type || '').trim().toLowerCase()))

function cloneConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

function resetRevealedSecretFields() {
  revealedSecretFields.value = {}
}

function isSecretFieldRevealed(key: string) {
  return Boolean(revealedSecretFields.value[key])
}

function toggleSecretField(key: string) {
  revealedSecretFields.value = {
    ...revealedSecretFields.value,
    [key]: !revealedSecretFields.value[key],
  }
}

function syncState() {
  resetRevealedSecretFields()
  if (props.editAccount) {
    state.name = props.editAccount.name
    state.drive_type = props.editAccount.drive_type
    state.configData = cloneConfig(props.editAccount.config || {})
    state.enabled = props.editAccount.enabled
    state.is_default = props.editAccount.is_default
    state.capacity_warning_threshold = props.editAccount.capacity_warning_threshold || 85
    return
  }
  state.name = ''
  state.drive_type = props.driveTypes[0]?.code || ''
  state.configData = cloneConfig(props.driveTypes[0]?.default_config || {})
  state.enabled = true
  state.is_default = false
  state.capacity_warning_threshold = 85
}

watch(
  () => [props.open, props.editAccount, props.driveTypes] as const,
  ([visible]) => {
    if (!visible) return
    syncState()
  },
  { immediate: true, deep: true },
)

watch(
  () => state.drive_type,
  (value, oldValue) => {
    if (!value || value === oldValue || isEditing.value) return
    const target = props.driveTypes.find((item) => item.code === value)
    state.configData = cloneConfig(target?.default_config || {})
  },
)

function handleClose() {
  resetRevealedSecretFields()
  emit('close')
}

function handleSubmit() {
  emit('save', {
    name: state.name.trim(),
    drive_type: state.drive_type,
    config: cloneConfig(state.configData),
    enabled: state.enabled,
    is_default: state.is_default,
    capacity_warning_threshold: state.capacity_warning_threshold,
  })
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-right">
      <div v-if="open" class="fixed inset-0 z-50 flex justify-end">
        <!-- Overlay -->
        <div
          class="absolute inset-0 bg-black/50 transition-opacity"
          @click="handleClose"
        />
        <!-- Panel -->
        <div class="relative z-10 flex h-full w-full max-w-md flex-col bg-[hsl(var(--card))] shadow-xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
            <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">
              {{ isEditing ? '编辑账号' : '添加账号' }}
            </h3>
            <button
              class="rounded-md p-1 hover:bg-[hsl(var(--muted))] transition-colors"
              @click="handleClose"
            >
              <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-5 space-y-6">
            <!-- 基本信息 -->
            <div class="space-y-4">
              <h4 class="text-sm font-medium text-[hsl(var(--foreground))]">基本信息</h4>

              <div class="space-y-2">
                <label class="text-sm text-[hsl(var(--muted-foreground))]">账号名称</label>
                <Input v-model="state.name" placeholder="例如：夸克主账号" />
              </div>

              <div class="space-y-2">
                <label class="text-sm text-[hsl(var(--muted-foreground))]">网盘类型</label>
                <select
                  v-model="state.drive_type"
                  :disabled="isEditing"
                  class="flex h-10 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] ring-offset-[hsl(var(--background))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option v-for="item in driveTypes" :key="item.code" :value="item.code">
                    {{ item.drive_name }}
                  </option>
                </select>
              </div>
            </div>

            <!-- 状态与预警 -->
            <div class="space-y-4">
              <h4 class="text-sm font-medium text-[hsl(var(--foreground))]">状态与预警</h4>

              <div class="space-y-2">
                <label class="text-sm text-[hsl(var(--muted-foreground))]">容量预警阈值 (%)</label>
                <Input
                  v-model="state.capacity_warning_threshold"
                  type="number"
                  placeholder="85"
                />
              </div>

              <div class="flex flex-wrap gap-4">
                <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                  <input
                    type="checkbox"
                    v-model="state.enabled"
                    class="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))]"
                  />
                  启用账号
                </label>
                <label class="flex items-center gap-2 text-sm text-[hsl(var(--foreground))] cursor-pointer">
                  <input
                    type="checkbox"
                    v-model="state.is_default"
                    class="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))]"
                  />
                  设为默认
                </label>
              </div>
            </div>

            <!-- 登录配置 -->
            <div class="space-y-4">
              <h4 class="text-sm font-medium text-[hsl(var(--foreground))]">登录配置</h4>

              <div
                v-if="isEditing"
                class="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]"
              >
                当前显示的是已保存的登录参数，保存后会直接覆盖当前账号配置。
              </div>

              <div
                v-if="isTvCredentialDrive"
                class="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400"
              >
                Quark / UC 支持同时保存 Cookie 与 TV 凭据，但账号运行仍按 Cookie 优先；TV 字段仅用于 TV 扫码登录与凭据留存。
              </div>

              <div v-for="field in currentDriveFields" :key="field.key" class="space-y-2">
                <label class="text-sm text-[hsl(var(--muted-foreground))]">
                  {{ field.label || field.key }}
                </label>

                <!-- Switch -->
                <label
                  v-if="field.input_type === 'switch'"
                  class="flex items-center gap-2 text-sm cursor-pointer"
                >
                  <input
                    type="checkbox"
                    v-model="state.configData[field.key]"
                    class="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))]"
                  />
                  <span class="text-[hsl(var(--foreground))]">{{ state.configData[field.key] ? '开启' : '关闭' }}</span>
                </label>

                <!-- Number -->
                <Input
                  v-else-if="field.input_type === 'number'"
                  v-model="state.configData[field.key]"
                  type="number"
                  :placeholder="field.placeholder || ''"
                />

                <!-- Textarea -->
                <textarea
                  v-else-if="field.input_type === 'textarea'"
                  v-model="state.configData[field.key]"
                  :placeholder="field.placeholder || ''"
                  :rows="field.secret ? 4 : 3"
                  class="flex w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] ring-offset-[hsl(var(--background))] placeholder:text-[hsl(var(--muted-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
                />

                <!-- Password / Text -->
                <div v-else class="relative">
                  <Input
                    v-model="state.configData[field.key]"
                    :type="field.input_type === 'password' && !isSecretFieldRevealed(field.key) ? 'password' : 'text'"
                    :placeholder="field.placeholder || ''"
                    :class="field.input_type === 'password' ? 'pr-10' : ''"
                  />
                  <button
                    v-if="field.input_type === 'password'"
                    type="button"
                    class="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                    :aria-label="isSecretFieldRevealed(field.key) ? '隐藏' : '显示'"
                    @click="toggleSecretField(field.key)"
                  >
                    <EyeOff v-if="isSecretFieldRevealed(field.key)" class="h-4 w-4" />
                    <Eye v-else class="h-4 w-4" />
                  </button>
                </div>

                <p v-if="field.description" class="text-xs text-[hsl(var(--muted-foreground))]">
                  {{ field.description }}
                </p>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-3 border-t border-[hsl(var(--border))] px-5 py-4">
            <Button variant="outline" size="sm" @click="handleClose">取消</Button>
            <Button size="sm" :disabled="submitting || !state.name.trim() || !state.drive_type" @click="handleSubmit">
              {{ submitting ? '保存中...' : '保存' }}
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet-right-enter-active,
.sheet-right-leave-active {
  transition: opacity 0.2s ease;
}
.sheet-right-enter-active > div:last-child,
.sheet-right-leave-active > div:last-child {
  transition: transform 0.25s ease;
}
.sheet-right-enter-from,
.sheet-right-leave-to {
  opacity: 0;
}
.sheet-right-enter-from > div:last-child,
.sheet-right-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
