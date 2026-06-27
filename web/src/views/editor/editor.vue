<template>
  <div class="editor-page">
    <audio
      ref="audioEl"
      hidden
      @ended="onAudioEnded"
      @pause="onAudioPause"
      @timeupdate="onAudioTimeUpdate"
    />

    <div class="editor-head">
      <div>
        <p class="eyebrow">// Audio Editor Lite</p>
        <h1>音频编辑工作台</h1>
      </div>
      <div class="head-actions">
        <el-button round class="ghost-btn" @click="importAudio">
          <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
        </el-button>
        <el-button :disabled="!project" round class="ghost-btn" @click="undo">
          <el-icon class="el-icon--left"><RefreshLeft /></el-icon>撤销
        </el-button>
        <el-button :disabled="!project" round class="ghost-btn" @click="redo">
          <el-icon class="el-icon--left"><RefreshRight /></el-icon>重做
        </el-button>
        <el-button :disabled="!project || (previewing && !playing)" :loading="previewing" round class="cta-btn" @click="playMix">
          <el-icon class="el-icon--left"><component :is="playing ? VideoPause : VideoPlay" /></el-icon>
          {{ playing ? '暂停' : '播放' }}
        </el-button>
        <el-dropdown :disabled="!project" trigger="click" @command="(cmd: string | number | object) => exportMix(String(cmd))">
          <el-button :disabled="!project" round class="ghost-btn">
            <el-icon class="el-icon--left"><Download /></el-icon>导出
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="wav">WAV</el-dropdown-item>
              <el-dropdown-item command="mp3">MP3</el-dropdown-item>
              <el-dropdown-item command="flac">FLAC</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button round class="ghost-btn" @click="exitEditor">
          <el-icon class="el-icon--left"><Close /></el-icon>退出
        </el-button>
        <el-button :disabled="!project" round class="danger-btn" @click="discardProject">
          <el-icon class="el-icon--left"><Delete /></el-icon>放弃工程
        </el-button>
      </div>
    </div>

    <div v-if="project" class="editor-shell">
      <aside class="inspector glass">
        <div class="project-block">
          <label>工程</label>
          <input v-model="project.title" class="title-input" @change="saveProject" />
          <div class="project-meta">
            <span>{{ fmtTime(project.duration) }}</span>
            <span>{{ project.tracks.length }} 轨</span>
            <span>{{ project.sample_rate }} Hz</span>
          </div>
        </div>

        <div class="tool-block">
          <div class="tool-row">
            <span>吸附</span>
            <el-switch v-model="snapEnabled" />
          </div>
          <div class="tool-row">
            <span>缩放</span>
            <el-slider v-model="zoom" :min="24" :max="180" :step="4" />
          </div>
          <div class="tool-row">
            <span>切口淡化</span>
            <el-slider v-model="cutCrossfade" :min="0.02" :max="0.8" :step="0.01" />
          </div>
        </div>

        <div v-if="selectedClip && selectedTrack" class="clip-block">
          <div class="clip-title">
            <span>{{ selectedClip.name || '片段' }}</span>
            <button :class="{ active: selectedClip.locked }" title="锁定片段" @click="toggleClipLock">
              <el-icon><Lock /></el-icon>
            </button>
          </div>
          <div class="field-grid">
            <label>开始</label>
            <input type="number" step="0.01" :value="round(selectedClip.start)" @change="setClipNumber('start', $event)" />
            <label>结束</label>
            <input type="number" step="0.01" :value="round(selectedClip.end)" @change="setClipNumber('end', $event)" />
            <label>偏移</label>
            <input type="number" step="0.01" :value="round(selectedClip.offset)" @change="setClipNumber('offset', $event)" />
          </div>
          <div class="channel-row">
            <span>声道</span>
            <div class="channel-segment">
              <button
                v-for="option in channelOptions"
                :key="option.value"
                :class="{ active: clipChannel(selectedClip) === option.value }"
                :title="option.title"
                @click="setClipChannel(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
          </div>
          <div class="slider-row">
            <span>音量</span>
            <el-slider v-model="selectedClip.volume" :min="0" :max="2" :step="0.01" @change="saveProject" />
          </div>
          <div class="slider-row">
            <span>淡入</span>
            <el-slider v-model="selectedClip.fade_in" :min="0" :max="2" :step="0.01" @change="saveProject" />
          </div>
          <div class="slider-row">
            <span>淡出</span>
            <el-slider v-model="selectedClip.fade_out" :min="0" :max="2" :step="0.01" @change="saveProject" />
          </div>
          <div class="clip-actions">
            <button title="静音片段" :class="{ active: selectedClip.mute }" @click="toggleClipMute">
              <el-icon><Mute /></el-icon>
            </button>
            <button title="按播放头剪切" :disabled="!canSplitAtPlayhead" @click="splitAtPlayhead">
              <el-icon><Scissor /></el-icon>
            </button>
            <button title="预览片段" @click="playSelectedClip">
              <el-icon><Aim /></el-icon>
            </button>
            <button title="删除片段" class="danger" @click="deleteSelectedClip">
              <el-icon><Delete /></el-icon>
            </button>
          </div>

          <div class="rerun-box">
            <label>局部重推理</label>
            <select v-model="rerunModelId">
              <option value="">选择模型</option>
              <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
            <span v-if="rerunGuardText" class="rerun-hint">{{ rerunGuardText }}</span>
            <el-button
              :disabled="!rerunModelId || rerunning || !canRerunSelectedClip"
              :loading="rerunning"
              round
              class="cta-btn mini"
              @click="rerunClip"
            >
              <el-icon class="el-icon--left"><Cpu /></el-icon>替换片段
            </el-button>
          </div>
        </div>

        <div v-else class="empty-side">
          <el-icon><Mouse /></el-icon>
          <span>选择一个片段</span>
        </div>
      </aside>

      <section class="timeline glass">
        <div class="timeline-top">
          <div class="timeline-main-tools">
            <div class="transport">
              <button title="回到开始" @click="seekStart"><el-icon><DArrowLeft /></el-icon></button>
              <button title="播放混音" :disabled="previewing && !playing" @click="playMix"><el-icon><component :is="playing ? VideoPause : VideoPlay" /></el-icon></button>
              <span>{{ fmtTime(playhead) }}</span>
            </div>
            <div class="edit-tools">
              <button
                class="split-btn"
                :disabled="!canSplitAtPlayhead"
                title="按播放头剪切并添加交叉淡化"
                @click="splitAtPlayhead"
              >
                <el-icon><Scissor /></el-icon>
                <span>剪切</span>
              </button>
              <span class="xf-badge">{{ cutCrossfade.toFixed(2) }}s</span>
            </div>
          </div>
          <div class="render-path" :title="renderedPath">{{ renderedPath || '未导出' }}</div>
        </div>

        <div ref="scrollEl" class="timeline-scroll" @pointerdown="onTimelinePointer">
          <div class="ruler" :style="{ width: timelineWidth + 'px' }">
            <span
              v-for="tick in ticks"
              :key="tick"
              class="tick"
              :style="{ left: tick * zoom + 'px' }"
            >
              {{ fmtTick(tick) }}
            </span>
            <i class="playhead" :style="{ left: playhead * zoom + 'px' }"></i>
          </div>

          <div class="tracks" :style="{ width: timelineWidth + 'px' }">
            <div v-for="track in project.tracks" :key="track.id" class="track-row">
              <div class="track-label" @pointerdown.stop>
                <button :title="track.locked ? '解除轨道锁定' : '锁定轨道'" :class="{ active: track.locked }" @click="toggleTrackLock(track)">
                  <el-icon><Lock /></el-icon>
                </button>
                <button :title="track.mute ? '取消静音' : '静音轨道'" :class="{ active: track.mute }" @click="toggleTrackMute(track)">
                  <el-icon><Mute /></el-icon>
                </button>
                <el-tooltip :content="track.name" placement="right" :show-after="250">
                  <span class="track-name" :title="track.name">{{ track.name }}</span>
                </el-tooltip>
              </div>

              <div class="track-lane">
                <div
                  v-for="clip in track.clips"
                  :key="clip.id"
                  class="clip"
                  :class="[
                    track.type,
                    {
                      selected: selected?.clipId === clip.id,
                      muted: clip.mute || track.mute,
                      locked: clip.locked || track.locked,
                    },
                  ]"
                  :style="clipStyle(clip)"
                  @pointerdown.stop="startDrag($event, track, clip, 'move')"
                  @click.stop="selectClip(track.id, clip.id)"
                >
                  <button class="handle left" @pointerdown.stop="startDrag($event, track, clip, 'start')"></button>
                  <div class="wave">
                    <i
                      v-for="(p, i) in waveformPeaks(clip)"
                      :key="i"
                      :style="waveBarStyle(p)"
                    ></i>
                  </div>
                  <span v-if="clip.fade_in > 0" class="fade-guide fade-in" :style="fadeStyle(clip.fade_in, clip)"></span>
                  <span v-if="clip.fade_out > 0" class="fade-guide fade-out" :style="fadeStyle(clip.fade_out, clip)"></span>
                  <span v-if="clipChannel(clip) !== 'stereo'" class="channel-pill">{{ channelLabel(clipChannel(clip)) }}</span>
                  <span class="clip-name">{{ clip.name }}</span>
                  <button class="handle right" @pointerdown.stop="startDrag($event, track, clip, 'end')"></button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div v-else class="empty-state glass">
      <el-icon><Scissor /></el-icon>
      <p>暂无编辑工程</p>
      <el-button round class="cta-btn" @click="importAudio">
        <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  Aim,
  Close,
  Cpu,
  DArrowLeft,
  Delete,
  Download,
  FolderAdd,
  Lock,
  Mouse,
  Mute,
  RefreshLeft,
  RefreshRight,
  Scissor,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useModelsStore } from '@/stores/models'
