import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const backend = vi.hoisted(() => ({
  status: 'queue',
  getSystemStatus: vi.fn(),
  listWorks: vi.fn(),
}))

vi.mock('@/api', () => ({
  api: {
    getSystemStatus: backend.getSystemStatus,
    listWorks: backend.listWorks,
  },
  pickColor: () => '#00f0ff',
}))

import { useNotificationsStore } from '@/stores/notifications'

describe('global notification synchronization', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    backend.status = 'queue'
    backend.getSystemStatus.mockResolvedValue({
      ready: true,
      tools: [{ key: 'svc', name: 'SVC', desc: '', version: 'test', status: 'ready', ok: true }],
    })
    backend.listWorks.mockImplementation(async () => [
      {
        id: 'work-1',
        title: '同步测试',
        model: 'voice.pt',
        status: backend.status,
        progress: backend.status === 'done' ? 100 : 0,
        duration: '00:10',
        format: 'WAV',
        size: '1 MB',
        created_at: '2026-07-16T10:00:00',
        time: '刚刚',
        steps: [],
      },
    ])
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('keeps polling globally and synchronizes read state', async () => {
    const store = useNotificationsStore()
    store.start()
    await vi.runOnlyPendingTimersAsync()

    expect(store.notifications[0]?.tone).toBe('queue')
    expect(store.hasUnread).toBe(true)
    store.markAllRead()
    expect(store.hasUnread).toBe(false)

    backend.status = 'done'
    await vi.advanceTimersByTimeAsync(1_000)
    expect(store.notifications[0]?.tone).toBe('done')
    expect(store.hasUnread).toBe(true)

    store.markAllRead()
    expect(store.hasUnread).toBe(false)
    window.dispatchEvent(new StorageEvent('storage', { key: 'xb-notif-seen', newValue: '' }))
    expect(store.hasUnread).toBe(true)
    store.stop()
  })
})
