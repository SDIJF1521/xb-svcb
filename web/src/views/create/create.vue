<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// AI 翻唱</p>
        <h1>歌声转换工作台</h1>
        <p class="page-sub">上传歌曲 → 选择 SVC 模型 → 调整参数 → 一键生成翻唱</p>
      </div>
    </div>

    <div class="layout">
      <!-- 左侧：配置 -->
      <div class="config">
        <!-- 上传歌曲 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">01</span>
            <h2>上传歌曲</h2>
          </div>
          <div v-if="!song" class="dropzone" @click="onPickSong">
            <el-icon class="dz-icon"><UploadFilled /></el-icon>
            <p class="dz-main">点击选择音频文件</p>
            <p class="dz-sub">支持 MP3 / WAV / FLAC，单文件 ≤ 50MB</p>
          </div>
          <div v-else class="song-file">
            <div class="song-cover"><el-icon><Headset /></el-icon></div>
            <div class="song-info">
              <div class="song-name">{{ song.name }}</div>
              <div class="song-meta">{{ song.hint }}</div>
            </div>
            <button class="icon-x" @click="song = null"><el-icon><Close /></el-icon></button>
          </div>

          <!-- 已下载素材：从「资源获取」下载的歌曲可直接选用 -->
          <div v-if="downloaded.length" class="lib">
            <div class="lib-head">
              <span>从已下载素材选择</span>
              <router-link to="/music" class="head-link">资源获取 <el-icon><Right /></el-icon></router-link>
            </div>
            <div class="lib-list">
              <button
                v-for="d in downloaded"
                :key="d.path"
                class="lib-item"
                :class="{ active: song?.path === d.path }"
                :title="d.name"
                @click="pickDownloaded(d)"
              >
                <el-icon><Headset /></el-icon>
                <span class="lib-name">{{ d.name }}</span>
                <span class="lib-size">{{ d.size }}</span>
              </button>
            </div>
          </div>
        </section>

        <!-- 选择模型 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">02</span>
            <h2>选择 SVC 模型</h2>
            <router-link to="/models" class="head-link">管理模型 <el-icon><Right /></el-icon></router-link>
          </div>
          <div class="model-list">
            <button
              v-for="m in models"
              :key="m.id"
              class="model-item"
              :class="{ active: selectedModel === m.id }"
              @click="selectedModel = m.id"
            >
              <div class="model-dot" :style="{ '--mc': m.color }">
                <el-icon><Microphone /></el-icon>
              </div>
              <div class="model-text">
                <div class="model-name">{{ m.name }}</div>
                <div class="model-tag">{{ m.type }} · {{ m.sr }}</div>
              </div>
              <el-icon v-if="selectedModel === m.id" class="model-check"><Select /></el-icon>
            </button>
          </div>
        </section>

        <!-- 人声分离 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">03</span>
            <h2>人声分离 (UVR)</h2>
          </div>
          <p class="field-tip">由 Ultimate Vocal Remover 自动分离人声与伴奏</p>
          <div class="seg">
            <button
              v-for="u in uvrModels"
              :key="u"
              class="seg-item"
              :class="{ active: uvrModel === u }"
              @click="uvrModel = u"
            >{{ u }}</button>
          </div>
        </section>

        <!-- 推理参数 -->
        <section class="card glass">
          <div class="card-head">
            <span class="step-no">04</span>
            <h2>推理参数</h2>
          </div>

          <div class="field">
            <div class="field-row">
              <label>主模型 / 扩散模型 比例</label>
              <span class="field-val">
                <i class="ratio-main">主 {{ Math.round((1 - diffusionRatio) * 100) }}%</i>
                ·
                <i class="ratio-diff">扩散 {{ Math.round(diffusionRatio * 100) }}%</i>
              </span>
            </div>
            <input class="ratio-range" type="range" min="0" max="1" step="0.05" v-model.number="diffusionRatio" />
            <div class="field-hint">两个模型共同参与推理，向右扩散模型占比更高</div>
          </div>

          <div class="field">
            <div class="field-row">
              <label>变调（半音）</label>
              <span class="field-val">{{ pitch > 0 ? '+' + pitch : pitch }}</span>
            </div>
            <input type="range" min="-12" max="12" step="1" v-model.number="pitch" />
            <div class="field-hint">男声转女声建议 +12，女声转男声建议 -12</div>
          </div>

          <div class="field">
            <label class="field-block-label">F0 提取算法</label>
            <div class="seg">
              <button
                v-for="f in f0Methods"
                :key="f"
                class="seg-item"
                :class="{ active: f0Method === f }"
                @click="f0Method = f"
              >{{ f }}</button>
            </div>
          </div>

          <div class="field">
            <label class="field-block-label">推理设备</label>
            <div class="seg">
              <button
                v-for="d in deviceOptions"
                :key="d.v"
                class="seg-item"
                :class="{ active: device === d.v }"
                @click="device = d.v"
              >{{ d.label }}</button>
            </div>
            <div class="field-hint">同时作用于人声分离与 SVC 推理；GPU 加速需 NVIDIA 显卡（CUDA），无显卡或显存不足时选 CPU</div>
          </div>

          <div class="field">
            <div class="field-row">
              <label>索引比率</label>
              <span class="field-val">{{ indexRate.toFixed(2) }}</span>
            </div>
            <input type="range" min="0" max="1" step="0.05" v-model.number="indexRate" />
          </div>

          <div class="field">
            <div class="field-row">
              <label>响度包络融合</label>
              <span class="field-val">{{ rmsMix.toFixed(2) }}</span>
            </div>
            <input type="range" min="0" max="1" step="0.05" v-model.number="rmsMix" />
          </div>
        </section>

        <el-button
          size="large"
          round
          class="cta-btn generate-btn"
          :disabled="!canGenerate || isGenerating"
          @click="generate"
        >
          <el-icon class="el-icon--left"><MagicStick /></el-icon>
          {{ isGenerating ? '生成中…' : '开始生成翻唱' }}
        </el-button>
      </div>

      <!-- 右侧：预览 / 进度 -->
      <div class="preview">
        <section class="card glass result-card">
          <div class="corner tl"></div>
          <div class="corner tr"></div>
          <div class="corner bl"></div>
          <div class="corner br"></div>

          <div class="result-head">
            <h2>输出预览</h2>
            <span class="result-state" :class="overallState.type">{{ overallState.text }}</span>
          </div>

          <div class="player">
            <div class="player-cover">
              <el-icon><Headset /></el-icon>
            </div>
            <div class="waveform" :class="{ playing: isPlaying }">
              <span v-for="n in 56" :key="n" :style="barStyle(n)"></span>
            </div>
            <div class="player-ctrl">
              <button class="play-main" :disabled="!done" @click="onTogglePlay">
                <el-icon v-if="!isPlaying"><VideoPlay /></el-icon>
                <el-icon v-else><VideoPause /></el-icon>
              </button>
              <el-button round class="ghost-btn" :disabled="!done" @click="onExport">
                <el-icon class="el-icon--left"><Download /></el-icon>导出
              </el-button>
            </div>
          </div>
          <audio
            ref="audioEl"
            style="display: none"
            @play="isPlaying = true"
            @pause="isPlaying = false"
            @ended="isPlaying = false"
          />
        </section>

        <section class="card glass">
          <div class="card-head"><h2>处理流程</h2></div>
          <div class="pipeline">
            <div
              v-for="(p, i) in pipeline"
              :key="p.label"
              class="pl-step"
              :class="p.status"
            >
              <div class="pl-icon">
                <el-icon v-if="p.status === 'done'"><Select /></el-icon>
                <el-icon v-else-if="p.status === 'active'" class="spin"><Loading /></el-icon>
                <span v-else>{{ i + 1 }}</span>
              </div>
              <div class="pl-text">
                <div class="pl-label">{{ p.label }}</div>
                <div class="pl-desc">{{ stepDesc(p.key) }}</div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="failed" class="card glass error-card">
          <div class="card-head"><h2>失败原因</h2></div>
          <div class="error-msg">{{ currentWork?.error || '推理失败，请查看日志' }}</div>
          <div v-if="currentWork?.log_path" class="error-path" :title="currentWork.log_path">
            日志路径：{{ currentWork.log_path }}
          </div>
          <div class="error-actions">
            <el-button round class="ghost-btn" @click="openLog">
              <el-icon class="el-icon--left"><Document /></el-icon>打开日志文件夹
            </el-button>
            <el-button round class="ghost-btn" @click="retry">
              <el-icon class="el-icon--left"><RefreshRight /></el-icon>重试
            </el-button>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  UploadFilled,
  Headset,
  Close,
  Right,
  Microphone,
  Select,
  MagicStick,
  VideoPlay,
  VideoPause,
  Download,
  Loading,
  Document,
  RefreshRight,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type WorkDTO, type PipelineStep, type DownloadedMusic } from '@/api'
