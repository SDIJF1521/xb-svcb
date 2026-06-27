<template>
  <div class="page">
    <audio
      ref="audioEl"
      style="display: none"
      @ended="playingId = null"
      @pause="onAudioPause"
    />
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// 我的作品</p>
        <h1>翻唱作品库</h1>
        <p class="page-sub">管理、试听并导出你生成的所有 AI 翻唱作品</p>
      </div>
      <router-link to="/create">
        <el-button size="large" round class="cta-btn">
          <el-icon class="el-icon--left"><Plus /></el-icon>新建翻唱
        </el-button>
      </router-link>
    </div>

    <!-- 工具条 -->
    <div class="toolbar">
      <div class="seg">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="seg-item"
          :class="{ active: filter === t.key }"
          @click="filter = t.key"
        >
          {{ t.label }}
          <span class="seg-count">{{ countOf(t.key) }}</span>
        </button>
      </div>
      <div class="search">
        <el-icon><Search /></el-icon>
        <input v-model="keyword" type="text" placeholder="搜索作品 / 模型…" />
      </div>
    </div>

    <!-- 作品列表 -->
    <div v-if="filteredWorks.length" class="works glass">
      <div class="works-th">
        <span class="col-title">作品</span>
        <span class="col-model">使用模型</span>
        <span class="col-dur">时长</span>
        <span class="col-status">状态</span>
        <span class="col-time">创建时间</span>
        <span class="col-ops">操作</span>
      </div>

      <div class="work-row" v-for="w in filteredWorks" :key="w.id">
        <div class="col-title work-title-cell">
          <button class="work-play" :disabled="w.status !== 'done'" @click="togglePlay(w.id)">
            <el-icon v-if="playingId === w.id"><VideoPause /></el-icon>
            <el-icon v-else><VideoPlay /></el-icon>
          </button>
          <div class="work-cover" :style="{ '--wc': w.color }"><el-icon><Headset /></el-icon></div>
          <div class="work-meta">
            <div class="work-name">{{ w.title }}</div>
            <div class="work-sub" v-if="w.status === 'running'">
              <span class="mini-bar"><i :style="{ width: w.progress + '%' }"></i></span>
              {{ w.progress }}%
            </div>
            <div
              class="work-sub work-err"
              v-else-if="w.status === 'failed'"
              :title="w.error || ''"
            >
              {{ w.error || '推理失败，点击日志按钮查看详情' }}
            </div>
            <div class="work-sub" v-else>{{ w.format }} · {{ w.size }}</div>
          </div>
        </div>
        <span class="col-model work-model">{{ w.model }}</span>
        <span class="col-dur work-dim">{{ w.duration }}</span>
        <span class="col-status">
          <span class="badge" :class="w.status">{{ statusText(w.status) }}</span>
        </span>
        <span class="col-time work-dim">{{ w.time }}</span>
        <span class="col-ops">
          <button class="op" title="重命名" @click="onRename(w.id, w.title)"><el-icon><EditPen /></el-icon></button>
          <button class="op" :disabled="w.status !== 'done'" title="下载" @click="onDownload(w.id)"><el-icon><Download /></el-icon></button>
          <button class="op" :disabled="w.status !== 'done'" title="进入音频编辑" @click="onEdit(w.id)"><el-icon><Scissor /></el-icon></button>
          <button class="op" v-if="w.status === 'failed'" title="打开日志" @click="onOpenLog(w.id)"><el-icon><Document /></el-icon></button>
          <button class="op" title="重新生成" @click="onRetry(w.id)"><el-icon><RefreshRight /></el-icon></button>
          <button class="op danger" title="删除" @click="onRemove(w.id)"><el-icon><Delete /></el-icon></button>
        </span>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty glass">
      <el-icon class="empty-icon"><Headset /></el-icon>
      <p class="empty-title">暂无作品</p>
      <p class="empty-sub">前往「AI 翻唱」上传歌曲并选择模型，生成你的第一首翻唱</p>
      <router-link to="/create">
        <el-button round class="cta-btn"><el-icon class="el-icon--left"><Plus /></el-icon>去创作</el-button>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  Plus,
  Search,
  VideoPlay,
  VideoPause,
  Headset,
  Download,
  Scissor,
  RefreshRight,
  Delete,
  Document,
  EditPen,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useWorksStore } from '@/stores/works'
import type { JobStatus } from '@/api'

defineOptions({ name: 'WorksPage' })

const worksStore = useWorksStore()
const { works } = storeToRefs(worksStore)
const router = useRouter()

const tabs: { key: JobStatus | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'done', label: '已完成' },
  { key: 'running', label: '生成中' },
  { key: 'queue', label: '排队中' },
  { key: 'failed', label: '失败' },
]
const route = useRoute()
const filter = ref<JobStatus | 'all'>('all')
const keyword = ref(typeof route.query.q === 'string' ? route.query.q : '')
watch(
  () => route.query.q,
  (q) => {
    keyword.value = typeof q === 'string' ? q : ''
  },
)
const playingId = ref<string | null>(null)

const countOf = (key: JobStatus | 'all') =>
  key === 'all' ? works.value.length : works.value.filter((w) => w.status === key).length

const filteredWorks = computed(() =>
  works.value.filter((w) => {
    const okStatus = filter.value === 'all' || w.status === filter.value
    const kw = keyword.value.toLowerCase()
    const okKw = !kw || w.title.toLowerCase().includes(kw) || w.model.toLowerCase().includes(kw)
    return okStatus && okKw
  }),
)

const statusText = (s: JobStatus) =>
  ({ done: '已完成', running: '生成中', queue: '排队中', failed: '失败' })[s]

const audioEl = ref<HTMLAudioElement | null>(null)
const audioLoadedFor = ref<string | null>(null)

