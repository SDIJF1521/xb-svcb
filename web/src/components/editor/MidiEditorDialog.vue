<template>
  <!-- teleport 到 body：页面主体本身有 z-index 堆叠上下文，留在里面会被顶栏压住 -->
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="midi-mask"
      :class="{ fullscreen: maximized }"
      @click.self="close"
    >
      <div
        class="midi-dialog"
        :class="{ 'is-compose': isCompose, fullscreen: maximized }"
        role="dialog"
        aria-label="MIDI 编辑器"
      >
      <header class="midi-head">
        <div class="midi-title">
          <p class="eyebrow">// MIDI {{ isCompose ? 'Composer' : 'Pitch Editor' }}</p>
          <h2>
            {{ isCompose ? t('MIDI 编曲') : t('MIDI 音高编辑器') }}
            <span class="midi-scope" :class="isCompose ? 'compose' : scope">
              {{ isCompose ? `${partCount} ${t('声部')}` : scope === 'track' ? t('轨道') : t('片段') }}
            </span>
          </h2>
          <p class="midi-sub">
            <template v-if="isCompose">
              {{ trackName || t('未命名音轨') }} · {{ formatClock(duration) }} · {{ totalNotes }} {{ t('个音符') }}
              <template v-if="!hasAudio"> · {{ t('空白轨道也可以直接写') }}</template>
            </template>
            <template v-else>
              {{ scope === 'track' ? trackName || t('未命名音轨') : clipName || t('未命名片段') }} ·
              {{ duration.toFixed(2) }}s · {{ draft.length }} {{ t('个音符') }}
              <template v-if="scope === 'track' && clipSpans.length">
                · {{ clipSpans.length }} {{ t('个片段分段') }}
              </template>
              <template v-if="analysisText"> · {{ analysisText }}</template>
            </template>
          </p>
        </div>

        <div class="midi-modes">
          <button
            type="button"
            :class="{ active: isCompose }"
            :title="t('多乐器编曲：从零写谱，可直接生成音频与 .mid')"
            @click="setMode('compose')"
          >
            {{ t('MIDI 编曲') }}
          </button>
          <button
            type="button"
            :class="{ active: !isCompose }"
            :disabled="!hasAudio"
            :title="hasAudio ? t('修正这段演唱的音高（保存到音频）') : t('这条轨道还没有音频')"
            @click="setMode('pitch')"
          >
            {{ t('演唱音准') }}
          </button>
        </div>

        <div class="midi-head-actions">
          <button v-if="!isCompose" class="ghost" :disabled="loading || applying" @click="refresh">
            {{ t('重新分析') }}
          </button>
          <button class="ghost" :disabled="!canUndo" title="Ctrl+Z" @click="undo">{{ t('撤销') }}</button>
          <button class="ghost" :disabled="!canRedo" title="Ctrl+Shift+Z" @click="redo">{{ t('重做') }}</button>
          <button
            class="ghost"
            :class="{ active: maximized }"
            :title="maximized ? t('退出全屏（Esc）') : t('铺满整个窗口')"
            @click="toggleMaximized"
          >
            {{ maximized ? t('退出全屏') : t('全屏') }}
          </button>
          <button class="ghost" @click="close">{{ t('关闭') }}</button>
        </div>
      </header>

      <div class="midi-toolbar">
        <div class="midi-group midi-transport">
          <button
            class="ghost midi-play"
            :disabled="transportDisabled"
            :title="transportHint"
            @click="togglePlay"
          >
            {{ transportLabel }}
          </button>
          <button class="ghost" :disabled="transportDisabled" :title="t('停止')" @click="stopPlay">■</button>
          <button
            class="ghost"
            :class="{ active: loopEnabled }"
            :disabled="transportDisabled"
            :title="t('循环播放')"
            @click="toggleLoop"
          >
            {{ t('循环') }}
          </button>
          <span class="midi-clock" :title="isCompose ? t('小节:拍 + 时间') : t('播放头时间')">
            {{ clockLabel }}
          </span>
        </div>

        <template v-if="isCompose">
          <label class="midi-field">
            <span>BPM</span>
            <input
              :value="Math.round(session.tempo)"
              type="number"
              :min="COMPOSE_MIN_TEMPO"
              :max="COMPOSE_MAX_TEMPO"
              step="1"
              @change="applyTempo"
            />
          </label>
          <label class="midi-field">
            <span>{{ t('拍号') }}</span>
            <select :value="timeSignatureLabel(session.time_signature)" @change="applySignature">
              <option v-for="option in signatureOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="midi-field">
            <span>{{ t('时长') }}</span>
            <input
              :value="durationSeconds > 0 ? durationSeconds : Math.round(duration)"
              type="number"
              min="1"
              max="86400"
              step="1"
              :title="t('时间轴长度（秒），留空或 0 为自动')"
              @change="applyDuration"
            />
            <em>{{ t('秒') }}</em>
          </label>
        </template>

        <label class="midi-field">
          <span>{{ t('网格') }}</span>
          <select v-if="isCompose" v-model="gridDivisionId">
            <option v-for="option in GRID_DIVISIONS" :key="option.id" :value="option.id">
              {{ option.label }}
            </option>
          </select>
          <select v-else v-model.number="pitchGrid">
            <option v-for="option in gridOptions" :key="option" :value="option">
              {{ formatGrid(option) }}
            </option>
          </select>
        </label>

        <label v-if="isCompose" class="midi-field">
          <span>{{ t('量化强度') }}</span>
          <input v-model.number="quantizeStrength" type="range" min="0" max="1" step="0.05" />
          <b>{{ Math.round(quantizeStrength * 100) }}%</b>
        </label>

        <div class="midi-group midi-zoom" :title="t('Ctrl+滚轮：横向缩放；Ctrl+Shift+滚轮：音域缩放')">
          <button class="ghost mini" :title="t('横向缩小 (-)')" @click="zoomTime(0.8)">－</button>
          <label class="midi-field">
            <span>{{ t('缩放') }}</span>
            <input v-model.number="pxPerSecond" type="range" min="12" max="800" step="2" />
            <b>{{ Math.round(pxPerSecond) }}px/s</b>
          </label>
          <button class="ghost mini" :title="t('横向放大 (+)')" @click="zoomTime(1.25)">＋</button>
          <label class="midi-field">
            <span>{{ t('音域') }}</span>
            <input v-model.number="rowHeight" type="range" min="8" max="40" step="1" />
            <b>{{ rowHeight }}px</b>
          </label>
        </div>

        <div class="midi-group">
          <button class="ghost" :title="t('放大到选区')" @click="zoomToSelection">{{ t('放大到选区') }}</button>
          <button class="ghost" @click="zoomToFit">{{ t('适应宽度') }}</button>
        </div>

        <div v-if="isCompose" class="midi-group midi-tools">
          <button
            v-for="tool in tools"
            :key="tool.id"
            class="ghost"
            :class="{ active: currentTool === tool.id }"
            :title="tool.hint"
            @click="currentTool = tool.id"
          >
            {{ tool.label }}
          </button>
          <label class="midi-field midi-toggle" :title="t('新建/选中音符时用振荡器发一个提示音')">
            <input v-model="notePreview" type="checkbox" />
            <span>{{ t('点击试听') }}</span>
          </label>
        </div>

        <label v-if="!isCompose" class="midi-field">
          <span>{{ t('音准偏移') }}</span>
          <input
            :value="primaryPitchNote?.detune ?? 0"
            type="number"
            min="-99"
            max="99"
            step="1"
            :disabled="!selection.length"
            @change="setSelectionDetune($event)"
          />
          <em>{{ t('音分') }}</em>
        </label>

        <div v-if="!isCompose" class="midi-group">
          <button class="ghost" :disabled="!selection.length" title="Ctrl+Q" @click="quantizeSelection">
            {{ t('量化') }}
          </button>
          <button class="ghost" :disabled="!selection.length" title="Alt+↑" @click="transposeSelection(1)">
            +1
          </button>
          <button class="ghost" :disabled="!selection.length" title="Alt+↓" @click="transposeSelection(-1)">
            -1
          </button>
          <button class="ghost" :disabled="!selection.length" @click="transposeSelection(12)">+12</button>
          <button class="ghost" :disabled="!selection.length" @click="transposeSelection(-12)">-12</button>
        </div>

        <span class="midi-hint">{{ hintText }}</span>
      </div>

      <p v-if="errorText" class="midi-error">{{ errorText }}</p>
      <p v-else-if="!isCompose && scope === 'track' && !clipSpans.length" class="midi-tip">
        {{ t('这条音轨还是空的：切到「MIDI 编曲」直接写谱，渲染后会自动生成音频。') }}
      </p>
      <p v-else-if="isCompose && !hasAudio" class="midi-tip">
        {{ t('空白轨道：直接在下方钢琴卷帘上写音符，点「渲染为分乐器音轨」就会生成可播放的音频。') }}
      </p>

      <div class="midi-workspace">
        <aside v-if="isCompose" class="midi-parts">
          <header class="midi-parts-head">
            <span>{{ t('声部 · 乐器') }}</span>
            <button class="ghost mini" :title="t('新增声部')" @click="addPart">＋</button>
          </header>
          <div class="midi-part-list">
            <div
              v-for="part in parts"
              :key="part.id"
              class="midi-part"
              :class="{ active: part.id === activePartId, muted: part.mute }"
              @click="selectPart(part.id)"
            >
              <span class="midi-part-color" :style="{ background: part.color }"></span>
              <input
                v-model="part.name"
                class="midi-part-name"
                maxlength="24"
                @change="touchDirty"
                @keydown.stop
                @click.stop
              />
              <button
                class="mini"
                :class="{ active: part.mute }"
                :title="t('静音')"
                @click.stop="toggleMute(part)"
              >
                M
              </button>
              <button
                class="mini"
                :class="{ active: part.solo }"
                :title="t('独奏')"
                @click.stop="toggleSolo(part)"
              >
                S
              </button>
              <button class="mini danger" :title="t('删除声部')" @click.stop="removePart(part)">×</button>
              <select
                class="midi-part-inst"
                :value="part.drum ? 'drum' : String(part.instrument)"
                :title="part.drum ? t('架子鼓 · GM 鼓组') : instrumentLabel(part.instrument)"
                @change="onInstrumentChange(part, $event)"
                @click.stop
                @keydown.stop
              >
                <option value="drum">{{ t('架子鼓 · GM 鼓组') }}</option>
                <optgroup v-for="group in instrumentGroups" :key="group.id" :label="group.label">
                  <option v-for="item in group.options" :key="item.program" :value="String(item.program)">
                    {{ item.name }}
                  </option>
                </optgroup>
              </select>
              <button
                v-if="part.drum"
                class="mini"
                :title="t('填充 4/4 基本节奏（底鼓/军鼓/八分踩镲）')"
                @click.stop="fillDrumBeat(part)"
              >
                {{ t('填充节奏') }}
              </button>
              <button class="mini" :title="t('导入 .mid 到这个声部')" @click.stop="importMidiToPart(part)">
                ⇩ MIDI
              </button>
              <span class="midi-part-count">
                <template v-if="part.drum">{{ part.notes.length }} {{ t('件') }}</template>
                <template v-else>{{ part.notes.length }} {{ t('个音') }}</template>
              </span>
            </div>
          </div>
          <footer class="midi-parts-foot">
            <button class="ghost mini" @click="addPart">＋ {{ t('新声部') }}</button>
            <button class="ghost mini" @click="addDrumPart">＋ {{ t('鼓组') }}</button>
            <button class="ghost mini" @click="emit('import-session')">{{ t('导入 .mid') }}</button>
          </footer>
        </aside>

        <div ref="bodyRef" class="midi-roll-wrap">
          <div v-if="busy" class="midi-busy">{{ busyText }}</div>
          <div v-else-if="!hasContent" class="midi-empty">
            <template v-if="isCompose">
              {{ t('还没有音符。用「画笔」在网格上拖出新音符，或双击空白处；空白轨道也能直接开始编曲。') }}
            </template>
            <template v-else>{{ t('还没有音符。双击网格新建，或点“重新分析”从音频里提取。') }}</template>
          </div>
          <div
            ref="scrollRef"
            class="midi-scroll"
            :class="{ 'with-velocity': showVelocity }"
            @scroll="onScroll"
          >
            <div class="midi-filler" :style="{ width: `${totalWidth}px`, height: `${totalHeight}px` }">
              <div
                class="midi-view"
                :style="{ width: `${keyWidth + viewWidth}px`, height: `${viewHeight}px` }"
              >
                <canvas
                  ref="keyCanvasRef"
                  class="midi-keys"
                  :width="keyWidth * dpr"
                  :height="viewHeight * dpr"
                  :style="{ width: `${keyWidth}px`, height: `${viewHeight}px` }"
                />
                <canvas
                  ref="gridCanvasRef"
                  class="midi-grid"
                  :width="viewWidth * dpr"
                  :height="viewHeight * dpr"
                  :style="{ width: `${viewWidth}px`, height: `${viewHeight}px` }"
                  @pointerdown="onPointerDown"
                  @pointermove="onPointerMove"
                  @pointerup="onPointerUp"
                  @pointercancel="onPointerUp"
                  @pointerleave="onPointerLeave"
                  @dblclick="onDoubleClick"
                  @contextmenu.prevent="onContextMenu"
                  @wheel="onWheel"
                />
              </div>
            </div>
          </div>

          <canvas
            v-if="showVelocity"
            ref="velocityCanvasRef"
            class="midi-velocity"
            :width="viewWidth * dpr"
            :height="velocityHeight * dpr"
            :style="{ left: `${keyWidth}px`, width: `${viewWidth}px`, height: `${velocityHeight}px` }"
            @pointerdown="onVelocityDown"
            @pointermove="onVelocityMove"
            @pointerup="onVelocityUp"
            @pointercancel="onVelocityUp"
          />

          <div
            v-if="contextMenu.visible"
            ref="menuRef"
            class="midi-menu"
            :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
            role="menu"
            @pointerdown.stop
            @contextmenu.prevent
          >
            <button type="button" role="menuitem" @click="menuAddNote">{{ t('在此添加音符') }}</button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuDelete">
              {{ t('删除选中') }} ({{ selection.length }})
            </button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuCopy">
              {{ t('复制') }} (Ctrl+C)
            </button>
            <button type="button" role="menuitem" :disabled="!hasClipboard" @click="menuPaste">
              {{ t('在指针处粘贴') }} (Ctrl+V)
            </button>
            <i class="midi-menu-sep" aria-hidden="true"></i>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuQuantize">
              {{ t('量化到网格') }} (Ctrl+Q)
            </button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuTranspose(1)">
              {{ t('升高半音') }} (Alt+↑)
            </button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuTranspose(-1)">
              {{ t('降低半音') }} (Alt+↓)
            </button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuTranspose(12)">
              {{ t('升高八度') }} (Shift+↑)
            </button>
            <button type="button" role="menuitem" :disabled="!selection.length" @click="menuTranspose(-12)">
              {{ t('降低八度') }} (Shift+↓)
            </button>
            <template v-if="isCompose">
              <i class="midi-menu-sep" aria-hidden="true"></i>
              <button type="button" role="menuitem" :disabled="!selection.length" @click="menuVelocity(1.1)">
                {{ t('力度') }} +10%
              </button>
              <button type="button" role="menuitem" :disabled="!selection.length" @click="menuVelocity(0.9)">
                {{ t('力度') }} -10%
              </button>
              <button type="button" role="menuitem" :disabled="!selection.length" @click="menuLegato">
                {{ t('连奏（接上后一个音）') }}
              </button>
              <button type="button" role="menuitem" :disabled="!selection.length" @click="menuSplitAtPlayhead">
                {{ t('在播放头切开') }}
              </button>
              <button type="button" role="menuitem" :disabled="!selection.length" @click="menuDuplicate">
                {{ t('复制到后面') }} (Ctrl+D)
              </button>
            </template>
            <i class="midi-menu-sep" aria-hidden="true"></i>
            <button type="button" role="menuitem" @click="menuSelectAll">{{ t('全选') }} (Ctrl+A)</button>
            <button type="button" role="menuitem" :disabled="!canUndo" @click="menuUndo">{{ t('撤销') }} (Ctrl+Z)</button>
            <button type="button" role="menuitem" :disabled="!canRedo" @click="menuRedo">{{ t('重做') }} (Ctrl+Shift+Z)</button>
          </div>
        </div>
      </div>

      <footer class="midi-foot">
        <div class="midi-selected">
          <template v-if="selection.length > 1">
            {{ t('已选') }} {{ selection.length }} {{ t('个音符') }}
            <template v-if="isCompose">
              · {{ t('力度') }} {{ selectionVelocityRange }}
            </template>
            <template v-else> · {{ noteName(primaryNote?.pitch ?? 60) }} {{ t('等') }}</template>
          </template>
          <template v-else-if="primaryNote">
            <b>{{ noteLabel(primaryNote.pitch) }}</b>
            <span>{{ primaryNote.start.toFixed(3) }}s → {{ primaryNote.end.toFixed(3) }}s</span>
            <span>{{ t('长度') }} {{ (primaryNote.end - primaryNote.start).toFixed(3) }}s</span>
            <span v-if="isCompose">{{ t('力度') }} {{ primaryNote.velocity }}</span>
            <span v-else-if="primaryPitchNote?.detune">
              {{ t('原始音准') }} {{ primaryPitchNote.detune > 0 ? '+' : '' }}{{ primaryPitchNote.detune.toFixed(1) }} {{ t('音分') }}
            </span>
          </template>
          <span v-else>{{ t('未选中音符') }}</span>
          <span v-if="isCompose" class="midi-dirty">{{ dirty ? t('· 未保存') : t('· 已同步') }}</span>
        </div>

        <div class="midi-actions">
          <template v-if="isCompose">
            <button class="ghost" :disabled="!hasContent" @click="resetDraft">{{ t('还原本次编辑') }}</button>
            <button class="ghost" :disabled="busy || !hasContent" @click="emitSaveSession">
              {{ t('保存编曲') }}
            </button>
            <button class="ghost" :disabled="busy || !hasContent" :title="previewTitle" @click="requestPreview">
              {{ t('试听编曲') }}
            </button>
            <button class="ghost" :disabled="busy || !hasContent" @click="emitRender('mix')">
              {{ busyAction === 'mix' ? t('渲染中…') : t('渲染到本轨') }}
            </button>
            <button class="ghost" @click="emitExport">{{ t('导出 .mid') }}</button>
            <button class="primary" :disabled="busy || !hasContent" @click="emitRender('tracks')">
              {{ busyAction === 'tracks' ? t('渲染中…') : t('渲染为分乐器音轨') }}
            </button>
          </template>
          <template v-else>
            <button class="ghost" :disabled="!draft.length" @click="resetDraft">{{ t('还原本次编辑') }}</button>
            <button class="ghost" :disabled="loading || applying || !draft.length" @click="emitSave">
              {{ t('保存音符') }}
            </button>
            <button class="ghost" :disabled="loading || !canPreview" :title="previewHint" @click="emitPreview">
              {{ t('试听音频') }}
            </button>
            <button
              class="primary"
              :disabled="loading || applying || !draft.length || !ready || !canApply"
              :title="applyHint"
              @click="emitApply"
            >
              {{ applying ? t('应用音频中…') : scope === 'track' ? t('应用到轨道片段') : t('应用音频') }}
            </button>
          </template>
        </div>
      </footer>

      <p class="midi-note">
        <template v-if="isCompose">
          {{ t('渲染使用内置多乐器合成器：每个声部一件 GM 乐器，可「分乐器各生成一条音轨」（可单独调音量/加效果），也可混成一条片段落回当前轨。导出 .mid 可在其他 DAW 里继续编辑；试听播放的是合成结果。') }}
        </template>
        <template v-else>
          {{ t('试听播放的是片段音频本身（应用后为编辑结果），不会用 MIDI 音源直接出声；应用会生成新音频并可撤销。未改动的音符保留原始音准，只有被拖动/改过分度的音符才会移动。') }}
        </template>
      </p>

      <audio
        ref="audioEl"
        class="midi-audio"
        :src="previewUrl || undefined"
        preload="auto"
        @pause="onAudioPause"
        @play="onAudioPlay"
        @ended="onAudioEnded"
      ></audio>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api } from '@/api'
