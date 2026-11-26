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

  it('stops playback instead of auto-playing when the playing song is deleted', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a'), track('b')], 0)
    const element = document.querySelector('audio') as HTMLAudioElement
    const playCalls = vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length
    expect(player.playing).toBe(true)
    expect(element.getAttribute('src')).toContain('/audio/a')

    player.removeTracks((item) => item.kind === 'work' && item.id === 'a')

    expect(player.queue.map((item) => item.id)).toEqual(['b'])
    expect(player.currentKey).toBe('work:b')
    expect(player.playing).toBe(false)
    expect(player.currentTime).toBe(0)
    expect(element.getAttribute('src')).toBeNull()
    // 不会自动续播下一首，避免播放已被删除的文件。
    expect(vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length).toBe(playCalls)
  })

  it('tracks stream metadata and lossless state', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a')], 0)
    expect(player.currentTrack?.audioInfo?.lossless).toBe(true)
    expect(player.currentTrack?.audioInfo?.sampleRate).toBe(44100)
    expect(player.isLossless).toBe(true)
    expect(player.currentQuality).toBe('HiFi 无损')
  })

  it('keeps a single played song in the queue and manages it there', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a'), track('b')], 0)

    await player.playAudition(track('c'))
    // 单曲播放不清空已有队列，但正在播放的歌一定进入队列并成为当前项。
    expect(player.isAudition).toBe(false)
    expect(player.activeKey).toBe('work:c')
    expect(player.currentKey).toBe('work:c')
    expect(player.currentTrack?.id).toBe('c')
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(player.isPlayingKey('work:c')).toBe(true)

    // 由队列管理：上一首回到队列里的 b。
    await player.previous()
    expect(player.currentKey).toBe('work:b')
    expect(player.playing).toBe(true)

    // 顺序播放走到最后一首 c 后停止。
    await player.next(false)
    expect(player.currentKey).toBe('work:c')
    const element = document.querySelector('audio') as HTMLAudioElement
    element.dispatchEvent(new Event('ended'))
    expect(player.playing).toBe(false)
    expect(player.activeKey).toBe('work:c')
    expect(player.queue).toHaveLength(3)
  })

  it('adds to the queue without reloading the currently playing song', async () => {
    const player = usePlayerStore()
    await player.playAudition(track('a'))
    const element = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(element, 'currentTime', { configurable: true, value: 12 })
    element.dispatchEvent(new Event('timeupdate'))
    const loadCalls = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length
    expect(player.queue.map((item) => item.id)).toEqual(['a'])
    expect(player.duration).toBe(10)
    expect(player.currentTime).toBe(12)

    expect(player.addToQueue([track('b')])).toBe(1)

    // 播放中的歌曲仍是当前项：音频不重新加载，播放状态和进度都不变。
    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b'])
    expect(player.currentKey).toBe('work:a')
    expect(player.activeKey).toBe('work:a')
    expect(player.currentTrack?.id).toBe('a')
    expect(player.playing).toBe(true)
    expect(player.currentTime).toBe(12)
    expect(player.duration).toBe(10)
    expect(vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length).toBe(loadCalls)
    expect(document.querySelector('audio')).toBe(element)
  })

  it('adds to a playing queue without interrupting the current song', async () => {
    const player = usePlayerStore()
    await player.playQueue([track('a'), track('b')], 0)
    const element = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(element, 'currentTime', { configurable: true, value: 7 })
    element.dispatchEvent(new Event('timeupdate'))
    const loadCalls = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length

    expect(player.addToQueue([track('c')])).toBe(1)

    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(player.currentKey).toBe('work:a')
    expect(player.playing).toBe(true)
    expect(player.currentTime).toBe(7)
    expect(vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length).toBe(loadCalls)
  })

  it('opens the queue panel during single playback without interrupting it', async () => {
    const player = usePlayerStore()
    await player.playAudition(track('a'))
    const loadCalls = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length
    expect(player.queue.map((item) => item.id)).toEqual(['a'])

    player.toggleQueue(true)

    expect(player.queueOpen).toBe(true)
    expect(player.queue.map((item) => item.id)).toEqual(['a'])
    expect(player.currentKey).toBe('work:a')
    expect(player.playing).toBe(true)
    expect(vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length).toBe(loadCalls)
  })
})
