<template>
  <el-tooltip :content="`${label} · ${hint}`" placement="top" :show-after="260">
    <button
      class="mode-button"
      :class="{ active: mode !== 'order', compact }"
      type="button"
      :aria-label="label"
      @click.stop="player.cycleMode()"
    >
      <PlayModeIcon :mode="mode" />
      <span v-if="!compact" class="mode-label">{{ label }}</span>
    </button>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { usePlayerStore } from '@/stores/player'
import { PLAY_MODE_HINTS, PLAY_MODE_LABELS } from '@/player/queue'
import PlayModeIcon from './PlayModeIcon.vue'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

defineOptions({ name: 'PlayModeButton' })

const player = usePlayerStore()
const mode = computed(() => player.mode)
const label = computed(() => PLAY_MODE_LABELS[mode.value])
const hint = computed(() => PLAY_MODE_HINTS[mode.value])
</script>

<style scoped>
.mode-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 9px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: transparent;
  color: var(--xb-muted);
  font-size: 12px;
  cursor: pointer;
  transition: 0.2s ease;
}
.mode-button:hover {
  color: var(--xb-text);
  border-color: rgba(var(--xb-primary-rgb), 0.5);
}
.mode-button.active {
  color: var(--xb-primary);
  border-color: rgba(var(--xb-primary-rgb), 0.42);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.mode-button.compact {
  width: 32px;
  padding: 0;
  justify-content: center;
  border-color: transparent;
}
.mode-label {
  white-space: nowrap;
}
@media (max-width: 720px) {
  .mode-label {
    display: none;
  }
  .mode-button {
    width: 32px;
    padding: 0;
    justify-content: center;
    border-color: transparent;
  }
}
</style>
