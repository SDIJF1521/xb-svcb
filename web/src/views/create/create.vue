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
        <!-- 翻唱模式 -->
        <section class="card glass mode-card">
          <button class="mode-item" :class="{ active: mode === 'single' }" @click="mode = 'single'">
            <el-icon><Microphone /></el-icon>
            <div class="mode-text">
              <div class="mode-name">单模型翻唱</div>
              <div class="mode-desc">整首歌用一个模型</div>
            </div>
          </button>
          <button class="mode-item" :class="{ active: mode === 'multi' }" @click="mode = 'multi'">
            <el-icon><Operation /></el-icon>
            <div class="mode-text">
              <div class="mode-name">多模型混合</div>
              <div class="mode-desc">逐句指派不同模型</div>
            </div>
          </button>
        </section>

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

        <!-- 选择模型（单模型） -->
        <section v-if="mode === 'single'" class="card glass">
          <div class="card-head">
            <span class="step-no">02</span>
            <h2>选择你的模型</h2>
            <router-link to="/models" class="head-link">管理模型 <el-icon><Right /></el-icon></router-link>
          </div>
          <div v-if="availableFrameworks.length > 1" class="model-filter">
            <button class="filter-chip" :class="{ on: modelFilter === '' }" @click="modelFilter = ''">全部</button>
            <button
              v-for="fw in availableFrameworks"
              :key="fw"
              class="filter-chip"
              :class="{ on: modelFilter === fw }"
              @click="modelFilter = fw"
            >{{ frameworkLabel(fw) }}</button>
          </div>
          <div v-if="filteredModels.length" class="model-list">
            <button
              v-for="m in filteredModels"
              :key="m.id"
              class="model-item"
              :class="{ active: selectedModel === m.id }"
              @click="selectedModel = m.id"
            >
              <div class="model-dot" :style="{ '--mc': m.color }">
                <el-icon><Microphone /></el-icon>
              </div>
              <div class="model-text">
                <div class="model-name">
                  {{ m.name }}<span class="fw-chip">{{ frameworkLabel(m.framework) }}</span>
                </div>
                <div class="model-tag">{{ m.type }} · {{ m.sr }}</div>
              </div>
              <el-icon v-if="selectedModel === m.id" class="model-check"><Select /></el-icon>
            </button>
          </div>
          <p v-else class="field-tip">该框架下暂无模型，切换筛选或前往「管理模型」导入。</p>
        </section>

        <!-- 选择模型（多模型 + 各自参数） -->
        <section v-else class="card glass">
          <div class="card-head">
            <span class="step-no">02</span>
            <h2>选择参与模型</h2>
            <router-link to="/models" class="head-link">管理模型 <el-icon><Right /></el-icon></router-link>
          </div>
          <p class="field-tip">勾选本次要混合的模型（可跨框架：RVC 与 So-VITS-SVC 同曲混用），每个模型可单独展开设置参数</p>
          <div v-if="availableFrameworks.length > 1" class="model-filter">
            <button class="filter-chip" :class="{ on: modelFilter === '' }" @click="modelFilter = ''">全部</button>
            <button
              v-for="fw in availableFrameworks"
              :key="fw"
              class="filter-chip"
              :class="{ on: modelFilter === fw }"
              @click="modelFilter = fw"
            >{{ frameworkLabel(fw) }}</button>
          </div>
          <div class="model-list">
            <div v-for="m in filteredModels" :key="m.id" class="multi-model">
              <button
                class="model-item"
                :class="{ active: isPicked(m.id) }"
                @click="togglePick(m.id)"
              >
                <div class="model-dot" :style="{ '--mc': m.color }">
                  <el-icon><Microphone /></el-icon>
                </div>
                <div class="model-text">
                  <div class="model-name">
                    {{ m.name }}<span class="fw-chip">{{ frameworkLabel(m.framework) }}</span>
                  </div>
                  <div class="model-tag">{{ m.type }} · {{ m.sr }}</div>
                </div>
                <span v-if="isPicked(m.id)" class="model-badge" :style="{ background: m.color }">
                  {{ pickedIndex(m.id) + 1 }}
                </span>
                <el-icon v-if="isPicked(m.id)" class="model-check"><Select /></el-icon>
              </button>

              <div v-if="isPicked(m.id)" class="mp-params">
                <div class="mp-row">
                  <label>变调 {{ mp(m.id).pitch > 0 ? '+' + mp(m.id).pitch : mp(m.id).pitch }}</label>
                  <input type="range" min="-12" max="12" step="1" v-model.number="mp(m.id).pitch" />
                </div>
                <div v-if="frameworkOf(m.id) !== 'rvc'" class="mp-row">
                  <label>扩散占比 {{ Math.round(mp(m.id).diffusionRatio * 100) }}%</label>
                  <input type="range" min="0" max="1" step="0.05" v-model.number="mp(m.id).diffusionRatio" />
                </div>
                <template v-else>
                  <div class="mp-row">
                    <label>清辅音保护 {{ mp(m.id).protect.toFixed(2) }}</label>
                    <input type="range" min="0" max="0.5" step="0.01" v-model.number="mp(m.id).protect" />
                  </div>
                  <div class="mp-row">
                    <label>检索比率 {{ mp(m.id).indexRate.toFixed(2) }}</label>
                    <input type="range" min="0" max="1" step="0.05" v-model.number="mp(m.id).indexRate" />
                  </div>
                </template>
                <div class="mp-inline">
                  <div class="mp-mini">
                    <span>F0</span>
                    <select v-model="mp(m.id).f0Method">
                      <option v-for="f in f0Methods" :key="f" :value="f">{{ f }}</option>
                    </select>
                  </div>
                  <div class="mp-mini">
                    <span>设备</span>
                    <select v-model="mp(m.id).device">
                      <option v-for="d in deviceOptions" :key="d.v" :value="d.v">{{ d.label }}</option>
                    </select>
                  </div>
                  <div v-if="frameworkOf(m.id) === 'rvc'" class="mp-mini">
                    <span>版本</span>
                    <select v-model="mp(m.id).rvcVersion">
                      <option v-for="v in rvcVersions" :key="v" :value="v">{{ v }}</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
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

        <!-- 推理参数（单模型） -->
        <section v-if="mode === 'single'" class="card glass">
          <div class="card-head">
            <span class="step-no">04</span>
            <h2>推理参数</h2>
          </div>

          <div class="fw-banner">
            当前模型框架：<b>{{ frameworkLabel(selectedFramework) }}</b>
          </div>

          <div v-if="selectedFramework !== 'rvc'" class="field">
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
            <div class="field-hint">同时作用于人声分离与模型推理；GPU 加速需 NVIDIA 显卡（CUDA），无显卡或显存不足时选 CPU</div>
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

          <!-- RVC 专属参数 -->
          <template v-if="selectedFramework === 'rvc'">
            <div class="field">
              <div class="field-row">
                <label>清辅音保护 (protect)</label>
                <span class="field-val">{{ protect.toFixed(2) }}</span>
              </div>
              <input type="range" min="0" max="0.5" step="0.01" v-model.number="protect" />
              <div class="field-hint">越小越贴合目标音色，越大越保留原声辅音/呼吸（0~0.5）</div>
            </div>

            <div class="field">
              <div class="field-row">
                <label>F0 中值滤波半径</label>
                <span class="field-val">{{ filterRadius }}</span>
              </div>
              <input type="range" min="0" max="7" step="1" v-model.number="filterRadius" />
              <div class="field-hint">≥3 可降低呼吸杂音（仅对 harvest 等有效）</div>
            </div>

            <div class="field">
              <label class="field-block-label">RVC 模型版本</label>
              <div class="seg">
                <button
                  v-for="v in rvcVersions"
                  :key="v"
                  class="seg-item"
                  :class="{ active: rvcVersion === v }"
                  @click="rvcVersion = v"
                >{{ v }}</button>
              </div>
            </div>
          </template>
        </section>

        <!-- 歌词与分句指派（多模型） -->
        <section v-else class="card glass">
          <div class="card-head">
            <span class="step-no">04</span>
            <h2>歌词分句指派</h2>
          </div>
          <p class="field-tip">按歌名获取带时间轴的歌词，再为每句指派演唱模型</p>

          <div class="lyric-fetch">
            <input
              v-model="songQuery"
              class="lyric-input"
              type="text"
              placeholder="歌曲名 / 歌手，用于获取歌词"
              @keyup.enter="fetchLyrics"
            />
            <input v-model.number="songIndex" class="lyric-n" type="number" min="1" max="20" title="搜索结果序号" />
            <el-select v-model="lyricSrc" class="lyric-src">
              <el-option v-for="s in lyricSources" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button round class="ghost-btn" :loading="lyricLoading" @click="fetchLyrics">获取歌词</el-button>
          </div>

          <!-- 对齐校验 -->
          <div v-if="lyrics.length" class="align-bar" :class="alignStatus.type">
            <el-icon><Clock /></el-icon>
            <span class="align-text">{{ alignStatus.text }}</span>
            <div class="offset-ctrl">
              <label>整体偏移 {{ offset > 0 ? '+' : '' }}{{ offset.toFixed(1) }}s</label>
              <input type="range" min="-10" max="10" step="0.1" v-model.number="offset" />
            </div>
          </div>

          <!-- 快捷指派 -->
          <div v-if="lyrics.length && pickedModels.length" class="assign-quick">
            <span class="muted">批量：</span>
            <button
              v-for="pm in pickedModels"
              :key="pm.id"
              class="quick-btn"
              :style="{ '--mc': pm.color }"
              @click="assignAll(pm.id)"
            >全指派给 {{ pm.name }}</button>
            <span class="muted assign-tip">每句可多选模型 → 合唱同唱一句</span>
          </div>

          <!-- 歌词逐句 -->
          <div v-if="lyrics.length" class="lyric-list">
            <div
              v-for="(ln, i) in lyrics"
              :key="i"
              class="lyric-row"
              :class="{ 'is-chorus': (assignments[i] || []).length > 1, 'is-idle': !(assignments[i] || []).length }"
            >
              <span class="ly-time">{{ fmtTime(ln.time + offset) }}</span>
              <span class="ly-text" :title="ln.text">{{ ln.text }}</span>
              <div class="ly-assign">
                <span v-if="(assignments[i] || []).length > 1" class="chorus-tag">
                  <el-icon><Microphone /></el-icon>合唱 ×{{ (assignments[i] || []).length }}
                </span>
                <span
                  v-for="id in (assignments[i] || [])"
                  :key="id"
                  class="model-chip"
                  :style="chipStyle(id)"
                >
                  <span class="chip-dot" :style="{ background: modelColor(id) }"></span>
                  <span class="chip-name">{{ modelName(id) }}</span>
                  <button class="chip-x" title="移除" @click.stop="removeAssign(i, id)">
                    <el-icon><Close /></el-icon>
                  </button>
                </span>
                <span v-if="!(assignments[i] || []).length" class="idle-chip">间奏 · 不唱</span>
                <el-popover
                  placement="bottom-end"
                  :width="232"
                  trigger="click"
                  popper-class="assign-popover"
                >
                  <template #reference>
                    <button class="add-chip" :title="(assignments[i] || []).length ? '增减演唱模型' : '指派模型'">
                      <el-icon><Plus /></el-icon>
                    </button>
                  </template>
                  <div class="pick-pop">
                    <p class="pick-hint">点选模型演唱本句，多选即「合唱」</p>
                    <button
                      v-for="pm in pickedModels"
                      :key="pm.id"
                      class="pick-item"
                      :class="{ on: isAssigned(i, pm.id) }"
                      :style="{ '--mc': pm.color }"
                      @click="toggleAssign(i, pm.id)"
                    >
                      <span class="pick-dot" :style="{ background: pm.color }"></span>
                      <span class="pick-name">{{ pm.name }}</span>
                      <el-icon v-if="isAssigned(i, pm.id)" class="pick-check"><Check /></el-icon>
                    </button>
                  </div>
                </el-popover>
              </div>
            </div>
          </div>
          <div v-else-if="lyricTried && !lyricLoading" class="lyric-empty">
            未获取到歌词，请检查歌名 / 序号 / 曲库后重试。
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
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
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
  Operation,
  Clock,
  Plus,
  Check,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  api,
  type WorkDTO,
  type PipelineStep,
  type DownloadedMusic,
  type LyricLine,
  type MusicSource,
  type BlendModel,
  type BlendSegment,
} from '@/api'
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