import { translateUiText } from '@/i18n'
import type {
  EditorMidiInstrument,
  EditorMidiInstrumentFamily,
} from '@/api/types'
import {
  COMPOSE_MAX_TEMPO,
  COMPOSE_MIN_TEMPO,
  MIDI_GRID_OPTIONS,
  MIDI_MIN_NOTE_PX,
  type MidiComposeNote,
  type MidiNote,
  type MidiPart,
  type MidiSession,
  GM_FAMILIES,
  GM_INSTRUMENTS,
  DRUM_PITCH_MAX,
  DRUM_PITCH_MIN,
  DRUM_DEFAULT_PITCH,
  basicDrumBeat,
  drumName,
  drumPiece,
  isDrumPitch,
  nearestDrumPitch,
  GRID_DIVISIONS,
  TIME_SIGNATURE_CHOICES,
  barBeatLabel,
  barSeconds,
  clampNoteSpan,
  clampTime,
  clampComposePitch,
  clampDetune,
  clampPitch,
  clampTempo,
  clampVelocity,
  composeNoteAtPoint,
  copyNotes,
  createComposeNote,
  createNote,
  createPart,
  duplicateNotes,
  clampProgram,
  instrumentName,
  fitZoom,
  gridStepSeconds,
  humanizeNotes,
  isBlackKey,
  isPartAudible,
  legatoNotes,
  moveComposeNotes,
  moveNotes,
  normalizeNotes,
  normalizeSession,
  MIN_RESIZE_PX,
  noteAtPoint,
  noteEdgeAt,
  noteName,
  noteRect,
  pasteNotes,
  pitchBounds,
  pitchToY,
  quantizeComposeNotes,
  quantizeNotes,
  resizeComposeNote,
  resizeNote,
  scaleNoteVelocity,
  secondsPerBeat,
  sessionNoteCount,
  sessionPitchRange,
  snapTime,
  sortNotes,
  splitNoteAt,
  timeSignatureLabel,
  timeToX,
  transposeNotes,
  velocityAlpha,
  xToTime,
  yToPitch,
} from '@/utils/midi'

const t = translateUiText

/** 声部名是不是默认名（空 / 「旋律」/「架子鼓」/「声部 N」等，含本地化后的写法）。 */
function isDefaultPartName(name: string): boolean {
  const value = String(name || '').trim()
  if (!value) return true
  if (value === t('旋律') || value === t('架子鼓')) return true
  return new RegExp(`^${t('声部')}\\s*\\d+$`).test(value)
}

interface ClipSpan {
  id: string
  name: string
  start: number
  end: number
}

type EditorMode = 'compose' | 'pitch'
type ToolId = 'draw' | 'select' | 'erase'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    mode?: EditorMode
    scope?: 'clip' | 'track'
    clipName?: string
    trackName?: string
    duration?: number
    hasAudio?: boolean
    clipSpans?: ClipSpan[]
    // 演唱音准模式
    notes?: MidiNote[]
    loading?: boolean
    applying?: boolean
    ready?: boolean
    error?: string
    analysis?: Record<string, unknown>
    playhead?: number
    playing?: boolean
    // MIDI 编曲模式
    composeSession?: MidiSession | null
    composeDuration?: number
    instruments?: EditorMidiInstrument[]
    families?: EditorMidiInstrumentFamily[]
    composeLoading?: boolean
    composeBusy?: boolean
    composeBusyAction?: string
    composeError?: string
    previewUrl?: string
    previewLoading?: boolean
  }>(),
  {
    mode: 'compose',
    scope: 'clip',
    clipName: '',
    trackName: '',
    duration: 0,
    hasAudio: false,
    clipSpans: () => [],
    notes: () => [],
    loading: false,
    applying: false,
    ready: true,
    error: '',
    analysis: () => ({}),
    playhead: -1,
    playing: false,
    composeSession: null,
    composeDuration: 0,
    instruments: () => [],
    families: () => [],
    composeLoading: false,
    composeBusy: false,
    composeBusyAction: '',
    composeError: '',
    previewUrl: '',
    previewLoading: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:mode': [mode: EditorMode]
  save: [notes: MidiNote[]]
  apply: [notes: MidiNote[]]
  refresh: []
  preview: []
  'save-session': [session: MidiSession]
  'render-session': [session: MidiSession, mode: 'tracks' | 'mix']
  'export-session': [session: MidiSession]
  'preview-session': [session: MidiSession]
  'import-session': []
}>()

const ROW_HEIGHT = 16
const KEY_WIDTH = 62
const RULER_HEIGHT = 34
const MIN_NOTE_LENGTH = 0.12
const VELOCITY_HEIGHT = 88
const gridOptions = MIDI_GRID_OPTIONS
const tools: Array<{ id: ToolId; label: string; hint: string }> = [
  { id: 'draw', label: t('画笔'), hint: t('空白处写音符 · 拖动移动 · 拖边缘改长度（D）') },
  { id: 'select', label: t('选择'), hint: t('框选/拖动/拖边缘改长度（V）') },
  { id: 'erase', label: t('橡皮'), hint: t('点掉音符（E）') },
]

const keyWidth = KEY_WIDTH
const rowHeight = ref<number>(ROW_HEIGHT)
const velocityHeight = VELOCITY_HEIGHT
const scrollRef = ref<HTMLDivElement | null>(null)
const bodyRef = ref<HTMLDivElement | null>(null)
const menuRef = ref<HTMLDivElement | null>(null)
const keyCanvasRef = ref<HTMLCanvasElement | null>(null)
const gridCanvasRef = ref<HTMLCanvasElement | null>(null)
const velocityCanvasRef = ref<HTMLCanvasElement | null>(null)
const audioEl = ref<HTMLAudioElement | null>(null)

const activeMode = ref<EditorMode>(props.mode)
const currentTool = ref<ToolId>('draw')
const selection = ref<string[]>([])
const pxPerSecond = ref(120)
const dpr = Math.max(1, Math.min(3, Math.round(window.devicePixelRatio || 1)))
const contextMenu = reactive({ visible: false, x: 0, y: 0, time: 0, pitch: 60 })
const cursorTime = ref(0)
const viewWidth = ref(760)
const viewHeight = ref(360)
const scrollLeft = ref(0)
const scrollTop = ref(0)
const gridDivisionId = ref('1/16')
const quantizeStrength = ref(1)
const loopEnabled = ref(false)
const dirty = ref(false)
const busyAction = ref('')
const previewPending = ref(false)
const previewTime = ref(0)
const pitchGrid = ref(0.1)
const playingState = ref(false)
const activePartId = ref('')
const notePreview = ref(true)
const maximized = ref(false)
/** 音符左右边缘的可抓取宽度（像素），与 utils/midi noteEdgeAt 默认值保持一致。 */
const EDGE_GRAB_PX = 8
/** 当前悬停的音符 id：用于画出「可拉伸」的边缘把手与抓取光标。 */
const hoveredNoteId = ref<string | null>(null)

// 演唱音准模式的草稿与历史
const draft = ref<MidiNote[]>([])
const pitchClipboard = ref<MidiNote[]>([])
const pitchUndo: MidiNote[][] = []
const pitchRedo: MidiNote[][] = []
const pitchUndoVersion = ref(0)

// 编曲模式的会话与历史
const session = ref<MidiSession>(normalizeSession(null, 60))
const composeClipboard = ref<Array<{ partId: string; note: MidiComposeNote }>>([])
const composeUndo: MidiSession[] = []
const composeRedo: MidiSession[] = []
const composeUndoVersion = ref(0)

let resizeObserver: ResizeObserver | null = null
let drawHandle = 0
let rafPlayhead = 0
const drag = ref<{
  mode: 'move' | 'start' | 'end' | 'marquee' | 'create' | 'velocity' | 'erase'
  originX: number
  originY: number
  baseAll: MidiNote[]
  baseSession: MidiSession | null
  partId: string
  ids: string[]
  pushed?: boolean
  createStart?: number
  createPitch?: number
  marqueeStart?: { x: number; y: number }
  marqueeEnd?: { x: number; y: number }
} | null>(null)

const isCompose = computed(() => activeMode.value === 'compose')
const showVelocity = computed(() => isCompose.value)
const busy = computed(() =>
  isCompose.value ? !!props.composeBusy || !!props.composeLoading : !!props.loading || !!props.applying,
)
const busyText = computed(() => {
  if (!isCompose.value) return props.loading ? t('正在分析片段基频…') : t('正在处理…')
  if (props.composeLoading) return t('正在读取 MIDI 编曲…')
  const action = props.composeBusyAction || busyAction.value
  if (action === 'tracks') return t('正在按乐器渲染音频…')
  if (action === 'mix') return t('正在渲染混合音频…')
  if (action === 'preview') return t('正在渲染试听…')
  if (action === 'save') return t('正在保存编曲…')
  return t('正在处理…')
})
const errorText = computed(() => (isCompose.value ? props.composeError : props.error))
// 用户手动填写的时间轴长度（秒）；0 表示自动（按工程/内容）。
const durationSeconds = ref(0)
const duration = computed(() => {
  const autoBase = isCompose.value
    ? Number(props.composeDuration) || Number(props.duration) || 600
    : Number(props.duration) || 0.05
  const base = durationSeconds.value > 0 ? durationSeconds.value : autoBase
  // 自动延伸：音符写到哪儿，时间轴就至少长到哪儿（末尾再留 8 秒余量）。
  let end = 0
  for (const part of session.value.parts || []) {
    for (const note of part.notes || []) end = Math.max(end, Number(note.end) || 0)
  }
  for (const note of draft.value) end = Math.max(end, Number(note.end) || 0)
  return Math.max(0.05, base, end > 0 ? end + 8 : 0)
})
const parts = computed<MidiPart[]>(() => session.value.parts || [])
const partCount = computed(() => parts.value.length)
const totalNotes = computed(() => sessionNoteCount(session.value))
const hasContent = computed(() =>
  isCompose.value ? totalNotes.value > 0 : draft.value.length > 0,
)
const pitchRange = computed(() => {
  if (!isCompose.value) return pitchBounds(draft.value)
  // 鼓组声部只显示整套鼓件（GM 35~81），别的音高在鼓组里没有意义。
  if (drumMode.value) return { min: DRUM_PITCH_MIN - 2, max: DRUM_PITCH_MAX + 2 }
  return sessionPitchRange(parts.value, 36, 96)
})
const rows = computed(() => pitchRange.value.max - pitchRange.value.min + 1)
const contentHeight = computed(() => rows.value * rowHeight.value + RULER_HEIGHT)
const totalWidth = computed(() =>
  Math.max(viewWidth.value, Math.round(duration.value * pxPerSecond.value)),
)
const totalHeight = computed(() => Math.max(viewHeight.value, contentHeight.value))
const snapStep = computed(() =>
  isCompose.value ? gridStepSeconds(session.value.tempo, gridDivisionId.value) : pitchGrid.value,
)
const activePart = computed(
  () => parts.value.find((part) => part.id === activePartId.value) || parts.value[0] || null,
)
/** 当前声部是不是架子鼓：鼓组模式下键列显示鼓件名、新音符吸附到真实鼓件。 */
const drumMode = computed(() => isCompose.value && !!activePart.value?.drum)
const drumPartIds = computed(
  () => new Set(parts.value.filter((part) => part.drum).map((part) => part.id)),
)
const signatureOptions = TIME_SIGNATURE_CHOICES.map((item) => ({
  value: `${item[0]}/${item[1]}`,
  label: `${item[0]}/${item[1]}`,
}))
/**
 * 乐器选择器：后端目录优先，缺失时用内嵌的 128 GM 表兜底。
 * 无论走哪条路径，显示的都是具体乐器名（不会出现「钢琴 1」这种编号占位）。
 */
