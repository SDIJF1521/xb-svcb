/**
 * 全局音乐播放器。
 *
 * 一个 Pinia store 持有唯一一个 <audio> 元素与队列，因此切页不会中断播放，
 * 播放页、迷你播放条和队列面板共享同一份状态。
 *
 * 任何一次播放（含单曲播放 playAudition）都会把歌曲放进播放队列并设为当前项，
 * 所以播放始终由队列管理（上一首 / 下一首、播放模式、持久化），且切页不中断。
 *
 * 播放顺序：order / repeat / single / shuffle，规则在 ``@/player/queue``。
 * 音质：后端把作品与在线歌曲发布为支持 Range 的本机音频流，前端不再把
 * 整首 WAV 转成 MP3 data URI；默认直通（不经过任何音效），仅当用户主动
 * 打开均衡器时才接入 Web Audio。
 */

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  api,
  type AudioStreamInfo,
  type DownloadedMusic,
  type MusicSearchItem,
  type WorkDTO,
} from '@/api'
import { audioDetailLabel, audioQualityBadge } from '@/player/format'
import {
  PLAY_MODES,
  buildShuffleOrder,
  moveItem,
  nextPlayMode,
  resolveNextKey,
  resolvePreviousKey,
  shuffleOrderValid,
} from '@/player/queue'
import { localToTrack, onlineToTrack, workToTrack } from '@/player/tracks'
import type { PlayMode, PlayerAudioInfo, PlayerTrack } from '@/player/types'

const STORAGE_KEY = 'xb-player-state-v2'

export const EQ_FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

export interface EqPreset {
  id: string
  label: string
  gains: number[]
}

/** 均衡器预设（增益单位 dB，范围 -12…+12）。 */
export const EQ_PRESETS: EqPreset[] = [
  { id: 'flat', label: '平直', gains: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
  { id: 'vocal', label: '人声', gains: [-1, 0, 1, 2, 3, 2, 1, 0, -1, 0] },
  { id: 'pop', label: '流行', gains: [2, 1, 0, 1, 2, 2, 1, 1, 0, 0] },
  { id: 'bass', label: '低频', gains: [5, 4, 2, 1, 0, 0, 0, 0, 0, 0] },
  { id: 'treble', label: '高频', gains: [0, 0, 0, 0, 0, 0, 1, 2, 3, 4] },
]

interface PersistedState {
  queue?: PlayerTrack[]
  currentKey?: string
  mode?: PlayMode
  volume?: number
  muted?: boolean
  eqEnabled?: boolean
  eqGains?: number[]
}

function clamp(value: number, min: number, max: number): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return min
  return Math.min(max, Math.max(min, number))
}

function normalizeGains(value: unknown): number[] {
  const source = Array.isArray(value) ? value : []
  return EQ_FREQUENCIES.map((_, index) => clamp(Number(source[index] ?? 0), -12, 12))
}

function isPlayMode(value: unknown): value is PlayMode {
  return typeof value === 'string' && (PLAY_MODES as string[]).includes(value)
}

function loadPersisted(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const data = JSON.parse(raw) as PersistedState
    if (!data || typeof data !== 'object') return {}
    const queue = Array.isArray(data.queue)
      ? data.queue.filter(
          (item): item is PlayerTrack =>
            !!item &&
            typeof item.key === 'string' &&
            typeof item.title === 'string' &&
            (item.kind === 'work' || item.kind === 'local' || item.kind === 'online'),
        )
      : []
    return {
      queue: queue.map((item) => ({ ...item, url: undefined, fallbackTried: false })),
      currentKey: typeof data.currentKey === 'string' ? data.currentKey : '',
      mode: isPlayMode(data.mode) ? data.mode : 'order',
      volume: typeof data.volume === 'number' ? clamp(data.volume, 0, 1) : 0.85,
      muted: !!data.muted,
      eqEnabled: !!data.eqEnabled,
      eqGains: normalizeGains(data.eqGains),
    }
  } catch {
    return {}
  }
}

