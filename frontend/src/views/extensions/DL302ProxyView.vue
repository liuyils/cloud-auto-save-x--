<script setup lang="ts">
import { ElMessage } from 'element-plus'

import { fetchDL302Config, fetchDL302SupportedDrivers, generateDL302Strm, patchDL302Config } from '@/api/dl302'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { DL302Config, DL302SupportedDriver, DL302StrmGenerateResult } from '@/types/dl302'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const loading = ref(false)
const activeTab = ref('drivers')
const drivers = ref<DL302SupportedDriver[]>([])

const settings = reactive({
  proxy_url: '',
  proxy_path_offset: -1,
  intranet_cidrs_text: '',
  strm_enabled: false,
  strm_mode: 'auto' as 'auto' | 'independent',
  strm_root_dir: '/strm',
  strm_prefix_url: '',
  savingProxy: false,
  generatingStrm: false,
})

const strmSummary = reactive({
  enabled: false,
  mode: 'auto' as 'auto' | 'independent',
  prefix_ready: false,
  root_exists: false,
  source_account_count: 0,
  path_ready_account_count: 0,
  path_missing_account_count: 0,
  generated_file_count: 0,
  generated_dir_count: 0,
})

function applyConfig(data: DL302Config) {
  settings.proxy_url = String(data.proxy_url || '')
  settings.proxy_path_offset = Number.isFinite(Number(data.proxy_path_offset)) ? Number(data.proxy_path_offset) : -1
  settings.intranet_cidrs_text = Array.isArray(data.intranet_cidrs) ? data.intranet_cidrs.filter(Boolean).join('\n') : ''
  settings.strm_enabled = Boolean(data.strm_enabled)
  settings.strm_mode = data.strm_mode === 'independent' ? 'independent' : 'auto'
  settings.strm_root_dir = String(data.strm_root_dir || '/strm')
  settings.strm_prefix_url = String(data.strm_prefix_url || '')
  strmSummary.enabled = Boolean(data.strm_summary?.enabled)
  strmSummary.mode = data.strm_summary?.mode === 'independent' ? 'independent' : 'auto'
  strmSummary.prefix_ready = Boolean(data.strm_summary?.prefix_ready)
  strmSummary.root_exists = Boolean(data.strm_summary?.root_exists)
  strmSummary.source_account_count = Number(data.strm_summary?.source_account_count || 0)
  strmSummary.path_ready_account_count = Number(data.strm_summary?.path_ready_account_count || 0)
  strmSummary.path_missing_account_count = Number(data.strm_summary?.path_missing_account_count || 0)
  strmSummary.generated_file_count = Number(data.strm_summary?.generated_file_count || 0)
  strmSummary.generated_dir_count = Number(data.strm_summary?.generated_dir_count || 0)
}

async function loadPage() {
  loading.value = true
  try {
    const [driverData, configData] = await Promise.all([fetchDL302SupportedDrivers(), fetchDL302Config()])
    drivers.value = driverData
    applyConfig(configData)
  } finally {
    loading.value = false
  }
}

function parseCIDRText(text: string): string[] | null {
  const parts = String(text || '')
    .replaceAll('\r\n', '\n')
    .replaceAll('\n', ',')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
  if (!parts.length) return null
  return Array.from(new Set(parts))
}

async function saveProxySettings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const data = await patchDL302Config({
      proxy_url: settings.proxy_url ? String(settings.proxy_url).trim() : null,
      proxy_path_offset: Number(settings.proxy_path_offset),
      intranet_cidrs: parseCIDRText(settings.intranet_cidrs_text),
      strm_enabled: Boolean(settings.strm_enabled),
      strm_mode: settings.strm_mode,
      strm_root_dir: String(settings.strm_root_dir || '').trim() || '/strm',
      strm_prefix_url: settings.strm_prefix_url ? String(settings.strm_prefix_url).trim() : null,
    })
    applyConfig(data)
    ElMessage.success('反代设置已保存，已触发 dl302 重载')
  } finally {
    settings.savingProxy = false
  }
}