const instrumentGroups = computed(() => {
  const names = new Map<number, string>()
  for (const item of GM_INSTRUMENTS) names.set(item.program, item.name_zh)
  for (const item of props.instruments || []) {
    if (Number.isFinite(item.program)) names.set(item.program, item.name_zh || item.name_en)
  }
  const families = props.families?.length
    ? props.families.map((family) => ({
        id: family.id,
        label: family.name_zh || family.name_en,
        programs: family.programs || [],
      }))
    : GM_FAMILIES.map((family) => ({
        id: family.id,
        label: family.name,
        programs: family.programs,
      }))
  return families
    .map((family) => ({
      id: family.id,
      label: family.label,
      options: family.programs
        .map((program) => ({
          program,
          name: names.get(program) || instrumentName(program),
        }))
        .filter((item) => Number.isFinite(item.program)),
    }))
    .filter((family) => family.options.length > 0)
})
const velocitySelection = computed(() => {
  const ids = new Set(selection.value)
  const values: number[] = []
  for (const part of parts.value) {
    for (const note of part.notes) if (ids.has(note.id)) values.push(note.velocity)
  }
  return values
})
const selectionVelocityRange = computed(() => {
  const values = velocitySelection.value
  if (!values.length) return '-'
  const low = Math.min(...values)
  const high = Math.max(...values)
  return low === high ? `${low}` : `${low}~${high}`
})

const pitchNoteMap = computed(() => new Map(draft.value.map((note) => [note.id, note])))
const primaryPitchNote = computed(() => {
  for (let index = selection.value.length - 1; index >= 0; index -= 1) {
    const found = pitchNoteMap.value.get(selection.value[index]!)
    if (found) return found
  }
  return null
})
const primaryComposeNote = computed(() => {
  for (let index = selection.value.length - 1; index >= 0; index -= 1) {
    const found = locateNote(selection.value[index]!)
    if (found) return found.note
  }
  return null
})
const primaryNote = computed(() =>
  isCompose.value
    ? primaryComposeNote.value
    : (primaryPitchNote.value as unknown as MidiComposeNote | null),
)

const transportDisabled = computed(() => (isCompose.value ? !hasContent.value : !canPreview.value))
const transportHint = computed(() => {
  if (isCompose.value) return hasContent.value ? t('用内置乐器渲染并播放') : t('还没有音符')
  return canPreview.value ? t('播放片段音频（不是 MIDI 音源）') : t('空白轨道没有音频可试听')
})
const previewTitle = computed(() => {
  if (props.previewLoading) return t('正在渲染试听…')
  return hasContent.value ? t('用内置乐器渲染并播放') : t('还没有音符')
})
const playing = computed(() => (isCompose.value ? playingState.value : props.playing))
const transportLabel = computed(() => {
  if (isCompose.value && props.previewLoading) return t('渲染试听…')
  return playing.value ? t('⏸ 暂停') : t('▶ 试听')
})
const playheadSeconds = computed(() => (isCompose.value ? previewTime.value : props.playhead))
const clockLabel = computed(() => {
  const seconds = Math.max(0, playheadSeconds.value)
  if (isCompose.value) {
    return `${barBeatLabel(seconds, session.value.tempo, session.value.time_signature)} · ${formatClock(seconds)}`
  }
  return formatClock(seconds)
})
const hintText = computed(() =>
  isCompose.value
    ? t('D 画笔 / V 选择 / E 橡皮 · 双击新建 · 拖音符移动 · 拖边缘改长度 · [ ] 伸缩 · 下方拖力度条 · 空格试听 · Del 删除')
    : t('双击空白新建 · 拖动移动 · 拖边缘改长度 · 框选多选 · 右键菜单 · Del 删除 · 空格试听'),
)
const canUndo = computed(() =>
  isCompose.value ? composeUndo.length > 0 : pitchUndoVersion.value >= 0 && pitchUndo.length > 0,
)
const canRedo = computed(() =>
  isCompose.value ? composeRedo.length > 0 : pitchUndoVersion.value >= 0 && pitchRedo.length > 0,
)
const hasClipboard = computed(() =>
  isCompose.value ? composeClipboard.value.length > 0 : pitchClipboard.value.length > 0,
)
const canPreview = computed(() => (props.scope === 'track' ? props.clipSpans.length > 0 : true))
const canApply = computed(() => (props.scope === 'track' ? props.clipSpans.length > 0 : true))
const applyHint = computed(() => {
  if (!props.ready) return t('MIDI 音高重绘环境未就绪')
  if (!canApply.value) return t('音轨上还没有片段：先切到「MIDI 编曲」写谱并渲染')
  return props.scope === 'track' ? t('把音符按片段切分后落到音频') : t('把音符应用到音频（保共振峰移调）')
})
const previewHint = computed(() =>
  canPreview.value ? t('播放片段音频（不是 MIDI 音源）') : t('空白轨道没有音频可试听'),
)
const analysisText = computed(() => {
  const data = props.analysis || {}
  const chunks: string[] = []
  const median = Number(data.median_hz ?? 0)
  if (median > 0) chunks.push(`${t('中位基频')} ${median.toFixed(1)}Hz`)
  const voiced = Number(data.voiced_ratio ?? 0)
  if (voiced > 0) chunks.push(`${t('浊音')} ${Math.round(voiced * 100)}%`)
  if (data.empty_track) chunks.push(t('空白轨道'))
  return chunks.join(' · ')
})

/* ---------------------------------------------------------------- 初始化与同步 */

watch(
  () => props.mode,
  (mode) => {
    if (mode !== activeMode.value) setMode(mode)
  },
)

watch(
  () => props.notes,
  (notes) => {
    draft.value = (notes || []).map((note) => ({ ...note }))
    selection.value = []
    pitchUndo.length = 0
    pitchRedo.length = 0
    pitchUndoVersion.value += 1
    fitZoomToWidth()
    nextTick(draw)
  },
  { immediate: true, deep: true },
)

watch(
  () => props.composeSession,
  (value) => {
    if (!value) return
    durationSeconds.value = 0
    session.value = normalizeSession(value, duration.value)
    if (!session.value.parts.some((part) => part.id === activePartId.value)) {
      activePartId.value = session.value.parts[0]?.id || ''
    }
    selection.value = []
    composeUndo.length = 0
    composeRedo.length = 0
    composeUndoVersion.value += 1
    dirty.value = false
    fitZoomToWidth()
    nextTick(draw)
  },
  { immediate: true, deep: false },
)

watch(
  () => props.modelValue,
  (open) => {
    lockPageScroll(open)
    if (!open) {
      maximized.value = false
      drag.value = null
      hoveredNoteId.value = null
      contextMenu.visible = false
      stopPlay()
      return
    }
    nextTick(() => {
      if (resizeObserver) {
        resizeObserver.disconnect()
        if (scrollRef.value) resizeObserver.observe(scrollRef.value)
      }
      measureViewport()
      fitZoomToWidth()
      draw()
    })
  },
)

/** 打开时锁住页面滚动：全屏编辑器里滚轮只应该滚钢琴卷帘。 */
function lockPageScroll(lock: boolean) {
  if (typeof document === 'undefined') return
  document.body.style.overflow = lock ? 'hidden' : ''
}

watch(
  [() => session.value, selection, () => pxPerSecond.value, () => rowHeight.value, showVelocity],
  () => scheduleDraw(),
  { deep: true },
)
watch(
  [draft, () => pxPerSecond.value, () => rowHeight.value, () => props.playhead, () => props.playing],
  () => scheduleDraw(),
  { deep: true },
)
watch(previewTime, () => scheduleDraw())
watch(hoveredNoteId, () => scheduleDraw())

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('pointerdown', onWindowPointerDown, true)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      measureViewport()
      scheduleDraw()
    })
    if (scrollRef.value) resizeObserver.observe(scrollRef.value)
  }
  nextTick(() => {
    measureViewport()
    fitZoomToWidth()
    draw()
  })
})

onBeforeUnmount(() => {
  lockPageScroll(false)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('pointerdown', onWindowPointerDown, true)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (drawHandle) window.cancelAnimationFrame(drawHandle)
  if (rafPlayhead) window.cancelAnimationFrame(rafPlayhead)
  drawHandle = 0
  rafPlayhead = 0
  if (audioContext) {
    void audioContext.close().catch(() => undefined)
    audioContext = null
  }
})

function setMode(mode: EditorMode) {
  if (mode === 'pitch' && !props.hasAudio) return
  activeMode.value = mode
  selection.value = []
  hoveredNoteId.value = null
  emit('update:mode', mode)
  nextTick(() => {
    measureViewport()
    fitZoomToWidth()
    draw()
  })
}

function formatClock(seconds: number) {
  const total = Math.max(0, seconds)
  const minutes = Math.floor(total / 60)
  const rest = total - minutes * 60
  return `${minutes}:${rest.toFixed(2).padStart(5, '0')}`
}

function formatGrid(value: number) {
  return `${Math.round(value * 1000)}ms`
}

function noteLabel(pitch: number) {
  return drumMode.value ? drumName(pitch) : noteName(pitch)
}

/* ---------------------------------------------------------------- 点击试听（WebAudio 提示音） */

let audioContext: AudioContext | null = null

function ensureAudioContext(): AudioContext | null {
  try {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    audioContext = audioContext || new Ctor()
    if (audioContext.state === 'suspended') void audioContext.resume()
    return audioContext
  } catch {
    return null
  }
}

/** 新建/选中音符时发一个短提示音：旋律用三角波，鼓组按鼓件类型发真实鼓声。 */
function playBlip(pitch: number, velocity = 100) {
  if (!notePreview.value || !isCompose.value) return
  if (drumMode.value) {
    playDrumBlip(pitch, velocity)
    return
  }
  const context = ensureAudioContext()
  if (!context) return
  try {
    const now = context.currentTime
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.type = 'triangle'
    oscillator.frequency.value = 440 * 2 ** ((clampComposePitch(pitch) - 69) / 12)
    const peak = Math.max(0.02, Math.min(0.22, (velocity / 127) * 0.2))
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(peak, now + 0.012)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.2)
    oscillator.connect(gain)
    gain.connect(context.destination)
    oscillator.start(now)
    oscillator.stop(now + 0.24)
  } catch {
    // 没有音频输出设备时静默失败即可，不影响编辑。
  }
}

/** 鼓组点按试听：底鼓用正弦下扫、军鼓/小打用噪声、踩镲/镲片用高频噪声。 */
function playDrumBlip(pitch: number, velocity = 110) {
  const context = ensureAudioContext()
  if (!context) return
  const piece = drumPiece(pitch) || drumPiece(nearestDrumPitch(pitch))
  const group = piece?.group || 'snare'
  const level = Math.max(0.05, Math.min(0.5, (velocity / 127) * 0.45))
  try {
    const now = context.currentTime
    const gain = context.createGain()
    gain.connect(context.destination)
    const stop = (duration: number) => {
      gain.gain.setValueAtTime(0.0001, now)
      gain.gain.exponentialRampToValueAtTime(level, now + 0.004)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration)
    }

    if (group === 'kick') {
      const oscillator = context.createOscillator()
      oscillator.type = 'sine'
      oscillator.frequency.setValueAtTime(150, now)
      oscillator.frequency.exponentialRampToValueAtTime(46, now + 0.12)
      oscillator.connect(gain)
      stop(0.26)
      oscillator.start(now)
      oscillator.stop(now + 0.28)
      return
    }

    if (group === 'tom') {
      const oscillator = context.createOscillator()
      oscillator.type = 'sine'
      const base = 90 + (nearestDrumPitch(pitch) - 41) * 12
      oscillator.frequency.setValueAtTime(base * 1.4, now)
      oscillator.frequency.exponentialRampToValueAtTime(base, now + 0.1)
      oscillator.connect(gain)
      stop(0.3)
      oscillator.start(now)
      oscillator.stop(now + 0.32)
      return
    }

    // 军鼓 / 踩镲 / 镲片 / 小打：短噪声
    const duration =
      group === 'crash' || group === 'ride' ? 0.5 : group === 'hat_open' ? 0.26 : group === 'hat' ? 0.06 : 0.16
    const frames = Math.max(1, Math.floor(context.sampleRate * duration))
    const buffer = context.createBuffer(1, frames, context.sampleRate)
    const data = buffer.getChannelData(0)
    for (let index = 0; index < frames; index += 1) {
      data[index] = (Math.random() * 2 - 1) * (1 - index / frames)
    }
    const source = context.createBufferSource()
    source.buffer = buffer
    const filter = context.createBiquadFilter()
    filter.type = group === 'hat' || group === 'hat_open' || group === 'crash' || group === 'ride'
      ? 'highpass'
      : 'bandpass'
    filter.frequency.value = group === 'snare' || group === 'clap' || group === 'rim' ? 1800 : 6500
    source.connect(filter)
    filter.connect(gain)
    stop(duration)
    source.start(now)
  } catch {
    // 忽略音频错误：编辑不受影响。
  }
}

function instrumentLabel(program: number) {
  const found = (props.instruments || []).find((item) => item.program === program)
  return found?.name_zh || instrumentName(program)
}

/* ---------------------------------------------------------------- 视口与缩放 */

function measureViewport() {
  const el = scrollRef.value
  if (!el) return
  viewWidth.value = Math.max(200, el.clientWidth - KEY_WIDTH)
  viewHeight.value = Math.max(140, el.clientHeight)
  scrollLeft.value = el.scrollLeft
  scrollTop.value = el.scrollTop
  const canvas = velocityCanvasRef.value
  if (canvas && showVelocity.value) {
    canvas.width = viewWidth.value * dpr
    canvas.height = velocityHeight * dpr
  }
}

function onScroll() {
  const el = scrollRef.value
  if (!el) return
  scrollLeft.value = el.scrollLeft
  scrollTop.value = el.scrollTop
  scheduleDraw()
}

/** Ctrl/⌘ + 滚轮：以指针为锚点横向缩放；再加 Shift 则缩放音域（行高）。 */
function onWheel(event: WheelEvent) {
  if (!(event.ctrlKey || event.metaKey)) return
  const canvas = gridCanvasRef.value
  if (!canvas) return
  event.preventDefault()
  const factor = event.deltaY < 0 ? 1.25 : 0.8
  if (event.shiftKey) {
    zoomPitch(factor)
    return
  }
  const rect = canvas.getBoundingClientRect()
  const pointerX = (event.clientX - rect.left) * (viewWidth.value / Math.max(1, rect.width))
  const anchorTime = (scrollLeft.value + pointerX) / Math.max(1, pxPerSecond.value)
  const next = Math.min(800, Math.max(12, Math.round(pxPerSecond.value * factor)))
  pxPerSecond.value = next
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollLeft = Math.max(0, anchorTime * next - pointerX)
    measureViewport()
    scheduleDraw()
  })
}

