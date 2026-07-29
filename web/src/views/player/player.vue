<template>
  <div class="player-page">
    <div v-if="loading" class="player-loading">
      <el-icon class="loading-icon"><Loading /></el-icon>
      <span>正在准备播放页面…</span>
    </div>

    <template v-else-if="work">
      <header class="player-head">
        <button class="icon-btn" title="返回作品库" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="head-context">
          <span class="head-kicker">NOW PLAYING</span>
          <span class="head-title">作品播放</span>
        </div>
        <div class="head-actions">
          <button class="text-btn" @click="router.push('/works')">作品库</button>
          <button class="icon-btn" title="下载作品" @click="downloadWork">
            <el-icon><Download /></el-icon>
          </button>
        </div>
      </header>

      <main class="player-layout">
        <section class="visual-stage" :class="{ 'has-media': !!mediaData, 'has-video': hasVideo }" :style="stageStyle">
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
            <div class="stage-label"><span class="live-dot"></span> AI COVER · {{ work.format || 'AUDIO' }}</div>
            <div class="record" :class="{ spinning: isPlaying }" :style="{ '--record-color': coverColor }">
              <div class="record-groove"></div>
              <div class="record-art"><el-icon><Headset /></el-icon></div>
              <div class="record-hole"></div>
            </div>
            <div class="track-heading">
              <h1 :title="work.title">{{ work.title }}</h1>
              <p>{{ work.model }} <span>·</span> {{ work.duration }}</p>
            </div>
          </div>
          <div class="stage-tools">
            <button class="media-btn" :class="{ active: !!mediaData }" title="为这首歌导入画面 MV" @click="importVisual">
              <el-icon><VideoCamera /></el-icon>
              <span>{{ mediaData ? '更换 MV' : '导入画面 MV' }}</span>
            </button>
            <button v-if="mediaData" class="media-remove" title="移除 MV 画面" @click="removeVisual">
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </section>

        <section class="lyrics-panel">
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
              {{ lyricsLoading ? '获取中' : (selectedLyricSong ? '获取选中歌曲歌词' : (needsLyricSelection ? '请先选择结果' : '按作品名获取')) }}
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

      <section class="transport glass">
        <audio
          ref="audioEl"
          :src="audioSrc"
          @timeupdate="onTimeUpdate"
          @loadedmetadata="onMetadata"
          @play="onAudioPlay"
          @pause="onAudioPause"
          @seeked="syncVideoToAudio(true)"
          @ended="onEnded"
        ></audio>
        <button class="transport-play" :title="isPlaying ? '暂停' : '播放'" @click="togglePlayback">
          <el-icon v-if="isPlaying"><VideoPause /></el-icon>
          <el-icon v-else><VideoPlay /></el-icon>
        </button>
        <div class="transport-main">
          <div class="transport-title"><span>{{ work.title }}</span><span class="transport-model">{{ work.model }}</span></div>
          <input v-model.number="currentTime" class="seek" type="range" min="0" :max="duration || 0.01" step="0.01" @input="onSeek" />
          <div class="transport-times"><span>{{ formatTime(currentTime) }}</span><span>{{ formatTime(duration) }}</span></div>
        </div>
        <div class="volume-control">
          <el-icon><Headset /></el-icon>
          <input v-model.number="volume" type="range" min="0" max="1" step="0.01" title="音量" @input="onVolume" />
        </div>
      </section>
    </template>

    <div v-else class="not-found glass">
      <el-icon><Headset /></el-icon>
      <h2>找不到这首作品</h2>
      <p>它可能已被删除，或仍在生成中。</p>
      <el-button class="cta-btn" round @click="router.push('/works')">返回作品库</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ChatLineSquare,
  Close,
  Download,
  Headset,
  Loading,
  MagicStick,
  Upload,
  Search,
  VideoCamera,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, pickColor, type LyricLine, type MusicSearchItem, type MusicSource, type WorkDTO } from '@/api'
import { useWorksStore } from '@/stores/works'

defineOptions({ name: 'PlayerPage' })

