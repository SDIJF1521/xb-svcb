import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type WorkDTO } from '@/api'
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

  afterEach(() => {
    vi.restoreAllMocks()
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

  it('drops every queue entry of a deleted song', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a'), track('b'), track('c')])

    expect(
      player.removeTracks(
        (item) => item.kind === 'work' && (item.workId === 'b' || item.id === 'b'),
      ),
    ).toBe(1)

    expect(player.queue.map((item) => item.id)).toEqual(['a', 'c'])
    expect(player.currentKey).toBe('work:a')
  })

  it('selects a neighbour without playing when the current song is deleted', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a'), track('b'), track('c')])

    player.removeTracks((item) => item.id === 'a')

    expect(player.queue.map((item) => item.id)).toEqual(['b', 'c'])
    expect(player.currentKey).toBe('work:b')
    expect(player.playing).toBe(false)
  })

  it('clears the queue when the last song is deleted', () => {
    const player = usePlayerStore()
    player.addToQueue([track('a')])

    player.removeTracks((item) => item.id === 'a')

    expect(player.queue).toEqual([])
    expect(player.currentKey).toBe('')
  })

  it('matches local downloads by path', () => {
    const player = usePlayerStore()
    player.addToQueue([
      {
        key: 'local:/music/a.wav',
        kind: 'local',
        id: '/music/a.wav',
        path: '/music/a.wav',
        title: 'a',
        subtitle: '已下载',
        color: '#00f0ff',
      },
      track('b'),
    ])

    player.removeTracks((item) => item.kind === 'local' && item.path === '/music/a.wav')

    expect(player.queue.map((item) => item.id)).toEqual(['b'])
  })

  it('drops persisted entries that no longer exist in the library', async () => {
    vi.spyOn(api, 'listWorks').mockResolvedValue([{ id: 'b' } as unknown as WorkDTO])
    vi.spyOn(api, 'listMusic').mockResolvedValue([])
    const player = usePlayerStore()
    player.addToQueue([
      track('a'),
      track('b'),
      {
        key: 'local:/music/gone.wav',
        kind: 'local',
        id: '/music/gone.wav',
        path: '/music/gone.wav',
        title: 'gone',
        subtitle: '已下载',
        color: '#00f0ff',
      },
    ])

    await expect(player.reconcileLibrary()).resolves.toBe(2)

    expect(player.queue.map((item) => item.id)).toEqual(['b'])
    expect(player.currentKey).toBe('work:b')
  })

  it('keeps the queue when the library lists cannot be read', async () => {
    vi.spyOn(api, 'listWorks').mockRejectedValue(new Error('offline'))
    vi.spyOn(api, 'listMusic').mockRejectedValue(new Error('offline'))
    const player = usePlayerStore()
    player.addToQueue([track('a')])

    await expect(player.reconcileLibrary()).resolves.toBe(0)
    expect(player.queue.map((item) => item.id)).toEqual(['a'])
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
