import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type ToolStatus } from '@/api'

export const useSystemStore = defineStore('system', () => {
  const tools = ref<ToolStatus[]>([])
  const ready = ref(false)
  const loaded = ref(false)
  let syncTimer: ReturnType<typeof setInterval> | null = null
  let syncUsers = 0

  async function load() {
    const status = await api.getSystemStatus()
    tools.value = status.tools
    ready.value = status.ready
    loaded.value = true
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

  return { tools, ready, loaded, load, startSync, stopSync }
})