function isCorsSafeUrl(url: string): boolean {
  if (!url) return true
  if (url.startsWith('data:') || url.startsWith('blob:')) return true
  try {
    const parsed = new URL(url, typeof window !== 'undefined' ? window.location.href : 'http://127.0.0.1')
    return ['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
  } catch {
    return false
  }
}

function mediaSessionAvailable(): boolean {
  return typeof navigator !== 'undefined' && 'mediaSession' in navigator
}

/** 把播放失败转成可读提示；自动播放被浏览器拦截时给出可操作的文案。 */
function playbackErrorMessage(err: unknown): string {
  const name = err instanceof Error ? err.name : ''
  if (name === 'NotAllowedError') return '系统阻止了自动播放，请点击播放按钮开始'
  return err instanceof Error ? err.message : String(err)
}

export const usePlayerStore = defineStore('player', () => {
  const persisted = loadPersisted()

  // ---- 队列与播放状态 ----
  const queue = ref<PlayerTrack[]>(persisted.queue ?? [])
  const currentKey = ref(
    persisted.currentKey && queue.value.some((track) => track.key === persisted.currentKey)
      ? persisted.currentKey
      : (queue.value[0]?.key ?? ''),
  )
  const mode = ref<PlayMode>(persisted.mode ?? 'order')
  const volume = ref(clamp(persisted.volume ?? 0.85, 0, 1))
  const muted = ref(!!persisted.muted)
  const eqEnabled = ref(!!persisted.eqEnabled)
  const eqGains = ref<number[]>(normalizeGains(persisted.eqGains))
  const queueOpen = ref(false)
  const playing = ref(false)
  /** 本次会话是否真正开始过播放；用于避免重启后自动出现迷你播放条。 */
  const sessionStarted = ref(false)
  /** 单曲试听：只播放一首，不进入队列、不自动切歌，也不持久化。 */
  const auditionTrack = ref<PlayerTrack | null>(null)
  const buffering = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const error = ref('')
  const lastError = ref('')
  const resolvingKey = ref('')
  const shuffleOrder = ref<string[]>(
    buildShuffleOrder(
      queue.value.map((track) => track.key),
      currentKey.value,
    ),
  )

  const currentIndex = computed(() =>
    currentKey.value ? queue.value.findIndex((track) => track.key === currentKey.value) : -1,
  )
  /** 当前真正播放/选中的 key：试听时优先试听曲目，否则使用队列当前曲目。 */
  const activeKey = computed(() => auditionTrack.value?.key ?? currentKey.value)
  const isAudition = computed(() => !!auditionTrack.value)
  const currentTrack = computed(() => {
    if (auditionTrack.value) return auditionTrack.value
    const index = currentIndex.value
    return index >= 0 ? (queue.value[index] ?? null) : null
  })
  if (currentTrack.value?.duration) duration.value = currentTrack.value.duration

  const hasQueue = computed(() => queue.value.length > 0)
  const progress = computed(() =>
    duration.value > 0 ? Math.min(1, Math.max(0, currentTime.value / duration.value)) : 0,
  )
  const canGoNext = computed(() => {
    if (isAudition.value) return false
    if (!queue.value.length) return false
    if (queue.value.length === 1) return mode.value !== 'order'
    if (mode.value === 'order') return currentIndex.value < queue.value.length - 1
    return true
  })
  const canGoPrev = computed(() => {
    if (isAudition.value) return false
    if (!queue.value.length) return false
    if (queue.value.length === 1) return mode.value !== 'order'
    if (mode.value === 'order') return currentIndex.value > 0
    return true
  })
  const queueDuration = computed(() =>
    queue.value.reduce((total, track) => total + (track.duration || 0), 0),
  )
  const currentQuality = computed(() => audioQualityBadge(currentTrack.value?.audioInfo))
  const currentDetail = computed(() => audioDetailLabel(currentTrack.value?.audioInfo))
  const isLossless = computed(() => !!currentTrack.value?.audioInfo?.lossless)
  const eqSupported = computed(() => {
    const track = currentTrack.value
    return !track?.url || isCorsSafeUrl(track.url)
  })

  // ---- 音频元素 ----
  let audioEl: HTMLAudioElement | null = null
  let loadedKey = ''
  let loadToken = 0
  let lastPositionSync = 0

  // ---- Web Audio（仅均衡器启用时存在）----
  let audioCtx: AudioContext | null = null
  let sourceNode: MediaElementAudioSourceNode | null = null
  let preampNode: GainNode | null = null
  let volumeNode: GainNode | null = null
  let eqNodes: BiquadFilterNode[] = []
  let graphReady = false

  function queueKeys(): string[] {
    return queue.value.map((track) => track.key)
  }

  function refreshShuffle(anchor = currentKey.value) {
    shuffleOrder.value = buildShuffleOrder(queueKeys(), anchor)
  }

  function serializableTrack(track: PlayerTrack): PlayerTrack {
    const copy: PlayerTrack = { ...track }
    delete copy.url
    delete copy.fallbackTried
    return copy
  }

  let persistTimer: ReturnType<typeof setTimeout> | null = null
  function persistSoon() {
    if (persistTimer) clearTimeout(persistTimer)
    persistTimer = setTimeout(persist, 350)
  }
  function persist() {
    try {
      const payload: PersistedState = {
        queue: queue.value.map(serializableTrack),
        currentKey: currentKey.value,
        mode: mode.value,
        volume: volume.value,
        muted: muted.value,
        eqEnabled: eqEnabled.value,
        eqGains: [...eqGains.value],
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
      /* localStorage 不可用时仅影响记忆，不影响播放 */
    }
  }

  // ---- 音频事件 ----
  function handleTimeUpdate() {
    if (!audioEl) return
    currentTime.value = audioEl.currentTime || 0
    if (Number.isFinite(audioEl.duration) && audioEl.duration > 0) {
      if (Math.abs(duration.value - audioEl.duration) > 0.5) duration.value = audioEl.duration
      const track = currentTrack.value
      if (track && Math.abs((track.duration || 0) - audioEl.duration) > 1) {
        track.duration = audioEl.duration
      }
    }
    syncMediaPosition()
  }

  function handleDurationChange() {
    if (audioEl && Number.isFinite(audioEl.duration) && audioEl.duration > 0) {
      duration.value = audioEl.duration
    }
  }

  function handlePlay() {
    playing.value = true
    // 试听同样属于「本次会话真的开始过播放」：离开播放页后播放条要继续可控制。
    sessionStarted.value = true
    buffering.value = false
    setMediaPlaybackState('playing')
  }

  function handlePause() {
    playing.value = false
    setMediaPlaybackState('paused')
  }

  function handleEnded() {
    playing.value = false
    if (auditionTrack.value) {
      // 试听只播一首：结束即停，不进入下一首，也不受循环模式影响。
      currentTime.value = duration.value
      setMediaPlaybackState('paused')
      return
    }
    void next(true)
  }

  function handleAudioError() {
    const track = currentTrack.value
    buffering.value = false
    playing.value = false
    if (!track || !audioEl?.error) return
    // 直通地址失败时用原 data URI 兜底一次（旧版后端 / 端口被占用等情况）。
    if (
      track.kind === 'work' &&
      track.url &&
      !track.url.startsWith('data:') &&
      !track.fallbackTried
    ) {
      track.fallbackTried = true
      track.url = ''
      if (auditionTrack.value) void playAudition(track)
      else void playAt(currentIndex.value, { autoplay: true })
      return
    }
    const code = audioEl?.error?.code
    const message = code ? `音频播放失败（错误 ${code}）` : '音频播放失败'
    error.value = message
    lastError.value = message
  }

  function setupMediaSessionHandlers() {
    if (!mediaSessionAvailable()) return
    try {
      navigator.mediaSession.setActionHandler('play', () => void resume())
      navigator.mediaSession.setActionHandler('pause', () => pause())
      navigator.mediaSession.setActionHandler('previoustrack', () => void previous())
      navigator.mediaSession.setActionHandler('nexttrack', () => void next(false))
      navigator.mediaSession.setActionHandler('seekbackward', (details) =>
        seekBy(-(details.seekOffset || 10)),
      )
      navigator.mediaSession.setActionHandler('seekforward', (details) =>
        seekBy(details.seekOffset || 10),
      )
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (typeof details.seekTime === 'number') seek(details.seekTime)
      })
    } catch {
      /* 某些操作在旧内核不支持，忽略即可 */
    }
  }

  function setMediaPlaybackState(state: 'playing' | 'paused' | 'none') {
    if (!mediaSessionAvailable()) return
    try {
      navigator.mediaSession.playbackState = state
    } catch {
      /* ignore */
    }
  }

  function syncMediaPosition(force = false) {
    if (!mediaSessionAvailable() || duration.value <= 0) return
    const now = Date.now()
    if (!force && now - lastPositionSync < 900) return
    lastPositionSync = now
    try {
      navigator.mediaSession.setPositionState({
        duration: duration.value,
        playbackRate: 1,
        position: Math.min(currentTime.value, duration.value),
      })
    } catch {
      /* ignore */
    }
  }

  function updateMediaSession(track: PlayerTrack) {
    if (!mediaSessionAvailable()) return
    try {
      if (typeof MediaMetadata !== 'undefined') {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: track.title,
          artist: track.subtitle,
          album: track.album || 'XB-SVCB',
        })
      }
    } catch {
      /* ignore */
    }
  }

  function getAudio(): HTMLAudioElement {
    if (audioEl) return audioEl
    const el = document.createElement('audio')
    el.preload = 'auto'
    el.setAttribute('playsinline', '')
    el.style.display = 'none'
    document.body.appendChild(el)
    el.addEventListener('timeupdate', handleTimeUpdate)
    el.addEventListener('durationchange', handleDurationChange)
    el.addEventListener('loadedmetadata', handleDurationChange)
    el.addEventListener('play', handlePlay)
    el.addEventListener('pause', handlePause)
    el.addEventListener('waiting', () => {
      buffering.value = true
    })
    el.addEventListener('playing', () => {
      buffering.value = false
    })
    el.addEventListener('canplay', () => {
      buffering.value = false
    })
    el.addEventListener('ended', handleEnded)
    el.addEventListener('error', handleAudioError)
    audioEl = el
    setupMediaSessionHandlers()
    return el
  }

  // ---- Web Audio 图 ----
  function wireGraph() {
    if (!audioCtx || !sourceNode || !preampNode || !volumeNode) return
    for (const node of [sourceNode, preampNode, ...eqNodes, volumeNode]) {
      try {
        node.disconnect()
      } catch {
        /* ignore */
      }
    }
    sourceNode.connect(preampNode)
    let node: AudioNode = preampNode
    for (const filter of eqNodes) {
      node.connect(filter)
      node = filter
    }
    node.connect(volumeNode)
    volumeNode.connect(audioCtx.destination)
    graphReady = true
  }

  function bypassGraph() {
    if (!audioCtx || !sourceNode || !graphReady) return
    try {
      sourceNode.disconnect()
    } catch {
      /* ignore */
    }
    sourceNode.connect(audioCtx.destination)
    graphReady = false
    applyVolume()
  }

  function ensureGraph(): boolean {
    const el = getAudio()
    if (audioCtx && sourceNode) {
      if (!graphReady) wireGraph()
      applyEq()
      applyVolume()
      if (audioCtx.state === 'suspended') void audioCtx.resume()
      return true
    }
    const scope = window as unknown as {
      AudioContext?: typeof AudioContext
      webkitAudioContext?: typeof AudioContext
    }
    const Ctor = scope.AudioContext || scope.webkitAudioContext
    if (!Ctor) return false
    const sampleRate = currentTrack.value?.audioInfo?.sampleRate || 0
    let ctx: AudioContext
    try {
      ctx = sampleRate >= 8000 && sampleRate <= 192000 ? new Ctor({ sampleRate }) : new Ctor()
    } catch {
      try {
        ctx = new Ctor()
      } catch {
        return false
      }
    }
    try {
      sourceNode = ctx.createMediaElementSource(el)
    } catch {
      try {
        void ctx.close()
      } catch {
        /* ignore */
      }
      return false
    }
    preampNode = ctx.createGain()
    volumeNode = ctx.createGain()
    eqNodes = EQ_FREQUENCIES.map((frequency, index) => {
      const filter = ctx.createBiquadFilter()
      filter.type =
        index === 0 ? 'lowshelf' : index === EQ_FREQUENCIES.length - 1 ? 'highshelf' : 'peaking'
      filter.frequency.value = frequency
      filter.Q.value = 1
      return filter
    })
    audioCtx = ctx
    wireGraph()
    applyEq()
    applyVolume()
    if (ctx.state === 'suspended') void ctx.resume()
    return true
  }

  function applyEq() {
    if (!eqNodes.length) return
    const gains = eqEnabled.value ? eqGains.value : EQ_FREQUENCIES.map(() => 0)
    eqNodes.forEach((node, index) => {
      node.gain.value = clamp(gains[index] ?? 0, -12, 12)
    })
    if (preampNode) {
      const maxBoost = eqEnabled.value ? Math.max(0, ...gains) : 0
      preampNode.gain.value = Math.pow(10, (-maxBoost * 0.45) / 20)
    }
  }

  function applyVolume() {
    if (!audioEl) return
    if (graphReady && volumeNode) {
      audioEl.volume = 1
      audioEl.muted = false
      volumeNode.gain.value = muted.value ? 0 : volume.value
    } else {
      audioEl.volume = volume.value
      audioEl.muted = muted.value
    }
  }

  function applySource(track: PlayerTrack, url: string) {
    const el = getAudio()
    const safe = isCorsSafeUrl(url)
    try {
      el.pause()
    } catch {
      /* ignore */
    }
    if (safe) el.crossOrigin = 'anonymous'
    else el.removeAttribute('crossorigin')
    el.src = url
    el.load()
    loadedKey = track.key
    if (safe) {
      if (eqEnabled.value && !ensureGraph()) {
        eqEnabled.value = false
        error.value = '当前音频无法接入均衡器，已切换为直通播放'
      }
    } else if (graphReady) {
      bypassGraph()
    }
    applyVolume()
  }

  // ---- 地址解析 ----
  function mergeAudioInfo(track: PlayerTrack, info: AudioStreamInfo) {
    const nextInfo: PlayerAudioInfo = {
      format: info.format || track.audioInfo?.format,
      codec: info.codec || track.audioInfo?.codec,
      sampleRate: info.sample_rate || track.audioInfo?.sampleRate || 0,
      bitDepth: info.bit_depth || track.audioInfo?.bitDepth || 0,
      channels: info.channels || track.audioInfo?.channels || 0,
      lossless: info.lossless ?? track.audioInfo?.lossless ?? false,
      quality: info.quality || track.audioInfo?.quality,
      size: info.size || track.audioInfo?.size,
    }
    track.audioInfo = nextInfo
    if (info.duration && info.duration > 0) track.duration = info.duration
  }

  async function resolveTrackUrl(
    track: PlayerTrack,
  ): Promise<{ url: string; info?: AudioStreamInfo }> {
    if (track.url) return { url: track.url }
    if (track.kind === 'work') {
      try {
        const info = await api.getWorkStream(track.id)
        if (info?.ok && info.url) return { url: info.url, info }
      } catch {
        /* 桌面直通服务不可用时回退旧 data URI */
      }
      const data = await api.getWorkAudio(track.id)
      if (!data) throw new Error('无法读取作品音频，可能仍在生成或文件已删除')
      return { url: data }
    }
    if (track.kind === 'local') {
      const info = await api.getMusicStream(track.path || track.id)
      if (!info?.ok || !info.url) throw new Error(info?.error || '无法读取本地歌曲')
      return { url: info.url, info }
    }
    const online = track.online
    if (!online) throw new Error('在线歌曲信息缺失')
    const info = await api.streamMusicOnline(online.msg, online.n, online.source, online.songId)
    if (!info?.ok || !info.url) throw new Error(info?.error || '该歌曲暂时无法播放')
    return { url: info.url, info }
  }

  // ---- 播放核心 ----
  async function playAt(
    index: number,
    options: { autoplay?: boolean; restart?: boolean } = {},
  ): Promise<boolean> {
    const track = queue.value[index]
    if (!track) return false
    // 切到队列播放时退出试听状态。
    auditionTrack.value = null
    const autoplay = options.autoplay !== false
    if (track.key === currentKey.value && loadedKey === track.key && options.restart === false) {
      if (autoplay && audioEl?.paused) await resume()
      return true
    }
    loadToken += 1
    const token = loadToken
    currentKey.value = track.key
    currentTime.value = 0
    duration.value = track.duration || 0
    error.value = ''
    lastError.value = ''
    buffering.value = true
    resolvingKey.value = track.key
    // 在用户手势的同步阶段创建/恢复 AudioContext，避免 await 之后被自动播放策略挂起。
    if (eqEnabled.value) {
      try {
        ensureGraph()
      } catch {
        /* 均衡器初始化失败不应阻断播放 */
      }
    }
    if (mode.value === 'shuffle') refreshShuffle(track.key)
    try {
      const { url, info } = await resolveTrackUrl(track)
      if (token !== loadToken) return false
      track.url = url
      if (info) mergeAudioInfo(track, info)
      if (track.duration) duration.value = track.duration
      applySource(track, url)
      if (autoplay) await (audioEl as HTMLAudioElement).play()
      else buffering.value = false
      updateMediaSession(track)
      setMediaPlaybackState(autoplay ? 'playing' : 'paused')
      syncMediaPosition(true)
      persistSoon()
      return true
    } catch (err) {
      if (token !== loadToken) return false
      playing.value = false
      buffering.value = false
      const message = playbackErrorMessage(err)
      error.value = message
      lastError.value = message
      return false
    } finally {
      if (token === loadToken) resolvingKey.value = ''
    }
  }

  function replaceQueue(tracks: PlayerTrack[], startIndex = 0) {
    const deduped = tracks.map((track) => ({ ...track }))
    queue.value = deduped
    const index = Math.max(0, Math.min(startIndex, Math.max(0, deduped.length - 1)))
    currentKey.value = deduped[index]?.key ?? ''
    currentTime.value = 0
    duration.value = deduped[index]?.duration ?? 0
    refreshShuffle(currentKey.value)
    persistSoon()
    return deduped
  }

  async function playQueue(
    tracks: PlayerTrack[],
    startIndex = 0,
    options: { autoplay?: boolean } = {},
  ): Promise<boolean> {
    const deduped = replaceQueue(tracks, startIndex)
    if (!deduped.length) {
      clearQueue()
      return false
    }
    queueOpen.value = false
    const index = Math.max(0, Math.min(startIndex, deduped.length - 1))
    // 清空当前键，确保同一首歌也会重新加载并从头播放。
    currentKey.value = ''
    return playAt(index, { autoplay: options.autoplay !== false })
  }

  /**
   * 单曲播放：把这一首歌加入播放队列并设为当前曲目，不清空已有队列。
   *
   * 作品库、在线曲库的播放按钮使用这个入口；无论播放一首还是多首，正在播放的
   * 歌曲始终在播放队列里，由队列统一管理（上一首 / 下一首、播放模式、持久化）。
   * 只有显式的「队列播放 / 连续试听」才会调用 playQueue / playWorks 重建整个队列。
   */
  async function playAudition(
    track: PlayerTrack,
    options: { autoplay?: boolean } = {},
  ): Promise<boolean> {
    const copy: PlayerTrack = {
      ...track,
      url: undefined,
      fallbackTried: track.fallbackTried ?? false,
    }
    const autoplay = options.autoplay !== false
    loadToken += 1
    const token = loadToken
    auditionTrack.value = copy
    currentTime.value = 0
    duration.value = copy.duration || 0
    error.value = ''
    lastError.value = ''
    buffering.value = true
    resolvingKey.value = copy.key
    queueOpen.value = false
    if (eqEnabled.value) {
      try {
        ensureGraph()
      } catch {
        /* ignore */
      }
    }
    try {
      const { url, info } = await resolveTrackUrl(copy)
      if (token !== loadToken) return false
      copy.url = url
      if (info) mergeAudioInfo(copy, info)
      if (copy.duration) duration.value = copy.duration
      applySource(copy, url)
      // 音频地址已就绪后再并入队列：队列项带着已解析的 url，播放不重新加载。
      if (adoptAuditionTrack()) refreshShuffle()
      if (autoplay) await (audioEl as HTMLAudioElement).play()
      else buffering.value = false
      updateMediaSession(copy)
      setMediaPlaybackState(autoplay ? 'playing' : 'paused')
      syncMediaPosition(true)
      return true
    } catch (err) {
      if (token !== loadToken) return false
      playing.value = false
      buffering.value = false
      const message = playbackErrorMessage(err)
      error.value = message
      lastError.value = message
      return false
    } finally {
      if (token === loadToken) resolvingKey.value = ''
    }
  }

  /** 结束单曲试听状态，回到队列当前曲目（不自动续播）。 */
  function stopAudition() {
    if (!auditionTrack.value) return
    loadToken += 1
    pause()
    auditionTrack.value = null
    loadedKey = ''
    playing.value = false
    buffering.value = false
    resolvingKey.value = ''
    currentTime.value = 0
    duration.value = currentTrack.value?.duration || 0
    if (audioEl) {
      try {
        audioEl.removeAttribute('src')
        audioEl.load()
      } catch {
        /* ignore */
      }
    }
    setMediaPlaybackState('none')
  }

  function playWorks(works: WorkDTO[], workId: string): Promise<boolean> {
    const tracks = works.filter((work) => work.status === 'done').map(workToTrack)
    const index = tracks.findIndex((track) => track.id === workId || track.workId === workId)
    if (index < 0) return Promise.resolve(false)
    return playQueue(tracks, index)
  }

  function playOnlineQueue(
    items: MusicSearchItem[],
    startN: number,
    context: { keyword: string; source: string },
  ): Promise<boolean> {
    const tracks = items.map((item) => onlineToTrack(item, context))
    const index = tracks.findIndex((track) => track.online?.n === startN)
    return playQueue(tracks, index < 0 ? 0 : index)
  }

  function playLocalQueue(items: DownloadedMusic[], startPath: string): Promise<boolean> {
    const tracks = items.map(localToTrack)
    const index = tracks.findIndex((track) => track.id === startPath)
    return playQueue(tracks, index < 0 ? 0 : index)
  }

  async function resume() {
    const active = currentTrack.value
    if (!active) return
    const el = getAudio()
    if (!el.src || loadedKey !== activeKey.value) {
      if (isAudition.value) await playAudition(active)
      else await playAt(Math.max(0, currentIndex.value), { autoplay: true })
      return
    }
    if (eqEnabled.value) ensureGraph()
    try {
      await el.play()
    } catch (err) {
      const name = err instanceof Error ? err.name : ''
      error.value =
        name === 'NotAllowedError'
          ? '系统阻止了自动播放，请再次点击播放'
          : '音频播放失败，请检查文件或网络'
    }
  }

  function pause() {
    try {
      audioEl?.pause()
    } catch {
      /* ignore */
    }
  }

  async function togglePlay() {
    const active = currentTrack.value
    if (!active) return
    if (!audioEl || !audioEl.src || loadedKey !== activeKey.value) {
      if (isAudition.value) await playAudition(active)
      else await playAt(Math.max(0, currentIndex.value), { autoplay: true })
      return
    }
    if (audioEl.paused) {
      if (audioEl.ended || (duration.value > 0 && audioEl.currentTime >= duration.value - 0.05)) {
        seek(0)
      }
      await resume()
    } else {
      pause()
    }
  }

  function stopAtEnd() {
    playing.value = false
    if (audioEl) {
      try {
        audioEl.pause()
      } catch {
        /* ignore */
      }
    }
    currentTime.value = duration.value
    setMediaPlaybackState('paused')
  }

  async function next(auto = false) {
    if (isAudition.value) return
    if (!queue.value.length) return
    if (auto && mode.value === 'single') {
      seek(0)
      await resume()
      return
    }
    const keys = queueKeys()
    if (mode.value === 'shuffle') {
      const valid = shuffleOrderValid(shuffleOrder.value, keys)
      if (!valid) refreshShuffle()
      else if (auto && shuffleOrder.value[shuffleOrder.value.length - 1] === currentKey.value) {
        // 一轮随机播完，重新洗牌（当前歌曲仍排在最前，避免立即重复）。
        refreshShuffle()
      }
    }
    const key = resolveNextKey({
      keys,
      currentKey: currentKey.value,
      mode: mode.value,
      shuffleOrder: shuffleOrder.value,
    })
    if (!key) {
      stopAtEnd()
      return
    }
    const index = queue.value.findIndex((track) => track.key === key)
    if (index >= 0) await playAt(index, { autoplay: true })
  }

  async function previous() {
    if (isAudition.value) return
    if (!queue.value.length) return
    if (audioEl && audioEl.currentTime > 3 && !audioEl.paused) {
      seek(0)
      return
    }
    const keys = queueKeys()
    if (mode.value === 'shuffle' && !shuffleOrderValid(shuffleOrder.value, keys)) {
      refreshShuffle()
    }
    const key = resolvePreviousKey({
      keys,
      currentKey: currentKey.value,
      mode: mode.value,
      shuffleOrder: shuffleOrder.value,
    })
    if (!key) return
    const index = queue.value.findIndex((track) => track.key === key)
    if (index >= 0) await playAt(index, { autoplay: true })
  }

  function seek(time: number) {
    const maximum = duration.value || audioEl?.duration || 0
    const target = clamp(time, 0, maximum > 0 ? maximum : Math.max(0, time))
    currentTime.value = target
    if (audioEl && Number.isFinite(target)) {
      try {
        audioEl.currentTime = target
      } catch {
        /* ignore */
      }
    }
    syncMediaPosition(true)
  }

  function seekBy(delta: number) {
    seek(currentTime.value + delta)
  }

  function setVolume(value: number) {
    volume.value = clamp(value, 0, 1)
    if (volume.value > 0 && muted.value) muted.value = false
    applyVolume()
    persistSoon()
  }

  function toggleMute() {
    muted.value = !muted.value
    applyVolume()
    persistSoon()
  }

  // ---- 队列编辑 ----
  /**
   * 把「单曲试听」并入播放队列（不重新加载音频）。
   *
   * 试听曲目直接成为队列里的当前项：<audio> 的 src、播放进度和播放状态都不动，
   * 因此正在播放的歌曲不会被打断；之后它和队列里的其它歌曲一样由队列管理
   * （上一首 / 下一首、播放模式、重排、移除都生效）。
   */
  function adoptAuditionTrack(): PlayerTrack | null {
    const audition = auditionTrack.value
    if (!audition) return null
    auditionTrack.value = null
    const existing = queue.value.find((track) => track.key === audition.key)
    if (existing) {
      // 队列里已有这首歌：用刚解析到的地址 / 音质信息刷新，避免界面显示旧数据。
      if (audition.url) existing.url = audition.url
      if (audition.audioInfo) existing.audioInfo = audition.audioInfo
      if (!existing.duration && audition.duration) existing.duration = audition.duration
      currentKey.value = existing.key
      sessionStarted.value = true
      return existing
    }
    // 保留已解析的 url / audioInfo / duration，避免重新解析地址或重置进度。
    const adopted: PlayerTrack = { ...audition }
    queue.value.push(adopted)
    currentKey.value = adopted.key
    sessionStarted.value = true
    return adopted
  }

  function addToQueue(tracks: PlayerTrack[], options: { next?: boolean } = {}): number {
    // 正在试听时先把试听曲目并入队列：播放中的歌曲和新加入的歌曲都进入队列，
    // 并且不重新加载音频，保证正在播放的声音不中断。
    const adopted = adoptAuditionTrack()
    const existing = new Set(queue.value.map((track) => track.key))
    const additions = tracks.filter((track) => !existing.has(track.key)).map((track) => ({ ...track }))
    if (!additions.length) {
      if (adopted) {
        refreshShuffle()
        persistSoon()
      }
      return 0
    }
    const anchor = adopted
      ? queue.value.findIndex((track) => track.key === adopted.key)
      : currentIndex.value
    if (options.next && anchor >= 0) {
      queue.value.splice(anchor + 1, 0, ...additions)
    } else {
      queue.value.push(...additions)
    }
    if (!currentKey.value) {
      currentKey.value = queue.value[0]?.key ?? ''
      duration.value = queue.value[0]?.duration ?? 0
    }
    sessionStarted.value = true
    refreshShuffle()
    persistSoon()
    return additions.length
  }

  function removeTrack(key: string) {
    const index = queue.value.findIndex((track) => track.key === key)
    if (index < 0) return
    const wasCurrent = key === currentKey.value
    const wasPlaying = playing.value
    const replacementKey = queue.value[index + 1]?.key ?? queue.value[index - 1]?.key ?? ''
    const remaining = queue.value.filter((track) => track.key !== key)
    queue.value = remaining
    refreshShuffle()
    if (auditionTrack.value) {
      // 试听中编辑队列不应打断试听；只更新队列的当前选中项。
      if (wasCurrent) {
        if (remaining.length) {
          const nextIndex = Math.max(
            0,
            remaining.findIndex((track) => track.key === replacementKey),
          )
          currentKey.value = remaining[nextIndex]?.key ?? ''
        } else {
          currentKey.value = ''
        }
      }
      persistSoon()
      return
    }
    if (!wasCurrent) {
      persistSoon()
      return
    }
    if (!remaining.length) {
      clearQueue()
      return
    }
    const targetIndex = Math.max(
      0,
      remaining.findIndex((track) => track.key === replacementKey),
    )
    currentKey.value = remaining[targetIndex]?.key ?? ''
    currentTime.value = 0
    duration.value = remaining[targetIndex]?.duration ?? 0
    refreshShuffle()
    void playAt(targetIndex, { autoplay: wasPlaying })
  }

  function moveTrack(from: number, to: number) {
    queue.value = moveItem(queue.value, from, to)
    refreshShuffle()
    persistSoon()
  }

  function jumpTo(key: string) {
    const index = queue.value.findIndex((track) => track.key === key)
    if (index >= 0) void playAt(index, { autoplay: true })
  }

  function clearQueue() {
    queue.value = []
    currentKey.value = ''
    auditionTrack.value = null
    currentTime.value = 0
    duration.value = 0
    sessionStarted.value = false
    loadToken += 1
    loadedKey = ''
    loadingReset()
    persistSoon()
  }

  function loadingReset() {
    pause()
    if (audioEl) {
      try {
        audioEl.removeAttribute('src')
        audioEl.load()
      } catch {
        /* ignore */
      }
    }
    playing.value = false
    buffering.value = false
    resolvingKey.value = ''
    setMediaPlaybackState('none')
    refreshShuffle('')
  }

  // ---- 播放模式 ----
  function setMode(value: PlayMode) {
    if (!isPlayMode(value)) return
    mode.value = value
    if (value === 'shuffle') refreshShuffle()
    persistSoon()
  }

  function cycleMode() {
    setMode(nextPlayMode(mode.value))
  }

  // ---- 均衡器 ----
  function setEqEnabled(value: boolean) {
    if (value && !ensureGraph()) {
      error.value = '当前环境不支持 Web Audio，无法启用均衡器'
      return
    }
    eqEnabled.value = value
    applyEq()
    applyVolume()
    persistSoon()
  }

  function toggleEq() {
    setEqEnabled(!eqEnabled.value)
  }

  function setEqGain(index: number, gain: number) {
    if (index < 0 || index >= EQ_FREQUENCIES.length) return
    const next = [...eqGains.value]
    next[index] = clamp(gain, -12, 12)
    eqGains.value = next
    applyEq()
    persistSoon()
  }

  function applyEqPreset(id: string) {
    const preset = EQ_PRESETS.find((item) => item.id === id)
    if (!preset) return
    eqGains.value = [...preset.gains]
    if (!eqEnabled.value) setEqEnabled(true)
    else applyEq()
    persistSoon()
  }

  function resetEq() {
    eqGains.value = EQ_FREQUENCIES.map(() => 0)
    applyEq()
    persistSoon()
  }

  function toggleQueue(open = !queueOpen.value) {
    if (open) {
      // 打开队列时把单曲试听并入队列，让面板里的「正在播放」与真实播放一致。
      if (adoptAuditionTrack()) {
        refreshShuffle()
        persistSoon()
      }
    }
    queueOpen.value = open
  }

  function isCurrent(key: string): boolean {
    return activeKey.value === key
  }

  /**
   * 当前曲目的音频地址是否已经加载。
   *
   * 用于进入播放页时决定是否自动开始：已加载但暂停的曲目保持暂停（不打断用户），
   * 只是被选为当前项、还没加载过的曲目则自动开始播放。
   */
  function isCurrentLoaded(): boolean {
    return !!loadedKey && loadedKey === activeKey.value
  }

  function isPlayingKey(key: string): boolean {
    return activeKey.value === key && playing.value
  }

  function clearError() {
    error.value = ''
  }

  // 队列与设置变化后持久化（url 在写入前剔除）。
  watch(queue, persistSoon, { deep: true })
  watch([mode, volume, muted, eqEnabled, eqGains, currentKey], persistSoon, { deep: true })

  return {
    // 状态
    queue,
    currentKey,
    activeKey,
    auditionTrack,
    isAudition,
    currentTrack,
    currentIndex,
    mode,
    volume,
    muted,
    eqEnabled,
    eqGains,
    queueOpen,
    playing,
    sessionStarted,
    buffering,
    currentTime,
    duration,
    error,
    lastError,
    resolvingKey,
    shuffleOrder,
    // 派生
    hasQueue,
    progress,
    canGoNext,
    canGoPrev,
    queueDuration,
    currentQuality,
    currentDetail,
    isLossless,
    eqSupported,
    // 播放
    playAt,
    playQueue,
    playAudition,
    stopAudition,
    playWorks,
    playOnlineQueue,
    playLocalQueue,
    togglePlay,
    resume,
    pause,
    next,
    previous,
    seek,
    seekBy,
    setVolume,
    toggleMute,
    // 队列
    addToQueue,
    removeTrack,
    moveTrack,
    jumpTo,
    clearQueue,
    // 模式
    setMode,
    cycleMode,
    // 均衡器
    setEqEnabled,
    toggleEq,
    setEqGain,
    applyEqPreset,
    resetEq,
    // 界面
    toggleQueue,
    isCurrent,
    isCurrentLoaded,
    isPlayingKey,
    clearError,
  }
})
