import { computed, nextTick, ref } from 'vue'
import { defineStore } from 'pinia'

export type ThemeName = 'cyber' | 'anime' | 'custom'

export interface CustomTheme {
  name: string
  bg: string
  bg2: string
  text: string
  muted: string
  primary: string
  primary2: string
  accent: string
  onPrimary: string
  fill: string
  success: string
  warn: string
  bgImage: string
  bgMediaType: 'image' | 'video'
  imageOverlay: number
  particles: boolean
  particleDensity: number
  particleSize: number
}

type CustomThemeColorKey = Exclude<keyof CustomTheme, 'name' | 'bgImage' | 'bgMediaType' | 'imageOverlay' | 'particles' | 'particleDensity' | 'particleSize'>

export interface CustomThemeField {
  key: CustomThemeColorKey
  label: string
}

interface ThemeTransitionOptions {
  event?: MouseEvent
}

type ThemeTransitionDirection = 'expand-new' | 'contract-old'

type ViewTransitionLike = {
  ready: Promise<void>
  finished: Promise<void>
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => void | Promise<void>) => ViewTransitionLike
}

const STORAGE_KEY = 'xb-theme'
const CUSTOM_STORAGE_KEY = 'xb-custom-theme'
const THEME_TRANSITION_DURATION = 480
const THEME_TRANSITION_EASING = 'cubic-bezier(0.22, 1, 0.36, 1)'

const HEX_RE = /^#[0-9a-f]{6}$/i

export const THEMES: { value: ThemeName; label: string; desc: string }[] = [
  { value: 'cyber', label: '赛博霓虹', desc: '暗色 · 青蓝霓虹' },
  { value: 'anime', label: '二次元', desc: '亮色 · 蓝粉少女' },
  { value: 'custom', label: '自定义', desc: '自己调配颜色' },
]

export const CUSTOM_THEME_FIELDS: CustomThemeField[] = [
  { key: 'bg', label: '背景' },
  { key: 'bg2', label: '底色' },
  { key: 'text', label: '正文' },
  { key: 'muted', label: '弱文字' },
  { key: 'primary', label: '主色' },
  { key: 'primary2', label: '副色' },
  { key: 'accent', label: '强调' },
  { key: 'onPrimary', label: '按钮字' },
  { key: 'fill', label: '叠加' },
  { key: 'success', label: '成功' },
  { key: 'warn', label: '警告' },
]

export const DEFAULT_CUSTOM_THEME: CustomTheme = {
  name: '晴空花园',
  bg: '#fbfcff',
  bg2: '#eef7ff',
  text: '#223047',
  muted: '#71809a',
  primary: '#4f8cff',
  primary2: '#2fc7a1',
  accent: '#ff7aa8',
  onPrimary: '#ffffff',
  fill: '#223047',
  success: '#21b981',
  warn: '#f3a13b',
  bgImage: '',
  bgMediaType: 'image',
  imageOverlay: 30,
  particles: true,
  particleDensity: 28,
  particleSize: 3.2,
}

const CUSTOM_CSS_VARS = [
  '--xb-bg',
  '--xb-bg-2',
  '--xb-bg-rgb',
  '--xb-panel',
  '--xb-border',
  '--xb-text',
  '--xb-muted',
  '--xb-primary',
  '--xb-primary-2',
  '--xb-accent',
  '--xb-on-primary',
  '--xb-primary-rgb',
  '--xb-secondary-rgb',
  '--xb-accent-rgb',
  '--xb-fill-rgb',
  '--xb-success',
  '--xb-success-rgb',
  '--xb-warn',
  '--xb-warn-rgb',
  '--xb-hero-gradient',
  '--xb-brand-gradient',
  '--xb-scroll-track',
  '--xb-scroll-thumb',
  '--xb-scroll-thumb-hover',
  '--xb-deco-1',
  '--xb-deco-2',
  '--xb-deco-3',
  '--xb-grid-rgb',
  '--xb-grid-opacity',
  '--xb-orb-opacity',
  '--xb-custom-bg-image',
  '--xb-custom-image-opacity',
  '--xb-image-overlay',
  '--xb-particle-opacity',
  '--xb-particle-size',
]

function normalizeColor(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const color = value.trim()
  return HEX_RE.test(color) ? color.toLowerCase() : fallback
}

function normalizeMedia(value: unknown): string {
  if (typeof value !== 'string') return ''
  const media = value.trim()
  if (!media) return ''
  if (media.startsWith('data:image/') || media.startsWith('data:video/mp4')) return media
  return media
}

