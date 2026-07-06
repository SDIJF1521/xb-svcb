<template>
  <div ref="themeWrap" class="menu-wrap theme-wrap">
    <button
      class="theme-toggle"
      :class="theme"
      :title="`当前：${themeLabel}（点击切换主题）`"
      @click="onThemeToggle"
    >
      <span class="theme-knob">
        <el-icon><component :is="theme === 'anime' ? Sunny : theme === 'custom' ? Brush : Moon" /></el-icon>
      </span>
      <span class="theme-name">{{ themeLabel }}</span>
    </button>
    <button
      class="theme-edit"
      :class="{ active: open }"
      title="自定义主题"
      @click="togglePanel"
    >
      <el-icon><Brush /></el-icon>
    </button>

    <transition name="pop">
      <div v-if="open" class="popover theme-pop">
        <div class="pop-head">
          <span>主题</span>
          <button class="pop-link" @click="resetCustomTheme">重置</button>
        </div>

        <ThemePresetList
          :active-theme="theme"
          :custom-theme="customTheme"
          @select="selectTheme"
        />
        <CustomThemeEditor
          v-model="customDraft"
          @preview="previewCustomTheme"
          @save="saveCustomTheme"
        />
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { Brush, Moon, Sunny } from '@element-plus/icons-vue'
import CustomThemeEditor from '@/components/theme/CustomThemeEditor.vue'
import ThemePresetList from '@/components/theme/ThemePresetList.vue'
import { cloneCustomTheme, DEFAULT_CUSTOM_THEME, useThemeStore } from '@/stores/theme'
import type { CustomTheme, ThemeName } from '@/stores/theme'

defineOptions({ name: 'ThemeSwitcher' })

const themeStore = useThemeStore()
const { theme, customTheme, themeLabel } = storeToRefs(themeStore)
const customDraft = ref<CustomTheme>(cloneCustomTheme(customTheme.value))
const themeWrap = ref<HTMLElement>()
const open = ref(false)

function togglePanel() {
  open.value = !open.value
  if (open.value) customDraft.value = cloneCustomTheme(customTheme.value)
}

function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  if (!themeWrap.value?.contains(target)) open.value = false
}

function onThemeToggle(e: MouseEvent) {
  open.value = false
  themeStore.toggle(e)
}

function selectTheme(name: ThemeName, e: MouseEvent) {
  if (name === 'custom') customDraft.value = cloneCustomTheme(customTheme.value)
  themeStore.setTheme(name, { event: e })
}

function previewCustomTheme(e: MouseEvent) {
  themeStore.previewCustomTheme(customDraft.value, { event: e })
}

function saveCustomTheme(e: MouseEvent) {
  themeStore.saveCustomTheme(customDraft.value, { event: e })
  open.value = false
}

function resetCustomTheme(e: MouseEvent) {
  customDraft.value = cloneCustomTheme(DEFAULT_CUSTOM_THEME)
  themeStore.resetCustomTheme({ event: e })
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.menu-wrap { position: relative; }
.theme-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
}
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 38px;
  width: 38px;
  padding: 0;
  border-radius: 999px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.25s;
}
.theme-toggle:hover {
  border-color: var(--xb-primary);
  box-shadow: 0 0 16px rgba(var(--xb-primary-rgb), 0.25);
}
.theme-knob {
  width: 28px; height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 15px;
  color: var(--xb-on-primary);
  background: var(--xb-brand-gradient);
  box-shadow: 0 0 12px rgba(var(--xb-primary-rgb), 0.45);
  transition: transform 0.4s ease;
}
.theme-toggle.anime .theme-knob { transform: rotate(360deg); }
.theme-toggle.custom .theme-knob { transform: rotate(180deg); }
.theme-name { display: none; }
.theme-edit {
  width: 24px;
  height: 38px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  background: rgba(var(--xb-fill-rgb), 0.035);
  color: var(--xb-muted);
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.theme-edit:hover,
.theme-edit.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
}
.popover {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  width: 320px;
  background: var(--xb-bg-2);
  border: 1px solid var(--xb-border);
  border-radius: 16px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(var(--xb-primary-rgb), 0.05);
  backdrop-filter: blur(20px);
  overflow: hidden;
  z-index: 80;
}
.pop-enter-active, .pop-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-6px); }
.pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  font-weight: 700;
  font-size: 14px;
  border-bottom: 1px solid var(--xb-border);
}
.pop-link {
  border: none;
  background: none;
  color: var(--xb-primary);
  font-size: 12.5px;
  cursor: pointer;
}
.pop-link:hover { text-decoration: underline; }
.theme-pop {
  width: 340px;
  max-height: calc(100vh - 88px);
  overflow-y: auto;
}

@media (max-width: 640px) {
  .theme-wrap {
    display: none;
  }
}
</style>
