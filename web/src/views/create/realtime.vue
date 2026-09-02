<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">// AI 翻唱 / 实时工程</p>
        <h1>实时翻唱工作台</h1>
        <p class="page-sub">读取系统混合音频，自动提取人声并流式输出变声结果</p>
      </div>
      <router-link to="/create" class="back-link"><el-icon><ArrowLeft /></el-icon>返回 AI 翻唱</router-link>
    </header>

    <div class="layout">
      <main class="config">
        <section class="card glass" data-guide="realtime-source">
          <div class="card-head"><span class="step-no">01</span><h2>播放源</h2></div>
          <div class="source-mode" role="group" aria-label="实时音频来源">
            <button :class="{ active: inputMode === 'system' }" :disabled="sessionActive" @click="setInputMode('system')">系统音频变声器</button>
            <button :class="{ active: inputMode === 'file' }" :disabled="sessionActive" @click="setInputMode('file')">歌曲文件实时播放</button>
          </div>
          <div v-if="inputMode === 'system'" class="system-audio-setup">
            <p class="system-audio-note">QQ 音乐保持原始歌曲（含人声和伴奏），把播放设备切换到虚拟音频线；应用从回环读取混合信号，自动分离人声后只替换人声，伴奏由原始信号恢复。</p>
            <label class="select-field"><span>系统混合音频输入</span><select v-model="systemInputId" :disabled="sessionActive"><option value="">选择承载 QQ 音乐的回环/虚拟线路</option><option v-for="device in systemInputDevices" :key="device.id" :value="device.id">{{ device.name }}</option></select></label>
            <label class="select-field"><span>变声输出设备</span><select v-model="systemOutputId" :disabled="sessionActive"><option value="">选择扬声器或耳机</option><option v-for="device in systemOutputDevices" :key="device.id" :value="device.id">{{ device.name }}</option></select></label>
            <button class="refresh-devices" :disabled="sessionActive" @click="loadSystemDevices"><el-icon><Refresh /></el-icon>刷新设备</button>
          </div>
          <button
            v-if="inputMode === 'file' && !song"
            class="dropzone"
            :class="{ 'is-dragover': songDragActive }"
            @click="pickSong"
            @dragenter.prevent="songDragActive = true"
            @dragover.prevent="songDragActive = true"
            @dragleave.prevent="songDragActive = false"
            @drop.prevent="onSongDrop"
          >
            <el-icon><UploadFilled /></el-icon>
            <span><b>选择或拖拽要实时播放的歌曲</b><small>先分离一次人声与伴奏，随后按时间顺序分块转换与播放</small></span>
          </button>
          <input ref="songInput" type="file" accept="audio/*,.mp3,.wav,.flac,.m4a,.ogg,.aac" hidden @change="onSongFileChange" />
          <div v-if="inputMode === 'file' && song" class="song-row">
            <span class="song-icon"><el-icon><Headset /></el-icon></span>
            <span class="song-copy"><b>{{ song.name }}</b><small>{{ song.hint }} · {{ formatTime(duration) }}</small></span>
            <button class="icon-btn" title="更换歌曲" :disabled="sessionActive" @click="pickSong"><el-icon><Refresh /></el-icon></button>
          </div>
          <div v-if="inputMode === 'file' && downloaded.length" class="source-library">
            <div class="source-library-head"><span>从已下载素材选择</span><router-link to="/music" class="text-action">资源获取 <el-icon><Right /></el-icon></router-link></div>
            <div class="source-library-list">
              <button v-for="item in downloaded" :key="item.path" class="source-item" :class="{ active: song?.path === item.path }" :title="item.name" @click="pickDownloaded(item)">
                <el-icon><Headset /></el-icon><span>{{ item.name }}</span><small>{{ item.size }}</small>
              </button>
            </div>
          </div>
        </section>

        <section class="card glass" data-guide="realtime-params">
          <div class="card-head"><span class="step-no">02</span><h2>演唱编排</h2></div>
          <p v-if="!realtimeModels.length" class="empty-note">暂无可用的 RVC / SeedVC 模型，请先在模型管理中导入。</p>
          <div v-else class="model-grid">
            <button
              v-for="model in realtimeModels"
              :key="model.id"
              class="model-item"
              :class="{ active: selectedId === model.id }"
              :disabled="sessionActive"
              @click="toggleModel(model.id)"
            >
              <span class="model-mark"><el-icon><Microphone /></el-icon></span>
              <span class="model-copy"><b>{{ model.name }}</b><small>{{ frameworkName(model.framework) }} · {{ model.sr }}</small></span>
              <el-icon v-if="selectedId === model.id" class="check"><Select /></el-icon>
            </button>
          </div>

          <div v-if="selectedId" class="model-settings">
            <template v-for="id in [selectedId]" :key="id">
            <div class="setting-title">
              <b>{{ modelName(id) }}</b>
              <span>{{ frameworkName(frameworkOf(id)) }}</span>
              <label class="manual-param-switch">
                <input v-model="manualParamsEnabled" type="checkbox" :disabled="sessionActive" />
                <span>全参数手动调整</span>
                <small>{{ manualParamsEnabled ? '已启用' : '基础可调 · 高级默认' }}</small>
              </label>
            </div>
            <div class="param-grid">
              <label class="range-row">
                <span>变调 <b>{{ paramsFor(id).pitch > 0 ? '+' : '' }}{{ paramsFor(id).pitch }} 半音</b></span>
                <input v-model.number="paramsFor(id).pitch" type="range" min="-12" max="12" step="1" :disabled="sessionActive" />
              </label>
              <label v-if="frameworkOf(id) === 'seed-vc'" class="range-row">
                <span>实时质量 <b>{{ seedVcSteps(paramsFor(id).diffusionRatio) }} 步</b></span>
                <input v-model.number="paramsFor(id).diffusionRatio" type="range" min="0" max="1" step="0.1" :disabled="sessionActive" />
              </label>
              <label v-if="frameworkOf(id) === 'rvc'" class="range-row">
                <span>检索率 <b>{{ paramsFor(id).indexRate.toFixed(2) }}</b></span>
                <input v-model.number="paramsFor(id).indexRate" type="range" min="0" max="1" step="0.05" :disabled="sessionActive" />
              </label>
              <label v-if="frameworkOf(id) === 'rvc'" class="range-row">
                <span>响度包络融合 <b>{{ paramsFor(id).rmsMix.toFixed(2) }}</b></span>
                <input v-model.number="paramsFor(id).rmsMix" type="range" min="0" max="1" step="0.05" :disabled="sessionActive" />
              </label>
              <label v-if="frameworkOf(id) === 'rvc'" class="range-row">
                <span>清辅音保护 <b>{{ paramsFor(id).protect.toFixed(2) }}</b></span>
                <input v-model.number="paramsFor(id).protect" type="range" min="0" max="0.5" step="0.01" :disabled="sessionActive" />
              </label>
              <label v-if="frameworkOf(id) === 'rvc'" class="range-row">
                <span>F0 滤波半径 <b>{{ paramsFor(id).filterRadius }}</b></span>
                <input v-model.number="paramsFor(id).filterRadius" type="range" min="0" max="7" step="1" :disabled="sessionActive" />
              </label>
            </div>
            <label v-if="manualParamsEnabled" class="range-row threshold-row">
              <span>F0 过滤阈值 <b>{{ paramsFor(id).f0FilterThreshold.toFixed(2) }}</b></span>
              <input v-model.number="paramsFor(id).f0FilterThreshold" type="range" min="0" max="1" step="0.01" :disabled="sessionActive || !manualParamsEnabled" />
            </label>
            <div class="select-grid">
              <label v-if="frameworkOf(id) === 'rvc'" class="select-field">
                <span>F0 算法</span>
                <select v-model="paramsFor(id).f0Method" :disabled="sessionActive">
                  <option v-for="method in rvcF0Methods" :key="method" :value="method">{{ method }}</option>
                </select>
              </label>
              <label class="select-field">
                <span>推理设备</span>
                <select v-model="paramsFor(id).device" :disabled="sessionActive">
                  <option v-for="option in deviceOptionsFor(id)" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <label v-if="frameworkOf(id) === 'rvc'" class="select-field">
                <span>模型版本</span>
                <select v-model="paramsFor(id).rvcVersion" :disabled="sessionActive">
                  <option value="v2">v2</option>
                  <option value="v1">v1</option>
                </select>
              </label>
            </div>
            <div class="pitch-guard-grid">
              <label class="toggle-field">
                <input v-model="paramsFor(id).autoHighPitchGuard" type="checkbox" :disabled="sessionActive" />
                <span><b>自动高音保护</b><small>高音先保共振峰降调，翻唱后升回原调</small></span>
              </label>
            </div>
            <label v-if="manualParamsEnabled && paramsFor(id).autoHighPitchGuard" class="range-row threshold-row">
              <span>高音保护轮次 <b>{{ paramsFor(id).highPitchGuardRounds }} 轮</b></span>
              <input v-model.number="paramsFor(id).highPitchGuardRounds" type="range" min="0" max="8" step="1" :disabled="sessionActive || !manualParamsEnabled" />
            </label>
            <div v-if="frameworkOf(id) === 'seed-vc'" class="reference-row">
              <span>目标音色参考</span>
              <button :disabled="sessionActive" @click="pickReference(id)">{{ baseName(paramsFor(id).referenceAudio) || '选择音频' }}</button>
            </div>
            </template>
          </div>
        </section>

        <section class="card glass">
          <div class="card-head"><span class="step-no">03</span><h2>实时参数</h2></div>
          <div class="control-grid">
            <label v-if="inputMode === 'file'" class="control"><span>输出缓冲 <b>{{ bufferSeconds }} 秒</b></span><input v-model.number="bufferSeconds" type="range" min="8" max="60" step="2" :disabled="sessionActive" /></label>
            <label class="control"><span>转换块 <b>{{ chunkSeconds }} 秒</b></span><input v-model.number="chunkSeconds" type="range" :min="inputMode === 'system' ? 4 : 4" :max="inputMode === 'system' ? 12 : 12" :step="inputMode === 'system' ? 2 : 1" :disabled="sessionActive" /></label>
            <label class="control"><span>转换人声 <b>{{ signedDb(vocalGain) }}</b></span><input v-model.number="vocalGain" type="range" min="-12" max="6" step="0.5" :disabled="sessionActive" /></label>
            <label v-if="inputMode === 'file'" class="control"><span>伴奏 <b>{{ signedDb(musicGain) }}</b></span><input v-model.number="musicGain" type="range" min="-12" max="6" step="0.5" :disabled="sessionActive" /></label>
            <div v-else class="direct-music"><el-icon><Connection /></el-icon><span><b>原始伴奏保持不变</b><small>从同一混合音频扣除提取的人声，再与变声人声按样本时钟混合</small></span></div>
          </div>
          <div class="select-grid realtime-selects">
            <label class="select-field">
              <span>人声分离模型</span>
                <select v-model="uvrModel" :disabled="sessionActive">
                <option v-for="model in uvrModels" :key="model" :value="model">{{ model }}</option>
              </select>
            </label>
          </div>
        </section>

        <button class="start-btn" :disabled="!canStart || sessionActive" @click="startSession">
          <el-icon><Aim /></el-icon><span>{{ sessionActive ? '实时工程运行中' : '启动实时翻唱' }}</span>
        </button>
      </main>

      <aside class="monitor">
        <section class="card glass monitor-card" data-guide="realtime-monitor">
          <div class="monitor-head"><span class="live-dot" :class="statusClass"></span><span>{{ statusLabel }}</span><b v-if="inputMode === 'system'">系统音频</b><b v-else>{{ formatTime(playhead) }} / {{ formatTime(status.duration || duration) }}</b></div>
          <div class="visualizer" :class="{ playing }"><i v-for="n in 42" :key="n" :style="barStyle(n)"></i></div>
          <div class="progress-track"><span :style="{ width: playPercent + '%' }"></span></div>
          <div v-if="inputMode === 'system'" class="buffer-line">
            <span>已处理音频</span><b>{{ Math.round(status.processed_seconds || 0) }}s</b>
          </div>
          <div v-else class="buffer-line">
            <span>转换缓冲</span><b>{{ Math.round(status.ready_seconds || 0) }}s / {{ Math.round(status.duration || duration) }}s</b>
          </div>
          <div v-if="inputMode !== 'system'" class="buffer-track"><span :style="{ width: processPercent + '%' }"></span></div>
          <div v-if="inputMode === 'system'" class="system-performance">
            <span>实时处理倍率</span>
            <b :class="{ slow: (status.realtime_factor || 0) > 1 }">{{ status.realtime_factor ? `${status.realtime_factor.toFixed(2)}x` : '--' }}</b>
          </div>
          <p class="monitor-message">{{ status.error || status.message || '配置完成后启动实时工程' }}</p>
          <p v-if="inputMode === 'system' && !status.input_silent && (status.realtime_factor || 0) > 1" class="monitor-warning">当前模型处理速度低于输入速度，输出会产生延迟；请增大转换块或改用更快的推理设备。</p>

          <div class="transport">
            <button class="round-btn" :disabled="!canTogglePlayback" :title="playing ? '暂停' : '继续'" @click="togglePlayback">
              <el-icon v-if="playing"><VideoPause /></el-icon><el-icon v-else><VideoPlay /></el-icon>
            </button>
            <button class="icon-btn" title="停止" :disabled="!sessionId" @click="stopSession"><el-icon><VideoPause /></el-icon></button>
            <button v-if="inputMode === 'file'" class="export-btn" :disabled="status.status !== 'done'" @click="exportResult"><el-icon><Download /></el-icon>导出成品</button>
          </div>
        </section>

        <section class="sync-panel">
          <div><el-icon><Clock /></el-icon><span><b>单时钟混音</b><small>每个转换块与同区间伴奏预先合成</small></span></div>
          <div><el-icon><Connection /></el-icon><span><b>样本级定长</b><small>模型输出逐块补齐或裁剪，不累计漂移</small></span></div>
          <div><el-icon><Microphone /></el-icon><span><b>块级对齐混音</b><small>人声转换完成后与对应伴奏块一起输出</small></span></div>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  Aim, ArrowLeft, Clock, Connection, Download, Headset, Microphone, Refresh, Right,
  Select, UploadFilled, VideoPause, VideoPlay,
} from '@element-plus/icons-vue'
import 'element-plus/es/components/message/style/css'
import { ElMessage } from 'element-plus'
import {
  api,
  isDesktop,
  type DownloadedMusic,
  type InferenceParams,
  type RealtimeCoverStatus,
} from '@/api'
import { useModelsStore } from '@/stores/models'
import { useSystemStore } from '@/stores/system'
import { useWorksStore } from '@/stores/works'
import { f0MethodsForFramework, normalizeF0Method } from '@/utils/f0'
import { storeToRefs } from 'pinia'

