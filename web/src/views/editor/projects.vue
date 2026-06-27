<template>
  <div class="projects-page">
    <div class="projects-head">
      <div>
        <p class="eyebrow">// Audio Editor</p>
        <h1>编辑工程</h1>
        <p class="page-sub">{{ projects.length }} 个工程</p>
      </div>
      <div class="head-actions">
        <el-button round class="ghost-btn" :loading="loading" @click="loadProjects">
          <el-icon class="el-icon--left"><Refresh /></el-icon>刷新
        </el-button>
        <el-button round class="cta-btn" @click="importAudio">
          <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
        </el-button>
      </div>
    </div>

    <section v-if="loading" class="empty-panel glass">
      <el-icon class="spin"><Refresh /></el-icon>
      <p>正在加载工程</p>
    </section>

    <section v-else-if="projects.length" class="project-grid">
      <article v-for="item in projects" :key="item.id" class="project-card glass">
        <button class="project-main" @click="openProject(item.id)">
          <span class="project-mark"><el-icon><Scissor /></el-icon></span>
          <span class="project-copy">
            <span class="project-title">{{ item.title }}</span>
            <span class="project-meta">
              <i>{{ fmtTime(item.duration) }}</i>
              <i>{{ item.tracks }} 轨</i>
              <i>{{ fmtDate(item.updated_at) }}</i>
            </span>
          </span>
          <el-icon class="project-go"><Right /></el-icon>
        </button>
        <button
          type="button"
          class="project-delete"
          :class="{ deleting: isDeleting(item.id) }"
          :disabled="isDeleting(item.id)"
          :aria-label="`删除工程 ${item.title}`"
          title="删除工程"
          @pointerdown.stop
          @click.stop.prevent="deleteProject(item)"
        >
          <el-icon v-if="isDeleting(item.id)" class="spin"><Refresh /></el-icon>
          <el-icon v-else><Delete /></el-icon>
        </button>
      </article>
    </section>

    <section v-else class="empty-panel glass">
      <el-icon><Headset /></el-icon>
      <p>暂无编辑工程</p>
      <el-button round class="cta-btn" @click="importAudio">
        <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
      </el-button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Delete,
  FolderAdd,
  Headset,
  Refresh,
  Right,
  Scissor,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type EditorProjectSummary } from '@/api'

defineOptions({ name: 'EditorProjectsPage' })

const router = useRouter()
const loading = ref(false)
const projects = ref<EditorProjectSummary[]>([])
const deletingIds = ref<Set<string>>(new Set())

function isDeleting(id: string) {
  return deletingIds.value.has(id)
}

function setDeleting(id: string, value: boolean) {
  const next = new Set(deletingIds.value)
  if (value) {
    next.add(id)
  } else {
    next.delete(id)
  }
  deletingIds.value = next
}

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await api.listEditorProjects()
  } finally {
    loading.value = false
  }
}

async function importAudio() {
  const path = await api.pickAudioFile()
  if (!path) return
  const project = await api.createEditorProjectFromAudio(path)
  if (!project) {
    ElMessage.error('导入音频失败')
    return
  }
  await router.push({ path: '/editor', query: { project: project.id } })
}

async function openProject(id: string) {
  await router.push({ path: '/editor', query: { project: id } })
}

async function deleteProject(item: EditorProjectSummary) {
  if (isDeleting(item.id)) return
  try {
    await ElMessageBox.confirm(
      `删除后无法从工程列表恢复「${item.title}」。原始歌曲和翻唱作品不会删除。`,
      '删除编辑工程？',
      {
        confirmButtonText: '删除工程',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  setDeleting(item.id, true)
  try {
    const ok = await api.deleteEditorProject(item.id)
    if (!ok) {
      ElMessage.error('删除工程失败')
      await loadProjects()
      return
    }
    projects.value = projects.value.filter((p) => p.id !== item.id)
    ElMessage.success('已删除编辑工程')
  } catch {
    ElMessage.error('删除工程失败')
  } finally {
    setDeleting(item.id, false)
  }
}

function fmtTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function fmtDate(value: string) {
  if (!value) return '未记录'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString()
}

onMounted(loadProjects)
</script>

<style scoped>
.projects-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 24px 56px;
}
.projects-head {
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
.projects-head h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 800;
}
.page-sub {
  margin: 8px 0 0;
  color: var(--xb-muted);
  font-size: 13px;
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
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 14px;
}
.project-card {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
}
.project-main {
  position: relative;
  z-index: 1;
  width: 100%;
  min-height: 104px;
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr) 28px;
  align-items: center;
  gap: 14px;
  padding: 18px 54px 18px 18px;
  border: none;
  background: transparent;
  color: var(--xb-text);
  cursor: pointer;
  text-align: left;
}
.project-main:hover {
  background: rgba(var(--xb-primary-rgb), 0.06);
}
.project-mark {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(var(--xb-primary-rgb), 0.12);
  color: var(--xb-primary);
  font-size: 22px;
}
.project-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.project-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 800;
}
.project-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  color: var(--xb-muted);
  font-size: 12px;
}
.project-meta i {
  padding: 3px 7px;
  border-radius: 6px;
  background: rgba(var(--xb-fill-rgb), 0.05);
  font-style: normal;
}
.project-go {
  color: var(--xb-muted);
}
.project-delete {
  position: absolute;
  z-index: 2;
  top: 12px;
  right: 12px;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  border: 1px solid rgba(var(--xb-accent-rgb), 0.34);
  background: rgba(var(--xb-accent-rgb), 0.08);
  color: var(--xb-accent);
  cursor: pointer;
}
.project-delete:hover {
  background: rgba(var(--xb-accent-rgb), 0.16);
}
.project-delete:disabled {
  opacity: 0.7;
  cursor: progress;
}
.project-delete.deleting {
  background: rgba(var(--xb-accent-rgb), 0.14);
}
.empty-panel {
  min-height: 360px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 16px;
  border-radius: 8px;
  color: var(--xb-muted);
}
.empty-panel .el-icon {
  font-size: 38px;
  color: var(--xb-primary);
}
.empty-panel p {
  margin: 0;
  color: var(--xb-text);
  font-size: 16px;
  font-weight: 800;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
@media (max-width: 760px) {
  .projects-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .head-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .project-grid {
    grid-template-columns: 1fr;
  }
}
</style>
