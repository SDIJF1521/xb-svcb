import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, pickColor, type ImportModelPayload, type ModelDTO } from '@/api'

export interface ModelVM {
  id: string
  name: string
  type: string
  /** 模型框架 id：so-vits-svc / rvc / …。 */
  framework: string
  sr: string
  size: string
  date: string
  color: string
  mainModel: string
  mainConfig: string
  diffusionModel: string
  diffusionConfig: string
  hasDiffusion: boolean
  /** RVC 检索特征文件名（无则为 '—'）。 */
  indexFile: string
}

function guessFramework(type: string): string {
  const t = (type || '').toLowerCase()
  if (t.includes('rvc')) return 'rvc'
  if (t.includes('ddsp')) return 'ddsp-svc'
  return 'so-vits-svc'
}

function toVM(m: ModelDTO): ModelVM {
  return {
    id: m.id,
    name: m.name,
    type: m.type,
    framework: m.framework || guessFramework(m.type),
    sr: m.sample_rate,
    size: m.size,
    date: m.imported_at,
    color: pickColor(m.id),
    mainModel: m.main_model?.name || '—',
    mainConfig: m.main_config?.name || '—',
    diffusionModel: m.diffusion_model?.name || '—',
    diffusionConfig: m.diffusion_config?.name || '—',
    hasDiffusion: !!m.diffusion_model,
    indexFile: m.index_file?.name || '—',
  }
}

export const useModelsStore = defineStore('models', () => {
  const models = ref<ModelVM[]>([])
  const defaultId = ref<string | null>(null)
  const loaded = ref(false)

  async function load() {
    const [list, def] = await Promise.all([api.listModels(), api.getDefaultModel()])
    models.value = list.map(toVM)
    defaultId.value = def
    loaded.value = true
  }

  async function ensureLoaded() {
    if (!loaded.value) await load()
  }

  async function importModel(payload: ImportModelPayload) {
    const created = await api.importModel(payload)
    if (created) await load()
    return created
  }

  async function setDefault(id: string) {
    const ok = await api.setDefaultModel(id)
    if (ok) defaultId.value = id
    return ok
  }

  async function remove(id: string) {
    const ok = await api.deleteModel(id)
    if (ok) await load()
    return ok
  }

  const count = computed(() => models.value.length)

  return { models, defaultId, loaded, count, load, ensureLoaded, importModel, setDefault, remove }
})
