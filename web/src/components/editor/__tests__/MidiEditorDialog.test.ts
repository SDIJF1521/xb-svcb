import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import MidiEditorDialog from '@/components/editor/MidiEditorDialog.vue'
import { DRUM_PIECES } from '@/utils/midi'
import type { EditorMidiSession } from '@/api/types'

const notes = Array.from({ length: 8 }, (_, index) => ({
  id: `n${index + 1}`,
  start: index * 12,
  end: index * 12 + 1.2,
  pitch: 60 + index,
  detune: 0,
}))

/** 等一轮宏任务 + nextTick：对话框挂载后会在 nextTick 里量视口、画布。 */
async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

afterEach(() => {
  // teleport 出去的节点不归 wrapper 管，失败用例也要清理干净，避免互相串。
  document.querySelectorAll('.midi-mask').forEach((element) => element.remove())
})

/**
 * 对话框会 teleport 到 body（避免被页面顶栏的堆叠上下文压住），
 * 所以这里统一从 body 里查真实 DOM，而不是从 wrapper 根节点。
 */
function dialogRoot(): HTMLElement {
  const masks = document.querySelectorAll('.midi-mask')
  const element = masks[masks.length - 1]
  if (!element) throw new Error('MIDI 对话框没有渲染到 body')
  return element as HTMLElement
}

function findAll(selector: string): HTMLElement[] {
  return Array.from(dialogRoot().querySelectorAll(selector)) as HTMLElement[]
}

function findByText(selector: string, text: string): HTMLElement | undefined {
  return findAll(selector).find((element) => (element.textContent || '').includes(text))
}

function mountDialog(duration: number) {
  return mount(MidiEditorDialog, {
    props: {
      modelValue: true,
      mode: 'pitch' as const,
      scope: 'clip' as const,
      clipName: 'instrumental',
      duration,
      notes,
      ready: true,
    },
    attachTo: document.body,
  })
}

const composeSession: EditorMidiSession = {
  version: 1,
  tempo: 120,
  time_signature: [4, 4],
  parts: [
    {
      id: 'part_1',
      name: '钢琴',
      instrument: 0,
      drum: false,
      channel: 0,
      volume: 1,
      pan: 0,
      mute: false,
      solo: false,
      color: '#5ec2ff',
      notes: [
        { id: 'a', start: 0, end: 0.5, pitch: 60, velocity: 100 },
        { id: 'b', start: 0.5, end: 1, pitch: 64, velocity: 80 },
      ],
    },
    {
      id: 'part_2',
      name: '贝斯',
      instrument: 33,
      drum: false,
      channel: 1,
      volume: 1,
      pan: 0,
      mute: false,
      solo: false,
      color: '#ffb454',
      notes: [{ id: 'c', start: 0, end: 1, pitch: 36, velocity: 90 }],
    },
  ],
}

function mountCompose(extra: Record<string, unknown> = {}) {
  return mount(MidiEditorDialog, {
    props: {
      modelValue: true,
      mode: 'compose' as const,
      scope: 'track' as const,
      trackName: '合成器',
      duration: 60,
      composeDuration: 60,
      composeSession,
      hasAudio: false,
      ...extra,
    },
    attachTo: document.body,
  })
}

const drumPart: EditorMidiSession = {
  version: 1,
  tempo: 120,
  time_signature: [4, 4],
  parts: [
    {
      id: 'drums',
      name: '架子鼓',
      instrument: 0,
      drum: true,
      channel: 9,
      volume: 1,
      pan: 0,
      mute: false,
      solo: false,
      color: '#ffb454',
      notes: [
        { id: 'k', start: 0, end: 0.2, pitch: 36, velocity: 118 },
        { id: 's', start: 0.5, end: 0.7, pitch: 38, velocity: 104 },
      ],
    },
  ],
}

function mountDrumCompose() {
  return mount(MidiEditorDialog, {
    props: {
      modelValue: true,
      mode: 'compose' as const,
      scope: 'track' as const,
      trackName: '架子鼓',
      duration: 60,
      composeDuration: 60,
      composeSession: drumPart,
      hasAudio: false,
    },
    attachTo: document.body,
  })
}

