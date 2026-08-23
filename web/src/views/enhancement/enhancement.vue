<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">// AI 翻唱 / AI 增强</p>
        <h1>AI 歌声增强工作台</h1>
        <p class="page-sub">使用原始歌曲校正翻唱人声，并生成新的增强成品</p>
      </div>
      <router-link to="/create" class="back-link">
        <el-icon><ArrowLeft /></el-icon><span>返回 AI 翻唱</span>
      </router-link>
    </header>

    <div class="workspace">
      <div class="configuration">
        <section class="panel glass">
          <div class="panel-head">
            <span class="step-no">01</span>
            <div>
              <h2>选择增强目标</h2>
              <p>可使用作品库成品，也可直接导入翻唱音频</p>
            </div>
            <span class="count">{{ availableWorks.length }} 首</span>
          </div>

          <div class="target-switch" role="group" aria-label="增强目标来源">
            <button :class="{ active: targetMode === 'work' }" @click="targetMode = 'work'">
              <el-icon><FolderOpened /></el-icon><span>我的作品</span>
            </button>
            <button :class="{ active: targetMode === 'import' }" @click="targetMode = 'import'">
              <el-icon><Upload /></el-icon><span>导入音频</span>
            </button>
          </div>
          <div v-if="targetMode === 'work' && availableWorks.length" class="work-list">
            <button
              v-for="work in availableWorks"
              :key="work.id"
              class="work-option"
              :class="{ selected: selectedWorkId === work.id }"
              @click="selectedWorkId = work.id"
            >
              <span class="work-icon"><el-icon><Headset /></el-icon></span>
              <span class="work-copy">
                <strong>{{ work.title }}</strong>
                <small>{{ work.model }} · {{ work.duration }} · {{ work.format }}</small>
              </span>
              <span class="select-indicator"><el-icon v-if="selectedWorkId === work.id"><Check /></el-icon></span>
            </button>
          </div>
          <div v-else-if="targetMode === 'work'" class="empty-state">
            <el-icon><Headset /></el-icon>
            <span>暂无可增强的翻唱作品</span>
            <router-link to="/create">创建翻唱</router-link>
          </div>
          <button v-else class="source-picker target-picker" :class="{ ready: !!targetAudioPath }" @click="pickTargetAudio">
            <span class="source-icon"><el-icon><Upload /></el-icon></span>
            <span class="source-copy">
              <strong>{{ targetAudioPath ? targetAudioName : '选择待增强的翻唱音频' }}</strong>
              <small>{{ targetAudioPath || '导入用户已有的翻唱成品或人声音频' }}</small>
            </span>
            <span class="pick-command">{{ targetAudioPath ? '更换' : '选择' }}</span>
          </button>
        </section>

        <section class="panel glass">
          <div class="panel-head">
            <span class="step-no">02</span>
            <div>
              <h2>提供原始歌曲</h2>
              <p>可选择本地音频，或从在线曲库搜索并下载原曲</p>
          </div>
          </div>
          <div class="source-switch" role="group" aria-label="原始歌曲来源">
            <button :class="{ active: originalMode === 'local' }" @click="originalMode = 'local'">
              <el-icon><Upload /></el-icon><span>本地文件</span>
            </button>
            <button :class="{ active: originalMode === 'online' }" @click="originalMode = 'online'">
              <el-icon><Search /></el-icon><span>在线曲库</span>
            </button>
          </div>
          <button v-if="originalMode === 'local'" class="source-picker" :class="{ ready: !!originalAudioPath }" @click="pickOriginalAudio">
            <span class="source-icon"><el-icon><Upload /></el-icon></span>
            <span class="source-copy">
              <strong>{{ originalAudioPath ? originalAudioName : '选择原始歌曲音频' }}</strong>
              <small>{{ originalAudioPath || '支持 WAV、FLAC、MP3、M4A 等常见音频格式' }}</small>
            </span>
            <span class="pick-command">{{ originalAudioPath ? '更换' : '选择' }}</span>
          </button>
          <div v-else class="online-picker">
            <div class="online-search">
              <input v-model="onlineKeyword" type="search" placeholder="搜索歌名 / 歌手" @keyup.enter="searchOriginal" />
              <select v-model="onlineSource" aria-label="在线曲库">
                <option v-for="source in musicSources" :key="source.id" :value="source.id">{{ source.name }}</option>
              </select>
              <button :disabled="onlineSearching || !onlineKeyword.trim()" @click="searchOriginal">
                <el-icon :class="{ spin: onlineSearching }"><component :is="onlineSearching ? Loading : Search" /></el-icon>
              </button>
            </div>
            <div v-if="onlineResults.length" class="online-results">
              <button v-for="item in onlineResults" :key="`${item.n}-${item.rid || item.name}`" class="online-result" :disabled="onlineDownloading === item.n" @click="useOnlineOriginal(item)">
                <span class="online-result-copy"><strong>{{ item.name }}</strong><small>{{ item.singer }}<template v-if="item.album"> · {{ item.album }}</template></small></span>
                <span class="online-use"><el-icon :class="{ spin: onlineDownloading === item.n }"><component :is="onlineDownloading === item.n ? Loading : Download" /></el-icon>{{ onlineDownloading === item.n ? '下载中' : '使用' }}</span>
              </button>
            </div>
            <p v-else class="online-hint">搜索结果会先下载到本地音乐库，再用于原曲参考。</p>
            <div v-if="originalAudioPath" class="online-selected">
              <el-icon><Check /></el-icon>
              <span><small>当前原始歌曲</small><strong>{{ originalAudioName }}</strong></span>
            </div>
          </div>
        </section>

        <section class="panel glass">
          <div class="panel-head">
            <span class="step-no">03</span>
            <div>
              <h2>增强参数</h2>
              <p>原曲参考用于音高、节奏、音色与动态校正</p>
            </div>
          </div>

          <div class="level-switch" role="group" aria-label="增强层级">
            <button :class="{ active: level === 'basic' }" @click="level = 'basic'">
              <span>Clean Voice</span><small>基础增强</small>
            </button>
            <button :class="{ active: level === 'advanced' }" @click="level = 'advanced'">
              <span>Natural Voice</span><small>高级增强</small>
            </button>
          </div>

          <div class="control-grid">
            <label v-for="item in visibleControls" :key="item.key" class="control">
              <span class="control-label">
                <span>{{ item.label }}</span><b>{{ Math.round(controls[item.key] * 100) }}%</b>
              </span>
              <input v-model.number="controls[item.key]" type="range" min="0" max="1" step="0.01" />
            </label>
          </div>
        </section>
      </div>

      <aside class="monitor glass">
        <div class="monitor-head">
          <span class="monitor-icon"><el-icon><MagicStick /></el-icon></span>
          <div><p>AI ENHANCEMENT</p><h2>增强任务</h2></div>
          <span class="env-badge" :class="{ ready: enhancementReady }">
            {{ enhancementReady ? '环境就绪' : '环境未就绪' }}
          </span>
        </div>

        <div v-if="!currentJob" class="selection-summary">
          <div><span>增强目标</span><strong>{{ targetMode === 'work' ? (selectedWork?.title || '未选择') : (targetAudioName || '未选择') }}</strong></div>
          <div><span>原始歌曲</span><strong>{{ originalAudioName || '未选择' }}</strong></div>
          <div><span>增强层级</span><strong>{{ level === 'advanced' ? 'Natural Voice' : 'Clean Voice' }}</strong></div>
        </div>

        <template v-else>
          <div class="job-summary">
            <span class="job-status" :class="currentJob.status">{{ statusLabel(currentJob.status) }}</span>
            <strong>{{ currentJob.title }}</strong>
            <div class="progress-track"><i :style="{ width: `${currentJob.progress}%` }"></i></div>
            <span class="progress-value">{{ currentJob.progress }}%</span>
          </div>
          <div class="pipeline">
            <div v-for="step in currentJob.steps" :key="step.key" class="pipeline-step" :class="step.status">
              <span class="step-state">
                <el-icon v-if="step.status === 'done'"><Check /></el-icon>
                <el-icon v-else-if="step.status === 'active'" class="spin"><Loading /></el-icon>
              </span>
              <span>{{ step.label }}</span>
            </div>
          </div>
          <p v-if="currentJob.error" class="job-error">{{ currentJob.error }}</p>
        </template>

        <div class="monitor-actions">
          <button v-if="!currentJob || currentJob.status === 'failed'" class="primary-action" :disabled="!canStart || submitting" @click="startEnhancement">
            <el-icon :class="{ spin: submitting }"><component :is="submitting ? Loading : MagicStick" /></el-icon>
            <span>{{ submitting ? '正在提交' : currentJob?.status === 'failed' ? '重新创建增强任务' : '开始 AI 增强' }}</span>
          </button>
          <button v-if="currentJob?.status === 'done'" class="primary-action" @click="openPlayer">
            <el-icon><VideoPlay /></el-icon><span>播放增强成品</span>
          </button>
          <button v-if="currentJob" class="secondary-action" @click="router.push('/works')">
            <el-icon><FolderOpened /></el-icon><span>打开我的作品</span>
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  ArrowLeft,
  Check,
  Download,
  FolderOpened,
  Headset,
  Loading,
  MagicStick,
  Search,
  Upload,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type JobStatus, type MusicSearchItem, type MusicSource, type VocalEnhancementLevel, type WorkDTO } from '@/api'