async function saveStrmSettings() {
  if (!canWrite.value) return
  settings.savingProxy = true
  try {
    const data = await patchDL302Config({
      strm_enabled: Boolean(settings.strm_enabled),
      strm_mode: settings.strm_mode,
      strm_root_dir: String(settings.strm_root_dir || '').trim() || '/strm',
      strm_prefix_url: settings.strm_prefix_url ? String(settings.strm_prefix_url).trim() : null,
    })
    applyConfig(data)
    ElMessage.success('STRM 设置已保存')
  } finally {
    settings.savingProxy = false
  }
}

function buildGenerateMessage(result: DL302StrmGenerateResult) {
  const parts = [
    `模式：${result.mode === 'independent' ? '独立模式' : '自动模式'}`,
    `文件：${result.generated_files}`,
    `目录：${result.generated_dirs}`,
    `跳过账号：${result.skipped_accounts}`,
  ]
  return parts.join('，')
}

async function generateStrm() {
  if (!canWrite.value) return
  settings.generatingStrm = true
  try {
    const result = await generateDL302Strm({
      mode: settings.strm_mode,
      persist_prefix_if_empty: true,
    })
    const latestConfig = await fetchDL302Config()
    applyConfig(latestConfig)
    ElMessage.success(result.message ? `${result.message}，${buildGenerateMessage(result)}` : buildGenerateMessage(result))
  } finally {
    settings.generatingStrm = false
  }
}

