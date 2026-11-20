<template>
  <div class="player-page">
    <div v-if="loading" class="player-loading">
      <el-icon class="loading-icon"><Loading /></el-icon>
      <span>正在准备播放页面…</span>
    </div>

    <template v-else-if="track">
      <header class="player-head">
        <button class="icon-btn" title="返回" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="head-context">
          <span class="head-kicker">NOW PLAYING</span>
          <span class="head-title">作品试听</span>
        </div>
        <div class="head-actions">
          <button
            v-if="showsQueueControls"
            class="text-btn queue-entry"
            title="打开播放队列"
            @click="player.toggleQueue()"
          >
            <el-icon><List /></el-icon>
            播放队列
            <span class="queue-count">{{ player.queue.length }}</span>
          </button>
          <el-popover
            placement="bottom-end"
            :width="380"
            trigger="click"
            popper-class="hifi-popover"
          >
            <template #reference>
              <button class="text-btn hifi-entry" title="高保真输出设置">
                <span class="hifi-dot"></span>
                HIFI
              </button>
            </template>
            <HiFiPanel />
          </el-popover>
          <el-dropdown
            v-if="canDownload"
            trigger="click"
            @command="(fmt: string | number | object) => downloadWork(String(fmt) as WorkAudioExportFormat)"
          >
            <button class="icon-btn" title="选择格式下载作品">
              <el-icon><Download /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="wav">WAV 无损</el-dropdown-item>
                <el-dropdown-item command="flac">FLAC 无损压缩</el-dropdown-item>
                <el-dropdown-item command="mp3">MP3 通用格式</el-dropdown-item>
                <el-dropdown-item command="m4a">M4A 移动设备</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <button class="text-btn" @click="router.push('/works')">作品库</button>
        </div>
      </header>

      <main class="player-layout">
        <section
          class="visual-stage"
          data-guide="player-visual"
          :class="{ 'has-media': !!mediaData, 'has-video': hasVideo }"
          :style="stageStyle"
        >
          <div v-if="mediaData" class="stage-media" :class="`is-${mediaKind}`" aria-hidden="true">
            <video
              v-if="mediaKind === 'video'"
              ref="mvVideoEl"
              :src="mediaData"
              muted
              playsinline
              preload="metadata"
              @loadedmetadata="syncVideoToAudio(true)"
            />
            <img v-else :src="mediaData" alt="" />
          </div>
          <div v-if="!hasVideo" class="stage-shade"></div>
          <div v-if="!hasVideo" class="stage-content">
            <div class="stage-label">
              <span class="live-dot"></span>
              {{ trackKindLabel }}
            </div>
            <div class="record" :class="{ spinning: player.playing }" :style="{ '--record-color': coverColor }">
              <div class="record-groove"></div>
              <div class="record-art"><el-icon><Headset /></el-icon></div>
              <div class="record-hole"></div>
            </div>
            <div class="track-heading">
              <h1 :title="track.title">{{ track.title }}</h1>
              <p>{{ track.subtitle }}<span v-if="track.album"> · {{ track.album }}</span></p>
            </div>
            <div class="hifi-strip" :class="{ lossless: player.isLossless }">
              <span class="hifi-badge">{{ player.currentQuality || '音频直通' }}</span>
              <span class="hifi-detail">{{ player.currentDetail || '正在解析音源参数…' }}</span>
              <span v-if="player.eqEnabled" class="hifi-eq">EQ</span>
            </div>
          </div>
          <div v-if="isWork" class="stage-tools">
            <button
              class="media-btn"
              :class="{ active: !!mediaData }"
              title="为这首歌导入画面 MV"
              @click="importVisual"
            >
              <el-icon><VideoCamera /></el-icon>
              <span>{{ mediaData ? '更换 MV' : '导入画面 MV' }}</span>
            </button>
            <button v-if="mediaData" class="media-remove" title="移除 MV 画面" @click="removeVisual">
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </section>

        <section class="lyrics-panel" data-guide="player-lyrics">
          <div class="panel-head">
            <div>
              <p class="eyebrow">LYRICS</p>
              <h2>歌词</h2>
            </div>
            <span class="lyrics-count">{{ lyrics.length ? `${lyrics.length} 句` : '未载入' }}</span>
          </div>
          <div class="lyric-search">
            <div class="source-field">
              <el-select v-model="lyricSource" class="lyric-source-select" aria-label="歌词曲库" @change="resetLyricSearch">
                <el-option v-for="source in lyricSources" :key="source.id" :label="source.name" :value="source.id" />
              </el-select>
            </div>
            <el-icon><Search /></el-icon>
            <input v-model="lyricQuery" type="search" placeholder="搜索歌名 / 歌手，再获取对应歌词" @keyup.enter="searchLyricSongs" />
            <button :disabled="lyricSearching || !lyricQuery.trim()" title="搜索歌词歌曲" @click="searchLyricSongs">
              <el-icon v-if="lyricSearching" class="spin"><Loading /></el-icon>
              <el-icon v-else><Search /></el-icon>
            </button>
          </div>
          <div v-if="lyricSearchResults.length" class="lyric-results">
            <button
              v-for="item in lyricSearchResults"
              :key="`${lyricSource}-${item.n}-${item.rid || item.name}`"
              :class="{ selected: isLyricSongSelected(item) }"
              @click="chooseLyricSong(item)"
            >
              <span class="lyric-result-main">
                <b>#{{ item.n }}</b>
                <span>
                  <strong>{{ item.name }}</strong>
                  <em>{{ [item.singer, item.album].filter(Boolean).join(' · ') || '未知歌手' }}</em>
                </span>
              </span>
              <small>{{ isLyricSongSelected(item) ? '已选中' : (item.subtitle || item.pay || '点击选择') }}</small>
            </button>
          </div>
          <div v-if="selectedLyricSong" class="lyric-selected">
            <span>已选中 #{{ selectedLyricSong.n }} {{ selectedLyricSong.name }}</span>
            <small>{{ [selectedLyricSong.singer, selectedLyricSong.album].filter(Boolean).join(' · ') || '待获取歌词' }}</small>
          </div>
          <div class="lyrics-actions">
            <button class="lyric-action primary" :disabled="lyricsLoading || needsLyricSelection" @click="fetchLyrics">
              <el-icon v-if="lyricsLoading" class="spin"><Loading /></el-icon>
              <el-icon v-else><MagicStick /></el-icon>
              {{ lyricsLoading ? '获取中' : (selectedLyricSong ? '获取选中歌曲歌词' : (needsLyricSelection ? '请先选择结果' : '按歌曲名获取')) }}
            </button>
            <button class="lyric-action" @click="importLyrics">
              <el-icon><Upload /></el-icon> 导入 LRC
            </button>
            <router-link class="music-link" to="/music">曲库设置</router-link>
          </div>
          <p v-if="needsLyricSelection" class="lyrics-tip">搜索结果可能有多个，请先点选第几个版本，再获取歌词。</p>
          <p v-if="lyricsMessage" class="lyrics-message" :class="{ error: lyricsError }">{{ lyricsMessage }}</p>
          <div v-if="lyrics.length" ref="lyricsEl" class="lyrics-scroll">
            <button
              v-for="(line, index) in lyrics"
              :key="`${line.time}-${index}`"
              class="lyric-line"
              :class="{ active: activeLyric === index }"
              @click="seekTo(line.time)"
            >
              <span class="lyric-time">{{ formatTime(line.time) }}</span>
              <span>{{ line.text }}</span>
            </button>
          </div>
          <div v-else class="lyrics-empty">
            <el-icon><ChatLineSquare /></el-icon>
            <strong>让歌词跟着音乐亮起来</strong>
            <span>从本地导入 LRC，或使用曲库 API 获取时间轴歌词。</span>
          </div>
        </section>
      </main>

      <section class="transport glass" data-guide="player-transport">
        <div class="transport-controls">
          <PlayModeButton v-if="showsQueueControls" class="transport-mode" />
          <button
            v-if="showsQueueControls"
            class="transport-skip"
            title="上一首"
            :disabled="!player.canGoPrev"
            @click="player.previous()"
          >
            <el-icon><CaretLeft /></el-icon>
          </button>
          <button
            class="transport-play"
            :title="player.playing ? '暂停' : '播放'"
            :disabled="!player.hasQueue"
            @click="player.togglePlay()"
          >
            <el-icon v-if="player.resolvingKey" class="spin"><Loading /></el-icon>
            <el-icon v-else-if="player.playing"><VideoPause /></el-icon>
            <el-icon v-else><VideoPlay /></el-icon>
          </button>
          <button
            v-if="showsQueueControls"
            class="transport-skip"
            title="下一首"
            :disabled="!player.canGoNext"
            @click="player.next(false)"
          >
            <el-icon><CaretRight /></el-icon>
          </button>
        </div>
        <div class="transport-main">
          <div class="transport-title">
            <span :title="track.title">{{ track.title }}</span>
            <span class="transport-model">
              <span v-if="!showsQueueControls" class="audition-tag">单曲试听</span>
              <span v-else class="audition-tag queue">队列播放</span>
              {{ track.subtitle }}
            </span>
          </div>
          <input
            class="seek"
            type="range"
            min="0"
            :max="duration || 0.01"
            step="0.01"
            :value="seekDisplay"
            aria-label="播放进度"
            @input="onSeekInput"
            @change="seekDraft = null"
          />
          <div class="transport-times">
            <span>{{ formatTime(seekDisplay) }}</span>
            <span>{{ formatTime(duration) }}</span>
          </div>
        </div>
        <div class="transport-side">
          <div class="hifi-inline" :class="{ lossless: player.isLossless }" :title="player.currentDetail || '直通输出'">
            <span class="hifi-dot"></span>
            <span>{{ player.currentDetail || '直通输出' }}</span>
          </div>
          <div class="volume-control">
            <button class="volume-mute" :title="player.muted ? '取消静音' : '静音'" @click="player.toggleMute()">
              <el-icon v-if="player.muted"><Mute /></el-icon>
              <el-icon v-else><Headset /></el-icon>
            </button>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              :value="player.volume"
              title="音量"
              aria-label="音量"
              @input="onVolume"
            />
          </div>
          <button v-if="showsQueueControls" class="queue-btn" title="播放队列" @click="player.toggleQueue()">
            <el-icon><List /></el-icon>
            <span>{{ player.queue.length }}</span>
          </button>
        </div>
      </section>
    </template>

    <div v-else class="not-found glass" data-guide="player-empty">
      <el-icon><Headset /></el-icon>
      <h2>还没有可试听的作品</h2>
      <p>生成或导入作品后，在作品库点击试听；在线曲库主要用于获取翻唱素材。</p>
      <div class="not-found-actions">
        <el-button class="cta-btn" round @click="router.push('/works')">打开作品库</el-button>
        <el-button round @click="router.push('/music')">在线曲库</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  CaretLeft,
  CaretRight,
  ChatLineSquare,
  Close,
  Download,
  Headset,
  List,
  Loading,
  MagicStick,
  Mute,
  Search,
  Upload,
  VideoCamera,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  api,
  pickColor,
  type LyricLine,
  type MusicSearchItem,
  type MusicSource,
  type WorkAudioExportFormat,
} from '@/api'
import HiFiPanel from '@/components/player/HiFiPanel.vue'
import PlayModeButton from '@/components/player/PlayModeButton.vue'
import { formatTime } from '@/player/format'
import { workToTrack } from '@/player/tracks'
import { usePlayerStore } from '@/stores/player'
import { useWorksStore } from '@/stores/works'

