import { describe, expect, it } from 'vitest'

import {
  PLAY_MODES,
  buildShuffleOrder,
  moveItem,
  nextPlayMode,
  resolveNextKey,
  resolvePreviousKey,
  shuffleOrderValid,
} from '@/player/queue'

const keys = ['a', 'b', 'c', 'd']

describe('play mode cycling', () => {
  it('cycles through all four modes in order', () => {
    expect(PLAY_MODES).toEqual(['order', 'repeat', 'single', 'shuffle'])
    expect(nextPlayMode('order')).toBe('repeat')
    expect(nextPlayMode('repeat')).toBe('single')
    expect(nextPlayMode('single')).toBe('shuffle')
    expect(nextPlayMode('shuffle')).toBe('order')
  })
})

describe('shuffle order', () => {
  it('keeps the current track first and contains every key exactly once', () => {
    const order = buildShuffleOrder(keys, 'c', () => 0.5)
    expect(order[0]).toBe('c')
    expect(new Set(order)).toEqual(new Set(keys))
    expect(order).toHaveLength(keys.length)
    expect(shuffleOrderValid(order, keys)).toBe(true)
  })

  it('rejects incomplete or duplicated orders', () => {
    expect(shuffleOrderValid(['a', 'b'], keys)).toBe(false)
    expect(shuffleOrderValid(['a', 'b', 'c', 'c'], keys)).toBe(false)
    expect(shuffleOrderValid([], [])).toBe(true)
  })
})

describe('next / previous resolution', () => {
  it('stops at the end in order mode', () => {
    expect(
      resolveNextKey({ keys, currentKey: 'd', mode: 'order', shuffleOrder: [] }),
    ).toBeNull()
    expect(
      resolveNextKey({ keys, currentKey: 'b', mode: 'order', shuffleOrder: [] }),
    ).toBe('c')
  })

  it('wraps in repeat / single modes', () => {
    expect(
      resolveNextKey({ keys, currentKey: 'd', mode: 'repeat', shuffleOrder: [] }),
    ).toBe('a')
    expect(
      resolveNextKey({ keys, currentKey: 'd', mode: 'single', shuffleOrder: [] }),
    ).toBe('a')
    expect(
      resolvePreviousKey({ keys, currentKey: 'a', mode: 'repeat', shuffleOrder: [] }),
    ).toBe('d')
  })

  it('walks the shuffled order and loops forever', () => {
    const order = ['b', 'd', 'a', 'c']
    expect(
      resolveNextKey({ keys, currentKey: 'b', mode: 'shuffle', shuffleOrder: order }),
    ).toBe('d')
    expect(
      resolveNextKey({ keys, currentKey: 'c', mode: 'shuffle', shuffleOrder: order }),
    ).toBe('b')
    expect(
      resolvePreviousKey({ keys, currentKey: 'b', mode: 'shuffle', shuffleOrder: order }),
    ).toBe('c')
  })

  it('returns null when the queue is empty', () => {
    expect(
      resolveNextKey({ keys: [], currentKey: '', mode: 'repeat', shuffleOrder: [] }),
    ).toBeNull()
    expect(
      resolvePreviousKey({ keys: [], currentKey: '', mode: 'repeat', shuffleOrder: [] }),
    ).toBeNull()
  })
})

describe('moveItem', () => {
  it('moves an item without mutating the source', () => {
    const source = ['a', 'b', 'c']
    expect(moveItem(source, 2, 0)).toEqual(['c', 'a', 'b'])
    expect(source).toEqual(['a', 'b', 'c'])
  })

  it('ignores out-of-range indexes', () => {
    expect(moveItem(['a', 'b'], -1, 0)).toEqual(['a', 'b'])
    expect(moveItem(['a', 'b'], 0, 5)).toEqual(['a', 'b'])
  })
})
