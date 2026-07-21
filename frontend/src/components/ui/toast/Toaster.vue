<script setup lang="ts">
import { ToastProvider, ToastViewport } from 'radix-vue'
import Toast from './Toast.vue'
import { useToast } from '@/composables/useToast'

const { toasts, dismiss } = useToast()
</script>

<template>
  <ToastProvider>
    <Toast
      v-for="item in toasts"
      :key="item.id"
      :title="item.title"
      :description="item.description"
      :variant="item.variant"
      :open="item.open"
      :duration="item.duration"
      @update:open="(val: boolean) => { if (!val) dismiss(item.id) }"
    />
    <ToastViewport
      class="fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col-reverse gap-2 p-4 sm:max-w-[420px]"
    />
  </ToastProvider>
</template>
