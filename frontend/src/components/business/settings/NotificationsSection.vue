<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Bell, Send, Loader2, Check, Settings2, Eye, EyeOff, X } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useNotificationsQuery } from '@/hooks/queries/extensions'
import { useUpdateNotificationConfigMutation, useTestNotificationMutation } from '@/hooks/mutations/notifications'

const { toast } = useToast()

// ─── Queries & Mutations ───────────────────────────────────────────
const { data: notifData, isLoading } = useNotificationsQuery()
const updateMutation = useUpdateNotificationConfigMutation()
const testMutation = useTestNotificationMutation()

// ─── Local State ───────────────────────────────────────────────────
const configData = ref<Record<string, any>>({})
const editingChannel = ref<string | null>(null)
const testingChannel = ref<string | null>(null)
const revealedFields = ref<Record<string, boolean>>({})

// Sync remote data → local state
watch(
  () => notifData.value,
  (val) => {
    if (val) {
      const merged: Record<string, any> = { ...(val.default_config || {}), ...(val.config || {}) }
      // Deep-copy the channel-enabled map: the spread above only clones the top level,
      // so the nested map would otherwise stay a reference into the (readonly) query cache
      // and in-place writes to it would silently no-op.
      const rawEnabled = merged.__channel_enabled
      merged.__channel_enabled =
        rawEnabled && typeof rawEnabled === 'object' && !Array.isArray(rawEnabled) ? { ...rawEnabled } : {}
      configData.value = merged
    }
  },
  { immediate: true },
)

// ─── Channel Definitions ───────────────────────────────────────────
interface ChannelField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'switch' | 'textarea'
  placeholder?: string
  rows?: number
}

interface ChannelDef {
  id: string
  title: string
  required_keys: string[]
  fields: ChannelField[]
}

