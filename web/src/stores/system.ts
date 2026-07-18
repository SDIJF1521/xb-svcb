import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  api,
  type InferenceDeviceBackend,
  type InferenceDeviceCapabilities,
  type InferenceDeviceOption,
  type ToolStatus,
} from '@/api'

const fallbackDevices = (): InferenceDeviceCapabilities => ({
  preferred: 'cpu',
  options: [
    { value: 'auto', label: '自动选择', backend: 'auto', frameworks: [] },
    { value: 'cpu', label: 'CPU', backend: 'cpu', frameworks: [] },
  ],
  frameworks: {},
})

const backendLabels: Record<InferenceDeviceBackend, string> = {
  auto: '自动',
  cuda: 'NVIDIA CUDA',
  rocm: 'AMD ROCm',
  directml: 'AMD DirectML',
  cpu: 'CPU',
}

export const useSystemStore = defineStore('system', () => {
  const tools = ref<ToolStatus[]>([])
  const ready = ref(false)
  const loaded = ref(false)
  const inferenceDevices = ref<InferenceDeviceCapabilities>(fallbackDevices())
  let syncTimer: ReturnType<typeof setInterval> | null = null
  let syncUsers = 0

  async function load() {
    const status = await api.getSystemStatus()
    tools.value = status.tools
    ready.value = status.ready
    inferenceDevices.value = status.inference_devices || fallbackDevices()
    loaded.value = true
  }

  function optionsForFramework(framework?: string | string[]): InferenceDeviceOption[] {
    const target = Array.isArray(framework) ? framework : framework ? [framework] : []
    const preferred = target.length
      ? target.map((item) => inferenceDevices.value.frameworks[item]?.preferred)
        .find((backend) => backend && target.every((item) =>
          inferenceDevices.value.frameworks[item]?.backends.includes(backend)))
        || 'cpu'
      : inferenceDevices.value.preferred
    return inferenceDevices.value.options
      .filter((option) => {
        if (option.value === 'auto' || option.value === 'cpu' || target.length === 0) return true
        return target.every((item) => option.frameworks.includes(item))
      })
      .map((option) => option.value === 'auto'
        ? { ...option, label: `自动 (${backendLabels[preferred]})` }
        : option)
  }

  function startSync() {
    syncUsers += 1
    if (syncUsers > 1) return
    void load().catch(() => undefined)
    syncTimer = setInterval(() => void load().catch(() => undefined), 30_000)
  }

  function stopSync() {
    syncUsers = Math.max(0, syncUsers - 1)
    if (syncUsers > 0 || !syncTimer) return
    clearInterval(syncTimer)
    syncTimer = null
  }

  return { tools, ready, loaded, inferenceDevices, optionsForFramework, load, startSync, stopSync }
})
