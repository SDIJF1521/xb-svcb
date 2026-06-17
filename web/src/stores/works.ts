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

  async function load() {
    const list = await api.listWorks()
    works.value = list.map(toVM)
    loaded.value = true
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

  return { works, loaded, load, ensureLoaded, create, refreshOne, retry, remove, rename }
})
