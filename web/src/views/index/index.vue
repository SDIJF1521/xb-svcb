<template>
  <div class="home">
    <!-- 欢迎 / 快速开始 -->
    <section class="welcome glass">
      <div class="corner tl"></div>
      <div class="corner tr"></div>
      <div class="corner bl"></div>
      <div class="corner br"></div>

      <div class="welcome-text">
        <p class="hello">// 欢迎回来，Lkpap</p>
        <h1>用你自己的 <span class="grad-text">SVC 模型</span> 翻唱</h1>
        <p class="welcome-sub">
          导入你的 SVC 歌声模型，上传一首歌，软件会自动用 Ultimate Vocal Remover
          分离人声、用 ffmpeg 处理音频，数十秒生成高保真翻唱作品。
        </p>
        <div class="welcome-actions">
          <el-button size="large" round class="cta-btn" @click="router.push('/create')">
            <el-icon class="el-icon--left"><Upload /></el-icon>
            上传歌曲开始
          </el-button>
          <el-button size="large" round class="ghost-btn" :loading="importing" @click="onImport">
            <el-icon v-if="!importing" class="el-icon--left"><FolderAdd /></el-icon>
            导入 SVC 模型
          </el-button>
        </div>
      </div>

      <div class="dropzone" @click="router.push('/create')">
        <el-icon class="dz-icon"><UploadFilled /></el-icon>
        <p class="dz-main">拖拽音频到此处</p>
        <p class="dz-sub">支持 MP3 / WAV / FLAC，单文件 ≤ 50MB</p>
      </div>
    </section>

    <!-- 数据概览 -->
    <section class="stats">
      <div class="stat-card glass" v-for="s in stats" :key="s.label">
        <div class="stat-icon" :style="{ '--ic': s.color }">
          <el-icon><component :is="s.icon" /></el-icon>
        </div>
        <div>
          <div class="stat-num">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </section>

    <!-- 快捷功能 -->
    <section class="block">
      <div class="block-head">
        <h2>快捷功能</h2>
      </div>
      <div class="quick-grid">
        <div class="quick-card glass" v-for="q in quickActions" :key="q.title" @click="q.action">
          <div class="quick-icon" :style="{ '--ic': q.color }">
            <el-icon><component :is="q.icon" /></el-icon>
          </div>
          <div class="quick-info">
            <h3>{{ q.title }}</h3>
            <p>{{ q.desc }}</p>
          </div>
          <el-icon class="quick-arrow"><Right /></el-icon>
        </div>
      </div>
    </section>

    <!-- 我的模型 -->
    <section class="block">
      <div class="block-head">
        <h2>我的模型</h2>
        <router-link class="more" to="/models">全部模型 <el-icon><Right /></el-icon></router-link>
      </div>
      <div class="model-grid">
        <div class="model-card glass" v-for="m in displayModels" :key="m.id" @click="router.push('/create')">
          <div class="model-top">
            <div class="model-icon" :style="{ '--mc': m.color }">
              <el-icon><Microphone /></el-icon>
            </div>
            <span class="model-type">{{ m.type }}</span>
          </div>
          <div class="model-name" :title="m.name">{{ m.name }}</div>
          <div class="model-meta">
            <span>{{ m.sr }}</span>
            <span>{{ m.size }}</span>
          </div>
        </div>

        <!-- 导入模型卡片 -->
        <button class="model-add" @click="onImport">
          <el-icon><FolderAdd /></el-icon>
          <span>{{ importing ? '导入中…' : '导入 SVC 模型' }}</span>
          <small>.pth / .onnx + 配置文件</small>
        </button>
      </div>
    </section>

    <!-- 集成工具 / 运行环境 -->
    <section class="block">
      <div class="block-head">
        <h2>集成工具</h2>
        <span class="env-tag" :class="{ degraded: !allReady }">
          <span class="env-dot"></span>{{ allReady ? '运行环境就绪' : '部分工具降级' }}
        </span>
      </div>
      <div class="tool-grid">
        <div class="tool-card glass" v-for="t in tools" :key="t.key">
          <div class="tool-icon" :style="{ '--ic': toolColor(t.key) }">
            <el-icon><component :is="toolIcon(t.key)" /></el-icon>
          </div>
          <div class="tool-info">
            <div class="tool-name">
              {{ t.name }}
              <span class="tool-ver">{{ t.version }}</span>
            </div>
            <div class="tool-desc">{{ t.desc }}</div>
          </div>
          <span class="tool-status" :class="t.ok ? 'ok' : 'warn'">
            <el-icon><component :is="t.ok ? CircleCheckFilled : WarningFilled" /></el-icon>
            {{ t.status }}
          </span>
        </div>
      </div>
    </section>

    <!-- 最近作品 -->
    <section class="block">
      <div class="block-head">
        <h2>最近作品</h2>
        <router-link class="more" to="/works">我的作品 <el-icon><Right /></el-icon></router-link>
      </div>
      <div v-if="recentWorks.length" class="works glass">
        <div class="work-row" v-for="w in recentWorks" :key="w.id">
          <button class="work-play"><el-icon><VideoPlay /></el-icon></button>
          <div class="work-cover" :style="{ '--wc': w.color }">
            <el-icon><Headset /></el-icon>
          </div>
          <div class="work-main">
            <div class="work-title">{{ w.title }}</div>
            <div class="work-sub">模型：{{ w.model }}</div>
          </div>
          <div class="work-bar">
            <div class="work-bar-inner" :style="{ width: w.progress + '%' }"></div>
          </div>
          <span class="work-status" :class="w.status">{{ statusText(w.status) }}</span>
          <span class="work-time">{{ w.time }}</span>
          <div class="work-ops">
            <button title="下载"><el-icon><Download /></el-icon></button>
            <button title="更多"><el-icon><MoreFilled /></el-icon></button>
          </div>
        </div>
      </div>
      <div v-else class="works glass empty-hint">还没有作品，去「AI 翻唱」生成第一首吧。</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  Upload,
  UploadFilled,
  FolderAdd,
  Right,
  VideoPlay,
  Headset,
  Download,
  MoreFilled,
  Microphone,
  Cpu,
  Files,
  FolderOpened,
  TrendCharts,
  Timer,
  Scissor,
  VideoCamera,
  CircleCheckFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import { useSystemStore } from '@/stores/system'