defineOptions({ name: 'PlayerPage' })

const route = useRoute()
const router = useRouter()
const player = usePlayerStore()
const worksStore = useWorksStore()

const loading = ref(true)
const mvVideoEl = ref<HTMLVideoElement | null>(null)
const lyrics = ref<LyricLine[]>([])
const activeLyric = ref(-1)
const lyricsLoading = ref(false)
const lyricSearching = ref(false)
const lyricQuery = ref('')
const lyricSearchResults = ref<MusicSearchItem[]>([])
const lyricSearchKeyword = ref('')
const selectedLyricSong = ref<MusicSearchItem | null>(null)
const lyricSources = ref<MusicSource[]>([{ id: 'wy', name: '网易云音乐', cookie: false }])
const lyricSource = ref('wy')
const lyricsMessage = ref('')
const lyricsError = ref(false)
const lyricsEl = ref<HTMLElement | null>(null)
const mediaData = ref('')
const mediaPath = ref('')
const mediaKind = ref<'image' | 'video'>('image')
const mediaName = ref('')
const seekDraft = ref<number | null>(null)

const requestedWorkId = computed(() => String(route.query.work || route.params.id || ''))
const track = computed(() => player.currentTrack)
const isWork = computed(() => track.value?.kind === 'work')
const workId = computed(() => {
  const current = track.value
  if (!current) return requestedWorkId.value
  if (current.workId) return current.workId
  return current.kind === 'work' ? current.id : requestedWorkId.value
})
const work = computed(() => worksStore.works.find((item) => item.id === workId.value) || null)
const canDownload = computed(() => isWork.value && work.value?.status === 'done')
const showsQueueControls = computed(() => player.queue.length > 1 && !player.isAudition)
const coverColor = computed(() => track.value?.color || pickColor(workId.value || 'player'))
const duration = computed(() => player.duration || track.value?.duration || 0)
const seekDisplay = computed(() => seekDraft.value ?? player.currentTime)
const hasVideo = computed(() => mediaKind.value === 'video' && !!mediaData.value)
const stageStyle = computed(() => ({ '--stage-color': coverColor.value }))
const trackKey = computed(
  () => track.value?.key || (requestedWorkId.value ? `work:${requestedWorkId.value}` : 'shared'),
)
const trackKindLabel = computed(() => {
  if (!track.value) return ''
  const format = (track.value.audioInfo?.format || work.value?.format || 'AUDIO').toUpperCase()
  if (track.value.kind === 'work') return `AI COVER · ${format}`
  if (track.value.kind === 'online') return 'ONLINE · 在线曲库'
  return 'LOCAL · 已下载'
})
const needsLyricSelection = computed(
  () => lyricSearchResults.value.length > 0 && !selectedLyricSong.value,
)

