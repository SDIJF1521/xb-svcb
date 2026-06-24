import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type HubJob } from '@/api'
import { useModelsStore } from './models'

/**
 * 后台传输任务中心：模型上传 / 下载挂后台执行，不阻塞前端操作。
 *
 * - 通过 hub_start_download / hub_start_upload 启动后台任务（立即返回 key）。
 * - 一个全局轮询循环（在布局挂载时 start）调 hub_list_jobs 拉取所有任务进度，
 *   因此切换页面也不会丢失进度，可在顶栏「传输」面板随时查看。
 * - 任务由后端内存维护（进程重启即清空），前端只负责展示与触发。
 */
export const useTransfersStore = defineStore('transfers', () => {
  const jobs = ref<HubJob[]>([])
  const polling = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  // 已提示过完成的任务 key，避免重复刷新本地模型 / 重复提示
  const settled = new Set<string>()

  const activeCount = computed(
    () => jobs.value.filter((j) => j.status === 'running').length,
  )
  const hasJobs = computed(() => jobs.value.length > 0)

  /** 拉取一次全部任务进度。 */
  async function refresh() {
    try {
      const list = await api.hubListJobs()
      jobs.value = Array.isArray(list) ? list : []
      // 下载完成 → 刷新本地模型库一次
      for (const j of jobs.value) {
        if (j.status === 'done' && !settled.has(j.key)) {
          settled.add(j.key)
          if (j.kind === 'download') useModelsStore().load()
        }
        if (j.status === 'failed') settled.add(j.key)
      }
    } catch {
      /* 单次轮询失败忽略 */
    }
  }

  /** 启动全局轮询（重复调用安全）。 */
  function start() {
    if (timer) return
    polling.value = true
    refresh()
    timer = setInterval(refresh, 800)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    polling.value = false
  }

  /** 后台下载并导入模型，返回任务 key（失败返回 null）。 */
  async function startDownload(repoId: string): Promise<string | null> {
    const res = await api.hubStartDownload(repoId)
    if (!res.ok) return null
    start()
    await refresh()
    return res.key || null
  }

  /** 后台上传本地模型，返回任务 key（失败返回 null）。 */
  async function startUpload(
    modelId: string,
    name?: string,
    framework?: string,
  ): Promise<string | null> {
    const res = await api.hubStartUpload(modelId, name, framework)
    if (!res.ok) return null
    start()
    await refresh()
    return res.key || null
  }

  /** 按 key 读取某个任务（用于在模型页内联显示对应进度）。 */
  function jobByKey(key: string): HubJob | undefined {
    return jobs.value.find((j) => j.key === key)
  }

  async function clear(key: string) {
    await api.hubClearJob(key)
    jobs.value = jobs.value.filter((j) => j.key !== key)
  }

  /** 清理所有已完成 / 失败的任务。 */
  async function clearFinished() {
    const finished = jobs.value.filter((j) => j.status !== 'running')
    for (const j of finished) await api.hubClearJob(j.key)
    jobs.value = jobs.value.filter((j) => j.status === 'running')
  }

  return {
    jobs,
    polling,
    activeCount,
    hasJobs,
    refresh,
    start,
    stop,
    startDownload,
    startUpload,
    jobByKey,
    clear,
    clearFinished,
  }
})