import { useModelsStore } from '@/stores/models'
import { useWorksStore } from '@/stores/works'

defineOptions({ name: 'CreatePage' })

const modelsStore = useModelsStore()
const worksStore = useWorksStore()
const { models, defaultId } = storeToRefs(modelsStore)

interface Song {
  name: string
  path: string
  hint: string
}

// 记忆上次使用的推理参数（localStorage，跨重启保留）
const PREFS_KEY = 'xb-create-prefs'
function loadPrefs(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (raw) return JSON.parse(raw) as Record<string, unknown>
  } catch {
    /* ignore */
  }
  return {}
}
const prefs = loadPrefs()
const num = (v: unknown, d: number) => (typeof v === 'number' ? v : d)
const str = (v: unknown, d: string) => (typeof v === 'string' ? v : d)

const song = ref<Song | null>(null)
const selectedModel = ref<string>('')

const uvrModels = ['MDX-Net', 'Demucs v4', 'VR Arch']
const uvrModel = ref(str(prefs.uvrModel, 'MDX-Net'))

const f0Methods = ['rmvpe', 'crepe', 'harvest', 'pm']
const f0Method = ref(str(prefs.f0Method, 'rmvpe'))

const pitch = ref(num(prefs.pitch, 0))
const indexRate = ref(num(prefs.indexRate, 0.75))
const rmsMix = ref(num(prefs.rmsMix, 0.25))
const diffusionRatio = ref(num(prefs.diffusionRatio, 0.5))

