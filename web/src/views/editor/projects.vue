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
        <el-button round class="ghost-btn" @click="createBlank">
          <el-icon class="el-icon--left"><Plus /></el-icon>新建空白工程
        </el-button>
        <el-button round class="ghost-btn" @click="importProject">
          <el-icon class="el-icon--left"><FolderOpened /></el-icon>导入工程
        </el-button>
        <el-button round class="cta-btn" data-guide="editor-import" @click="importAudio">
          <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
        </el-button>
        <el-button round class="ghost-btn" :class="{ active: batchMode }" @click="toggleBatchMode">
          <el-icon class="el-icon--left"><Select /></el-icon>{{ batchMode ? '退出批量' : '批量管理' }}
        </el-button>
        <el-input
          v-model="search"
          clearable
          class="project-search"
          placeholder="搜索工程名称"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
    </div>

    <section v-if="loading" class="empty-panel glass">
      <el-icon class="spin"><Refresh /></el-icon>
      <p>正在加载工程</p>
    </section>

    <template v-else>
      <section v-if="!projects.length" class="empty-panel glass" data-guide="editor-project-empty">
        <el-icon><Headset /></el-icon>
        <p>暂无编辑工程</p>
        <el-button round class="cta-btn" @click="importAudio">
          <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入音频
        </el-button>
      </section>

      <template v-else>
        <section v-if="batchMode" class="batch-bar glass">
          <span class="batch-count">已选择 {{ selectedIds.size }} 个工程</span>
          <el-button round class="ghost-btn" @click="toggleSelectAll">{{ allFilteredSelected ? '取消全选' : '全选当前' }}</el-button>
          <el-button
            round
            class="danger-btn"
            :disabled="!selectedIds.size || batchDeleting"
            :loading="batchDeleting"
            @click="deleteSelected"
          >
            <el-icon v-if="!batchDeleting" class="el-icon--left"><Delete /></el-icon>删除选中
          </el-button>
        </section>

        <section v-if="!filteredProjects.length" class="empty-panel glass">
          <el-icon><Search /></el-icon>
          <p>没有匹配的工程</p>
          <el-button round class="ghost-btn" @click="search = ''">清除搜索</el-button>
        </section>

        <section v-else class="project-grid" data-guide="editor-project-list">
          <article
            v-for="item in filteredProjects"
            :key="item.id"
            class="project-card glass"
            :class="{ batch: batchMode, selected: selectedIds.has(item.id) }"
          >
            <el-checkbox
              v-if="batchMode"
              class="project-check"
              :model-value="selectedIds.has(item.id)"
              @click.stop
              @change="toggleSelect(item.id)"
            />
            <button class="project-main" @click="onCardClick(item)">
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
              v-if="!batchMode"
              type="button"
              class="project-export"
              :disabled="isExporting(item.id)"
              :aria-label="`导出工程 ${item.title}`"
              title="导出工程文件"
              @pointerdown.stop
              @click.stop.prevent="exportProject(item)"
            >
              <el-icon v-if="isExporting(item.id)" class="spin"><Refresh /></el-icon>
              <el-icon v-else><Download /></el-icon>
            </button>
            <button
              v-if="!batchMode"
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
      </template>
    </template>

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Delete,
  Download,
  FolderAdd,
  FolderOpened,
  Headset,
  Plus,
  Refresh,
  Right,
  Scissor,
  Search,
  Select,
} from '@element-plus/icons-vue'
import 'element-plus/es/components/message-box/style/css'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type EditorProjectSummary } from '@/api'

defineOptions({ name: 'EditorProjectsPage' })

const router = useRouter()
const loading = ref(false)
const projects = ref<EditorProjectSummary[]>([])
const deletingIds = ref<Set<string>>(new Set())
const exportingIds = ref<Set<string>>(new Set())
const search = ref('')
const batchMode = ref(false)
const batchDeleting = ref(false)
const selectedIds = ref<Set<string>>(new Set())