describe('MidiEditorDialog 架子鼓', () => {
  it('鼓组声部显示鼓组标识而不是乐器下拉，并提供填充节奏', async () => {
    const wrapper = mountDrumCompose()
    await flush()

    const part = findAll('.midi-part')[0]!
    expect(part.textContent).toContain('架子鼓 · GM 鼓组')
    expect(part.querySelector('select.midi-part-inst')).toBeNull()
    expect(part.textContent).toContain('2 件')
    const fillButton = findByText('.midi-part-drum button', '填充节奏')
    expect(fillButton).toBeTruthy()

    wrapper.unmount()
  })

  it('填充节奏会写入底鼓/军鼓/踩镲', async () => {
    const wrapper = mountDrumCompose()
    await flush()

    findByText('.midi-part-drum button', '填充节奏')!.click()
    await flush()

    // 2 小节基础节奏 = 24 个音符，加上原有的 2 个，共 26
    const part = findAll('.midi-part')[0]!
    expect(part.textContent).toContain('26 件')
    const session = wrapper.emitted('save-session')
    expect(session).toBeUndefined()
    // 保存时把鼓件音高交给后端（都在 35~81 的鼓件上）
    findByText('.midi-actions button', '保存编曲')!.click()
    await flush()
    const payload = wrapper.emitted('save-session')?.[0]?.[0] as EditorMidiSession
    expect(payload).toBeTruthy()
    const notes = payload.parts[0]!.notes
    expect(notes.length).toBe(26)
    const allDrumPitches = new Set(DRUM_PIECES.map((piece) => piece.pitch))
    expect(notes.every((note) => allDrumPitches.has(note.pitch))).toBe(true)
    expect(notes.some((note) => note.pitch === 36)).toBe(true)
    expect(notes.some((note) => note.pitch === 38)).toBe(true)
    expect(notes.some((note) => note.pitch === 42)).toBe(true)

    wrapper.unmount()
  })

  it('「＋ 鼓组」新增的声部就是架子鼓', async () => {
    const wrapper = mountCompose()
    await flush()

    findByText('.midi-parts-foot button', '鼓组')!.click()
    await flush()

    const parts = findAll('.midi-part')
    expect(parts).toHaveLength(3)
    expect(parts[2]!.textContent).toContain('架子鼓')
    expect(parts[2]!.querySelector('select.midi-part-inst')).toBeNull()

    wrapper.unmount()
  })
})

describe('MidiEditorDialog 层级与全屏', () => {
  it('把对话框挂到 body 上，不会被顶栏压住', async () => {
    const wrapper = mountCompose()
    await flush()

    expect(dialogRoot().parentElement).toBe(document.body)
    wrapper.unmount()
    expect(document.querySelector('.midi-mask')).toBeNull()
  })

  it('支持全屏切换，再点一次还原', async () => {
    const wrapper = mountCompose()
    await flush()

    const fullscreenButton = findByText('.midi-head-actions button', '全屏')
    expect(fullscreenButton).toBeTruthy()
    fullscreenButton!.click()
    await flush()
    expect(dialogRoot().classList.contains('fullscreen')).toBe(true)
    expect(document.querySelector('.midi-dialog.fullscreen')).not.toBeNull()

    const restoreButton = findByText('.midi-head-actions button', '退出全屏')
    expect(restoreButton).toBeTruthy()
    restoreButton!.click()
    await flush()
    expect(dialogRoot().classList.contains('fullscreen')).toBe(false)

    wrapper.unmount()
  })

  it('缩放控件同时提供横向与音域缩放', async () => {
    const wrapper = mountCompose()
    await flush()

    const before = dialogRoot().querySelector('.midi-zoom')?.textContent || ''
    expect(before).toContain('px/s')
    expect(before).toContain('px')
    const zoomIn = findAll('.midi-zoom button').find((button) => button.textContent?.includes('＋'))
    expect(zoomIn).toBeTruthy()
    zoomIn!.click()
    await flush()
    const after = dialogRoot().querySelector('.midi-zoom')?.textContent || ''
    expect(after).not.toBe(before)

    wrapper.unmount()
  })
})