const deviceOptions = [
  { v: 'cuda', label: 'GPU (CUDA)' },
  { v: 'cpu', label: 'CPU' },
]
const device = ref(str(prefs.device, 'cuda'))

// 任一参数变化即写回 localStorage
watch([uvrModel, f0Method, pitch, indexRate, rmsMix, diffusionRatio, device], () => {
  try {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        uvrModel: uvrModel.value,
        f0Method: f0Method.value,
        pitch: pitch.value,
        indexRate: indexRate.value,
        rmsMix: rmsMix.value,
        diffusionRatio: diffusionRatio.value,
        device: device.value,
      }),
    )
  } catch {
    /* ignore */
  }
})

const isPlaying = ref(false)
const currentWork = ref<WorkDTO | null>(null)

const stepMeta: Record<string, string> = {
  separate: 'UVR 提取干声与伴奏',
  f0: '分析音高曲线',
  infer: '加载模型进行歌声转换',
  mix: 'ffmpeg 合成与重采样',
}
const defaultPipeline: PipelineStep[] = [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'f0', label: 'F0 提取', status: 'wait' },
  { key: 'infer', label: 'SVC 推理', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]

const pipeline = computed<PipelineStep[]>(() => currentWork.value?.steps ?? defaultPipeline)
const stepDesc = (key: string) => stepMeta[key] ?? ''

