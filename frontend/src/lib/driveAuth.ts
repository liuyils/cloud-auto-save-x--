import axios, { type AxiosError } from 'axios'
import type { DriveAccountAuthChallenge } from '@/types/extensions'

type ApiErrorBody = {
  code?: string
  message?: string
  detail?: string
}

/** 支持 TV 扫码登录的驱动（同时也支持普通扫码流程） */
export const TV_QRCODE_DRIVES = ['quark', 'uc']
/** 支持扫码登录的驱动 */
export const QRCODE_DRIVES = ['aliyun', ...TV_QRCODE_DRIVES]

export function normalizeDriveType(driveType?: string | null) {
  return String(driveType || '').trim().toLowerCase()
}

export function supportsTvQrcodeAuth(driveType?: string | null) {
  return TV_QRCODE_DRIVES.includes(normalizeDriveType(driveType))
}

export function supportsQrcodeAuth(driveType?: string | null) {
  return QRCODE_DRIVES.includes(normalizeDriveType(driveType))
}

/**
 * 从接口错误（409）中解析二次认证挑战。
 * 后端会在 detail 字段中返回 JSON 字符串，包含 session_id / method 等。
 */
export function parseAuthChallenge(error: unknown): DriveAccountAuthChallenge | null {
  if (!axios.isAxiosError(error)) return null
  const err = error as AxiosError<ApiErrorBody>
  if (err.response?.status !== 409) return null
  const code = err.response?.data?.code
  if (code !== 'DRIVE_ACCOUNT_AUTH_REQUIRED' && code !== 'DRIVE_ACCOUNT_AUTH_PENDING') return null
  const detail = err.response?.data?.detail
  if (!detail || typeof detail !== 'string') return null
  try {
    const parsed = JSON.parse(detail)
    if (!parsed?.session_id || !parsed?.method) return null
    return parsed as DriveAccountAuthChallenge
  } catch {
    return null
  }
}

/** 从任意接口错误中提取可读的错误信息 */
export function extractErrorMessage(error: unknown, fallback = '操作失败'): string {
  if (axios.isAxiosError(error)) {
    const err = error as AxiosError<ApiErrorBody>
    return err.response?.data?.message || err.message || fallback
  }
  if (error instanceof Error) return error.message || fallback
  return fallback
}