import { useModelsStore } from '@/stores/models'
import { useWorksStore } from '@/stores/works'
import type { JobStatus } from '@/api'

defineOptions({ name: 'Index' })

const router = useRouter()
const systemStore = useSystemStore()
const modelsStore = useModelsStore()
const worksStore = useWorksStore()

const { tools } = storeToRefs(systemStore)
const { models } = storeToRefs(modelsStore)
const { works } = storeToRefs(worksStore)

const importing = ref(false)

const allReady = computed(() => tools.value.length > 0 && tools.value.every((t) => t.ok))
const displayModels = computed(() => models.value.slice(0, 5))
const recentWorks = computed(() => works.value.slice(0, 5))

const stats = computed(() => [
  { value: String(models.value.length), label: '已导入模型', icon: FolderOpened, color: '#00f0ff' },
  { value: String(works.value.length), label: '我的作品', icon: Files, color: '#b65cff' },
  { value: String(works.value.filter((w) => w.status === 'done').length), label: '已完成', icon: TrendCharts, color: 'var(--xb-success)' },
  { value: String(works.value.filter((w) => w.status === 'running' || w.status === 'queue').length), label: '处理中', icon: Timer, color: 'var(--xb-warn)' },
])

const quickActions = [
  { title: 'AI 翻唱', desc: '加载 SVC 模型，一键换声生成翻唱', icon: Microphone, color: '#00f0ff', action: () => router.push('/create') },
  { title: '人声分离', desc: '由 Ultimate Vocal Remover 提取干声与伴奏', icon: Scissor, color: '#ff2e88', action: () => router.push('/create') },
  { title: '我的模型', desc: '管理 .pth / .onnx 的 SVC 歌声模型', icon: FolderOpened, color: 'var(--xb-success)', action: () => router.push('/models') },
  { title: '导入模型', desc: '从本地导入新的 SVC 歌声模型', icon: FolderAdd, color: '#b65cff', action: () => onImport() },
]

const toolIconMap: Record<string, Component> = {
  uvr: Scissor,
  ffmpeg: VideoCamera,
  svc: Cpu,
}
const toolColorMap: Record<string, string> = {
  uvr: '#ff2e88',
  ffmpeg: 'var(--xb-success)',
  svc: '#00f0ff',
}
const toolIcon = (key: string): Component => toolIconMap[key] ?? Cpu
const toolColor = (key: string): string => toolColorMap[key] ?? '#00f0ff'

const statusText = (s: JobStatus) =>
  ({ done: '已完成', running: '生成中', queue: '排队中', failed: '失败' })[s]

function onImport() {
  // 导入需手动选择多个文件，统一在「我的模型」页操作
  router.push('/models')
}

onMounted(() => {
  systemStore.load()
  modelsStore.ensureLoaded()
  worksStore.ensureLoaded()
})
</script>

<style scoped>
.home {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}

