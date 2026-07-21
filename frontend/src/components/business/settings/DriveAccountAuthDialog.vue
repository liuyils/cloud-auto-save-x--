<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { X, RefreshCw, QrCode, ShieldCheck } from 'lucide-vue-next'
import {
  fetchDriveAccountAuthSession,
  pollDriveAccountQrcodeAuth,
  sendDriveAccountSms,
  startDriveAccountAuth,
  startDriveAccountQrcodeAuth,
  submitDriveAccountCaptcha,
  submitDriveAccountSms,
} from '@/api/extensions'
import { useToast } from '@/composables/useToast'
import {
  supportsQrcodeAuth,
  supportsTvQrcodeAuth,
  parseAuthChallenge,
  extractErrorMessage,
  normalizeDriveType,
} from '@/lib/driveAuth'
import type { DriveAccountAuthChallenge, DriveAccountAuthMethod } from '@/types/extensions'

interface Props {
  open: boolean
  accountId: number
  accountName?: string
  driveType?: string
  /** 由 409 挑战触发时传入 */
  initialChallenge?: DriveAccountAuthChallenge | null
  /** 直接发起（TV）扫码 */
  startQrcode?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  accountName: '',
  driveType: '',
  initialChallenge: null,
  startQrcode: false,
})

const emit = defineEmits<{
  close: []
  success: []
}>()

const { toast } = useToast()

const loading = ref(false)
const method = ref<DriveAccountAuthMethod>('captcha')
const sessionId = ref('')
const payload = ref<Record<string, any>>({})

const captchaCode = ref('')
const smsCode = ref('')
const smsSending = ref(false)
const captchaSubmitting = ref(false)
const smsSubmitting = ref(false)
const qrcodePolling = ref(false)

let pollTimer: number | null = null

const driveType = computed(() =>
  normalizeDriveType(props.driveType || payload.value.drive_type || ''),
)
const canStartQrcode = computed(() => supportsQrcodeAuth(driveType.value))
const isTvQrcodeDrive = computed(() => supportsTvQrcodeAuth(driveType.value))
const qrcodeButtonText = computed(() => (isTvQrcodeDrive.value ? 'TV 扫码登录' : '扫码登录'))
const qrcodeAlertTitle = computed(() =>
  isTvQrcodeDrive.value ? '请使用对应 TV 客户端扫描二维码完成登录。' : '请使用手机扫描二维码完成登录。',
)
const qrcodeSuccessMessage = computed(() => (isTvQrcodeDrive.value ? 'TV 凭据已保存' : '扫码成功，账号已登录'))
const qrcodeImageSrc = computed(() => String(payload.value.qrcode_image || payload.value.qrcode_url || '').trim())

function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startAutoPoll() {
  stopPoll()
  pollTimer = window.setInterval(() => {
    pollQrcodeOnce()
  }, 2000)
}

function resetState() {
  stopPoll()
  method.value = 'captcha'
  sessionId.value = ''
  payload.value = {}
  captchaCode.value = ''
  smsCode.value = ''
  loading.value = false
}

function handleClose() {
  stopPoll()
  emit('close')
}

function handleSuccess() {
  stopPoll()
  emit('success')
}

async function startFlow() {
  stopPoll()
  loading.value = true
  try {
    sessionId.value = ''
    payload.value = {}
    try {
      const result = await startDriveAccountAuth(props.accountId)
      if (String(result?.runtime_status || '').trim().toLowerCase() === 'active') {
        toast.success('账号已登录，无需二次认证')
        handleSuccess()
        return
      }
      payload.value = {
        ...payload.value,
        drive_type: driveType.value || String(result?.drive_type || ''),
        status: String(result?.runtime_status || ''),
        message: String(result?.last_error || '当前账号未完成登录'),
      }
      if (canStartQrcode.value) {
        method.value = 'qrcode'
        toast.info('当前账号可继续使用扫码登录')
        return
      }
      throw new Error(String(result?.last_error || '当前账号未完成登录'))
    } catch (e) {
      const challenge = parseAuthChallenge(e)
      if (!challenge) {
        toast.error(extractErrorMessage(e, '发起认证失败'))
        return
      }
      applyChallenge(challenge)
    }
  } finally {
    loading.value = false
  }
}

async function startQrcodeFlow() {
  stopPoll()
  loading.value = true
  try {
    const resp = await startDriveAccountQrcodeAuth(props.accountId)
    method.value = 'qrcode'
    sessionId.value = String(resp.session_id || '')
    payload.value = { ...(resp.payload || {}), drive_type: String(resp.drive_type || driveType.value || '') }
    startAutoPoll()
  } catch (e) {
    toast.error(extractErrorMessage(e, '发起扫码失败'))
  } finally {
    loading.value = false
  }
}

