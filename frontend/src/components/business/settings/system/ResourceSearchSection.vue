<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SettingCard } from '@/components/ui/setting-card'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Save, Loader2, RefreshCw, Search } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useResourceSearchSourcesQuery } from '@/hooks/queries/settings'
import { usePatchResourceSearchSourceMutation } from '@/hooks/mutations/settings'
import type { ResourceSearchSourceKey } from '@/types/resourceSearch'

const { toast } = useToast()

const { data: rsData, isLoading, refetch } = useResourceSearchSourcesQuery()
const mutation = usePatchResourceSearchSourceMutation()

const form = reactive({
  net: { enabled: true },
  cloudsaver: { enabled: false, server: '', username: '', passwordInput: '' },
  pansou: { enabled: false, server: '' },
})

watch(rsData, (d) => {
  if (!d?.sources) return
  const net = d.sources.find((s) => s.key === 'net')
  if (net) form.net.enabled = net.enabled
  const cs = d.sources.find((s) => s.key === 'cloudsaver')
  if (cs) { form.cloudsaver.enabled = cs.enabled; form.cloudsaver.server = cs.server || ''; form.cloudsaver.username = cs.username || '' }
  const ps = d.sources.find((s) => s.key === 'pansou')
  if (ps) { form.pansou.enabled = ps.enabled; form.pansou.server = ps.server || '' }
}, { immediate: true })

function saveSource(key: ResourceSearchSourceKey) {
  let payload: any = {}
  if (key === 'net') payload = { enabled: form.net.enabled }
  else if (key === 'pansou') payload = { enabled: form.pansou.enabled, server: form.pansou.server.trim() || null }
  else {
    payload = { enabled: form.cloudsaver.enabled, server: form.cloudsaver.server.trim() || null, username: form.cloudsaver.username.trim() || null }
    const pw = form.cloudsaver.passwordInput.trim()
    if (pw) payload.password = pw
  }
  mutation.mutate({ key, payload }, {
    onSuccess: () => { form.cloudsaver.passwordInput = ''; toast.success('已保存') },
    onError: (err: any) => toast.error(err?.response?.data?.message || '保存失败'),
  })
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-base font-semibold text-[hsl(var(--foreground))]">🔎 资源搜索</h2>
        <p class="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">配置资源搜索来源与服务端点</p>
      </div>
      <Button variant="outline" size="sm" @click="refetch()">
        <RefreshCw class="h-4 w-4" />
      </Button>
    </div>

    <div v-if="isLoading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
    </div>

    <template v-else>
      <!-- Net -->
      <SettingCard title="网络搜索 (net)" description="内置聚合网络资源搜索" :icon="Search">
        <template #actions>
          <ToggleSwitch v-model="form.net.enabled" />
        </template>
        <template #footer>
          <Button size="sm" :disabled="mutation.isPending.value" @click="saveSource('net')">
            <Save class="mr-1.5 h-3.5 w-3.5" /> 保存
          </Button>
        </template>
      </SettingCard>

      <!-- CloudSaver -->
      <SettingCard title="CloudSaver" description="对接自建 CloudSaver 服务">
        <template #actions>
          <ToggleSwitch v-model="form.cloudsaver.enabled" />
        </template>
        <div>
          <label class="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">服务器地址</label>
          <Input v-model="form.cloudsaver.server" placeholder="http://localhost:port" />
        </div>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label class="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">用户名</label>
            <Input v-model="form.cloudsaver.username" placeholder="用户名" />
          </div>
          <div>
            <label class="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">密码（留空不修改）</label>
            <Input v-model="form.cloudsaver.passwordInput" type="password" placeholder="输入新密码" />
          </div>
        </div>
        <template #footer>
          <Button size="sm" :disabled="mutation.isPending.value" @click="saveSource('cloudsaver')">
            <Save class="mr-1.5 h-3.5 w-3.5" /> 保存
          </Button>
        </template>
      </SettingCard>

      <!-- Pansou -->
      <SettingCard title="盘搜 (pansou)" description="对接 pansou 搜索服务">
        <template #actions>
          <ToggleSwitch v-model="form.pansou.enabled" />
        </template>
        <div>
          <label class="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">服务器地址</label>
          <Input v-model="form.pansou.server" placeholder="http://..." />
        </div>
        <template #footer>
          <Button size="sm" :disabled="mutation.isPending.value" @click="saveSource('pansou')">
            <Save class="mr-1.5 h-3.5 w-3.5" /> 保存
          </Button>
        </template>
      </SettingCard>
    </template>
  </div>
</template>
