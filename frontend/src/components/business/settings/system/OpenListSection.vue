<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { SettingCard } from '@/components/ui/setting-card'
import { Save, Loader2, RefreshCw, FolderTree } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useOpenListConfigQuery } from '@/hooks/queries/settings'
import { usePatchOpenListConfigMutation } from '@/hooks/mutations/settings'

const { toast } = useToast()

const { data: olData, isLoading, refetch } = useOpenListConfigQuery()
const mutation = usePatchOpenListConfigMutation()

const form = reactive({ url: '', tokenInput: '' })

watch(olData, (d) => {
  if (d) form.url = d.url || ''
}, { immediate: true })

function save() {
  const payload: any = { url: form.url.trim() || null }
  const token = form.tokenInput.trim()
  if (token) payload.token = token
  mutation.mutate(payload, {
    onSuccess: () => { form.tokenInput = ''; toast.success('OpenList 配置已保存') },
    onError: (err: any) => toast.error(err?.response?.data?.message || '保存失败'),
  })
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <SettingCard title="🗂️ OpenList 配置" description="配置 OpenList 服务地址和认证信息" :icon="FolderTree">
      <template #actions>
        <Button variant="outline" size="sm" @click="refetch()">
          <RefreshCw class="h-4 w-4" />
        </Button>
      </template>

      <div v-if="isLoading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
      </div>

      <template v-else>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">OpenList URL</label>
          <Input v-model="form.url" placeholder="http://localhost:5245" />
        </div>
        <div>
          <label class="mb-1.5 flex items-center gap-2 text-sm font-medium text-[hsl(var(--foreground))]">
            Token
            <Badge v-if="olData?.has_token" variant="outline" class="text-[10px]">已设置</Badge>
          </label>
          <Input v-model="form.tokenInput" type="password" :placeholder="olData?.has_token ? '已设置（留空不修改）' : '输入 Token'" />
        </div>
      </template>

      <template #footer>
        <Button :disabled="mutation.isPending.value" @click="save">
          <Loader2 v-if="mutation.isPending.value" class="mr-2 h-4 w-4 animate-spin" />
          <Save v-else class="mr-2 h-4 w-4" />
          保存 OpenList 配置
        </Button>
      </template>
    </SettingCard>
  </div>
</template>
