<template>
  <div v-if="visible" class="global-player" data-guide="global-player">
    <div class="gp-track" @click="openFullPlayer">
      <div class="gp-cover" :style="{ '--gp-color': track?.color || 'var(--xb-primary)' }">
        <span class="gp-cover-ring" :class="{ spinning: player.playing }">
          <el-icon><Headset /></el-icon>
        </span>
      </div>
      <div class="gp-meta">
        <div class="gp-title" :title="track?.title">{{ track?.title || '未在播放' }}</div>
        <div class="gp-sub" :title="track?.subtitle">
          {{ track?.subtitle || '从作品库或曲库开始播放' }}
        </div>
      </div>
      <span v-if="player.currentQuality" class="gp-quality" :class="{ lossless: player.isLossless }">
        {{ player.currentQuality }}
      </span>
    </div>

    <div class="gp-controls">
      <PlayModeButton />
      <button
        class="gp-icon gp-skip"
        type="button"
        title="上一首"
        :disabled="!player.canGoPrev"
        @click="player.previous()"
      >
        <el-icon><CaretLeft /></el-icon>
      </button>
      <button
        class="gp-play"
        type="button"
        :title="player.playing ? '暂停' : '播放'"
        :disabled="!player.hasQueue"
        @click="player.togglePlay()"
      >
        <el-icon v-if="player.resolvingKey" class="spin"><Loading /></el-icon>
        <el-icon v-else-if="player.playing"><VideoPause /></el-icon>
        <el-icon v-else><VideoPlay /></el-icon>
      </button>
      <button
        class="gp-icon gp-skip"
        type="button"
        title="下一首"
        :disabled="!player.canGoNext"
        @click="player.next(false)"
      >
        <el-icon><CaretRight /></el-icon>
      </button>
      <button
        class="gp-icon gp-queue-mobile"
        type="button"
        title="播放队列"
        @click="player.toggleQueue()"
      >
        <el-icon><List /></el-icon>
        <span class="gp-badge">{{ player.queue.length }}</span>
      </button>
    </div>

    <div class="gp-seek">
      <span class="gp-time">{{ formatTime(seekDisplay) }}</span>
      <input
        class="gp-range"
        type="range"
        min="0"
        :max="player.duration || 0.01"
        step="0.01"
        :value="seekDisplay"
        aria-label="播放进度"
        @input="onSeekInput"
        @change="seekDraft = null"
      />
      <span class="gp-time">{{ formatTime(player.duration) }}</span>
    </div>

    <div class="gp-side">
      <span v-if="player.buffering" class="gp-buffering">缓冲中</span>
      <button
        class="gp-icon"
        type="button"
        :title="player.muted ? '取消静音' : '静音'"
        @click="player.toggleMute()"
      >
        <el-icon v-if="player.muted"><Mute /></el-icon>
        <el-icon v-else><Headset /></el-icon>
      </button>
      <input
        class="gp-volume"
        type="range"
        min="0"
        max="1"
        step="0.01"
        :value="player.volume"
        title="音量"
        aria-label="音量"
        @input="onVolumeInput"
      />
      <button class="gp-icon gp-queue" type="button" title="播放队列" @click="player.toggleQueue()">
        <el-icon><List /></el-icon>
        <span class="gp-badge">{{ player.queue.length }}</span>
      </button>
      <button class="gp-icon" type="button" title="打开完整播放器" @click="openFullPlayer">
        <el-icon><FullScreen /></el-icon>
      </button>
    </div>
  </div>
  <PlayerQueuePanel />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  CaretLeft,
  CaretRight,
  FullScreen,
  Headset,
  List,
  Loading,
  Mute,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import PlayerQueuePanel from './PlayerQueuePanel.vue'
import PlayModeButton from './PlayModeButton.vue'
import { formatTime } from '@/player/format'
import { usePlayerStore } from '@/stores/player'

defineOptions({ name: 'GlobalPlayer' })

const player = usePlayerStore()
const route = useRoute()
const router = useRouter()

/** 只有作品库与曲库资源页显示全局播放条；首页、AI 工作区和编辑器不被播放器占用。 */
const MINI_PLAYER_ROUTES = new Set(['Works', 'Music'])

const canShowMiniPlayer = computed(() => MINI_PLAYER_ROUTES.has(String(route.name)))
/** 全屏播放页不显示迷你条，但仍允许媒体快捷键继续工作。 */
const canControlPlayer = computed(() => canShowMiniPlayer.value || route.name === 'Player')
const visible = computed(
  () =>
    route.name !== 'Player' &&
    canShowMiniPlayer.value &&
    player.hasQueue &&
    player.sessionStarted &&
    !player.isAudition,
)
const track = computed(() => player.currentTrack)
const seekDraft = ref<number | null>(null)
const seekDisplay = computed(() => seekDraft.value ?? player.currentTime)

watch(
  () => player.activeKey,
  () => {
    seekDraft.value = null
  },
)

watch(
  () => route.name,
  () => {
    if (route.name !== 'Player' && player.queueOpen) player.toggleQueue(false)
    if (canControlPlayer.value) return
    // 工作区有自己的试听/播放，离开浏览页面时暂停全局背景音乐，避免声音来源混淆。
    if (player.playing && !player.isAudition) player.pause()
  },
)

watch(
  () => player.error,
  (message) => {
    if (!message) return
    ElMessage.error(message)
    player.clearError()
  },
)

function onSeekInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  seekDraft.value = value
  player.seek(value)
}