/* RVC 专属参数 */
const rvcVersions = ['v2', 'v1']
const protect = ref(num(prefs.protect, 0.33))
const filterRadius = ref(num(prefs.filterRadius, 3))
const rvcVersion = ref(str(prefs.rvcVersion, 'v2'))

/* 模型框架辅助：用于单/多模型参数面板按框架切换、下拉显示框架标签 */
function frameworkOf(id: string): string {
  return models.value.find((m) => m.id === id)?.framework || 'so-vits-svc'
}
function frameworkLabel(id: string): string {
  const map: Record<string, string> = {
    'so-vits-svc': 'So-VITS-SVC',
    rvc: 'RVC',
    'ddsp-svc': 'DDSP-SVC',
    other: '其他',
  }
  return map[id] || id || 'So-VITS-SVC'
}
const selectedFramework = computed(() => frameworkOf(selectedModel.value))

/* 模型框架筛选：'' = 全部；只在存在多种框架时展示筛选条 */
const modelFilter = ref('')
const availableFrameworks = computed(() => {
  const seen: string[] = []
  for (const m of models.value) {
    const fw = m.framework || 'so-vits-svc'
    if (!seen.includes(fw)) seen.push(fw)
  }
  return seen
})
const filteredModels = computed(() =>
  modelFilter.value
    ? models.value.filter((m) => (m.framework || 'so-vits-svc') === modelFilter.value)
    : models.value,
)