function normalizeMediaType(value: unknown, media: string): 'image' | 'video' {
  if (value === 'video' || media.startsWith('data:video/mp4') || /\.mp4($|\?)/i.test(media)) {
    return 'video'
  }
  return 'image'
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback
}

function sanitizeCustomTheme(value: unknown): CustomTheme {
  const raw = (value && typeof value === 'object' ? value : {}) as Partial<CustomTheme>
  return {
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim().slice(0, 16) : DEFAULT_CUSTOM_THEME.name,
    bg: normalizeColor(raw.bg, DEFAULT_CUSTOM_THEME.bg),
    bg2: normalizeColor(raw.bg2, DEFAULT_CUSTOM_THEME.bg2),
    text: normalizeColor(raw.text, DEFAULT_CUSTOM_THEME.text),
    muted: normalizeColor(raw.muted, DEFAULT_CUSTOM_THEME.muted),
    primary: normalizeColor(raw.primary, DEFAULT_CUSTOM_THEME.primary),
    primary2: normalizeColor(raw.primary2, DEFAULT_CUSTOM_THEME.primary2),
    accent: normalizeColor(raw.accent, DEFAULT_CUSTOM_THEME.accent),
    onPrimary: normalizeColor(raw.onPrimary, DEFAULT_CUSTOM_THEME.onPrimary),
    fill: normalizeColor(raw.fill, DEFAULT_CUSTOM_THEME.fill),
    success: normalizeColor(raw.success, DEFAULT_CUSTOM_THEME.success),
    warn: normalizeColor(raw.warn, DEFAULT_CUSTOM_THEME.warn),
    bgImage: normalizeMedia(raw.bgImage),
    bgMediaType: normalizeMediaType(raw.bgMediaType, normalizeMedia(raw.bgImage)),
    imageOverlay: clampNumber(raw.imageOverlay, DEFAULT_CUSTOM_THEME.imageOverlay, 0, 90),
    particles: typeof raw.particles === 'boolean' ? raw.particles : DEFAULT_CUSTOM_THEME.particles,
    particleDensity: clampNumber(raw.particleDensity, DEFAULT_CUSTOM_THEME.particleDensity, 0, 64),
    particleSize: clampNumber(raw.particleSize, DEFAULT_CUSTOM_THEME.particleSize, 1.5, 8),
  }
}

function readStoredTheme(): ThemeName {
  if (typeof localStorage === 'undefined') return 'cyber'
  const value = localStorage.getItem(STORAGE_KEY) as ThemeName | null
  return value === 'anime' || value === 'custom' || value === 'cyber' ? value : 'cyber'
}

function readStoredCustomTheme(): CustomTheme {
  if (typeof localStorage === 'undefined') return { ...DEFAULT_CUSTOM_THEME }
  try {
    return sanitizeCustomTheme(JSON.parse(localStorage.getItem(CUSTOM_STORAGE_KEY) || 'null'))
  } catch {
    return { ...DEFAULT_CUSTOM_THEME }
  }
}

function hexToRgb(color: string): [number, number, number] {
  const safe = normalizeColor(color, '#000000').slice(1)
  return [
    Number.parseInt(safe.slice(0, 2), 16),
    Number.parseInt(safe.slice(2, 4), 16),
    Number.parseInt(safe.slice(4, 6), 16),
  ]
}

function rgb(color: string): string {
  return hexToRgb(color).join(', ')
}

function luminance(color: string): number {
  const [r, g, b] = hexToRgb(color).map((v) => {
    const n = v / 255
    return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4
  }) as [number, number, number]
  return r * 0.2126 + g * 0.7152 + b * 0.0722
}

function clearCustomThemeVars() {
  if (typeof document === 'undefined') return
  for (const name of CUSTOM_CSS_VARS) {
    document.documentElement.style.removeProperty(name)
  }
}