const channels: ChannelDef[] = [
  {
    id: 'bark',
    title: 'Bark',
    required_keys: ['BARK_PUSH'],
    fields: [
      { key: 'BARK_PUSH', label: 'Bark URL / 设备码', type: 'text', placeholder: 'https://api.day.app/xxx' },
      { key: 'BARK_GROUP', label: '分组', type: 'text', placeholder: 'CloudSaver' },
      { key: 'BARK_SOUND', label: '提示音', type: 'text', placeholder: 'minuet' },
      { key: 'BARK_ICON', label: '图标 URL', type: 'text' },
      { key: 'BARK_LEVEL', label: '通知等级', type: 'text', placeholder: 'active / timeSensitive / passive' },
    ],
  },
  {
    id: 'telegram',
    title: 'Telegram',
    required_keys: ['TG_BOT_TOKEN', 'TG_USER_ID'],
    fields: [
      { key: 'TG_BOT_TOKEN', label: 'Bot Token', type: 'password' },
      { key: 'TG_USER_ID', label: 'Chat ID', type: 'text' },
      { key: 'TG_API_HOST', label: 'API Host', type: 'text', placeholder: 'https://api.telegram.org' },
      { key: 'TG_PROXY_HOST', label: '代理 Host', type: 'text' },
      { key: 'TG_PROXY_PORT', label: '代理 Port', type: 'text' },
    ],
  },
  {
    id: 'dingding',
    title: '钉钉机器人',
    required_keys: ['DD_BOT_TOKEN', 'DD_BOT_SECRET'],
    fields: [
      { key: 'DD_BOT_TOKEN', label: 'Token', type: 'password' },
      { key: 'DD_BOT_SECRET', label: 'Secret', type: 'password' },
    ],
  },
  {
    id: 'feishu',
    title: '飞书机器人',
    required_keys: ['FSKEY'],
    fields: [
      { key: 'FSKEY', label: 'Webhook Key', type: 'password' },
    ],
  },
  {
    id: 'wecom_bot',
    title: '企业微信机器人',
    required_keys: ['QYWX_KEY'],
    fields: [
      { key: 'QYWX_KEY', label: 'Webhook Key', type: 'password' },
    ],
  },
  {
    id: 'wecom_app',
    title: '企业微信应用',
    required_keys: ['QYWX_AM'],
    fields: [
      { key: 'QYWX_ORIGIN', label: 'API Origin', type: 'text', placeholder: 'https://qyapi.weixin.qq.com' },
      { key: 'QYWX_AM', label: 'QYWX_AM', type: 'text', placeholder: 'corpid,corpsecret,agentid,touser' },
    ],
  },
  {
    id: 'smtp',
    title: 'SMTP 邮件',
    required_keys: ['SMTP_SERVER', 'SMTP_EMAIL', 'SMTP_PASSWORD'],
    fields: [
      { key: 'SMTP_SERVER', label: 'SMTP 服务器', type: 'text', placeholder: 'smtp.example.com:465' },
      { key: 'SMTP_SSL', label: 'SSL', type: 'switch' },
      { key: 'SMTP_EMAIL', label: '邮箱', type: 'text' },
      { key: 'SMTP_PASSWORD', label: '密码', type: 'password' },
      { key: 'SMTP_NAME', label: '发件人名称', type: 'text' },
      { key: 'SMTP_EMAIL_TO', label: '收件人', type: 'text', placeholder: '多个用逗号分隔' },
    ],
  },
  {
    id: 'pushplus',
    title: 'PushPlus',
    required_keys: ['PUSH_PLUS_TOKEN'],
    fields: [
      { key: 'PUSH_PLUS_TOKEN', label: 'Token', type: 'password' },
      { key: 'PUSH_PLUS_USER', label: '群组编码', type: 'text', placeholder: '可选' },
      { key: 'PUSH_PLUS_TEMPLATE', label: '模板', type: 'text', placeholder: 'html / txt / markdown' },
      { key: 'PUSH_PLUS_CHANNEL', label: '渠道', type: 'text', placeholder: 'wechat / webhook / cp / mail' },
    ],
  },
  {
    id: 'serverj',
    title: 'Server酱',
    required_keys: ['PUSH_KEY'],
    fields: [
      { key: 'PUSH_KEY', label: 'SendKey', type: 'password' },
    ],
  },
  {
    id: 'pushdeer',
    title: 'PushDeer',
    required_keys: ['DEER_KEY'],
    fields: [
      { key: 'DEER_KEY', label: 'Key', type: 'password' },
      { key: 'DEER_URL', label: 'URL', type: 'text', placeholder: 'https://api2.pushdeer.com/message/push' },
    ],
  },
  {
    id: 'gotify',
    title: 'Gotify',
    required_keys: ['GOTIFY_URL', 'GOTIFY_TOKEN'],
    fields: [
      { key: 'GOTIFY_URL', label: 'URL', type: 'text', placeholder: 'https://push.example.de:8080' },
      { key: 'GOTIFY_TOKEN', label: 'Token', type: 'password' },
      { key: 'GOTIFY_PRIORITY', label: '优先级', type: 'number' },
    ],
  },
  {
    id: 'ntfy',
    title: 'Ntfy',
    required_keys: ['NTFY_TOPIC'],
    fields: [
      { key: 'NTFY_URL', label: 'URL', type: 'text', placeholder: 'https://ntfy.sh' },
      { key: 'NTFY_TOPIC', label: 'Topic', type: 'text' },
      { key: 'NTFY_PRIORITY', label: '优先级', type: 'text', placeholder: '3' },
      { key: 'NTFY_TOKEN', label: 'Token', type: 'password' },
    ],
  },
  {
    id: 'wxpusher',
    title: 'WxPusher',
    required_keys: ['WXPUSHER_APP_TOKEN'],
    fields: [
      { key: 'WXPUSHER_APP_TOKEN', label: 'App Token', type: 'password' },
      { key: 'WXPUSHER_TOPIC_IDS', label: 'Topic IDs', type: 'text', placeholder: '多个用 ; 分隔' },
      { key: 'WXPUSHER_UIDS', label: 'UIDs', type: 'text', placeholder: '多个用 ; 分隔' },
    ],
  },
  {
    id: 'webhook',
    title: '自定义 Webhook',
    required_keys: ['WEBHOOK_URL', 'WEBHOOK_METHOD'],
    fields: [
      { key: 'WEBHOOK_URL', label: 'URL', type: 'text', placeholder: '支持 $title / $content 替换' },
      { key: 'WEBHOOK_METHOD', label: '方法', type: 'text', placeholder: 'POST / GET' },
      { key: 'WEBHOOK_HEADERS', label: 'Headers', type: 'textarea', rows: 2, placeholder: 'JSON 字符串' },
      { key: 'WEBHOOK_BODY', label: 'Body', type: 'textarea', rows: 3, placeholder: '支持 $title / $content' },
      { key: 'WEBHOOK_CONTENT_TYPE', label: 'Content-Type', type: 'text', placeholder: 'application/json' },
    ],
  },
  {
    id: 'gocqhttp',
    title: 'go-cqhttp',
    required_keys: ['GOBOT_URL', 'GOBOT_QQ'],
    fields: [
      { key: 'GOBOT_URL', label: 'URL', type: 'text', placeholder: 'http://127.0.0.1/send_private_msg' },
      { key: 'GOBOT_QQ', label: 'QQ', type: 'text' },
      { key: 'GOBOT_TOKEN', label: 'Token', type: 'password' },
    ],
  },
  {
    id: 'pushme',
    title: 'PushMe',
    required_keys: ['PUSHME_KEY'],
    fields: [
      { key: 'PUSHME_KEY', label: 'Key', type: 'password' },
      { key: 'PUSHME_URL', label: 'URL', type: 'text' },
    ],
  },
  {
    id: 'weplus',
    title: '微加机器人',
    required_keys: ['WE_PLUS_BOT_TOKEN'],
    fields: [
      { key: 'WE_PLUS_BOT_TOKEN', label: 'Token', type: 'password' },
      { key: 'WE_PLUS_BOT_RECEIVER', label: 'Receiver', type: 'text' },
      { key: 'WE_PLUS_BOT_VERSION', label: 'Version', type: 'text', placeholder: 'pro' },
    ],
  },
  {
    id: 'dodo',
    title: 'DoDo 机器人',
    required_keys: ['DODO_BOTTOKEN', 'DODO_BOTID', 'DODO_SOURCEID'],
    fields: [
      { key: 'DODO_BOTTOKEN', label: 'Bot Token', type: 'password' },
      { key: 'DODO_BOTID', label: 'Bot ID', type: 'text' },
      { key: 'DODO_LANDSOURCEID', label: 'Land Source ID', type: 'text' },
      { key: 'DODO_SOURCEID', label: 'Source ID', type: 'text' },
    ],
  },
]