const deviceOptions = [
  { v: 'cuda', label: 'GPU (CUDA)' },
  { v: 'cpu', label: 'CPU' },
]
const device = ref(str(prefs.device, 'cuda'))

/* ===== 多模型混合翻唱 ===== */
type MultiParams = {
  pitch: number
  diffusionRatio: number
  f0Method: string
  device: string
  indexRate: number
  rmsMix: number
  protect: number
  filterRadius: number
  rvcVersion: string
}
const mode = ref<'single' | 'multi'>(prefs.mode === 'multi' ? 'multi' : 'single')

// 已勾选模型的 id（保持勾选顺序）与各自参数
const selectedMulti = ref<string[]>([])
const modelParams = reactive<Record<string, MultiParams>>({})

function defaultParams(): MultiParams {
  return {
    pitch: pitch.value,
    diffusionRatio: diffusionRatio.value,
    f0Method: f0Method.value,
    device: device.value,
    indexRate: indexRate.value,
    rmsMix: rmsMix.value,
    protect: protect.value,
    filterRadius: filterRadius.value,
    rvcVersion: rvcVersion.value,
  }
}
function mp(id: string): MultiParams {
  let p = modelParams[id]
  if (!p) {
    p = defaultParams()
    modelParams[id] = p
  }
  return p
}
function isPicked(id: string) {
  return selectedMulti.value.includes(id)
}
function pickedIndex(id: string) {
  return selectedMulti.value.indexOf(id)
}
function togglePick(id: string) {
  if (isPicked(id)) {
    selectedMulti.value = selectedMulti.value.filter((x) => x !== id)
  } else {
    if (!modelParams[id]) modelParams[id] = defaultParams()
    selectedMulti.value = [...selectedMulti.value, id]
  }
}
const pickedModels = computed(() =>
  selectedMulti.value
    .map((id) => models.value.find((m) => m.id === id))
    .filter((m): m is NonNullable<typeof m> => !!m)
    .map((m) => ({ id: m.id, name: m.name, color: m.color })),
)

