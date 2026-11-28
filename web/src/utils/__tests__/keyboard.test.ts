import { describe, expect, it } from 'vitest'

import { isDeleteShortcut, isTextEditingTarget } from '@/utils/keyboard'

function keydown(init: KeyboardEventInit) {
  return new KeyboardEvent('keydown', init)
}

describe('isTextEditingTarget', () => {
  it('treats text fields as typing targets', () => {
    const input = document.createElement('input')
    expect(isTextEditingTarget(input)).toBe(true)

    const number = document.createElement('input')
    number.type = 'number'
    expect(isTextEditingTarget(number)).toBe(true)

    const textarea = document.createElement('textarea')
    expect(isTextEditingTarget(textarea)).toBe(true)

    const editable = document.createElement('div')
    editable.setAttribute('contenteditable', 'true')
    const inner = document.createElement('span')
    editable.appendChild(inner)
    expect(isTextEditingTarget(editable)).toBe(true)
    expect(isTextEditingTarget(inner)).toBe(true)
  })

  it('does not swallow shortcuts for non-text controls', () => {
    // 点过复选框/滑块/下拉框后焦点会留在它们身上，此时 Delete 仍应删除片段。
    for (const type of ['checkbox', 'radio', 'range', 'button', 'file', 'color']) {
      const input = document.createElement('input')
      input.type = type
      expect(isTextEditingTarget(input), type).toBe(false)
    }
    expect(isTextEditingTarget(document.createElement('select'))).toBe(false)
    expect(isTextEditingTarget(document.createElement('div'))).toBe(false)
  })

  it('ignores read-only and disabled fields but keeps open comboboxes', () => {
    const readonly = document.createElement('input')
    readonly.readOnly = true
    expect(isTextEditingTarget(readonly)).toBe(false)

    const disabled = document.createElement('input')
    disabled.disabled = true
    expect(isTextEditingTarget(disabled)).toBe(false)

    // Element Plus 下拉框内部是只读 input：收起时 Delete 应继续删除片段，
    // 展开（aria-expanded）时把键盘留给下拉框自身。
    const combobox = document.createElement('input')
    combobox.setAttribute('role', 'combobox')
    combobox.readOnly = true
    expect(isTextEditingTarget(combobox)).toBe(false)
    combobox.setAttribute('aria-expanded', 'true')
    expect(isTextEditingTarget(combobox)).toBe(true)
  })

  it('returns false for non-element targets', () => {
    expect(isTextEditingTarget(null)).toBe(false)
    expect(isTextEditingTarget(window)).toBe(false)
  })
})

describe('isDeleteShortcut', () => {
  it('accepts Delete and Backspace without modifiers', () => {
    expect(isDeleteShortcut(keydown({ key: 'Delete', code: 'Delete' }))).toBe(true)
    expect(isDeleteShortcut(keydown({ key: 'Backspace', code: 'Backspace' }))).toBe(true)
  })

  it('falls back to the physical key while an IME reports Process', () => {
    expect(isDeleteShortcut(keydown({ key: 'Process', code: 'Delete' }))).toBe(true)
    expect(isDeleteShortcut(keydown({ key: 'Process', code: 'Backspace' }))).toBe(true)
  })

  it('ignores modified keys and unrelated keys', () => {
    expect(isDeleteShortcut(keydown({ key: 'Delete', code: 'Delete', ctrlKey: true }))).toBe(false)
    expect(isDeleteShortcut(keydown({ key: 'Backspace', code: 'Backspace', metaKey: true }))).toBe(false)
    expect(isDeleteShortcut(keydown({ key: 'a', code: 'KeyA' }))).toBe(false)
  })
})