/** 横向缩放（以视口中心为锚点），给工具栏的 ＋/－ 与键盘 +/- 用。 */
function zoomTime(factor: number) {
  const el = scrollRef.value
  const centre = viewWidth.value / 2
  const anchorTime = el ? (el.scrollLeft + centre) / Math.max(1, pxPerSecond.value) : 0
  const next = Math.min(800, Math.max(12, Math.round(pxPerSecond.value * factor)))
  if (next === pxPerSecond.value) return
  pxPerSecond.value = next
  nextTick(() => {
    if (el) el.scrollLeft = Math.max(0, anchorTime * next - centre)
    measureViewport()
    scheduleDraw()
  })
}

/** 纵向缩放（音域行高），保持时间轴位置不变。 */
function zoomPitch(factor: number) {
  const el = scrollRef.value
  const anchorRatio =
    el && contentHeight.value > 0 ? el.scrollTop / Math.max(1, contentHeight.value) : 0
  const next = Math.min(40, Math.max(8, Math.round(rowHeight.value * factor)))
  if (next === rowHeight.value) return
  rowHeight.value = next
  nextTick(() => {
    if (el) el.scrollTop = Math.max(0, anchorRatio * contentHeight.value)
    measureViewport()
    scheduleDraw()
  })
}

function toggleMaximized() {
  maximized.value = !maximized.value
  nextTick(() => {
    measureViewport()
    scheduleDraw()
  })
}

function scheduleDraw() {
  if (drawHandle) return
  drawHandle = window.requestAnimationFrame(() => {
    drawHandle = 0
    draw()
  })
}

function close() {
  stopPlay()
  emit('update:modelValue', false)
}

function refresh() {
  emit('refresh')
}

function usableWidth() {
  return Math.max(200, viewWidth.value - 24)
}

function fitZoomToWidth() {
  measureViewport()
  const hasNotes = isCompose.value
    ? parts.value.some((part) => (part.notes || []).length > 0)
    : draft.value.length > 0
  if (hasNotes) {
    pxPerSecond.value = fitZoom(duration.value, usableWidth(), 12, 800)
    return
  }
  // 空白会话：不要缩到 12px/s 只剩一小段可视区，用能直接写音符的默认缩放。
  pxPerSecond.value = Math.max(48, Math.min(160, Math.round(usableWidth() / 8)))
}

function zoomToFit() {
  fitZoomToWidth()
  if (scrollRef.value) {
    scrollRef.value.scrollLeft = 0
    scrollRef.value.scrollTop = 0
  }
  onScroll()
}

function focusNotes(notes: Array<{ start: number; end: number }>) {
  if (!notes.length) {
    zoomToFit()
    return
  }
  const start = Math.min(...notes.map((note) => note.start))
  const end = Math.max(...notes.map((note) => note.end))
  const span = Math.max(0.2, end - start)
  measureViewport()
  pxPerSecond.value = fitZoom(span, usableWidth(), 40, 800)
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollLeft = Math.max(0, start * pxPerSecond.value - 40)
    measureViewport()
    scheduleDraw()
  })
}

function zoomToSelection() {
  const notes = isCompose.value
    ? parts.value.flatMap((part) => part.notes.filter((note) => selection.value.includes(note.id)))
    : draft.value.filter((note) => selection.value.includes(note.id))
  focusNotes(notes.length ? notes : allNoteSpans())
}

function allNoteSpans() {
  return isCompose.value
    ? parts.value.flatMap((part) => part.notes)
    : draft.value
}

/* ---------------------------------------------------------------- 撤销 / 选择 */

function cloneSession(source: MidiSession): MidiSession {
  return {
    ...source,
    time_signature: [...(source.time_signature || [4, 4])],
    parts: (source.parts || []).map((part) => ({
      ...part,
      notes: (part.notes || []).map((note) => ({ ...note })),
    })),
  }
}

function pushUndo() {
  if (isCompose.value) {
    composeUndo.push(cloneSession(session.value))
    if (composeUndo.length > 100) composeUndo.shift()
    composeRedo.length = 0
    composeUndoVersion.value += 1
    dirty.value = true
    return
  }
  pitchUndo.push(draft.value.map((note) => ({ ...note })))
  if (pitchUndo.length > 100) pitchUndo.shift()
  pitchRedo.length = 0
  pitchUndoVersion.value += 1
}

function undo() {
  if (isCompose.value) {
    const previous = composeUndo.pop()
    if (!previous) return
    composeRedo.push(cloneSession(session.value))
    session.value = previous
    composeUndoVersion.value += 1
    dirty.value = true
    selection.value = selection.value.filter((id) => !!locateNote(id))
    scheduleDraw()
    return
  }
  const previous = pitchUndo.pop()
  if (!previous) return
  pitchRedo.push(draft.value.map((note) => ({ ...note })))
  draft.value = previous
  selection.value = selection.value.filter((id) => previous.some((note) => note.id === id))
  pitchUndoVersion.value += 1
}

function redo() {
  if (isCompose.value) {
    const next = composeRedo.pop()
    if (!next) return
    composeUndo.push(cloneSession(session.value))
    session.value = next
    composeUndoVersion.value += 1
    dirty.value = true
    scheduleDraw()
    return
  }
  const next = pitchRedo.pop()
  if (!next) return
  pitchUndo.push(draft.value.map((note) => ({ ...note })))
  draft.value = next
  selection.value = selection.value.filter((id) => next.some((note) => note.id === id))
  pitchUndoVersion.value += 1
}

function resetDraft() {
  if (isCompose.value) {
    if (props.composeSession) session.value = normalizeSession(props.composeSession, duration.value)
    composeUndo.length = 0
    composeRedo.length = 0
    composeUndoVersion.value += 1
    selection.value = []
    dirty.value = false
    scheduleDraw()
    return
  }
  pitchUndo.length = 0
  pitchRedo.length = 0
  draft.value = (props.notes || []).map((note) => ({ ...note }))
  selection.value = []
  pitchUndoVersion.value += 1
}

function touchDirty() {
  dirty.value = true
}

function selectOnly(id: string) {
  selection.value = id ? [id] : []
}

function toggleSelect(id: string) {
  selection.value = selection.value.includes(id)
    ? selection.value.filter((item) => item !== id)
    : [...selection.value, id]
}

function selectAll() {
  selection.value = isCompose.value
    ? parts.value.flatMap((part) => part.notes.map((note) => note.id))
    : draft.value.map((note) => note.id)
}

function clearSelection() {
  selection.value = []
}

function selectionSet(): Set<string> {
  return new Set(selection.value)
}

function locateNote(id: string): { part: MidiPart; note: MidiComposeNote } | null {
  for (const part of parts.value) {
    const note = part.notes.find((item) => item.id === id)
    if (note) return { part, note }
  }
  return null
}

/** 鼓组声部里的音符永远落在真实鼓件上：拖动/移调后把音高吸附到最近的鼓件。 */
function snapDrumPitches(nextParts: MidiPart[], ids: Set<string>): MidiPart[] {
  return nextParts.map((part) => {
    if (!part.drum) return part
    let changed = false
    const notes = part.notes.map((note) => {
      if (!ids.has(note.id)) return note
      const snapped = nearestDrumPitch(note.pitch)
      if (snapped === note.pitch) return note
      changed = true
      return { ...note, pitch: snapped }
    })
    return changed ? { ...part, notes } : part
  })
}

/* ---------------------------------------------------------------- 声部操作 */

function selectPart(partId: string) {
  activePartId.value = partId
  scheduleDraw()
}

function addPart() {
  pushUndo()
  const part = createPart(parts.value.length, {
    instrument: parts.value.length === 0 ? 0 : 48,
    name: parts.value.length === 0 ? t('旋律') : `${t('声部')} ${parts.value.length + 1}`,
  })
  session.value.parts = [...session.value.parts, part]
  activePartId.value = part.id
  markPreviewStale()
  scheduleDraw()
}

function addDrumPart() {
  pushUndo()
  const part = createPart(parts.value.length, { drum: true, name: t('架子鼓') })
  session.value.parts = [...session.value.parts, part]
  activePartId.value = part.id
  markPreviewStale()
  scheduleDraw()
}

/** 在鼓组声部里填一段 4/4 基本节奏（可撤销，随后随便改）。 */
function fillDrumBeat(part: MidiPart) {
  pushUndo()
  const beat = secondsPerBeat(session.value.tempo)
  const start = Math.max(0, Math.min(previewTime.value || 0, duration.value - 0.1))
  const generated = basicDrumBeat(beat, { bars: 2, start, velocity: 112 }).map((note) => ({
    ...note,
    start: clampTime(note.start, duration.value),
    end: clampTime(note.end, duration.value),
  }))
  part.notes = sortNotes([...part.notes, ...generated])
  activePartId.value = part.id
  selection.value = generated.map((note) => note.id)
  markPreviewStale()
  scheduleDraw()
}

/** 把 .mid 文件的音符导入到指定声部（鼓组轨会把声部切到鼓组）。 */
async function importMidiToPart(part: MidiPart) {
  const result = await api.importEditorMidiTracks()
  if (!result?.ok) {
    if (result?.error) ElMessage.error(t(result.error))
    return
  }
  const tracks = (result.tracks || []).filter((track) => track.notes.length)
  if (!tracks.length) {
    ElMessage.error(t('MIDI 文件里没有音符'))
    return
  }
  pushUndo()
  const stamp = Date.now().toString(36)
  let counter = 0
  const imported: MidiComposeNote[] = []
  for (const track of tracks) {
    for (const note of track.notes) {
      const span = clampNoteSpan(note.start, note.end, duration.value)
      imported.push({
        id: `im_${stamp}_${counter++}`,
        start: span.start,
        end: span.end,
        pitch: clampComposePitch(note.pitch),
        velocity: clampVelocity(note.velocity),
      })
    }
  }
  part.notes = sortNotes(imported)
  const first = tracks[0]!
  const autoName = isDefaultPartName(part.name)
  if (first.drum) {
    part.drum = true
    part.instrument = 0
    if (autoName) part.name = t('架子鼓')
  } else {
    part.drum = false
    part.instrument = clampProgram(first.program)
    if (autoName) part.name = instrumentLabel(part.instrument)
  }
  activePartId.value = part.id
  selection.value = imported.map((note) => note.id)
  dirty.value = true
  markPreviewStale()
  scheduleDraw()
}

function removePart(part: MidiPart) {
  if (parts.value.length <= 1) return
  pushUndo()
  session.value.parts = parts.value.filter((item) => item.id !== part.id)
  if (activePartId.value === part.id) activePartId.value = session.value.parts[0]?.id || ''
  selection.value = selection.value.filter((id) => !!locateNote(id))
  markPreviewStale()
  scheduleDraw()
}

function toggleMute(part: MidiPart) {
  part.mute = !part.mute
  dirty.value = true
  markPreviewStale()
  scheduleDraw()
}

function toggleSolo(part: MidiPart) {
  part.solo = !part.solo
  dirty.value = true
  markPreviewStale()
  scheduleDraw()
}

function onInstrumentChange(part: MidiPart, event: Event) {
  const target = event.target as HTMLSelectElement
  const value = target.value
  if (value === 'drum') {
    // 切到鼓组：把已有音符吸附到真实鼓件。
    if (!part.drum) {
      const autoName = isDefaultPartName(part.name)
      part.drum = true
      part.instrument = 0
      if (autoName) part.name = t('架子鼓')
      part.notes = part.notes.map((note) => ({ ...note, pitch: nearestDrumPitch(note.pitch) }))
    }
    dirty.value = true
    markPreviewStale()
    scheduleDraw()
    return
  }
  const program = Number(value)
  if (!Number.isFinite(program)) return
  const autoName = isDefaultPartName(part.name)
  part.drum = false
  part.instrument = clampProgram(program)
  if (autoName) part.name = instrumentLabel(part.instrument)
  dirty.value = true
  markPreviewStale()
  scheduleDraw()
}

function applyTempo(event: Event) {
  const target = event.target as HTMLInputElement
  const previous = session.value.tempo
  const next = clampTempo(Number(target.value) || previous)
  target.value = String(Math.round(next))
  if (next === previous) return
  pushUndo()
  // 速度变化时同步缩放已有音符，让「音乐位置」保持不变（和主流 DAW 一致）。
  const factor = previous / next
  session.value.parts = session.value.parts.map((part) => ({
    ...part,
    notes: part.notes.map((note) => ({
      ...note,
      start: Math.round(note.start * factor * 1000) / 1000,
      end: Math.round(note.end * factor * 1000) / 1000,
    })),
  }))
  session.value.tempo = next
  markPreviewStale()
  scheduleDraw()
}

function applySignature(event: Event) {
  const target = event.target as HTMLSelectElement
  const [numerator, denominator] = target.value.split('/').map((item) => Number(item) || 4)
  session.value.time_signature = [numerator || 4, denominator || 4]
  dirty.value = true
  scheduleDraw()
}

function applyDuration(event: Event) {
  const target = event.target as HTMLInputElement
  const raw = Number(target.value)
  const next = Number.isFinite(raw) ? Math.max(0, Math.min(86400, Math.round(raw))) : 0
  durationSeconds.value = next
  target.value = String(next || Math.round(duration.value))
  dirty.value = true
  markPreviewStale()
  scheduleDraw()
}

/* ---------------------------------------------------------------- 编辑操作 */

function setSelectionDetune(event: Event) {
  if (!selection.value.length || isCompose.value) return
  const target = event.target as HTMLInputElement
  const detune = clampDetune(Number(target.value) || 0)
  const ids = selectionSet()
  pushUndo()
  draft.value = draft.value.map((note) => (ids.has(note.id) ? { ...note, detune } : note))
}

function quantizeSelection() {
  if (!selection.value.length) return
  pushUndo()
  if (isCompose.value) {
    const ids = selectionSet()
    const step = snapStep.value
    if (!(step > 0)) {
      undo()
      return
    }
    session.value.parts = parts.value.map((part) => ({
      ...part,
      notes: part.notes.map((note) => {
        if (!ids.has(note.id)) return note
        return quantizeComposeNotes([note], step, duration.value, quantizeStrength.value)[0] || note
      }),
    }))
    markPreviewStale()
    scheduleDraw()
    return
  }
  draft.value = quantizeNotes(draft.value, selection.value, pitchGrid.value, duration.value)
}

function transposeSelection(semitones: number) {
  if (!selection.value.length) return
  pushUndo()
  if (isCompose.value) {
    const ids = selectionSet()
    session.value.parts = snapDrumPitches(
      parts.value.map((part) => ({
        ...part,
        notes: part.notes.map((note) =>
          ids.has(note.id) ? { ...note, pitch: clampComposePitch(note.pitch + semitones) } : note,
        ),
      })),
      ids,
    )
    markPreviewStale()
    scheduleDraw()
    return
  }
  draft.value = transposeNotes(draft.value, selection.value, semitones)
}

function scaleVelocitySelection(factor: number) {
  const ids = selectionSet()
  if (!ids.size) return
  pushUndo()
  session.value.parts = parts.value.map((part) => ({
    ...part,
    notes: part.notes.map((note) =>
      ids.has(note.id) ? scaleNoteVelocity([note], factor)[0]! : note,
    ),
  }))
  markPreviewStale()
  scheduleDraw()
}

function legatoSelection() {
  const ids = selectionSet()
  if (!ids.size) return
  pushUndo()
  session.value.parts = parts.value.map((part) => {
    const chosen = part.notes.filter((note) => ids.has(note.id))
    if (!chosen.length) return part
    const updated = new Map(legatoNotes(chosen, snapStep.value || 0.25).map((note) => [note.id, note]))
    return {
      ...part,
      notes: part.notes.map((note) => updated.get(note.id) || note),
    }
  })
  markPreviewStale()
  scheduleDraw()
}