const route = useRoute()
const router = useRouter()
const worksStore = useWorksStore()
const work = ref<WorkDTO | null>(null)
const loading = ref(true)
const audioEl = ref<HTMLAudioElement | null>(null)
const mvVideoEl = ref<HTMLVideoElement | null>(null)
const audioSrc = ref('')
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(0.9)
const lyrics = ref<LyricLine[]>([])
const activeLyric = ref(-1)
const lyricsLoading = ref(false)
const lyricSearching = ref(false)
const lyricQuery = ref('')
const lyricSearchResults = ref<MusicSearchItem[]>([])
const lyricSearchKeyword = ref('')
const selectedLyricSong = ref<MusicSearchItem | null>(null)
const needsLyricSelection = computed(() => lyricSearchResults.value.length > 0 && !selectedLyricSong.value)
const lyricSources = ref<MusicSource[]>([{ id: 'wy', name: '网易云音乐', cookie: false }])
const lyricSource = ref('wy')
const lyricsMessage = ref('')
const lyricsError = ref(false)
const lyricsEl = ref<HTMLElement | null>(null)
const mediaData = ref('')
const mediaPath = ref('')
const mediaKind = ref<'image' | 'video'>('image')
const mediaName = ref('')
const playerStoragePrefix = 'xb-player-'

const workId = computed(() => String(route.query.work || route.params.id || ''))
const coverColor = computed(() => pickColor(work.value?.id || 'player'))
const hasVideo = computed(() => mediaKind.value === 'video' && !!mediaData.value)
const stageStyle = computed(() => ({ '--stage-color': coverColor.value }))

function storageKey(suffix: string) {
  return `${playerStoragePrefix}${suffix}-${workId.value}`
}

function formatTime(value: number) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  const mins = Math.floor(seconds / 60)
  return `${mins}:${String(seconds % 60).padStart(2, '0')}`
}

function parseLyrics(text: string): LyricLine[] {
  const result: LyricLine[] = []
  const pattern = /\[(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?\]/g
  for (const raw of String(text || '').split(/\r?\n/)) {
    const tags = [...raw.matchAll(pattern)]
    const textValue = raw.replace(pattern, '').trim()
    if (!textValue || !tags.length) continue
    for (const tag of tags) {
      const fraction = String(tag[3] || '').padEnd(3, '0').slice(0, 3)
      result.push({ time: Number(tag[1]) * 60 + Number(tag[2]) + Number(fraction) / 1000, text: textValue })
    }
  }
  return result.sort((a, b) => a.time - b.time)
}

function saveLyrics(lines: LyricLine[], source: string) {
  lyrics.value = lines
  activeLyric.value = -1
  lyricsMessage.value = source
  lyricsError.value = false
  try { localStorage.setItem(storageKey('lyrics'), JSON.stringify(lines)) } catch { /* storage may be disabled */ }
  void nextTick(onTimeUpdate)
}

function loadSavedLyrics() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey('lyrics')) || 'null')
    if (Array.isArray(saved)) lyrics.value = saved.filter((x) => Number.isFinite(x?.time) && x?.text)
  } catch { /* ignore invalid local data */ }
}

async function fetchLyrics() {
  if (!work.value) return
  if (needsLyricSelection.value) {
    lyricsError.value = true
    lyricsMessage.value = '请先在搜索结果中选择第几个版本，再获取歌词。'
    return
  }
  lyricsLoading.value = true
  lyricsMessage.value = ''
  lyricsError.value = false
  try {
    const item = selectedLyricSong.value
    const query = (item ? lyricSearchKeyword.value : lyricQuery.value.trim()) || work.value.title
    const songId = lyricSource.value === 'kuwo' ? undefined : item?.rid || undefined
    const res = await api.getMusicLyrics(query, item?.n || 1, lyricSource.value, songId)
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
  return selectedLyricSong.value?.n === item.n && selectedLyricSong.value?.rid === item.rid && selectedLyricSong.value?.name === item.name
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
  try {
    localStorage.setItem(storageKey('visual'), JSON.stringify({ path: mediaPath.value, kind: mediaKind.value, name: mediaName.value }))
  } catch { /* ignore storage errors */ }
  await nextTick()
  syncVideoToAudio(true)
  ElMessage.success(`已设置画面：${mediaName.value}`)
}

function loadSavedVisual() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey('visual')) || 'null')
    if (!saved?.path) return
    mediaPath.value = String(saved.path)
    mediaKind.value = saved.kind === 'video' ? 'video' : 'image'
    mediaName.value = String(saved.name || '自定义 MV')
    void api.getThemeMediaData(mediaPath.value).then(async (data) => {
      mediaData.value = data || ''
      await nextTick()
      syncVideoToAudio(true)
    })
  } catch { /* ignore invalid local data */ }
}