import type { EditorClip, EditorClipChannel, EditorProject, EditorTrack } from '@/api'

defineOptions({ name: 'AudioEditorPage' })

type DragMode = 'move' | 'start' | 'end'
type PlaybackMode = 'none' | 'mix' | 'clip'
interface Selection { trackId: string; clipId: string }
interface DragState {
  mode: DragMode
  startX: number
  startY: number
  trackId: string
  clipId: string
  original: EditorClip
  originalTrackIndex: number
}

const router = useRouter()
const route = useRoute()
const modelsStore = useModelsStore()
const { models } = storeToRefs(modelsStore)

const project = ref<EditorProject | null>(null)
const selected = ref<Selection | null>(null)
const waveformMap = ref<Record<string, number[]>>({})
const zoom = ref(64)
const snapEnabled = ref(true)
const cutCrossfade = ref(0.08)
const playhead = ref(0)
const playing = ref(false)
const previewing = ref(false)
const rerunning = ref(false)
const playbackMode = ref<PlaybackMode>('none')
const timelineSeeking = ref(false)
const rerunModelId = ref('')
const renderedPath = ref('')
const audioEl = ref<HTMLAudioElement | null>(null)
const scrollEl = ref<HTMLElement | null>(null)
const history = ref<EditorProject[]>([])
const future = ref<EditorProject[]>([])
const drag = ref<DragState | null>(null)
let clipStopTimer: ReturnType<typeof setTimeout> | null = null
let lastPlayToggleAt = 0
let mixPreviewRequestId = 0
let waveformZoomTimer: ReturnType<typeof setTimeout> | null = null
const waveformLoading = new Set<string>()

