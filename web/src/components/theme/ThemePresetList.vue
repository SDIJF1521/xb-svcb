<template>
  <div class="theme-presets">
    <button
      v-for="item in THEMES"
      :key="item.value"
      class="theme-preset"
      :class="{ active: activeTheme === item.value }"
      :style="themeSwatchStyle(item.value)"
      @click="emit('select', item.value, $event)"
    >
      <span class="preset-swatch"><i></i><i></i><i></i></span>
      <span class="preset-copy">
        <span>{{ item.value === 'custom' ? customTheme.name : item.label }}</span>
        <small>{{ item.desc }}</small>
      </span>
      <el-icon v-if="activeTheme === item.value"><Check /></el-icon>
    </button>
  </div>
</template>

<script setup lang="ts">
import { Check } from '@element-plus/icons-vue'
import { THEMES } from '@/stores/theme'
import type { CustomTheme, ThemeName } from '@/stores/theme'

defineOptions({ name: 'ThemePresetList' })

const props = defineProps<{
  activeTheme: ThemeName
  customTheme: CustomTheme
}>()

const emit = defineEmits<{
  select: [name: ThemeName, event: MouseEvent]
}>()

function themeSwatchStyle(name: ThemeName): Record<string, string> {
  if (name === 'anime') {
    return { '--sw-1': '#5b9cff', '--sw-2': '#8a7bff', '--sw-3': '#ff84bd' }
  }
  if (name === 'custom') {
    return {
      '--sw-1': props.customTheme.primary,
      '--sw-2': props.customTheme.primary2,
      '--sw-3': props.customTheme.accent,
    }
  }
  return { '--sw-1': '#00f0ff', '--sw-2': '#2f6bff', '--sw-3': '#ff2e88' }
}
</script>

<style scoped>
.theme-presets {
  display: grid;
  gap: 6px;
  padding: 8px;
  border-bottom: 1px solid var(--xb-border);
}
.theme-preset {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--xb-text);
  text-align: left;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}
.theme-preset:hover,
.theme-preset.active {
  background: rgba(var(--xb-fill-rgb), 0.06);
  border-color: var(--xb-border);
}
.preset-swatch {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid rgba(var(--xb-fill-rgb), 0.16);
}
.preset-swatch i:nth-child(1) { background: var(--sw-1); }
.preset-swatch i:nth-child(2) { background: var(--sw-2); }
.preset-swatch i:nth-child(3) { background: var(--sw-3); }
.preset-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.preset-copy span {
  font-size: 13.5px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.preset-copy small {
  font-size: 12px;
  color: var(--xb-muted);
}
.theme-preset > .el-icon {
  flex-shrink: 0;
  color: var(--xb-primary);
}
</style>