function removeVisual() {
  mvVideoEl.value?.pause()
  mediaData.value = ''
  mediaPath.value = ''
  try { localStorage.removeItem(storageKey('visual')) } catch { /* ignore storage errors */ }
}

function syncVideoToAudio(forceSeek = false) {
  const audio = audioEl.value
  const video = mvVideoEl.value
  if (!audio || !video || !hasVideo.value || video.readyState < HTMLMediaElement.HAVE_METADATA) return

  const maximumTime = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.05) : audio.currentTime
  const targetTime = Math.min(Math.max(0, audio.currentTime), maximumTime)
  if (forceSeek || Math.abs(video.currentTime - targetTime) > 0.3) {
    video.currentTime = targetTime
  }

  if (audio.paused || audio.ended) {
    video.pause()
  } else if (video.paused && targetTime < maximumTime) {
    void video.play().catch(() => { /* the next audio event will retry */ })
  }
}

function onAudioPlay() {
  isPlaying.value = true
  syncVideoToAudio(true)
}

function onAudioPause() {
  isPlaying.value = false
  mvVideoEl.value?.pause()
}

async function togglePlayback() {
  const el = audioEl.value
  if (!el || !audioSrc.value) return
  if (el.paused) {
    try { await el.play() } catch { ElMessage.error('音频播放失败') }
  } else {
    el.pause()
  }
}

function scrollActiveLyricIntoView() {
  const container = lyricsEl.value
  const target = container?.querySelector('.lyric-line.active') as HTMLElement | null
  if (!container || !target) return

  const containerRect = container.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const relativeTop = targetRect.top - containerRect.top - container.clientTop
  const centeredTop = container.scrollTop + relativeTop - (container.clientHeight - targetRect.height) / 2
  const maximumTop = Math.max(0, container.scrollHeight - container.clientHeight)
  container.scrollTo({
    top: Math.min(maximumTop, Math.max(0, centeredTop)),
    behavior: 'smooth',
  })
}

function onTimeUpdate() {
  const el = audioEl.value
  if (!el) return
  currentTime.value = el.currentTime
  syncVideoToAudio()
  let next = -1
  for (let i = 0; i < lyrics.value.length; i += 1) {
    const line = lyrics.value[i]
    if (line && line.time <= currentTime.value + 0.08) next = i
    else break
  }
  if (next !== activeLyric.value) {
    activeLyric.value = next
    void nextTick(scrollActiveLyricIntoView)
  }
}

function onMetadata() {
  if (audioEl.value) duration.value = Number.isFinite(audioEl.value.duration) ? audioEl.value.duration : 0
  syncVideoToAudio(true)
}

function onEnded() {
  isPlaying.value = false
  activeLyric.value = -1
  mvVideoEl.value?.pause()
}

function onSeek() {
  if (audioEl.value) audioEl.value.currentTime = currentTime.value
  onTimeUpdate()
  syncVideoToAudio(true)
}

function onVolume() {
  if (audioEl.value) audioEl.value.volume = volume.value
}

function seekTo(time: number) {
  currentTime.value = time
  onSeek()
  if (audioEl.value?.paused) void togglePlayback()
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/works')
}

async function downloadWork() {
  if (!work.value) return
  const dest = await api.exportWork(work.value.id)
  if (dest) ElMessage.success(`已导出到：${dest}`)
}

onMounted(async () => {
  try {
    const [sourceList, currentSource] = await Promise.all([api.listMusicSources(), api.getMusicSource()])
    if (sourceList.length) lyricSources.value = sourceList
    if (sourceList.some((source) => source.id === currentSource)) lyricSource.value = currentSource
    await worksStore.ensureLoaded()
    work.value = worksStore.works.find((item) => item.id === workId.value) || await api.getWork(workId.value)
    if (!work.value || work.value.status !== 'done') return
    lyricQuery.value = work.value.title
    audioSrc.value = await api.getWorkAudio(work.value.id)
    await nextTick()
    if (audioEl.value) {
      audioEl.value.volume = volume.value
      audioEl.value.load()
    }
    loadSavedLyrics()
    loadSavedVisual()
  } finally {
    loading.value = false
  }
})

watch(workId, () => {
  if (workId.value) window.location.reload()
})
</script>

