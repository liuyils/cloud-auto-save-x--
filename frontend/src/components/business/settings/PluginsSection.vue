<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Puzzle, RefreshCw, Settings2, X } from 'lucide-vue-next'
import { usePluginsQuery, useSyncPluginsQuery } from '@/hooks/queries/extensions'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { updatePlugin, refreshPlugins, updateSyncPlugin, refreshSyncPlugins } from '@/api/extensions'
import type { PluginItem, ConfigFieldItem } from '@/types/extensions'

const activeTab = ref<'cas' | 'sync'>('cas')
const queryClient = useQueryClient()

const { data: casPlugins, isLoading: casLoading } = usePluginsQuery()
const { data: syncPlugins, isLoading: syncLoading } = useSyncPluginsQuery()

const plugins = computed(() => activeTab.value === 'cas' ? casPlugins.value : syncPlugins.value)
const isLoading = computed(() => activeTab.value === 'cas' ? casLoading.value : syncLoading.value)

const queryKeys = computed(() => activeTab.value === 'cas' ? ['plugins'] : ['sync-plugins'])

// --- Toggle mutation ---
const toggleMutation = useMutation({
  mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
    activeTab.value === 'cas'
      ? updatePlugin(key, { enabled })
      : updateSyncPlugin(key, { enabled }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.value }),
})

// --- Refresh mutation ---
const refreshMutation = useMutation({
  mutationFn: () => activeTab.value === 'cas' ? refreshPlugins() : refreshSyncPlugins(),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.value }),
})

// --- Config Sheet ---
const sheetOpen = ref(false)
const currentPlugin = ref<PluginItem | null>(null)
const configState = reactive({
  enabled: false,
  priority: 100,
  configData: {} as Record<string, any>,
  configText: '{}',
})

const configFields = computed<ConfigFieldItem[]>(() => currentPlugin.value?.config_fields || [])
const taskConfigFields = computed<ConfigFieldItem[]>(() => currentPlugin.value?.task_config_fields || [])
const useStructuredForm = computed(() => configFields.value.length > 0)

function openConfig(plugin: PluginItem) {
  currentPlugin.value = plugin
  configState.enabled = plugin.enabled
  configState.priority = plugin.priority
  configState.configData = JSON.parse(JSON.stringify(plugin.config || {}))
  configState.configText = JSON.stringify(plugin.config || {}, null, 2)
  sheetOpen.value = true
}

function closeSheet() {
  sheetOpen.value = false
}

const saveMutation = useMutation({
  mutationFn: (payload: { enabled: boolean; priority: number; config: Record<string, any> }) => {
    const key = currentPlugin.value!.plugin_key
    return activeTab.value === 'cas'
      ? updatePlugin(key, payload)
      : updateSyncPlugin(key, payload)
  },
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.value })
    sheetOpen.value = false
  },
})

function submitConfig() {
  const config = useStructuredForm.value
    ? JSON.parse(JSON.stringify(configState.configData))
    : JSON.parse(configState.configText || '{}')
  saveMutation.mutate({
    enabled: configState.enabled,
    priority: configState.priority,
    config,
  })
}

function handleToggle(pluginKey: string, currentEnabled: boolean) {
  toggleMutation.mutate({ key: pluginKey, enabled: !currentEnabled })
}

// --- Priority inline edit ---
const editingPriority = ref<string | null>(null)
const priorityValue = ref(0)

function startEditPriority(plugin: PluginItem) {
  editingPriority.value = plugin.plugin_key
  priorityValue.value = plugin.priority
}

const priorityMutation = useMutation({
  mutationFn: ({ key, priority }: { key: string; priority: number }) =>
    activeTab.value === 'cas'
      ? updatePlugin(key, { priority })
      : updateSyncPlugin(key, { priority }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.value })
    editingPriority.value = null
  },
})

function savePriority(pluginKey: string) {
  priorityMutation.mutate({ key: pluginKey, priority: priorityValue.value })
}

function statusColor(status?: string | null) {
  if (status === 'ok') return 'default'
  if (status === 'error') return 'destructive'
  return 'secondary'
}
</script>

