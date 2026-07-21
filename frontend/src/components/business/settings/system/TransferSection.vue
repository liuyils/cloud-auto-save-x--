<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Button } from '@/components/ui/button'
import { SettingCard } from '@/components/ui/setting-card'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Save, Loader2, ArrowLeftRight } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useSaveRuleConfigQuery, useDl302ConfigQuery } from '@/hooks/queries/settings'
import { patchSaveRuleConfig } from '@/api/systemSettings'
import { patchDL302Config } from '@/api/dl302'

const { toast } = useToast()
const queryClient = useQueryClient()

const { data: saveRuleData, isLoading: saveRuleLoading } = useSaveRuleConfigQuery()
const { data: dl302Data, isLoading: dl302Loading } = useDl302ConfigQuery()
const saving = ref(false)
const loading = computed(() => saveRuleLoading.value || dl302Loading.value)

const form = reactive({
  skipTransferred: false,
  copyDownloadMode: '0' as '0' | '1',
})

watch(saveRuleData, (d) => {
  if (d) form.skipTransferred = Boolean(d.enable_skip_transferred_history)
}, { immediate: true })
watch(dl302Data, (d) => {
  if (d) form.copyDownloadMode = d.copy_download_mode === '1' ? '1' : '0'
}, { immediate: true })

async function save() {
  saving.value = true
  try {
    await Promise.all([
      patchSaveRuleConfig({ enable_skip_transferred_history: form.skipTransferred }),
      patchDL302Config({ copy_download_mode: form.copyDownloadMode }),
    ])
    queryClient.invalidateQueries({ queryKey: ['system-settings', 'save-rules'] })
    queryClient.invalidateQueries({ queryKey: ['dl302', 'config'] })
    toast.success('转存设置已保存')
  } catch (err: any) {
    toast.error(err?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <SettingCard title="🔀 转存设置" description="转存 / CAS 复制相关的全局行为配置" :icon="ArrowLeftRight">
      <div v-if="loading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
      </div>

      <template v-else>
        <!-- 跳过已转存历史 -->
        <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
          <div class="min-w-0">
            <div class="text-sm font-medium text-[hsl(var(--foreground))]">跳过已转存历史</div>
            <p class="mt-0.5 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">开启后转存时会跳过历史记录中已成功转存过的文件，避免重复转存。</p>
          </div>
          <ToggleSwitch v-model="form.skipTransferred" />
        </div>

        <!-- 下载模式 -->
        <div class="rounded-lg bg-[hsl(var(--muted))]/40 p-3">
          <div class="mb-2 text-sm font-medium text-[hsl(var(--foreground))]">下载模式</div>
          <div class="flex gap-2">
            <button
              class="flex-1 rounded-md border px-3 py-2 text-sm transition-colors"
              :class="form.copyDownloadMode === '0' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'"
              @click="form.copyDownloadMode = '0'"
            >
              <div class="font-medium">流式</div>
              <div class="mt-0.5 text-[11px] opacity-80">边下边传（0）</div>
            </button>
            <button
              class="flex-1 rounded-md border px-3 py-2 text-sm transition-colors"
              :class="form.copyDownloadMode === '1' ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--primary))]/40'"
              @click="form.copyDownloadMode = '1'"
            >
              <div class="font-medium">下载</div>
              <div class="mt-0.5 text-[11px] opacity-80">先下载再上传（1）</div>
            </button>
          </div>
          <p class="mt-2 text-xs text-[hsl(var(--muted-foreground))]">CAS 复制任务的下载方式。</p>
        </div>
      </template>

      <template #footer>
        <Button :disabled="saving || loading" @click="save">
          <Loader2 v-if="saving" class="mr-2 h-4 w-4 animate-spin" />
          <Save v-else class="mr-2 h-4 w-4" />
          保存转存设置
        </Button>
      </template>
    </SettingCard>
  </div>
</template>