const filteredProjects = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return projects.value
  return projects.value.filter((item) => item.title.toLowerCase().includes(keyword))
})

const allFilteredSelected = computed(
  () => filteredProjects.value.length > 0
    && filteredProjects.value.every((item) => selectedIds.value.has(item.id)),
)

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  if (!batchMode.value) selectedIds.value = new Set()
}

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  selectedIds.value = allFilteredSelected.value
    ? new Set()
    : new Set(filteredProjects.value.map((item) => item.id))
}

function onCardClick(item: EditorProjectSummary) {
  if (batchMode.value) {
    toggleSelect(item.id)
    return
  }
  void openProject(item.id)
}

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

function isExporting(id: string) {
  return exportingIds.value.has(id)
}

function setExporting(id: string, value: boolean) {
  const next = new Set(exportingIds.value)
  if (value) next.add(id)
  else next.delete(id)
  exportingIds.value = next
}

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await api.listEditorProjects()
    const alive = new Set(projects.value.map((item) => item.id))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => alive.has(id)))
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

async function createBlank() {
  const project = await api.createEditorProjectBlank()
  if (!project) {
    ElMessage.error('创建空白工程失败')
    return
  }
  await router.push({ path: '/editor', query: { project: project.id } })
}

async function importProject() {
  try {
    const result = await api.importEditorProjectBundle()
    if (result.cancelled) return
    if (!result.ok || !result.project) {
      ElMessage.error(result.error || '工程导入失败')
      return
    }
    ElMessage.success('工程已导入')
    await router.push({ path: '/editor', query: { project: result.project.id } })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '工程导入失败')
  }
}

async function exportProject(item: EditorProjectSummary) {
  if (isExporting(item.id)) return
  setExporting(item.id, true)
  try {
    const result = await api.exportEditorProjectBundle(item.id)
    if (result.cancelled) return
    if (!result.ok) {
      ElMessage.error(result.error || '工程导出失败')
      return
    }
    ElMessage.success('工程已导出到：' + result.path)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '工程导出失败')
  } finally {
    setExporting(item.id, false)
  }
}

async function openProject(id: string) {
  await router.push({ path: '/editor', query: { project: id } })
}

