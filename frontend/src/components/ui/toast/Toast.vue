<script lang="ts">
import { cva, type VariantProps } from 'class-variance-authority'

export const toastVariants = cva(
  'group pointer-events-auto relative flex w-full items-center justify-between gap-3 overflow-hidden rounded-md border border-[hsl(var(--border))] p-4 pr-8 shadow-lg transition-all data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=move]:transition-none data-[state=open]:animate-[toast-slide-in_0.3s_ease-out] data-[state=closed]:animate-[toast-slide-out_0.2s_ease-in_forwards]',
  {
    variants: {
      variant: {
        default: 'bg-[hsl(var(--background))] text-[hsl(var(--foreground))]',
        destructive:
          'bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] border-[hsl(var(--destructive))]',
        success:
          'bg-[hsl(142_76%_36%)] text-white border-[hsl(142_76%_36%)]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export type ToastVariants = VariantProps<typeof toastVariants>
</script>

<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'
import {
  ToastRoot,
  type ToastRootEmits,
  ToastTitle,
  ToastDescription,
  ToastClose,
} from 'radix-vue'
import { cn } from '@/lib/utils'
import type { ToastVariant } from '@/composables/useToast'

interface Props {
  title: string
  description?: string
  variant?: ToastVariant
  open?: boolean
  duration?: number
  class?: HTMLAttributes['class']
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  open: true,
  duration: 4000,
})

const emit = defineEmits<ToastRootEmits>()

const rootClass = computed(() =>
  cn(toastVariants({ variant: props.variant }), props.class),
)
</script>

<template>
  <ToastRoot
    :open="props.open"
    :duration="props.duration"
    :class="rootClass"
    @update:open="(val) => emit('update:open', val)"
  >
    <div class="grid gap-1">
      <ToastTitle class="text-sm font-semibold">
        {{ title }}
      </ToastTitle>
      <ToastDescription v-if="description" class="text-sm opacity-90">
        {{ description }}
      </ToastDescription>
    </div>
    <ToastClose
      class="absolute right-2 top-2 rounded-md p-1 opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 focus:outline-none focus:ring-2"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    </ToastClose>
  </ToastRoot>
</template>
