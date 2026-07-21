import { formatBytes } from '@/lib/capacity'
import type { DL302CASTask, DL302CASTaskItem, DL302SupportedAccount } from '@/types/dl302'

/** CAS 任务状态中文文案 */
export function casStatusText(status?: string | null): string {
  switch (status) {
    case 'running':
      return '运行中'
    case 'pending':
      return '待执行'
    case 'pausing':
      return '暂停中'
    case 'paused':
      return '已暂停'
    case 'done':
      return '已完成'
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已停止'
    default:
      return '未创建'
  }
}

/** CAS 任务状态对应的 pill 配色（Tailwind class） */
export function casStatusClass(status?: string | null): string {
  switch (status) {
    case 'done':
      return 'bg-green-500/15 text-green-600 dark:text-green-400'
    case 'failed':
      return 'bg-red-500/15 text-red-500'
    case 'cancelled':
      return 'bg-gray-500/15 text-gray-500 dark:text-gray-400'
    case 'running':
    case 'pending':
    case 'pausing':
      return 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
    case 'paused':
      return 'bg-blue-500/15 text-blue-600 dark:text-blue-400'
    default:
      return 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
  }
}

/** CAS 明细状态中文文案 */
export function itemStatusLabel(status?: string | null): string {
  switch (status) {
    case 'running':
      return '处理中'
    case 'pending':
      return '待处理'
    case 'done':
      return '已完成'
    case 'failed':
      return '失败'
    case 'skipped':
      return '已跳过'
    case 'cancelled':
      return '已取消'
    default:
      return '未知'
  }
}

/** CAS 明细状态对应的 pill 配色 */
export function itemStatusClass(status?: string | null): string {
  switch (status) {
    case 'done':
    case 'skipped':
      return 'bg-green-500/15 text-green-600 dark:text-green-400'
    case 'failed':
      return 'bg-red-500/15 text-red-500'
    case 'cancelled':
      return 'bg-gray-500/15 text-gray-500 dark:text-gray-400'
    case 'running':
      return 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
    default:
      return 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
  }
}

export function taskProcessedItems(task?: DL302CASTask | null): number {
  if (!task) return 0
  return Number(task.done_items || 0) + Number(task.skipped_items || 0) + Number(task.failed_items || 0)
}

export function taskProgressText(task?: DL302CASTask | null): string {
  if (!task) return '0/0'
  return `${taskProcessedItems(task)}/${task.total_items}`
}

export function taskPercent(task?: DL302CASTask | null): number {
  if (!task || !task.total_items) return 0
  return Math.min(100, Math.round((taskProcessedItems(task) / task.total_items) * 100))
}

export function itemPercent(item: DL302CASTaskItem): number {
  const total = Number(item.stage_total || item.size || 0)
  const done = Number(item.stage_done || 0)
  if (!total) return done > 0 ? 1 : 0
  return Math.min(100, Math.round((done / total) * 100))
}

export function formatStageProgress(item: DL302CASTaskItem): string {
  const total = Number(item.stage_total || item.size || 0)
  const done = Number(item.stage_done || 0)
  if (!total) return done > 0 ? formatBytes(done) : '-'
  return `${formatBytes(done)} / ${formatBytes(total)}`
}

export function isTaskActive(status?: string | null): boolean {
  return status === 'running' || status === 'pending' || status === 'pausing'
}

export function canPauseTask(task?: DL302CASTask | null): boolean {
  if (!task) return false
  return task.status === 'running' || task.status === 'pending'
}

export function canResumeTask(task?: DL302CASTask | null): boolean {
  if (!task) return false
  return task.status === 'paused' || task.status === 'failed'
}

export function canCancelTask(task?: DL302CASTask | null): boolean {
  if (!task) return false
  return (
    task.status === 'running' ||
    task.status === 'pending' ||
    task.status === 'pausing' ||
    task.status === 'failed' ||
    task.status === 'paused'
  )
}

export function accountCasBasePath(account: DL302SupportedAccount): string {
  return String(account.strm_scan_base_path || account.media_base_path || '').trim()
}

export function canGenerateCas(account: DL302SupportedAccount): boolean {
  return Boolean(accountCasBasePath(account))
}

export function taskOptionLabel(task: DL302CASTask): string {
  return `${task.task_id.slice(0, 8)} · ${casStatusText(task.status)}`
}

/** 账号 CAS 概要文案 */
export function buildCasSummary(account: DL302SupportedAccount, task?: DL302CASTask | null): string {
  if (!canGenerateCas(account)) return '未配置 STRM 扫描路径。'
  if (!task) return '尚未创建 CAS 任务。'
  const processed = taskProcessedItems(task)
  if (task.status === 'running' || task.status === 'pending' || task.status === 'pausing') {
    return `任务 ${task.task_id.slice(0, 8)} 处理中：已处理 ${processed}/${task.total_items}，字节 ${formatBytes(task.done_bytes)}/${formatBytes(task.total_bytes || 0)}`
  }
  if (task.status === 'paused') return `任务已暂停：已处理 ${processed}/${task.total_items}`
  if (task.status === 'failed') return task.last_error || 'CAS 任务失败。'
  if (task.status === 'cancelled') return `任务已停止：已处理 ${processed}/${task.total_items}`
  if (task.status === 'done') return `任务完成：完成 ${task.done_items}，跳过 ${task.skipped_items}，失败 ${task.failed_items}`
  return '尚未创建 CAS 任务。'
}