const fallbackPeaks = Array.from({ length: 56 }, (_, i) => 0.18 + Math.abs(Math.sin(i * 0.33)) * 0.5)
const MIN_RERUN_CLIP_SECONDS = 1
const PLAY_TOGGLE_DEBOUNCE_MS = 350
const channelOptions: { value: EditorClipChannel; label: string; title: string }[] = [
  { value: 'stereo', label: '双', title: '双声道' },
  { value: 'left', label: 'L', title: '左声道' },
  { value: 'right', label: 'R', title: '右声道' },
]

const selectedTrack = computed(() => {
  if (!project.value || !selected.value) return null
  return project.value.tracks.find((t) => t.id === selected.value?.trackId) || null
})
const selectedClip = computed(() => {
  const track = selectedTrack.value
  if (!track || !selected.value) return null
  return track.clips.find((c) => c.id === selected.value?.clipId) || null
})
const selectedClipDuration = computed(() => {
  const clip = selectedClip.value
  return clip ? Math.max(0, clip.end - clip.start) : 0
})
const canRerunSelectedClip = computed(() => {
  const clip = selectedClip.value
  const track = selectedTrack.value
  return !!clip && !clip.locked && !track?.locked && selectedClipDuration.value >= MIN_RERUN_CLIP_SECONDS
})
const rerunGuardText = computed(() => {
  if (!selectedClip.value) return ''
  if (selectedTrack.value?.locked || selectedClip.value.locked) return '片段已锁定，不能重推理'
  if (selectedClipDuration.value < MIN_RERUN_CLIP_SECONDS) {
    return `片段 ${selectedClipDuration.value.toFixed(2)}s，至少 ${MIN_RERUN_CLIP_SECONDS.toFixed(2)}s 才能重推理`
  }
  return ''
})
const timelineWidth = computed(() => Math.max(980, (project.value?.duration || 60) * zoom.value + 240))
const tickStep = computed(() => (zoom.value < 34 ? 10 : zoom.value < 72 ? 5 : zoom.value < 130 ? 2 : 1))
const splitTarget = computed(() => findSplitTarget())
const canSplitAtPlayhead = computed(() => !!splitTarget.value)
const ticks = computed(() => {
  const total = Math.ceil(project.value?.duration || 0)
  const arr: number[] = []
  for (let t = 0; t <= total + tickStep.value; t += tickStep.value) arr.push(t)
  return arr
})

function snapshot(): EditorProject | null {
  return project.value ? JSON.parse(JSON.stringify(project.value)) as EditorProject : null
}
function pushHistory() {
  const snap = snapshot()
  if (!snap) return
  history.value.push(snap)
  if (history.value.length > 80) history.value.shift()
  future.value = []
}
function applyProject(next: EditorProject | null) {
  if (!next) return
  project.value = next
  waveformMap.value = {}
  waveformLoading.clear()
  selected.value = keepSelection(next)
  router.replace({ path: '/editor', query: { project: next.id } })
  nextTick(loadWaveforms)
}
function keepSelection(next: EditorProject): Selection | null {
  if (!selected.value) return null
  const track = next.tracks.find((t) => t.id === selected.value?.trackId)
  if (track?.clips.some((c) => c.id === selected.value?.clipId)) return selected.value
  return null
}

async function loadInitial() {
  await modelsStore.ensureLoaded()
  const projectId = typeof route.query.project === 'string' ? route.query.project : ''
  const workId = typeof route.query.work === 'string' ? route.query.work : ''
  if (projectId) {
    applyProject(await api.getEditorProject(projectId))
    return
  }
  if (workId) {
    const created = await api.createEditorProjectFromWork(workId)
    if (created) applyProject(created)
    else ElMessage.error('无法从该作品创建编辑工程')
    return
  }
  await router.replace('/editor/projects')
}

async function importAudio() {
  const path = await api.pickAudioFile()
  if (!path) return
  const created = await api.createEditorProjectFromAudio(path)
  if (!created) {
    ElMessage.error('导入音频失败')
    return
  }
  history.value = []
  future.value = []
  applyProject(created)
}

async function saveProject() {
  if (!project.value) return
  project.value.duration = calcDuration(project.value)
  const saved = await api.saveEditorProject(project.value)
  if (saved) project.value = saved
}

async function undo() {
  if (!project.value) return
  const prev = history.value.pop()
  if (prev) {
    const cur = snapshot()
    if (cur) future.value.push(cur)
    project.value = prev
    waveformMap.value = {}
    await api.saveEditorProject(prev)
    nextTick(loadWaveforms)
    return
  }
  applyProject(await api.undoEditorProject(project.value.id))
}

async function redo() {
  if (!project.value) return
  const next = future.value.pop()
  if (next) {
    const cur = snapshot()
    if (cur) history.value.push(cur)
    project.value = next
    waveformMap.value = {}
    await api.saveEditorProject(next)
    nextTick(loadWaveforms)
    return
  }
  applyProject(await api.redoEditorProject(project.value.id))
}

function selectClip(trackId: string, clipId: string) {
  selected.value = { trackId, clipId }
  const track = project.value?.tracks.find((t) => t.id === trackId)
  const clip = track?.clips.find((c) => c.id === clipId)
  if (clip) loadWaveform(clip)
}

