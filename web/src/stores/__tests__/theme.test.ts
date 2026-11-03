import { createPinia, setActivePinia } from 'pinia'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import CustomThemeEditor from '@/components/theme/CustomThemeEditor.vue'
import ThemeSwitcher from '@/components/theme/ThemeSwitcher.vue'
import { DEFAULT_CUSTOM_THEME, THEMES, useThemeStore } from '@/stores/theme'

type TestViewTransition = {
  ready: Promise<void>
  finished: Promise<void>
}

describe('theme transitions', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('xb-theme', 'anime')
    document.body.innerHTML = '<div id="app"></div>'
    document.documentElement.className = ''
    document.documentElement.removeAttribute('style')
    setActivePinia(createPinia())
  })

  afterEach(() => {
    Reflect.deleteProperty(document, 'startViewTransition')
    Reflect.deleteProperty(document.documentElement, 'animate')
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses the native snapshot when revealing the dark theme', async () => {
    let finishTransition = () => {}
    const finished = new Promise<void>((resolve) => {
      finishTransition = resolve
    })
    const animate = vi.fn(() => ({}) as Animation)
    const startViewTransition = vi.fn((callback: () => void | Promise<void>): TestViewTransition => {
      const ready = Promise.resolve(callback()).then(() => undefined)
      return { ready, finished }
    })

    Object.defineProperty(document, 'startViewTransition', {
      configurable: true,
      value: startViewTransition,
    })
    Object.defineProperty(document.documentElement, 'animate', {
      configurable: true,
      value: animate,
    })
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(performance.now())
      return 1
    })

    const store = useThemeStore()
    store.setTheme('cyber', { event: new MouseEvent('click', { clientX: 120, clientY: 32 }) })
    await nextTick()
    await vi.waitFor(() => expect(animate).toHaveBeenCalledOnce())

    expect(startViewTransition).toHaveBeenCalledOnce()
    expect(store.theme).toBe('cyber')
    expect(document.documentElement.dataset.theme).toBe('cyber')
    expect(animate).toHaveBeenCalledWith(
      expect.objectContaining({
        clipPath: expect.arrayContaining([
          'circle(0px at 120px 32px)',
          expect.stringMatching(/^circle\(\d+px at 120px 32px\)$/),
        ]),
      }),
      expect.objectContaining({
        duration: 480,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        pseudoElement: '::view-transition-new(root)',
      }),
    )

    finishTransition()
    await Promise.resolve()
    await Promise.resolve()
    expect(document.documentElement.classList.contains('theme-transitioning')).toBe(false)
  })

  it('commits the latest theme when a transition is interrupted by a rapid switch', async () => {
    let finishTransition = () => {}
    const finished = new Promise<void>((resolve) => {
      finishTransition = resolve
    })
    let transitionCalls = 0
    const startViewTransition = vi.fn((callback: () => void | Promise<void>): TestViewTransition => {
      transitionCalls += 1
      if (transitionCalls > 1) throw new Error('transition already running')
      const ready = Promise.resolve(callback()).then(() => undefined)
      return { ready, finished }
    })

    Object.defineProperty(document, 'startViewTransition', {
      configurable: true,
      value: startViewTransition,
    })

    const store = useThemeStore()
    store.setTheme('cyber')
    store.setTheme('anime')

    expect(store.theme).toBe('anime')
    expect(document.documentElement.dataset.theme).toBe('anime')
    expect(startViewTransition).toHaveBeenCalledTimes(2)

    finishTransition()
    await Promise.resolve()
    await Promise.resolve()
    expect(document.documentElement.classList.contains('theme-transitioning')).toBe(false)
  })

  it('applies and persists background media changes immediately', () => {
    localStorage.setItem('xb-theme', 'custom')
    localStorage.setItem('xb-custom-theme', JSON.stringify({
      name: 'Media test',
      bgImage: 'old-background.png',
      bgMediaType: 'image',
    }))
    setActivePinia(createPinia())
    const store = useThemeStore()

    store.saveCustomTheme({
      ...store.customTheme,
      bgImage: 'new-background.png',
      bgMediaType: 'image',
    })

    expect(store.theme).toBe('custom')
    expect(store.customTheme.bgImage).toBe('new-background.png')
    expect(document.documentElement.dataset.theme).toBe('custom')
    expect(JSON.parse(localStorage.getItem('xb-custom-theme') || '{}').bgImage).toBe('new-background.png')

    store.saveCustomTheme({
      ...store.customTheme,
      bgImage: '',
      bgMediaType: 'image',
    })

    expect(store.customTheme.bgImage).toBe('')
    expect(document.documentElement.style.getPropertyValue('--xb-custom-image-opacity')).toBe('0')
    expect(JSON.parse(localStorage.getItem('xb-custom-theme') || '{}').bgImage).toBe('')
  })

  it('applies and persists the XB brand theme', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
    const store = useThemeStore()

    store.setTheme('brand')

    expect(store.theme).toBe('brand')
    expect(document.documentElement.dataset.theme).toBe('brand')
    expect(localStorage.getItem('xb-theme')).toBe('brand')
    expect(THEMES.find((item) => item.value === 'brand')?.label).toBe('XB 声纹')
  })

  it('uses XB brand as the first and default theme', () => {
    localStorage.removeItem('xb-theme')
    setActivePinia(createPinia())

    const store = useThemeStore()

    expect(THEMES[0]?.value).toBe('brand')
    expect(store.theme).toBe('brand')
    expect(document.documentElement.dataset.theme).toBe('brand')
  })

  it('restores a temporary sky garden palette to the original bright defaults', () => {
    localStorage.setItem('xb-theme', 'custom')
    localStorage.setItem('xb-custom-theme', JSON.stringify({
      name: '晴空花园',
      bg: '#f6fbfd',
      bg2: '#e8f4f5',
      text: '#173847',
      muted: '#587686',
      primary: '#0f719e',
      primary2: '#1f7a5d',
      accent: '#c63f63',
      onPrimary: '#ffffff',
      fill: '#244b59',
      success: '#1d815f',
      warn: '#b96c22',
      bgImage: 'garden-background.png',
      bgMediaType: 'image',
      imageOverlay: 42,
      particles: false,
      particleDensity: 12,
      particleSize: 4,
    }))
    setActivePinia(createPinia())

    const store = useThemeStore()
    const persisted = JSON.parse(localStorage.getItem('xb-custom-theme') || '{}')

    expect(store.customTheme.bg).toBe(DEFAULT_CUSTOM_THEME.bg)
    expect(store.customTheme.primary).toBe(DEFAULT_CUSTOM_THEME.primary)
    expect(store.customTheme.primary2).toBe(DEFAULT_CUSTOM_THEME.primary2)
    expect(store.customTheme.accent).toBe(DEFAULT_CUSTOM_THEME.accent)
    expect(store.customTheme.bgImage).toBe('garden-background.png')
    expect(store.customTheme.imageOverlay).toBe(42)
    expect(store.customTheme.particles).toBe(false)
    expect(persisted.primary).toBe(DEFAULT_CUSTOM_THEME.primary)
    expect(document.documentElement.style.getPropertyValue('--xb-orb-opacity')).toBe('0.42')
    expect(document.documentElement.style.getPropertyValue('--xb-grid-opacity')).toBe('0.045')
  })

  it('removes the active background immediately from the theme editor', async () => {
    localStorage.setItem('xb-theme', 'custom')
    localStorage.setItem('xb-custom-theme', JSON.stringify({
      name: 'Remove test',
      bgImage: 'stored-background.png',
      bgMediaType: 'image',
    }))
    setActivePinia(createPinia())
    const deleteMedia = vi.spyOn(api, 'deleteThemeMediaFile').mockResolvedValue(true)
    const wrapper = shallowMount(ThemeSwitcher)
    const store = useThemeStore()

    await wrapper.get('.theme-edit').trigger('click')
    const editor = wrapper.getComponent(CustomThemeEditor)
    editor.vm.$emit('update:modelValue', {
      ...store.customTheme,
      bgImage: '',
      bgMediaType: 'image',
    })
    await nextTick()

    expect(store.customTheme.bgImage).toBe('')
    expect(JSON.parse(localStorage.getItem('xb-custom-theme') || '{}').bgImage).toBe('')
    expect(deleteMedia).toHaveBeenCalledWith('stored-background.png')
    wrapper.unmount()
  })
})
