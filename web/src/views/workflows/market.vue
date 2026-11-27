<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// 工作流商城</p>
        <h1>{{ translateUiText('工作流商城') }}</h1>
        <p class="page-sub">
          {{ translateUiText('浏览、预览并下载社区分享的 AI 翻唱工作流；下载后自动同步所需的 PyMSS 模型，并在「已保存工作流」中直接使用。') }}
        </p>
      </div>
      <div class="head-actions">
        <el-button round class="ghost-btn" @click="openSettings">
          <el-icon class="el-icon--left"><Key /></el-icon>{{ translateUiText('ModelScope 设置') }}
        </el-button>
        <el-button round class="cta-btn" @click="openUpload">
          <el-icon class="el-icon--left"><Upload /></el-icon>{{ translateUiText('上传工作流') }}
        </el-button>
      </div>
    </div>

    <div v-if="!hasToken" class="notice glass">
      <el-icon class="notice-ic"><Key /></el-icon>
      <div class="notice-main">
        <div class="notice-title">{{ translateUiText('尚未配置 ModelScope 访问令牌') }}</div>
        <div class="notice-sub">
          {{ translateUiText('浏览、预览与下载无需令牌；上传工作流时需要配置你自己的访问令牌（与模型站共用）。') }}
        </div>
      </div>
      <el-button round class="ghost-btn" @click="openSettings">{{ translateUiText('前往设置') }}</el-button>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar glass">
      <div class="field">
        <el-select v-model="scope" class="scope-select" :placeholder="translateUiText('全部工作流')" @change="onScopeChange">
          <el-option :label="translateUiText('全部工作流')" value="all" />
          <el-option :label="translateUiText('我上传的工作流')" value="mine" />
        </el-select>
      </div>
      <div class="field">
        <el-select v-model="pageSize" class="size-select" @change="onPageSizeChange">
          <el-option v-for="size in PAGE_SIZES" :key="size" :label="`${translateUiText('每页')} ${size}`" :value="size" />
        </el-select>
      </div>
      <div class="search">
        <el-icon><Search /></el-icon>
        <input
          v-model="query"
          type="text"
          :placeholder="translateUiText('搜索工作流名称、简介或标签（留空浏览全部）…')"
          @keyup.enter="doSearch"
        />
        <button v-if="query" class="search-clear" :title="translateUiText('清除')" @click="query = ''">
          <el-icon><Close /></el-icon>
        </button>
      </div>
      <el-button round class="cta-btn" :loading="loading" @click="doSearch">
        <el-icon v-if="!loading" class="el-icon--left"><Search /></el-icon>{{ translateUiText('搜索') }}
      </el-button>
      <button class="refresh-btn" :title="translateUiText('刷新')" :disabled="loading" @click="load(page, true)">
        <el-icon :class="{ spin: loading }"><RefreshRight /></el-icon>
      </button>
    </div>

    <p class="hub-hint muted">
      <el-icon><InfoFilled /></el-icon>
      {{ translateUiText('仅展示由本软件上传并通过清单校验的工作流。预览不会写入本地；下载后会保存到「已保存工作流」，并自动安装缺失的 PyMSS 模型。') }}
      <span v-if="viewer" class="viewer-chip">{{ translateUiText('当前账号') }}：{{ viewer }}</span>
    </p>

    <!-- 列表：独立滚动，分页固定在页面底部 -->
    <div ref="listEl" class="list-region">
      <div v-if="items.length" class="grid">
        <article
          v-for="item in items"
          :key="item.repo_id"
          class="card glass"
        >
          <button class="card-preview" type="button" @click="openDetail(item)">
            <WorkflowGraphPreview :graph="item.preview_graph" :height="116" compact />
            <span class="preview-mask"><el-icon><VideoPlay /></el-icon>{{ translateUiText('预览工作流') }}</span>
            <span v-if="item.downloaded" class="card-badge">
              <el-icon><CircleCheck /></el-icon>{{ translateUiText('已保存') }}
            </span>
          </button>

          <div class="card-body">
            <div class="card-title-row">
              <h3 :title="item.name">{{ item.name }}</h3>
              <span class="ver-tag">v{{ item.version }}</span>
            </div>
            <div class="card-meta">
              <span>{{ translateUiText('作者') }} {{ item.author || translateUiText('匿名') }}</span>
              <span>{{ formatDate(item.uploaded_at) }}</span>
            </div>
            <div class="stat-row">
              <span class="stat-chip">{{ item.node_count }} {{ translateUiText('节点') }}</span>
              <span class="stat-chip">{{ item.edge_count }} {{ translateUiText('连线') }}</span>
              <span v-if="(item.pymss_models || []).length" class="stat-chip pymss">
                PyMSS {{ downloadedCount(item) }}/{{ item.pymss_models!.length }}
              </span>
            </div>
            <div v-if="(item.tags || []).length" class="tag-row">
              <span v-for="tag in (item.tags || []).slice(0, 4)" :key="tag" class="mini-tag">{{ tag }}</span>
            </div>

            <div v-if="downloadJob(item.repo_id)?.status === 'running'" class="row-prog">
              <el-progress
                :percentage="Math.round(downloadJob(item.repo_id)?.pct || 0)"
                :stroke-width="5"
                :show-text="false"
                striped
                striped-flow
              />
              <span class="prog-msg">{{ translateUiText(downloadJob(item.repo_id)?.msg || '下载中…') }}</span>
            </div>
            <div v-else-if="downloadJob(item.repo_id)?.status === 'failed'" class="row-prog failed">
              <span class="prog-msg">{{ translateUiText(downloadJob(item.repo_id)?.error || '下载失败，可重试') }}</span>
            </div>

            <div class="card-actions">
              <el-button round size="small" class="ghost-btn" @click="openDetail(item)">
                <el-icon class="el-icon--left"><VideoPlay /></el-icon>{{ translateUiText('预览') }}
              </el-button>
              <el-button
                round
                size="small"
                class="cta-btn"
                :loading="downloadJob(item.repo_id)?.status === 'running'"
                @click="download(item)"
              >
                <el-icon
                  v-if="downloadJob(item.repo_id)?.status !== 'running' && item.downloaded"
                  class="el-icon--left"
                ><CircleCheck /></el-icon>
                <el-icon
                  v-else-if="downloadJob(item.repo_id)?.status !== 'running'"
                  class="el-icon--left"
                ><Download /></el-icon>
                {{ translateUiText(item.downloaded ? '重新下载' : '下载工作流') }}
              </el-button>
            </div>
          </div>
        </article>
      </div>

      <div v-else-if="loading" class="empty glass">
        <el-icon class="spin empty-icon"><Loading /></el-icon>
        <p class="empty-title">{{ translateUiText('正在读取工作流商城…') }}</p>
      </div>
      <div v-else-if="searched" class="empty glass">
        <el-icon class="empty-icon"><Shop /></el-icon>
        <p class="empty-title">{{ translateUiText('没有找到相关工作流') }}</p>
        <p class="empty-sub">
          {{ translateUiText(scope === 'mine' ? '你还没有上传过工作流，或当前令牌下没有匹配项。' : '换个关键词，或把你的工作流「上传到商城」让社区也能用。') }}
        </p>
      </div>
    </div>

    <!-- 分页组件：固定在页面底部，只统计工作流（不混入声音模型） -->
    <div v-if="total > 0" class="pager glass">
      <span class="pager-total">
        {{ translateUiText('共') }} <b>{{ total }}</b> {{ translateUiText('个工作流') }}
      </span>
      <el-pagination
        background
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        :pager-count="7"
        layout="prev, pager, next, jumper"
        @current-change="onPageChange"
      />
    </div>

    <!-- 详情 / 预览 -->
    <el-dialog
      v-model="detailVisible"
      :title="detail?.name || translateUiText('工作流详情')"
      width="min(1080px, calc(100vw - 32px))"
      class="wf-hub-detail"
      destroy-on-close
    >
      <div v-if="detailLoading && !detail" class="detail-loading">
        <el-icon class="spin"><Loading /></el-icon>
        <span>{{ translateUiText('正在读取工作流清单…') }}</span>
      </div>
      <div v-else-if="detail" class="detail-body">
        <div class="detail-head">
          <div class="detail-title-row">
            <h3>{{ detail.name }}</h3>
            <span class="ver-tag">v{{ detail.version }}</span>
            <span v-if="detail.downloaded" class="saved-tag">
              <el-icon><CircleCheck /></el-icon>{{ translateUiText('已保存到我的工作流') }}
            </span>
          </div>
          <p v-if="detail.description" class="detail-desc">{{ detail.description }}</p>
          <div class="detail-meta">
            <span>{{ translateUiText('作者') }} {{ detail.author || translateUiText('匿名') }}</span>
            <span>{{ formatDate(detail.uploaded_at) }}</span>
            <span>{{ detail.node_count }} {{ translateUiText('节点') }} · {{ detail.edge_count }} {{ translateUiText('连线') }}</span>
            <a v-if="detail.url && detail.url !== '#'" :href="detail.url" target="_blank" rel="noreferrer">
              <el-icon><Link /></el-icon>{{ translateUiText('在 ModelScope 查看') }}
            </a>
          </div>
        </div>

        <div class="preview-wrap">
          <WorkflowGraphPreview :graph="detail.graph || detail.preview_graph" :max-height="460" />
          <p class="preview-note">
            <el-icon><InfoFilled /></el-icon>
            {{ translateUiText('预览仅用于查看工作流结构，未下载前不能载入或运行；下载后会保存到「已保存工作流」，转换节点仍需要选择你本地的声音模型。') }}
          </p>
        </div>

        <div class="detail-grid">
          <section class="detail-section">
            <h4>
              {{ translateUiText('相关 PyMSS 模型') }}
              <span class="count">{{ (detail.pymss_models || []).length }}</span>
            </h4>
            <div v-if="(detail.pymss_models || []).length" class="pymss-list">
              <div v-for="model in detail.pymss_models" :key="model.name" class="pymss-item">
                <div class="pymss-main">
                  <span class="dot" :class="{ ready: model.downloaded }" />
                  <b :title="model.name">{{ model.name }}</b>
                  <small>{{ model.purpose_label || model.category_label || translateUiText('PyMSS 分离模型') }}</small>
                </div>
                <span class="pymss-state" :class="{ ready: model.downloaded }">
                  {{ translateUiText(model.downloaded ? '已安装' : '待下载') }}
                </span>
              </div>
            </div>
            <p v-else class="muted small-text">{{ translateUiText('该工作流未依赖 PyMSS 模型。') }}</p>
            <p v-if="(detail.pymss_models || []).length" class="section-note">
              {{ translateUiText('下载工作流时会自动同步安装缺失的 PyMSS 模型，已安装的会自动跳过。') }}
            </p>
          </section>

          <section class="detail-section">
            <h4>{{ translateUiText('标签') }}</h4>
            <div v-if="(detail.tags || []).length" class="tag-row">
              <span v-for="tag in detail.tags" :key="tag" class="mini-tag">{{ tag }}</span>
            </div>
            <p v-else class="muted small-text">{{ translateUiText('暂无标签') }}</p>
            <h4>{{ translateUiText('使用方式') }}</h4>
            <p class="section-note">
              {{ translateUiText('下载完成后，在 AI 翻唱工作台的「已保存工作流」面板中载入即可。') }}
            </p>
          </section>
        </div>

        <div v-if="detailJob && detailJob.status === 'running'" class="detail-progress">
          <el-progress
            :percentage="Math.round(detailJob.pct || 0)"
            :stroke-width="6"
            striped
            striped-flow
          />
          <span class="prog-msg">{{ translateUiText(detailJob.msg || '处理中…') }}</span>
        </div>
        <div v-else-if="detailJob && detailJob.status === 'failed'" class="detail-progress failed">
          <span class="prog-msg">{{ translateUiText(detailJob.error || '下载失败，可重试') }}</span>
        </div>
      </div>

      <template #footer>
        <el-button round @click="detailVisible = false">{{ translateUiText('关闭') }}</el-button>
        <el-button v-if="detail?.downloaded" round class="ghost-btn" @click="goWorkbench">
          <el-icon class="el-icon--left"><Promotion /></el-icon>{{ translateUiText('前往 AI 翻唱工作台') }}
        </el-button>
        <el-button
          round
          class="cta-btn"
          :loading="!!detailJob && detailJob.status === 'running'"
          @click="detail && download(detail)"
        >
          <el-icon v-if="!detailJob || detailJob.status !== 'running'" class="el-icon--left"><Download /></el-icon>
          {{ translateUiText(detail?.downloaded ? '重新下载并同步依赖' : '下载工作流并同步 PyMSS') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 上传工作流 -->
    <el-dialog
      v-model="uploadVisible"
      :title="translateUiText('上传工作流到商城')"
      width="min(560px, calc(100vw - 32px))"
      class="wf-hub-upload"
    >
      <div class="dialog-body">
        <p class="dialog-tip">
          {{ translateUiText('从「已保存工作流」中选择一个，上传到你的 ModelScope 公开仓库，供其他用户搜索、预览和下载。') }}
        </p>
        <label class="dialog-label">{{ translateUiText('选择工作流') }}</label>
        <el-select
          v-model="uploadWorkflowId"
          class="full"
          filterable
          :placeholder="translateUiText('选择要上传的已保存工作流')"
          @change="onUploadTargetChange"
        >
          <el-option v-for="workflow in localWorkflows" :key="workflow.id" :label="workflow.name" :value="workflow.id" />
        </el-select>
        <p v-if="!localWorkflows.length" class="dialog-tip warn">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('还没有已保存的工作流，请先到 AI 翻唱工作台画布中保存一个。') }}
        </p>
        <p v-else-if="uploadTarget?.source?.repo_id" class="dialog-tip warn">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('该工作流之前分享过，重新上传会更新同一个仓库。') }}
        </p>

        <label class="dialog-label">{{ translateUiText('名称') }}</label>
        <el-input v-model="uploadName" maxlength="120" show-word-limit :disabled="!uploadWorkflowId" />

        <label class="dialog-label">{{ translateUiText('版本号') }}</label>
        <el-input v-model="uploadVersion" maxlength="32" placeholder="1.0.0" :disabled="!uploadWorkflowId" />

        <label class="dialog-label">{{ translateUiText('简介') }}</label>
        <el-input
          v-model="uploadDescription"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="1000"
          show-word-limit
          :placeholder="translateUiText('描述适用曲风、分离 / 增强思路或使用说明')"
          :disabled="!uploadWorkflowId"
        />

        <label class="dialog-label">{{ translateUiText('标签') }}</label>
        <el-input
          v-model="uploadTags"
          :placeholder="translateUiText('例如：女声, 流行, PyMSS')"
          :disabled="!uploadWorkflowId"
        />

        <p v-if="uploadTarget && uploadRequiredModels.length" class="dialog-tip">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('该工作流依赖的 PyMSS 模型会写入清单，下载者会自动同步安装：') }}
          {{ uploadRequiredModels.join('、') }}
        </p>
        <p class="dialog-tip">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('上传只包含工作流结构与 PyMSS 依赖，不包含声音模型文件；下载者需要在转换节点选择自己的本地模型。') }}
        </p>
        <p class="dialog-tip">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('上传会在后台进行，不影响继续操作；进度可在顶栏「传输」面板查看。') }}
        </p>
      </div>
      <template #footer>
        <el-button round @click="uploadVisible = false">{{ translateUiText('取消') }}</el-button>
        <el-button
          round
          class="cta-btn"
          :loading="uploading"
          :disabled="!uploadWorkflowId || !uploadName.trim()"
          @click="confirmUpload"
        >{{ translateUiText('上传') }}</el-button>
      </template>
    </el-dialog>

    <!-- ModelScope 设置（与模型站共用令牌） -->
    <el-dialog
      v-model="settingsVisible"
      :title="translateUiText('ModelScope 设置')"
      width="min(480px, calc(100vw - 32px))"
      class="api-dialog"
    >
      <div class="dialog-body">
        <p class="dialog-tip">
          {{ translateUiText('工作流商城基于魔搭社区 ModelScope，与模型站共用访问令牌。请登录后在「个人中心 → 访问令牌」获取令牌填入下方。') }}
        </p>
        <label class="dialog-label">{{ translateUiText('访问令牌（Access Token）') }}</label>
        <el-input
          v-model="tokenDraft"
          type="password"
          show-password
          size="large"
          :placeholder="translateUiText('粘贴你的 ModelScope 访问令牌')"
        />
        <div v-if="verifiedUser" class="verify-ok">
          <el-icon><CircleCheck /></el-icon>{{ translateUiText('已验证') }}：{{ verifiedUser }}
        </div>
        <p v-if="!uploadReady" class="dialog-tip warn">
          <el-icon><InfoFilled /></el-icon>
          {{ translateUiText('未检测到上传组件（.venv-hub）。搜索 / 下载不受影响；如需上传工作流，请在安装器中安装「模型上传组件」。') }}
        </p>
      </div>
      <template #footer>
        <el-button round @click="settingsVisible = false">{{ translateUiText('取消') }}</el-button>
        <el-button round class="ghost-btn" :loading="verifying" @click="verifyToken">{{ translateUiText('验证') }}</el-button>
        <el-button round class="cta-btn" :loading="savingToken" @click="saveToken">{{ translateUiText('保存') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck,
  Close,
  Download,
  InfoFilled,
  Key,
  Link,
  Loading,
  Promotion,
  RefreshRight,
  Search,
  Shop,
  Upload,
  VideoPlay,
} from '@element-plus/icons-vue'
import { api, type CoverWorkflow, type HubJob, type WorkflowHubItem } from '@/api'
import { useTransfersStore } from '@/stores/transfers'
import { translateUiText } from '@/i18n'
import WorkflowGraphPreview from '@/components/workflow/WorkflowGraphPreview.vue'

defineOptions({ name: 'WorkflowMarketPage' })

const router = useRouter()
const transfers = useTransfersStore()

const PAGE_SIZES = [6, 12, 24]
const pageSize = ref(12)
const page = ref(1)
const total = ref(0)
const items = ref<WorkflowHubItem[]>([])
const listEl = ref<HTMLElement | null>(null)
const loading = ref(false)
const searched = ref(false)
const query = ref('')
const scope = ref<'all' | 'mine'>('all')
const viewer = ref('')

const hasToken = ref(false)
const uploadReady = ref(false)

const settingsVisible = ref(false)
const tokenDraft = ref('')
const savingToken = ref(false)
const verifying = ref(false)
const verifiedUser = ref('')

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<WorkflowHubItem | null>(null)

const uploadVisible = ref(false)
const uploading = ref(false)
const localWorkflows = ref<CoverWorkflow[]>([])
const uploadWorkflowId = ref('')
const uploadName = ref('')
const uploadVersion = ref('1.0.0')
const uploadDescription = ref('')
const uploadTags = ref('')

const uploadTarget = computed(
  () => localWorkflows.value.find((workflow) => workflow.id === uploadWorkflowId.value) || null,
)

const uploadRequiredModels = computed(() => {
  const nodes = uploadTarget.value?.nodes || []
  const names = new Set<string>()
  for (const node of nodes) {
    if (node.type !== 'separate' && node.type !== 'dereverb') continue
    if (String(node.params?.engine || '').toLowerCase() !== 'pymss') continue
    const name = String(node.params?.model || '').trim()
    if (name) names.add(name)
  }
  return [...names]
})

function formatDate(value?: string): string {
  if (!value) return translateUiText('未知时间')
  const time = Date.parse(value)
  if (Number.isNaN(time)) return value
  const date = new Date(time)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function shortModelName(name: string): string {
  const base = name.split(/[/\\]/).pop() || name
  return base.replace(/\.[^.]+$/, '')
}

function downloadedCount(item: WorkflowHubItem): number {
  return (item.pymss_models || []).filter((model) => model.downloaded).length
}

function downloadJob(repoId: string): HubJob | undefined {
  return transfers.jobByKey(`wfdl:${repoId}`)
}

const detailJob = computed(() => (detail.value ? downloadJob(detail.value.repo_id) : undefined))

async function load(targetPage = page.value, silent = false) {
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.workflowHubSearch(
      query.value.trim(),
      Math.max(1, targetPage),
      pageSize.value,
      scope.value === 'mine',
    )
    if (!res.ok) {
      if (!silent) ElMessage.error(res.error || translateUiText('读取工作流商城失败'))
      searched.value = true
      return
    }
    items.value = res.items || []
    total.value = Number(res.total || 0)
    page.value = Number(res.page || targetPage)
    if (res.viewer) viewer.value = res.viewer
    searched.value = true
    // 换页 / 搜索后让列表回到顶部；分页栏本身固定不动。
    await nextTick()
    listEl.value?.scrollTo({ top: 0 })
  } catch (err) {
    if (!silent) {
      ElMessage.error(
        `${translateUiText('读取工作流商城失败')}：${err instanceof Error ? err.message : String(err)}`,
      )
    }
  } finally {
    loading.value = false
  }
}

function doSearch() {
  void load(1)
}

function onPageChange(next: number) {
  void load(next)
}

function onPageSizeChange() {
  void load(1)
}

function onScopeChange() {
  void load(1)
}

async function refreshLocalWorkflows() {
  try {
    localWorkflows.value = await api.listCoverWorkflows()
  } catch {
    localWorkflows.value = []
  }
}

async function openSettings() {
  tokenDraft.value = await api.getModelscopeToken()
  verifiedUser.value = ''
  settingsVisible.value = true
}

async function verifyToken() {
  const value = tokenDraft.value.trim()
  if (!value) {
    ElMessage.info(translateUiText('请先填写访问令牌'))
    return
  }
  verifying.value = true
  try {
    const res = await api.verifyModelscopeToken(value)
    if (res.ok && res.username) {
      verifiedUser.value = res.username
      ElMessage.success(`${translateUiText('令牌有效')}：${res.username}`)
    } else {
      verifiedUser.value = ''
      ElMessage.error(res.error || translateUiText('令牌无效'))
    }
  } finally {
    verifying.value = false
  }
}

async function saveToken() {
  savingToken.value = true
  try {
    await api.setModelscopeToken(tokenDraft.value.trim())
    hasToken.value = !!tokenDraft.value.trim()
    settingsVisible.value = false
    ElMessage.success(translateUiText('已保存'))
    void load(page.value, true)
  } finally {
    savingToken.value = false
  }
}

async function openDetail(item: WorkflowHubItem) {
  detailVisible.value = true
  detail.value = item
  detailLoading.value = true
  try {
    const res = await api.workflowHubDetail(item.repo_id)
    if (res.ok && res.item) {
      detail.value = {
        ...item,
        ...res.item,
        downloaded: res.item.downloaded || item.downloaded,
      }
    } else {
      ElMessage.error(res.error || translateUiText('读取工作流详情失败'))
    }
  } catch (err) {
    ElMessage.error(
      `${translateUiText('读取工作流详情失败')}：${err instanceof Error ? err.message : String(err)}`,
    )
  } finally {
    detailLoading.value = false
  }
}

async function download(item: WorkflowHubItem) {
  const running = downloadJob(item.repo_id)
  if (running && running.status === 'running') {
    ElMessage.info(translateUiText('该工作流正在后台下载，请在顶栏「传输」查看进度'))
    return
  }
  const missing = (item.pymss_models || []).filter((model) => !model.downloaded)
  const lines = [
    translateUiText('下载后会保存到「已保存工作流」，可在 AI 翻唱工作台中使用。'),
    missing.length
      ? `${translateUiText('将同时下载')} ${missing.length} ${translateUiText('个缺失的 PyMSS 模型：')}${missing.map((model) => shortModelName(model.name)).join('、')}`
      : translateUiText('该工作流依赖的 PyMSS 模型都已安装，无需额外下载。'),
  ]
  try {
    await ElMessageBox.confirm(lines.join('\n'), translateUiText('下载工作流'), {
      type: 'info',
      confirmButtonText: translateUiText(item.downloaded ? '重新下载' : '开始下载'),
      cancelButtonText: translateUiText('取消'),
    })
  } catch {
    return
  }
  const res = await api.workflowHubStartDownload(item.repo_id).catch((err) => ({
    ok: false,
    error: err instanceof Error ? err.message : String(err),
  }))
  if (!res.ok) {
    ElMessage.error(res.error || translateUiText('启动下载失败'))
    return
  }
  transfers.start()
  await transfers.refresh()
  ElMessage.success(translateUiText('已加入后台下载，可在顶栏「传输」查看进度'))
}

async function openUpload() {
  if (!hasToken.value) {
    ElMessage.info(translateUiText('请先在「ModelScope 设置」填写访问令牌'))
    openSettings()
    return
  }
  if (!uploadReady.value) {
    ElMessage.warning(
      translateUiText('未安装上传组件（.venv-hub），请在安装器中安装「模型上传组件」后重试'),
    )
    return
  }
  await refreshLocalWorkflows()
  if (!localWorkflows.value.length) {
    ElMessage.info(translateUiText('还没有已保存的工作流，请先在 AI 翻唱工作台保存一个'))
    void router.push('/create')
    return
  }
  uploadWorkflowId.value = localWorkflows.value[0]!.id
  onUploadTargetChange(uploadWorkflowId.value)
  uploadVisible.value = true
}

function onUploadTargetChange(workflowId: string) {
  const workflow = localWorkflows.value.find((item) => item.id === workflowId)
  uploadName.value = workflow?.name || ''
  uploadVersion.value = workflow?.source?.version || '1.0.0'
  uploadDescription.value = ''
  uploadTags.value = ''
}

async function confirmUpload() {
  if (!uploadWorkflowId.value) return
  const name = uploadName.value.trim()
  if (!name) {
    ElMessage.info(translateUiText('请填写工作流名称'))
    return
  }
  uploading.value = true
  try {
    const res = await api
      .workflowHubStartUpload(uploadWorkflowId.value, {
        name,
        version: uploadVersion.value.trim() || '1.0.0',
        description: uploadDescription.value.trim(),
        tags: uploadTags.value.split(/[,，;；\s]+/).map((tag) => tag.trim()).filter(Boolean),
      })
      .catch((err) => ({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      }))
    if (!res.ok) {
      ElMessage.error(res.error || translateUiText('启动上传失败'))
      return
    }
    uploadVisible.value = false
    transfers.start()
    await transfers.refresh()
    ElMessage.success(translateUiText('已加入后台上传，可在顶栏「传输」查看进度'))
  } finally {
    uploading.value = false
  }
}

function goWorkbench() {
  const workflowId = detail.value?.local_workflow_id || ''
  detailVisible.value = false
  // 先让弹窗关闭动画结束，再切换路由，避免 Element Plus 的遮罩层卡住页面转场。
  window.setTimeout(() => {
    void router.push({
      path: '/create',
      query: {
        mode: 'workflow',
        ...(workflowId ? { workflow: workflowId } : {}),
      },
    })
  }, 240)
}

// 后台任务完成时同步列表的「已保存 / 依赖已安装」状态。
const handledJobs = new Set<string>()
watch(
  () => transfers.jobs.map((job) => `${job.key}:${job.status}`).join('|'),
  () => {
    let downloadedAny = false
    let uploadedAny = false
    for (const job of transfers.jobs) {
      const isDownload = job.key.startsWith('wfdl:')
      const isUpload = job.key.startsWith('wful:')
      if (!isDownload && !isUpload) continue
      if (job.status === 'running') {
        handledJobs.delete(`${job.key}:done`)
        handledJobs.delete(`${job.key}:failed`)
        continue
      }
      const signature = `${job.key}:${job.status}`
      if (handledJobs.has(signature)) continue
      handledJobs.add(signature)
      if (isUpload) {
        if (job.status === 'done') {
          uploadedAny = true
          ElMessage.success(translateUiText('工作流已上传到商城'))
        } else if (job.status === 'failed') {
          ElMessage.error(`${translateUiText('工作流上传失败')}：${job.error || ''}`)
        }
        continue
      }
      const repoId = job.key.slice(5)
      if (job.status === 'done') {
        downloadedAny = true
        const workflowId = job.result?.workflow?.id || ''
        const failedModels = new Set(
          (job.result?.pymss_failed || []).map((model) => model.name),
        )
        const markItem = (item: WorkflowHubItem) => {
          item.downloaded = true
          if (workflowId) item.local_workflow_id = workflowId
          for (const model of item.pymss_models || []) {
            if (!failedModels.has(model.name)) model.downloaded = true
          }
        }
        for (const item of items.value) {
          if (item.repo_id === repoId) markItem(item)
        }
        // 详情弹窗是独立对象；同步它，下载完成后「前往 AI 翻唱工作台」按钮才会立即出现。
        if (detail.value?.repo_id === repoId) {
          detail.value = {
            ...detail.value,
            downloaded: true,
            local_workflow_id: workflowId || detail.value.local_workflow_id,
            pymss_models: (detail.value.pymss_models || []).map((model) => ({
              ...model,
              downloaded: model.downloaded || !failedModels.has(model.name),
            })),
          }
        }
        const warnings = job.result?.warnings || []
        if (warnings.length) {
          ElMessage.warning(
            `${translateUiText('工作流已保存，但部分依赖下载失败')}：${warnings.join('；')}`,
          )
        } else {
          ElMessage.success(translateUiText('工作流已保存到「已保存工作流」，依赖模型已就绪'))
        }
      } else if (job.status === 'failed') {
        ElMessage.error(`${translateUiText('工作流下载失败')}：${job.error || ''}`)
      }
    }
    if (downloadedAny || uploadedAny) {
      void refreshLocalWorkflows()
      void load(page.value, true)
    }
  },
)

onMounted(async () => {
  transfers.start()
  const [token, ready, workflows] = await Promise.all([
    api.getModelscopeToken(),
    api.modelhubUploadReady(),
    api.listCoverWorkflows(),
  ])
  hasToken.value = !!token
  uploadReady.value = ready
  localWorkflows.value = workflows
  await load(1)
})
</script>

<style scoped>
.page {
  max-width: var(--xb-page-max, 1320px);
  margin: 0 auto;
  padding: 28px var(--xb-page-gutter, 24px) 16px;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.page-head,
.notice,
.toolbar,
.hub-hint { flex: none; }
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.eyebrow {
  color: var(--xb-primary);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 14px;
  margin: 0 0 8px;
}
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; max-width: 780px; line-height: 1.6; }
.head-actions { display: flex; gap: 10px; align-items: center; }
.glass {
  position: relative;
  background: var(--xb-panel);
  border: 1px solid var(--xb-border);
  backdrop-filter: blur(16px);
  border-radius: 16px;
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
  box-shadow: 0 0 18px rgba(var(--xb-primary-rgb), 0.35);
}
.ghost-btn {
  background: rgba(var(--xb-primary-rgb), 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.ghost-btn:hover { border-color: var(--xb-primary) !important; color: var(--xb-primary) !important; }
.muted { color: var(--xb-muted); }

.notice {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  margin-bottom: 16px;
}
.notice-ic { color: var(--xb-primary); font-size: 22px; }
.notice-main { flex: 1 1 auto; min-width: 0; }
.notice-title { font-weight: 700; margin-bottom: 4px; }
.notice-sub { color: var(--xb-muted); font-size: 13px; line-height: 1.5; }

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.field { display: flex; align-items: center; }
.scope-select { width: 138px; }
.size-select { width: 112px; }
.search {
  flex: 1 1 260px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  padding: 0 12px;
  height: 38px;
  border-radius: 999px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.04);
  color: var(--xb-muted);
}
.search input {
  flex: 1 1 auto;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--xb-text);
  font-size: 14px;
}
.search input::placeholder { color: var(--xb-muted); }
.search-clear {
  display: grid;
  place-items: center;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  padding: 2px;
}
.refresh-btn {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-primary-rgb), 0.05);
  color: var(--xb-text);
  cursor: pointer;
}
.refresh-btn:hover { border-color: var(--xb-primary); color: var(--xb-primary); }
.refresh-btn:disabled { opacity: 0.5; cursor: default; }
.spin { animation: wf-spin 1s linear infinite; }
@keyframes wf-spin { to { transform: rotate(360deg); } }