.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.grad-text {
  background: var(--xb-hero-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

/* 切角 */
.corner {
  position: absolute;
  width: 14px; height: 14px;
  border-color: var(--xb-primary);
}
.corner.tl { top: -1px; left: -1px; border-top: 2px solid; border-left: 2px solid; }
.corner.tr { top: -1px; right: -1px; border-top: 2px solid; border-right: 2px solid; }
.corner.bl { bottom: -1px; left: -1px; border-bottom: 2px solid; border-left: 2px solid; }
.corner.br { bottom: -1px; right: -1px; border-bottom: 2px solid; border-right: 2px solid; }

.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 22px rgba(var(--xb-primary-rgb), 0.4);
}
.ghost-btn {
  background: rgba(var(--xb-primary-rgb), 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.ghost-btn:hover {
  border-color: var(--xb-primary) !important;
  color: var(--xb-primary) !important;
}

/* 欢迎区 */
.welcome {
  border-radius: 6px;
  padding: 38px 36px;
  display: grid;
  grid-template-columns: 1.3fr 0.9fr;
  gap: 36px;
  align-items: center;
  box-shadow: 0 0 50px rgba(var(--xb-primary-rgb), 0.08);
}
.hello {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 10px;
}
.welcome-text h1 {
  font-size: 36px;
  font-weight: 800;
  margin: 0 0 14px;
  letter-spacing: -0.5px;
}
.welcome-sub {
  color: var(--xb-muted);
  font-size: 15.5px;
  line-height: 1.7;
  margin: 0 0 26px;
  max-width: 500px;
}
.welcome-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.dropzone {
  border: 1.5px dashed rgba(var(--xb-primary-rgb), 0.3);
  border-radius: 8px;
  padding: 34px 20px;
  text-align: center;
  background: rgba(var(--xb-primary-rgb), 0.03);
  transition: all 0.25s;
  cursor: pointer;
}
.dropzone:hover {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.07);
}
.dz-icon {
  font-size: 46px;
  color: var(--xb-primary);
  margin-bottom: 12px;
}
.dz-main { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.dz-sub { font-size: 13px; color: var(--xb-muted); margin: 0; }

/* 数据概览 */
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
  margin-top: 22px;
}
.stat-card {
  border-radius: 6px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 50px; height: 50px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 24px;
  color: var(--ic);
  background: color-mix(in srgb, var(--ic) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--ic) 38%, transparent);
}
.stat-num {
  font-size: 26px;
  font-weight: 800;
  line-height: 1.1;
}
.stat-label {
  font-size: 13px;
  color: var(--xb-muted);
  margin-top: 4px;
}

/* 区块 */
.block { margin-top: 40px; }
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.block-head h2 {
  font-size: 22px;
  font-weight: 800;
  margin: 0;
}
.more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--xb-muted);
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: color 0.2s;
}
.more:hover { color: var(--xb-primary); }
.env-tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--xb-success);
}
.env-tag.degraded { color: var(--xb-warn); }
.env-tag.degraded .env-dot { background: var(--xb-warn); box-shadow: 0 0 8px var(--xb-warn); }
.empty-hint {
  padding: 36px;
  text-align: center;
  color: var(--xb-muted);
  font-size: 14px;
}
.env-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--xb-success);
  box-shadow: 0 0 8px var(--xb-success);
  animation: env-pulse 1.8s infinite;
}
@keyframes env-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* 快捷功能 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
}
.quick-card {
  border-radius: 6px;
  padding: 22px;
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
  transition: transform 0.25s, border-color 0.25s, box-shadow 0.25s;
}
.quick-card:hover {
  transform: translateY(-4px);
  border-color: rgba(var(--xb-primary-rgb), 0.5);
  box-shadow: 0 0 28px rgba(var(--xb-primary-rgb), 0.12);
}
.quick-icon {
  width: 48px; height: 48px;
  flex-shrink: 0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 23px;
  color: var(--ic);
  background: color-mix(in srgb, var(--ic) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--ic) 38%, transparent);
  box-shadow: 0 0 18px color-mix(in srgb, var(--ic) 22%, transparent);
}
.quick-info { flex: 1; }
.quick-info h3 { font-size: 16px; margin: 0 0 5px; }
.quick-info p { font-size: 13px; color: var(--xb-muted); margin: 0; line-height: 1.5; }
.quick-arrow { color: var(--xb-muted); transition: transform 0.25s, color 0.25s; }
.quick-card:hover .quick-arrow { color: var(--xb-primary); transform: translateX(4px); }