function applyChallenge(challenge: DriveAccountAuthChallenge) {
  method.value = challenge.method
  sessionId.value = challenge.session_id
  payload.value = { ...(challenge.payload || {}), drive_type: challenge.drive_type }
  captchaCode.value = ''
  smsCode.value = ''
  if (method.value === 'qrcode') startAutoPoll()
}

async function submitCaptcha() {
  if (!sessionId.value) return
  captchaSubmitting.value = true
  try {
    await submitDriveAccountCaptcha(sessionId.value, captchaCode.value.trim())
    toast.success('验证码已验证，账号已登录')
    handleSuccess()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      applyChallenge(challenge)
      return
    }
    toast.error(extractErrorMessage(e, '验证码校验失败'))
  } finally {
    captchaSubmitting.value = false
  }
}

async function handleSendSms() {
  if (!sessionId.value) return
  smsSending.value = true
  try {
    await sendDriveAccountSms(sessionId.value)
    toast.success('短信验证码已发送')
  } catch (e) {
    toast.error(extractErrorMessage(e, '发送短信失败'))
  } finally {
    smsSending.value = false
  }
}

async function submitSms() {
  if (!sessionId.value) return
  smsSubmitting.value = true
  try {
    await submitDriveAccountSms(sessionId.value, smsCode.value.trim())
    toast.success('短信已验证，账号已登录')
    handleSuccess()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      applyChallenge(challenge)
      return
    }
    toast.error(extractErrorMessage(e, '短信校验失败'))
  } finally {
    smsSubmitting.value = false
  }
}

async function pollQrcodeOnce() {
  if (!sessionId.value) return
  qrcodePolling.value = true
  try {
    await pollDriveAccountQrcodeAuth(sessionId.value)
    toast.success(qrcodeSuccessMessage.value)
    handleSuccess()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      payload.value = { ...payload.value, ...(challenge.payload || {}), drive_type: challenge.drive_type }
      const status = String(payload.value.status || '')
      if (status === 'EXPIRED' || status === 'CANCELED') stopPoll()
      return
    }
    toast.error(extractErrorMessage(e, '扫码状态查询失败'))
  } finally {
    qrcodePolling.value = false
  }
}

function bootstrap() {
  resetState()
  if (props.initialChallenge) {
    method.value = props.initialChallenge.method
    sessionId.value = props.initialChallenge.session_id
    payload.value = {
      ...(props.initialChallenge.payload || {}),
      drive_type: props.initialChallenge.drive_type || props.driveType || '',
    }
    if (sessionId.value && !props.initialChallenge.payload) {
      loading.value = true
      fetchDriveAccountAuthSession(sessionId.value)
        .then((data) => {
          payload.value = { ...(data?.payload || {}), drive_type: data?.drive_type || props.driveType || '' }
          if (method.value === 'qrcode') startAutoPoll()
        })
        .catch((e) => toast.error(extractErrorMessage(e, '会话获取失败')))
        .finally(() => {
          loading.value = false
        })
      return
    }
    if (method.value === 'qrcode') startAutoPoll()
    return
  }
  if (props.startQrcode && canStartQrcode.value) {
    method.value = 'qrcode'
    startQrcodeFlow()
    return
  }
  startFlow()
}

watch(
  () => props.open,
  (visible) => {
    if (visible) bootstrap()
    else stopPoll()
  },
  { immediate: true },
)

onBeforeUnmount(stopPoll)
</script>