.hub-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 18px;
  font-size: 13px;
  line-height: 1.5;
}
.hub-hint .el-icon { color: var(--xb-primary); flex: none; }
.viewer-chip {
  margin-left: auto;
  padding: 1px 9px;
  border-radius: 999px;
  border: 1px solid rgba(var(--xb-primary-rgb), 0.25);
  color: var(--xb-primary);
  font-size: 11px;
  white-space: nowrap;
}

.list-region {
  flex: 1 1 auto;
  min-height: 160px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--xb-primary-rgb), 0.28) transparent;
}
.list-region::-webkit-scrollbar { width: 6px; }
.list-region::-webkit-scrollbar-track { background: transparent; }
.list-region::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(var(--xb-primary-rgb), 0.28);
}
.list-region > .empty { min-height: 100%; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(276px, 1fr));
  gap: 16px;
  min-height: 120px;
}
.card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}
.card:hover {
  transform: translateY(-2px);
  border-color: rgba(var(--xb-primary-rgb), 0.45);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
}
.card-preview {
  position: relative;
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.card-preview :deep(.wfp) { border-radius: 0; border: none; border-bottom: 1px solid var(--xb-border); }
.preview-mask {
  position: absolute;
  inset: 0 0 1px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: rgba(3, 8, 20, 0.55);
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.16s ease;
}
.card-preview:hover .preview-mask,
.card-preview:focus-visible .preview-mask { opacity: 1; }
.card-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #04231a;
  background: linear-gradient(135deg, #19f59a, #5eead4);
  box-shadow: 0 4px 14px rgba(25, 245, 154, 0.3);
}
.card-body { display: flex; flex-direction: column; gap: 8px; padding: 13px 14px 14px; }
.card-title-row { display: flex; align-items: flex-start; gap: 8px; }
.card-title-row h3 {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.ver-tag {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(var(--xb-primary-rgb), 0.35);
  color: var(--xb-primary);
  font-size: 11px;
  font-weight: 700;
}
.card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--xb-muted);
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
}
.stat-row { display: flex; gap: 6px; flex-wrap: wrap; }
.stat-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.07);
  color: var(--xb-muted);
  font-size: 11px;
}
.stat-chip.pymss { color: var(--xb-primary); border-color: rgba(var(--xb-primary-rgb), 0.28); }
.tag-row { display: flex; gap: 6px; flex-wrap: wrap; }
.mini-tag {
  padding: 1px 8px;
  border-radius: 6px;
  background: rgba(var(--xb-primary-rgb), 0.08);
  border: 1px solid rgba(var(--xb-primary-rgb), 0.18);
  color: var(--xb-text);
  font-size: 11px;
}
.row-prog { display: flex; flex-direction: column; gap: 4px; }
.prog-msg { color: var(--xb-muted); font-size: 11px; }
.row-prog.failed .prog-msg { color: #ff7a9c; }
.card-actions { display: flex; gap: 8px; margin-top: 2px; }
.card-actions .el-button { flex: 1 1 0; }

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 56px 20px;
  text-align: center;
}
.empty-icon { font-size: 38px; color: rgba(var(--xb-primary-rgb), 0.65); }
.empty-title { margin: 0; font-size: 16px; font-weight: 700; }
.empty-sub { margin: 0; color: var(--xb-muted); font-size: 13px; max-width: 520px; line-height: 1.6; }

