<script setup lang="ts">
import CreateTaskSheet from '@/components/business/drama/CreateTaskSheet.vue'
import StreamLogDialog from '@/components/business/common/StreamLogDialog.vue'
import type { useDramaTaskLauncher } from '@/composables/useDramaTaskLauncher'

const props = defineProps<{
  launcher: ReturnType<typeof useDramaTaskLauncher>
}>()
</script>

<template>
  <CreateTaskSheet
    :open="props.launcher.sheetOpen.value"
    :edit-task="props.launcher.editingTask.value"
    :preset-tmdb="props.launcher.presetTmdb.value"
    @close="props.launcher.close"
    @run-once="props.launcher.handleRunOnce"
  />

  <StreamLogDialog
    v-model:visible="props.launcher.showStreamLog.value"
    :url="props.launcher.streamLogUrl.value"
    :title="props.launcher.streamLogTitle.value"
    :method="props.launcher.streamLogMethod.value"
    :body="props.launcher.streamLogBody.value"
  />
</template>
