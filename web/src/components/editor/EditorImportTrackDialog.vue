<template>
  <el-dialog v-model="open" title="选择导入音轨" width="420px" class="import-track-dialog">
    <div class="import-track-options">
      <el-radio-group v-model="target">
        <el-radio
          v-for="track in tracks"
          :key="track.id"
          :value="track.id"
          :disabled="track.locked"
        >
          {{ track.name }}
        </el-radio>
        <el-radio value="__new__">新建音轨</el-radio>
      </el-radio-group>
    </div>
    <template #footer>
      <el-button round class="ghost-btn" @click="open = false">取消</el-button>
      <el-button round class="cta-btn" @click="emit('confirm')">选择音频</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EditorTrack } from '@/api'

const props = defineProps<{
  modelValue: boolean
  targetTrackId: string
  tracks: EditorTrack[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:targetTrackId': [value: string]
  confirm: []
}>()

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const target = computed({
  get: () => props.targetTrackId,
  set: (value) => emit('update:targetTrackId', value),
})
</script>

<style scoped>
.ghost-btn {
  background: rgba(var(--xb-fill-rgb), 0.04) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
}
.import-track-options :deep(.el-radio-group) {
  display: grid;
  gap: 8px;
  align-items: stretch;
}
.import-track-options :deep(.el-radio) {
  min-height: 34px;
  margin-right: 0;
  padding: 0 10px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
}
</style>