.pager {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-top: 12px;
}
.pager-total { color: var(--xb-muted); font-size: 13px; }
.pager-total b { color: var(--xb-text); font-size: 14px; margin: 0 2px; }

.detail-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 240px;
  color: var(--xb-muted);
}
.detail-body { display: flex; flex-direction: column; gap: 16px; }
.detail-head { display: flex; flex-direction: column; gap: 8px; }
.detail-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.detail-title-row h3 { margin: 0; font-size: 20px; font-weight: 800; }
.saved-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  background: rgba(25, 245, 154, 0.14);
  border: 1px solid rgba(25, 245, 154, 0.4);
  color: #67f7c0;
  font-size: 11px;
  font-weight: 700;
}
.detail-desc { margin: 0; color: var(--xb-muted); font-size: 14px; line-height: 1.65; }
.detail-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  color: var(--xb-muted);
  font-size: 12px;
}
.detail-meta a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--xb-primary);
  text-decoration: none;
}
.preview-wrap { display: flex; flex-direction: column; gap: 8px; }
.preview-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0;
  color: var(--xb-muted);
  font-size: 12px;
  line-height: 1.55;
}
.preview-note .el-icon { color: var(--xb-warn); flex: none; margin-top: 2px; }
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 16px;
}
.detail-section {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.025);
}
.detail-section h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 700;
}
.detail-section h4 + h4 { margin-top: 16px; }
.detail-section .count {
  padding: 0 7px;
  border-radius: 999px;
  background: rgba(var(--xb-primary-rgb), 0.12);
  color: var(--xb-primary);
  font-size: 11px;
}
.pymss-list { display: flex; flex-direction: column; gap: 7px; }
.pymss-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.pymss-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pymss-main b {
  font-size: 12px;
  font-weight: 600;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pymss-main small { color: var(--xb-muted); font-size: 11px; white-space: nowrap; }
.dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.22);
}
.dot.ready { background: #19f59a; box-shadow: 0 0 8px rgba(25, 245, 154, 0.6); }
.pymss-state {
  flex: none;
  padding: 1px 8px;
  border-radius: 999px;
  color: var(--xb-muted);
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-size: 11px;
}
.pymss-state.ready { color: #67f7c0; border-color: rgba(25, 245, 154, 0.4); background: rgba(25, 245, 154, 0.1); }
.section-note { margin: 8px 0 0; color: var(--xb-muted); font-size: 12px; line-height: 1.55; }
.small-text { font-size: 12px; }
.detail-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-primary-rgb), 0.05);
}
.detail-progress.failed { border-color: rgba(255, 46, 136, 0.35); }

.dialog-body { display: flex; flex-direction: column; gap: 8px; }
.dialog-label { font-size: 12px; color: var(--xb-muted); margin-top: 4px; }
.dialog-tip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0;
  color: var(--xb-muted);
  font-size: 12px;
  line-height: 1.6;
}
.dialog-tip .el-icon { flex: none; margin-top: 2px; color: var(--xb-primary); }
.dialog-tip.warn .el-icon { color: var(--xb-warn); }
.full { width: 100%; }
.verify-ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #67f7c0;
  font-size: 12px;
}

@media (max-width: 900px) {
  .detail-grid { grid-template-columns: 1fr; }
  .card-actions .el-button { flex: 1 1 0; }
}
</style>
