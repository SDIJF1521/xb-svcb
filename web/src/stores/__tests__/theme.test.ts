import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
})