function startDrag(e: PointerEvent, track: EditorTrack, clip: EditorClip, mode: DragMode) {
  if (!project.value || track.locked || clip.locked) return
  pushHistory()
  selectClip(track.id, clip.id)
  drag.value = {
    mode,
    startX: e.clientX,
    startY: e.clientY,
    trackId: track.id,
    clipId: clip.id,
    original: { ...clip },
    originalTrackIndex: project.value.tracks.findIndex((t) => t.id === track.id),
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', stopDrag, { once: true })
}

function onDragMove(e: PointerEvent) {
  if (!project.value || !drag.value) return
  const d = drag.value
  const dt = (e.clientX - d.startX) / zoom.value
  const rowShift = Math.round((e.clientY - d.startY) / 72)
  const sourceTrack = project.value.tracks.find((t) => t.id === selected.value?.trackId)
  if (!sourceTrack) return
  const clip = sourceTrack.clips.find((c) => c.id === d.clipId)
  if (!clip) return
  const minDur = 0.05
  if (d.mode === 'move') {
    const dur = d.original.end - d.original.start
    const start = snapTime(Math.max(0, d.original.start + dt), d.clipId)
    clip.start = start
    clip.end = start + dur
    const targetIndex = clamp(d.originalTrackIndex + rowShift, 0, project.value.tracks.length - 1)
    const target = project.value.tracks[targetIndex]
    if (target && target.id !== sourceTrack.id && !target.locked) {
      sourceTrack.clips = sourceTrack.clips.filter((c) => c.id !== clip.id)
      target.clips.push(clip)
      selected.value = { trackId: target.id, clipId: clip.id }
    }
  } else if (d.mode === 'start') {
    const start = snapTime(Math.min(d.original.end - minDur, Math.max(0, d.original.start + dt)), d.clipId)
    const shift = start - d.original.start
    clip.start = start
    clip.offset = Math.max(0, d.original.offset + shift)
  } else {
    clip.end = snapTime(Math.max(d.original.start + minDur, d.original.end + dt), d.clipId)
  }
  project.value.duration = calcDuration(project.value)
}

async function stopDrag() {
  window.removeEventListener('pointermove', onDragMove)
  const clip = selected.value?.clipId ? findClipById(selected.value.clipId) : null
  drag.value = null
  await saveProject()
  if (clip) loadWaveform(clip)
}

function onTimelinePointer(e: PointerEvent) {
  if (e.button !== 0) return
  const el = scrollEl.value
  if (!el || !project.value) return
  if (shouldIgnoreTimelinePointer(e, el)) return
  timelineSeeking.value = true
  setPlayheadFromPointer(e)
  window.addEventListener('pointermove', onTimelinePointerMove)
  window.addEventListener('pointerup', stopTimelinePointer, { once: true })
}

function shouldIgnoreTimelinePointer(e: PointerEvent, el: HTMLElement) {
  const rect = el.getBoundingClientRect()
  const horizontalScrollbar = Math.max(0, el.offsetHeight - el.clientHeight)
  const verticalScrollbar = Math.max(0, el.offsetWidth - el.clientWidth)
  if (horizontalScrollbar > 0 && e.clientY >= rect.bottom - horizontalScrollbar) return true
  if (verticalScrollbar > 0 && e.clientX >= rect.right - verticalScrollbar) return true
  const target = e.target instanceof Element ? e.target : null
  return !!target?.closest('.track-label, button, .el-slider, .el-input, .el-select')
}

function onTimelinePointerMove(e: PointerEvent) {
  if (!timelineSeeking.value) return
  setPlayheadFromPointer(e)
}

function stopTimelinePointer() {
  window.removeEventListener('pointermove', onTimelinePointerMove)
  timelineSeeking.value = false
  syncMixAudioToPlayhead()
}

function setPlayheadFromPointer(e: PointerEvent) {
  const el = scrollEl.value
  if (!el || !project.value) return
  const rect = el.getBoundingClientRect()
  const next = (e.clientX - rect.left + el.scrollLeft - 128) / zoom.value
  playhead.value = clamp(next, 0, project.value.duration)
  syncMixAudioToPlayhead()
}

function syncMixAudioToPlayhead() {
  const el = audioEl.value
  if (!el || playbackMode.value !== 'mix' || !el.src) return
  const max = Number.isFinite(el.duration) && el.duration > 0 ? el.duration : project.value?.duration || playhead.value
  el.currentTime = clamp(playhead.value, 0, max)
}

function clipStyle(clip: EditorClip) {
  const left = Math.max(0, clip.start * zoom.value)
  const width = clipPixelWidth(clip)
  return { left: left + 'px', width: width + 'px' }
}

function clipDuration(clip: EditorClip) {
  return Math.max(0.05, Number(clip.end || 0) - Number(clip.start || 0))
}

function clipPixelWidth(clip: EditorClip) {
  return Math.max(30, clipDuration(clip) * zoom.value)
}

function waveformBins(clip: EditorClip) {
  const drawable = Math.max(12, clipPixelWidth(clip))
  return Math.max(16, Math.min(900, Math.round(drawable / 3)))
}

function waveformKey(clip: EditorClip) {
  const duration = clipDuration(clip).toFixed(3)
  const offset = Number(clip.offset || 0).toFixed(3)
  return [clip.id, clip.file || '', offset, duration, waveformBins(clip)].join('|')
}

function fallbackWaveform(clip: EditorClip) {
  const count = waveformBins(clip)
  return Array.from({ length: count }, (_, i) => fallbackPeaks[i % fallbackPeaks.length] || 0.18)
}

function waveformPeaks(clip: EditorClip) {
  const key = waveformKey(clip)
  const peaks = waveformMap.value[key]
  return peaks?.length ? peaks : fallbackWaveform(clip)
}

function waveBarStyle(peak: number) {
  const value = Math.max(0, Math.min(1, Number(peak || 0)))
  return {
    height: `${Math.max(2, value * 42)}px`,
    opacity: value < 0.01 ? 0.28 : 1,
  }
}

function findClipById(clipId: string) {
  for (const track of project.value?.tracks || []) {
    const clip = track.clips.find((c) => c.id === clipId)
    if (clip) return clip
  }
  return null
}

function snapTime(value: number, excludeClipId?: string): number {
  const v = Math.max(0, value)
  if (!snapEnabled.value || !project.value) return v
  const threshold = 10 / zoom.value
  const grid = Math.round(v / 0.25) * 0.25
  let best = grid
  let bestDelta = Math.abs(v - grid)
  for (const track of project.value.tracks) {
    for (const clip of track.clips) {
      if (clip.id === excludeClipId) continue
      for (const b of [clip.start, clip.end]) {
        const delta = Math.abs(v - b)
        if (delta < threshold && delta < bestDelta) {
          best = b
          bestDelta = delta
        }
      }
    }
  }
  return Math.max(0, Number(best.toFixed(3)))
}

function toggleTrackMute(track: EditorTrack) {
  pushHistory()
  track.mute = !track.mute
  saveProject()
}
function toggleTrackLock(track: EditorTrack) {
  track.locked = !track.locked
  saveProject()
}
function toggleClipMute() {
  if (!selectedClip.value) return
  pushHistory()
  selectedClip.value.mute = !selectedClip.value.mute
  saveProject()
}
function toggleClipLock() {
  if (!selectedClip.value) return
  selectedClip.value.locked = !selectedClip.value.locked
  saveProject()
}
function deleteSelectedClip() {
  if (!project.value || !selected.value) return
  const track = selectedTrack.value
  if (!track) return
  pushHistory()
  track.clips = track.clips.filter((c) => c.id !== selected.value?.clipId)
  selected.value = null
  saveProject()
}

function setClipChannel(channel: EditorClipChannel) {
  const clip = selectedClip.value
  if (!clip || clipChannel(clip) === channel) return
  pushHistory()
  clip.channel = channel
  saveProject()
}

function clipChannel(clip?: EditorClip | null): EditorClipChannel {
  if (clip?.channel === 'left' || clip?.channel === 'right') return clip.channel
  return 'stereo'
}

function channelLabel(channel: EditorClipChannel) {
  if (channel === 'left') return 'L'
  if (channel === 'right') return 'R'
  return '双'
}

function findSplitTarget(): { track: EditorTrack; clip: EditorClip } | null {
  if (!project.value) return null
  const t = playhead.value
  const isReady = (track: EditorTrack, clip: EditorClip) => {
    if (track.locked || clip.locked) return false
    return t > clip.start + 0.05 && t < clip.end - 0.05
  }
  if (selectedTrack.value && selectedClip.value && isReady(selectedTrack.value, selectedClip.value)) {
    return { track: selectedTrack.value, clip: selectedClip.value }
  }
  for (const track of project.value.tracks) {
    for (const clip of track.clips) {
      if (isReady(track, clip)) return { track, clip }
    }
  }
  return null
}

async function splitAtPlayhead() {
  if (!project.value) return
  const target = splitTarget.value
  if (!target) {
    ElMessage.info('把播放头放在可编辑片段内部再剪切')
    return
  }
  const { track, clip } = target
  const cut = snapTime(playhead.value, clip.id)
  if (cut <= clip.start + 0.05 || cut >= clip.end - 0.05) {
    ElMessage.info('切口离片段边缘太近')
    return
  }

  pushHistory()
  const original = {
    ...clip,
    metadata: { ...(clip.metadata || {}) },
    effects: [...(clip.effects || [])],
  }
  const minDur = 0.05
  const maxHalf = Math.max(0, Math.min(cut - original.start - minDur, original.end - cut - minDur))
  const half = Math.min(Math.max(0, cutCrossfade.value / 2), maxHalf)
  const fade = roundTime(half * 2)
  const leftEnd = roundTime(cut + half)
  const rightStart = roundTime(cut - half)
  const rightOffset = roundTime(original.offset + (rightStart - original.start))
  const rightClip: EditorClip = {
    ...original,
    id: makeId('clp_'),
    name: `${original.name || '片段'} · 后段`,
    start: rightStart,
    end: original.end,
    offset: Math.max(0, rightOffset),
    fade_in: fade,
    fade_out: original.fade_out || 0,
    channel: clipChannel(original),
    metadata: {
      ...(original.metadata || {}),
      split_parent: original.id,
      split_at: roundTime(cut),
      split_crossfade: fade,
      split_side: 'right',
    },
  }
  clip.end = leftEnd
  clip.fade_in = original.fade_in || 0
  clip.fade_out = fade
  clip.channel = clipChannel(original)
  clip.metadata = {
    ...(original.metadata || {}),
    split_at: roundTime(cut),
    split_crossfade: fade,
    split_side: 'left',
  }

  const idx = track.clips.findIndex((c) => c.id === clip.id)
  track.clips.splice(idx >= 0 ? idx + 1 : track.clips.length, 0, rightClip)
  selected.value = { trackId: track.id, clipId: rightClip.id }
  project.value.duration = calcDuration(project.value)
  await saveProject()
  loadWaveform(clip)
  loadWaveform(rightClip)
  ElMessage.success(fade > 0 ? `已剪切，切口交叉淡化 ${fade.toFixed(2)}s` : '已剪切')
}

async function setClipNumber(field: 'start' | 'end' | 'offset', e: Event) {
  const clip = selectedClip.value
  if (!clip) return
  const value = Number((e.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  pushHistory()
  if (field === 'start') clip.start = Math.max(0, Math.min(value, clip.end - 0.05))
  else if (field === 'end') clip.end = Math.max(clip.start + 0.05, value)
  else clip.offset = Math.max(0, value)
  if (project.value) project.value.duration = calcDuration(project.value)
  await saveProject()
  loadWaveform(clip)
}

function claimPlayToggle() {
  const now = Date.now()
  if (now - lastPlayToggleAt < PLAY_TOGGLE_DEBOUNCE_MS) return false
  lastPlayToggleAt = now
  return true
}

function stopPlayback() {
  mixPreviewRequestId += 1
  previewing.value = false
  if (clipStopTimer) {
    clearTimeout(clipStopTimer)
    clipStopTimer = null
  }
  audioEl.value?.pause()
  playing.value = false
  playbackMode.value = 'none'
}

async function playMix() {
  if (!project.value || !audioEl.value) return
  if (!claimPlayToggle() || previewing.value) return
  if (playing.value) {
    stopPlayback()
    return
  }
  const requestId = ++mixPreviewRequestId
  previewing.value = true
  try {
    await saveProject()
    if (!project.value) return
    const data = await api.renderEditorPreview(project.value.id)
    if (requestId !== mixPreviewRequestId) return
    if (!data) {
      ElMessage.error('预览渲染失败')
      return
    }
    if (clipStopTimer) {
      clearTimeout(clipStopTimer)
      clipStopTimer = null
    }
    playbackMode.value = 'mix'
    audioEl.value.src = data
    audioEl.value.currentTime = Math.max(0, playhead.value)
    await audioEl.value.play()
    playing.value = true
  } catch (err) {
    playbackMode.value = 'none'
    ElMessage.error(err instanceof Error ? err.message : '播放失败')
  } finally {
    if (requestId === mixPreviewRequestId) previewing.value = false
  }
}

async function playSelectedClip() {
  if (!project.value || !selectedClip.value || !audioEl.value) return
  const clip = selectedClip.value
  const data = await api.getEditorClipAudio(project.value.id, clip.id)
  if (!data) {
    ElMessage.error('无法加载片段音频')
    return
  }
  if (clipStopTimer) clearTimeout(clipStopTimer)
  playbackMode.value = 'clip'
  audioEl.value.src = data
  audioEl.value.currentTime = Math.max(0, clip.offset || 0)
  await audioEl.value.play()
  playing.value = true
  clipStopTimer = setTimeout(() => {
    audioEl.value?.pause()
    playing.value = false
    playbackMode.value = 'none'
  }, Math.max(80, (clip.end - clip.start) * 1000))
}

async function exportMix(fmt: string) {
  if (!project.value) return
  await saveProject()
  const dest = await api.exportEditorProject(project.value.id, fmt)
  if (dest) {
    renderedPath.value = dest
    ElMessage.success('已导出到：' + dest)
  } else {
    ElMessage.info('已取消导出')
  }
}

async function exitEditor() {
  stopPlayback()
  if (project.value) await saveProject()
  await router.push('/editor/projects')
}

async function discardProject() {
  const current = project.value
  if (!current) return
  try {
    await ElMessageBox.confirm(
      '放弃后会删除当前编辑工程和导入到工程里的编辑素材，原始歌曲与翻唱作品不会删除。',
      '放弃这个工程？',
      {
        confirmButtonText: '放弃工程',
        cancelButtonText: '继续编辑',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  stopPlayback()
  const ok = await api.deleteEditorProject(current.id)
  if (!ok) {
    ElMessage.error('放弃工程失败')
    return
  }
  project.value = null
  selected.value = null
  history.value = []
  future.value = []
  renderedPath.value = ''
  ElMessage.success('已放弃编辑工程')
  await router.push('/editor/projects')
}

async function rerunClip() {
  if (!project.value || !selected.value || !rerunModelId.value) return
  if (!canRerunSelectedClip.value) {
    ElMessage.warning(rerunGuardText.value || '当前片段不能重推理')
    return
  }
  rerunning.value = true
  const res = await api.rerunEditorClip(
    project.value.id,
    selected.value.trackId,
    selected.value.clipId,
    rerunModelId.value,
    {},
  )
  rerunning.value = false
  if (!res.ok || !res.project) {
    ElMessage.error(res.error || '局部重推理失败')
    return
  }
  applyProject(res.project)
  ElMessage.success('片段已替换')
}

function seekStart() {
  playhead.value = 0
  if (audioEl.value && playbackMode.value === 'mix') audioEl.value.currentTime = 0
}
function onAudioPause() {
  if (audioEl.value?.ended) playing.value = false
}
function onAudioEnded() {
  playing.value = false
  playbackMode.value = 'none'
  if (project.value) playhead.value = project.value.duration
}
function onAudioTimeUpdate() {
  const el = audioEl.value
  if (!el || playbackMode.value !== 'mix' || timelineSeeking.value) return
  playhead.value = clamp(el.currentTime, 0, project.value?.duration || el.currentTime)
}

async function loadWaveforms() {
  if (!project.value) return
  for (const track of project.value.tracks) {
    for (const clip of track.clips) {
      loadWaveform(clip)
    }
  }
}
async function loadWaveform(input: EditorClip | string) {
  if (!project.value) return
  const clip = typeof input === 'string' ? findClipById(input) : input
  if (!clip) return
  const key = waveformKey(clip)
  if (waveformMap.value[key]?.length || waveformLoading.has(key)) return
  waveformLoading.add(key)
  try {
    const bins = waveformBins(clip)
    const wf = await api.getEditorWaveform(project.value.id, clip.id, bins)
    if (wf.ok && wf.peaks.length && waveformKey(clip) === key) {
      waveformMap.value = { ...waveformMap.value, [key]: wf.peaks }
    }
  } finally {
    waveformLoading.delete(key)
  }
}

watch(zoom, () => {
  if (waveformZoomTimer) clearTimeout(waveformZoomTimer)
  waveformZoomTimer = setTimeout(() => {
    waveformZoomTimer = null
    void loadWaveforms()
  }, 140)
})

function calcDuration(p: EditorProject) {
  return Math.max(0.05, ...p.tracks.flatMap((t) => t.clips.map((c) => c.end || 0)))
}
function fmtTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds || 0))
  const m = Math.floor(s / 60)
  const rest = s % 60
  return `${m}:${String(rest).padStart(2, '0')}`
}
function fmtTick(seconds: number) {
  return fmtTime(seconds)
}
function round(value: number | undefined) {
  return Number(value || 0).toFixed(2)
}
function roundTime(value: number) {
  return Number(value.toFixed(3))
}
function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v))
}
function makeId(prefix: string) {
  return prefix + Math.random().toString(36).slice(2, 9) + Date.now().toString(36)
}
function fadeStyle(seconds: number | undefined, clip: EditorClip) {
  const clipWidth = Math.max(30, (clip.end - clip.start) * zoom.value)
  const width = Math.min(clipWidth / 2, Math.max(0, Number(seconds || 0) * zoom.value))
  return { width: `${width}px` }
}
function onKey(e: KeyboardEvent) {
  if (!project.value || !e.ctrlKey) return
  const key = e.key.toLowerCase()
  if (key === 'z') {
    e.preventDefault()
    undo()
  } else if (key === 'y') {
    e.preventDefault()
    redo()
  }
}

