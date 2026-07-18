import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const backend = vi.hoisted(() => ({ getSystemStatus: vi.fn() }))

vi.mock('@/api', () => ({
  api: { getSystemStatus: backend.getSystemStatus },
}))

import { useSystemStore } from '@/stores/system'

describe('inference device adaptation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    backend.getSystemStatus.mockResolvedValue({
      ready: true,
      tools: [],
      inference_devices: {
        preferred: 'directml',
        options: [
          { value: 'auto', label: '自动选择', backend: 'auto', frameworks: ['uvr', 'so-vits-svc', 'rvc'] },
          { value: 'directml', label: 'AMD GPU (DirectML)', backend: 'directml', name: 'AMD Radeon RX 7900 XTX', frameworks: ['uvr', 'so-vits-svc'] },
          { value: 'cpu', label: 'CPU', backend: 'cpu', frameworks: ['uvr', 'so-vits-svc', 'rvc'] },
        ],
        frameworks: {
          uvr: {
            ok: true,
            torch_version: '2.4.1',
            backends: ['directml', 'cpu'],
            devices: [{ backend: 'directml', name: 'AMD Radeon RX 7900 XTX', index: 0 }],
            preferred: 'directml',
          },
          'so-vits-svc': {
            ok: true,
            torch_version: '2.4.1',
            backends: ['directml', 'cpu'],
            devices: [{ backend: 'directml', name: 'AMD Radeon RX 7900 XTX', index: 0 }],
            preferred: 'directml',
          },
          rvc: {
            ok: true,
            torch_version: '2.4.1',
            backends: ['cpu'],
            devices: [],
            preferred: 'cpu',
          },
        },
      },
    })
  })

  it('shows AMD DirectML only for frameworks whose environment supports it', async () => {
    const store = useSystemStore()
    await store.load()

    expect(store.optionsForFramework('so-vits-svc').map((item) => item.value)).toEqual([
      'auto',
      'directml',
      'cpu',
    ])
    expect(store.optionsForFramework('so-vits-svc')[0]?.label).toBe('自动 (AMD DirectML)')
    expect(store.optionsForFramework('rvc').map((item) => item.value)).toEqual(['auto', 'cpu'])
    expect(store.optionsForFramework('rvc')[0]?.label).toBe('自动 (CPU)')
  })

  it('uses only devices shared by UVR and the selected singing framework', async () => {
    const store = useSystemStore()
    await store.load()

    expect(store.optionsForFramework(['uvr', 'so-vits-svc']).map((item) => item.value)).toEqual([
      'auto',
      'directml',
      'cpu',
    ])
    expect(store.optionsForFramework(['uvr', 'rvc']).map((item) => item.value)).toEqual([
      'auto',
      'cpu',
    ])
  })
})
