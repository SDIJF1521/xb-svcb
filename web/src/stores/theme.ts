import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ThemeName = 'cyber' | 'anime'

const STORAGE_KEY = 'xb-theme'

export const THEMES: { value: ThemeName; label: string; desc: string }[] = [
  { value: 'cyber', label: '赛博霓虹', desc: '暗色 · 青蓝霓虹' },
  { value: 'anime', label: '二次元', desc: '亮色 · 蓝粉少女' },
]

function readStored(): ThemeName {
  const v = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) as ThemeName | null
  return v === 'anime' || v === 'cyber' ? v : 'cyber'
}

function applyTheme(name: ThemeName) {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = name
  }
}

/** 通知 pywebview 后端给原生窗口标题栏/边框上色（桌面运行时才有 pywebview）。 */
function syncWindowChrome(name: ThemeName) {
  if (typeof window === 'undefined') return
  const api = (window as unknown as { pywebview?: { api?: { apply_window_theme?: (t: string) => Promise<unknown> } } }).pywebview?.api
  if (api?.apply_window_theme) {
    Promise.resolve(api.apply_window_theme(name)).catch(() => {})
  }
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeName>(readStored())

  function setTheme(name: ThemeName) {
    theme.value = name
    applyTheme(name)
    syncWindowChrome(name)
    try {
      localStorage.setItem(STORAGE_KEY, name)
    } catch {
      /* ignore persistence errors */
    }
  }

  function toggle() {
    setTheme(theme.value === 'cyber' ? 'anime' : 'cyber')
  }

  // 确保初始 DOM 与状态一致
  applyTheme(theme.value)

  // pywebview 就绪后同步原生窗口外观（桌面端）；若已就绪则立即同步
  if (typeof window !== 'undefined') {
    window.addEventListener('pywebviewready', () => syncWindowChrome(theme.value))
    if ((window as unknown as { pywebview?: unknown }).pywebview) {
      syncWindowChrome(theme.value)
    }
  }

  return { theme, setTheme, toggle }
})