const storagePrefix = 'xb-player-'

function storageKey(suffix: string) {
  return `${storagePrefix}${suffix}-v2-${trackKey.value}`
}

function legacyStorageKey(suffix: string) {
  return `${storagePrefix}${suffix}-${workId.value}`
}

function readStored(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage may be disabled */
  }
}

function removeStored(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

function parseLyrics(text: string): LyricLine[] {
  const result: LyricLine[] = []
  const pattern = /\[(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?\]/g
  for (const raw of String(text || '').split(/\r?\n/)) {
    const tags = [...raw.matchAll(pattern)]
    const value = raw.replace(pattern, '').trim()
    if (!value || !tags.length) continue
    for (const tag of tags) {
      const fraction = String(tag[3] || '').padEnd(3, '0').slice(0, 3)
      result.push({ time: Number(tag[1]) * 60 + Number(tag[2]) + Number(fraction) / 1000, text: value })
    }
  }
  return result.sort((a, b) => a.time - b.time)
}

function saveLyrics(lines: LyricLine[], source: string) {
  lyrics.value = lines
  activeLyric.value = -1
  lyricsMessage.value = source
  lyricsError.value = false
  writeStored(storageKey('lyrics'), JSON.stringify(lines))
  void nextTick(updateActiveLyric)
}

function loadSavedLyrics() {
  lyrics.value = []
  activeLyric.value = -1
  const raw =
    readStored(storageKey('lyrics')) ||
    (isWork.value && workId.value ? readStored(legacyStorageKey('lyrics')) : null)
  if (!raw) return
  try {
    const saved = JSON.parse(raw) as LyricLine[]
    if (Array.isArray(saved)) {
      lyrics.value = saved.filter((line) => Number.isFinite(line?.time) && line?.text)
    }
  } catch {
    /* ignore invalid local data */
  }
}

async function fetchLyrics() {
  const current = track.value
  if (!current) return
  if (needsLyricSelection.value) {
    lyricsError.value = true
    lyricsMessage.value = '请先在搜索结果中选择第几个版本，再获取歌词。'
    return
  }
  lyricsLoading.value = true
  lyricsMessage.value = ''
  lyricsError.value = false
  const owner = trackKey.value
  try {
    const item = selectedLyricSong.value
    const query = (item ? lyricSearchKeyword.value : lyricQuery.value.trim()) || current.title
    const songId = lyricSource.value === 'kuwo' ? undefined : item?.rid || undefined
    const res = await api.getMusicLyrics(query, item?.n || 1, lyricSource.value, songId)
    if (owner !== trackKey.value) return
    if (!res.ok || !res.lines?.length) {
      lyricsError.value = true
      lyricsMessage.value = res.error || '没有找到时间轴歌词，请尝试导入 LRC 文件。'
      return
    }
    saveLyrics(res.lines, `已通过曲库 API 获取${item ? ` · ${item.name}` : ''}`)
    ElMessage.success(`已获取 ${res.lines.length} 句歌词`)
  } catch (error) {
    lyricsError.value = true
    lyricsMessage.value = error instanceof Error ? error.message : '歌词 API 请求失败'
  } finally {
    lyricsLoading.value = false
  }
}

async function searchLyricSongs() {
  const query = lyricQuery.value.trim()
  if (!query) return
  lyricSearching.value = true
  selectedLyricSong.value = null
  lyricSearchKeyword.value = ''
  try {
    const res = await api.searchMusic(query, lyricSource.value)
    if (!res.ok) {
      lyricSearchResults.value = []
      lyricsError.value = true
      lyricsMessage.value = res.error || '歌词搜索失败，请检查曲库 API 设置。'
      return
    }
    lyricSearchKeyword.value = query
    lyricSearchResults.value = (res.songs || []).slice(0, 8)
    if (!lyricSearchResults.value.length) {
      lyricsError.value = true
      lyricsMessage.value = '没有找到对应歌曲，请换个歌名或歌手。'
    } else {
      lyricsError.value = false
      lyricsMessage.value = `已找到 ${lyricSearchResults.value.length} 条结果，请选择第几个版本再获取歌词。`
    }
  } catch (error) {
    lyricsError.value = true
    lyricsMessage.value = error instanceof Error ? error.message : '歌词搜索失败'
  } finally {
    lyricSearching.value = false
  }
}

function chooseLyricSong(item: MusicSearchItem) {
  selectedLyricSong.value = item
  lyricSearchResults.value = []
  lyricsError.value = false
  lyricsMessage.value = `已选中 #${item.n} ${item.name}，点击“获取选中歌曲歌词”继续。`
}

function isLyricSongSelected(item: MusicSearchItem) {
  return (
    selectedLyricSong.value?.n === item.n &&
    selectedLyricSong.value?.rid === item.rid &&
    selectedLyricSong.value?.name === item.name
  )
}

function resetLyricSearch() {
  lyricSearchResults.value = []
  lyricSearchKeyword.value = ''
  selectedLyricSong.value = null
  lyricsMessage.value = ''
}

async function importLyrics() {
  const result = await api.pickLyricsFile()
  if (!result.ok || !result.text) {
    if (!result.cancelled) ElMessage.error(result.error || '无法读取歌词文件')
    return
  }
  const parsed = parseLyrics(result.text)
  if (!parsed.length) {
    ElMessage.warning('未找到带时间轴的歌词，请选择 LRC 文件（例如 [00:12.30] 歌词）')
    return
  }
  saveLyrics(parsed, `已导入 ${result.name || '本地歌词'}`)
  ElMessage.success(`已导入 ${parsed.length} 句歌词`)
}

async function importVisual() {
  if (!isWork.value) {
    ElMessage.info('MV 画面目前绑定在翻唱作品上')
    return
  }
  const result = await api.pickThemeMediaFile()
  if (!result.ok || !result.path) {
    if (!result.cancelled) ElMessage.error(result.error || '无法读取 MV 文件')
    return
  }
  const data = await api.getThemeMediaData(result.path)
  if (!data) {
    ElMessage.error('无法加载这个 MV 文件')
    return
  }
  mediaPath.value = result.path
  mediaKind.value = result.kind || 'image'
  mediaName.value = result.name || '自定义 MV'
  mediaData.value = data
  writeStored(
    storageKey('visual'),
    JSON.stringify({ path: mediaPath.value, kind: mediaKind.value, name: mediaName.value }),
  )
  await nextTick()
  syncVideoToAudio(true)
  ElMessage.success(`已设置画面：${mediaName.value}`)
}

function loadSavedVisual() {
  clearVisual()
  if (!isWork.value) return
  const raw =
    readStored(storageKey('visual')) ||
    (workId.value ? readStored(legacyStorageKey('visual')) : null)
  if (!raw) return
  try {
    const saved = JSON.parse(raw) as { path?: string; kind?: string; name?: string }
    if (!saved?.path) return
    const owner = trackKey.value
    const path = String(saved.path)
    mediaPath.value = path
    mediaKind.value = saved.kind === 'video' ? 'video' : 'image'
    mediaName.value = String(saved.name || '自定义 MV')
    void api.getThemeMediaData(path).then(async (data) => {
      if (owner !== trackKey.value) return
      mediaData.value = data || ''
      await nextTick()
      syncVideoToAudio(true)
    })
  } catch {
    /* ignore invalid local data */
  }
}

function clearVisual() {
  mvVideoEl.value?.pause()
  mediaData.value = ''
  mediaPath.value = ''
  mediaKind.value = 'image'
  mediaName.value = ''
}

function removeVisual() {
  clearVisual()
  removeStored(storageKey('visual'))
  if (isWork.value) removeStored(legacyStorageKey('visual'))
}

function syncVideoToAudio(forceSeek = false) {
  const video = mvVideoEl.value
  if (!video || !hasVideo.value || video.readyState < HTMLMediaElement.HAVE_METADATA) return
  const maximumTime = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.05) : player.currentTime
  const targetTime = Math.min(Math.max(0, player.currentTime), maximumTime)
  if (forceSeek || Math.abs(video.currentTime - targetTime) > 0.3) {
    video.currentTime = targetTime
  }
  if (!player.playing) {
    video.pause()
  } else if (video.paused && targetTime < maximumTime) {
    void video.play().catch(() => {
      /* the next audio event will retry */
    })
  }
}

function updateActiveLyric() {
  if (!lyrics.value.length) {
    activeLyric.value = -1
    return
  }
  let next = -1
  for (let i = 0; i < lyrics.value.length; i += 1) {
    const line = lyrics.value[i]
    if (line && line.time <= player.currentTime + 0.08) next = i
    else break
  }
  if (next !== activeLyric.value) {
    activeLyric.value = next
    void nextTick(scrollActiveLyricIntoView)
  }
}

function scrollActiveLyricIntoView() {
  const container = lyricsEl.value
  const target = container?.querySelector('.lyric-line.active') as HTMLElement | null
  if (!container || !target) return
  const containerRect = container.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const relativeTop = targetRect.top - containerRect.top - container.clientTop
  const centeredTop =
    container.scrollTop + relativeTop - (container.clientHeight - targetRect.height) / 2
  const maximumTop = Math.max(0, container.scrollHeight - container.clientHeight)
  container.scrollTo({
    top: Math.min(maximumTop, Math.max(0, centeredTop)),
    behavior: 'smooth',
  })
}

function onSeekInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  seekDraft.value = value
  player.seek(value)
}

