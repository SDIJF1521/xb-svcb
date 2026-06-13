import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type ToolStatus } from '@/api'

export const useSystemStore = defineStore('system', () => {
  const tools = ref<ToolStatus[]>([])
  const ready = ref(false)
  const loaded = ref(false)

  async function load() {
    const status = await api.getSystemStatus()
    tools.value = status.tools
    ready.value = status.ready
    loaded.value = true
  }

  return { tools, ready, loaded, load }
})