function duplicateSelection() {
  const ids = selectionSet()
  if (!ids.size) return
  pushUndo()
  const offset = Math.max(snapStep.value || 0.25, 0.1)
  if (isCompose.value) {
    const created: string[] = []
    session.value.parts = parts.value.map((part) => {
      const copies = duplicateNotes(part.notes, ids, offset, duration.value)
      created.push(...copies.map((note) => note.id))
      return copies.length ? { ...part, notes: sortNotes([...part.notes, ...copies]) } : part
    })
    selection.value = created
    markPreviewStale()
    scheduleDraw()
    return
  }
  const copies = pasteNotes(
    copyNotes(draft.value, selection.value),
    (primaryPitchNote.value?.start ?? 0) + offset,
    duration.value,
  )
  draft.value = [...draft.value, ...copies]
  selection.value = copies.map((note) => note.id)
}

function splitSelectionAtPlayhead() {
  if (!isCompose.value) return
  const ids = selectionSet()
  if (!ids.size) return
  const at = previewTime.value
  let changed = false
  pushUndo()
  session.value.parts = parts.value.map((part) => {
    const notes: MidiComposeNote[] = []
    for (const note of part.notes) {
      if (!ids.has(note.id)) {
        notes.push(note)
        continue
      }
      const split = splitNoteAt(note, at)
      if (!split) {
        notes.push(note)
        continue
      }
      changed = true
      notes.push(split[0], split[1])
    }
    return { ...part, notes: sortNotes(notes) }
  })
  if (!changed) {
    composeUndo.pop()
    composeUndoVersion.value += 1
    return
  }
  markPreviewStale()
  scheduleDraw()
}

function humanizeSelection() {
  if (!isCompose.value) return
  const ids = selectionSet()
  if (!ids.size) return
  pushUndo()
  const step = snapStep.value || 0.25
  session.value.parts = parts.value.map((part) => {
    const chosen = part.notes.filter((note) => ids.has(note.id))
    if (!chosen.length) return part
    const updated = new Map(
      humanizeNotes(chosen, step * 0.06, 8, duration.value).map((note) => [note.id, note]),
    )
    return { ...part, notes: part.notes.map((note) => updated.get(note.id) || note) }
  })
  markPreviewStale()
  scheduleDraw()
}

function addComposeNote(time: number, pitch: number, length?: number) {
  const part = activePart.value
  if (!part) return null
  const step = snapStep.value
  const start = step > 0 ? snapTime(clampTime(time, duration.value), step) : clampTime(time, duration.value)
  const drum = !!part.drum
  // 鼓组音符不需要「拉长」：默认就是短促一击，长度取网格但不超过 1/4 拍。
  const defaultLength = drum
    ? Math.min(step || 0.25, 0.25)
    : Math.max(step || 0.25, 0.1)
  const note = createComposeNote(
    start,
    drum ? nearestDrumPitch(pitch || DRUM_DEFAULT_PITCH) : pitch,
    duration.value,
    length ?? defaultLength,
    drum ? 112 : 100,
  )
  pushUndo()
  part.notes = sortNotes([...part.notes, note])
  selectOnly(note.id)
  markPreviewStale()
  playBlip(note.pitch, note.velocity)
  scheduleDraw()
  return note
}

function addPitchNote(time: number, pitch: number, length = MIN_NOTE_LENGTH) {
  const note = createNote(
    snapTime(clampTime(time, duration.value), pitchGrid.value),
    pitch,
    duration.value,
    pitchGrid.value,
    Math.max(pitchGrid.value, length),
  )
  pushUndo()
  draft.value = [...draft.value, note]
  selectOnly(note.id)
  return note
}

function deleteSelected() {
  if (!selection.value.length) return
  const ids = selectionSet()
  pushUndo()
  if (isCompose.value) {
    session.value.parts = parts.value.map((part) => ({
      ...part,
      notes: part.notes.filter((note) => !ids.has(note.id)),
    }))
    markPreviewStale()
    scheduleDraw()
  } else {
    draft.value = draft.value.filter((note) => !ids.has(note.id))
  }
  selection.value = []
}

function copySelected() {
  if (!selection.value.length) return
  const ids = selectionSet()
  if (isCompose.value) {
    composeClipboard.value = parts.value.flatMap((part) =>
      part.notes.filter((note) => ids.has(note.id)).map((note) => ({ partId: part.id, note: { ...note } })),
    )
    return
  }
  pitchClipboard.value = copyNotes(draft.value, selection.value)
}

function pasteClipboard(at: number) {
  if (isCompose.value) {
    if (!composeClipboard.value.length) return
    const anchor = Math.min(...composeClipboard.value.map((entry) => entry.note.start))
    const shift = Math.max(0, at - anchor)
    pushUndo()
    const created: string[] = []
    const stamp = Date.now().toString(36)
    session.value.parts = parts.value.map((part) => {
      const additions = composeClipboard.value
        .filter((entry) => entry.partId === part.id)
        .map((entry, index) => {
          const length = entry.note.end - entry.note.start
          const start = Math.min(entry.note.start + shift, Math.max(0, duration.value - length))
          return {
            ...entry.note,
            id: `${entry.note.id}_p${stamp}${index}`,
            start: Math.round(start * 1000) / 1000,
            end: Math.round(Math.min(duration.value, start + length) * 1000) / 1000,
          }
        })
      if (!additions.length) return part
      created.push(...additions.map((note) => note.id))
      return { ...part, notes: sortNotes([...part.notes, ...additions]) }
    })
    // 粘贴到别的声部（来源声部不存在时落到当前声部）
    if (!created.length && composeClipboard.value.length) {
      const part = activePart.value
      if (part) {
        const additions = composeClipboard.value.map((entry, index) => {
          const length = entry.note.end - entry.note.start
          const start = Math.min(entry.note.start + shift, Math.max(0, duration.value - length))
          return {
            ...entry.note,
            id: `${entry.note.id}_p${stamp}${index}`,
            start: Math.round(start * 1000) / 1000,
            end: Math.round(Math.min(duration.value, start + length) * 1000) / 1000,
          }
        })
        part.notes = sortNotes([...part.notes, ...additions])
        created.push(...additions.map((note) => note.id))
      }
    }
    selection.value = created
    markPreviewStale()
    scheduleDraw()
    return
  }
  if (!pitchClipboard.value.length) return
  const pasted = pasteNotes(pitchClipboard.value, at, duration.value)
  if (!pasted.length) return
  pushUndo()
  draft.value = [...draft.value, ...pasted]
  selection.value = pasted.map((note) => note.id)
}

function emitSave() {
  emit('save', normalizeNotes(draft.value, duration.value))
}

function emitApply() {
  emit('apply', normalizeNotes(draft.value, duration.value))
}

function emitPreview() {
  emit('preview')
}

function emitSaveSession() {
  busyAction.value = 'save'
  emit('save-session', normalizeSession(session.value, duration.value))
}

function emitRender(mode: 'tracks' | 'mix') {
  busyAction.value = mode
  emit('render-session', normalizeSession(session.value, duration.value), mode)
}

function emitExport() {
  emit('export-session', normalizeSession(session.value, duration.value))
}

function requestPreview() {
  busyAction.value = 'preview'
  previewPending.value = true
  if (props.previewUrl && !previewStale.value) {
    busyAction.value = ''
    void playPreview()
    return
  }
  emit('preview-session', normalizeSession(session.value, duration.value))
}

const previewStale = ref(true)

function markPreviewStale() {
  previewStale.value = true
}

watch(
  () => props.previewUrl,
  (url) => {
    if (!url) return
    previewStale.value = false
    previewTime.value = 0
    nextTick(() => {
      const el = audioEl.value
      if (!el) return
      el.currentTime = 0
      if (previewPending.value) {
        previewPending.value = false
        void playPreview()
      }
    })
  },
)

watch(
  () => props.previewLoading,
  (loading) => {
    if (loading) previewPending.value = true
  },
)

async function playPreview() {
  const el = audioEl.value
  if (!el) return
  try {
    await el.play()
  } catch {
    playingState.value = false
  }
}

function togglePlay() {
  if (!isCompose.value) {
    emitPreview()
    return
  }
  if (playingState.value) {
    audioEl.value?.pause()
    return
  }
  if (!props.previewUrl || previewStale.value) {
    requestPreview()
    return
  }
  void playPreview()
}

function stopPlay() {
  const el = audioEl.value
  if (el) {
    el.pause()
    el.currentTime = 0
  }
  playingState.value = false
  previewTime.value = 0
  previewPending.value = false
  if (rafPlayhead) window.cancelAnimationFrame(rafPlayhead)
  rafPlayhead = 0
}

function toggleLoop() {
  loopEnabled.value = !loopEnabled.value
}

function onAudioPlay() {
  playingState.value = true
  busyAction.value = ''
  if (rafPlayhead) window.cancelAnimationFrame(rafPlayhead)
  const tick = () => {
    const el = audioEl.value
    if (!el) return
    previewTime.value = el.currentTime
    if (!el.paused) rafPlayhead = window.requestAnimationFrame(tick)
  }
  rafPlayhead = window.requestAnimationFrame(tick)
}

function onAudioPause() {
  playingState.value = false
  if (rafPlayhead) window.cancelAnimationFrame(rafPlayhead)
  rafPlayhead = 0
}

function onAudioEnded() {
  playingState.value = false
  if (loopEnabled.value) {
    const el = audioEl.value
    if (el) {
      el.currentTime = 0
      void el.play()
    }
    return
  }
  previewTime.value = 0
}

/* ---------------------------------------------------------------- 快捷键 */

function isTypingTarget(target: EventTarget | null) {
  const element = target instanceof HTMLElement ? target : null
  if (!element) return false
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) || element.isContentEditable
}

function onKeyDown(event: KeyboardEvent) {
  if (!props.modelValue || isTypingTarget(event.target)) return
  const mod = event.ctrlKey || event.metaKey
  const key = event.key
  if (key === 'Escape') {
    if (contextMenu.visible) {
      contextMenu.visible = false
      return
    }
    if (selection.value.length) {
      clearSelection()
      return
    }
    if (maximized.value) {
      toggleMaximized()
      return
    }
    close()
    return
  }
  if (key === ' ' || key === 'Spacebar') {
    event.preventDefault()
    togglePlay()
    return
  }
  // 缩放：+ / - 横向，Shift + + / - 纵向音域
  if (key === '+' || key === '=') {
    event.preventDefault()
    if (event.shiftKey) zoomPitch(1.25)
    else zoomTime(1.25)
    return
  }
  if (key === '-' || key === '_') {
    event.preventDefault()
    if (event.shiftKey) zoomPitch(0.8)
    else zoomTime(0.8)
    return
  }
  if (key === 'F11' || (mod && event.shiftKey && key.toLowerCase() === 'f')) {
    event.preventDefault()
    toggleMaximized()
    return
  }
  if (mod && key.toLowerCase() === 'z') {
    event.preventDefault()
    if (event.shiftKey) redo()
    else undo()
    return
  }
  if (mod && key.toLowerCase() === 'y') {
    event.preventDefault()
    redo()
    return
  }
  if (mod && key.toLowerCase() === 'a') {
    event.preventDefault()
    selectAll()
    return
  }
  if (mod && key.toLowerCase() === 'c') {
    event.preventDefault()
    copySelected()
    return
  }
  if (mod && key.toLowerCase() === 'v') {
    event.preventDefault()
    pasteClipboard(cursorTime.value || (primaryNote.value?.start ?? 0))
    return
  }
  if (mod && key.toLowerCase() === 'd') {
    event.preventDefault()
    duplicateSelection()
    return
  }
  if (mod && key.toLowerCase() === 'q') {
    event.preventDefault()
    quantizeSelection()
    return
  }
  if (!mod && !event.altKey && isCompose.value) {
    const lower = key.toLowerCase()
    if (lower === 'd') {
      currentTool.value = 'draw'
      return
    }
    if (lower === 'v') {
      currentTool.value = 'select'
      return
    }
    if (lower === 'e') {
      currentTool.value = 'erase'
      return
    }
    if (lower === 'h') {
      humanizeSelection()
      return
    }
    if (lower === 'l') {
      legatoSelection()
      return
    }
    if (lower === 's') {
      splitSelectionAtPlayhead()
      return
    }
  }
  if (key === 'Delete' || key === 'Backspace') {
    if (selection.value.length) {
      event.preventDefault()
      deleteSelected()
    }
    return
  }
  if (!selection.value.length) return
  // 选中音符伸缩：] 加长、[ 缩短（以网格步长为步长，网格关闭时用 0.05s）。
  if (key === ']' || key === '[') {
    event.preventDefault()
    const step = snapStep.value > 0 ? snapStep.value : 0.05
    stretchSelection(key === ']' ? step : -step)
    return
  }
  if (key === 'ArrowUp' || key === 'ArrowDown') {
    event.preventDefault()
    const step = event.shiftKey ? 12 : 1
    transposeSelection(key === 'ArrowUp' ? step : -step)
    return
  }
  if (key === 'ArrowLeft' || key === 'ArrowRight') {
    event.preventDefault()
    const step = (event.shiftKey ? 4 : 1) * (snapStep.value || 0.1)
    const delta = key === 'ArrowLeft' ? -step : step
    nudgeSelection(delta)
  }
}

function nudgeSelection(deltaSeconds: number) {
  if (isCompose.value) {
    pushUndo()
    const ids = selectionSet()
    session.value.parts = parts.value.map((part) => ({
      ...part,
      notes: part.notes.map((note) => {
        if (!ids.has(note.id)) return note
        const span = clampNoteSpan(note.start + deltaSeconds, note.end + deltaSeconds, duration.value)
        return { ...note, start: span.start, end: span.end }
      }),
    }))
    markPreviewStale()
    scheduleDraw()
    return
  }
  const ids = selectionSet()
  pushUndo()
  draft.value = draft.value.map((note) => {
    if (!ids.has(note.id)) return note
    const span = clampNoteSpan(note.start + deltaSeconds, note.end + deltaSeconds, duration.value)
    return { ...note, start: span.start, end: span.end }
  })
}

/** 单个/多个选中音符伸缩：只改结束时间（右手边），带最小长度与时间轴边界。 */
function stretchSelection(deltaSeconds: number) {
  if (!selection.value.length) return
  const ids = selectionSet()
  pushUndo()
  if (isCompose.value) {
    session.value.parts = parts.value.map((part) => ({
      ...part,
      notes: part.notes.map((note) =>
        ids.has(note.id)
          ? resizeComposeNote(note, 'end', note.end + deltaSeconds, duration.value, 0)
          : note,
      ),
    }))
    markPreviewStale()
    scheduleDraw()
    return
  }
  draft.value = draft.value.map((note) =>
    ids.has(note.id) ? resizeNote(note, 'end', note.end + deltaSeconds, duration.value, 0) : note,
  )
}

/* ---------------------------------------------------------------- 画布绘制 */

function contextOf(canvas: HTMLCanvasElement | null) {
  if (!canvas) return null
  const context = canvas.getContext('2d')
  if (!context) return null
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  return context
}

function draw() {
  drawKeys()
  drawGrid()
  if (showVelocity.value) drawVelocity()
}