import { useSystemStore } from '@/stores/system'
import { useWorksStore } from '@/stores/works'

defineOptions({ name: 'AiEnhancementPage' })

type ControlKey =
  | 'pitch_correction'
  | 'timing_alignment'
  | 'timbre_focus'
  | 'ai_eq'
  | 'ai_compressor'
  | 'ai_exciter'
  | 'stereo_width'
  | 'loudness_envelope'

const controlDefinitions: { key: ControlKey; label: string; advanced?: boolean }[] = [
  { key: 'pitch_correction', label: '自然修音' },
  { key: 'timing_alignment', label: '原曲节奏对齐' },
  { key: 'timbre_focus', label: '角色共振峰' },
  { key: 'ai_eq', label: 'AI EQ', advanced: true },
  { key: 'ai_compressor', label: 'AI Compressor', advanced: true },
  { key: 'ai_exciter', label: 'AI Exciter', advanced: true },
  { key: 'stereo_width', label: 'Stereo 宽度', advanced: true },
  { key: 'loudness_envelope', label: '响度包络', advanced: true },
]

const route = useRoute()
const router = useRouter()
const worksStore = useWorksStore()
const systemStore = useSystemStore()
const { works } = storeToRefs(worksStore)
const { tools } = storeToRefs(systemStore)