// 歌词获取与对齐
const songQuery = ref('')
const songIndex = ref(1)
const lyricSrc = ref('wy')
const lyricSources = ref<MusicSource[]>([{ id: 'wy', name: '网易云音乐', cookie: false }])
const lyrics = ref<LyricLine[]>([])
// 每句歌词指派的模型 id 列表（空=间奏/不唱，1=独唱，>1=合唱）
const assignments = ref<string[][]>([])
const offset = ref(0)
const lyricLoading = ref(false)
const lyricTried = ref(false)
const audioDuration = ref(0)

async function fetchLyrics() {
  const q = songQuery.value.trim()
  if (!q) {
    ElMessage.info('请输入歌曲名')
    return
  }
  lyricLoading.value = true
  lyricTried.value = true
  try {
    const res = await api.getMusicLyrics(q, songIndex.value || 1, lyricSrc.value)
    if (!res.ok || !res.lines?.length) {
      lyrics.value = []
      assignments.value = []
      ElMessage.error(res.error || '未获取到歌词')
      return
    }
    lyrics.value = res.lines
    const first = pickedModels.value[0]?.id || ''
    assignments.value = res.lines.map(() => (first ? [first] : []))
    if (song.value?.path) {
      audioDuration.value = await api.getAudioDuration(song.value.path)
    }
  } finally {
    lyricLoading.value = false
  }
}