describe('MidiEditorDialog 画布尺寸', () => {
  it('长片段仍按视口分配画布，靠占位层滚动', async () => {
    const wrapper = mountDialog(160)
    await flush()

    const grid = dialogRoot().querySelector('canvas.midi-grid') as HTMLCanvasElement
    expect(grid).not.toBeNull()
    const dpr = Math.max(1, Math.round(window.devicePixelRatio || 1))
    const width = Number(grid.getAttribute('width'))
    const height = Number(grid.getAttribute('height'))
    expect(width).toBeLessThanOrEqual(320 * dpr)
    expect(height).toBeLessThanOrEqual(320 * dpr)

    const filler = dialogRoot().querySelector('.midi-filler') as HTMLElement
    const fillerWidth = Number.parseFloat(
      String(filler.getAttribute('style') || '').match(/width:\s*([\d.]+)px/)?.[1] || '0',
    )
    expect(fillerWidth).toBeGreaterThan(width)

    wrapper.unmount()
  })

  it('渲染钢琴键盘与音符统计', async () => {
    const wrapper = mountDialog(30)
    await flush()
    expect(dialogRoot().querySelector('canvas.midi-keys')).not.toBeNull()
    expect(dialogRoot().textContent).toContain('个音符')
    wrapper.unmount()
  })
})

describe('MidiEditorDialog 编曲模式', () => {
  it('渲染期间显示进度条与百分比', async () => {
    const wrapper = mountCompose({
      renderProgress: { percent: 42, message: '渲染声部 2/4' },
    })
    await flush()

    const bar = dialogRoot().querySelector('.midi-render-bar i') as HTMLElement | null
    expect(bar).not.toBeNull()
    expect(bar!.getAttribute('style') || '').toContain('42%')
    expect(dialogRoot().textContent).toContain('渲染声部 2/4')
    expect(dialogRoot().textContent).toContain('42%')

    wrapper.unmount()
  })

  it('列出每个声部与乐器、音符数', async () => {
    const wrapper = mountCompose()
    await flush()

    expect(dialogRoot().textContent).toContain('MIDI 编曲')
    expect(dialogRoot().textContent).toContain('2 声部')
    const parts = findAll('.midi-part')
    expect(parts).toHaveLength(2)
    const firstName = parts[0]!.querySelector('input.midi-part-name') as HTMLInputElement
    expect(firstName.value).toBe('钢琴')
    expect(parts[0]!.textContent).toContain('2 个音')
    expect(findByText('.midi-actions button', '渲染为分乐器音轨')).toBeTruthy()
    expect(dialogRoot().querySelector('canvas.midi-velocity')).not.toBeNull()

    wrapper.unmount()
  })

  it('乐器选择器给出具体乐器名，没有编号占位', async () => {
    const wrapper = mountCompose()
    await flush()

    const selects = findAll('select.midi-part-inst') as HTMLSelectElement[]
    expect(selects.length).toBe(2)
    const labels = Array.from(selects[0]!.options).map((option) => option.textContent || '')
    expect(labels).toContain('原声大钢琴')
    expect(labels).toContain('小提琴')
    expect(labels).toContain('西塔琴')
    expect(labels.some((label) => /^(钢琴|贝斯)\s*\d+$/.test(label))).toBe(false)
    expect(selects[0]!.value).toBe('0')

    wrapper.unmount()
  })

  it('可以新增声部并发出渲染/导出请求', async () => {
    const wrapper = mountCompose()
    await flush()

    const addButton = findByText('.midi-parts-foot button', '新声部')
    expect(addButton).toBeTruthy()
    addButton!.click()
    await flush()
    expect(findAll('.midi-part')).toHaveLength(3)

    findByText('.midi-actions button', '渲染为分乐器音轨')!.click()
    await flush()
    const emitted = wrapper.emitted('render-session')
    expect(emitted).toBeTruthy()
    expect(emitted![0]![1]).toBe('tracks')

    findByText('.midi-actions button', '导出 .mid')!.click()
    await flush()
    expect(wrapper.emitted('export-session')).toBeTruthy()

    wrapper.unmount()
  })

  it('只有存在音频时才能切到演唱音准模式', async () => {
    const audioWrapper = mount(MidiEditorDialog, {
      props: {
        modelValue: true,
        mode: 'compose' as const,
        scope: 'track' as const,
        duration: 30,
        composeSession,
        hasAudio: true,
      },
      attachTo: document.body,
    })
    await flush()
    const pitchButton = findByText('.midi-modes button', '演唱音准') as HTMLButtonElement
    expect(pitchButton.disabled).toBe(false)
    pitchButton.click()
    await flush()
    expect(audioWrapper.emitted('update:mode')?.[0]).toEqual(['pitch'])
    audioWrapper.unmount()

    const emptyWrapper = mountCompose()
    await flush()
    const disabledButton = findByText('.midi-modes button', '演唱音准') as HTMLButtonElement
    expect(disabledButton.disabled).toBe(true)
    emptyWrapper.unmount()
  })
})
