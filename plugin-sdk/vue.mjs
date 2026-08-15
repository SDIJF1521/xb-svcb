import { computed, onMounted, readonly, ref } from 'vue'

import { host, isHosted } from './client.mjs'

function errorValue(value) {
  return value instanceof Error ? value : new Error(String(value))
}

export function usePluginHost(options = {}) {
  const hosted = ref(isHosted())
  const context = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let activeRequests = 0

  async function invoke(task) {
    activeRequests += 1
    loading.value = true
    error.value = null
    try {
      return await task()
    } catch (value) {
      error.value = errorValue(value)
      throw error.value
    } finally {
      activeRequests -= 1
      loading.value = activeRequests > 0
    }
  }

  async function refreshContext() {
    hosted.value = isHosted()
    if (!hosted.value) return undefined
    const value = await invoke(() => host.getContext())
    context.value = value
    return value
  }

  const runAction = (actionId, values = {}) => invoke(() => host.runAction(actionId, values))
  const createWork = payload => invoke(() => host.createWork(payload))
  const assetData = path => invoke(() => host.assetData(path))
  const assetUrl = path => invoke(() => host.assetUrl(path))
  const notify = (message, type = 'success') => invoke(() => host.notify(message, type))
  const clearError = () => { error.value = null }

  if (options.loadContext !== false) {
    onMounted(() => { void refreshContext().catch(() => undefined) })
  }

  return {
    hosted: readonly(hosted),
    context: readonly(context),
    plugin: computed(() => context.value?.plugin),
    page: computed(() => context.value?.page),
    theme: computed(() => context.value?.theme || ''),
    loading: readonly(loading),
    error: readonly(error),
    refreshContext,
    runAction,
    createWork,
    assetData,
    assetUrl,
    notify,
    clearError,
  }
}
