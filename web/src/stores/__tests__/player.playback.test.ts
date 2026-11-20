import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import type { PlayerTrack } from '@/player/types'
import { usePlayerStore } from '@/stores/player'

function track(id: string): PlayerTrack {
  return {
    key: `work:${id}`,
    kind: 'work',
    id,
    workId: id,
    title: id,
    subtitle: '测试模型',
    color: '#00f0ff',
  }
}

function setPaused(element: HTMLMediaElement, value: boolean) {
  Object.defineProperty(element, 'paused', { configurable: true, value })
}

describe('global player playback', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
    setActivePinia(createPinia())
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function play(
      this: HTMLMediaElement,
    ) {
      setPaused(this, false)
      this.dispatchEvent(new Event('play'))
      return Promise.resolve()
    })
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function pause(
      this: HTMLMediaElement,
    ) {
      setPaused(this, true)
      this.dispatchEvent(new Event('pause'))
    })
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined)
    vi.spyOn(api, 'getWorkStream').mockImplementation(async (id: string) => ({
      ok: true,
      url: `http://127.0.0.1:65530/audio/${id}`,
      format: 'wav',
      sample_rate: 44100,
      channels: 2,
      bit_depth: 16,
      duration: 10,
      lossless: true,
    }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('plays through the queue, stops in order mode and wraps in repeat mode', async () => {
    const player = usePlayerStore()
    player.setMode('order')
    await player.playQueue([track('a'), track('b'), track('c')], 0)
    expect(player.currentKey).toBe('work:a')
    expect(player.playing).toBe(true)

    await player.next(false)
    expect(player.currentKey).toBe('work:b')
    await player.next(false)
    expect(player.currentKey).toBe('work:c')
    await player.next(false)
    expect(player.currentKey).toBe('work:c')
    expect(player.playing).toBe(false)

    player.setMode('repeat')
    await player.next(false)
    expect(player.currentKey).toBe('work:a')
    await player.previous()
    expect(player.currentKey).toBe('work:c')
  })

  it('repeats the same track in single mode when it ends', async () => {
    const player = usePlayerStore()
    player.setMode('single')
    await player.playQueue([track('a'), track('b')], 0)
    const element = document.querySelector('audio') as HTMLAudioElement
    element.dispatchEvent(new Event('ended'))
    await vi.waitFor(() => expect(player.playing).toBe(true))
    expect(player.currentKey).toBe('work:a')
    expect(player.currentTime).toBe(0)
  })

  it('moves to the next track when the current song is removed', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a'), track('b')], 0)
    player.removeTrack('work:a')
    await vi.waitFor(() => expect(player.currentKey).toBe('work:b'))
    expect(player.queue.map((item) => item.id)).toEqual(['b'])
  })

  it('tracks stream metadata and lossless state', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a')], 0)
    expect(player.currentTrack?.audioInfo?.lossless).toBe(true)
    expect(player.currentTrack?.audioInfo?.sampleRate).toBe(44100)
    expect(player.isLossless).toBe(true)
    expect(player.currentQuality).toBe('HiFi 无损')
  })

  it('auditions a single track without touching the music queue or auto-advancing', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a'), track('b')], 0)
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b'])

    await player.playAudition(track('c'))
    expect(player.isAudition).toBe(true)
    expect(player.activeKey).toBe('work:c')
    expect(player.currentTrack?.id).toBe('c')
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b'])
    expect(player.isPlayingKey('work:c')).toBe(true)

    // 试听模式下 next 不会改变曲目，也不会把队列的下一首加进来。
    await player.next(false)
    expect(player.activeKey).toBe('work:c')
    expect(player.queue).toHaveLength(2)

    const element = document.querySelector('audio') as HTMLAudioElement
    element.dispatchEvent(new Event('ended'))
    expect(player.playing).toBe(false)
    expect(player.activeKey).toBe('work:c')

    player.stopAudition()
    expect(player.isAudition).toBe(false)
    expect(player.activeKey).toBe('work:a')
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b'])
  })
})