function onVolume(event: Event) {
  player.setVolume(Number((event.target as HTMLInputElement).value))
}

function seekTo(time: number) {
  player.seek(time)
  if (!player.playing) void player.togglePlay()
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/works')
}

async function downloadWork(format: WorkAudioExportFormat) {
  if (!work.value) return
  const dest = await api.exportWork(work.value.id, format)
  if (dest) ElMessage.success(`已导出到：${dest}`)
}

async function handleTrackChange() {
  resetLyricSearch()
  lyricsMessage.value = ''
  lyricsError.value = false
  seekDraft.value = null
  if (!track.value) {
    lyrics.value = []
    activeLyric.value = -1
    clearVisual()
    return
  }
  lyricQuery.value = track.value.title || ''
  loadSavedLyrics()
  if (isWork.value) loadSavedVisual()
  else clearVisual()
  await nextTick()
  updateActiveLyric()
  syncVideoToAudio(true)
}

watch(
  () => player.activeKey,
  () => {
    void handleTrackChange()
  },
)

watch(
  () => player.currentTime,
  () => {
    updateActiveLyric()
    syncVideoToAudio()
  },
)

watch(
  () => player.playing,
  () => syncVideoToAudio(),
)

onMounted(async () => {
  try {
    const [sourceList, currentSource] = await Promise.all([
      api.listMusicSources(),
      api.getMusicSource(),
      worksStore.ensureLoaded(),
    ])
    if (sourceList.length) lyricSources.value = sourceList
    if (sourceList.some((source) => source.id === currentSource)) lyricSource.value = currentSource

    const requested = requestedWorkId.value
    if (requested) {
      const tracks = worksStore.works
        .filter((item) => item.status === 'done')
        .map((item) => workToTrack(item))
      const index = tracks.findIndex((item) => item.workId === requested)
      if (index >= 0) {
        const requestedTrack = tracks[index] as (typeof tracks)[number]
        const queueRequested = String(route.query.queue || '') === '1'
        if (queueRequested) {
          // 队列已经由「队列播放」按钮按当前筛选结果建好；只有直接带
          // queue=1 打开页面、队列里又没有该作品时才回退到全部作品。
          const hasRequested = player.queue.some((item) => item.key === requestedTrack.key)
          if (!hasRequested) {
            await player.playQueue(tracks, index, { autoplay: player.playing })
          } else if (player.currentTrack?.key !== requestedTrack.key) {
            const queueIndex = player.queue.findIndex((item) => item.key === requestedTrack.key)
            if (queueIndex >= 0) await player.playAt(queueIndex, { autoplay: player.playing })
          }
        } else if (
          !player.isAudition ||
          player.currentTrack?.key !== requestedTrack.key
        ) {
          // 默认只试听当前作品，不把其余作品加入队列，也不破坏已有的音乐队列。
          await player.playAudition(requestedTrack, { autoplay: player.playing })
        }
      }
    }
    await handleTrackChange()
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  // 单曲试听是临时行为：离开试听页就停止，不留下后台播放。
  if (player.isAudition) player.stopAudition()
})
</script>

<style scoped>
.player-page { min-height: calc(100vh - 64px); max-width: 1440px; margin: 0 auto; padding: 20px 28px 42px; color: var(--xb-text); }
.player-head { display: flex; align-items: center; gap: 14px; min-height: 46px; margin-bottom: 18px; }
.head-context { display: flex; align-items: baseline; gap: 10px; }
.head-kicker, .eyebrow { color: var(--xb-primary); font: 700 11px/1 ui-monospace, monospace; letter-spacing: 1.6px; }
.head-title { color: var(--xb-muted); font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.icon-btn { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--xb-border); border-radius: 50%; background: rgba(var(--xb-fill-rgb), .04); color: var(--xb-text); cursor: pointer; transition: .2s ease; }
.icon-btn:hover { color: var(--xb-primary); border-color: var(--xb-primary); transform: translateY(-1px); }
.text-btn { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--xb-muted); cursor: pointer; padding: 8px 10px; font-size: 12px; border-radius: 8px; transition: .2s ease; }
.text-btn:hover { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .06); }
.queue-count { min-width: 17px; height: 17px; padding: 0 4px; border-radius: 999px; background: rgba(var(--xb-primary-rgb), .14); color: var(--xb-primary); font: 10px/17px ui-monospace, monospace; text-align: center; }
.hifi-entry { color: var(--xb-primary); font-weight: 700; letter-spacing: .6px; }
.hifi-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--xb-success); box-shadow: 0 0 10px var(--xb-success); }
.player-layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(340px, .85fr); align-items: stretch; gap: 18px; height: clamp(620px, calc(100dvh - 205px), 700px); min-height: 0; }
.visual-stage { position: relative; height: 100%; min-height: 0; overflow: hidden; isolation: isolate; border: 1px solid var(--xb-border); background-color: var(--xb-bg-2); background-image: radial-gradient(circle at 50% 28%, color-mix(in srgb, var(--stage-color) 36%, transparent), transparent 48%), linear-gradient(145deg, rgba(var(--xb-primary-rgb), .16), transparent 55%, rgba(var(--xb-accent-rgb), .1)); }
.visual-stage.has-media { background-color: #05060d; background-image: none; }
.stage-media, .stage-media.is-image::after { position: absolute; inset: 0; }
.stage-media { background: #05060d; opacity: 1; }
.stage-media.is-image::after { content: ''; background: linear-gradient(180deg, rgba(5,6,13,.3), rgba(5,6,13,.76) 75%, rgba(5,6,13,.95)); }
.stage-media img, .stage-media video { width: 100%; height: 100%; }
.stage-media img { object-fit: cover; filter: saturate(.86); }
.stage-media video { display: block; object-fit: contain; background: #05060d; }
.stage-shade { position: absolute; inset: 0; background: linear-gradient(125deg, rgba(var(--xb-primary-rgb), .13), transparent 50%, rgba(var(--xb-accent-rgb), .12)); pointer-events: none; }
.stage-content { position: relative; z-index: 1; height: 100%; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 46px 34px 72px; text-align: center; }
.stage-label { display: flex; align-items: center; gap: 7px; color: rgba(255,255,255,.72); font: 700 11px/1 ui-monospace, monospace; letter-spacing: 1.1px; }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--xb-success); box-shadow: 0 0 12px var(--xb-success); }
.record { position: relative; width: clamp(190px, 28vw, 280px); aspect-ratio: 1; margin: 28px 0 24px; border-radius: 50%; background: repeating-radial-gradient(circle, #111 0 2px, #1d1d25 3px 4px), #101016; box-shadow: 0 22px 55px rgba(0,0,0,.45), 0 0 0 8px rgba(255,255,255,.04), 0 0 48px color-mix(in srgb, var(--record-color) 34%, transparent); display: grid; place-items: center; }
.record.spinning { animation: spin-record 9s linear infinite; }
.record-groove { position: absolute; inset: 11%; border-radius: 50%; border: 1px solid rgba(255,255,255,.1); box-shadow: inset 0 0 0 12px rgba(0,0,0,.18), inset 0 0 0 25px rgba(255,255,255,.05); }
.record-art { width: 43%; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%; color: #fff; font-size: clamp(28px, 4vw, 44px); background: linear-gradient(145deg, var(--record-color), var(--xb-primary-2)); box-shadow: 0 0 30px color-mix(in srgb, var(--record-color) 40%, transparent); }
.record-hole { position: absolute; width: 11px; aspect-ratio: 1; border-radius: 50%; background: #08090f; border: 2px solid rgba(255,255,255,.24); }
.track-heading h1 { max-width: 600px; margin: 0; color: #fff; font-size: clamp(24px, 3vw, 38px); line-height: 1.15; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track-heading p { margin: 10px 0 0; color: rgba(255,255,255,.66); font-size: 14px; }
.track-heading p span { padding: 0 7px; color: var(--xb-primary); }
.hifi-strip { display: flex; align-items: center; flex-wrap: wrap; justify-content: center; gap: 9px; margin-top: 16px; color: rgba(255,255,255,.68); font-size: 11px; }
.hifi-badge { padding: 3px 9px; border: 1px solid rgba(255,255,255,.22); border-radius: 999px; font-weight: 700; letter-spacing: .4px; }
.hifi-strip.lossless .hifi-badge { color: var(--xb-success); border-color: rgba(var(--xb-success-rgb), .5); background: rgba(var(--xb-success-rgb), .12); }
.hifi-detail { font-family: ui-monospace, monospace; }
.hifi-eq { padding: 2px 6px; border-radius: 4px; background: rgba(var(--xb-primary-rgb), .18); color: var(--xb-primary); font-size: 9px; font-weight: 700; }
.stage-tools { position: absolute; z-index: 2; right: 18px; bottom: 18px; display: flex; align-items: center; gap: 7px; }
.visual-stage.has-video .stage-tools { top: 14px; right: 14px; bottom: auto; }
.visual-stage.has-video .media-btn { width: 36px; height: 36px; justify-content: center; padding: 0; background: #080b16; }
.visual-stage.has-video .media-btn span { display: none; }
.visual-stage.has-video .media-remove { background: #080b16; }
.media-btn, .media-remove { border: 1px solid rgba(255,255,255,.2); background: rgba(0,0,0,.28); color: rgba(255,255,255,.8); cursor: pointer; transition: .2s ease; }
.media-btn { display: inline-flex; align-items: center; gap: 7px; padding: 9px 13px; font-size: 12px; }
.media-btn:hover, .media-btn.active { color: #fff; border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .18); }
.media-remove { width: 34px; height: 34px; display: grid; place-items: center; }
.lyrics-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; contain: layout paint; border: 1px solid var(--xb-border); background: var(--xb-bg-2); padding: 26px 24px 18px; }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.panel-head h2 { margin: 8px 0 0; font-size: 25px; }
.lyrics-count { color: var(--xb-muted); font-size: 12px; padding-top: 8px; }
.lyric-search { display: flex; align-items: center; gap: 10px; margin-top: 18px; padding: 9px 10px; border: 1px solid var(--xb-border); border-radius: 10px; background: var(--xb-bg); color: var(--xb-muted); transition: .2s ease; }
.lyric-search:focus-within { border-color: var(--xb-primary); box-shadow: 0 0 0 1px rgba(var(--xb-primary-rgb), .12); }
.source-field { flex-shrink: 0; }
.lyric-source-select { width: 150px; }
.lyric-source-select :deep(.el-select__wrapper) { min-height: 40px; padding: 0 12px; border: 1px solid rgba(var(--xb-primary-rgb), .18); border-radius: 9px; background: var(--xb-bg-2); box-shadow: inset 0 1px 0 rgba(255,255,255,.03); }
.lyric-source-select :deep(.el-select__wrapper:hover) { border-color: rgba(var(--xb-primary-rgb), .42); }
.lyric-source-select :deep(.el-select__wrapper.is-focused) { border-color: var(--xb-primary); box-shadow: 0 0 0 1px rgba(var(--xb-primary-rgb), .16); }
.lyric-source-select :deep(.el-select__placeholder), .lyric-source-select :deep(.el-select__selected-item) { color: var(--xb-text); font-size: 12px; font-weight: 600; }
.lyric-source-select :deep(.el-select__caret), .lyric-source-select :deep(.el-select__suffix) { color: var(--xb-primary); }
.lyric-search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--xb-text); font-size: 12px; }
.lyric-search input::placeholder { color: var(--xb-muted); }
.lyric-search button { width: 30px; height: 30px; display: grid; place-items: center; border: 1px solid rgba(var(--xb-primary-rgb), .18); border-radius: 9px; background: rgba(var(--xb-primary-rgb), .08); color: var(--xb-primary); cursor: pointer; transition: .2s ease; }
.lyric-search button:hover:not(:disabled) { border-color: rgba(var(--xb-primary-rgb), .45); background: rgba(var(--xb-primary-rgb), .14); }
.lyric-search button:disabled { opacity: .45; cursor: wait; }
.lyric-results { display: flex; flex: 0 1 144px; flex-direction: column; gap: 2px; max-height: 144px; min-height: 0; overflow: auto; overscroll-behavior: contain; margin-top: 5px; padding: 4px; border: 1px solid var(--xb-border); background: var(--xb-bg); }
.lyric-results button { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; border: 0; background: transparent; color: var(--xb-text); padding: 8px 9px; text-align: left; cursor: pointer; font-size: 12px; }
.lyric-results button:hover { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); }
.lyric-results button.selected { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .12); box-shadow: inset 0 0 0 1px rgba(var(--xb-primary-rgb), .26); }
.lyric-results b { margin-right: 7px; color: var(--xb-primary); font: 10px ui-monospace, monospace; }
.lyric-result-main { display: flex; align-items: flex-start; min-width: 0; }
.lyric-result-main > span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.lyric-result-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.lyric-result-main em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--xb-muted); font-size: 10px; font-style: normal; }
.lyric-results small { color: var(--xb-muted); white-space: nowrap; }
.lyric-results button.selected small { color: var(--xb-primary); }
.lyric-selected { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 8px; padding: 9px 11px; border: 1px solid rgba(var(--xb-primary-rgb), .2); border-radius: 9px; background: color-mix(in srgb, var(--xb-primary) 7%, var(--xb-bg)); color: var(--xb-text); font-size: 12px; }
.lyric-selected small { color: var(--xb-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lyrics-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 22px 0 8px; }
.lyric-action { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--xb-border); background: var(--xb-bg); color: var(--xb-text); padding: 8px 11px; font-size: 12px; cursor: pointer; }
.lyric-action:hover:not(:disabled) { border-color: var(--xb-primary); color: var(--xb-primary); }
.lyric-action.primary { color: var(--xb-primary); border-color: rgba(var(--xb-primary-rgb), .45); background: rgba(var(--xb-primary-rgb), .08); }
.lyric-action:disabled { opacity: .6; cursor: wait; }
.music-link { margin-left: auto; color: var(--xb-muted); font-size: 12px; text-decoration: none; }
.music-link:hover { color: var(--xb-primary); }
.lyrics-tip { margin: 0 0 4px; color: var(--xb-muted); font-size: 11px; line-height: 1.5; }
.lyrics-message { color: var(--xb-success); margin: 5px 0 10px; font-size: 12px; }
.lyrics-message.error { color: var(--xb-warn); }
.lyrics-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 12px 3px; border: 1px solid var(--xb-border); background: var(--xb-bg); scrollbar-width: thin; }
.lyric-line { width: 100%; display: flex; align-items: baseline; gap: 12px; text-align: left; border: 0; border-left: 2px solid transparent; background: transparent; color: var(--xb-muted); cursor: pointer; padding: 11px 10px; font-size: 15px; line-height: 1.45; transition: .22s ease; }
.lyric-line:hover { color: var(--xb-text); background: rgba(var(--xb-primary-rgb), .05); }
.lyric-line.active { color: var(--xb-primary); border-left-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .09); font-weight: 700; transform: translateX(3px); }
.lyric-time { flex: 0 0 40px; color: color-mix(in srgb, var(--xb-muted) 70%, transparent); font: 10px ui-monospace, monospace; }
.lyric-line.active .lyric-time { color: var(--xb-primary); }
.lyrics-empty { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; gap: 10px; border: 1px solid var(--xb-border); background: var(--xb-bg); color: var(--xb-muted); }
.lyrics-empty .el-icon { font-size: 38px; color: var(--xb-primary); opacity: .65; }
.lyrics-empty strong { color: var(--xb-text); font-size: 15px; }
.lyrics-empty span { max-width: 250px; font-size: 12px; line-height: 1.6; }
.transport { display: flex; align-items: center; gap: 18px; margin-top: 18px; padding: 14px 20px; border-radius: 6px; }
.transport-controls { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.transport-mode { margin-right: 4px; }
.transport-skip { width: 34px; height: 34px; display: grid; place-items: center; border: 0; border-radius: 50%; background: transparent; color: var(--xb-muted); cursor: pointer; font-size: 18px; transition: .2s ease; }
.transport-skip:hover:not(:disabled) { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); }
.transport-skip:disabled { opacity: .3; cursor: default; }
.transport-play { width: 44px; height: 44px; display: grid; place-items: center; flex: 0 0 auto; border: 0; border-radius: 50%; background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); cursor: pointer; font-size: 19px; box-shadow: 0 5px 22px rgba(var(--xb-primary-rgb), .28); }
.transport-play:disabled { opacity: .5; cursor: default; }
.transport-main { flex: 1; min-width: 0; }
.transport-title { display: flex; justify-content: space-between; gap: 12px; color: var(--xb-text); font-size: 13px; font-weight: 700; }
.transport-title > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.transport-model { color: var(--xb-muted); font-size: 11px; font-weight: 400; white-space: nowrap; }
.audition-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border: 1px solid rgba(var(--xb-primary-rgb), .3);
  border-radius: 999px;
  color: var(--xb-primary);
  font: 9px/1.5 ui-monospace, monospace;
}
.audition-tag.queue {
  color: var(--xb-success);
  border-color: rgba(var(--xb-success-rgb), .35);
}
.seek { width: 100%; margin: 10px 0 3px; accent-color: var(--xb-primary); cursor: pointer; }
.transport-times { display: flex; justify-content: space-between; color: var(--xb-muted); font: 10px ui-monospace, monospace; }
.transport-side { flex: 0 0 auto; display: flex; align-items: center; gap: 12px; }
.hifi-inline { display: flex; align-items: center; gap: 6px; max-width: 210px; color: var(--xb-muted); font: 10px ui-monospace, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hifi-inline.lossless { color: var(--xb-success); }
.hifi-inline .hifi-dot { flex: 0 0 auto; width: 5px; height: 5px; }
.volume-control { display: flex; align-items: center; gap: 6px; color: var(--xb-muted); }
.volume-mute { width: 26px; height: 26px; display: grid; place-items: center; border: 0; border-radius: 6px; background: transparent; color: var(--xb-muted); cursor: pointer; }
.volume-mute:hover { color: var(--xb-primary); }
.volume-control input { width: 76px; accent-color: var(--xb-primary); }
.queue-btn { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 9px; border: 1px solid var(--xb-border); border-radius: 8px; background: transparent; color: var(--xb-muted); font: 11px ui-monospace, monospace; cursor: pointer; }
.queue-btn:hover { color: var(--xb-primary); border-color: rgba(var(--xb-primary-rgb), .45); }
.player-loading, .not-found { min-height: 55vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
.loading-icon { font-size: 28px; color: var(--xb-primary); animation: spin-record 1s linear infinite; }
.not-found { border: 1px solid var(--xb-border); padding: 40px; text-align: center; }
.not-found > .el-icon { color: var(--xb-primary); font-size: 45px; }
.not-found h2 { margin: 0; }
.not-found p { color: var(--xb-muted); margin: 0 0 8px; }
.not-found-actions { display: flex; gap: 10px; }
.cta-btn { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important; border: none !important; color: var(--xb-on-primary) !important; font-weight: 700; }
.spin { animation: spin-record 1s linear infinite; }
@keyframes spin-record { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .record.spinning, .spin, .loading-icon { animation: none; } }
@media (max-width: 1100px) {
  .hifi-inline { display: none; }
  .head-actions .text-btn:not(.hifi-entry) { padding: 8px 6px; }
}
@media (max-width: 900px) {
  .player-page { padding: 14px 16px 30px; }
  .player-layout { grid-template-columns: 1fr; height: auto; min-height: 0; }
  .visual-stage { height: clamp(470px, 68dvh, 580px); min-height: 470px; }
  .stage-content { height: 100%; min-height: 0; padding-top: 40px; }
  .lyrics-panel { height: clamp(540px, calc(100dvh - 96px), 660px); min-height: 540px; }
  .transport { display: grid; grid-template-columns: auto 1fr; gap: 10px; }
  .transport-main { grid-column: 1 / -1; order: -1; }
  .transport-side { justify-self: end; }
}
@media (max-width: 560px) {
  .head-title, .head-actions .text-btn:not(.hifi-entry):not(.queue-entry) { display: none; }
  .queue-entry { font-size: 0; padding: 8px; gap: 2px; }
  .queue-entry .el-icon { font-size: 16px; }
  .queue-entry .queue-count { font-size: 9px; }
  .head-actions { gap: 3px; }
  .track-heading h1 { max-width: 84vw; font-size: 25px; }
  .transport { gap: 10px; padding: 12px; }
  .transport-side { display: flex; grid-column: 1 / -1; justify-content: center; }
  .hifi-inline, .queue-btn { display: none; }
  .volume-control input { width: 160px; }
  .transport-controls { grid-column: 1 / -1; justify-content: center; }
  .media-btn span { display: none; }
}
</style>

<style>
.hifi-popover.el-popover {
  padding: 14px 16px;
  border: 1px solid var(--xb-border);
  border-radius: 12px;
  background: var(--xb-bg-2);
  box-shadow: 0 18px 48px rgba(var(--xb-bg-rgb), 0.5);
  max-width: calc(100vw - 24px);
}
</style>