watch(
  () => route.query.project,
  async (id) => {
    if (typeof id === 'string' && id && id !== project.value?.id) {
      applyProject(await api.getEditorProject(id))
    }
  },
)

onMounted(() => {
  window.addEventListener('keydown', onKey)
  loadInitial()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointermove', onTimelinePointerMove)
  window.removeEventListener('pointerup', stopTimelinePointer)
  if (clipStopTimer) clearTimeout(clipStopTimer)
  if (waveformZoomTimer) clearTimeout(waveformZoomTimer)
})
</script>

<style scoped>
.editor-page {
  max-width: 1460px;
  margin: 0 auto;
  padding: 24px 24px 56px;
}
.editor-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 18px;
  margin-bottom: 20px;
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
}
.editor-head h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 800;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.glass {
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
}
.ghost-btn {
  background: rgba(var(--xb-fill-rgb), 0.04) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.danger-btn {
  background: rgba(var(--xb-accent-rgb), 0.08) !important;
  border: 1px solid rgba(var(--xb-accent-rgb), 0.42) !important;
  color: var(--xb-accent) !important;
  font-weight: 700;
}
.editor-shell {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.inspector {
  border-radius: 6px;
  padding: 18px;
  min-height: 640px;
}
.project-block label,
.rerun-box label {
  display: block;
  color: var(--xb-muted);
  font-size: 12px;
  margin-bottom: 8px;
}
.title-input,
.field-grid input,
.rerun-box select {
  width: 100%;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.05);
  color: var(--xb-text);
  padding: 0 10px;
  outline: none;
}
.title-input:focus,
.field-grid input:focus,
.rerun-box select:focus {
  border-color: var(--xb-primary);
}
.project-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
  color: var(--xb-muted);
  font-size: 12px;
}
.project-meta span {
  padding: 4px 8px;
  border-radius: 7px;
  background: rgba(var(--xb-fill-rgb), 0.05);
}
.tool-block,
.clip-block {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--xb-border);
}
.tool-row,
.slider-row,
.channel-row {
  display: grid;
  grid-template-columns: 66px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-height: 38px;
  color: var(--xb-muted);
  font-size: 13px;
}
.channel-row {
  margin-top: 12px;
}
.channel-segment {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
}
.channel-segment button {
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--xb-muted);
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
.channel-segment button:hover,
.channel-segment button.active {
  color: var(--xb-on-primary);
  background: var(--xb-brand-gradient);
}
.clip-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  font-weight: 700;
}
.clip-title span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.clip-title button,
.clip-actions button,
.transport button,
.track-label button,
.edit-tools button {
  width: 32px;
  height: 32px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  display: inline-grid;
  place-items: center;
  cursor: pointer;
}
.clip-title button.active,
.clip-actions button.active,
.track-label button.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
}
.clip-actions button:disabled,
.transport button:disabled,
.edit-tools button:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.clip-actions button.danger {
  color: var(--xb-accent);
}
.field-grid {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  color: var(--xb-muted);
  font-size: 12px;
}
.clip-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.rerun-box {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}
.rerun-hint {
  color: var(--xb-warn);
  font-size: 12px;
  line-height: 1.5;
}
.mini {
  width: 100%;
}
.empty-side {
  min-height: 220px;
  display: grid;
  place-items: center;
  color: var(--xb-muted);
  gap: 8px;
}
.empty-side .el-icon {
  font-size: 26px;
}
.timeline {
  border-radius: 6px;
  overflow: hidden;
  min-height: 640px;
}
.timeline-top {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--xb-border);
}
.timeline-main-tools {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.transport {
  display: flex;
  align-items: center;
  gap: 8px;
}
.transport span {
  min-width: 48px;
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
.edit-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.edit-tools .split-btn {
  width: auto;
  min-width: 72px;
  padding: 0 10px;
  grid-auto-flow: column;
  gap: 6px;
  font-weight: 700;
}
.edit-tools .split-btn:not(:disabled):hover {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
}
.xf-badge {
  height: 24px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: rgba(var(--xb-primary-rgb), 0.1);
  color: var(--xb-primary);
  font-size: 12px;
  font-weight: 800;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
.render-path {
  min-width: 0;
  max-width: 50%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-muted);
  font-size: 12px;
}
.timeline-scroll {
  position: relative;
  overflow: auto;
  max-height: 720px;
}
.ruler {
  position: sticky;
  top: 0;
  z-index: 6;
  height: 42px;
  margin-left: 128px;
  background: rgba(var(--xb-bg-rgb), 0.92);
  border-bottom: 1px solid var(--xb-border);
}
.tick {
  position: absolute;
  top: 0;
  height: 42px;
  padding-left: 6px;
  border-left: 1px solid rgba(var(--xb-primary-rgb), 0.18);
  color: var(--xb-muted);
  font-size: 11px;
  line-height: 24px;
  user-select: none;
}
.playhead {
  position: absolute;
  top: 0;
  bottom: -900px;
  width: 2px;
  background: var(--xb-accent);
  box-shadow: 0 0 10px rgba(var(--xb-accent-rgb), 0.7);
  pointer-events: none;
}
.tracks {
  position: relative;
}
.track-row {
  display: grid;
  grid-template-columns: 128px minmax(0, 1fr);
  min-height: 72px;
  border-bottom: 1px solid rgba(var(--xb-fill-rgb), 0.07);
}
.track-label {
  position: sticky;
  left: 0;
  z-index: 4;
  display: grid;
  grid-template-columns: 30px 30px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  padding: 8px;
  background: var(--xb-bg-2);
  border-right: 1px solid var(--xb-border);
}
.track-label button {
  width: 28px;
  height: 28px;
}
.track-name {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 700;
}
.track-lane {
  position: relative;
  min-height: 72px;
  background-image: linear-gradient(90deg, rgba(var(--xb-fill-rgb), 0.04) 1px, transparent 1px);
  background-size: 64px 100%;
}
.clip {
  position: absolute;
  top: 10px;
  height: 52px;
  min-width: 30px;
  border-radius: 6px;
  border: 1px solid rgba(var(--xb-primary-rgb), 0.42);
  background: rgba(var(--xb-primary-rgb), 0.18);
  color: var(--xb-text);
  overflow: hidden;
  cursor: grab;
  user-select: none;
}
.clip:active {
  cursor: grabbing;
}
.clip.bgm {
  border-color: rgba(var(--xb-success-rgb), 0.45);
  background: rgba(var(--xb-success-rgb), 0.18);
}
.clip.ai {
  border-color: rgba(var(--xb-accent-rgb), 0.48);
  background: rgba(var(--xb-accent-rgb), 0.18);
}
.clip.effect {
  border-color: rgba(var(--xb-warn-rgb), 0.48);
  background: rgba(var(--xb-warn-rgb), 0.14);
}
.clip.selected {
  border-color: var(--xb-primary);
  box-shadow: 0 0 0 1px var(--xb-primary), 0 0 18px rgba(var(--xb-primary-rgb), 0.25);
}
.clip.muted {
  opacity: 0.42;
}
.clip.locked {
  cursor: default;
}
.wave {
  position: absolute;
  inset: 5px 0;
  display: flex;
  align-items: center;
  gap: 1px;
  opacity: 0.72;
  z-index: 1;
}
.wave i {
  flex: 1 1 0;
  min-width: 1px;
  min-height: 2px;
  border-radius: 2px;
  background: currentColor;
}
.fade-guide {
  position: absolute;
  top: 0;
  bottom: 0;
  pointer-events: none;
  z-index: 2;
}
.fade-in {
  left: 0;
  background: linear-gradient(90deg, rgba(var(--xb-primary-rgb), 0.48), transparent);
  clip-path: polygon(0 100%, 100% 0, 100% 100%);
}
.fade-out {
  right: 0;
  background: linear-gradient(270deg, rgba(var(--xb-primary-rgb), 0.48), transparent);
  clip-path: polygon(0 0, 100% 100%, 0 100%);
}
.channel-pill {
  position: absolute;
  top: 4px;
  right: 10px;
  z-index: 3;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(var(--xb-accent-rgb), 0.18);
  color: var(--xb-accent);
  font-size: 11px;
  font-weight: 900;
  line-height: 18px;
  text-align: center;
}
.clip-name {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 5px;
  z-index: 3;
  font-size: 12px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 8px;
  border: none;
  background: transparent;
  cursor: ew-resize;
  z-index: 4;
}
.handle.left {
  left: 0;
}
.handle.right {
  right: 0;
}
.empty-state {
  min-height: 430px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 16px;
  color: var(--xb-muted);
}
.empty-state .el-icon {
  font-size: 42px;
  color: var(--xb-primary);
}
.empty-state p {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--xb-text);
}
@media (max-width: 1080px) {
  .editor-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .editor-shell {
    grid-template-columns: 1fr;
  }
  .inspector {
    min-height: 0;
  }
}
</style>
