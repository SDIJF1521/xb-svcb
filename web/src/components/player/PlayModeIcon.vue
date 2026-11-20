<template>
  <svg class="mode-icon" viewBox="0 0 24 24" aria-hidden="true">
    <g v-if="mode === 'order'" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M4 6h9M4 12h9M4 18h9" />
      <path d="m16 9 4 3-4 3" />
    </g>
    <g
      v-else-if="mode === 'shuffle'"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M4 6h3.5c4.5 0 4.5 12 9 12H20" />
      <path d="M17 15l3 3-3 3" />
      <path d="M4 18h3.5c1.6 0 2.6-1.4 3.6-3.3M13.2 8.9C14 7.4 15 6 16.5 6H20" />
      <path d="M17 3l3 3-3 3" />
    </g>
    <g
      v-else
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M17 2l4 4-4 4" />
      <path d="M3 11V9a3 3 0 0 1 3-3h15" />
      <path d="M7 22l-4-4 4-4" />
      <path d="M21 13v2a3 3 0 0 1-3 3H3" />
      <path v-if="mode === 'single'" d="M11 10h1v5" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import type { PlayMode } from '@/player/types'

defineOptions({ name: 'PlayModeIcon' })

defineProps<{ mode: PlayMode }>()
</script>

<style scoped>
.mode-icon {
  width: 18px;
  height: 18px;
  display: block;
}
</style>