<template>
  <Teleport to="body">
    <Transition name="auth-fade">
      <div v-if="open" class="fixed inset-0 z-[60] flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50" @click="handleClose" />
        <div class="relative z-10 flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-[hsl(var(--card))] shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
            <div class="flex items-center gap-2">
              <ShieldCheck class="h-5 w-5 text-[hsl(var(--primary))]" />
              <div>
                <h3 class="text-base font-semibold text-[hsl(var(--foreground))]">账号二次认证</h3>
                <p v-if="accountName" class="text-xs text-[hsl(var(--muted-foreground))]">{{ accountName }}</p>
              </div>
            </div>
            <button
              class="rounded-md p-1 transition-colors hover:bg-[hsl(var(--muted))]"
              @click="handleClose"
            >
              <X class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-5" :class="{ 'opacity-60 pointer-events-none': loading }">
            <!-- Captcha -->
            <template v-if="method === 'captcha'">
              <div class="mb-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
                该账号登录需要输入图形验证码。
              </div>
              <div class="flex flex-col items-center gap-4">
                <img
                  v-if="payload.image_base64"
                  class="h-[120px] w-[240px] rounded-md border border-[hsl(var(--border))] object-contain"
                  :src="`data:image/png;base64,${payload.image_base64}`"
                  alt="captcha"
                />
                <div v-else class="flex h-[120px] w-[240px] items-center justify-center rounded-md border border-dashed border-[hsl(var(--border))] text-xs text-[hsl(var(--muted-foreground))]">
                  未获取到验证码图片，可点击“重新检测”。
                </div>
                <Input v-model="captchaCode" placeholder="输入验证码" class="w-full" />
                <Button class="w-full" :disabled="captchaSubmitting || !captchaCode.trim()" @click="submitCaptcha">
                  {{ captchaSubmitting ? '提交中...' : '提交验证码' }}
                </Button>
              </div>
            </template>

            <!-- SMS -->
            <template v-else-if="method === 'sms'">
              <div class="mb-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
                该账号登录需要短信验证。
              </div>
              <div class="space-y-3">
                <div class="flex items-center justify-between rounded-md border border-[hsl(var(--border))] px-3 py-2 text-sm">
                  <span class="text-[hsl(var(--muted-foreground))]">手机号</span>
                  <span class="font-medium text-[hsl(var(--foreground))]">{{ payload.mobile || '-' }}</span>
                </div>
                <div v-if="payload.show_name" class="flex items-center justify-between rounded-md border border-[hsl(var(--border))] px-3 py-2 text-sm">
                  <span class="text-[hsl(var(--muted-foreground))]">账号</span>
                  <span class="font-medium text-[hsl(var(--foreground))]">{{ payload.show_name }}</span>
                </div>
                <Button variant="outline" class="w-full" :disabled="smsSending" @click="handleSendSms">
                  {{ smsSending ? '发送中...' : '发送验证码' }}
                </Button>
                <Input v-model="smsCode" placeholder="输入短信验证码" class="w-full" />
                <Button class="w-full" :disabled="smsSubmitting || !smsCode.trim()" @click="submitSms">
                  {{ smsSubmitting ? '提交中...' : '提交短信验证码' }}
                </Button>
              </div>
            </template>

            <!-- QRCode -->
            <template v-else>
              <div class="mb-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
                {{ qrcodeAlertTitle }}
              </div>
              <div class="flex flex-col items-center gap-4">
                <img
                  v-if="qrcodeImageSrc"
                  class="h-[200px] w-[200px] rounded-md border border-[hsl(var(--border))] object-contain"
                  :src="qrcodeImageSrc"
                  alt="qrcode"
                />
                <div v-else class="flex h-[200px] w-[200px] items-center justify-center rounded-md border border-dashed border-[hsl(var(--border))] text-center text-xs text-[hsl(var(--muted-foreground))]">
                  未获取到二维码，可点击下方按钮重新发起。
                </div>
                <div class="w-full space-y-2 text-sm">
                  <div class="flex items-center justify-between">
                    <span class="text-[hsl(var(--muted-foreground))]">状态</span>
                    <span class="font-medium text-[hsl(var(--foreground))]">{{ payload.message || payload.status || '等待扫码' }}</span>
                  </div>
                </div>
                <div class="flex w-full gap-2">
                  <Button variant="outline" class="flex-1" :disabled="qrcodePolling" @click="pollQrcodeOnce">
                    <RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': qrcodePolling }" />
                    刷新状态
                  </Button>
                  <Button v-if="canStartQrcode" class="flex-1" @click="startQrcodeFlow">
                    <QrCode class="mr-1 h-4 w-4" />
                    {{ qrcodeButtonText }}
                  </Button>
                </div>
                <div v-if="isTvQrcodeDrive" class="w-full rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                  当前仅保存 TV 凭据，账号实际运行仍以 Cookie 为准。
                </div>
              </div>
            </template>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-4">
            <Button variant="ghost" size="sm" @click="startFlow">
              <RefreshCw class="mr-1 h-4 w-4" />
              重新检测
            </Button>
            <div class="flex items-center gap-2">
              <Button
                v-if="method !== 'qrcode' && canStartQrcode"
                variant="outline"
                size="sm"
                @click="startQrcodeFlow"
              >
                <QrCode class="mr-1 h-4 w-4" />
                {{ qrcodeButtonText }}
              </Button>
              <Button variant="outline" size="sm" @click="handleClose">关闭</Button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.auth-fade-enter-active,
.auth-fade-leave-active {
  transition: opacity 0.2s ease;
}
.auth-fade-enter-from,
.auth-fade-leave-to {
  opacity: 0;
}
</style>