async function deleteSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length || batchDeleting.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 个工程吗？删除后无法从工程列表恢复。原始歌曲和翻唱作品不会删除。`,
      '批量删除编辑工程？',
      {
        confirmButtonText: '删除选中',
        cancelButtonText: '取消',
        type: 'warning',
        customClass: 'editor-delete-confirm',
      },
    )
  } catch {
    return
  }
  batchDeleting.value = true
  let removed = 0
  let failed = 0
  try {
    for (const id of ids) {
      try {
        const ok = await api.deleteEditorProject(id)
        if (ok) {
          removed += 1
          projects.value = projects.value.filter((item) => item.id !== id)
        } else {
          failed += 1
        }
      } catch {
        failed += 1
      }
    }
    selectedIds.value = new Set()
    if (failed === 0) ElMessage.success(`已删除 ${removed} 个工程`)
    else if (removed === 0) ElMessage.error('删除工程失败，请稍后重试')
    else ElMessage.warning(`已删除 ${removed} 个工程，${failed} 个失败`)
    if (failed > 0) await loadProjects()
  } finally {
    batchDeleting.value = false
  }
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
        customClass: 'editor-delete-confirm',
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
    if (selectedIds.value.has(item.id)) toggleSelect(item.id)
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
  max-width: var(--xb-page-max, 1180px);
  margin: 0 auto;
  padding: 24px var(--xb-page-gutter, 24px) 56px;
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
  padding: 18px 90px 18px 18px;
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
.project-export,
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
.project-export {
  right: 48px;
  border-color: var(--xb-border);
  background: rgba(var(--xb-primary-rgb), 0.08);
  color: var(--xb-primary);
}
.project-export:hover {
  background: rgba(var(--xb-primary-rgb), 0.16);
}
.project-delete:hover {
  background: rgba(var(--xb-accent-rgb), 0.16);
}
.project-export:disabled,
.project-delete:disabled {
  opacity: 0.7;
  cursor: progress;
}
.project-delete.deleting {
  background: rgba(var(--xb-accent-rgb), 0.14);
}
.project-search {
  width: 220px;
}
.project-search :deep(.el-input__wrapper) {
  border-radius: 999px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  box-shadow: none;
  border: 1px solid var(--xb-border);
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border-radius: 8px;
}
.batch-count {
  margin-right: auto;
  color: var(--xb-muted);
  font-size: 13px;
  font-weight: 600;
}
.danger-btn {
  background: rgba(var(--xb-accent-rgb), 0.12) !important;
  border: 1px solid rgba(var(--xb-accent-rgb), 0.4) !important;
  color: var(--xb-accent) !important;
  font-weight: 700;
}
.ghost-btn.active {
  border-color: var(--xb-primary) !important;
  color: var(--xb-primary) !important;
}
.project-card.batch .project-main {
  padding-left: 52px;
}
.project-card.selected {
  border-color: rgba(var(--xb-primary-rgb), 0.55);
  box-shadow: 0 0 0 1px rgba(var(--xb-primary-rgb), 0.28) inset;
}
.project-card.selected .project-main {
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.project-check {
  position: absolute;
  z-index: 3;
  top: 10px;
  left: 12px;
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
:global(.editor-delete-confirm.el-message-box) {
  width: min(430px, calc(100vw - 32px));
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(var(--xb-accent-rgb), .38);
  border-radius: 12px;
  background: var(--xb-bg-2);
  box-shadow: 0 22px 64px rgba(var(--xb-bg-rgb), .58), 0 0 0 1px rgba(var(--xb-fill-rgb), .06) inset;
}
:global(.editor-delete-confirm .el-message-box__header) {
  padding: 18px 20px 14px;
  border-bottom: 1px solid rgba(var(--xb-fill-rgb), .1);
  background: linear-gradient(110deg, rgba(var(--xb-accent-rgb), .13), transparent 70%);
}
:global(.editor-delete-confirm .el-message-box__title) {
  color: var(--xb-text);
  font-size: 16px;
  font-weight: 800;
}
:global(.editor-delete-confirm .el-message-box__headerbtn) {
  top: 14px;
  right: 14px;
}
:global(.editor-delete-confirm .el-message-box__headerbtn .el-message-box__close) {
  color: var(--xb-muted);
}
:global(.editor-delete-confirm .el-message-box__headerbtn:hover .el-message-box__close) {
  color: var(--xb-text);
}
:global(.editor-delete-confirm .el-message-box__content) {
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px 8px;
}
:global(.editor-delete-confirm .el-message-box__status) {
  margin-top: 2px;
  color: var(--xb-accent);
}
:global(.editor-delete-confirm .el-message-box__message) {
  color: var(--xb-muted);
  font-size: 13px;
  line-height: 1.7;
}
:global(.editor-delete-confirm .el-message-box__btns) {
  gap: 9px;
  padding: 14px 20px 18px;
}
:global(.editor-delete-confirm .el-button) {
  min-width: 82px;
  height: 34px;
  border-radius: 7px;
  font-weight: 700;
}
:global(.editor-delete-confirm .el-button--default) {
  border-color: var(--xb-border);
  background: rgba(var(--xb-fill-rgb), .05);
  color: var(--xb-text);
}
:global(.editor-delete-confirm .el-button--default:hover) {
  border-color: var(--xb-primary);
  color: var(--xb-primary);
}
:global(.editor-delete-confirm .el-button--primary) {
  border-color: transparent;
  background: var(--xb-accent);
  color: var(--xb-on-accent, #fff);
  box-shadow: 0 7px 18px rgba(var(--xb-accent-rgb), .22);
}
:global(.editor-delete-confirm .el-button--primary:hover) {
  filter: brightness(1.08);
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
  .project-search {
    width: 100%;
  }
}
</style>