// ─── Computed Helpers ──────────────────────────────────────────────
function hasValue(value: any): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return !Number.isNaN(value) && value !== 0
  return String(value ?? '').trim() !== ''
}

function isChannelEnabled(channelId: string): boolean {
  const map = configData.value.__channel_enabled
  if (!map || typeof map !== 'object') return false
  return map[channelId] === true
}

function isChannelConfigured(channel: ChannelDef): boolean {
  return channel.required_keys.every((k) => hasValue(configData.value[k]))
}

function toggleChannel(channelId: string) {
  // Rebuild the map and the top-level object instead of mutating shared/readonly refs in place,
  // otherwise the toggled value never changes and the request payload stays the same.
  const map = { ...(configData.value.__channel_enabled || {}) }
  map[channelId] = !map[channelId]
  configData.value = { ...configData.value, __channel_enabled: map }
  saveConfig()
}

function openChannelEditor(channelId: string) {
  revealedFields.value = {}
  editingChannel.value = channelId
}

function closeChannelEditor() {
  editingChannel.value = null
  revealedFields.value = {}
}

const editingChannelDef = computed(() => channels.find((c) => c.id === editingChannel.value) || null)

function isRevealed(key: string): boolean {
  return revealedFields.value[key] === true
}

function toggleReveal(key: string) {
  revealedFields.value = { ...revealedFields.value, [key]: !revealedFields.value[key] }
}

