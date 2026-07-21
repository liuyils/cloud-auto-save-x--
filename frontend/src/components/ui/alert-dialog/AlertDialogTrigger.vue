<script setup lang="ts">
import { type HTMLAttributes } from 'vue'
import { AlertDialogTrigger, type AlertDialogTriggerProps } from 'radix-vue'
import { cn } from '@/lib/utils'

interface Props extends AlertDialogTriggerProps {
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()
</script>

<template>
  <AlertDialogTrigger v-bind="props" :class="cn(props.class)">
    <slot />
  </AlertDialogTrigger>
</template>
