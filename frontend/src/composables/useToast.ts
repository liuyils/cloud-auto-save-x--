import { ref } from 'vue'

export type ToastVariant = 'default' | 'destructive' | 'success'

export interface ToastItem {
  id: string
  title: string
  description?: string
  variant: ToastVariant
  duration: number
  open: boolean
}

const toasts = ref<ToastItem[]>([])

let idCounter = 0

function genId() {
  return `toast-${++idCounter}-${Date.now()}`
}

function addToast(options: { title: string; description?: string; variant?: ToastVariant; duration?: number }) {
  const item: ToastItem = {
    id: genId(),
    title: options.title,
    description: options.description,
    variant: options.variant ?? 'default',
    duration: options.duration ?? 4000,
    open: true,
  }
  toasts.value.push(item)
}

function dismiss(id: string) {
  const idx = toasts.value.findIndex((t) => t.id === id)
  if (idx !== -1) {
    toasts.value[idx].open = false
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, 300)
  }
}

const toast = {
  success(msg: string, options?: { description?: string; duration?: number }) {
    addToast({ title: msg, description: options?.description, variant: 'success', duration: options?.duration })
  },
  error(msg: string, options?: { description?: string; duration?: number }) {
    addToast({ title: msg, description: options?.description, variant: 'destructive', duration: options?.duration ?? 5000 })
  },
  info(msg: string, options?: { description?: string; duration?: number }) {
    addToast({ title: msg, description: options?.description, variant: 'default', duration: options?.duration })
  },
  dismiss,
}

export function useToast() {
  return { toasts, toast, dismiss }
}