function fieldInputType(field: ChannelField): string {
  if (field.type === 'password') return isRevealed(field.key) ? 'text' : 'password'
  return field.type
}

function getFieldValue(key: string): string {
  const val = configData.value[key]
  if (val === undefined || val === null) return ''
  return String(val)
}

function setFieldValue(key: string, value: string) {
  configData.value[key] = value
}

// ─── Actions ──────────────────────────────────────────────────────
async function saveConfig(): Promise<boolean> {
  try {
    // Send a plain deep clone so no reactive/readonly proxy leaks into the request payload
    const payload = JSON.parse(JSON.stringify(configData.value))
    await updateMutation.mutateAsync(payload)
    toast.success('配置已保存')
    return true
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '保存失败')
    return false
  }
}

async function saveChannelEditor() {
  const ok = await saveConfig()
  if (ok) closeChannelEditor()
}

async function testChannel(channelId: string) {
  testingChannel.value = channelId
  try {
    const result = await testMutation.mutateAsync({
      title: '测试通知',
      content: '这是一条来自 CloudSaver 的测试消息。',
      channels: [channelId],
    })
    const channelResult = result.results.find((r) => r.channel === channelId)
    if (channelResult?.ok) {
      toast.success(`${getChannelTitle(channelId)} 测试发送成功`)
    } else {
      toast.error(`测试失败: ${channelResult?.error || '未知错误'}`)
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.message || '测试发送失败')
  } finally {
    testingChannel.value = null
  }
}

function getChannelTitle(id: string): string {
  return channels.find((c) => c.id === id)?.title || id
}