function assignAll(id: string) {
  assignments.value = lyrics.value.map(() => [id])
}
/* ---- 逐句指派：彩色模型胶囊 + 弹出选择 ---- */
function modelName(id: string): string {
  return pickedModels.value.find((x) => x.id === id)?.name || '未知模型'
}
function modelColor(id: string): string {
  return pickedModels.value.find((x) => x.id === id)?.color || 'var(--xb-primary)'
}
/** 已指派模型胶囊的配色（淡底 + 同色文字/描边）。 */
function chipStyle(id: string) {
  const c = modelColor(id)
  return {
    color: c,
    borderColor: c,
    background: `color-mix(in srgb, ${c} 14%, transparent)`,
  }
}
function isAssigned(i: number, id: string): boolean {
  return (assignments.value[i] || []).includes(id)
}
/** 在第 i 句里切换某模型的「参与合唱」状态。 */
function toggleAssign(i: number, id: string) {
  const cur = [...(assignments.value[i] || [])]
  const idx = cur.indexOf(id)
  if (idx >= 0) cur.splice(idx, 1)
  else cur.push(id)
  assignments.value[i] = cur
}
function removeAssign(i: number, id: string) {
  const cur = assignments.value[i] || []
  assignments.value[i] = cur.filter((x) => x !== id)
}
function fmtTime(t: number) {
  const s = Math.max(0, t)
  const mm = Math.floor(s / 60)
  const ss = Math.floor(s % 60)
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

const alignStatus = computed(() => {
  const dur = audioDuration.value
  const arr = lyrics.value
  const lastLine = arr[arr.length - 1]
  if (!arr.length || !lastLine) return { type: 'idle', text: '' }
  const last = lastLine.time + offset.value
  if (!dur) return { type: 'warn', text: `共 ${lyrics.value.length} 句；未知音频时长，建议核对偏移` }
  const diff = last - dur
  if (last > dur + 2) {
    return { type: 'bad', text: `歌词末句 ${fmtTime(last)} 超出音频 ${fmtTime(dur)}，请调整偏移或核对版本` }
  }
  if (Math.abs(diff) <= 8 || last <= dur) {
    return { type: 'ok', text: `对齐良好：${lyrics.value.length} 句 · 音频 ${fmtTime(dur)}` }
  }
  return { type: 'warn', text: `请核对：歌词末句 ${fmtTime(last)} / 音频 ${fmtTime(dur)}` }
})

// 任一参数变化即写回 localStorage
watch(
  [uvrModel, f0Method, pitch, indexRate, rmsMix, diffusionRatio, device, mode, protect, filterRadius, rvcVersion],
  () => {
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
          mode: mode.value,
          protect: protect.value,
          filterRadius: filterRadius.value,
          rvcVersion: rvcVersion.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)

const isPlaying = ref(false)
const currentWork = ref<WorkDTO | null>(null)

const stepMeta: Record<string, string> = {
  separate: 'UVR 提取干声与伴奏',
  f0: '分析音高曲线',
  infer: '加载模型进行歌声转换',
  split: '按歌词时间轴切分人声',
  merge: '按顺序拼接各模型片段',
  mix: 'ffmpeg 合成与重采样',
}
const singlePipeline: PipelineStep[] = [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'f0', label: 'F0 提取', status: 'wait' },
  { key: 'infer', label: '模型推理', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]
const multiPipeline: PipelineStep[] = [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'split', label: '歌词分割', status: 'wait' },
  { key: 'infer', label: '逐段推理', status: 'wait' },
  { key: 'merge', label: '人声合并', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]

const pipeline = computed<PipelineStep[]>(
  () => currentWork.value?.steps ?? (mode.value === 'multi' ? multiPipeline : singlePipeline),
)
const stepDesc = (key: string) => stepMeta[key] ?? ''

const isGenerating = computed(
  () => currentWork.value?.status === 'running' || currentWork.value?.status === 'queue',
)
const done = computed(() => currentWork.value?.status === 'done')
const failed = computed(() => currentWork.value?.status === 'failed')
const canGenerate = computed(() => {
  if (!song.value) return false
  if (mode.value === 'single') return !!selectedModel.value
  // 多模型：至少选 1 个模型，且至少 1 句已指派
  return (
    selectedMulti.value.length > 0 &&
    lyrics.value.length > 0 &&
    assignments.value.some((a) => a && a.length > 0)
  )
})

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
  const title = song.value.name.replace(/\.[^.]+$/, '')

  if (mode.value === 'multi') {
    const lines = lyrics.value
    const lastLine = lines[lines.length - 1]
    const dur = audioDuration.value || (lastLine ? lastLine.time + offset.value + 5 : 180)
    const segments: BlendSegment[] = []
    for (let i = 0; i < lines.length; i++) {
      const cur = lines[i]
      const mids = (assignments.value[i] || []).filter(Boolean)
      if (!cur || mids.length === 0) continue
      const start = Math.max(0, cur.time + offset.value)
      const nextLine = lines[i + 1]
      const next = nextLine ? nextLine.time + offset.value : dur
      const end = Math.min(dur, Math.max(start, next))
      if (end > start) segments.push({ start, end, model_id: mids[0]!, model_ids: mids })
    }
    const blendModels: BlendModel[] = pickedModels.value.map((pm) => {
      const p = mp(pm.id)
      return {
        model_id: pm.id,
        params: {
          pitch: p.pitch,
          f0_method: p.f0Method,
          index_rate: p.indexRate,
          rms_mix: p.rmsMix,
          uvr_model: uvrModel.value,
          diffusion_ratio: p.diffusionRatio,
          device: p.device,
          protect: p.protect,
          filter_radius: p.filterRadius,
          rvc_version: p.rvcVersion,
        },
      }
    })
    const work = await worksStore.create({
      title,
      mode: 'multi',
      source_path: song.value.path,
      models: blendModels,
      segments,
      params: blendModels[0]?.params,
    })
    currentWork.value = work
    startPolling(work.id)
    return
  }

  const work = await worksStore.create({
    title,
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
      protect: protect.value,
      filter_radius: filterRadius.value,
      rvc_version: rvcVersion.value,
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

// 选中歌曲后默认带出歌名作为歌词搜索词；切歌时重置时长
watch(song, (s) => {
  if (s && !songQuery.value.trim()) songQuery.value = s.name.replace(/\.[^.]+$/, '')
  audioDuration.value = 0
})

onMounted(async () => {
  await modelsStore.ensureLoaded()
  selectedModel.value = defaultId.value || models.value[0]?.id || ''
  // 默认勾选默认模型，便于直接进入多模型流程
  if (selectedModel.value && selectedMulti.value.length === 0) {
    togglePick(selectedModel.value)
  }
  await loadDownloaded()
  // 加载歌词曲库选项（与「资源获取」共用妖狐 API 来源）
  try {
    const [srcList, curSource] = await Promise.all([
      api.listMusicSources(),
      api.getMusicSource(),
    ])
    if (srcList.length) lyricSources.value = srcList
    if (srcList.some((s) => s.id === curSource)) lyricSrc.value = curSource
  } catch {
    /* ignore */
  }
  // 从「资源获取」页跳转而来时，预选传入的已下载素材
  const src = typeof route.query.source === 'string' ? route.query.source : ''
  if (src) {
    const name = typeof route.query.name === 'string' && route.query.name
      ? route.query.name
      : src.split(/[/\\]/).pop() || src
    song.value = { name, path: src, hint: '来自资源获取' }
    songQuery.value = name.replace(/\.[^.]+$/, '')
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
.fw-chip { display: inline-block; margin-left: 8px; padding: 0 7px; border-radius: 6px; font-size: 11px; font-weight: 700; vertical-align: middle; color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.14); border: 1px solid rgba(var(--xb-accent-rgb), 0.35); }
.model-filter { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.filter-chip { padding: 5px 14px; border-radius: 20px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), 0.04); color: var(--xb-muted); font-size: 12.5px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.filter-chip:hover { color: var(--xb-text); border-color: var(--xb-primary); }
.filter-chip.on { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); border-color: transparent; }
.fw-banner { font-size: 12.5px; color: var(--xb-muted); margin-bottom: 14px; padding: 8px 12px; border-radius: 8px; background: rgba(var(--xb-primary-rgb), 0.06); border: 1px solid var(--xb-border); }
.fw-banner b { color: var(--xb-primary); }
.model-check { color: var(--xb-primary); font-size: 18px; }

/* 模式切换 */
.mode-card { display: flex; gap: 10px; padding: 12px; }
.mode-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.02);
  color: var(--xb-text);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.mode-item .el-icon { font-size: 20px; color: var(--xb-muted); }
.mode-item:hover { border-color: rgba(var(--xb-primary-rgb), 0.45); }
.mode-item.active { border-color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.09); }
.mode-item.active .el-icon { color: var(--xb-primary); }
.mode-name { font-weight: 700; font-size: 14px; }
.mode-desc { font-size: 12px; color: var(--xb-muted); margin-top: 2px; }

/* 多模型：每个模型 + 参数 */
.multi-model { display: flex; flex-direction: column; }
.model-badge {
  min-width: 20px; height: 20px;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  display: grid;
  place-items: center;
  padding: 0 5px;
}
.mp-params {
  margin: 6px 0 4px 8px;
  padding: 12px 14px;
  border-left: 2px solid var(--xb-border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mp-row { display: flex; flex-direction: column; gap: 6px; }
.mp-row label { font-size: 12.5px; color: var(--xb-muted); }
.mp-inline { display: flex; gap: 10px; }
.mp-mini { flex: 1; display: flex; align-items: center; gap: 6px; }
.mp-mini span { font-size: 12.5px; color: var(--xb-muted); }
.mp-mini select {
  flex: 1;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 13px;
}

/* 歌词获取 */
.lyric-fetch { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.lyric-input {
  flex: 1;
  min-width: 140px;
  padding: 9px 12px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 13.5px;
}
.lyric-input:focus { border-color: var(--xb-primary); }
.lyric-n {
  width: 52px;
  padding: 9px 8px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  text-align: center;
}
.lyric-src { width: 120px; }
.lyric-src :deep(.el-select__wrapper) {
  background: rgba(var(--xb-fill-rgb), 0.04);
  border: 1px solid var(--xb-border);
  border-radius: 9px;
  box-shadow: none;
  min-height: 38px;
}
.lyric-src :deep(.el-select__selected-item) { color: var(--xb-text); }

/* 对齐校验条 */
.align-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 9px;
  margin-bottom: 12px;
  font-size: 13px;
  border: 1px solid var(--xb-border);
  flex-wrap: wrap;
}
.align-bar .el-icon { font-size: 16px; flex-shrink: 0; }
.align-bar.ok { border-color: rgba(var(--xb-success-rgb), 0.4); color: var(--xb-success); }
.align-bar.warn { border-color: rgba(var(--xb-warn-rgb), 0.4); color: var(--xb-warn); }
.align-bar.bad { border-color: rgba(var(--xb-accent-rgb), 0.4); color: var(--xb-accent); }
.align-text { flex: 1; min-width: 120px; }
.offset-ctrl { display: flex; align-items: center; gap: 8px; }
.offset-ctrl label { font-size: 12px; color: var(--xb-muted); white-space: nowrap; }
.offset-ctrl input[type='range'] { width: 120px; }

/* 批量指派 */
.assign-quick { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.assign-quick .muted { font-size: 12.5px; color: var(--xb-muted); }
.assign-tip { margin-left: auto; }
.quick-btn {
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--mc);
  background: transparent;
  color: var(--mc);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.quick-btn:hover { background: color-mix(in srgb, var(--mc) 14%, transparent); }

/* 歌词逐句 */
.lyric-list { max-height: 360px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.lyric-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 8px;
}
.lyric-row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.lyric-row.is-idle { opacity: 0.72; }
.lyric-row.is-chorus {
  background: linear-gradient(90deg, rgba(var(--xb-primary-rgb), 0.07), transparent);
  box-shadow: inset 2px 0 0 var(--xb-primary);
}

/* 逐句指派：彩色模型胶囊 + 弹出选择 */
.ly-assign {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 60%;
}
.chorus-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
  color: #fff;
  background: linear-gradient(90deg, var(--xb-primary), #b06bff);
  box-shadow: 0 2px 8px rgba(var(--xb-primary-rgb), 0.35);
  white-space: nowrap;
}
.chorus-tag .el-icon { font-size: 12px; }
.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px 3px 9px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.model-chip:hover { transform: translateY(-1px); }
.chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}
.chip-name { max-width: 96px; overflow: hidden; text-overflow: ellipsis; }
.chip-x {
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 11px;
  opacity: 0.7;
}
.chip-x:hover { opacity: 1; background: color-mix(in srgb, currentColor 20%, transparent); }
.idle-chip {
  font-size: 12px;
  color: var(--xb-muted);
  padding: 2px 4px;
  font-style: italic;
}
.add-chip {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px dashed var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.16s ease;
}
.add-chip:hover {
  border-color: var(--xb-primary);
  border-style: solid;
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  transform: rotate(90deg);
}
.ly-time {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 12px;
  color: var(--xb-muted);
  flex-shrink: 0;
  width: 44px;
}
.ly-text {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ly-model {
  width: 116px;
  flex-shrink: 0;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  outline: none;
  font-size: 12.5px;
}
.lyric-empty {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--xb-muted);
}

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

<!-- 逐句指派弹出层会被传送到 body，需用非 scoped 样式命中 -->
<style>
.assign-popover.el-popover.el-popper {
  padding: 10px;
  border-radius: 14px;
  border: 1px solid var(--xb-border);
  background: var(--xb-bg-2);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.32);
}
.assign-popover .pick-pop { display: flex; flex-direction: column; gap: 4px; }
.assign-popover .pick-hint {
  margin: 0 4px 6px;
  font-size: 11.5px;
  color: var(--xb-muted);
}
.assign-popover .pick-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background 0.14s ease, border-color 0.14s ease;
}
.assign-popover .pick-item:hover {
  background: color-mix(in srgb, var(--mc) 12%, transparent);
}
.assign-popover .pick-item.on {
  border-color: var(--mc);
  background: color-mix(in srgb, var(--mc) 16%, transparent);
  color: var(--mc);
  font-weight: 700;
}
.assign-popover .pick-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px var(--mc);
}
.assign-popover .pick-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.assign-popover .pick-check { color: var(--mc); font-size: 15px; flex-shrink: 0; }
</style>
