/** 播放队列的纯函数规则：四种模式、随机顺序与重排。 */

import type { PlayMode } from './types'

export const PLAY_MODES: PlayMode[] = ['order', 'repeat', 'single', 'shuffle']

export const PLAY_MODE_LABELS: Record<PlayMode, string> = {
  order: '顺序播放',
  repeat: '列表循环',
  single: '单曲循环',
  shuffle: '随机播放',
}

export const PLAY_MODE_HINTS: Record<PlayMode, string> = {
  order: '按队列顺序播完最后一首后停止',
  repeat: '播完最后一首后回到第一首继续',
  single: '当前歌曲播完自动重播',
  shuffle: '随机打乱队列，播完继续新一轮',
}

export function nextPlayMode(mode: PlayMode): PlayMode {
  const index = PLAY_MODES.indexOf(mode)
  return PLAY_MODES[(index + 1) % PLAY_MODES.length] as PlayMode
}

/** 是否为合法的随机顺序（包含全部歌曲且不重复）。 */
export function shuffleOrderValid(order: string[], keys: string[]): boolean {
  if (order.length !== keys.length) return false
  const expected = new Set(keys)
  const seen = new Set<string>()
  for (const key of order) {
    if (!expected.has(key) || seen.has(key)) return false
    seen.add(key)
  }
  return true
}

/**
 * 生成随机顺序：当前歌曲固定在最前，其余 Fisher–Yates 洗牌。
 * 单曲队列直接返回自身。
 */
export function buildShuffleOrder(
  keys: string[],
  currentKey: string,
  random: () => number = Math.random,
): string[] {
  if (keys.length <= 1) return [...keys]
  const rest = keys.filter((key) => key !== currentKey)
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1))
    const a = rest[i] as string
    const b = rest[j] as string
    rest[i] = b
    rest[j] = a
  }
  return currentKey && keys.includes(currentKey)
    ? [currentKey, ...rest]
    : [...keys]
}

/**
 * 下一首的键。
 *
 * - order：到最后一首后返回 null（自动结束）。
 * - repeat：到最后一首后回到第一首。
 * - single：手动切歌按顺序走，到末尾回到开头（自动重播由播放器处理）。
 * - shuffle：按随机顺序循环，永不返回 null（随机播放可一直进行）。
 */
export function resolveNextKey(params: {
  keys: string[]
  currentKey: string
  mode: PlayMode
  shuffleOrder: string[]
}): string | null {
  const { keys, currentKey, mode, shuffleOrder } = params
  if (!keys.length) return null
  if (mode === 'shuffle') {
    const order = shuffleOrderValid(shuffleOrder, keys) ? shuffleOrder : keys
    const position = order.indexOf(currentKey)
    if (position < 0) return order[0] ?? keys[0] ?? null
    return order[(position + 1) % order.length] ?? keys[0] ?? null
  }
  const index = keys.indexOf(currentKey)
  if (index < 0) return keys[0] ?? null
  if (index + 1 < keys.length) return keys[index + 1] ?? null
  return mode === 'order' ? null : (keys[0] ?? null)
}

/** 上一首的键；order 模式在开头返回 null，其它模式循环。 */
export function resolvePreviousKey(params: {
  keys: string[]
  currentKey: string
  mode: PlayMode
  shuffleOrder: string[]
}): string | null {
  const { keys, currentKey, mode, shuffleOrder } = params
  if (!keys.length) return null
  if (mode === 'shuffle') {
    const order = shuffleOrderValid(shuffleOrder, keys) ? shuffleOrder : keys
    const position = order.indexOf(currentKey)
    if (position < 0) return order[0] ?? keys[0] ?? null
    return order[(position - 1 + order.length) % order.length] ?? keys[0] ?? null
  }
  const index = keys.indexOf(currentKey)
  if (index < 0) return keys[0] ?? null
  if (index > 0) return keys[index - 1] ?? null
  return mode === 'order' ? null : (keys[keys.length - 1] ?? null)
}

/** 把列表中的一项从 from 移到 to（返回新数组，越界时原样返回）。 */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to) return [...list]
  if (from < 0 || from >= list.length || to < 0 || to >= list.length) return [...list]
  const next = [...list]
  const [item] = next.splice(from, 1)
  if (item === undefined) return next
  next.splice(to, 0, item)
  return next
}
