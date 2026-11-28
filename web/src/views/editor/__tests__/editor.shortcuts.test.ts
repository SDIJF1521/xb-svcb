// 音频编辑页删除片段快捷键回归测试。
//
// 背景：快捷键挂在 window 上，只有 event.target 是真正能输入文字的控件时才应该放过。
// 之前 target 只要落在 input/textarea/select 上就 return，导致点过「角色」下拉框、
// 复选框、音量滑块之后再按 Delete 完全没反应，用户感知就是「删除片段的快捷键失效」。
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { project: 'edt_shortcut' } }),
  useRouter: () => ({
    replace: () => Promise.resolve(undefined),
    push: () => Promise.resolve(undefined),
  }),
}))

function makeClip(id: string, start: number, end: number, locked = false) {
  return {
    id,
    name: id,
    start,
    end,
    offset: 0,
    volume: 1,
    mute: false,
    file: 'C:/music/demo.wav',
    effects: [],
    locked,
    fade_in: 0,
    fade_out: 0,
    channel: 'stereo',
    metadata: {},
  }
}

const PROJECT = {
  id: 'edt_shortcut',
  title: '快捷键回归工程',
  duration: 160,
  sample_rate: 44100,
  waveform_cache: {},
  metadata: { source_path: 'C:/music/demo.wav', mode: 'mock' },
  roles: [{ id: 'role_a', name: '主唱', color: '#4f8cff', pitch: 0, notes: '' }],
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
  tracks: [
    {
      id: 'trk_a',
      name: '人声轨',
      type: 'vocal',
      volume: 1,
      mute: false,
      locked: false,
      clips: [
        makeClip('clp_a1', 0, 10),
        makeClip('clp_a2', 12, 22),
        makeClip('clp_a3', 24, 34),
      ],
    },
    {
      id: 'trk_b',
      name: 'BGM 轨',
      type: 'bgm',
      volume: 0.8,
      mute: false,
      locked: false,
      clips: [makeClip('clp_b1', 40, 60)],
    },
    {
      id: 'trk_c',
      name: '素材轨',
      type: 'audio',
      volume: 1,
      mute: false,
      locked: false,
      clips: [makeClip('clp_c1', 70, 80, true)],
    },
  ],
}

async function waitFor(condition: () => boolean, timeout = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeout) {
    if (condition()) return true
    await new Promise((resolve) => setTimeout(resolve, 30))
    await flushPromises()
  }
  return condition()
}

function dispatchDelete(target: EventTarget, key: 'Delete' | 'Backspace' = 'Delete') {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, code: key, bubbles: true, cancelable: true }))
}

function messageTexts() {
  return [...document.querySelectorAll('.el-message')].map((node) => (node.textContent || '').trim())
}

beforeAll(() => {
  const global = globalThis as unknown as Record<string, unknown>
  if (!global.ResizeObserver) {
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
  if (!window.matchMedia) {
    window.matchMedia = () => ({
      matches: false,
      media: '',
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent: () => false,
    })
  }
  if (!globalThis.URL.createObjectURL) {
    globalThis.URL.createObjectURL = () => 'blob:mock'
  }
})

describe('音频编辑页删除片段快捷键', () => {
  it('Delete / Backspace 始终能删除选中片段，而不是被焦点控件吞掉', async () => {
    localStorage.setItem(
      'xb-mock-editor-state',
      JSON.stringify({ projects: [JSON.parse(JSON.stringify(PROJECT))], midiNotes: {}, midiSessions: {} }),
    )
    const { whenReady } = await import('@/api/bridge')
    // 浏览器环境等 pywebview 注入会多等 1.5s，这里先把就绪 Promise 落定。
    await whenReady(0)
    const Editor = (await import('../editor.vue')).default
    const wrapper = mount(Editor, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
      attachTo: document.body,
    })

    expect(
      await waitFor(() => wrapper.element.querySelectorAll('.clip').length === 5),
      `编辑器未加载出片段：${wrapper.element.querySelectorAll('.clip').length}`,
    ).toBe(true)

    const root = wrapper.element as HTMLElement
    const clipCount = () => root.querySelectorAll('.clip').length
    const clickClip = async (index: number) => {
      const clips = root.querySelectorAll<HTMLElement>('.clip')
      clips[index]!.click()
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(root.querySelectorAll('.clip.selected').length, '点击后未选中片段').toBe(1)
    }

    // 1) 常规路径：焦点在页面上，Delete 删除片段。
    await clickClip(0)

    // 片段面板的数值输入框回车提交后应主动失焦，随后 Delete 才会作用于片段。
    const numberInput = root.querySelector<HTMLInputElement>('.clip-panel input[type="number"]')
    expect(numberInput, '片段面板里应存在数值输入框').not.toBeNull()
    numberInput!.focus()
    expect(document.activeElement).toBe(numberInput)
    numberInput!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }))
    await flushPromises()
    expect(document.activeElement, '回车后数值输入框应失焦').not.toBe(numberInput)

    dispatchDelete(document.body)
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(clipCount()).toBe(4)

    // 3) 回归点：焦点落在「角色」原生下拉框上（isTextEditingTarget 之前会误判成输入中）。
    await clickClip(0)
    const roleSelect = root.querySelector<HTMLElement>('.clip-panel select')
    expect(roleSelect, '片段面板里应存在角色下拉框').not.toBeNull()
    roleSelect!.focus()
    dispatchDelete(roleSelect!)
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(clipCount()).toBe(3)

    // 4) 回归点：焦点落在复选框 / 滑块这类非文本控件上。
    const checkbox = document.createElement('input')
    checkbox.type = 'checkbox'
    document.body.appendChild(checkbox)
    await clickClip(0)
    checkbox.focus()
    dispatchDelete(checkbox)
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(clipCount()).toBe(2)
    checkbox.remove()

    // 5) 文本框内 Delete 只编辑文字，不能误删片段。
    const textInput = document.createElement('input')
    textInput.type = 'number'
    document.body.appendChild(textInput)
    await clickClip(0)
    textInput.focus()
    dispatchDelete(textInput)
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(clipCount(), '文本框内的 Delete 不应删除片段').toBe(2)
    textInput.remove()

    // 6) Backspace 与 Delete 等价。
    dispatchDelete(document.body, 'Backspace')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(clipCount()).toBe(1)

    // 7) 锁定片段：不删除，但给出明确提示，而不是静默失败。
    const lockedClip = root.querySelector<HTMLElement>('.clip.locked')
    expect(lockedClip, '工程里应有锁定片段').not.toBeNull()
    lockedClip!.click()
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 20))
    dispatchDelete(document.body)
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(clipCount()).toBe(1)
    // 语言跟随浏览器（jsdom 默认 en-US），中英文提示都接受。
    expect(messageTexts().some((text) => /锁定|locked/i.test(text))).toBe(true)

    wrapper.unmount()
  }, 120000)
})