const isGenerating = computed(
  () => currentWork.value?.status === 'running' || currentWork.value?.status === 'queue',
)
const done = computed(() => currentWork.value?.status === 'done')
const failed = computed(() => currentWork.value?.status === 'failed')
const canGenerate = computed(() => !!song.value && !!selectedModel.value)

const audioEl = ref<HTMLAudioElement | null>(null)
const audioLoadedFor = ref<string | null>(null)

async function onTogglePlay() {
  const work = currentWork.value
  const el = audioEl.value
  if (!work || work.status !== 'done' || !el) return
  if (audioLoadedFor.value !== work.id) {
    const data = await api.getWorkAudio(work.id)
    if (!data) {
      ElMessage.error('无法加载生成的音频')
      return
    }
    el.src = data
    audioLoadedFor.value = work.id
  }
  if (el.paused) await el.play()
  else el.pause()
}

async function onExport() {
  const work = currentWork.value
  if (!work || work.status !== 'done') return
  const dest = await api.exportWork(work.id)
  if (dest) ElMessage.success('已导出到：' + dest)
  else ElMessage.info('已取消导出')
}

async function openLog() {
  if (currentWork.value) await api.openWorkLog(currentWork.value.id)
}

async function retry() {
  const id = currentWork.value?.id
  if (!id) return
  const ok = await api.retryWork(id)
  if (ok) startPolling(id)
}

const overallState = computed(() => {
  const s = currentWork.value?.status
  if (s === 'running' || s === 'queue') return { type: 'running', text: '处理中' }
  if (s === 'done') return { type: 'done', text: '已完成' }
  if (s === 'failed') return { type: 'idle', text: '失败' }
  return { type: 'idle', text: '待生成' }
})

async function onPickSong() {
  const path = await api.pickAudioFile()
  if (!path) return
  const name = path.split(/[/\\]/).pop() || path
  song.value = { name, path, hint: '本地音频已选择' }
}

// 已下载素材（来自「资源获取」页）
const route = useRoute()
const downloaded = ref<DownloadedMusic[]>([])

function pickDownloaded(d: DownloadedMusic) {
  song.value = { name: d.name, path: d.path, hint: '已下载素材' }
}

async function loadDownloaded() {
  downloaded.value = await api.listMusic()
}

let timer: ReturnType<typeof setInterval> | null = null
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function startPolling(id: string) {
  stopPolling()
  timer = setInterval(async () => {
    const w = await api.getWork(id)
    if (w) currentWork.value = w
    if (!w || w.status === 'done' || w.status === 'failed') stopPolling()
  }, 800)
}

const generate = async () => {
  if (!canGenerate.value || isGenerating.value || !song.value) return
  isPlaying.value = false
  const work = await worksStore.create({
    title: song.value.name.replace(/\.[^.]+$/, ''),
    model_id: selectedModel.value,
    source_path: song.value.path,
    params: {
      pitch: pitch.value,
      f0_method: f0Method.value,
      index_rate: indexRate.value,
      rms_mix: rmsMix.value,
      uvr_model: uvrModel.value,
      diffusion_ratio: diffusionRatio.value,
      device: device.value,
    },
  })
  currentWork.value = work
  startPolling(work.id)
}

const barStyle = (n: number) => ({
  height: 18 + Math.abs(Math.sin(n * 0.6)) * 74 + '%',
  animationDelay: n * 0.03 + 's',
})

watch(defaultId, (id) => {
  if (id && !selectedModel.value) selectedModel.value = id
})

onMounted(async () => {
  await modelsStore.ensureLoaded()
  selectedModel.value = defaultId.value || models.value[0]?.id || ''
  await loadDownloaded()
  // 从「资源获取」页跳转而来时，预选传入的已下载素材
  const src = typeof route.query.source === 'string' ? route.query.source : ''
  if (src) {
    const name = typeof route.query.name === 'string' && route.query.name
      ? route.query.name
      : src.split(/[/\\]/).pop() || src
    song.value = { name, path: src, hint: '来自资源获取' }
  }
})
onUnmounted(stopPolling)
</script>

<style scoped>
.page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.page-head { margin-bottom: 24px; }
.eyebrow {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 8px;
}
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; }