defineOptions({ name: 'RealtimeCoverPage' })

interface Song { name: string; path: string; hint: string }
interface LiveParams {
  pitch: number
  highPitchGuardRounds: number
  f0FilterThreshold: number
  diffusionRatio: number
  referenceAudio: string
  device: string
  f0Method: string
  indexRate: number
  rmsMix: number
  protect: number
  filterRadius: number
  rvcVersion: string
  autoHighPitchGuard: boolean
}

const modelsStore = useModelsStore()
const systemStore = useSystemStore()
const worksStore = useWorksStore()
const { models } = storeToRefs(modelsStore)
const inputMode = ref<'system' | 'file'>('system')
const song = ref<Song | null>(null)
const songInput = ref<HTMLInputElement | null>(null)
const songDragActive = ref(false)
const duration = ref(0)
const downloaded = ref<DownloadedMusic[]>([])
const selectedId = ref('')
const systemInputId = ref('')
const systemOutputId = ref('')
const systemInputDevices = ref<Array<{ id: string; name: string; kind: 'input' | 'output'; loopback?: boolean; system_mix?: boolean }>>([])
const systemOutputDevices = ref<Array<{ id: string; name: string; kind: 'input' | 'output'; loopback?: boolean }>>([])
const modelParams = reactive<Record<string, LiveParams>>({})
const manualParamsEnabled = ref(false)
const uvrModels = ['MDX-Net', 'Demucs v4', 'VR Arch']
const uvrModel = ref('MDX-Net')
const bufferSeconds = ref(8)
const chunkSeconds = ref(8)
const vocalGain = ref(0)
const musicGain = ref(0)
const sessionId = ref('')
const registeredWorkId = ref('')
const status = ref<RealtimeCoverStatus>({ id: '', status: 'missing' })
const playing = ref(false)
const playhead = ref(0)
const realtimeModels = computed(() => models.value.filter((model) => ['rvc', 'seed-vc'].includes(model.framework || '')))
const rvcF0Methods = f0MethodsForFramework('rvc')
const sessionActive = computed(() => ['preparing', 'buffering', 'ready', 'live', 'done'].includes(status.value.status))
const canStart = computed(() => {
  if (!selectedId.value) return false
  if (inputMode.value === 'file' && !song.value) return false
  if (inputMode.value === 'system' && (!systemInputId.value || !systemOutputId.value)) return false
  return frameworkOf(selectedId.value) !== 'seed-vc' || Boolean(paramsFor(selectedId.value).referenceAudio)
})
const canTogglePlayback = computed(() => Boolean(audioContext) && ['ready', 'done'].includes(status.value.status))
const playPercent = computed(() => Math.min(100, (playhead.value / Math.max(1, status.value.duration || duration.value)) * 100))
const processPercent = computed(() => Math.min(100, ((status.value.processed_seconds || 0) / Math.max(1, status.value.duration || duration.value)) * 100))
const statusClass = computed(() => ({ active: sessionActive.value, failed: status.value.status === 'failed', done: status.value.status === 'done' }))
const statusLabel = computed(() => {
  const labels: Partial<Record<RealtimeCoverStatus['status'], string>> = {
    preparing: inputMode.value === 'system' ? '加载变声模型' : '分离音轨',
    buffering: '预缓冲',
    ready: playing.value ? '实时播放' : '缓冲就绪',
    live: inputMode.value === 'system' ? '混合音频流式变声中' : '独立人声变声中',
    done: playing.value ? '实时播放' : '转换完成',
    failed: '转换失败',
    stopped: '已停止',
  }
  return labels[status.value.status] || '待启动'
})

let pollTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null
let audioContext: AudioContext | null = null
let nextFetchIndex = 0
let nextScheduleTime = 0
let playbackOrigin = 0
let scheduledDuration = 0
const scheduledSources: AudioBufferSourceNode[] = []

function frameworkOf(id: string) { return models.value.find((model) => model.id === id)?.framework || '' }
function frameworkName(framework?: string) { return framework === 'seed-vc' ? 'SeedVC' : 'RVC' }
function modelName(id: string) { return models.value.find((model) => model.id === id)?.name || id }
function baseName(path: string) { return path.split(/[/\\]/).pop() || path }
function signedDb(value: number) { return `${value > 0 ? '+' : ''}${value.toFixed(1)} dB` }
function formatTime(seconds = 0) { const value = Math.max(0, Math.floor(seconds)); return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}` }
function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message
  if (typeof error === 'string' && error.trim()) return error
  if (error && typeof error === 'object') {
    const value = error as { message?: unknown; error?: unknown; detail?: unknown }
    for (const candidate of [value.message, value.error, value.detail]) {
      if (typeof candidate === 'string' && candidate.trim()) return candidate
    }
  }
  return fallback
}
function paramsFor(id: string) {
  return modelParams[id] ||= {
    pitch: 0,
    highPitchGuardRounds: 3,
    f0FilterThreshold: 0.05,
    diffusionRatio: 0.5,
    referenceAudio: '',
    device: 'auto',
    // RMVPE is the compatible default for file-mode conversion. PM remains
    // available as an explicit low-latency option for system audio devices.
    f0Method: 'rmvpe',
    indexRate: 0.75,
    rmsMix: 0.25,
    protect: 0.33,
    filterRadius: 3,
    rvcVersion: 'v2',
    autoHighPitchGuard: true,
  }
}
function seedVcSteps(ratio: number) { return Math.round(4 + Math.max(0, Math.min(1, ratio)) * 6) }
function deviceOptionsFor(id: string) {
  return systemStore.optionsForFramework([frameworkOf(id), 'uvr'])
}
function toggleModel(id: string) {
  paramsFor(id)
  selectedId.value = id
}

function setInputMode(mode: 'system' | 'file') {
  if (sessionActive.value) return
  inputMode.value = mode
  if (mode === 'system') {
    chunkSeconds.value = Math.min(12, Math.max(4, chunkSeconds.value))
  } else {
    bufferSeconds.value = Math.max(8, bufferSeconds.value)
    chunkSeconds.value = Math.max(4, chunkSeconds.value)
  }
}

async function loadSystemDevices() {
  try {
    const devices = await api.listSystemAudioDevices()
    systemInputDevices.value = devices.filter((device) => device.kind === 'input' && device.system_mix)
    systemOutputDevices.value = devices.filter((device) => device.kind === 'output')
    if (!systemInputId.value) systemInputId.value = systemInputDevices.value[0]?.id || ''
    if (!systemOutputId.value) systemOutputId.value = systemOutputDevices.value[0]?.id || ''
    if (!systemInputDevices.value.length) ElMessage.warning('请把 QQ 音乐输出切换到虚拟音频线后再刷新设备')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '系统音频设备读取失败')
  }
}

async function pickSong() {
  if (!isDesktop()) {
    songInput.value?.click()
    return
  }
  const path = await api.pickAudioFile()
  if (!path) return
  song.value = { path, name: baseName(path), hint: '本地音频已选择' }
  duration.value = await api.getAudioDuration(path)
}

function readFileDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('无法读取拖入的音频文件'))
    reader.readAsDataURL(file)
  })
}

async function setSongFromFile(file: File | undefined) {
  if (!file) return
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.warning('音频文件不能超过 50MB')
    return
  }
  if (!file.type.startsWith('audio/') && !/\.(mp3|wav|flac|m4a|ogg|aac|opus|wma)$/i.test(file.name)) {
    ElMessage.warning('请选择音频文件')
    return
  }
  let path = String((file as File & { path?: string }).path || '').trim()
  if (!path && isDesktop()) {
    try {
      path = String(await api.importAudioData(file.name, await readFileDataUrl(file)) || '').trim()
    } catch {
      ElMessage.error('无法导入拖入的音频文件')
      return
    }
  }
  if (!path) path = file.name
  song.value = { name: file.name, path, hint: '已导入音频' }
  void loadSongDuration()
}

function onSongFileChange(event: Event) {
  void setSongFromFile((event.target as HTMLInputElement).files?.[0])
  ;(event.target as HTMLInputElement).value = ''
}

function onSongDrop(event: DragEvent) {
  songDragActive.value = false
  void setSongFromFile(event.dataTransfer?.files?.[0])
}

function pickDownloaded(item: DownloadedMusic) {
  song.value = { name: item.name, path: item.path, hint: '已下载素材' }
  void loadSongDuration()
}

async function loadSongDuration() {
  if (!song.value) return
  duration.value = await api.getAudioDuration(song.value.path)
}

async function pickReference(id: string) {
  const path = await api.pickAudioFile()
  if (path) paramsFor(id).referenceAudio = path
}

function inferenceParams(id: string): InferenceParams {
  const values = paramsFor(id)
  const effective = manualParamsEnabled.value
      ? values
    : {
        ...values,
        highPitchGuardRounds: 3,
        f0FilterThreshold: 0.05,
      }
  const common = {
    pitch: Math.round(effective.pitch),
    device: effective.device,
    uvr_model: uvrModel.value,
    auto_high_pitch_guard: effective.autoHighPitchGuard,
    high_pitch_guard_rounds: Math.max(0, Math.min(8, Math.round(effective.highPitchGuardRounds ?? 3))),
    f0_filter_threshold: effective.f0FilterThreshold,
    manual_params_enabled: manualParamsEnabled.value,
  }
  return frameworkOf(id) === 'seed-vc'
    ? {
        ...common,
        diffusion_ratio: effective.diffusionRatio,
        reference_audio: values.referenceAudio,
      }
    : {
        ...common,
        f0_method: normalizeF0Method('rvc', effective.f0Method),
        index_rate: effective.indexRate,
        rms_mix: effective.rmsMix,
        protect: effective.protect,
        filter_radius: Math.round(effective.filterRadius),
        rvc_version: effective.rvcVersion,
      }
}

async function startSession() {
  if (!canStart.value) return
  if (inputMode.value === 'system' && systemInputId.value === systemOutputId.value) {
    ElMessage.error('人声输入和输出设备不能相同，请选择不同的回环输入与播放输出设备')
    return
  }
  resetScheduler()
  if (inputMode.value === 'file') {
    audioContext = new AudioContext()
    await audioContext.resume()
  }
  try {
    const payload = {
      source_path: inputMode.value === 'file' ? song.value!.path : undefined,
      input_mode: inputMode.value,
      title: inputMode.value === 'file' ? song.value!.name.replace(/\.[^.]+$/, '') : '系统音频实时变声',
      mode: 'single' as const,
      model_id: selectedId.value,
      params: inferenceParams(selectedId.value),
      chunk_seconds: chunkSeconds.value,
      buffer_seconds: bufferSeconds.value,
      vocal_gain_db: vocalGain.value,
      instrumental_gain_db: musicGain.value,
      input_device: systemInputId.value,
      output_device: systemOutputId.value,
      sample_rate: 44100,
    }
    status.value = inputMode.value === 'system'
      ? await api.startSystemAudioRealtime(payload)
      : await api.startRealtimeCover(payload)
    sessionId.value = status.value.id
    registeredWorkId.value = ''
    startPolling()
  } catch (error) {
    ElMessage.error(errorMessage(error, '无法启动实时翻唱'))
    if (audioContext) await audioContext.close()
    audioContext = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => void pollStatus(), 650)
  clockTimer = setInterval(() => {
    if (audioContext && playing.value) playhead.value = Math.max(0, Math.min(scheduledDuration, audioContext.currentTime - playbackOrigin))
  }, 100)
  void pollStatus()
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
  pollTimer = null
  clockTimer = null
}

async function pollStatus() {
  if (!sessionId.value) return
  status.value = await api.getRealtimeCoverStatus(sessionId.value)
  if (status.value.status === 'done' && status.value.work_id && status.value.work_id !== registeredWorkId.value) {
    registeredWorkId.value = status.value.work_id
    await worksStore.load()
    ElMessage.success('实时翻唱已保存到“我的作品”')
  }
  if (['ready', 'done'].includes(status.value.status)) await fetchReadyChunks()
  if (status.value.status === 'failed') { stopPolling(); ElMessage.error(status.value.error || '实时转换失败') }
}

async function fetchReadyChunks() {
  if (!audioContext) return
  const ready = status.value.ready_chunks || 0
  while (nextFetchIndex < ready) {
    const item = await api.getRealtimeCoverChunk(sessionId.value, nextFetchIndex)
    if (!item.ok || !item.audio) break
    const encoded = item.audio.split(',', 2)[1]
    if (!encoded) break
    const binary = atob(encoded)
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
    const buffer = await audioContext.decodeAudioData(bytes.buffer)
    const source = audioContext.createBufferSource()
    source.buffer = buffer
    source.connect(audioContext.destination)
    if (!nextScheduleTime) {
      nextScheduleTime = audioContext.currentTime + 0.12
      playbackOrigin = nextScheduleTime
    }
    if (nextScheduleTime < audioContext.currentTime + 0.02) {
      nextScheduleTime = audioContext.currentTime + 0.08
      playbackOrigin = nextScheduleTime - playhead.value
    }
    source.start(nextScheduleTime)
    scheduledSources.push(source)
    const blockDuration = item.duration || buffer.duration
    nextScheduleTime += blockDuration
    scheduledDuration += blockDuration
    nextFetchIndex += 1
    source.onended = () => {
      const isLastScheduled = source === scheduledSources[scheduledSources.length - 1]
      if (isLastScheduled && nextFetchIndex >= (status.value.total_chunks || Number.MAX_SAFE_INTEGER)) {
        playing.value = false
        playhead.value = status.value.duration || duration.value
      }
    }
    playing.value = audioContext.state === 'running'
  }
}

async function togglePlayback() {
  if (!audioContext) return
  if (audioContext.state === 'running') { await audioContext.suspend(); playing.value = false }
  else { await audioContext.resume(); playing.value = true }
}

async function stopSession() {
  const id = sessionId.value
  if (id) await api.stopRealtimeCover(id)
  stopPolling()
  scheduledSources.forEach((source) => { try { source.stop() } catch { /* already stopped */ } })
  scheduledSources.length = 0
  if (audioContext) await audioContext.close()
  audioContext = null
  playing.value = false
  sessionId.value = ''
  status.value = { id: '', status: 'stopped', message: '实时播放已停止，可以开始新的工程' }
  resetScheduler()
}

function resetScheduler() {
  nextFetchIndex = 0
  nextScheduleTime = 0
  playbackOrigin = 0
  scheduledDuration = 0
  playhead.value = 0
}

async function exportResult() {
  if (!sessionId.value) return
  const destination = await api.exportRealtimeCover(sessionId.value)
  if (destination) ElMessage.success(`已导出到：${destination}`)
}

function barStyle(index: number) { return { height: `${16 + Math.abs(Math.sin(index * 0.73)) * 74}%`, animationDelay: `${index * 0.035}s` } }

onMounted(async () => {
  await Promise.all([
    modelsStore.load(),
    systemStore.load(),
    api.listMusic().then((items) => { downloaded.value = items }),
  ])
  await loadSystemDevices()
  const first = realtimeModels.value[0]
  if (first) { selectedId.value = first.id; paramsFor(first.id) }
})

onUnmounted(() => {
  const id = sessionId.value
  const canCleanup = ['done', 'failed'].includes(status.value.status)
  void stopSession().then(() => id && canCleanup ? api.cleanupRealtimeCover(id) : false)
})
</script>

<style scoped>
.page { --accent: var(--xb-primary, #00d5ff); --text-primary: var(--xb-text, #f4f7fb); --text-muted: var(--xb-muted, #8f9aaa); --border-color: var(--xb-border, #344151); --app-bg: var(--xb-bg, #0c1118); position: relative; z-index: 1; max-width: 1320px; margin: 24px auto 40px; padding: 28px 24px 60px; border: 1px solid var(--xb-border, #344151); border-radius: 14px; background: color-mix(in srgb, var(--xb-bg, #0c1118) 78%, transparent); box-shadow: 0 18px 60px rgba(20, 35, 70, .12); backdrop-filter: blur(18px); }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.eyebrow { margin: 0 0 6px; color: var(--accent, #00d5ff); font-size: 12px; font-weight: 700; }
h1 { margin: 0; font-size: 30px; letter-spacing: 0; } .page-sub { margin: 8px 0 0; color: var(--text-muted, #8f9aaa); }
.back-link, .text-action { display: inline-flex; align-items: center; gap: 7px; color: var(--text-muted, #a7b0bf); background: none; border: 0; text-decoration: none; cursor: pointer; }
.layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .8fr); gap: 20px; align-items: start; }
.config { display: grid; gap: 16px; } .card { padding: 20px; border-radius: 8px; } .page .glass { background: var(--xb-panel, rgba(10, 20, 40, .45)); border: 1px solid var(--xb-border, #344151); backdrop-filter: blur(16px); }
.card-head { min-height: 28px; display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.card-head h2 { margin: 0; font-size: 16px; letter-spacing: 0; } .card-head .text-action { margin-left: auto; color: var(--accent, #00d5ff); }
.step-no { display: grid; place-items: center; min-width: 28px; height: 24px; padding: 0 6px; border: 1px solid color-mix(in srgb, var(--accent, #00d5ff) 45%, transparent); color: var(--accent, #00d5ff); font-size: 11px; }
.dropzone { width: 100%; min-height: 112px; display: flex; justify-content: center; align-items: center; gap: 14px; border: 1px dashed var(--border-color, #344151); background: color-mix(in srgb, var(--accent, #00d5ff) 4%, transparent); color: inherit; cursor: pointer; }
.dropzone.is-dragover { border-color: var(--accent, #00d5ff); background: color-mix(in srgb, var(--accent, #00d5ff) 14%, transparent); }
.dropzone > .el-icon { font-size: 30px; color: var(--accent, #00d5ff); } .dropzone span { display: grid; text-align: left; gap: 5px; } small { color: var(--text-muted, #8f9aaa); font-size: 12px; }
.song-row { display: flex; align-items: center; gap: 12px; min-height: 64px; padding: 10px; border: 1px solid var(--border-color, #344151); }
.song-icon, .model-mark { display: grid; place-items: center; width: 42px; height: 42px; color: var(--accent, #00d5ff); background: color-mix(in srgb, var(--accent, #00d5ff) 12%, transparent); }
.song-copy, .model-copy { min-width: 0; flex: 1; display: grid; gap: 4px; text-align: left; } .song-copy b, .model-copy b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-library { display: grid; gap: 10px; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border-color); }
.source-library-head { display: flex; justify-content: space-between; align-items: center; color: var(--text-muted); font-size: 12px; }
.source-library-head .text-action { color: var(--accent); font-size: 12px; }
.source-mode { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-bottom: 14px; padding: 4px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 82%, transparent); }
.source-mode button { min-height: 38px; border: 0; background: transparent; color: var(--text-muted); cursor: pointer; }
.source-mode button.active { background: color-mix(in srgb, var(--accent) 13%, transparent); color: var(--text-primary); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent); }
.system-performance { display: flex; justify-content: space-between; margin-top: 10px; color: var(--text-muted); font-size: 12px; }
.system-performance b { color: var(--accent); font-variant-numeric: tabular-nums; }
.system-performance b.slow, .monitor-warning { color: #ffae00; }
.monitor-warning { margin: 6px 0 0; font-size: 12px; line-height: 1.5; }
.system-audio-setup { display: grid; grid-template-columns: 1fr 1fr auto; gap: 10px; align-items: end; margin-bottom: 14px; }
.system-audio-note { grid-column: 1 / -1; margin: 0; padding: 10px 12px; border-left: 2px solid #ffae00; color: var(--text-muted); font-size: 12px; line-height: 1.55; }
.refresh-devices { height: 34px; display: inline-flex; align-items: center; gap: 5px; padding: 0 10px; border: 1px solid var(--border-color); background: transparent; color: var(--text-muted); cursor: pointer; white-space: nowrap; }
.source-library-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.source-item { min-width: 0; display: flex; align-items: center; gap: 8px; padding: 9px 10px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 74%, transparent); color: inherit; text-align: left; cursor: pointer; }
.source-item:hover, .source-item.active { border-color: var(--accent); color: var(--text-primary); background: color-mix(in srgb, var(--accent) 10%, var(--xb-panel)); }
.source-item .el-icon { flex: 0 0 auto; color: var(--accent); } .source-item span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; } .source-item small { margin-left: auto; font-size: 10px; white-space: nowrap; }
.icon-btn { flex: 0 0 auto; display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid var(--border-color, #344151); background: transparent; color: inherit; cursor: pointer; }
.icon-btn.danger { color: #ff647c; } button:disabled { opacity: .45; cursor: not-allowed; }
.model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.model-item { min-width: 0; display: flex; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--border-color, #344151); background: color-mix(in srgb, var(--xb-panel, #172033) 78%, transparent); color: inherit; cursor: pointer; }
.model-item.active { border-color: color-mix(in srgb, var(--accent, #00d5ff) 65%, transparent); background: color-mix(in srgb, var(--accent, #00d5ff) 7%, transparent); }
.check { color: var(--accent, #00d5ff); } .empty-note, .section-note { margin: 0; color: var(--text-muted, #8f9aaa); font-size: 13px; }
.model-settings { display: grid; gap: 10px; margin-top: 12px; padding: 12px; border-left: 2px solid var(--accent, #00d5ff); background: color-mix(in srgb, var(--xb-panel, #172033) 88%, transparent); }
.pitch-guard-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-color); }
.toggle-field { min-height: 42px; display: flex; align-items: center; gap: 9px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border-color)); border-left: 3px solid var(--accent); border-radius: 7px; background: color-mix(in srgb, var(--accent) 6%, transparent); cursor: pointer; }
.toggle-field input { width: 16px; height: 16px; accent-color: var(--accent); }
.toggle-field span { display: grid; gap: 2px; }
.toggle-field small { font-size: 11px; }
.compact-range { padding: 8px 10px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 72%, transparent); }
.setting-title, .range-row > span, .reference-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.setting-title span { color: var(--text-muted, #8f9aaa); font-size: 11px; } .range-row { display: grid; gap: 7px; font-size: 13px; }
.manual-param-switch { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; padding: 6px 9px; border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border-color)); border-radius: 8px; background: color-mix(in srgb, var(--accent) 7%, transparent); color: var(--text-primary); font-size: 12px; font-weight: 650; white-space: nowrap; }
.manual-param-switch input { accent-color: var(--accent); }
.manual-param-switch small { color: var(--text-muted); }
.param-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 22px; }
.direct-music { display: flex; align-items: center; gap: 9px; min-height: 42px; color: var(--accent); }
.direct-music span { display: grid; gap: 3px; }
.direct-music small { color: var(--text-muted); }
.select-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.realtime-selects { margin-top: 12px; }
.select-field { min-width: 0; display: grid; gap: 6px; color: var(--text-muted, #8f9aaa); font-size: 12px; }
.select-field select { width: 100%; height: 34px; padding: 0 9px; border: 1px solid var(--xb-border, var(--border-color, #344151)); border-radius: 4px; background: var(--xb-panel, color-mix(in srgb, var(--app-bg, #0c1118) 92%, #fff)); color: var(--xb-text, var(--text-primary, #f4f7fb)); }
.select-field select option { background: var(--xb-panel, #171c25); color: var(--xb-text, #f4f7fb); }
input[type='range'] { width: 100%; accent-color: var(--accent, #00d5ff); } .reference-row { font-size: 13px; }
.reference-row button { border: 1px solid var(--border-color, #344151); background: transparent; color: inherit; padding: 7px 10px; cursor: pointer; }
.timeline-actions { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.lyric-toolbar { display: grid; gap: 10px; margin-top: 14px; }
.lyric-search { display: flex; align-items: center; gap: 8px; min-height: 36px; padding-left: 10px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 70%, transparent); }
.lyric-search .el-icon { color: var(--accent); } .lyric-search input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; color: var(--text-primary); } .lyric-search .lyric-index { flex: 0 0 42px; height: 28px; padding: 0 5px; border-left: 1px solid var(--border-color); border-right: 1px solid var(--border-color); } .lyric-source { flex: 0 0 108px; height: 34px; padding: 0 6px; border: 0; border-right: 1px solid var(--border-color); background: transparent; color: var(--text-primary); } .lyric-source option { background: var(--xb-panel); color: var(--text-primary); } .lyric-search button { height: 34px; padding: 0 12px; border: 0; border-left: 1px solid var(--border-color); background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); cursor: pointer; }
.timeline-preview { position: relative; height: 28px; margin: 15px 0 12px; overflow: hidden; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 62%, transparent); }
.timeline-preview-block { position: absolute; top: 3px; bottom: 3px; min-width: 2px; border-radius: 2px; background: var(--accent); opacity: .72; } .timeline-preview-block.chorus { background: linear-gradient(90deg, var(--accent), var(--xb-accent)); } .timeline-preview-block.idle { background: var(--text-muted); opacity: .25; }
.lyric-assign-card { overflow: hidden; }
.assign-description { margin: -5px 0 14px; color: var(--text-muted); font-size: 13px; }
.lyric-fetch-row { display: grid; grid-template-columns: minmax(180px, 1fr) 54px 132px auto auto; gap: 9px; align-items: center; }
.lyric-fetch-row input, .lyric-fetch-row select { min-width: 0; height: 38px; padding: 0 12px; border: 1px solid var(--border-color); border-radius: 8px; background: color-mix(in srgb, var(--xb-panel) 86%, transparent); color: var(--text-primary); outline: 0; }
.lyric-fetch-row input:focus, .lyric-fetch-row select:focus { border-color: var(--accent); }
.fetch-lyrics-btn, .import-lyrics-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 38px; padding: 0 14px; border: 1px solid var(--accent); border-radius: 8px; background: color-mix(in srgb, var(--accent) 9%, transparent); color: var(--accent); white-space: nowrap; cursor: pointer; }
.import-lyrics-btn { border-radius: 999px; }
.lyric-assign-card .align-bar { display: flex; align-items: center; gap: 12px; min-height: 48px; margin-top: 14px; padding: 0 14px; border: 1px solid color-mix(in srgb, var(--xb-warn, #ffae00) 42%, transparent); border-radius: 10px; color: var(--xb-warn, #ffae00); }
.lyric-assign-card .align-bar label { margin-left: auto; color: var(--text-muted); white-space: nowrap; } .lyric-assign-card .align-bar input { width: 180px; accent-color: var(--accent); }
.lyric-assign-card .assign-quick { margin: 16px 0 10px; } .lyric-assign-card .assign-quick > button { min-height: 32px; padding: 0 12px; border: 1px solid var(--accent); border-radius: 999px; background: color-mix(in srgb, var(--accent) 8%, transparent); color: var(--accent); cursor: pointer; } .lyric-assign-card .assign-quick > button:disabled { opacity: .45; cursor: not-allowed; }
.lyric-assign-card .assign-tip { margin-left: auto; color: var(--text-muted); }
.lyric-assign-card .timeline-wrap { margin: 12px 0 15px; padding: 13px 14px 11px; border: 1px solid var(--border-color); border-radius: 12px; background: color-mix(in srgb, var(--xb-panel) 72%, transparent); }
.lyric-assign-card .timeline-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; } .lyric-assign-card .tl-title { display: inline-flex; align-items: center; gap: 7px; color: var(--text-primary); font-weight: 700; font-size: 14px; }
.tl-tools { display: inline-flex; align-items: center; gap: 5px; }
.tl-tool, .tl-enlarge { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 32px; height: 32px; padding: 0 8px; border: 1px solid var(--border-color); border-radius: 7px; background: color-mix(in srgb, var(--xb-panel) 78%, transparent); color: var(--text-muted); cursor: pointer; }
.tl-enlarge { border-color: var(--accent); color: var(--accent); } .tl-tool:hover:not(:disabled), .tl-enlarge:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); } .tl-tool:disabled, .tl-enlarge:disabled { opacity: .4; cursor: not-allowed; }
.lyric-assign-card .tl-legend, .timeline-editor-dialog .tl-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; } .lyric-assign-card .tl-leg, .timeline-editor-dialog .tl-leg { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 12px; } .lyric-assign-card .tl-leg-dot, .timeline-editor-dialog .tl-leg-dot { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; color: #fff; font-size: 10px; font-weight: 700; } .lyric-assign-card .tl-leg-dot.idle, .timeline-editor-dialog .tl-leg-dot.idle { border: 1px solid var(--text-muted); background: transparent; }
.tl-ruler-simple { position: relative; width: 100%; height: 18px; color: var(--text-muted); font: 10px ui-monospace, monospace; font-variant-numeric: tabular-nums; } .tl-ruler-simple span { position: absolute; transform: translateX(-50%); white-space: nowrap; } .tl-ruler-simple span:first-child { transform: none; } .tl-ruler-simple span:last-child { transform: translateX(-100%); }
.lyric-assign-card .tl-mini { position: relative; width: 100%; max-width: 100%; min-width: 0; height: 34px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 6px; background: repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent) 5%, transparent) 0 1px, transparent 1px 25%); }
.lyric-assign-card .tl-mini-block { position: absolute; top: 3px; bottom: 3px; min-width: 3px; overflow: hidden; border: 1px solid color-mix(in srgb, #fff 22%, transparent); border-radius: 5px; box-shadow: inset 0 0 0 1px color-mix(in srgb, #fff 12%, transparent); }
.lyric-assign-card .tl-mini-block.is-idle { background: var(--text-muted); opacity: .28; } .lyric-assign-card .tl-mini-block.is-chorus { box-shadow: inset 0 0 0 1px color-mix(in srgb, #fff 45%, transparent); }
.timeline-zoom-dialog { min-width: 0; }
.timeline-zoom-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.zoom-actions { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font: 12px ui-monospace, monospace; }
.zoom-btn { display: grid; place-items: center; width: 30px; height: 30px; border: 1px solid var(--border-color); border-radius: 7px; background: transparent; color: var(--text-primary); cursor: pointer; }
.zoom-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); } .zoom-btn:disabled { opacity: .4; cursor: not-allowed; }
.timeline-zoom-scroll { width: 100%; overflow-x: auto; overflow-y: hidden; padding-bottom: 8px; }
.timeline-zoom-inner { min-width: 100%; }
.timeline-zoom-ruler { position: relative; height: 24px; color: var(--text-muted); font: 11px ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.timeline-zoom-ruler span { position: absolute; transform: translateX(-50%); white-space: nowrap; } .timeline-zoom-ruler span:first-child { transform: none; } .timeline-zoom-ruler span:last-child { transform: translateX(-100%); }
.timeline-zoom-track { position: relative; height: 86px; min-width: 640px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 8px; background: repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent) 6%, transparent) 0 1px, transparent 1px 25%); }
.timeline-zoom-block { position: absolute; top: 12px; bottom: 12px; min-width: 8px; display: flex; align-items: center; justify-content: space-between; gap: 4px; overflow: hidden; padding: 0 4px; border: 1px solid color-mix(in srgb, #fff 25%, transparent); border-radius: 5px; color: #fff; font-size: 11px; font-weight: 650; text-shadow: 0 1px 2px rgba(0, 0, 0, .5); white-space: nowrap; cursor: pointer; user-select: none; }
.timeline-block-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.timeline-grip { z-index: 1; width: 6px; height: 30px; flex: 0 0 auto; border-left: 2px solid rgba(255, 255, 255, .8); cursor: ew-resize; }
.timeline-grip.right { border-left: 0; border-right: 2px solid rgba(255, 255, 255, .8); }
.timeline-zoom-block .timeline-grip { position: absolute; top: 0; bottom: 0; width: 8px; height: auto; z-index: 3; flex: none; touch-action: none; }
.timeline-zoom-block .timeline-grip:not(.right) { left: -1px; border-radius: 5px 0 0 5px; }
.timeline-zoom-block .timeline-grip.right { right: -1px; border-radius: 0 5px 5px 0; }
.timeline-zoom-block .timeline-grip::after { content: ''; position: absolute; top: 50%; left: 50%; width: 2px; height: 56%; transform: translate(-50%, -50%); border-radius: 2px; background: rgba(255, 255, 255, .82); opacity: .75; }
.timeline-zoom-block.dragging { z-index: 5; filter: brightness(1.16); box-shadow: 0 5px 14px rgba(0, 0, 0, .25), inset 0 0 0 1px rgba(255, 255, 255, .4); }
.timeline-zoom-block.idle { background: var(--text-muted); opacity: .3; } .timeline-zoom-block.chorus { box-shadow: inset 0 0 0 1px color-mix(in srgb, #fff 50%, transparent); }
.lyric-assign-card .tl-hint { margin: 8px 0 0; color: var(--text-muted); font-size: 11px; }
.timeline-editor-dialog { display: grid; gap: 10px; min-width: 0; }
.timeline-editor-dialog .timeline-ruler { height: 20px; }
.timeline-editor-dialog .timeline-track { height: 82px; border-radius: 8px; background: repeating-linear-gradient(90deg, color-mix(in srgb, var(--xb-fill-rgb) 8%, transparent) 0 1px, transparent 1px 25%); }
.timeline-edit-list { display: grid; gap: 5px; max-height: 46vh; margin-top: 8px; overflow-y: auto; }
.timeline-edit-row { display: grid; grid-template-columns: 270px minmax(160px, 1fr) 130px 32px; align-items: center; gap: 12px; min-height: 50px; padding: 7px 9px; border-radius: 8px; background: color-mix(in srgb, var(--xb-panel) 72%, transparent); }
.timeline-edit-time { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px; }
.timeline-edit-time input { min-width: 0; width: 100%; height: 34px; padding: 0 8px; border: 1px solid var(--border-color); border-radius: 6px; background: color-mix(in srgb, var(--xb-panel) 88%, transparent); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.timeline-edit-text { min-width: 0; overflow: hidden; color: var(--text-primary); text-overflow: ellipsis; white-space: nowrap; }
.timeline-edit-label { overflow: hidden; color: var(--accent); text-overflow: ellipsis; white-space: nowrap; } .timeline-edit-label.idle { color: var(--text-muted); }
.lyric-list { max-height: 480px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; padding-right: 4px; }
.lyric-row { display: flex; align-items: center; gap: 12px; min-height: 66px; padding: 8px 8px; border-radius: 8px; } .lyric-row:hover { background: color-mix(in srgb, var(--accent) 5%, transparent); } .lyric-row.is-chorus { background: color-mix(in srgb, var(--accent) 7%, transparent); box-shadow: inset 2px 0 0 var(--accent); } .lyric-row.is-idle { opacity: .72; }
.ly-time { flex: 0 0 58px; color: var(--text-muted); font: 11px ui-monospace, monospace; line-height: 1.45; } .ly-text { min-width: 0; flex: 1; overflow: hidden; color: var(--text-primary); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.ly-assign { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 6px; max-width: 55%; }
.model-chip { display: inline-flex; align-items: center; gap: 5px; min-height: 28px; padding: 0 7px 0 9px; border: 1px solid; border-radius: 999px; font-size: 12px; font-weight: 650; white-space: nowrap; } .chip-dot { width: 7px; height: 7px; border-radius: 50%; } .chip-x { width: 15px; height: 15px; border: 0; background: transparent; color: inherit; cursor: pointer; }
.add-chip, .seg-op { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--border-color); border-radius: 7px; background: transparent; color: var(--text-muted); cursor: pointer; } .add-chip { border-style: dashed; border-radius: 50%; } .add-chip:hover:not(:disabled), .seg-op:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); } .add-chip:disabled, .seg-op:disabled, .chip-x:disabled { opacity: .4; cursor: not-allowed; }
.idle-chip { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
.pick-pop { display: grid; gap: 7px; min-width: 0; }
.pick-hint { margin: 0 0 2px; color: var(--text-muted); font-size: 11px; line-height: 1.4; }
.pick-item { display: flex; align-items: center; gap: 7px; min-height: 31px; padding: 0 8px; border: 1px solid var(--border-color); border-radius: 6px; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.pick-item:hover:not(:disabled), .pick-item.on { border-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); } .pick-item:disabled { opacity: .45; cursor: not-allowed; }
.pick-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; } .pick-dot.idle { border: 1px solid var(--text-muted); background: transparent; }
.pick-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .pick-item .el-icon { margin-left: auto; }
.seg-ops { display: inline-flex; gap: 4px; } .seg-op.danger:hover { border-color: var(--xb-accent); color: var(--xb-accent); }
.workbench-overview { margin: 14px 0 16px; padding: 12px 14px 18px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 76%, transparent); }
.overview-legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--text-muted); font-size: 12px; }
.overview-legend span { display: inline-flex; align-items: center; gap: 7px; } .overview-legend i { width: 10px; height: 10px; border-radius: 50%; } .overview-legend .idle-dot { border: 1px solid var(--text-muted); background: transparent; }
.overview-ruler { position: relative; height: 25px; margin-top: 8px; color: var(--text-muted); font: 11px ui-monospace, monospace; }
.overview-ruler span { position: absolute; transform: translateX(-50%); white-space: nowrap; } .overview-ruler span:first-child { transform: none; }
.overview-track { position: relative; height: 82px; overflow: hidden; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-primary) 4%, transparent); }
.overview-block { position: absolute; top: 13px; bottom: 13px; min-width: 7px; display: grid; place-items: center; overflow: hidden; border: 1px solid transparent; border-radius: 4px; color: #fff; box-shadow: inset 0 0 0 1px rgba(255,255,255,.2); }
.overview-block b { overflow: hidden; padding: 0 6px; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 2px rgba(0,0,0,.55); } .overview-block.idle { background: var(--text-muted); opacity: .3; } .overview-block.chorus { box-shadow: inset 0 0 0 1px rgba(255,255,255,.55); }
.timeline-editor { display: grid; gap: 8px; margin: 15px 0 12px; padding: 12px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--xb-panel) 76%, transparent); }
.timeline-legend { display: flex; flex-wrap: wrap; gap: 12px; color: var(--text-muted); font-size: 11px; }
.timeline-legend span { display: inline-flex; align-items: center; gap: 5px; } .timeline-legend i { width: 9px; height: 9px; border-radius: 50%; } .timeline-legend .idle-dot { border: 1px solid var(--text-muted); background: transparent; }
.timeline-ruler { position: relative; height: 16px; color: var(--text-muted); font: 10px ui-monospace, monospace; }
.timeline-ruler span { position: absolute; transform: translateX(-50%); white-space: nowrap; } .timeline-ruler span:first-child { transform: none; }
.timeline-track { position: relative; height: 64px; overflow: hidden; border: 1px solid var(--border-color); background: repeating-linear-gradient(90deg, color-mix(in srgb, var(--xb-fill-rgb) 8%, transparent) 0 1px, transparent 1px 25%); }
.timeline-block { position: absolute; top: 9px; bottom: 9px; min-width: 7px; display: flex; align-items: center; justify-content: space-between; gap: 2px; padding: 0 3px; overflow: hidden; border: 1px solid transparent; border-radius: 4px; color: #fff; cursor: pointer; box-shadow: inset 0 0 0 1px rgba(255,255,255,.14); }
.timeline-block b { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 2px rgba(0,0,0,.55); } .timeline-block.idle { background: var(--text-muted); opacity: .35; } .timeline-block.chorus { box-shadow: inset 0 0 0 1px rgba(255,255,255,.5); }
.timeline-grip { width: 5px; height: 24px; flex: 0 0 auto; border-left: 2px solid rgba(255,255,255,.75); cursor: ew-resize; } .timeline-grip.right { border-left: 0; border-right: 2px solid rgba(255,255,255,.75); }
.assign-pop { display: grid; gap: 7px; padding-top: 8px; border-top: 1px solid var(--border-color); } .assign-pop p { margin: 0 0 2px; color: var(--text-muted); font-size: 11px; }
.assign-pop > button { display: flex; align-items: center; gap: 7px; min-height: 30px; padding: 0 8px; border: 1px solid var(--border-color); background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; } .assign-pop > button.on { border-color: var(--accent); color: var(--accent); } .assign-pop > button i { width: 8px; height: 8px; border-radius: 50%; } .assign-pop > button .el-icon { margin-left: auto; } .assign-pop .assign-interlude { color: var(--text-muted); }
.assign-pop-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 3px; } .assign-pop-actions button { min-height: 27px; padding: 0 8px; border: 1px solid var(--border-color); background: transparent; color: var(--text-muted); cursor: pointer; }
.assign-quick { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-top: 12px; color: var(--text-muted); font-size: 12px; }
.assign-quick button { min-height: 28px; padding: 0 9px; border: 1px solid var(--border-color); background: color-mix(in srgb, var(--accent) 7%, transparent); color: var(--text-primary); cursor: pointer; }
.assign-quick button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.segment-list { display: grid; gap: 9px; margin-top: 13px; } .segment-row { display: grid; grid-template-columns: 190px minmax(120px, 1fr) minmax(180px, 1.2fr) auto auto; align-items: center; gap: 10px; padding: 10px; background: color-mix(in srgb, var(--xb-panel, #172033) 76%, transparent); }
.segment-lyric { min-width: 0; overflow: hidden; color: var(--text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.time-fields { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 6px; } .time-fields input { min-width: 0; width: 100%; height: 32px; padding: 0 7px; border: 1px solid var(--border-color, #344151); background: rgba(0, 0, 0, .12); color: inherit; }
.assignments { display: flex; align-items: center; justify-content: flex-start; flex-wrap: wrap; gap: 7px; } .row-assign-button { min-width: 132px; min-height: 36px; padding: 0 14px; border: 1px solid var(--accent); background: color-mix(in srgb, var(--accent) 7%, transparent); color: var(--accent); font-size: 13px; text-align: left; cursor: pointer; } .row-assign-label, .row-assign-empty { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .row-assign-empty { color: var(--text-muted); }
.chorus { color: #ff83b0; font-size: 11px; white-space: nowrap; }
.control-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px 22px; } .control { display: grid; gap: 9px; } .control span { display: flex; justify-content: space-between; font-size: 13px; }
.start-btn { min-height: 52px; display: flex; justify-content: center; align-items: center; gap: 9px; border: 1px solid var(--accent, #00d5ff); background: color-mix(in srgb, var(--accent, #00d5ff) 16%, transparent); color: var(--text-primary, #fff); font-weight: 700; cursor: pointer; }
.monitor { position: sticky; top: 18px; display: grid; gap: 14px; } .monitor-card { overflow: hidden; }
.monitor-head { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 8px; font-size: 13px; } .monitor-head b { color: var(--text-muted, #8f9aaa); font-variant-numeric: tabular-nums; }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: #687382; } .live-dot.active { background: #00d5ff; box-shadow: 0 0 12px #00d5ff; } .live-dot.done { background: #35d07f; } .live-dot.failed { background: #ff647c; }
.visualizer { height: 132px; display: flex; align-items: center; gap: 3px; margin: 24px 0; } .visualizer i { flex: 1; min-width: 2px; max-height: 100%; background: color-mix(in srgb, var(--accent, #00d5ff) 72%, #fff); opacity: .5; transform: scaleY(.4); }
.visualizer.playing i { animation: pulse .65s ease-in-out infinite alternate; } @keyframes pulse { to { transform: scaleY(1); opacity: .9; } }
.progress-track, .buffer-track { height: 4px; background: rgba(127, 140, 160, .16); overflow: hidden; } .progress-track span, .buffer-track span { display: block; height: 100%; background: var(--accent, #00d5ff); transition: width .25s linear; }
.buffer-line { display: flex; justify-content: space-between; margin: 18px 0 7px; font-size: 12px; color: var(--text-muted, #8f9aaa); } .buffer-track span { background: #35d07f; }
.monitor-message { min-height: 38px; margin: 14px 0; color: var(--text-muted, #8f9aaa); font-size: 12px; line-height: 1.55; }
.transport { display: flex; justify-content: center; align-items: center; gap: 10px; } .round-btn { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; border: 1px solid var(--accent, #00d5ff); background: color-mix(in srgb, var(--accent, #00d5ff) 18%, transparent); color: inherit; cursor: pointer; }
.export-btn { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px; border: 1px solid var(--border-color, #344151); background: transparent; color: inherit; cursor: pointer; }
.sync-panel { display: grid; gap: 0; overflow: hidden; border: 1px solid var(--xb-border, var(--border-color, #344151)); border-left: 2px solid var(--xb-primary, var(--accent, #00d5ff)); border-radius: 8px; background: color-mix(in srgb, var(--xb-primary, #00d5ff) 4%, transparent); }
.sync-panel > div { display: flex; gap: 11px; align-items: center; min-height: 64px; padding: 12px 14px; background: transparent; }
.sync-panel > div + div { border-top: 1px solid var(--xb-border, var(--border-color, #344151)); }
.sync-panel .el-icon { flex: 0 0 auto; color: var(--xb-primary, var(--accent, #00d5ff)); font-size: 18px; }
.sync-panel span { display: grid; gap: 4px; min-width: 0; }
.sync-panel b { color: var(--xb-text, var(--text-primary, #f4f7fb)); font-size: 12px; }
.sync-panel small { color: var(--xb-muted, var(--text-muted, #8f9aaa)); line-height: 1.45; }
@media (max-width: 940px) { .layout { grid-template-columns: 1fr; } .monitor { position: static; } }
@media (max-width: 640px) { .page { margin: 10px 8px 24px; padding: 20px 14px 40px; } .page-head { align-items: flex-start; flex-direction: column; } .model-grid, .control-grid, .param-grid, .select-grid, .pitch-guard-grid, .source-library-list, .system-audio-setup { grid-template-columns: 1fr; } .system-audio-note { grid-column: auto; } .setting-title { flex-wrap: wrap; } .manual-param-switch { width: 100%; margin-left: 0; white-space: normal; } }
</style>