// Summary
const summary = computed(() => {
  const configured = channels.filter((c) => isChannelConfigured(c)).length
  const enabled = channels.filter((c) => isChannelEnabled(c.id)).length
  return { total: channels.length, configured, enabled }
})
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-5 flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-[hsl(var(--foreground))]">🔔 通知配置</h2>
        <p class="mt-0.5 text-sm text-[hsl(var(--muted-foreground))]">
          管理消息通知渠道 ·
          <span class="text-[hsl(var(--foreground))]">{{ summary.enabled }}</span> 已启用 /
          <span class="text-[hsl(var(--foreground))]">{{ summary.configured }}</span> 已配置 /
          {{ summary.total }} 个渠道
        </p>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <Skeleton v-for="i in 6" :key="i" class="h-24 w-full rounded-lg" />
    </div>

    <!-- Channel Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="channel in channels"
        :key="channel.id"
        class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden transition-shadow hover:shadow-sm"
      >
        <!-- Card Header -->
        <div class="flex items-center gap-3 px-4 py-3">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--muted))]">
            <Bell class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          </div>
          <div class="flex-1 min-w-0">
            <span class="text-sm font-medium text-[hsl(var(--foreground))]">{{ channel.title }}</span>
            <div class="flex items-center gap-1.5 mt-0.5">
              <Badge
                :variant="isChannelConfigured(channel) ? 'default' : 'secondary'"
                class="text-[10px] px-1.5 py-0"
              >
                {{ isChannelConfigured(channel) ? '已配置' : '未配置' }}
              </Badge>
              <Badge
                v-if="isChannelEnabled(channel.id)"
                variant="default"
                class="text-[10px] px-1.5 py-0 bg-green-600"
              >
                已启用
              </Badge>
            </div>
          </div>
          <!-- Toggle -->
          <button
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors"
            :class="isChannelEnabled(channel.id) ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
            role="switch"
            :aria-checked="isChannelEnabled(channel.id)"
            @click.stop="toggleChannel(channel.id)"
          >
            <span
              class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform"
              :class="isChannelEnabled(channel.id) ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
        </div>

        <!-- Action Bar -->
        <div class="flex items-center gap-1 border-t border-[hsl(var(--border))] px-3 py-1.5 bg-[hsl(var(--muted))]/30">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 text-xs px-2"
            @click="openChannelEditor(channel.id)"
          >
            <Settings2 class="mr-1 h-3 w-3" />
            配置
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 text-xs px-2"
            :disabled="!isChannelConfigured(channel) || testingChannel === channel.id"
            @click="testChannel(channel.id)"
          >
            <Loader2 v-if="testingChannel === channel.id" class="mr-1 h-3 w-3 animate-spin" />
            <Send v-else class="mr-1 h-3 w-3" />
            测试
          </Button>
        </div>
      </div>
    </div>

    <!-- Channel Config Modal -->
    <Transition name="fade">
      <div
        v-if="editingChannelDef"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        @click.self="closeChannelEditor"
      >
        <div class="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
            <div class="flex items-center gap-2.5">
              <div class="flex h-8 w-8 items-center justify-center rounded-md bg-[hsl(var(--muted))]">
                <Bell class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
              </div>
              <div>
                <div class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ editingChannelDef.title }}</div>
                <div class="text-xs text-[hsl(var(--muted-foreground))]">渠道配置</div>
              </div>
            </div>
            <Button variant="ghost" size="sm" class="h-7 w-7 p-0" @click="closeChannelEditor"><X class="h-4 w-4" /></Button>
          </div>

          <!-- Body -->
          <div class="flex-1 space-y-3.5 overflow-y-auto px-5 py-4">
            <div v-for="field in editingChannelDef.fields" :key="field.key" class="space-y-1.5">
              <label class="text-xs font-medium text-[hsl(var(--muted-foreground))]">{{ field.label }}</label>
              <!-- Switch -->
              <div v-if="field.type === 'switch'" class="flex items-center">
                <button
                  class="relative inline-flex h-5 w-9 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors"
                  :class="getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
                  role="switch"
                  @click="setFieldValue(field.key, getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'false' : 'true')"
                >
                  <span
                    class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform"
                    :class="getFieldValue(field.key) === 'true' || getFieldValue(field.key) === '1' ? 'translate-x-4' : 'translate-x-0'"
                  />
                </button>
              </div>
              <!-- Textarea -->
              <textarea
                v-else-if="field.type === 'textarea'"
                :value="getFieldValue(field.key)"
                :placeholder="field.placeholder"
                :rows="field.rows || 3"
                class="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                @input="setFieldValue(field.key, ($event.target as HTMLTextAreaElement).value)"
              />
              <!-- Input (with password reveal) -->
              <div v-else class="relative">
                <Input
                  :type="fieldInputType(field)"
                  :model-value="getFieldValue(field.key)"
                  :placeholder="field.placeholder"
                  class="h-9 text-sm"
                  :class="field.type === 'password' ? 'pr-9' : ''"
                  @update:model-value="setFieldValue(field.key, $event)"
                />
                <button
                  v-if="field.type === 'password'"
                  type="button"
                  class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  :aria-label="isRevealed(field.key) ? '隐藏' : '显示'"
                  @click="toggleReveal(field.key)"
                >
                  <EyeOff v-if="isRevealed(field.key)" class="h-4 w-4" />
                  <Eye v-else class="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex justify-end gap-2 border-t border-[hsl(var(--border))] px-5 py-3.5">
            <Button variant="outline" size="sm" @click="closeChannelEditor">取消</Button>
            <Button size="sm" :disabled="updateMutation.isPending.value" @click="saveChannelEditor">
              <Loader2 v-if="updateMutation.isPending.value" class="mr-1 h-3.5 w-3.5 animate-spin" />
              <Check v-else class="mr-1 h-3.5 w-3.5" />
              保存
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