<template>
  <div>
    <div class="mb-5 flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">🧩 插件管理</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">管理转存/同步后置插件</p>
      </div>
      <Button variant="outline" size="sm" :disabled="refreshMutation.isPending.value" @click="refreshMutation.mutate()">
        <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': refreshMutation.isPending.value }" />
        扫描插件
      </Button>
    </div>

    <!-- Tab bar -->
    <div class="mb-4 flex gap-1 rounded-lg bg-[hsl(var(--muted))] p-1 w-fit">
      <button
        class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
        :class="activeTab === 'cas' ? 'bg-[hsl(var(--background))] text-[hsl(var(--foreground))] shadow-sm' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
        @click="activeTab = 'cas'"
      >
        转存插件
      </button>
      <button
        class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
        :class="activeTab === 'sync' ? 'bg-[hsl(var(--background))] text-[hsl(var(--foreground))] shadow-sm' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
        @click="activeTab = 'sync'"
      >
        同步插件
      </button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="grid gap-4 sm:grid-cols-2">
      <Skeleton v-for="i in 4" :key="i" class="h-32 rounded-lg" />
    </div>

    <!-- Empty -->
    <div
      v-else-if="!plugins || plugins.length === 0"
      class="flex flex-col items-center justify-center py-16"
    >
      <div class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--muted))]">
        <Puzzle class="h-6 w-6 text-[hsl(var(--muted-foreground))]" />
      </div>
      <p class="text-sm text-[hsl(var(--muted-foreground))]">暂无可用插件，可先执行扫描</p>
    </div>

    <!-- Plugin grid -->
    <div v-else class="grid gap-4 sm:grid-cols-2">
      <Card
        v-for="plugin in plugins"
        :key="plugin.plugin_key"
        class="border-[hsl(var(--border))]"
      >
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <CardTitle class="text-sm font-medium">{{ plugin.plugin_key }}</CardTitle>
            <div class="flex items-center gap-1.5">
              <Badge v-if="plugin.runtime_status" :variant="statusColor(plugin.runtime_status)" class="text-[10px]">
                {{ plugin.runtime_status }}
              </Badge>
              <Badge :variant="plugin.enabled ? 'default' : 'secondary'">
                {{ plugin.enabled ? '启用' : '禁用' }}
              </Badge>
            </div>
          </div>
          <CardDescription class="text-xs">
            {{ plugin.module_name }}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div class="flex items-center justify-between">
            <!-- Priority -->
            <div class="flex items-center gap-1.5">
              <span class="text-xs text-[hsl(var(--muted-foreground))]">优先级:</span>
              <template v-if="editingPriority === plugin.plugin_key">
                <Input
                  v-model="priorityValue"
                  type="number"
                  class="h-6 w-16 text-xs"
                  @keyup.enter="savePriority(plugin.plugin_key)"
                  @blur="savePriority(plugin.plugin_key)"
                />
              </template>
              <button
                v-else
                class="text-xs font-mono text-[hsl(var(--foreground))] hover:underline cursor-pointer"
                @click="startEditPriority(plugin)"
              >
                {{ plugin.priority }}
              </button>
            </div>
            <!-- Actions -->
            <div class="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 text-xs px-2"
                @click="openConfig(plugin)"
              >
                <Settings2 class="mr-1 h-3.5 w-3.5" />
                配置
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="h-7 text-xs"
                @click="handleToggle(plugin.plugin_key, plugin.enabled)"
              >
                {{ plugin.enabled ? '禁用' : '启用' }}
              </Button>
            </div>
          </div>
          <p v-if="plugin.last_error" class="mt-2 text-xs text-red-500 truncate" :title="plugin.last_error">
            {{ plugin.last_error }}
          </p>
        </CardContent>
      </Card>
    </div>

    <!-- Config Sheet (right-side drawer) -->
    <Teleport to="body">
      <Transition name="config-sheet">
        <div v-if="sheetOpen" class="fixed inset-0 z-50 flex justify-end">
          <div class="absolute inset-0 bg-black/50" @click="closeSheet" />
          <div class="relative z-10 flex h-full w-full max-w-md flex-col bg-[hsl(var(--card))] shadow-xl overflow-y-auto">
            <!-- Header -->
            <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
              <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">
                配置 · {{ currentPlugin?.plugin_key }}
              </h3>
              <button class="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="closeSheet">
                <X class="h-5 w-5" />
              </button>
            </div>

            <!-- Body -->
            <div class="flex-1 space-y-5 p-5">
              <!-- Control section -->
              <div class="rounded-lg border border-[hsl(var(--border))] p-4 space-y-3">
                <div class="text-sm font-medium text-[hsl(var(--foreground))]">运行控制</div>
                <div class="flex items-center justify-between">
                  <span class="text-sm text-[hsl(var(--muted-foreground))]">启用插件</span>
                  <button
                    class="relative h-5 w-9 rounded-full transition-colors"
                    :class="configState.enabled ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
                    @click="configState.enabled = !configState.enabled"
                  >
                    <span
                      class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                      :class="configState.enabled ? 'left-[18px]' : 'left-0.5'"
                    />
                  </button>
                </div>
                <div class="flex items-center justify-between">
                  <span class="text-sm text-[hsl(var(--muted-foreground))]">优先级</span>
                  <Input v-model="configState.priority" type="number" class="h-8 w-24 text-sm" />
                </div>
              </div>

              <!-- Config fields section -->
              <div class="rounded-lg border border-[hsl(var(--border))] p-4 space-y-3">
                <div class="text-sm font-medium text-[hsl(var(--foreground))]">全局配置</div>
                <template v-if="useStructuredForm">
                  <div v-for="field in configFields" :key="field.key" class="space-y-1">
                    <label class="text-xs font-medium text-[hsl(var(--foreground))]">
                      {{ field.label || field.key }}
                    </label>
                    <!-- Switch -->
                    <div v-if="field.input_type === 'switch'" class="flex items-center">
                      <button
                        class="relative h-5 w-9 rounded-full transition-colors"
                        :class="configState.configData[field.key] ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
                        @click="configState.configData[field.key] = !configState.configData[field.key]"
                      >
                        <span
                          class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
                          :class="configState.configData[field.key] ? 'left-[18px]' : 'left-0.5'"
                        />
                      </button>
                    </div>
                    <!-- Number -->
                    <Input
                      v-else-if="field.input_type === 'number'"
                      v-model="configState.configData[field.key]"
                      type="number"
                      :placeholder="field.placeholder || ''"
                      class="h-8 text-sm"
                    />
                    <!-- Textarea -->
                    <textarea
                      v-else-if="field.input_type === 'textarea'"
                      v-model="configState.configData[field.key]"
                      :placeholder="field.placeholder || ''"
                      rows="3"
                      class="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                    />
                    <!-- Password -->
                    <Input
                      v-else-if="field.input_type === 'password'"
                      v-model="configState.configData[field.key]"
                      type="password"
                      :placeholder="field.placeholder || ''"
                      class="h-8 text-sm"
                    />
                    <!-- Text (default) -->
                    <Input
                      v-else
                      v-model="configState.configData[field.key]"
                      :placeholder="field.placeholder || ''"
                      class="h-8 text-sm"
                    />
                    <p v-if="field.description" class="text-[11px] text-[hsl(var(--muted-foreground))]">
                      {{ field.description }}
                    </p>
                  </div>
                </template>
                <template v-else>
                  <textarea
                    v-model="configState.configText"
                    rows="10"
                    class="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm font-mono text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                    placeholder="{}"
                  />
                </template>
              </div>

              <!-- Task config fields info -->
              <div v-if="taskConfigFields.length" class="rounded-lg border border-[hsl(var(--border))] p-4 space-y-3">
                <div class="text-sm font-medium text-[hsl(var(--foreground))]">任务配置说明</div>
                <div v-for="field in taskConfigFields" :key="field.key" class="space-y-0.5">
                  <div class="text-xs font-medium text-[hsl(var(--foreground))]">{{ field.label || field.key }}</div>
                  <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ field.description || '未提供说明' }}</div>
                </div>
              </div>
            </div>

            <!-- Footer -->
            <div class="border-t border-[hsl(var(--border))] px-5 py-3 flex justify-end gap-2">
              <Button variant="outline" size="sm" @click="closeSheet">取消</Button>
              <Button size="sm" :disabled="saveMutation.isPending.value" @click="submitConfig">
                保存
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.config-sheet-enter-active,
.config-sheet-leave-active {
  transition: opacity 0.2s ease;
}
.config-sheet-enter-active > div:last-child,
.config-sheet-leave-active > div:last-child {
  transition: transform 0.2s ease;
}
.config-sheet-enter-from,
.config-sheet-leave-to {
  opacity: 0;
}
.config-sheet-enter-from > div:last-child,
.config-sheet-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
