<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 focus-visible:ring-offset-[hsl(var(--background))] disabled:cursor-not-allowed disabled:opacity-50"
    :class="modelValue ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'"
    @click="toggle"
  >
    <span
      class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200"
      :class="modelValue ? 'left-[18px]' : 'left-0.5'"
    />
  </button>
</template>