onMounted(loadPage)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>302代理</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadPage">刷新页面</el-button>
      </div>
    </div>

    <section class="glass-panel dashboard-section">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="支持驱动" name="drivers">
          <div class="tab-copy">
            展示当前 dl302 支持的账号驱动，以及各驱动已配置的账号情况。STRM 生成会复用账号管理中各账号的 `302_path`（302 代理基础路径）作为过滤目录，请确保已填写。
            302 直连需要保留端口：5115/9000。5115 为统一代理端口，9000 为独立端口；不建议将 5115 直接暴露到公网，推荐使用反代服务代理 `/dl`。
          </div>
          <el-table :data="drivers" border>
            <el-table-column prop="drive_name" label="驱动名称" min-width="180" />
            <el-table-column prop="code" label="驱动编码" min-width="140" />
            <el-table-column prop="account_count" label="账号数" width="100" />
            <el-table-column prop="enabled_count" label="启用数" width="100" />
            <el-table-column label="默认账号" min-width="180">
              <template #default="{ row }">
                {{ row.default_account_name || '-' }}
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="反代设置" name="proxy">
          <div class="form-card">
            <el-form label-width="150px">
              <el-form-item label="ProxyURL">
                <div class="form-field">
                  <el-input v-model="settings.proxy_url" placeholder="http://127.0.0.1:5666" :disabled="!canWrite" />
                  <div class="form-field-hint">反代目标地址。</div>
                </div>
              </el-form-item>
              <el-form-item label="飞牛影视路径偏移">
                <div class="form-field">
                  <el-input-number v-model="settings.proxy_path_offset" :step="1" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    飞牛影视的路径偏移配置，会影响代理重写时的目录回退层级，通常使用负数。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="内网网段(CIDR)">
                <div class="form-field">
                  <el-input
                    v-model="settings.intranet_cidrs_text"
                    type="textarea"
                    :rows="6"
                    placeholder="10.0.0.0/8&#10;172.16.0.0/12&#10;192.168.0.0/16&#10;127.0.0.0/8&#10;::1/128&#10;fc00::/7&#10;fe80::/10"
                    :disabled="!canWrite"
                  />
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveProxySettings">
                  保存反代设置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="STRM管理" name="strm">
          <section class="metric-strip metric-strip--inner">
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">生成状态</div>
              <div class="metric-tile__value">{{ strmSummary.enabled ? '开启' : '关闭' }}</div>
              <div class="metric-tile__hint">当前 STRM 自动生成总开关</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">生成模式</div>
              <div class="metric-tile__value">{{ strmSummary.mode === 'independent' ? '独立' : '自动' }}</div>
              <div class="metric-tile__hint">当前正在使用的 STRM 生成模式</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">可参与账号</div>
              <div class="metric-tile__value">{{ strmSummary.path_ready_account_count }}</div>
              <div class="metric-tile__hint">已配置 302 基础路径的可用账号</div>
            </div>
            <div class="glass-panel metric-tile">
              <div class="metric-tile__label">已生成文件</div>
              <div class="metric-tile__value">{{ strmSummary.generated_file_count }}</div>
              <div class="metric-tile__hint">当前模式 manifest 中记录的 STRM 文件数</div>
            </div>
          </section>

          <div class="form-card">
            <el-form label-width="150px">
              <el-divider content-position="left">STRM 管理</el-divider>
              <el-form-item label="开启生成 STRM">
                <div class="form-field">
                  <el-switch v-model="settings.strm_enabled" :disabled="!canWrite" />
                  <div class="form-field-hint">
                    开启后会在驱动目录扫描/缓存巡检完成时自动对账生成。目录过滤复用各账号驱动配置里的 `302代理基础路径`。
                  </div>
                  <div class="form-field-hint">
                    可参与账号：{{ strmSummary.path_ready_account_count }} / {{ strmSummary.source_account_count }}，缺少基础路径账号：{{
                      strmSummary.path_missing_account_count
                    }}。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="生成模式">
                <div class="form-field">
                  <el-radio-group v-model="settings.strm_mode" :disabled="!canWrite">
                    <el-radio value="auto">自动模式</el-radio>
                    <el-radio value="independent">独立模式</el-radio>
                  </el-radio-group>
                  <div class="form-field-hint">
                    自动模式：合并所有可用账号结果，仅保留一份目录树，STRM 链接统一指向 `/dl/auto`。
                  </div>
                  <div class="form-field-hint">
                    独立模式：按账号名生成一级目录，STRM 链接使用对应驱动入口和 `account` 参数。
                  </div>
                </div>
              </el-form-item>
              <el-form-item label="STRM 生成目录">
                <div class="form-field">
                  <el-input v-model="settings.strm_root_dir" placeholder="/strm" :disabled="!canWrite" />
                  <div class="form-field-hint">STRM 文件输出目录；不存在会自动创建。</div>
                  <div class="form-field-hint">开启生成 STRM 状态下修改目录/模式时，会清理旧目录下旧产物并按新配置重建。</div>
                </div>
              </el-form-item>
              <el-form-item label="前缀 URL">
                <div class="form-field">
                  <el-input
                    v-model="settings.strm_prefix_url"
                    placeholder="例如：http://192.168.1.10:9978"
                    :disabled="!canWrite"
                  />
                  <div class="form-field-hint">用于生成 STRM 内的访问链接前缀；留空时访问页面会自动回填当前访问地址。</div>
                  <div class="form-field-hint">
                    前缀 URL：{{ strmSummary.prefix_ready ? '已就绪' : '未就绪' }}，生成目录状态：{{ strmSummary.root_exists ? '已存在' : '不存在' }}，已生成目录：{{
                      strmSummary.generated_dir_count
                    }}。
                  </div>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="settings.savingProxy" :disabled="!canWrite" @click="saveStrmSettings">
                  保存 STRM 设置
                </el-button>
                <el-button type="success" :loading="settings.generatingStrm" :disabled="!canWrite" @click="generateStrm">
                  立即生成 STRM
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.tab-copy {
  margin-bottom: 16px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.metric-strip--inner {
  margin-bottom: 20px;
}

.form-card {
  max-width: 720px;
}

.form-field {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
</style>