function drawKeys() {
  const context = contextOf(keyCanvasRef.value)
  if (!context) return
  const height = viewHeight.value
  const top = pitchRange.value.max
  const offsetY = scrollTop.value
  context.clearRect(0, 0, KEY_WIDTH, height)
  context.fillStyle = '#0b0f18'
  context.fillRect(0, 0, KEY_WIDTH, height)
  context.save()
  context.beginPath()
  context.rect(0, RULER_HEIGHT, KEY_WIDTH, Math.max(0, height - RULER_HEIGHT))
  context.clip()
  for (let pitch = top; pitch >= pitchRange.value.min; pitch -= 1) {
    const y = pitchToY(pitch, top, rowHeight.value) + RULER_HEIGHT - offsetY
    if (y + rowHeight.value < RULER_HEIGHT || y > height) continue
    if (drumMode.value) {
      // 鼓组：只有真实鼓件那一行像「键」，其它行弱化成空白，避免误点。
      const piece = drumPiece(pitch)
      context.fillStyle = piece ? '#e8ecf5' : '#0d121b'
      context.fillRect(0, y, KEY_WIDTH - 6, rowHeight.value - 1)
      if (piece) {
        context.fillStyle = piece.group === 'kick' ? '#1c2a3a' : '#3a4356'
        context.font = '10px ui-sans-serif, system-ui'
        context.textBaseline = 'middle'
        context.fillText(piece.name_zh, 6, y + rowHeight.value / 2)
      } else {
        context.fillStyle = '#243044'
        context.fillRect(KEY_WIDTH - 8, y + rowHeight.value / 2, 2, 1)
      }
      continue
    }
    const black = isBlackKey(pitch)
    context.fillStyle = black ? '#141a26' : '#e8ecf5'
    context.fillRect(0, y, KEY_WIDTH - 6, rowHeight.value - 1)
    context.fillStyle = black ? '#8e9bb3' : '#3a4356'
    context.font = '10px ui-sans-serif, system-ui'
    context.textBaseline = 'middle'
    context.fillText(noteName(pitch), 8, y + rowHeight.value / 2)
  }
  context.restore()
  context.fillStyle = '#0b0f18'
  context.fillRect(0, 0, KEY_WIDTH, RULER_HEIGHT)
  context.strokeStyle = 'rgba(120,180,255,0.22)'
  context.beginPath()
  context.moveTo(0, RULER_HEIGHT - 0.5)
  context.lineTo(KEY_WIDTH, RULER_HEIGHT - 0.5)
  context.stroke()
}

function drawGrid() {
  const canvas = gridCanvasRef.value
  const context = contextOf(canvas)
  if (!context) return
  const width = viewWidth.value
  const height = viewHeight.value
  const top = pitchRange.value.max
  const offsetX = scrollLeft.value
  const offsetY = scrollTop.value
  const pps = pxPerSecond.value
  context.clearRect(0, 0, width, height)
  context.fillStyle = '#0b0f18'
  context.fillRect(0, 0, width, height)

  context.save()
  context.beginPath()
  context.rect(0, RULER_HEIGHT, width, Math.max(0, height - RULER_HEIGHT))
  context.clip()

  for (let pitch = top; pitch >= pitchRange.value.min; pitch -= 1) {
    const y = pitchToY(pitch, top, rowHeight.value) + RULER_HEIGHT - offsetY
    if (y + rowHeight.value < RULER_HEIGHT || y > height) continue
    if (drumMode.value && !isDrumPitch(pitch)) {
      context.fillStyle = '#090d14'
      context.fillRect(0, y, width, rowHeight.value - 1)
      continue
    }
    context.fillStyle = isBlackKey(pitch) ? '#0f1520' : '#121926'
    context.fillRect(0, y, width, rowHeight.value - 1)
    if (drumMode.value) {
      // 鼓件行按组着色，扫一眼就知道哪一行是鼓、哪一行是镲。
      const piece = drumPiece(pitch)
      if (piece && (piece.group === 'kick' || piece.group === 'snare')) {
        context.fillStyle = 'rgba(255, 209, 102, 0.05)'
        context.fillRect(0, y, width, rowHeight.value - 1)
      }
    }
    if (pitch % 12 === 0) {
      context.fillStyle = 'rgba(120,180,255,0.18)'
      context.fillRect(0, y, width, 1)
    }
  }

  // 竖向网格：编曲模式按小节/拍，音准模式按秒
  if (isCompose.value) {
    const beat = secondsPerBeat(session.value.tempo)
    const bar = barSeconds(session.value.tempo, session.value.time_signature)
    const subStep = snapStep.value
    const firstTime = Math.max(0, xToTime(offsetX, pps))
    const lastTime = Math.min(duration.value, xToTime(offsetX + width, pps))
    if (subStep > 0 && timeToX(subStep, pps) >= 5) {
      context.strokeStyle = 'rgba(255,255,255,0.05)'
      context.lineWidth = 1
      context.beginPath()
      for (let time = Math.floor(firstTime / subStep) * subStep; time <= lastTime; time += subStep) {
        const x = Math.round(timeToX(time, pps) - offsetX) + 0.5
        context.moveTo(x, RULER_HEIGHT)
        context.lineTo(x, height)
      }
      context.stroke()
    }
    if (beat > 0 && timeToX(beat, pps) >= 12) {
      context.strokeStyle = 'rgba(140,190,255,0.16)'
      context.beginPath()
      for (let time = Math.floor(firstTime / beat) * beat; time <= lastTime; time += beat) {
        const x = Math.round(timeToX(time, pps) - offsetX) + 0.5
        context.moveTo(x, RULER_HEIGHT)
        context.lineTo(x, height)
      }
      context.stroke()
    }
    if (bar > 0) {
      context.strokeStyle = 'rgba(160,210,255,0.32)'
      context.beginPath()
      for (let time = Math.floor(firstTime / bar) * bar; time <= lastTime; time += bar) {
        const x = Math.round(timeToX(time, pps) - offsetX) + 0.5
        context.moveTo(x, RULER_HEIGHT)
        context.lineTo(x, height)
      }
      context.stroke()
    }
  } else {
    const step = pitchGrid.value > 0 ? pitchGrid.value : 0.1
    const pxPerStep = timeToX(step, pps)
    const firstTime = Math.max(0, xToTime(offsetX, pps))
    const lastTime = Math.min(duration.value, xToTime(offsetX + width, pps))
    if (pxPerStep >= 4) {
      context.strokeStyle = 'rgba(255,255,255,0.06)'
      context.lineWidth = 1
      context.beginPath()
      for (let time = Math.floor(firstTime / step) * step; time <= lastTime; time += step) {
        const x = Math.round(timeToX(time, pps) - offsetX) + 0.5
        context.moveTo(x, RULER_HEIGHT)
        context.lineTo(x, height)
      }
      context.stroke()
    }
    if (props.scope === 'track' && props.clipSpans.length) {
      props.clipSpans.forEach((span, index) => {
        const left = timeToX(Math.max(0, span.start), pps) - offsetX
        const right = timeToX(span.end, pps) - offsetX
        if (right < 0 || left > width) return
        context.fillStyle = index % 2 === 0 ? 'rgba(94,194,255,0.05)' : 'rgba(94,194,255,0.09)'
        context.fillRect(left, RULER_HEIGHT, Math.max(1, right - left), height - RULER_HEIGHT)
        context.strokeStyle = 'rgba(94,194,255,0.45)'
        context.lineWidth = 1
        context.beginPath()
        context.moveTo(Math.round(left) + 0.5, RULER_HEIGHT)
        context.lineTo(Math.round(left) + 0.5, height)
        context.stroke()
        context.fillStyle = 'rgba(160,210,255,0.7)'
        context.font = '9px ui-sans-serif, system-ui'
        if (right - left > 24) context.fillText(span.name || span.id, left + 3, RULER_HEIGHT + 9)
      })
    }
  }

  const selected = selectionSet()
  if (isCompose.value) {
    const soloed = parts.value.some((part) => part.solo)
    for (const part of parts.value) {
      const dim = part.mute || (soloed && !part.solo) || (activePartId.value && part.id !== activePartId.value)
      for (const note of part.notes) {
        const rect = noteRect(note, top, rowHeight.value, pps, MIDI_MIN_NOTE_PX)
        const x = rect.x - offsetX
        if (x + rect.width < -4 || x > width + 4) continue
        const y = rect.y + RULER_HEIGHT - offsetY
        if (y + rect.height < RULER_HEIGHT - 4 || y > height + 4) continue
        const active = selected.has(note.id)
        context.globalAlpha = active ? 1 : dim ? velocityAlpha(note.velocity) * 0.55 : velocityAlpha(note.velocity)
        context.fillStyle = part.color
        roundRect(context, x, y, rect.width, rect.height, 3)
        context.fill()
        context.globalAlpha = 1
        if (active) {
          context.strokeStyle = '#f2fbff'
          context.lineWidth = 1.5
          roundRect(context, x, y, rect.width, rect.height, 3)
          context.stroke()
        }
        if (rect.width > 26) {
          context.fillStyle = 'rgba(4,10,18,0.82)'
          context.font = '9px ui-sans-serif, system-ui'
          context.fillText(
            part.drum ? drumName(note.pitch) : noteName(note.pitch),
            x + 3,
            y + rect.height / 2,
          )
        }
        if (active || hoveredNoteId.value === note.id) {
          drawNoteEdgeHandles(context, x, y, rect.width, rect.height, active)
        }
      }
    }
  } else {
    for (const note of draft.value) {
      const rect = noteRect(note, top, rowHeight.value, pps, MIDI_MIN_NOTE_PX)
      const x = rect.x - offsetX
      if (x + rect.width < -4 || x > width + 4) continue
      const y = rect.y + RULER_HEIGHT - offsetY
      if (y + rect.height < RULER_HEIGHT - 4 || y > height + 4) continue
      const active = selected.has(note.id)
      context.fillStyle = active ? 'rgba(94,206,255,0.95)' : 'rgba(94,206,255,0.5)'
      roundRect(context, x, y, rect.width, rect.height, 3)
      context.fill()
      if (active) {
        context.strokeStyle = '#dff6ff'
        context.lineWidth = 1.5
        roundRect(context, x, y, rect.width, rect.height, 3)
        context.stroke()
      }
      if (rect.width > 24) {
        context.fillStyle = active ? '#04121c' : '#08222e'
        context.font = '9px ui-sans-serif, system-ui'
        context.fillText(noteName(note.pitch), x + 3, y + rect.height / 2)
      }
      if (active || hoveredNoteId.value === note.id) {
        drawNoteEdgeHandles(context, x, y, rect.width, rect.height, active)
      }
    }
  }

  if (drag.value?.mode === 'marquee' && drag.value.marqueeStart && drag.value.marqueeEnd) {
    const { marqueeStart, marqueeEnd } = drag.value
    const left = Math.min(marqueeStart.x, marqueeEnd.x) - offsetX
    const right = Math.max(marqueeStart.x, marqueeEnd.x) - offsetX
    const topY = Math.min(marqueeStart.y, marqueeEnd.y) + RULER_HEIGHT - offsetY
    const bottomY = Math.max(marqueeStart.y, marqueeEnd.y) + RULER_HEIGHT - offsetY
    context.fillStyle = 'rgba(94,206,255,0.12)'
    context.fillRect(left, topY, right - left, bottomY - topY)
    context.strokeStyle = 'rgba(94,206,255,0.6)'
    context.lineWidth = 1
    context.strokeRect(left + 0.5, topY + 0.5, right - left, bottomY - topY)
  }
  context.restore()

  drawRuler(context, width, pps, offsetX)

  const headSeconds = playheadSeconds.value
  const headX = headSeconds >= 0 && headSeconds <= duration.value ? timeToX(headSeconds, pps) : null
  if (headX !== null) {
    const x = headX - offsetX
    if (x >= -2 && x <= width + 2) {
      context.strokeStyle = playing.value ? '#ffd166' : 'rgba(255,209,102,0.55)'
      context.lineWidth = 1.5
      context.beginPath()
      context.moveTo(x, 0)
      context.lineTo(x, height)
      context.stroke()
      context.fillStyle = playing.value ? '#ffd166' : 'rgba(255,209,102,0.7)'
      context.beginPath()
      context.moveTo(x - 4, 0)
      context.lineTo(x + 4, 0)
      context.lineTo(x, 5)
      context.closePath()
      context.fill()
    }
  }
}

function drawRuler(
  context: CanvasRenderingContext2D,
  width: number,
  pps: number,
  offsetX: number,
) {
  const height = viewHeight.value
  const dividerY = RULER_HEIGHT - 16 // 上面是小节/拍，下面是秒刻度
  context.fillStyle = '#0b0f18'
  context.fillRect(0, 0, width, RULER_HEIGHT)
  context.font = '10px ui-sans-serif, system-ui'
  context.textBaseline = 'middle'
  context.strokeStyle = 'rgba(255,255,255,0.16)'

  // 上排：编曲模式画小节/拍，音高模式画秒刻度。
  if (isCompose.value) {
    const tempo = session.value.tempo
    const signature = session.value.time_signature
    const beat = secondsPerBeat(tempo)
    const bar = barSeconds(tempo, signature)
    const beatsPerBar = Math.max(1, Math.round(bar / Math.max(1e-6, beat)))
    const firstBar = Math.max(0, Math.floor(xToTime(offsetX, pps) / bar))
    const lastTime = xToTime(offsetX + width, pps)
    for (let index = firstBar; index * bar <= lastTime + 1e-6; index += 1) {
      const barTime = index * bar
      const x = Math.round(timeToX(barTime, pps) - offsetX) + 0.5
      if (x >= -60 && x <= width + 60) {
        context.strokeStyle = 'rgba(160,210,255,0.4)'
        context.beginPath()
        context.moveTo(x, dividerY - 7)
        context.lineTo(x, dividerY)
        context.stroke()
        context.fillStyle = '#9db8dd'
        context.fillText(`${index + 1}`, x + 3, 7)
        for (let offset = 1; offset < beatsPerBar; offset += 1) {
          const beatTime = barTime + offset * beat
          const bx = Math.round(timeToX(beatTime, pps) - offsetX) + 0.5
          if (bx < -4 || bx > width + 4) continue
          context.strokeStyle = 'rgba(255,255,255,0.14)'
          context.beginPath()
          context.moveTo(bx, dividerY - 3)
          context.lineTo(bx, dividerY)
          context.stroke()
        }
      }
    }
  }

  // 下排：秒刻度，两种模式都显示，方便和主编辑器的秒级时间轴对齐。
  const secondPx = timeToX(1, pps)
  const labelEvery = secondPx >= 64 ? 1 : secondPx >= 28 ? 2 : secondPx >= 10 ? 5 : 10
  const firstLabel = Math.max(
    0,
    Math.floor(xToTime(offsetX, pps) / labelEvery) * labelEvery,
  )
  for (
    let second = firstLabel;
    second <= duration.value + 1e-6 && timeToX(second, pps) - offsetX <= width;
    second += labelEvery
  ) {
    const x = Math.round(timeToX(second, pps) - offsetX) + 0.5
    if (x < -20) continue
    context.strokeStyle = 'rgba(255,255,255,0.10)'
    context.beginPath()
    context.moveTo(x, dividerY + 5)
    context.lineTo(x, RULER_HEIGHT)
    context.stroke()
    context.fillStyle = '#75839c'
    context.fillText(`${second}s`, x + 3, dividerY + 11)
  }

  context.strokeStyle = 'rgba(120,180,255,0.22)'
  context.beginPath()
  context.moveTo(0, dividerY + 0.5)
  context.lineTo(width, dividerY + 0.5)
  context.stroke()
  context.beginPath()
  context.moveTo(0, RULER_HEIGHT - 0.5)
  context.lineTo(width, RULER_HEIGHT - 0.5)
  context.stroke()
  void height
}

