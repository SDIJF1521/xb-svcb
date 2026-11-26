import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import type { PlayerTrack } from '@/player/types'
import { usePlayerStore } from '@/stores/player'
import { useWorksStore } from '@/stores/works'

function workTrack(id: string): PlayerTrack {
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

describe('works store deletion', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('removes the deleted work from the player queue', async () => {
    vi.spyOn(api, 'deleteWork').mockResolvedValue(true)
    const player = usePlayerStore()
    player.addToQueue([workTrack('a'), workTrack('b')])
    const works = useWorksStore()

    await expect(works.remove('a')).resolves.toBe(true)

    expect(player.queue.map((item) => item.id)).toEqual(['b'])
    expect(player.currentKey).toBe('work:b')
  })

  it('keeps the queue when the deletion fails', async () => {
    vi.spyOn(api, 'deleteWork').mockResolvedValue(false)
    const player = usePlayerStore()
    player.addToQueue([workTrack('a'), workTrack('b')])
    const works = useWorksStore()

    await expect(works.remove('a')).resolves.toBe(false)

    expect(player.queue.map((item) => item.id)).toEqual(['a', 'b'])
  })
})
