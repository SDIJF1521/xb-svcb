import { createPinia, setActivePinia } from 'pinia'
import { enableAutoUnmount, flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type ModelDTO } from '@/api'
import { useModelsStore } from '@/stores/models'
import CreatePage from '../create.vue'
import RealtimeCoverPage from '../realtime.vue'

vi.mock('@/api', () => ({
  isDesktop: () => false,
  pickColor: () => '#00aabb',
  api: {
    listModels: vi.fn(),
    getDefaultModel: vi.fn(),
    getModelLibraryOverview: vi.fn(),
    listMusic: vi.fn(),
    pymssModels: vi.fn(),
    pymssStatus: vi.fn(),
    getSystemStatus: vi.fn(),
    listInferencePresets: vi.fn(),
    getInferenceQueue: vi.fn(),
    listMusicSources: vi.fn(),
    getMusicSource: vi.fn(),
    listSystemAudioDevices: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const models: ModelDTO[] = ['First', 'Default', 'Manual'].map((name) => ({
  id: name.toLowerCase(),
  name,
  type: 'RVC',
  framework: 'rvc',
  sample_rate: '40k',
  size: '1 MB',
  imported_at: '',
  main_model: { name: `${name}.pth`, path: `${name}.pth` },
  main_config: { name: '', path: '' },
}))

function mountPage(page = CreatePage) {
  return shallowMount(page, { global: { stubs: { RouterLink: true } } })
}

function modelButton(wrapper: VueWrapper, name: string) {
  const button = wrapper.findAll('button.model-item').find((item) => item.text().includes(name))
  if (!button) throw new Error(`Missing model button: ${name}`)
  return button
}

function selectedNames(wrapper: VueWrapper) {
  return wrapper.findAll('button.model-item.active').map((item) =>
    item.find('.model-name, .model-copy b').text(),
  )
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  setActivePinia(createPinia())
  vi.mocked(api.listModels).mockResolvedValue(models)
  vi.mocked(api.getDefaultModel).mockResolvedValue('default')
  vi.mocked(api.getModelLibraryOverview).mockResolvedValue({
    total: models.length, total_size_bytes: 0, total_size: '', frameworks: [],
  })
  vi.mocked(api.listMusic).mockResolvedValue([])
  vi.mocked(api.pymssModels).mockResolvedValue([])
  vi.mocked(api.pymssStatus).mockResolvedValue({ ok: false, environment: false, model: '', status: '' })
  vi.mocked(api.getSystemStatus).mockResolvedValue({ ready: true, tools: [] })
  vi.mocked(api.listInferencePresets).mockResolvedValue([])
  vi.mocked(api.getInferenceQueue).mockResolvedValue({ running: false, pending: [], size: 0 })
  vi.mocked(api.listMusicSources).mockResolvedValue([])
  vi.mocked(api.getMusicSource).mockResolvedValue('wy')
  vi.mocked(api.listSystemAudioDevices).mockResolvedValue([
    { id: 'input', name: 'Input', kind: 'input', system_mix: true },
    { id: 'output', name: 'Output', kind: 'output' },
  ])
})

describe('cover model selection during initialization', () => {
  it('initializes single and multi selection before optional PyMSS loading finishes', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.pymssModels>>>()
    vi.mocked(api.pymssModels).mockReturnValueOnce(pending.promise)
    const wrapper = mountPage()
    await flushPromises()

    expect(selectedNames(wrapper)).toEqual(['DefaultRVC'])
    await wrapper.get('[data-guide="multi-mode"]').trigger('click')
    expect(selectedNames(wrapper)).toEqual(['DefaultRVC'])

    pending.resolve([])
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual(['DefaultRVC'])
  })

  it('preserves a manual selection when the delayed queue request finishes', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.getInferenceQueue>>>()
    vi.mocked(api.getInferenceQueue).mockReturnValueOnce(pending.promise)
    const wrapper = mountPage()
    await flushPromises()
    expect(api.getInferenceQueue).toHaveBeenCalledOnce()

    await modelButton(wrapper, 'Manual').trigger('click')
    expect(selectedNames(wrapper)).toEqual(['ManualRVC'])
    pending.resolve({ running: false, pending: [], size: 0 })
    await flushPromises()

    expect(api.listMusicSources).toHaveBeenCalledOnce()
    expect(selectedNames(wrapper)).toEqual(['ManualRVC'])
  })

  it('preserves selection from a cached list when the model refresh finishes', async () => {
    await useModelsStore().load()
    const pending = deferred<ModelDTO[]>()
    vi.mocked(api.listModels).mockReturnValueOnce(pending.promise)
    const wrapper = mountPage()
    await modelButton(wrapper, 'Manual').trigger('click')

    pending.resolve(models)
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual(['ManualRVC'])
  })

  it('does not reselect a model after the user clears the multi selection', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.getInferenceQueue>>>()
    vi.mocked(api.getInferenceQueue).mockReturnValueOnce(pending.promise)
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-guide="multi-mode"]').trigger('click')
    expect(selectedNames(wrapper)).toEqual(['DefaultRVC'])
    await modelButton(wrapper, 'Default').trigger('click')
    expect(selectedNames(wrapper)).toEqual([])

    pending.resolve({ running: false, pending: [], size: 0 })
    await flushPromises()
    await useModelsStore().load()
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual([])
  })

  it.each([null, 'deleted-model'])('uses the first model when default %s is unavailable', async (id) => {
    vi.mocked(api.getDefaultModel).mockResolvedValue(id)
    const wrapper = mountPage()
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual(['FirstRVC'])
  })

  it('leaves selection empty when there are no models', async () => {
    vi.mocked(api.listModels).mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual([])
    await wrapper.get('[data-guide="multi-mode"]').trigger('click')
    expect(selectedNames(wrapper)).toEqual([])
  })

  it('preserves the current selection when the default changes', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await modelButton(wrapper, 'Manual').trigger('click')

    vi.mocked(api.getDefaultModel).mockResolvedValue('first')
    await useModelsStore().load()
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual(['ManualRVC'])
  })
})

describe('realtime model selection during initialization', () => {
  it('preserves a manual selection when audio device loading finishes', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.listSystemAudioDevices>>>()
    vi.mocked(api.listSystemAudioDevices).mockReturnValueOnce(pending.promise)
    const wrapper = mountPage(RealtimeCoverPage)
    await flushPromises()
    expect(api.listSystemAudioDevices).toHaveBeenCalledOnce()
    expect(selectedNames(wrapper)).toEqual(['First'])
    await modelButton(wrapper, 'Manual').trigger('click')
    expect(selectedNames(wrapper)).toEqual(['Manual'])

    pending.resolve([{ id: 'input', name: 'Input', kind: 'input', system_mix: true }])
    await flushPromises()
    expect(selectedNames(wrapper)).toEqual(['Manual'])
  })
})
