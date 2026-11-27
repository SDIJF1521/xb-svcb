<template>
  <Teleport to="body">
    <Transition name="queue-fade">
      <div v-if="player.queueOpen" class="queue-mask" @click.self="player.toggleQueue(false)">
        <aside class="queue-panel" role="dialog" aria-label="播放队列">
          <header class="queue-head">
            <div>
              <p class="eyebrow">PLAY QUEUE</p>
              <h2>播放队列</h2>
            </div>
            <button class="queue-close" title="收起队列" @click="player.toggleQueue(false)">
              <el-icon><Close /></el-icon>
            </button>
          </header>

          <div class="queue-modes" role="group" aria-label="播放顺序">
            <button
              v-for="item in PLAY_MODES"
              :key="item"
              class="queue-mode"
              :class="{ active: player.mode === item }"
              :title="PLAY_MODE_HINTS[item]"
              @click="player.setMode(item)"
            >
              <PlayModeIcon :mode="item" />
              <span>{{ PLAY_MODE_LABELS[item] }}</span>
            </button>
          </div>

          <div ref="listEl" class="queue-list">
            <div
              v-for="(track, index) in player.queue"
              :key="track.key"
              class="queue-row"
              :class="{ current: player.isCurrent(track.key), dragging: dragIndex === index }"
              draggable="true"
              @click="player.jumpTo(track.key)"
              @dragstart="onDragStart(index, $event)"
              @dragend="dragIndex = null"
              @dragover.prevent
              @drop.prevent="onDrop(index)"
            >
              <span class="queue-index">
                <span v-if="player.isPlayingKey(track.key)" class="eq" aria-label="正在播放">
                  <i></i><i></i><i></i>
                </span>
                <span v-else>{{ index + 1 }}</span>
              </span>
              <span class="queue-cover" :style="{ background: track.color }">
                <el-icon><Headset /></el-icon>
              </span>
              <span class="queue-main">
                <span class="queue-title" :title="track.title">{{ track.title }}</span>
                <span class="queue-sub" :title="track.subtitle">{{ track.subtitle }}</span>
              </span>
              <span class="queue-time">{{ track.duration ? formatTime(track.duration) : '--:--' }}</span>
              <span class="queue-ops" @click.stop>
                <button title="上移" :disabled="index === 0" @click="player.moveTrack(index, index - 1)">
                  <el-icon><Top /></el-icon>
                </button>
                <button
                  title="下移"
                  :disabled="index === player.queue.length - 1"
                  @click="player.moveTrack(index, index + 1)"
                >
                  <el-icon><Bottom /></el-icon>
                </button>
                <button title="移出队列" @click="player.removeTrack(track.key)">
                  <el-icon><Close /></el-icon>
                </button>
              </span>
            </div>

            <div v-if="!player.queue.length" class="queue-empty">
              <el-icon><Headset /></el-icon>
              <strong>队列是空的</strong>
              <span>在作品库点击播放，或把在线歌曲加入队列。</span>
            </div>
          </div>

          <footer class="queue-foot">
            <span>
              {{ player.queue.length }} 首<template v-if="totalLabel"> · {{ totalLabel }}</template>
            </span>
            <button class="queue-clear" :disabled="!player.queue.length" @click="clearQueue">清空队列</button>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Bottom, Close, Headset, Top } from '@element-plus/icons-vue'

import { formatTime, formatTotalDuration } from '@/player/format'
import { PLAY_MODE_HINTS, PLAY_MODE_LABELS, PLAY_MODES } from '@/player/queue'
import { usePlayerStore } from '@/stores/player'
import PlayModeIcon from './PlayModeIcon.vue'

defineOptions({ name: 'PlayerQueuePanel' })

const player = usePlayerStore()
const dragIndex = ref<number | null>(null)
const listEl = ref<HTMLElement | null>(null)
const totalLabel = computed(() => formatTotalDuration(player.queueDuration))

watch(
  () => player.queueOpen,
  async (open) => {
    if (!open) return
    await nextTick()
    const current = listEl.value?.querySelector('.queue-row.current')
    current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  },
)

function onDrop(target: number) {
  if (dragIndex.value === null || dragIndex.value === target) {
    dragIndex.value = null
    return
  }
  player.moveTrack(dragIndex.value, target)
  dragIndex.value = null
}

function onDragStart(index: number, event: DragEvent) {
  dragIndex.value = index
  event.dataTransfer?.setData('text/plain', String(index))
}

