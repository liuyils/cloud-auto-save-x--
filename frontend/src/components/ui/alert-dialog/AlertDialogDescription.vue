<script setup lang="ts">
import { type HTMLAttributes } from 'vue'
import { AlertDialogDescription, type AlertDialogDescriptionProps } from 'radix-vue'
import { cn } from '@/lib/utils'

interface Props extends AlertDialogDescriptionProps {
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()
</script>

<template>
  <AlertDialogDescription :class="cn('text-sm text-[hsl(var(--muted-foreground))]', props.class)">
    <slot />
  </AlertDialogDescription>
</template>