function applyCustomThemeVars(theme: CustomTheme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement.style
  const bg = rgb(theme.bg)
  const bg2 = rgb(theme.bg2)
  const primary = rgb(theme.primary)
  const primary2 = rgb(theme.primary2)
  const accent = rgb(theme.accent)
  const fill = rgb(theme.fill)
  const success = rgb(theme.success)
  const warn = rgb(theme.warn)

  root.setProperty('--xb-bg', theme.bg)
  root.setProperty('--xb-bg-2', theme.bg2)
  root.setProperty('--xb-bg-rgb', bg)
  root.setProperty('--xb-panel', `rgba(${bg2}, 0.72)`)
  root.setProperty('--xb-border', `rgba(${primary}, 0.22)`)
  root.setProperty('--xb-text', theme.text)
  root.setProperty('--xb-muted', theme.muted)
  root.setProperty('--xb-primary', theme.primary)
  root.setProperty('--xb-primary-2', theme.primary2)
  root.setProperty('--xb-accent', theme.accent)
  root.setProperty('--xb-on-primary', theme.onPrimary)
  root.setProperty('--xb-primary-rgb', primary)
  root.setProperty('--xb-secondary-rgb', primary2)
  root.setProperty('--xb-accent-rgb', accent)
  root.setProperty('--xb-fill-rgb', fill)
  root.setProperty('--xb-success', theme.success)
  root.setProperty('--xb-success-rgb', success)
  root.setProperty('--xb-warn', theme.warn)
  root.setProperty('--xb-warn-rgb', warn)
  root.setProperty('--xb-hero-gradient', `linear-gradient(120deg, ${theme.primary} 0%, ${theme.primary2} 48%, ${theme.accent} 100%)`)
  root.setProperty('--xb-brand-gradient', `linear-gradient(135deg, ${theme.primary}, ${theme.primary2})`)
  root.setProperty('--xb-scroll-track', theme.bg)
  root.setProperty('--xb-scroll-thumb', theme.bg2)
  root.setProperty('--xb-scroll-thumb-hover', theme.muted)
  root.setProperty('--xb-deco-1', theme.primary)
  root.setProperty('--xb-deco-2', theme.accent)
  root.setProperty('--xb-deco-3', theme.primary2)
  root.setProperty('--xb-grid-rgb', primary)
  root.setProperty('--xb-grid-opacity', luminance(theme.bg) > 0.5 ? '0.045' : '0.06')
  root.setProperty('--xb-orb-opacity', luminance(theme.bg) > 0.5 ? '0.42' : '0.34')
  root.setProperty(
    '--xb-custom-bg-image',
    theme.bgImage && theme.bgMediaType === 'image' && theme.bgImage.startsWith('data:image/')
      ? `url("${theme.bgImage}")`
      : 'none',
  )
  root.setProperty('--xb-custom-image-opacity', theme.bgImage && theme.bgMediaType === 'image' ? '1' : '0')
  root.setProperty('--xb-image-overlay', String(theme.imageOverlay / 100))
  root.setProperty('--xb-particle-opacity', theme.particles ? '0.62' : '0')
  root.setProperty('--xb-particle-size', `${theme.particleSize}px`)
}

function applyTheme(name: ThemeName, customTheme: CustomTheme = readStoredCustomTheme()) {
  if (typeof document === 'undefined') return
  if (name === 'custom') {
    applyCustomThemeVars(customTheme)
  } else {
    clearCustomThemeVars()
  }
  document.documentElement.dataset.theme = name
}

export function applyStoredThemeBeforeMount() {
  applyTheme(readStoredTheme(), readStoredCustomTheme())
}

function persistTheme(name: ThemeName, customTheme?: CustomTheme) {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, name)
    if (customTheme) localStorage.setItem(CUSTOM_STORAGE_KEY, JSON.stringify(customTheme))
  } catch {
    /* ignore persistence errors */
  }
}

function chromeThemeFor(name: ThemeName, customTheme: CustomTheme): 'cyber' | 'anime' {
  if (name === 'custom') return luminance(customTheme.bg) > 0.5 ? 'anime' : 'cyber'
  return name
}

function isDarkVisualTheme(name: ThemeName, customTheme: CustomTheme): boolean {
  if (name === 'custom') return luminance(customTheme.bg) <= 0.5
  return name === 'cyber'
}

/** 通知 pywebview 后端给原生窗口标题栏/边框上色（桌面运行时才有 pywebview）。 */
function syncWindowChrome(name: ThemeName, customTheme: CustomTheme) {
  if (typeof window === 'undefined') return
  const api = (window as unknown as { pywebview?: { api?: { apply_window_theme?: (t: string) => Promise<unknown> } } }).pywebview?.api
  if (api?.apply_window_theme) {
    Promise.resolve(api.apply_window_theme(chromeThemeFor(name, customTheme))).catch(() => {})
  }
}

function shouldReduceMotion() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function transitionOrigin(event?: MouseEvent) {
  if (typeof window === 'undefined') return { x: 0, y: 0, radius: 0 }
  const x = event?.clientX ?? window.innerWidth - 72
  const y = event?.clientY ?? 32
  const right = window.innerWidth - x
  const bottom = window.innerHeight - y
  return {
    x,
    y,
    radius: Math.ceil(Math.hypot(Math.max(x, right), Math.max(y, bottom))) + 32,
  }
}