const selectedWorkId = ref(typeof route.query.work === 'string' ? route.query.work : '')
const targetMode = ref<'work' | 'import'>(selectedWorkId.value ? 'work' : 'work')
const targetAudioPath = ref('')
const originalAudioPath = ref('')
const originalMode = ref<'local' | 'online'>('local')
const onlineKeyword = ref('')
const onlineSource = ref('wy')
const onlineResultKeyword = ref('')
const onlineResultSource = ref('wy')
const musicSources = ref<MusicSource[]>([])
const onlineResults = ref<MusicSearchItem[]>([])
const onlineSearching = ref(false)
const onlineDownloading = ref<number | null>(null)
const level = ref<VocalEnhancementLevel>('basic')
const submitting = ref(false)
const currentJob = ref<WorkDTO | null>(null)
const controls = reactive<Record<ControlKey, number>>({
  pitch_correction: 0.45,
  timing_alignment: 0.45,
  timbre_focus: 0.60,
  ai_eq: 0.55,
  ai_compressor: 0.45,
  ai_exciter: 0.25,
  stereo_width: 0.30,
  loudness_envelope: 0.58,
})

const availableWorks = computed(() =>
  works.value.filter((work) => work.status === 'done' && work.workflow !== 'ai_enhancement'),
)
const selectedWork = computed(() => availableWorks.value.find((work) => work.id === selectedWorkId.value))
const originalAudioName = computed(() => originalAudioPath.value.split(/[/\\]/).pop() || '')
const targetAudioName = computed(() => targetAudioPath.value.split(/[/\\]/).pop() || '')
const enhancementReady = computed(() =>
  ['vocal-enhancement', 'uvr', 'ffmpeg'].every((key) => tools.value.find((tool) => tool.key === key)?.ok),
)
const visibleControls = computed(() =>
  level.value === 'advanced' ? controlDefinitions : controlDefinitions.filter((item) => !item.advanced),
)
const canStart = computed(() => Boolean(
  (targetMode.value === 'work' ? selectedWork.value : targetAudioPath.value)
  && originalAudioPath.value
  && enhancementReady.value,
))

