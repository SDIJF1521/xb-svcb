import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '@/stores/system'
import { useWorksStore } from '@/stores/works'

export interface GlobalNotification {
  id: string
  title: string
  text: string
  time: string
  tone: 'done' | 'failed' | 'running' | 'queue' | 'warn'
  to: string
}

const SEEN_KEY = 'xb-notif-seen'
const CHANNEL_NAME = 'xb-global-notifications'

export const useNotificationsStore = defineStore('notifications', () => {
  const systemStore = useSystemStore()
  const worksStore = useWorksStore()
  const { tools, loaded: systemLoaded } = storeToRefs(systemStore)
  const { works } = storeToRefs(worksStore)
  const seenSignature = ref(readSeenSignature())
  let users = 0
  let channel: BroadcastChannel | null = null

  const allReady = computed(
    () => systemLoaded.value && tools.value.length > 0 && tools.value.every((tool) => tool.ok),
  )

  const notifications = computed<GlobalNotification[]>(() => {
    const items: GlobalNotification[] = []
    if (systemLoaded.value && !allReady.value) {
      const unavailable = tools.value.filter((tool) => !tool.ok).map((tool) => tool.name)
      items.push({
        id: 'env',
        title: '运行环境降级',
        text: unavailable.length ? `${unavailable.join('、')}不可用` : '部分集成工具不可用，点击查看',
        time: '',
        tone: 'warn',
        to: '/',
      })
    }
    for (const work of works.value.slice(0, 8)) {
      let text = '排队中'
      let tone: GlobalNotification['tone'] = 'queue'
      if (work.status === 'done') {
        text = '翻唱完成，可试听 / 导出'
        tone = 'done'
      } else if (work.status === 'failed') {
        text = work.error ? `任务失败：${work.error}` : '任务失败，点击查看日志'
        tone = 'failed'
      } else if (work.status === 'running') {
        text = `处理中 ${work.progress || 0}%`
        tone = 'running'
      }
      items.push({ id: work.id, title: work.title, text, time: work.time || '', tone, to: '/works' })
    }
    return items
  })

  const currentSignature = computed(() =>
    notifications.value.map((notification) => `${notification.id}:${notification.tone}`).join('|'),
  )
  const hasUnread = computed(
    () => currentSignature.value !== '' && currentSignature.value !== seenSignature.value,
  )

  function markAllRead() {
    applySeenSignature(currentSignature.value, true)
  }

  function applySeenSignature(value: string, broadcast: boolean) {
    seenSignature.value = value
    try {
      localStorage.setItem(SEEN_KEY, value)
    } catch {
      // Persistence is optional in restricted browser contexts.
    }
    if (broadcast) channel?.postMessage({ type: 'seen', value })
  }

  function onStorage(event: StorageEvent) {
    if (event.key === SEEN_KEY) seenSignature.value = event.newValue || ''
  }

  function start() {
    users += 1
    if (users > 1) return
    window.addEventListener('storage', onStorage)
    if ('BroadcastChannel' in window) {
      channel = new BroadcastChannel(CHANNEL_NAME)
      channel.onmessage = (event: MessageEvent<{ type?: string; value?: string }>) => {
        if (event.data?.type === 'seen') applySeenSignature(event.data.value || '', false)
      }
    }
    systemStore.startSync()
    worksStore.startSync()
  }

  function stop() {
    users = Math.max(0, users - 1)
    if (users > 0) return
    window.removeEventListener('storage', onStorage)
    channel?.close()
    channel = null
    systemStore.stopSync()
    worksStore.stopSync()
  }

  return { notifications, hasUnread, allReady, markAllRead, start, stop }
})

function readSeenSignature(): string {
  try {
    return localStorage.getItem(SEEN_KEY) || ''
  } catch {
    return ''
  }
}
