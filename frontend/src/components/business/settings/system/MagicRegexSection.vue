<script setup lang="ts">
import { reactive, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Plus, Pencil, Trash2, TestTube2, Loader2, RefreshCw } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { useMagicRegexRulesQuery } from '@/hooks/queries/settings'
import { useUpsertMagicRegexRuleMutation, useDeleteMagicRegexRuleMutation } from '@/hooks/mutations/settings'
import type { MagicRegexRuleSetting } from '@/types/magicRegex'

const { toast } = useToast()

const { data: regexData, isLoading, refetch } = useMagicRegexRulesQuery()
const upsertMutation = useUpsertMagicRegexRuleMutation()
const deleteMutation = useDeleteMagicRegexRuleMutation()

const rules = computed(() => regexData.value?.rules || [])
const builtinRules = computed(() => rules.value.filter((r) => r.built_in))
const customRules = computed(() => rules.value.filter((r) => !r.built_in))

const ruleDialog = reactive({
  visible: false,
  isEdit: false,
  form: { key: '$', label: '' as string, enabled: true, pattern: '', replace: '' },
})
const testPanel = reactive({ input: '', result: '' })

function openCreateRule() {
  ruleDialog.visible = true
  ruleDialog.isEdit = false
  ruleDialog.form = { key: '$', label: '', enabled: true, pattern: '', replace: '' }
  testPanel.input = ''
  testPanel.result = ''
}
function openEditRule(rule: MagicRegexRuleSetting) {
  ruleDialog.visible = true
  ruleDialog.isEdit = true
  ruleDialog.form = { key: rule.key, label: rule.label || '', enabled: rule.enabled, pattern: rule.pattern, replace: rule.replace }
  testPanel.input = ''
  testPanel.result = ''
}
function submitRule() {
  const key = ruleDialog.form.key.trim()
  if (!key.startsWith('$') || key.includes(' ') || key.length > 64) {
    toast.error('key 必须以 $ 开头，不含空格，最长 64 字符')
    return
  }
  if (!ruleDialog.isEdit && !ruleDialog.form.pattern.trim()) {
    toast.error('新增规则 pattern 不能为空')
    return
  }
  upsertMutation.mutate(
    { key, payload: { label: ruleDialog.form.label.trim() || null, enabled: ruleDialog.form.enabled, pattern: ruleDialog.form.pattern.trim() || null, replace: ruleDialog.form.replace } },
    {
      onSuccess: () => { ruleDialog.visible = false; toast.success('规则已保存') },
      onError: (err: any) => toast.error(err?.response?.data?.message || '保存失败'),
    },
  )
}
function removeRule(rule: MagicRegexRuleSetting) {
  if (!confirm(rule.built_in ? `确认恢复 ${rule.key} 为默认？` : `确认删除 ${rule.key}？`)) return
  deleteMutation.mutate(rule.key, {
    onSuccess: () => toast.success('已删除'),
    onError: (err: any) => toast.error(err?.response?.data?.message || '删除失败'),
  })
}
function testRegex() {
  if (!testPanel.input.trim()) { testPanel.result = ''; return }
  try {
    const re = new RegExp(ruleDialog.form.pattern)
    testPanel.result = testPanel.input.replace(re, ruleDialog.form.replace)
  } catch (e: any) {
    testPanel.result = `[正则错误] ${e.message}`
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-base font-semibold text-[hsl(var(--foreground))]">✨ 重命名规则</h2>
        <p class="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">
          规则 key 需以 <code class="rounded bg-[hsl(var(--muted))] px-1">$</code> 开头，在追剧任务中将 pattern 设为该 key 即可使用。
        </p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" @click="refetch()"><RefreshCw class="h-4 w-4" /></Button>
        <Button size="sm" @click="openCreateRule"><Plus class="mr-1 h-4 w-4" /> 新增规则</Button>
      </div>
    </div>

    <div v-if="isLoading" class="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-4 w-4 animate-spin" /> 加载中...
    </div>

    <template v-else>
      <!-- Built-in -->
      <div v-if="builtinRules.length" class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <h4 class="mb-3 text-sm font-semibold text-[hsl(var(--foreground))]">内置规则</h4>
        <div class="overflow-x-auto overscroll-x-contain rounded-lg border border-[hsl(var(--border))]">
          <table class="w-full min-w-[720px] text-sm">
            <thead class="bg-[hsl(var(--muted))]/60">
              <tr>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Key</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">名称</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">状态</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Pattern</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Replace</th>
                <th class="px-3 py-2 text-right font-medium text-[hsl(var(--muted-foreground))]">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in builtinRules" :key="rule.key" class="border-t border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]/30">
                <td class="px-3 py-2 font-mono text-xs">{{ rule.key }}</td>
                <td class="px-3 py-2">{{ rule.label || '-' }}</td>
                <td class="px-3 py-2">
                  <Badge v-if="rule.overridden" variant="outline" class="text-[10px]">已覆盖</Badge>
                  <Badge v-else variant="secondary" class="text-[10px]">默认</Badge>
                </td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="rule.pattern">{{ rule.pattern }}</td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="rule.replace">{{ rule.replace }}</td>
                <td class="px-3 py-2 text-right">
                  <div class="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" class="h-7 w-7 p-0" @click="openEditRule(rule)"><Pencil class="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="sm" class="h-7 w-7 p-0" :disabled="!rule.overridden" @click="removeRule(rule)"><RefreshCw class="h-3.5 w-3.5" /></Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Custom -->
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-sm">
        <h4 class="mb-3 text-sm font-semibold text-[hsl(var(--foreground))]">自定义规则</h4>
        <div v-if="customRules.length" class="overflow-hidden rounded-lg border border-[hsl(var(--border))]">
          <table class="w-full text-sm">
            <thead class="bg-[hsl(var(--muted))]/60">
              <tr>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Key</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">名称</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">启用</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Pattern</th>
                <th class="px-3 py-2 text-left font-medium text-[hsl(var(--muted-foreground))]">Replace</th>
                <th class="px-3 py-2 text-right font-medium text-[hsl(var(--muted-foreground))]">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in customRules" :key="rule.key" class="border-t border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]/30">
                <td class="px-3 py-2 font-mono text-xs">{{ rule.key }}</td>
                <td class="px-3 py-2">{{ rule.label || '-' }}</td>
                <td class="px-3 py-2">
                  <Badge :variant="rule.enabled ? 'default' : 'secondary'" class="text-[10px]">{{ rule.enabled ? '启用' : '禁用' }}</Badge>
                </td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="rule.pattern">{{ rule.pattern }}</td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="rule.replace">{{ rule.replace }}</td>
                <td class="px-3 py-2 text-right">
                  <div class="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" class="h-7 w-7 p-0" @click="openEditRule(rule)"><Pencil class="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-red-500 hover:text-red-600" @click="removeRule(rule)"><Trash2 class="h-3.5 w-3.5" /></Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="py-6 text-center text-sm text-[hsl(var(--muted-foreground))]">暂无自定义规则</div>
      </div>
    </template>

    <!-- Rule Dialog -->
    <div v-if="ruleDialog.visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="ruleDialog.visible = false">
      <div class="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-2xl">
        <h3 class="mb-4 text-base font-semibold text-[hsl(var(--foreground))]">{{ ruleDialog.isEdit ? '编辑规则' : '新增规则' }}</h3>
        <div class="space-y-3">
          <div>
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">Key</label>
            <Input v-model="ruleDialog.form.key" :disabled="ruleDialog.isEdit" placeholder="$MY_RULE" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">名称（可选）</label>
            <Input v-model="ruleDialog.form.label" placeholder="规则描述" />
          </div>
          <div class="flex items-center justify-between rounded-md bg-[hsl(var(--muted))]/40 px-3 py-2">
            <span class="text-sm font-medium text-[hsl(var(--foreground))]">启用</span>
            <ToggleSwitch v-model="ruleDialog.form.enabled" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">Pattern (正则)</label>
            <Input v-model="ruleDialog.form.pattern" placeholder="正则表达式" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">Replace (替换)</label>
            <Input v-model="ruleDialog.form.replace" placeholder="替换模板" />
          </div>
          <div class="mt-3 border-t border-[hsl(var(--border))] pt-3">
            <label class="mb-1 block text-sm font-medium text-[hsl(var(--muted-foreground))]">测试</label>
            <div class="flex gap-2">
              <Input v-model="testPanel.input" placeholder="输入文件名..." class="flex-1" />
              <Button variant="outline" size="sm" @click="testRegex"><TestTube2 class="h-4 w-4" /></Button>
            </div>
            <div v-if="testPanel.result" class="mt-2 rounded bg-[hsl(var(--muted))] p-2 font-mono text-sm text-[hsl(var(--foreground))]">{{ testPanel.result }}</div>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <Button variant="outline" @click="ruleDialog.visible = false">取消</Button>
          <Button :disabled="upsertMutation.isPending.value" @click="submitRule">
            <Loader2 v-if="upsertMutation.isPending.value" class="mr-2 h-4 w-4 animate-spin" />
            保存
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