let pollTimer: ReturnType<typeof setInterval> | null = null

watch(availableWorks, (items) => {
  if (!selectedWorkId.value && items.length) selectedWorkId.value = items[0]!.id
})

async function pickOriginalAudio() {
  const path = await api.pickAudioFile()
  if (path) originalAudioPath.value = path
}

async function searchOriginal() {
  const keyword = onlineKeyword.value.trim()
  if (!keyword) return
  onlineSearching.value = true
  try {
    const result = await api.searchMusic(keyword, onlineSource.value)
    if (!result.ok) {
      ElMessage.error(result.error || '在线曲库搜索失败')
      onlineResults.value = []
    } else {
      onlineResults.value = result.songs || []
      onlineResultKeyword.value = result.keyword || keyword
      onlineResultSource.value = result.source || onlineSource.value
      if (!onlineResults.value.length) ElMessage.info('没有找到匹配的歌曲')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '在线曲库搜索失败')
  } finally {
    onlineSearching.value = false
  }
}

async function useOnlineOriginal(item: MusicSearchItem) {
  onlineDownloading.value = item.n
  try {
    const result = await api.downloadMusic(
      onlineResultKeyword.value || onlineKeyword.value.trim(),
      item.n,
      onlineResultSource.value || onlineSource.value,
      item.rid,
    )
    if (!result.ok || !result.path) {
      ElMessage.error(result.error || '原始歌曲下载失败')
      return
    }
    originalAudioPath.value = result.path
    ElMessage.success(`已下载原始歌曲：${result.name || item.name}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '原始歌曲下载失败')
  } finally {
    onlineDownloading.value = null
  }
}

async function pickTargetAudio() {
  const path = await api.pickAudioFile()
  if (path) targetAudioPath.value = path
}

async function startEnhancement() {
  if (!canStart.value || (targetMode.value === 'work' && !selectedWork.value)) return
  submitting.value = true
  try {
    currentJob.value = await api.createWork({
      title: targetMode.value === 'work'
        ? selectedWork.value!.title.replace(/\s*\([^)]*\)\s*$/, '')
        : targetAudioName.value.replace(/\.[^.]+$/, ''),
      workflow: 'ai_enhancement',
      target_work_id: targetMode.value === 'work' ? selectedWork.value!.id : undefined,
      target_audio_path: targetMode.value === 'import' ? targetAudioPath.value : undefined,
      original_audio_path: originalAudioPath.value,
      params: { device: 'auto', uvr_model: 'MDX-Net' },
      vocal_enhancement: {
        enabled: true,
        level: level.value,
        ...controls,
      },
    })
    await worksStore.load()
    startPolling()
    ElMessage.success('AI 增强任务已提交')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'AI 增强任务创建失败')
  } finally {
    submitting.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => void refreshJob(), 900)
  void refreshJob()
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function refreshJob() {
  const id = currentJob.value?.id
  if (!id) return
  const next = await api.getWork(id)
  if (!next) return
  currentJob.value = next
  await worksStore.refreshOne(id)
  if (next.status === 'done') {
    stopPolling()
    ElMessage.success('AI 增强成品已保存到“我的作品”')
  } else if (next.status === 'failed') {
    stopPolling()
    ElMessage.error(next.error || 'AI 增强处理失败')
  }
}

function openPlayer() {
  if (currentJob.value?.id) router.push({ path: '/player', query: { work: currentJob.value.id } })
}

function statusLabel(status: JobStatus) {
  return ({ queue: '排队中', running: '增强中', done: '已完成', failed: '失败' })[status]
}

onMounted(async () => {
  await Promise.all([
    worksStore.load(),
    systemStore.load(),
    api.listMusicSources().then((items) => {
      musicSources.value = items
      onlineSource.value = items.find((item) => item.id === 'wy')?.id || items[0]?.id || 'wy'
    }),
  ])
  if (!selectedWorkId.value && availableWorks.value.length) selectedWorkId.value = availableWorks.value[0]!.id
})
onUnmounted(stopPolling)
</script>

<style scoped>
.page { max-width: 1320px; margin: 0 auto; padding: 28px 24px 60px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.eyebrow { margin: 0 0 7px; color: var(--xb-primary); font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
h1 { margin: 0; font-size: 30px; letter-spacing: 0; }
.page-sub { margin: 8px 0 0; color: var(--xb-muted); font-size: 14px; }
.back-link { display: inline-flex; align-items: center; gap: 7px; color: var(--xb-muted); text-decoration: none; }
.workspace { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .72fr); align-items: start; gap: 20px; }
.configuration { display: grid; gap: 16px; }
.glass { background: var(--xb-panel); border: 1px solid var(--xb-border); backdrop-filter: blur(16px); }
.panel, .monitor { border-radius: 8px; }
.panel { padding: 20px; }
.panel-head { display: flex; align-items: center; gap: 11px; min-height: 36px; margin-bottom: 16px; }
.panel-head > div { min-width: 0; }
.panel-head h2, .monitor h2 { margin: 0; font-size: 16px; letter-spacing: 0; }
.panel-head p { margin: 4px 0 0; color: var(--xb-muted); font-size: 12px; }
.step-no { display: grid; place-items: center; width: 31px; height: 27px; flex: 0 0 auto; border: 1px solid rgba(var(--xb-primary-rgb), .55); color: var(--xb-primary); font: 700 11px ui-monospace, monospace; }
.count { margin-left: auto; color: var(--xb-muted); font-size: 12px; }
.target-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; padding: 4px; margin-bottom: 12px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), .025); }
.target-switch button { min-height: 38px; display: flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid transparent; color: var(--xb-muted); background: transparent; cursor: pointer; font-weight: 700; }
.target-switch button.active { border-color: rgba(var(--xb-primary-rgb), .5); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); }
.source-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; padding: 4px; margin-bottom: 12px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), .025); }
.source-switch button { min-height: 38px; display: flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid transparent; color: var(--xb-muted); background: transparent; cursor: pointer; font-weight: 700; }
.source-switch button.active { border-color: rgba(var(--xb-primary-rgb), .5); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); }
.online-picker { display: grid; gap: 10px; }
.online-search { display: grid; grid-template-columns: minmax(0, 1fr) 130px 42px; gap: 8px; }
.online-search input, .online-search select { min-width: 0; height: 42px; padding: 0 11px; border: 1px solid var(--xb-border); border-radius: 0; outline: none; color: var(--xb-text); background: rgba(var(--xb-fill-rgb), .035); }
.online-search input:focus, .online-search select:focus { border-color: var(--xb-primary); }
.online-search button { width: 42px; height: 42px; display: grid; place-items: center; border: 1px solid var(--xb-primary); color: var(--xb-on-primary); background: var(--xb-primary); cursor: pointer; }
.online-search button:disabled { opacity: .4; cursor: not-allowed; }
.online-results { display: grid; max-height: 260px; overflow: auto; border-top: 1px solid var(--xb-border); }
.online-result { min-height: 58px; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 9px 8px; border: 0; border-bottom: 1px solid var(--xb-border); color: var(--xb-text); background: transparent; text-align: left; cursor: pointer; }
.online-result:hover { background: rgba(var(--xb-primary-rgb), .065); }
.online-result:disabled { opacity: .65; cursor: wait; }
.online-result-copy { display: grid; gap: 4px; min-width: 0; }
.online-result-copy strong, .online-result-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.online-result-copy strong { font-size: 12px; }.online-result-copy small { color: var(--xb-muted); font-size: 10px; }
.online-use { display: inline-flex; align-items: center; gap: 5px; color: var(--xb-primary); font-size: 11px; font-weight: 750; }
.online-hint { margin: 4px 0 0; color: var(--xb-muted); font-size: 11px; text-align: center; }
.online-selected { min-height: 48px; display: grid; grid-template-columns: 24px minmax(0, 1fr); align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid rgba(var(--xb-success-rgb), .35); color: var(--xb-success); background: rgba(var(--xb-success-rgb), .06); }
.online-selected > span { display: grid; gap: 2px; min-width: 0; }.online-selected small { color: var(--xb-muted); font-size: 9px; }.online-selected strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.work-list { display: grid; max-height: 330px; overflow: auto; border-top: 1px solid var(--xb-border); }
.work-option { display: grid; grid-template-columns: 42px minmax(0, 1fr) 24px; align-items: center; gap: 11px; min-height: 68px; padding: 10px 8px; border: 0; border-bottom: 1px solid var(--xb-border); color: var(--xb-text); background: transparent; text-align: left; cursor: pointer; }
.work-option:hover { background: rgba(var(--xb-fill-rgb), .045); }
.work-option.selected { background: rgba(var(--xb-primary-rgb), .08); box-shadow: inset 3px 0 var(--xb-primary); }
.work-icon, .source-icon, .monitor-icon { display: grid; place-items: center; color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .10); }
.work-icon { width: 38px; height: 38px; }
.work-copy { display: grid; gap: 4px; min-width: 0; }
.work-copy strong, .work-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.work-copy strong { font-size: 13px; }
.work-copy small { color: var(--xb-muted); font-size: 11px; }
.select-indicator { display: grid; place-items: center; width: 20px; height: 20px; border: 1px solid var(--xb-border); border-radius: 50%; color: var(--xb-on-primary); }
.selected .select-indicator { border-color: var(--xb-primary); background: var(--xb-primary); }
.empty-state { min-height: 120px; display: flex; align-items: center; justify-content: center; gap: 9px; color: var(--xb-muted); }
.empty-state a { color: var(--xb-primary); }
.source-picker { width: 100%; min-height: 84px; display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 13px; padding: 12px; border: 1px dashed var(--xb-border); color: var(--xb-text); background: rgba(var(--xb-fill-rgb), .025); text-align: left; cursor: pointer; }
.source-picker:hover, .source-picker.ready { border-color: var(--xb-primary); }
.target-picker { margin-top: 3px; }
.source-icon { width: 46px; height: 46px; font-size: 21px; }
.source-copy { display: grid; gap: 5px; min-width: 0; }
.source-copy strong { font-size: 13px; }
.source-copy small { overflow: hidden; color: var(--xb-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.pick-command { color: var(--xb-primary); font-size: 12px; font-weight: 700; }
.level-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 4px; margin-bottom: 18px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), .025); }
.level-switch button { min-height: 48px; display: grid; place-items: center; gap: 2px; border: 1px solid transparent; color: var(--xb-muted); background: transparent; cursor: pointer; }
.level-switch button.active { border-color: rgba(var(--xb-primary-rgb), .55); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .09); }
.level-switch span { font-weight: 750; }
.level-switch small { font-size: 10px; }
.control-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 24px; }
.control { display: grid; gap: 9px; }
.control-label { display: flex; justify-content: space-between; gap: 12px; color: var(--xb-muted); font-size: 12px; }
.control-label b { color: var(--xb-primary); font-variant-numeric: tabular-nums; }
.control input { width: 100%; accent-color: var(--xb-primary); }
.monitor { position: sticky; top: 86px; padding: 20px; }
.monitor-head { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 11px; padding-bottom: 17px; border-bottom: 1px solid var(--xb-border); }
.monitor-icon { width: 42px; height: 42px; font-size: 20px; }
.monitor-head p { margin: 0 0 3px; color: var(--xb-primary); font: 700 10px ui-monospace, monospace; }
.env-badge { padding: 5px 7px; color: var(--xb-danger); border: 1px solid rgba(var(--xb-danger-rgb), .35); font-size: 10px; white-space: nowrap; }
.env-badge.ready { color: var(--xb-success); border-color: rgba(var(--xb-success-rgb), .35); }
.selection-summary { display: grid; margin: 18px 0; }
.selection-summary > div { display: grid; gap: 5px; padding: 12px 2px; border-bottom: 1px solid var(--xb-border); }
.selection-summary span { color: var(--xb-muted); font-size: 10px; }
.selection-summary strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.job-summary { position: relative; display: grid; gap: 9px; padding: 18px 0; }
.job-summary strong { padding-right: 54px; font-size: 13px; }
.job-status { width: max-content; color: var(--xb-muted); font-size: 10px; }
.job-status.running { color: var(--xb-primary); }.job-status.done { color: var(--xb-success); }.job-status.failed { color: var(--xb-danger); }
.progress-track { height: 6px; overflow: hidden; background: rgba(var(--xb-fill-rgb), .10); }
.progress-track i { display: block; height: 100%; background: var(--xb-primary); transition: width .25s ease; }
.progress-value { position: absolute; top: 38px; right: 0; color: var(--xb-primary); font: 700 12px ui-monospace, monospace; }
.pipeline { display: grid; margin-bottom: 18px; border-top: 1px solid var(--xb-border); }
.pipeline-step { display: grid; grid-template-columns: 24px 1fr; align-items: center; gap: 8px; min-height: 42px; border-bottom: 1px solid var(--xb-border); color: var(--xb-muted); font-size: 11px; }
.pipeline-step.active { color: var(--xb-primary); }.pipeline-step.done { color: var(--xb-success); }.pipeline-step.failed { color: var(--xb-danger); }
.step-state { display: grid; place-items: center; width: 18px; height: 18px; border: 1px solid currentColor; border-radius: 50%; }
.job-error { padding: 10px; color: var(--xb-danger); background: rgba(var(--xb-danger-rgb), .08); font-size: 11px; line-height: 1.5; }
.monitor-actions { display: grid; gap: 9px; margin-top: 18px; }
.primary-action, .secondary-action { min-height: 44px; display: flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid var(--xb-primary); font-weight: 750; cursor: pointer; }
.primary-action { color: var(--xb-on-primary); background: var(--xb-primary); }
.primary-action:disabled { opacity: .38; cursor: not-allowed; }
.secondary-action { color: var(--xb-primary); background: transparent; }
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) { .workspace { grid-template-columns: 1fr; } .monitor { position: static; } }
@media (max-width: 640px) { .page { padding: 20px 14px 40px; } .page-head { align-items: flex-start; flex-direction: column; } .control-grid { grid-template-columns: 1fr; } .online-search { grid-template-columns: minmax(0, 1fr) 42px; } .online-search select { grid-column: 1 / -1; grid-row: 2; } .monitor-head { grid-template-columns: 42px minmax(0, 1fr); } .env-badge { grid-column: 2; width: max-content; } }
</style>
