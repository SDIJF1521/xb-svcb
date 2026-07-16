import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, pickColor, type CreateWorkPayload, type WorkDTO } from '@/api'

export type WorkVM = WorkDTO & { color: string }

function toVM(w: WorkDTO): WorkVM {
  return { ...w, color: pickColor(w.id) }
}

export const useWorksStore = defineStore('works', () => {
  const works = ref<WorkVM[]>([])
  const loaded = ref(false)
  let syncTimer: ReturnType<typeof setTimeout> | null = null
  let syncUsers = 0
  let syncing = false

  async function load() {
    const list = await api.listWorks()
    works.value = list.map(toVM)
    loaded.value = true
  }

  function hasActiveWork() {
    return works.value.some((work) => work.status === 'queue' || work.status === 'running')
  }

  function scheduleSync() {
    if (syncUsers <= 0) return
    if (syncTimer) clearTimeout(syncTimer)
    const delay = document.visibilityState === 'hidden' ? 5000 : hasActiveWork() ? 1000 : 3000
    syncTimer = setTimeout(() => void syncNow(), delay)
  }

  async function syncNow() {
    if (syncing || syncUsers <= 0) return
    syncing = true
    try {
      await load()
    } catch {
      // A transient bridge failure must not stop later global refreshes.
    } finally {
      syncing = false
      scheduleSync()
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') void syncNow()
    else scheduleSync()
  }

  function startSync() {
    syncUsers += 1
    if (syncUsers > 1) return
    document.addEventListener('visibilitychange', onVisibilityChange)
    void syncNow()
  }

  function stopSync() {
    syncUsers = Math.max(0, syncUsers - 1)
    if (syncUsers > 0) return
    if (syncTimer) clearTimeout(syncTimer)
    syncTimer = null
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }

  async function ensureLoaded() {
    if (!loaded.value) await load()
  }

  async function create(payload: CreateWorkPayload) {
    const work = await api.createWork(payload)
    await load()
    return toVM(work)
  }

  async function refreshOne(id: string) {
    const w = await api.getWork(id)
    if (!w) return null
    const vm = toVM(w)
    const idx = works.value.findIndex((x) => x.id === id)
    if (idx >= 0) works.value[idx] = vm
    else works.value.unshift(vm)
    return vm
  }

  async function retry(id: string) {
    const ok = await api.retryWork(id)
    if (ok) await refreshOne(id)
    return ok
  }

  async function remove(id: string) {
    const ok = await api.deleteWork(id)
    if (ok) works.value = works.value.filter((w) => w.id !== id)
    return ok
  }

  async function rename(id: string, title: string) {
    const ok = await api.renameWork(id, title)
    if (ok) {
      const idx = works.value.findIndex((w) => w.id === id)
      if (idx >= 0) works.value[idx] = { ...works.value[idx], title: title.trim() } as WorkVM
    }
    return ok
  }

  return {
    works,
    loaded,
    load,
    ensureLoaded,
    startSync,
    stopSync,
    create,
    refreshOne,
    retry,
    remove,
    rename,
  }
})