function drawVelocity() {
  const canvas = velocityCanvasRef.value
  const context = contextOf(canvas)
  if (!context) return
  const width = viewWidth.value
  const pps = pxPerSecond.value
  const offsetX = scrollLeft.value
  context.clearRect(0, 0, width, velocityHeight)
  context.fillStyle = '#0a0e16'
  context.fillRect(0, 0, width, velocityHeight)
  context.strokeStyle = 'rgba(255,255,255,0.06)'
  for (let index = 1; index < 4; index += 1) {
    const y = Math.round((velocityHeight / 4) * index) + 0.5
    context.beginPath()
    context.moveTo(0, y)
    context.lineTo(width, y)
    context.stroke()
  }
  context.fillStyle = '#6d7f9c'
  context.font = '9px ui-sans-serif, system-ui'
  context.textBaseline = 'middle'
  context.fillText(t('力度'), 6, 10)
  const selected = selectionSet()
  for (const part of parts.value) {
    if (part.mute) continue
    for (const note of part.notes) {
      const x = timeToX(note.start, pps) - offsetX
      if (x < -3 || x > width + 3) continue
      const height = (note.velocity / 127) * (velocityHeight - 14)
      const active = selected.has(note.id)
      context.fillStyle = part.color
      context.globalAlpha = active ? 1 : 0.55
      context.fillRect(x, velocityHeight - 10 - height, active ? 5 : 3, height)
      context.globalAlpha = 1
      if (active) {
        context.strokeStyle = '#f2fbff'
        context.lineWidth = 1
        context.strokeRect(x + 0.5, velocityHeight - 10 - height + 0.5, 4, height - 1)
      }
    }
  }
  context.strokeStyle = 'rgba(120,180,255,0.18)'
  context.beginPath()
  context.moveTo(0, 0.5)
  context.lineTo(width, 0.5)
  context.stroke()
}

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const r = Math.min(radius, width / 2, height / 2)
  context.beginPath()
  context.moveTo(x + r, y)
  context.arcTo(x + width, y, x + width, y + height, r)
  context.arcTo(x + width, y + height, x, y + height, r)
  context.arcTo(x, y + height, x, y, r)
  context.arcTo(x, y, x + width, y, r)
  context.closePath()
}

/** 在音符左右边缘画「可拉伸」把手：选中或悬停时提示拖这里改长度。 */
function drawNoteEdgeHandles(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  active: boolean,
) {
  // 太窄的音符按 noteEdgeAt 的逻辑不开放边缘拉伸，也就不画把手。
  if (width < MIN_RESIZE_PX) return
  const handleW = Math.min(EDGE_GRAB_PX, Math.max(3, width / 3))
  context.fillStyle = active ? 'rgba(255,255,255,0.96)' : 'rgba(222,238,255,0.9)'
  context.fillRect(x + 0.5, y + 1, handleW - 1, height - 2)
  context.fillRect(x + width - handleW + 0.5, y + 1, handleW - 1, height - 2)
  context.fillStyle = 'rgba(4,10,18,0.55)'
  context.fillRect(x + handleW - 0.5, y + 1, 1, height - 2)
  context.fillRect(x + width - handleW + 0.5, y + 1, 1, height - 2)
}

/* ---------------------------------------------------------------- 指针交互 */

interface CanvasPoint {
  vx: number
  vy: number
  x: number
  y: number
}

function canvasPoint(event: PointerEvent | MouseEvent): CanvasPoint {
  const canvas = gridCanvasRef.value
  if (!canvas) return { vx: 0, vy: 0, x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const vx = (event.clientX - rect.left) * (viewWidth.value / Math.max(1, rect.width))
  const vy = (event.clientY - rect.top) * (viewHeight.value / Math.max(1, rect.height))
  return { vx, vy, x: vx + scrollLeft.value, y: vy + scrollTop.value }
}

function timeOf(x: number) {
  return clampTime(xToTime(x, pxPerSecond.value), duration.value)
}

function pitchOf(y: number) {
  const raw = yToPitch(Math.max(0, y - RULER_HEIGHT), pitchRange.value.max, rowHeight.value)
  // 鼓组没有音高，只有鼓件：吸附到最近的鼓件上；旋律声部覆盖 GM 全音域。
  if (drumMode.value) return nearestDrumPitch(raw)
  return isCompose.value ? clampComposePitch(raw) : clampPitch(raw)
}

function pitchNoteAt(point: CanvasPoint) {
  return noteAtPoint(
    draft.value,
    point.x,
    point.y - RULER_HEIGHT,
    pitchRange.value.max,
    rowHeight.value,
    pxPerSecond.value,
  )
}

function composeNoteAt(point: CanvasPoint) {
  return composeNoteAtPoint(
    parts.value.filter((part) => isPartAudible(parts.value, part) || part.id === activePartId.value),
    point.x,
    point.y - RULER_HEIGHT,
    pitchRange.value.max,
    rowHeight.value,
    pxPerSecond.value,
  )
}

function onPointerDown(event: PointerEvent) {
  if (event.button === 2) return
  hideContextMenu()
  const point = canvasPoint(event)
  if (point.vy < RULER_HEIGHT) {
    // 刻度尺：点一下把播放头移过去
    const target = timeOf(point.x)
    cursorTime.value = target
    seek(target)
    return
  }
  cursorTime.value = timeOf(point.x)
  const step = snapStep.value

  if (isCompose.value) {
    const hit = composeNoteAt(point)
    if (currentTool.value === 'erase') {
      if (hit) {
        pushUndo()
        hit.part.notes = hit.part.notes.filter((note) => note.id !== hit.note.id)
        selection.value = selection.value.filter((id) => id !== hit.note.id)
        markPreviewStale()
        drag.value = {
          mode: 'erase',
          originX: point.x,
          originY: point.y,
          baseAll: [],
          baseSession: null,
          partId: hit.part.id,
          ids: [],
        }
        scheduleDraw()
      }
      return
    }
    if (currentTool.value === 'draw' && !hit) {
      const note = addComposeNote(timeOf(point.x), pitchOf(point.y), Math.max(step || 0.25, 0.1))
      if (note) {
        drag.value = {
          mode: 'create',
          originX: point.x,
          originY: point.y,
          baseAll: [],
          baseSession: cloneSession(session.value),
          partId: activePart.value?.id || '',
          ids: [note.id],
          createStart: note.start,
          createPitch: note.pitch,
        }
        ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
      }
      return
    }
    if (!hit) {
      if (!(event.shiftKey || event.ctrlKey || event.metaKey)) clearSelection()
      drag.value = {
        mode: 'marquee',
        originX: point.x,
        originY: point.y,
        baseAll: [],
        baseSession: null,
        partId: '',
        ids: [],
        marqueeStart: { x: point.x, y: point.y - RULER_HEIGHT },
        marqueeEnd: { x: point.x, y: point.y - RULER_HEIGHT },
      }
      ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
      return
    }
    if (event.shiftKey || event.ctrlKey || event.metaKey) toggleSelect(hit.note.id)
    else if (!selection.value.includes(hit.note.id)) selectOnly(hit.note.id)
    activePartId.value = hit.part.id
    if (currentTool.value === 'select') playBlip(hit.note.pitch, hit.note.velocity)
    const edge = noteEdgeAt(
      hit.note,
      point.x,
      pitchRange.value.max,
      rowHeight.value,
      pxPerSecond.value,
      EDGE_GRAB_PX,
    )
    drag.value = {
      mode: edge,
      originX: point.x,
      originY: point.y,
      baseAll: [],
      baseSession: cloneSession(session.value),
      partId: hit.part.id,
      ids:
        edge === 'move' && currentTool.value === 'select'
          ? selection.value.slice()
          : [hit.note.id],
    }
    ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
    event.preventDefault()
    return
  }

  // 演唱音准模式
  const note = pitchNoteAt(point)
  if (!note) {
    if (!(event.shiftKey || event.ctrlKey || event.metaKey)) clearSelection()
    drag.value = {
      mode: 'marquee',
      originX: point.x,
      originY: point.y,
      baseAll: draft.value.map((item) => ({ ...item })),
      baseSession: null,
      partId: '',
      ids: [],
      marqueeStart: { x: point.x, y: point.y - RULER_HEIGHT },
      marqueeEnd: { x: point.x, y: point.y - RULER_HEIGHT },
    }
    ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
    return
  }
  if (event.shiftKey || event.ctrlKey || event.metaKey) toggleSelect(note.id)
  else if (!selection.value.includes(note.id)) selectOnly(note.id)
  const edge = noteEdgeAt(note, point.x, pitchRange.value.max, rowHeight.value, pxPerSecond.value, EDGE_GRAB_PX)
  drag.value = {
    mode: edge,
    originX: point.x,
    originY: point.y,
    baseAll: draft.value.map((item) => ({ ...item })),
    baseSession: null,
    partId: '',
    ids: edge === 'move' ? selection.value.slice() : [note.id],
  }
  ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
  event.preventDefault()
}

function seek(seconds: number) {
  const target = Math.min(Math.max(0, seconds), duration.value)
  previewTime.value = target
  const el = audioEl.value
  if (el && el.src) {
    el.currentTime = Math.min(target, Math.max(0, (el.duration || target) - 0.001))
  }
}

function onPointerMove(event: PointerEvent) {
  const current = drag.value
  const point = canvasPoint(event)
  if (!current) {
    const canvas = gridCanvasRef.value
    if (!canvas) return
    const hovered = isCompose.value ? composeNoteAt(point) : pitchNoteAt(point)
    const hoveredNote = hovered ? ('note' in hovered ? hovered.note : hovered) : null
    hoveredNoteId.value = hoveredNote?.id || null
    if (hoveredNote) {
      const edge = noteEdgeAt(
        hoveredNote,
        point.x,
        pitchRange.value.max,
        rowHeight.value,
        pxPerSecond.value,
        EDGE_GRAB_PX,
      )
      canvas.style.cursor = edge === 'move' ? 'grab' : 'ew-resize'
    } else {
      canvas.style.cursor =
        currentTool.value === 'erase' ? 'not-allowed' : point.vy < RULER_HEIGHT ? 'pointer' : 'crosshair'
    }
    return
  }
  if (current.mode === 'erase') {
    const hit = isCompose.value ? composeNoteAt(point) : null
    if (hit) {
      hit.part.notes = hit.part.notes.filter((note) => note.id !== hit.note.id)
      selection.value = selection.value.filter((id) => id !== hit.note.id)
      markPreviewStale()
      scheduleDraw()
    }
    return
  }
  if (current.mode === 'marquee') {
    current.marqueeEnd = { x: point.x, y: point.y - RULER_HEIGHT }
    scheduleDraw()
    return
  }
  const deltaSeconds = xToTime(point.x - current.originX, pxPerSecond.value)
  const deltaPitch = Math.round((current.originY - point.y) / rowHeight.value)
  const step = snapStep.value

  if (isCompose.value) {
    if (current.mode === 'create' && current.baseSession) {
      const partId = current.partId
      const ids = new Set(current.ids)
      const start = current.createStart ?? 0
      const target = step > 0 ? snapTime(timeOf(point.x), step) : timeOf(point.x)
      const end = Math.max(start + (step || 0.05), target)
      session.value.parts = parts.value.map((part) =>
        part.id === partId
          ? {
              ...part,
              notes: part.notes.map((note) =>
                ids.has(note.id)
                  ? { ...note, start, end: Math.min(duration.value, end) }
                  : note,
              ),
            }
          : part,
      )
      markPreviewStale()
      scheduleDraw()
      return
    }
    if (!current.pushed) {
      if (current.baseSession) session.value = current.baseSession
      pushUndo()
      current.pushed = true
    }
    const ids = new Set(current.ids)
    if (current.mode === 'move') {
      const base = current.baseSession
      if (!base) return
      // 拖动移动跟随鼠标 1:1，不做网格吸附（吸附交给「量化」按钮 / Ctrl+Q）。
      // 之前按网格把「位移量」吸附，拖一小段就会跳一整格，手感很差。
      session.value.parts = snapDrumPitches(
        moveComposeNotes(
          base.parts,
          ids,
          deltaSeconds,
          deltaPitch,
          duration.value,
          0,
        ),
        ids,
      )
      markPreviewStale()
      scheduleDraw()
      return
    }
    const base = current.baseSession
    if (!base) return
    const located = base.parts.flatMap((part) => part.notes.map((note) => ({ part, note })))
    const targetItem = located.find((item) => ids.has(item.note.id))
    if (!targetItem) return
    const anchor = current.mode === 'start' ? targetItem.note.start : targetItem.note.end
    // 拉缩边缘同样跟随鼠标 1:1，不吸附网格（网格对齐交给「量化」）。
    const updated = resizeComposeNote(
      targetItem.note,
      current.mode === 'start' ? 'start' : 'end',
      anchor + deltaSeconds,
      duration.value,
      0,
    )
    session.value.parts = base.parts.map((part) => ({
      ...part,
      notes: part.notes.map((note) => (note.id === targetItem.note.id ? updated : note)),
    }))
    markPreviewStale()
    scheduleDraw()
    return
  }

  // 演唱音准模式
  if (!current.pushed) {
    pushUndo()
    current.pushed = true
  }
  if (current.mode === 'move') {
    if (!current.baseAll.some((note) => current.ids.includes(note.id))) return
    // 拖动移动同样跟随鼠标 1:1，不吸附网格。
    draft.value = moveNotes(
      current.baseAll,
      current.ids,
      deltaSeconds,
      deltaPitch,
      duration.value,
      0,
    )
    return
  }
  const base = current.baseAll.find((note) => note.id === current.ids[0])
  if (!base) return
  // 拉缩边缘跟随鼠标 1:1：以被抓取的边缘为锚点（start / end），不吸附网格。
  const anchor = current.mode === 'start' ? base.start : base.end
  const target = anchor + deltaSeconds
  draft.value = current.baseAll.map((note) =>
    note.id === base.id
      ? resizeNote(
          base,
          current.mode === 'start' ? 'start' : 'end',
          current.mode === 'start'
            ? Math.min(target, base.end - MIN_NOTE_LENGTH / 2)
            : Math.max(target, base.start + MIN_NOTE_LENGTH / 2),
          duration.value,
          0,
        )
      : note,
  )
}

function onPointerUp(event: PointerEvent) {
  const current = drag.value
  if (!current) return
  ;(event.target as HTMLCanvasElement).releasePointerCapture?.(event.pointerId)
  if (current.mode === 'marquee' && current.marqueeStart && current.marqueeEnd) {
    const left = Math.min(current.marqueeStart.x, current.marqueeEnd.x)
    const right = Math.max(current.marqueeStart.x, current.marqueeEnd.x)
    const topY = Math.min(current.marqueeStart.y, current.marqueeEnd.y)
    const bottomY = Math.max(current.marqueeStart.y, current.marqueeEnd.y)
    const hits = isCompose.value
      ? parts.value.flatMap((part) =>
          part.notes
            .filter((note) => {
              const rect = noteRect(
                note,
                pitchRange.value.max,
                rowHeight.value,
                pxPerSecond.value,
                MIDI_MIN_NOTE_PX,
              )
              return (
                rect.x + rect.width >= left &&
                rect.x <= right &&
                rect.y + rect.height >= topY &&
                rect.y <= bottomY
              )
            })
            .map((note) => note.id),
        )
      : draft.value
          .filter((note) => {
            const rect = noteRect(
              note,
              pitchRange.value.max,
              rowHeight.value,
              pxPerSecond.value,
              MIDI_MIN_NOTE_PX,
            )
            return (
              rect.x + rect.width >= left &&
              rect.x <= right &&
              rect.y + rect.height >= topY &&
              rect.y <= bottomY
            )
          })
          .map((note) => note.id)
    selection.value = Array.from(new Set([...selection.value, ...hits]))
  }
  drag.value = null
  if (
    isCompose.value &&
    current.mode !== 'marquee' &&
    current.mode !== 'erase' &&
    current.mode !== 'create' &&
    current.ids.length
  ) {
    const landed = locateNote(current.ids[0]!)
    if (landed) playBlip(landed.note.pitch, landed.note.velocity)
  }
  scheduleDraw()
}

function onPointerLeave() {
  // 指针移出画布时保留正在进行的拖动，由 pointerup/pointercancel 收尾。
  hoveredNoteId.value = null
  if (gridCanvasRef.value) gridCanvasRef.value.style.cursor = ''
}

function onDoubleClick(event: MouseEvent) {
  const point = canvasPoint(event)
  if (point.vy < RULER_HEIGHT) {
    zoomToFit()
    return
  }
  if (isCompose.value) {
    if (composeNoteAt(point)) return
    addComposeNote(timeOf(point.x), pitchOf(point.y), Math.max(snapStep.value || 0.25, 0.25))
    return
  }
  if (pitchNoteAt(point)) return
  addPitchNote(timeOf(point.x), pitchOf(point.y), Math.max(pitchGrid.value, 0.25))
}

/* ---------------------------------------------------------------- 力度条 */

function velocityPoint(event: PointerEvent) {
  const canvas = velocityCanvasRef.value
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  const vx = (event.clientX - rect.left) * (viewWidth.value / Math.max(1, rect.width))
  const vy = (event.clientY - rect.top) * (velocityHeight / Math.max(1, rect.height))
  return { x: vx + scrollLeft.value, y: vy }
}

function velocityTarget(x: number): { part: MidiPart; note: MidiComposeNote } | null {
  const seconds = xToTime(x, pxPerSecond.value)
  let best: { part: MidiPart; note: MidiComposeNote; distance: number } | null = null
  for (const part of parts.value) {
    if (part.mute) continue
    for (const note of part.notes) {
      const distance = Math.abs(note.start - seconds)
      if (distance <= 0.12 && (!best || distance < best.distance)) {
        best = { part, note, distance }
      }
    }
  }
  return best ? { part: best.part, note: best.note } : null
}

function applyVelocityAt(x: number, y: number) {
  const target = velocityTarget(x)
  if (!target) return
  const value = Math.round(((velocityHeight - 10 - y) / (velocityHeight - 14)) * 127)
  const velocity = Math.min(127, Math.max(1, value))
  if (target.note.velocity === velocity) return
  target.note.velocity = velocity
  markPreviewStale()
  scheduleDraw()
}

function onVelocityDown(event: PointerEvent) {
  const point = velocityPoint(event)
  if (!point) return
  const target = velocityTarget(point.x)
  if (!target) return
  pushUndo()
  if (!selection.value.includes(target.note.id)) selectOnly(target.note.id)
  drag.value = {
    mode: 'velocity',
    originX: point.x,
    originY: point.y,
    baseAll: [],
    baseSession: null,
    partId: target.part.id,
    ids: [target.note.id],
  }
  applyVelocityAt(point.x, point.y)
  ;(event.target as HTMLCanvasElement).setPointerCapture?.(event.pointerId)
}

function onVelocityMove(event: PointerEvent) {
  if (drag.value?.mode !== 'velocity') return
  const point = velocityPoint(event)
  if (!point) return
  applyVelocityAt(point.x, point.y)
}

function onVelocityUp(event: PointerEvent) {
  if (drag.value?.mode === 'velocity') {
    drag.value = null
    ;(event.target as HTMLCanvasElement).releasePointerCapture?.(event.pointerId)
  }
}

/* ---------------------------------------------------------------- 右键菜单 */

function onContextMenu(event: MouseEvent) {
  const point = canvasPoint(event)
  const hit = isCompose.value ? composeNoteAt(point) : pitchNoteAt(point)
  if (hit) {
    const noteId = 'note' in hit ? hit.note.id : hit.id
    if (!selection.value.includes(noteId)) selectOnly(noteId)
  }
  cursorTime.value = timeOf(point.x)
  const host = bodyRef.value?.getBoundingClientRect()
  contextMenu.visible = true
  contextMenu.x = event.clientX - (host?.left ?? 0) + 4
  contextMenu.y = event.clientY - (host?.top ?? 0) + 4
  contextMenu.time = timeOf(point.x)
  contextMenu.pitch = pitchOf(point.y)
  event.preventDefault()
  nextTick(clampContextMenu)
}

/** 菜单贴边时往回夹，避免超出钢琴卷帘可视区导致显示不全。 */
function clampContextMenu() {
  const menu = menuRef.value
  const host = bodyRef.value
  if (!menu || !host) return
  const margin = 6
  const maxX = Math.max(margin, host.clientWidth - menu.offsetWidth - margin)
  const maxY = Math.max(margin, host.clientHeight - menu.offsetHeight - margin)
  contextMenu.x = Math.max(margin, Math.min(contextMenu.x, maxX))
  contextMenu.y = Math.max(margin, Math.min(contextMenu.y, maxY))
}

function hideContextMenu() {
  contextMenu.visible = false
}

function onWindowPointerDown(event: PointerEvent) {
  if (!contextMenu.visible) return
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('.midi-menu')) return
  hideContextMenu()
}

