import { createPinia, setActivePinia } from 'pinia'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import CustomThemeEditor from '@/components/theme/CustomThemeEditor.vue'
import ThemeSwitcher from '@/components/theme/ThemeSwitcher.vue'
import { useThemeStore } from '@/stores/theme'

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
