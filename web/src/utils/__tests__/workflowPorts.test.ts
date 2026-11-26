import { describe, expect, it } from 'vitest'

import { mergePortOffsets, portOffsetKey, portOffsetsEqual } from '@/utils/workflowPorts'

describe('workflow port offsets', () => {
  it('builds the same key format as the canvas template', () => {
    expect(portOffsetKey('n1', 'in', 'audio')).toBe('n1:in:audio')
    expect(portOffsetKey('n1', 'out', 'stem:vocals')).toBe('n1:out:stem:vocals')
  })

  it('merges a partial re-measure and keeps other nodes untouched', () => {
    const current = {
      'n1:in:audio': { x: 0, y: 20 },
      'n1:out:audio': { x: 268, y: 40 },
      'n2:in:audio': { x: 0, y: 300 },
      'n2:out:audio': { x: 268, y: 320 },
    }
    const measured = {
      // 展开高级参数后输出端口下移；输入端口没变。
      'n1:in:audio': { x: 0, y: 20 },
      'n1:out:audio': { x: 268, y: 520 },
      'n1:out:stem:vocal': { x: 268, y: 560 },
    }

    const merged = mergePortOffsets(current, measured, ['n1'])

    expect(merged['n1:out:audio']).toEqual({ x: 268, y: 520 })
    expect(merged['n1:out:stem:vocal']).toEqual({ x: 268, y: 560 })
    expect(merged['n1:in:audio']).toEqual({ x: 0, y: 20 })
    // 其它节点保持原样
    expect(merged['n2:in:audio']).toEqual({ x: 0, y: 300 })
    expect(merged['n2:out:audio']).toEqual({ x: 268, y: 320 })
  })

  it('drops ports that disappeared on the re-measured node only', () => {
    const current = {
      'n1:in:audio': { x: 0, y: 20 },
      'n1:out:vocals': { x: 268, y: 40 },
      'n1:out:instrumental': { x: 268, y: 60 },
    }

    const merged = mergePortOffsets(current, { 'n1:in:audio': { x: 0, y: 20 }, 'n1:out:vocals': { x: 268, y: 44 } }, ['n1'])

    expect(Object.keys(merged).sort()).toEqual(['n1:in:audio', 'n1:out:vocals'])
    expect(merged['n1:out:vocals']).toEqual({ x: 268, y: 44 })
  })

  it('does not treat a colon inside a node id as another node', () => {
    const current = {
      'a:in:audio': { x: 0, y: 10 },
      'a:out:stem:vocals': { x: 268, y: 30 },
      'a:b:in:audio': { x: 0, y: 99 },
    }

    const merged = mergePortOffsets(current, { 'a:in:audio': { x: 0, y: 30 } }, ['a'])

    expect(merged['a:in:audio']).toEqual({ x: 0, y: 30 })
    // 只认 `<id>:in|out:` 前缀：id 里带冒号的其它节点不能被误删。
    expect(merged['a:b:in:audio']).toEqual({ x: 0, y: 99 })
    // `a` 自己这次没测到的旧端口会被清掉（端口可能已经不存在）。
    expect(merged['a:out:stem:vocals']).toBeUndefined()
  })

  it('compares offsets with a small tolerance', () => {
    const left = { 'n:in:a': { x: 10, y: 20 } }

    expect(portOffsetsEqual(left, { 'n:in:a': { x: 10.005, y: 20.005 } })).toBe(true)
    expect(portOffsetsEqual(left, { 'n:in:a': { x: 10.5, y: 20 } })).toBe(false)
    expect(portOffsetsEqual(left, { 'n:in:a': { x: 10, y: 20 }, 'n:out:a': { x: 1, y: 2 } })).toBe(false)
    expect(portOffsetsEqual(left, {})).toBe(false)
  })
})