function menuAddNote() {
  hideContextMenu()
  if (isCompose.value) {
    addComposeNote(contextMenu.time, contextMenu.pitch, Math.max(snapStep.value || 0.25, 0.25))
    return
  }
  addPitchNote(contextMenu.time, contextMenu.pitch, Math.max(pitchGrid.value, 0.25))
}

function menuDelete() {
  hideContextMenu()
  deleteSelected()
}

function menuCopy() {
  hideContextMenu()
  copySelected()
}

function menuPaste() {
  hideContextMenu()
  pasteClipboard(contextMenu.time)
}

function menuQuantize() {
  hideContextMenu()
  quantizeSelection()
}

function menuTranspose(semitones: number) {
  hideContextMenu()
  transposeSelection(semitones)
}

function menuVelocity(factor: number) {
  hideContextMenu()
  scaleVelocitySelection(factor)
}

function menuLegato() {
  hideContextMenu()
  legatoSelection()
}

function menuSplitAtPlayhead() {
  hideContextMenu()
  splitSelectionAtPlayhead()
}

function menuDuplicate() {
  hideContextMenu()
  duplicateSelection()
}

function menuSelectAll() {
  hideContextMenu()
  selectAll()
}

function menuUndo() {
  hideContextMenu()
  undo()
}

function menuRedo() {
  hideContextMenu()
  redo()
}
</script>

<style scoped>
.midi-mask {
  position: fixed;
  inset: 0;
  /* 高于页面主体（.layout-main z-index:1）、顶栏（z-index:50）、
     编辑器右键菜单（4000）与 Element Plus 弹层，避免被导航栏压住。 */
  z-index: 6000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(2, 5, 12, 0.72);
  backdrop-filter: blur(6px);
}

.midi-mask.fullscreen {
  padding: 0;
  background: rgba(2, 5, 12, 0.96);
}

.midi-dialog {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(1360px, 97vw);
  height: min(92vh, 940px);
  padding: 14px 16px 10px;
  border: 1px solid rgba(120, 180, 255, 0.18);
  border-radius: 18px;
  background: linear-gradient(160deg, rgba(14, 20, 32, 0.98), rgba(9, 13, 22, 0.98));
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
  color: #e8eefb;
  font-size: 12px;
}

.midi-dialog.fullscreen {
  width: 100vw;
  height: 100vh;
  max-height: none;
  padding: 10px 12px 8px;
  border: none;
  border-radius: 0;
  box-shadow: none;
}

.midi-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.midi-title {
  flex: 1 1 auto;
  min-width: 220px;
}

.midi-head h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0 4px;
  font-size: 18px;
}

.midi-scope {
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid rgba(94, 194, 255, 0.4);
  color: #8fd6ff;
  font-size: 11px;
  font-weight: 500;
}

.midi-scope.compose {
  border-color: rgba(142, 227, 107, 0.5);
  color: #8ee36b;
}

.midi-sub {
  margin: 0;
  color: #8ea0bd;
}

.eyebrow {
  margin: 0;
  color: #5ec2ff;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.midi-modes {
  display: flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid rgba(120, 180, 255, 0.16);
  border-radius: 11px;
  background: rgba(9, 14, 23, 0.85);
  height: fit-content;
}

.midi-modes button {
  padding: 5px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #9db0cc;
  font-size: 12px;
  cursor: pointer;
}

.midi-modes button.active {
  background: rgba(94, 194, 255, 0.18);
  color: #d8efff;
  font-weight: 600;
}

.midi-modes button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.midi-head-actions,
.midi-actions,
.midi-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.ghost,
.primary,
.mini {
  padding: 5px 11px;
  border: 1px solid rgba(120, 180, 255, 0.22);
  border-radius: 9px;
  background: rgba(18, 26, 40, 0.9);
  color: #cfe4ff;
  font-size: 12px;
  cursor: pointer;
}

.mini {
  padding: 2px 7px;
  border-radius: 7px;
  font-size: 11px;
}

.ghost.active,
.mini.active {
  border-color: rgba(94, 194, 255, 0.7);
  background: rgba(94, 194, 255, 0.22);
  color: #eaf8ff;
}

.mini.danger {
  border-color: rgba(255, 120, 150, 0.35);
  color: #ffb4c4;
}

.ghost:disabled,
.primary:disabled,
.mini:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.primary {
  border-color: rgba(94, 194, 255, 0.65);
  background: linear-gradient(140deg, rgba(60, 168, 255, 0.9), rgba(43, 122, 210, 0.9));
  color: #041320;
  font-weight: 600;
}

.midi-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid rgba(120, 180, 255, 0.12);
  border-radius: 12px;
  background: rgba(10, 16, 26, 0.8);
}

.midi-transport {
  padding-right: 8px;
  border-right: 1px solid rgba(120, 180, 255, 0.14);
}

.midi-play {
  min-width: 76px;
}

.midi-clock {
  min-width: 108px;
  font-variant-numeric: tabular-nums;
  color: #ffd166;
  font-size: 12px;
}

.midi-field {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #9db0cc;
}

.midi-field select,
.midi-field input[type='number'] {
  width: 74px;
  padding: 3px 6px;
  border: 1px solid rgba(120, 180, 255, 0.2);
  border-radius: 7px;
  background: rgba(8, 13, 22, 0.9);
  color: #e8eefb;
}

.midi-field input[type='range'] {
  width: 110px;
  accent-color: #5ec2ff;
}

.midi-field b {
  color: #8fd6ff;
  font-variant-numeric: tabular-nums;
}

.midi-toggle {
  padding-left: 4px;
  cursor: pointer;
}

.midi-toggle input {
  accent-color: #5ec2ff;
}

.midi-hint {
  margin-left: auto;
  color: #6d7f9c;
}

.midi-error,
.midi-tip {
  margin: 0;
  padding: 7px 10px;
  border-radius: 10px;
}

.midi-error {
  border: 1px solid rgba(255, 120, 120, 0.35);
  background: rgba(255, 90, 90, 0.12);
  color: #ffb4b4;
}

.midi-tip {
  border: 1px solid rgba(255, 209, 102, 0.3);
  background: rgba(255, 209, 102, 0.08);
  color: #ffd79a;
}

.midi-workspace {
  display: flex;
  flex: 1 1 auto;
  gap: 10px;
  min-height: 0;
}

.midi-parts {
  display: flex;
  flex-direction: column;
  flex: 0 0 242px;
  min-height: 0;
  border: 1px solid rgba(120, 180, 255, 0.14);
  border-radius: 12px;
  background: rgba(9, 14, 23, 0.85);
  overflow: hidden;
}

.midi-parts-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 9px;
  border-bottom: 1px solid rgba(120, 180, 255, 0.12);
  color: #8ea0bd;
  font-size: 11px;
}

.midi-part-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.midi-part {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  padding: 6px 7px;
  border: 1px solid rgba(120, 180, 255, 0.14);
  border-radius: 9px;
  background: rgba(14, 21, 33, 0.9);
  cursor: pointer;
}

.midi-part.active {
  border-color: rgba(94, 194, 255, 0.6);
  background: rgba(30, 48, 72, 0.9);
}

.midi-part.muted {
  opacity: 0.55;
}

.midi-part-color {
  flex: none;
  width: 8px;
  height: 26px;
  border-radius: 4px;
}

.midi-part-name {
  flex: 1 1 84px;
  min-width: 66px;
  padding: 2px 5px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #e8eefb;
  font-size: 12px;
}

.midi-part-name:hover,
.midi-part-name:focus {
  border-color: rgba(120, 180, 255, 0.3);
  background: rgba(8, 13, 22, 0.8);
}

.midi-part-count {
  flex: none;
  color: #6d7f9c;
  font-size: 10px;
}

.midi-part-inst {
  flex: 1 1 100%;
  width: 100%;
  padding: 2px 5px;
  border: 1px solid rgba(120, 180, 255, 0.18);
  border-radius: 6px;
  background: rgba(8, 13, 22, 0.9);
  color: #cfe4ff;
  font-size: 11px;
}

.midi-part-drum {
  flex: 1 1 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 5px;
  border: 1px dashed rgba(255, 209, 102, 0.32);
  border-radius: 6px;
  background: rgba(28, 22, 10, 0.55);
}

.midi-part-drum-tag {
  color: #ffd166;
  font-size: 11px;
}

.midi-parts-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 7px;
  border-top: 1px solid rgba(120, 180, 255, 0.12);
}

.midi-roll-wrap {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 200px;
  border: 1px solid rgba(120, 180, 255, 0.14);
  border-radius: 12px;
  background: #0b0f18;
  overflow: hidden;
}

.midi-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  color: #7d8fae;
  text-align: center;
  pointer-events: none;
  background: linear-gradient(180deg, rgba(8, 12, 20, 0.25), rgba(8, 12, 20, 0.55));
  z-index: 2;
}

.midi-busy {
  position: absolute;
  top: 8px;
  right: 10px;
  z-index: 5;
  padding: 4px 10px;
  border: 1px solid rgba(94, 194, 255, 0.4);
  border-radius: 999px;
  background: rgba(10, 20, 34, 0.94);
  color: #9fd8ff;
  font-size: 11px;
  pointer-events: none;
}

.midi-scroll {
  position: absolute;
  inset: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

.midi-scroll.with-velocity {
  bottom: 88px;
}

.midi-filler {
  position: relative;
}

.midi-view {
  position: sticky;
  top: 0;
  left: 0;
  z-index: 2;
  display: flex;
  align-items: flex-start;
}

.midi-keys {
  display: block;
  flex: none;
  border-right: 1px solid rgba(120, 180, 255, 0.16);
  background: #0b0f18;
}

.midi-grid {
  display: block;
  flex: none;
  touch-action: none;
  background: #0b0f18;
}

.midi-velocity {
  position: absolute;
  bottom: 0;
  display: block;
  touch-action: none;
  border-top: 1px solid rgba(120, 180, 255, 0.18);
  background: #0a0e16;
  z-index: 3;
}

.midi-menu {
  position: absolute;
  z-index: 6;
  display: flex;
  flex-direction: column;
  min-width: 196px;
  padding: 5px;
  border: 1px solid rgba(120, 180, 255, 0.24);
  border-radius: 10px;
  background: rgba(12, 18, 29, 0.98);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.5);
}

.midi-menu button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: #d7e6ff;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.midi-menu button:hover:not(:disabled) {
  background: rgba(94, 194, 255, 0.16);
}

.midi-menu button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.midi-menu-sep {
  display: block;
  height: 1px;
  margin: 4px 6px;
  background: rgba(120, 180, 255, 0.18);
}

.midi-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.midi-selected {
  display: flex;
  gap: 10px;
  color: #9db0cc;
  flex-wrap: wrap;
}

.midi-selected b {
  color: #5ec2ff;
}

.midi-dirty {
  color: #ffd166;
}

.midi-note {
  margin: 0;
  color: #6d7f9c;
  line-height: 1.5;
}

.midi-audio {
  display: none;
}
</style>
