<template>
  <div ref="wrap" class="locale-wrap">
    <button
      class="locale-button"
      :class="{ active: open }"
      :title="t('language.current', { language: activeOption.nativeLabel })"
      :aria-label="t('language.title')"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <el-icon><ChatDotSquare /></el-icon>
      <span>{{ activeOption.short }}</span>
    </button>

    <transition name="locale-pop">
      <div v-if="open" class="locale-menu" role="menu" :aria-label="t('language.title')">
        <div class="locale-heading">{{ t('language.title') }}</div>
        <button
          v-for="option in options"
          :key="option.value"
          class="locale-option"
          :class="{ selected: option.value === locale }"
          role="menuitemradio"
          :aria-checked="option.value === locale"
          @click="choose(option.value)"
        >
          <span class="locale-code">{{ option.short }}</span>
          <span class="locale-label">
            <strong>{{ option.nativeLabel }}</strong>
            <small>{{ option.label }}</small>
          </span>
          <el-icon v-if="option.value === locale"><Check /></el-icon>
        </button>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ChatDotSquare, Check } from '@element-plus/icons-vue'
import { type AppLocale, useI18n } from '@/i18n'

defineOptions({ name: 'LocaleSwitcher' })

const { locale, activeOption, options, setLocale, t } = useI18n()
const wrap = ref<HTMLElement>()
const open = ref(false)

function choose(next: AppLocale) {
  setLocale(next)
  open.value = false
}

function onDocumentClick(event: MouseEvent) {
  if (!wrap.value?.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<style scoped>
.locale-wrap { position: relative; flex: 0 0 auto; }
.locale-button {
  width: 46px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0;
  border: 1px solid var(--xb-border);
  border-radius: 10px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  font: 700 11px/1 var(--xb-font);
  cursor: pointer;
  transition: color .18s ease, border-color .18s ease, background .18s ease;
}
.locale-button .el-icon { font-size: 15px; }
.locale-button:hover,
.locale-button.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.09);
}
.locale-menu {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  z-index: 90;
  width: 220px;
  padding: 6px;
  border: 1px solid var(--xb-border);
  border-radius: 12px;
  background: var(--xb-bg-2);
  box-shadow: 0 18px 44px rgba(var(--xb-bg-rgb), .38);
  backdrop-filter: blur(20px);
}
.locale-heading {
  padding: 8px 10px 9px;
  color: var(--xb-muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.locale-option {
  width: 100%;
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--xb-text);
  font-family: var(--xb-font);
  text-align: left;
  cursor: pointer;
}
.locale-option:hover,
.locale-option.selected { background: rgba(var(--xb-primary-rgb), .1); }
.locale-option.selected { color: var(--xb-primary); }
.locale-code {
  width: 32px;
  height: 28px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 1px solid var(--xb-border);
  border-radius: 7px;
  font-size: 11px;
  font-weight: 800;
}
.locale-label { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.locale-label strong { font-size: 13px; font-weight: 700; }
.locale-label small { color: var(--xb-muted); font-size: 10.5px; }
.locale-option > .el-icon { flex: 0 0 auto; font-size: 15px; }
.locale-pop-enter-active,
.locale-pop-leave-active { transition: opacity .16s ease, transform .16s ease; }
.locale-pop-enter-from,
.locale-pop-leave-to { opacity: 0; transform: translateY(-5px); }
@media (max-width: 1080px) {
  .locale-button { width: 38px; }
  .locale-button span { display: none; }
}
</style>