function clearQueue() {
  player.clearQueue()
}
</script>

<style scoped>
.queue-mask {
  position: fixed;
  inset: 0;
  z-index: 1800;
  display: flex;
  justify-content: flex-end;
  background: rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(2px);
}
.queue-panel {
  width: min(430px, 100vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 22px 20px 16px;
  border-left: 1px solid var(--xb-border);
  background: var(--xb-bg-2);
  box-shadow: -18px 0 60px rgba(0, 0, 0, 0.4);
}
.queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.eyebrow {
  margin: 0 0 6px;
  color: var(--xb-primary);
  font: 700 10px/1 ui-monospace, monospace;
  letter-spacing: 1.5px;
}
.queue-head h2 {
  margin: 0;
  font-size: 22px;
}
.queue-close {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid var(--xb-border);
  border-radius: 50%;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
}
.queue-close:hover {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
}
.queue-modes {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin: 16px 0 12px;
}
.queue-mode {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 34px;
  padding: 0 4px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: transparent;
  color: var(--xb-muted);
  font-size: 11px;
  cursor: pointer;
  transition: 0.2s ease;
}
.queue-mode:hover {
  color: var(--xb-text);
  border-color: rgba(var(--xb-primary-rgb), 0.45);
}
.queue-mode.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
}
.queue-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px;
  border: 1px solid var(--xb-border);
  border-radius: 10px;
  background: var(--xb-bg);
  scrollbar-width: thin;
}
.queue-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.18s ease;
}
.queue-row:hover {
  background: rgba(var(--xb-primary-rgb), 0.06);
}
.queue-row.current {
  background: rgba(var(--xb-primary-rgb), 0.1);
}
.queue-row.dragging {
  opacity: 0.5;
}
.queue-index {
  flex: 0 0 22px;
  text-align: center;
  color: var(--xb-muted);
  font: 11px ui-monospace, monospace;
}
.queue-row.current .queue-index {
  color: var(--xb-primary);
}
.queue-cover {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--xb-on-primary);
  font-size: 16px;
}
.queue-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.queue-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 600;
}
.queue-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-muted);
  font-size: 11px;
}
.queue-time {
  flex: 0 0 auto;
  color: var(--xb-muted);
  font: 10px ui-monospace, monospace;
}
.queue-ops {
  flex: 0 0 auto;
  display: flex;
  gap: 1px;
  opacity: 0;
  transition: opacity 0.18s ease;
}
.queue-row:hover .queue-ops,
.queue-row.current .queue-ops {
  opacity: 1;
}
.queue-ops button {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
}
.queue-ops button:hover:not(:disabled) {
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
}
.queue-ops button:disabled {
  opacity: 0.25;
  cursor: default;
}
.queue-empty {
  height: 100%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--xb-muted);
  text-align: center;
}
.queue-empty .el-icon {
  font-size: 34px;
  color: var(--xb-primary);
  opacity: 0.6;
}
.queue-empty strong {
  color: var(--xb-text);
}
.queue-empty span {
  max-width: 220px;
  font-size: 12px;
  line-height: 1.6;
}
.queue-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  color: var(--xb-muted);
  font-size: 12px;
}
.queue-clear {
  border: 0;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  padding: 6px 8px;
}
.queue-clear:hover:not(:disabled) {
  color: var(--xb-accent);
}
.queue-clear:disabled {
  opacity: 0.4;
  cursor: default;
}
.eq {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 12px;
}
.eq i {
  width: 2px;
  height: 100%;
  background: var(--xb-primary);
  animation: eq-bounce 0.9s ease-in-out infinite;
}
.eq i:nth-child(2) {
  animation-delay: 0.15s;
}
.eq i:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes eq-bounce {
  0%,
  100% {
    transform: scaleY(0.35);
  }
  50% {
    transform: scaleY(1);
  }
}
.queue-fade-enter-active,
.queue-fade-leave-active {
  transition: opacity 0.22s ease;
}
.queue-fade-enter-from,
.queue-fade-leave-to {
  opacity: 0;
}
.queue-fade-enter-active .queue-panel,
.queue-fade-leave-active .queue-panel {
  transition: transform 0.24s ease;
}
.queue-fade-enter-from .queue-panel,
.queue-fade-leave-to .queue-panel {
  transform: translateX(24px);
}
@media (max-width: 720px) {
  .queue-panel {
    width: 100vw;
    padding: 18px 14px 12px;
  }
  .queue-mode span {
    display: none;
  }
}
</style>
