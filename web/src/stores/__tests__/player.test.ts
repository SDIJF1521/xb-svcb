import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { PlayerTrack } from '@/player/types'
import { usePlayerStore } from '@/stores/player'

function track(id: string, title = id): PlayerTrack {
  return {
    key: `work:${id}`,
    kind: 'work',
    id,
    workId: id,
    title,
    subtitle: '测试模型',
    color: '#00f0ff',
  }
}

describe('player queue', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('adds tracks without duplicates and can insert the next track', () => {
    const player = usePlayerStore()
    expect(player.addToQueue([track('a'), track('b')])).toBe(2)
    expect(player.currentKey).toBe('work:a')
    expect(player.addToQueue([track('b'), track('c')])).toBe(1)
    expect(player.addToQueue([track('d')], { next: true })).toBe(1)
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'd', 'b', 'c'])
  })

  it('removes a non-current track and keeps the current one', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a'), track('b'), track('c')])
    player.removeTrack('work:b')
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'c'])
    expect(player.currentKey).toBe('work:a')
  })

  it('reorders the queue and keeps the current track', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a'), track('b'), track('c')])
    player.moveTrack(2, 0)
    expect(player.queue.map((item) => item.id)).toEqual(['c', 'a', 'b'])
    expect(player.currentKey).toBe('work:a')
  })

  it('cycles playback modes and exposes the queue state', () => {
    const player = usePlayerStore()
    expect(player.mode).toBe('order')
    player.cycleMode()
    expect(player.mode).toBe('repeat')
    player.setMode('shuffle')
    expect(player.mode).toBe('shuffle')
    player.addToQueue([track('a'), track('b')])
    expect(player.queueDuration).toBe(0)
    player.setVolume(2)
    expect(player.volume).toBe(1)
    player.setVolume(-1)
    expect(player.volume).toBe(0)
    player.toggleQueue()
    expect(player.queueOpen).toBe(true)
    player.toggleQueue(false)
    expect(player.queueOpen).toBe(false)
  })

  it('clears the queue completely', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a'), track('b')])
    player.clearQueue()
    expect(player.queue).toEqual([])
    expect(player.currentKey).toBe('')
    expect(player.queueOpen).toBe(false)
  })
})