<style scoped>
.player-page { min-height: calc(100vh - 64px); max-width: 1440px; margin: 0 auto; padding: 20px 28px 42px; color: var(--xb-text); }
.player-head { display: flex; align-items: center; gap: 14px; min-height: 46px; margin-bottom: 18px; }
.head-context { display: flex; align-items: baseline; gap: 10px; }
.head-kicker, .eyebrow { color: var(--xb-primary); font: 700 11px/1 ui-monospace, monospace; letter-spacing: 1.6px; }
.head-title { color: var(--xb-muted); font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.icon-btn { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--xb-border); border-radius: 50%; background: rgba(var(--xb-fill-rgb), .04); color: var(--xb-text); cursor: pointer; transition: .2s ease; }
.icon-btn:hover { color: var(--xb-primary); border-color: var(--xb-primary); transform: translateY(-1px); }
.text-btn { border: 0; background: transparent; color: var(--xb-muted); cursor: pointer; padding: 8px 10px; }
.text-btn:hover { color: var(--xb-primary); }
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
.stage-content { position: relative; z-index: 1; height: 100%; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 54px 34px 80px; text-align: center; }
.stage-label { display: flex; align-items: center; gap: 7px; color: rgba(255,255,255,.72); font: 700 11px/1 ui-monospace, monospace; letter-spacing: 1.1px; }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--xb-success); box-shadow: 0 0 12px var(--xb-success); }
.record { position: relative; width: clamp(205px, 31vw, 310px); aspect-ratio: 1; margin: 36px 0 28px; border-radius: 50%; background: repeating-radial-gradient(circle, #111 0 2px, #1d1d25 3px 4px), #101016; box-shadow: 0 22px 55px rgba(0,0,0,.45), 0 0 0 8px rgba(255,255,255,.04), 0 0 48px color-mix(in srgb, var(--record-color) 34%, transparent); display: grid; place-items: center; }
.record.spinning { animation: spin-record 9s linear infinite; }
.record-groove { position: absolute; inset: 11%; border-radius: 50%; border: 1px solid rgba(255,255,255,.1); box-shadow: inset 0 0 0 12px rgba(0,0,0,.18), inset 0 0 0 25px rgba(255,255,255,.05); }
.record-art { width: 43%; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%; color: #fff; font-size: clamp(28px, 4vw, 44px); background: linear-gradient(145deg, var(--record-color), var(--xb-primary-2)); box-shadow: 0 0 30px color-mix(in srgb, var(--record-color) 40%, transparent); }
.record-hole { position: absolute; width: 11px; aspect-ratio: 1; border-radius: 50%; background: #08090f; border: 2px solid rgba(255,255,255,.24); }
.track-heading h1 { max-width: 600px; margin: 0; color: #fff; font-size: clamp(24px, 3vw, 38px); line-height: 1.15; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track-heading p { margin: 10px 0 0; color: rgba(255,255,255,.66); font-size: 14px; }
.track-heading p span { padding: 0 7px; color: var(--xb-primary); }
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
.lyric-search {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  padding: 9px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 10px;
  background: var(--xb-bg);
  color: var(--xb-muted);
  transition: .2s ease;
}
.lyric-search:focus-within {
  border-color: var(--xb-primary);
  box-shadow: 0 0 0 1px rgba(var(--xb-primary-rgb), .12);
}
.source-field { flex-shrink: 0; }
.lyric-source-select { width: 150px; }
.lyric-source-select :deep(.el-select__wrapper) {
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid rgba(var(--xb-primary-rgb), .18);
  border-radius: 9px;
  background: var(--xb-bg-2);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.lyric-source-select :deep(.el-select__wrapper:hover) { border-color: rgba(var(--xb-primary-rgb), .42); }
.lyric-source-select :deep(.el-select__wrapper.is-focused) {
  border-color: var(--xb-primary);
  box-shadow: 0 0 0 1px rgba(var(--xb-primary-rgb), .16);
}
.lyric-source-select :deep(.el-select__placeholder),
.lyric-source-select :deep(.el-select__selected-item) {
  color: var(--xb-text);
  font-size: 12px;
  font-weight: 600;
}
.lyric-source-select :deep(.el-select__caret) { color: var(--xb-primary); }
.lyric-source-select :deep(.el-select__suffix) { color: var(--xb-primary); }
.lyric-search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--xb-text); font-size: 12px; }
.lyric-search input::placeholder { color: var(--xb-muted); }
.lyric-search button {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(var(--xb-primary-rgb), .18);
  border-radius: 9px;
  background: rgba(var(--xb-primary-rgb), .08);
  color: var(--xb-primary);
  cursor: pointer;
  transition: .2s ease;
}
.lyric-search button:hover:not(:disabled) {
  border-color: rgba(var(--xb-primary-rgb), .45);
  background: rgba(var(--xb-primary-rgb), .14);
}
.lyric-search button:disabled { opacity: .45; cursor: wait; }
.lyric-results { display: flex; flex: 0 1 144px; flex-direction: column; gap: 2px; max-height: 144px; min-height: 0; overflow: auto; overscroll-behavior: contain; margin-top: 5px; padding: 4px; border: 1px solid var(--xb-border); background: var(--xb-bg); }
.lyric-results button { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; border: 0; background: transparent; color: var(--xb-text); padding: 8px 9px; text-align: left; cursor: pointer; font-size: 12px; }
.lyric-results button:hover { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); }
.lyric-results button.selected {
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), .12);
  box-shadow: inset 0 0 0 1px rgba(var(--xb-primary-rgb), .26);
}
.lyric-results b { margin-right: 7px; color: var(--xb-primary); font: 10px ui-monospace, monospace; }
.lyric-result-main { display: flex; align-items: flex-start; min-width: 0; }
.lyric-result-main > span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.lyric-result-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.lyric-result-main em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--xb-muted); font-size: 10px; font-style: normal; }
.lyric-results small { color: var(--xb-muted); white-space: nowrap; }
.lyric-results button.selected small { color: var(--xb-primary); }
.lyric-selected {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  padding: 9px 11px;
  border: 1px solid rgba(var(--xb-primary-rgb), .2);
  border-radius: 9px;
  background: color-mix(in srgb, var(--xb-primary) 7%, var(--xb-bg));
  color: var(--xb-text);
  font-size: 12px;
}
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
.transport { display: flex; align-items: center; gap: 16px; margin-top: 18px; padding: 15px 20px; border-radius: 6px; }
.transport-play { width: 44px; height: 44px; display: grid; place-items: center; flex: 0 0 auto; border: 0; border-radius: 50%; background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); cursor: pointer; font-size: 19px; box-shadow: 0 5px 22px rgba(var(--xb-primary-rgb), .28); }
.transport-main { flex: 1; min-width: 0; }
.transport-title { display: flex; justify-content: space-between; gap: 12px; color: var(--xb-text); font-size: 13px; font-weight: 700; }
.transport-model { color: var(--xb-muted); font-size: 11px; font-weight: 400; }
.seek { width: 100%; margin: 10px 0 3px; accent-color: var(--xb-primary); cursor: pointer; }
.transport-times { display: flex; justify-content: space-between; color: var(--xb-muted); font: 10px ui-monospace, monospace; }
.volume-control { display: flex; align-items: center; gap: 8px; color: var(--xb-muted); }
.volume-control input { width: 82px; accent-color: var(--xb-primary); }
.player-loading, .not-found { min-height: 55vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
.loading-icon { font-size: 28px; color: var(--xb-primary); animation: spin-record 1s linear infinite; }
.not-found { border: 1px solid var(--xb-border); padding: 40px; text-align: center; }
.not-found > .el-icon { color: var(--xb-primary); font-size: 45px; }
.not-found h2 { margin: 0; }
.not-found p { color: var(--xb-muted); margin: 0 0 8px; }
.cta-btn { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important; border: none !important; color: var(--xb-on-primary) !important; font-weight: 700; }
.spin { animation: spin-record 1s linear infinite; }
@keyframes spin-record { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .record.spinning, .spin, .loading-icon { animation: none; } }
@media (max-width: 900px) { .player-page { padding: 14px 16px 30px; } .player-layout { grid-template-columns: 1fr; height: auto; min-height: 0; } .visual-stage { height: clamp(470px, 68dvh, 580px); min-height: 470px; } .stage-content { height: 100%; min-height: 0; padding-top: 40px; } .lyrics-panel { height: clamp(540px, calc(100dvh - 96px), 660px); min-height: 540px; } }
@media (max-width: 560px) { .head-title, .head-actions .text-btn { display: none; } .head-actions { gap: 3px; } .track-heading h1 { max-width: 84vw; font-size: 25px; } .transport { gap: 10px; padding: 12px; } .volume-control { display: none; } .media-btn span { display: none; } }
</style>