.layout {
  display: grid;
  grid-template-columns: 1fr 0.85fr;
  gap: 22px;
  align-items: start;
}
.config { display: flex; flex-direction: column; gap: 18px; }
.preview {
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: sticky;
  top: 84px;
}

.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.card {
  border-radius: 6px;
  padding: 22px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}
.card-head h2 { font-size: 17px; font-weight: 700; margin: 0; }
.step-no {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
  font-weight: 800;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  padding: 3px 8px;
  border-radius: 6px;
}
.head-link {
  margin-left: auto;
  color: var(--xb-muted);
  font-size: 13px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.head-link:hover { color: var(--xb-primary); }

/* 切角 */
.corner { position: absolute; width: 14px; height: 14px; border-color: var(--xb-primary); }
.corner.tl { top: -1px; left: -1px; border-top: 2px solid; border-left: 2px solid; }
.corner.tr { top: -1px; right: -1px; border-top: 2px solid; border-right: 2px solid; }
.corner.bl { bottom: -1px; left: -1px; border-bottom: 2px solid; border-left: 2px solid; }
.corner.br { bottom: -1px; right: -1px; border-bottom: 2px solid; border-right: 2px solid; }

/* 按钮 */
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 22px rgba(var(--xb-primary-rgb), 0.4);
}
.cta-btn.is-disabled { opacity: 0.45; box-shadow: none; }
.ghost-btn {
  background: rgba(var(--xb-primary-rgb), 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.generate-btn { width: 100%; padding: 24px; font-size: 16px; }

/* 上传 */
.dropzone {
  border: 1.5px dashed rgba(var(--xb-primary-rgb), 0.3);
  border-radius: 8px;
  padding: 32px 20px;
  text-align: center;
  background: rgba(var(--xb-primary-rgb), 0.03);
  transition: all 0.25s;
  cursor: pointer;
}
.dropzone:hover { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.07); }
.dz-icon { font-size: 42px; color: var(--xb-primary); margin-bottom: 10px; }
.dz-main { font-size: 15px; font-weight: 600; margin: 0 0 6px; }
.dz-sub { font-size: 12.5px; color: var(--xb-muted); margin: 0; }
.song-file {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border-radius: 8px;
  background: rgba(var(--xb-primary-rgb), 0.05);
  border: 1px solid var(--xb-border);
}
.song-cover {
  width: 46px; height: 46px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 22px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
}
.song-info { flex: 1; }
.song-name { font-weight: 600; font-size: 14.5px; }
.song-meta { font-size: 12.5px; color: var(--xb-muted); margin-top: 3px; }
.icon-x {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
}
.icon-x:hover { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }

/* 已下载素材 */
.lib { margin-top: 16px; border-top: 1px solid var(--xb-border); padding-top: 14px; }
.lib-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--xb-muted);
  margin-bottom: 10px;
}
.lib-list { display: flex; flex-direction: column; gap: 8px; max-height: 220px; overflow-y: auto; }
.lib-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-text);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}
.lib-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.lib-item.active { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.08); }
.lib-item .el-icon { color: var(--xb-primary); flex-shrink: 0; }
.lib-name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lib-size { font-size: 12px; color: var(--xb-muted); flex-shrink: 0; }

/* 模型选择 */
.model-list { display: flex; flex-direction: column; gap: 10px; }
.model-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.model-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.model-item.active {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.model-dot {
  width: 38px; height: 38px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 18px;
  color: var(--xb-on-primary);
  background: var(--mc);
}
.model-text { flex: 1; }
.model-name { font-weight: 600; font-size: 14px; color: var(--xb-text); }
.model-tag { font-size: 12px; color: var(--xb-muted); margin-top: 2px; }
.model-check { color: var(--xb-primary); font-size: 18px; }

/* 字段 */
.field { margin-bottom: 18px; }
.field:last-child { margin-bottom: 0; }
.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.field label, .field-block-label {
  font-size: 14px;
  color: var(--xb-text);
  font-weight: 500;
}
.field-block-label { display: block; margin-bottom: 10px; }
.field-val {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--xb-primary);
}
.field-hint { font-size: 12px; color: var(--xb-muted); margin-top: 8px; }
.field-tip { font-size: 13px; color: var(--xb-muted); margin: -6px 0 12px; }
input[type='range'] {
  width: 100%;
  accent-color: var(--xb-primary);
  cursor: pointer;
}
.ratio-range { accent-color: var(--xb-accent); }
.ratio-main { color: var(--xb-primary); font-style: normal; }
.ratio-diff { color: var(--xb-accent); font-style: normal; }