function captureThemeVars(target: HTMLElement) {
  const styles = window.getComputedStyle(document.documentElement)
  for (const name of CUSTOM_CSS_VARS) {
    const value = styles.getPropertyValue(name)
    if (value) target.style.setProperty(name, value)
  }
  const font = styles.getPropertyValue('--xb-font')
  if (font) target.style.setProperty('--xb-font', font)
  target.style.background = styles.getPropertyValue('--xb-bg') || window.getComputedStyle(document.body).backgroundColor
}

function createThemeSnapshot() {
  document.querySelectorAll('.theme-snapshot-overlay').forEach((node) => node.remove())
  const app = document.getElementById('app')
  if (!app) return null

  const overlay = document.createElement('div')
  overlay.className = 'theme-snapshot-overlay'
  overlay.setAttribute('aria-hidden', 'true')
  captureThemeVars(overlay)
  overlay.appendChild(app.cloneNode(true))
  document.body.appendChild(overlay)
  overlay.scrollTo(window.scrollX, window.scrollY)
  return overlay
}

function setSnapshotHole(overlay: HTMLElement, x: number, y: number, radius: number) {
  const r = Math.max(0, radius)
  const feather = Math.min(24, Math.max(1, r * 0.08))
  const mask = `radial-gradient(circle at ${x}px ${y}px, transparent ${Math.max(0, r - feather)}px, #000 ${r}px)`
  overlay.style.maskImage = mask
  overlay.style.webkitMaskImage = mask
}

function animateSnapshotReveal(overlay: HTMLElement, x: number, y: number, radius: number): Promise<void> {
  return new Promise((resolve) => {
    const start = performance.now()
    const easeOutCubic = (t: number) => 1 - (1 - t) ** 3

    function frame(now: number) {
      const progress = Math.min(1, (now - start) / THEME_TRANSITION_DURATION)
      setSnapshotHole(overlay, x, y, radius * easeOutCubic(progress))
      if (progress < 1) {
        window.requestAnimationFrame(frame)
      } else {
        overlay.remove()
        resolve()
      }
    }

    setSnapshotHole(overlay, x, y, 0)
    window.requestAnimationFrame(frame)
  })
}

function runThemeTransition(
  commit: () => void,
  event?: MouseEvent,
  direction: ThemeTransitionDirection = 'expand-new',
  onFinished: () => void = () => {},
) {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    commit()
    onFinished()
    return
  }
  if (shouldReduceMotion()) {
    commit()
    onFinished()
    return
  }

  const { x, y, radius } = transitionOrigin(event)
  const doc = document as ViewTransitionDocument
  if (doc.startViewTransition) {
    const layerClass = direction === 'contract-old' ? 'theme-transition-contract' : 'theme-transition-expand'
    const fromBg = window.getComputedStyle(document.documentElement).getPropertyValue('--xb-bg').trim()
    document.documentElement.style.setProperty('--theme-transition-x', `${x}px`)
    document.documentElement.style.setProperty('--theme-transition-y', `${y}px`)
    document.documentElement.style.setProperty('--theme-transition-radius', `${radius}px`)
    document.documentElement.style.setProperty('--theme-transition-from-bg', fromBg || window.getComputedStyle(document.body).backgroundColor)
    document.documentElement.classList.add('theme-transitioning', layerClass)

    const cleanup = () => {
      document.documentElement.classList.remove('theme-transitioning', layerClass)
      document.documentElement.style.removeProperty('--theme-transition-x')
      document.documentElement.style.removeProperty('--theme-transition-y')
      document.documentElement.style.removeProperty('--theme-transition-radius')
      document.documentElement.style.removeProperty('--theme-transition-from-bg')
      document.documentElement.style.removeProperty('--theme-transition-to-bg')
      onFinished()
    }

    try {
      const transition = doc.startViewTransition(async () => {
        commit()
        await nextTick()
        const toBg = window.getComputedStyle(document.documentElement).getPropertyValue('--xb-bg').trim()
        document.documentElement.style.setProperty('--theme-transition-to-bg', toBg || window.getComputedStyle(document.body).backgroundColor)
      })

      transition.ready
        .then(() => {
          const clipPath = [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]
          const pseudoElement = direction === 'contract-old' ? '::view-transition-old(root)' : '::view-transition-new(root)'
          const options: KeyframeAnimationOptions & { pseudoElement?: string } = {
            duration: THEME_TRANSITION_DURATION,
            easing: THEME_TRANSITION_EASING,
            fill: 'both',
            pseudoElement,
          }
          document.documentElement.animate(
            {
              clipPath: direction === 'contract-old' ? [...clipPath].reverse() : clipPath,
            },
            options,
          )
        })
        .catch(() => {})
      transition.finished.then(() => window.requestAnimationFrame(cleanup), cleanup)
      return
    } catch {
      document.documentElement.classList.remove('theme-transitioning', layerClass)
    }
  }

  const snapshot = createThemeSnapshot()
  if (!snapshot) {
    commit()
    onFinished()
    return
  }
  document.documentElement.classList.add('theme-transitioning')
  commit()
  nextTick()
    .then(() => animateSnapshotReveal(snapshot, x, y, radius))
    .finally(() => {
      snapshot.remove()
      document.documentElement.classList.remove('theme-transitioning')
      onFinished()
    })
}