/* 我的模型 */
.model-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}
.model-card {
  border-radius: 6px;
  padding: 18px;
  transition: transform 0.25s, border-color 0.25s, box-shadow 0.25s;
  cursor: pointer;
}
.model-card:hover {
  transform: translateY(-4px);
  border-color: rgba(var(--xb-primary-rgb), 0.5);
  box-shadow: 0 0 24px rgba(var(--xb-primary-rgb), 0.12);
}
.model-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.model-icon {
  width: 42px; height: 42px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  font-size: 20px;
  color: var(--xb-on-primary);
  background: var(--mc);
  box-shadow: 0 0 16px color-mix(in srgb, var(--mc) 45%, transparent);
}
.model-type {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  border: 1px solid rgba(var(--xb-primary-rgb), 0.25);
}
.model-name {
  font-weight: 600;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.model-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--xb-border);
  font-size: 12px;
  color: var(--xb-muted);
}
.model-add {
  border-radius: 6px;
  border: 1.5px dashed rgba(var(--xb-primary-rgb), 0.3);
  background: rgba(var(--xb-primary-rgb), 0.03);
  color: var(--xb-muted);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 18px;
  transition: all 0.25s;
  font-size: 14px;
  font-weight: 600;
}
.model-add .el-icon { font-size: 26px; color: var(--xb-primary); }
.model-add small { font-size: 11px; font-weight: 400; }
.model-add:hover {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.08);
  color: var(--xb-text);
}

/* 集成工具 */
.tool-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.tool-card {
  border-radius: 6px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.tool-icon {
  width: 48px; height: 48px;
  flex-shrink: 0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 23px;
  color: var(--ic);
  background: color-mix(in srgb, var(--ic) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--ic) 38%, transparent);
}
.tool-info { flex: 1; min-width: 0; }
.tool-name {
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tool-ver {
  font-size: 11px;
  font-weight: 600;
  color: var(--xb-muted);
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(var(--xb-fill-rgb), 0.06);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
.tool-desc {
  font-size: 12.5px;
  color: var(--xb-muted);
  margin-top: 5px;
  line-height: 1.5;
}
.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 999px;
  flex-shrink: 0;
}
.tool-status.ok { color: var(--xb-success); background: rgba(var(--xb-success-rgb), 0.12); }
.tool-status.warn { color: var(--xb-warn); background: rgba(var(--xb-warn-rgb), 0.12); }

/* 最近作品 */
.works {
  border-radius: 6px;
  padding: 8px;
}
.work-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 6px;
  transition: background 0.2s;
}
.work-row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.work-row + .work-row { border-top: 1px solid rgba(var(--xb-fill-rgb), 0.04); }
.work-play {
  width: 36px; height: 36px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-primary-rgb), 0.08);
  color: var(--xb-primary);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 15px;
  transition: all 0.2s;
}
.work-play:hover { background: var(--xb-primary); color: var(--xb-on-primary); }
.work-cover {
  width: 42px; height: 42px;
  flex-shrink: 0;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--xb-on-primary);
  font-size: 19px;
  background: var(--wc);
}
.work-main { flex: 1; min-width: 0; }
.work-title {
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.work-sub { font-size: 12.5px; color: var(--xb-muted); margin-top: 3px; }
.work-bar {
  width: 120px;
  height: 5px;
  border-radius: 5px;
  background: rgba(var(--xb-fill-rgb), 0.08);
  overflow: hidden;
  flex-shrink: 0;
}
.work-bar-inner {
  height: 100%;
  border-radius: 5px;
  background: linear-gradient(90deg, var(--xb-primary), var(--xb-primary-2));
}
.work-status {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  flex-shrink: 0;
}
.work-status.done { color: var(--xb-success); background: rgba(var(--xb-success-rgb), 0.12); }
.work-status.running { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.12); }
.work-status.queue { color: var(--xb-warn); background: rgba(var(--xb-warn-rgb), 0.12); }
.work-time {
  font-size: 12.5px;
  color: var(--xb-muted);
  width: 70px;
  text-align: right;
  flex-shrink: 0;
}
.work-ops { display: flex; gap: 4px; flex-shrink: 0; }
.work-ops button {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
  transition: all 0.2s;
}
.work-ops button:hover { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.08); }

/* 响应式 */
@media (max-width: 1080px) {
  .model-grid { grid-template-columns: repeat(3, 1fr); }
  .quick-grid { grid-template-columns: repeat(2, 1fr); }
  .tool-grid { grid-template-columns: 1fr; }
}
@media (max-width: 880px) {
  .welcome { grid-template-columns: 1fr; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .work-bar, .work-time { display: none; }
}
@media (max-width: 560px) {
  .model-grid { grid-template-columns: repeat(2, 1fr); }
  .quick-grid { grid-template-columns: 1fr; }
  .stats { grid-template-columns: 1fr; }
  .welcome-text h1 { font-size: 28px; }
}
</style>
