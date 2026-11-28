/**
 * 全局快捷键的焦点判定。
 *
 * 编辑器把 Delete / Backspace、Ctrl+Z 这类快捷键挂在 window 上，事件目标就是
 * 当前获得焦点的元素。只有「正在输入文字」的控件才应该吞掉这些快捷键：
 * 复选框、单选框、滑块、原生下拉框、只读输入框都不属于文字输入，否则用户点过
 * 这些控件之后，删除片段/撤销等快捷键会静默失效，看起来就像「快捷键坏了」。
 */

/** input 里不属于「文字输入」的 type。 */
const NON_TEXT_INPUT_TYPES = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'hidden',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
])

function isTextControl(element: HTMLElement): boolean {
  if (element instanceof HTMLTextAreaElement) return true
  if (!(element instanceof HTMLInputElement)) return false
  const type = (element.type || 'text').toLowerCase()
  if (NON_TEXT_INPUT_TYPES.has(type)) return false
  // Element Plus 的 el-select 也是 input：只读时只负责展示，Delete 没有编辑语义；
  // 可筛选时下拉展开（aria-expanded）才需要把 Delete 留给筛选词。
  if (element.getAttribute('role') === 'combobox') {
    return element.getAttribute('aria-expanded') === 'true'
  }
  return true
}

/** 事件目标（或它的祖先）是不是一个正在编辑文字的控件。 */
export function isTextEditingTarget(target: EventTarget | null): boolean {
  const element = target instanceof HTMLElement ? target : null
  if (!element) return false
  if (element.isContentEditable) return true
  const editing = element.closest<HTMLElement>(
    '[contenteditable]:not([contenteditable="false"]), textarea, input',
  )
  if (!editing) return false
  // 命中的是 contenteditable 容器（不是 input/textarea）：一定可以编辑文字。
  if (!(editing instanceof HTMLInputElement || editing instanceof HTMLTextAreaElement)) return true
  // 禁用/只读字段收不到文本编辑，Delete 应该继续作用于时间轴。
  if (editing.disabled) return false
  if (editing.readOnly) {
    // Element Plus 的下拉框也是 input：只读时只负责展示，下拉展开才需要保留键盘。
    return editing.getAttribute('role') === 'combobox'
      && editing.getAttribute('aria-expanded') === 'true'
  }
  return isTextControl(editing)
}

/**
 * 是否是不带 Ctrl/Meta 的删除键（Delete 或 Backspace）。
 *
 * 输入法激活时 `event.key` 可能变成 'Process'，所以再按物理键位 `event.code`
 * 兜底，避免中文/日文输入法状态下快捷键失灵。
 */
export function isDeleteShortcut(event: KeyboardEvent): boolean {
  if (event.ctrlKey || event.metaKey) return false
  const key = (event.key || '').toLowerCase()
  if (key === 'delete' || key === 'backspace') return true
  return event.code === 'Delete' || event.code === 'Backspace'
}