const onAudioPause = () => {
  if (audioEl.value && audioEl.value.ended) playingId.value = null
}

const togglePlay = async (id: string) => {
  const el = audioEl.value
  if (!el) return
  if (playingId.value === id && !el.paused) {
    el.pause()
    playingId.value = null
    return
  }
  if (audioLoadedFor.value !== id) {
    const data = await api.getWorkAudio(id)
    if (!data) {
      ElMessage.error('无法加载生成的音频')
      return
    }
    el.src = data
    audioLoadedFor.value = id
  }
  await el.play()
  playingId.value = id
}

const onDownload = async (id: string) => {
  const dest = await api.exportWork(id)
  if (dest) ElMessage.success('已导出到：' + dest)
  else ElMessage.info('已取消导出')
}

const onRetry = (id: string) => worksStore.retry(id)
const onRemove = (id: string) => worksStore.remove(id)
const onOpenLog = (id: string) => api.openWorkLog(id)
const onEdit = (id: string) => router.push({ path: '/editor', query: { work: id } })

const onRename = async (id: string, current: string) => {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的作品名称', '重命名作品', {
      inputValue: current,
      inputPlaceholder: '作品名称',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (v: string) => (v && v.trim() ? true : '名称不能为空'),
    })
    const name = (value || '').trim()
    if (!name || name === current) return
    const ok = await worksStore.rename(id, name)
    if (ok) ElMessage.success('已重命名，导出文件名将同步更新')
    else ElMessage.error('重命名失败')
  } catch {
    /* 用户取消 */
  }
}

// 轮询刷新进行中 / 排队中的任务进度
let timer: ReturnType<typeof setInterval> | null = null
function pollActive() {
  works.value
    .filter((w) => w.status === 'running' || w.status === 'queue')
    .forEach((w) => worksStore.refreshOne(w.id))
}

onMounted(() => {
  worksStore.load()
  timer = setInterval(pollActive, 1000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}
.eyebrow {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 8px;
}
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; }

.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 22px rgba(var(--xb-primary-rgb), 0.4);
}

/* 工具条 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 18px;
}
.seg { display: flex; gap: 6px; flex-wrap: wrap; }
.seg-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
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
.seg-count {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(var(--xb-fill-rgb), 0.08);
  color: inherit;
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 9px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
  width: 240px;
}
.search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--xb-text);
  font-size: 14px;
  width: 100%;
}
.search input::placeholder { color: var(--xb-muted); }
.search:focus-within { border-color: var(--xb-primary); }

/* 列表 */
.works { border-radius: 6px; padding: 6px; }
.works-th, .work-row {
  display: grid;
  grid-template-columns: 2.4fr 1.3fr 0.7fr 0.9fr 1.1fr 1.1fr;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
}
.works-th {
  font-size: 12px;
  color: var(--xb-muted);
  font-weight: 600;
  letter-spacing: 0.5px;
}
.work-row {
  border-radius: 6px;
  transition: background 0.2s;
}
.work-row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.work-row + .work-row { border-top: 1px solid rgba(var(--xb-fill-rgb), 0.04); }
.col-ops { text-align: right; }

.work-title-cell { display: flex; align-items: center; gap: 12px; min-width: 0; }
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
.work-play:hover:not(:disabled) { background: var(--xb-primary); color: var(--xb-on-primary); }
.work-play:disabled { opacity: 0.35; cursor: not-allowed; }
.work-cover {
  width: 40px; height: 40px;
  flex-shrink: 0;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--xb-on-primary);
  font-size: 18px;
  background: var(--wc);
}
.work-meta { min-width: 0; }
.work-name {
  font-weight: 600;
  font-size: 14.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.work-sub {
  font-size: 12px;
  color: var(--xb-muted);
  margin-top: 3px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.mini-bar {
  width: 70px;
  height: 4px;
  border-radius: 4px;
  background: rgba(var(--xb-fill-rgb), 0.1);
  overflow: hidden;
}
.mini-bar i {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--xb-primary), var(--xb-primary-2));
}
.work-model { font-size: 13.5px; color: var(--xb-text); }
.work-dim { font-size: 13px; color: var(--xb-muted); }

.badge {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
}
.badge.done { color: var(--xb-success); background: rgba(var(--xb-success-rgb), 0.12); }
.badge.running { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.12); }
.badge.queue { color: var(--xb-warn); background: rgba(var(--xb-warn-rgb), 0.12); }
.badge.failed { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.12); }

.op {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 15px;
  transition: all 0.2s;
}
.op:hover:not(:disabled) { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.08); }
.op.danger:hover { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }
.op:disabled { opacity: 0.3; cursor: not-allowed; }

/* 空状态 */
.empty {
  border-radius: 6px;
  padding: 70px 20px;
  text-align: center;
}
.empty-icon {
  font-size: 52px;
  color: var(--xb-muted);
  opacity: 0.5;
  margin-bottom: 14px;
}
.empty-title { font-size: 18px; font-weight: 700; margin: 0 0 8px; }
.empty-sub { font-size: 14px; color: var(--xb-muted); margin: 0 0 22px; }

@media (max-width: 980px) {
  .works-th { display: none; }
  .work-row {
    grid-template-columns: 1fr auto;
    grid-template-areas:
      'title status'
      'title ops';
    row-gap: 6px;
  }
  .col-title { grid-area: title; }
  .col-status { grid-area: status; justify-self: end; }
  .col-ops { grid-area: ops; justify-self: end; }
  .col-model, .col-dur, .col-time { display: none; }
}
@media (max-width: 560px) {
  .page-head { flex-direction: column; align-items: flex-start; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .search { width: 100%; }
}
</style>
