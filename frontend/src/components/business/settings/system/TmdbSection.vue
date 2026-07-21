<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { SettingCard } from '@/components/ui/setting-card'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Save, Loader2, Clapperboard } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useTMDBConfigQuery } from '@/hooks/queries/settings'
import { usePatchTMDBConfigMutation } from '@/hooks/mutations/settings'

const { toast } = useToast()

const { data: tmdbData } = useTMDBConfigQuery()
const mutation = usePatchTMDBConfigMutation()

const form = reactive({
  apiKeyInput: '',
  language: 'zh-CN',
  posterLanguage: 'zh-CN',
  enableGuessitFallbackRename: true,
  tvRenameTemplate: '{title}.S{season}E{episode}{ext}',
  movieRenameTemplate: '{title_dot}.{year}{ext}',
})

watch(tmdbData, (d) => {
  if (!d) return
  form.language = d.language || 'zh-CN'
  form.posterLanguage = d.poster_language || 'zh-CN'
  form.enableGuessitFallbackRename = !d.disable_guessit_tmdb_fallback_rename
  form.tvRenameTemplate = d.guessit_tmdb_tv_rename_template || '{title}.S{season}E{episode}{ext}'
  form.movieRenameTemplate = d.guessit_tmdb_movie_rename_template || '{title_dot}.{year}{ext}'
}, { immediate: true })

const LANGS = [
  { value: 'zh-CN', label: '中文 (zh-CN)' },
  { value: 'en-US', label: 'English (en-US)' },
  { value: 'ja-JP', label: '日本語 (ja-JP)' },
  { value: 'ko-KR', label: '한국어 (ko-KR)' },
]

function save() {
  const payload: Parameters<typeof mutation.mutate>[0] = {
    language: form.language.trim() || null,
    poster_language: form.posterLanguage.trim() || null,
    disable_guessit_tmdb_fallback_rename: !form.enableGuessitFallbackRename,
    guessit_tmdb_tv_rename_template: form.tvRenameTemplate.trim() || null,
    guessit_tmdb_movie_rename_template: form.movieRenameTemplate.trim() || null,
  }
  const apiKey = form.apiKeyInput.trim()
  if (apiKey) (payload as any).api_key = apiKey
  mutation.mutate(payload, {
    onSuccess: () => { form.apiKeyInput = ''; toast.success('TMDB 配置已保存') },
    onError: (err: any) => toast.error(err?.response?.data?.message || '保存失败'),
  })
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <SettingCard title="🎬 TMDB 配置" description="用于影视元数据刮削、海报与重命名" :icon="Clapperboard">
      <template #actions>
        <Badge v-if="tmdbData?.has_api_key" variant="outline" class="text-[10px]">API Key 已设置</Badge>
        <Badge v-else variant="destructive" class="text-[10px]">未设置</Badge>
      </template>

      <div data-tour="tmdb-api-key">
        <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">API Key</label>
        <Input v-model="form.apiKeyInput" type="password" :placeholder="tmdbData?.has_api_key ? '已设置（留空不修改）' : '输入 TMDB API Key'" />
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">语言</label>
          <select v-model="form.language" class="h-10 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]">
            <option v-for="l in LANGS" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">海报语言</label>
          <select v-model="form.posterLanguage" class="h-10 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm text-[hsl(var(--foreground))] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]">
            <option v-for="l in LANGS" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
        </div>
      </div>

      <div class="flex items-start justify-between gap-4 rounded-lg bg-[hsl(var(--muted))]/40 p-3">
        <div class="min-w-0">
          <div class="text-sm font-medium text-[hsl(var(--foreground))]">启用 Guessit 兜底重命名</div>
          <p class="mt-0.5 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">当 TMDB 无法命中时，使用 Guessit 解析结果按下方模板兜底重命名。</p>
        </div>
        <ToggleSwitch v-model="form.enableGuessitFallbackRename" />
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">剧集重命名模板</label>
          <Input v-model="form.tvRenameTemplate" placeholder="{title}.S{season}E{episode}{ext}" />
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground))]">电影重命名模板</label>
          <Input v-model="form.movieRenameTemplate" placeholder="{title_dot}.{year}{ext}" />
        </div>
      </div>

      <template #footer>
        <Button :disabled="mutation.isPending.value" @click="save">
          <Loader2 v-if="mutation.isPending.value" class="mr-2 h-4 w-4 animate-spin" />
          <Save v-else class="mr-2 h-4 w-4" />
          保存 TMDB 配置
        </Button>
      </template>
    </SettingCard>
  </div>
</template>