/* 分段控件 */
.seg {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.seg-item {
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}
.seg-item:hover { color: var(--xb-text); border-color: rgba(var(--xb-primary-rgb), 0.45); }
.seg-item.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
}

/* 预览 */
.result-card { box-shadow: 0 0 40px rgba(var(--xb-primary-rgb), 0.08); }
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.result-head h2 { font-size: 17px; font-weight: 700; margin: 0; }
.result-state {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
}
.result-state.idle { color: var(--xb-muted); background: rgba(var(--xb-fill-rgb), 0.06); }
.result-state.running { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.12); }
.result-state.done { color: var(--xb-success); background: rgba(var(--xb-success-rgb), 0.12); }

.player-cover {
  width: 70px; height: 70px;
  margin: 0 auto 18px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-size: 32px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
  box-shadow: 0 0 26px rgba(var(--xb-primary-rgb), 0.4);
}
.waveform {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2px;
  height: 64px;
  margin-bottom: 20px;
}
.waveform span {
  flex: 1;
  background: linear-gradient(180deg, var(--xb-primary), var(--xb-primary-2));
  border-radius: 2px;
  opacity: 0.4;
}
.waveform.playing span {
  opacity: 1;
  animation: bar 1s ease-in-out infinite alternate;
}
@keyframes bar { from { transform: scaleY(0.35); } to { transform: scaleY(1); } }
.player-ctrl {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
}
.play-main {
  width: 48px; height: 48px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  color: var(--xb-on-primary);
  font-size: 20px;
  display: grid;
  place-items: center;
  box-shadow: 0 0 20px rgba(var(--xb-primary-rgb), 0.5);
}
.play-main:disabled { opacity: 0.4; box-shadow: none; cursor: not-allowed; }

/* 流程 */
.pipeline { display: flex; flex-direction: column; gap: 6px; }
.pl-step {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border-radius: 8px;
  transition: background 0.25s;
}
.pl-step.active { background: rgba(var(--xb-primary-rgb), 0.06); }
.pl-icon {
  width: 32px; height: 32px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
  background: rgba(var(--xb-fill-rgb), 0.03);
}
.pl-step.active .pl-icon { color: var(--xb-primary); border-color: var(--xb-primary); }
.pl-step.done .pl-icon {
  color: var(--xb-on-primary);
  background: var(--xb-success);
  border-color: var(--xb-success);
}
.pl-label { font-size: 14px; font-weight: 600; }
.pl-desc { font-size: 12.5px; color: var(--xb-muted); margin-top: 2px; }
.pl-step.wait .pl-label { color: var(--xb-muted); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-card { border-color: rgba(var(--xb-accent-rgb), 0.35); }
.error-msg {
  font-size: 13px;
  line-height: 1.6;
  color: var(--xb-accent);
  background: rgba(var(--xb-accent-rgb), 0.08);
  border: 1px solid rgba(var(--xb-accent-rgb), 0.25);
  border-radius: 10px;
  padding: 10px 12px;
  word-break: break-word;
  max-height: 160px;
  overflow: auto;
}
.error-path {
  margin-top: 10px;
  font-size: 12px;
  color: var(--xb-muted);
  word-break: break-all;
}
.error-actions { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }

@media (max-width: 980px) {
  .layout { grid-template-columns: 1fr; }
  .preview { position: static; }
}
</style>