export function cloneCustomTheme(theme: CustomTheme): CustomTheme {
  return { ...theme }
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeName>(readStoredTheme())
  const customTheme = ref<CustomTheme>(readStoredCustomTheme())
  const themeLabel = computed(() => (theme.value === 'custom' ? customTheme.value.name : THEMES.find((t) => t.value === theme.value)?.label ?? '主题'))

  function commitTheme(name: ThemeName, nextCustomTheme = customTheme.value, persist = true, syncChrome = true) {
    const cleanCustomTheme = sanitizeCustomTheme(nextCustomTheme)
    theme.value = name
    customTheme.value = cleanCustomTheme
    applyTheme(name, cleanCustomTheme)
    if (syncChrome) syncWindowChrome(name, cleanCustomTheme)
    if (persist) persistTheme(name, name === 'custom' ? cleanCustomTheme : undefined)
  }

  function setTheme(name: ThemeName, options: ThemeTransitionOptions = {}) {
    if (name === theme.value && name !== 'custom') return
    const nextCustomTheme = sanitizeCustomTheme(customTheme.value)
    const direction: ThemeTransitionDirection = isDarkVisualTheme(name, nextCustomTheme) ? 'expand-new' : 'contract-old'
    runThemeTransition(
      () => commitTheme(name, nextCustomTheme, true, false),
      options.event,
      direction,
      () => syncWindowChrome(name, nextCustomTheme),
    )
  }

  function toggle(event?: MouseEvent) {
    setTheme(theme.value === 'cyber' ? 'anime' : 'cyber', { event })
  }

  function previewCustomTheme(value: CustomTheme, options: ThemeTransitionOptions = {}) {
    const nextCustomTheme = sanitizeCustomTheme(value)
    const direction: ThemeTransitionDirection = isDarkVisualTheme('custom', nextCustomTheme) ? 'expand-new' : 'contract-old'
    runThemeTransition(
      () => commitTheme('custom', nextCustomTheme, false, false),
      options.event,
      direction,
      () => syncWindowChrome('custom', nextCustomTheme),
    )
  }

  function saveCustomTheme(value: CustomTheme, options: ThemeTransitionOptions = {}) {
    const nextCustomTheme = sanitizeCustomTheme(value)
    const direction: ThemeTransitionDirection = isDarkVisualTheme('custom', nextCustomTheme) ? 'expand-new' : 'contract-old'
    runThemeTransition(
      () => commitTheme('custom', nextCustomTheme, true, false),
      options.event,
      direction,
      () => syncWindowChrome('custom', nextCustomTheme),
    )
  }

  function resetCustomTheme(options: ThemeTransitionOptions = {}) {
    const nextCustomTheme = { ...DEFAULT_CUSTOM_THEME }
    const direction: ThemeTransitionDirection = isDarkVisualTheme('custom', nextCustomTheme) ? 'expand-new' : 'contract-old'
    runThemeTransition(
      () => commitTheme('custom', nextCustomTheme, true, false),
      options.event,
      direction,
      () => syncWindowChrome('custom', nextCustomTheme),
    )
  }

  // 确保初始 DOM 与状态一致
  applyTheme(theme.value, customTheme.value)

  // pywebview 就绪后同步原生窗口外观（桌面端）；若已就绪则立即同步
  if (typeof window !== 'undefined') {
    window.addEventListener('pywebviewready', () => syncWindowChrome(theme.value, customTheme.value))
    if ((window as unknown as { pywebview?: unknown }).pywebview) {
      syncWindowChrome(theme.value, customTheme.value)
    }
  }

  return {
    theme,
    customTheme,
    themeLabel,
    setTheme,
    toggle,
    previewCustomTheme,
    saveCustomTheme,
    resetCustomTheme,
  }
})