function onVolumeInput(event: Event) {
  player.setVolume(Number((event.target as HTMLInputElement).value))
}

function openFullPlayer() {
  const current = player.currentTrack
  if (current?.kind === 'work') {
    void router.push({ path: '/player', query: { work: current.id } })
  } else {
    void router.push('/player')
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  if (element.isContentEditable) return true
  const tag = element.tagName?.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'button'
}

function onKeydown(event: KeyboardEvent) {
  if (!canControlPlayer.value) return
  if (isEditableTarget(event.target)) return
  if (event.altKey) return
  const modifier = event.ctrlKey || event.metaKey
  if (modifier) {
    if (event.code === 'ArrowRight') {
      event.preventDefault()
      void player.next(false)
    } else if (event.code === 'ArrowLeft') {
      event.preventDefault()
      void player.previous()
    }
    return
  }
  switch (event.code) {
    case 'Space':
      if (!player.hasQueue) return
      event.preventDefault()
      void player.togglePlay()
      break
    case 'ArrowRight':
      event.preventDefault()
      player.seekBy(5)
      break
    case 'ArrowLeft':
      event.preventDefault()
      player.seekBy(-5)
      break
    case 'ArrowUp':
      event.preventDefault()
      player.setVolume(player.volume + 0.05)
      break
    case 'ArrowDown':
      event.preventDefault()
      player.setVolume(player.volume - 0.05)
      break
    case 'KeyM':
      player.toggleMute()
      break
    default:
      break
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.global-player {
  position: relative;
  z-index: 30;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto minmax(240px, 1.4fr) auto;
  align-items: center;
  gap: 18px;
  min-height: 78px;
  padding: 10px 20px;
  border-top: 1px solid var(--xb-border);
  background:
    linear-gradient(180deg, rgba(var(--xb-primary-rgb), 0.04), transparent 60%),
    var(--xb-bg-2);
  box-shadow: 0 -14px 36px rgba(var(--xb-bg-rgb), 0.45);
}
.gp-track {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  cursor: pointer;
}
.gp-cover {
  flex: 0 0 46px;
  width: 46px;
  height: 46px;
  position: relative;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 45%, rgba(255, 255, 255, 0.16), transparent 55%),
    repeating-radial-gradient(circle, #10101a 0 2px, #191a26 3px 4px);
  box-shadow: 0 0 20px color-mix(in srgb, var(--gp-color) 34%, transparent);
}
.gp-cover-ring {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  font-size: 13px;
  background: linear-gradient(145deg, var(--gp-color), var(--xb-primary-2));
}
.gp-cover-ring.spinning {
  animation: gp-spin 9s linear infinite;
}
.gp-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.gp-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 700;
}
.gp-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-muted);
  font-size: 11px;
}
.gp-quality {
  flex: 0 0 auto;
  padding: 3px 7px;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  color: var(--xb-muted);
  font: 9px/1 ui-monospace, monospace;
  letter-spacing: 0.4px;
  white-space: nowrap;
}
.gp-quality.lossless {
  color: var(--xb-success);
  border-color: rgba(var(--xb-success-rgb), 0.4);
}
.gp-controls {
  display: flex;
  align-items: center;
  gap: 5px;
}
.gp-icon {
  position: relative;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  transition: 0.18s ease;
}
.gp-icon:hover:not(:disabled) {
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.gp-icon:disabled {
  opacity: 0.3;
  cursor: default;
}
.gp-skip {
  font-size: 18px;
}
.gp-play {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  color: var(--xb-on-primary);
  font-size: 18px;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(var(--xb-primary-rgb), 0.3);
}
.gp-play:hover:not(:disabled) {
  transform: translateY(-1px);
}
.gp-play:disabled {
  opacity: 0.5;
  cursor: default;
}
.gp-seek {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.gp-range {
  flex: 1;
  min-width: 0;
  height: 4px;
  accent-color: var(--xb-primary);
  cursor: pointer;
}
.gp-time {
  flex: 0 0 auto;
  color: var(--xb-muted);
  font: 10px ui-monospace, monospace;
}
.gp-side {
  display: flex;
  align-items: center;
  gap: 4px;
}
.gp-volume {
  width: 82px;
  accent-color: var(--xb-primary);
  cursor: pointer;
}
.gp-buffering {
  margin-right: 4px;
  color: var(--xb-primary);
  font-size: 10px;
  animation: gp-pulse 1.2s ease-in-out infinite;
}
.gp-badge {
  position: absolute;
  top: 1px;
  right: 0;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 999px;
  background: var(--xb-accent);
  color: #fff;
  font: 9px/14px ui-monospace, monospace;
  text-align: center;
}
.gp-queue-mobile {
  display: none;
}
.spin {
  animation: gp-spin 1s linear infinite;
}
@keyframes gp-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes gp-pulse {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}
@media (max-width: 980px) {
  .global-player {
    grid-template-columns: minmax(150px, 1fr) auto minmax(160px, 1fr) auto;
    gap: 10px;
    padding: 9px 12px;
  }
  .gp-volume {
    display: none;
  }
  .gp-quality {
    display: none;
  }
}
@media (max-width: 720px) {
  .global-player {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'track controls'
      'seek seek';
    row-gap: 6px;
    min-height: 86px;
  }
  .gp-track {
    grid-area: track;
  }
  .gp-controls {
    grid-area: controls;
  }
  .gp-seek {
    grid-area: seek;
  }
  .gp-side {
    display: none;
  }
  .gp-queue-mobile {
    display: grid;
  }
  .gp-sub {
    display: none;
  }
}
</style>
