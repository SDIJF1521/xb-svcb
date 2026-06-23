<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// 模型管理</p>
        <h1>声音模型</h1>
        <p class="page-sub">导入本地 SVC 模型，或在「模型站」分享与获取社区模型</p>
      </div>
      <el-button size="large" round class="ghost-btn" @click="openSettings">
        <el-icon class="el-icon--left"><Setting /></el-icon>ModelScope 设置
      </el-button>
    </div>

    <!-- 标签切换 -->
    <div class="tabs glass">
      <button class="tab" :class="{ on: tab === 'local' }" @click="tab = 'local'">
        <el-icon><FolderOpened /></el-icon>本地模型
        <span class="tab-badge">{{ modelsStore.count }}</span>
      </button>
      <button class="tab" :class="{ on: tab === 'hub' }" @click="tab = 'hub'">
        <el-icon><Connection /></el-icon>模型站
      </button>
    </div>

    <!-- ===================== 本地模型 ===================== -->
    <template v-if="tab === 'local'">
      <!-- 导入卡片 -->
      <div class="block">
        <div class="block-head">
          <h2>导入模型</h2>
          <span class="muted">{{ impFramework === 'rvc' ? '主模型(.pth) 必填，检索文件(.index) 可选' : '主模型 + 配置为必填，扩散模型可选' }}</span>
        </div>
        <div class="import-card glass">
          <!-- 框架选择 -->
          <div class="fw-row">
            <label>模型框架</label>
            <div class="seg">
              <button
                v-for="opt in importFrameworks"
                :key="opt.id"
                class="seg-btn"
                :class="{ on: impFramework === opt.id }"
                @click="impFramework = opt.id"
              >{{ opt.name }}</button>
            </div>
          </div>

          <!-- So-VITS-SVC：主模型 + 配置 + 可选扩散 -->
          <div v-if="impFramework !== 'rvc'" class="imp-grid">
            <div class="imp-field" :class="{ filled: !!imp.mainModel }">
              <label>主模型权重 <i>*</i></label>
              <button class="picker" @click="pick('mainModel', 'model')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.mainModel) || '选择 G_xxx.pth' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
            <div class="imp-field" :class="{ filled: !!imp.mainConfig }">
              <label>主模型配置 <i>*</i></label>
              <button class="picker" @click="pick('mainConfig', 'config')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.mainConfig) || '选择 config.json' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
            <div class="imp-field" :class="{ filled: !!imp.diffusionModel }">
              <label>扩散模型（可选）</label>
              <button class="picker" @click="pick('diffusionModel', 'model')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.diffusionModel) || '选择 model_xxx.pt' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
            <div class="imp-field" :class="{ filled: !!imp.diffusionConfig }">
              <label>扩散配置（可选）</label>
              <button class="picker" @click="pick('diffusionConfig', 'config')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.diffusionConfig) || '选择 diffusion.yaml' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
          </div>

          <!-- RVC：主模型(.pth) + 可选检索特征(.index) -->
          <div v-else class="imp-grid">
            <div class="imp-field" :class="{ filled: !!imp.mainModel }">
              <label>RVC 主模型 <i>*</i></label>
              <button class="picker" @click="pick('mainModel', 'model')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.mainModel) || '选择 model.pth' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
            <div class="imp-field" :class="{ filled: !!imp.indexFile }">
              <label>检索特征 .index（可选）</label>
              <button class="picker" @click="pick('indexFile', 'index')">
                <el-icon><Document /></el-icon>
                <span class="picker-text">{{ baseName(imp.indexFile) || '选择 added_xxx.index' }}</span>
                <el-icon class="picker-arrow"><Plus /></el-icon>
              </button>
            </div>
          </div>
          <div class="imp-foot">
            <div class="name-field">
              <label>模型名称</label>
              <input v-model="imp.name" type="text" :placeholder="suggestedName || '默认取主模型文件名'" />
            </div>
            <el-button round class="cta-btn" :loading="importing" :disabled="!canImport" @click="doImport">
              <el-icon v-if="!importing" class="el-icon--left"><Plus /></el-icon>导入模型
            </el-button>
          </div>
        </div>
      </div>

      <!-- 本地模型列表 -->
      <div class="block">
        <div class="block-head"><h2>我的模型</h2><span class="muted">{{ modelsStore.count }} 个</span></div>
        <div v-if="modelsStore.models.length" class="list glass">
          <div class="row" v-for="m in modelsStore.models" :key="m.id">
            <div class="row-cover" :style="{ background: m.color }"><el-icon><Microphone /></el-icon></div>
            <div class="row-main">
              <div class="row-title" :title="m.name">
                {{ m.name }}
                <span class="fw-tag">{{ frameworkLabel(m.framework) }}</span>
                <span v-if="m.id === modelsStore.defaultId" class="def-tag">默认</span>
                <span v-if="m.hasDiffusion" class="diff-tag">扩散</span>
                <span v-if="m.framework === 'rvc' && m.indexFile !== '—'" class="diff-tag">index</span>
              </div>
              <div class="row-sub">{{ m.type }} · {{ m.sr }} · {{ m.size }} · {{ m.date }}</div>
            </div>
            <div class="row-ops">
              <el-button
                v-if="m.id !== modelsStore.defaultId"
                round size="small" class="ghost-btn"
                @click="setDefault(m.id)"
              >
                <el-icon class="el-icon--left"><Star /></el-icon>设为默认
              </el-button>
              <el-button
                round size="small" class="cta-btn"
                :loading="uploadingId === m.id"
                @click="uploadModel(m)"
              >
                <el-icon v-if="uploadingId !== m.id" class="el-icon--left"><Upload /></el-icon>分享到模型站
              </el-button>
              <button class="op danger" title="删除" @click="removeModel(m)">
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>
        </div>
        <div v-else class="empty glass small">
          <span>还没有本地模型，使用上方「导入模型」添加，或在「模型站」下载社区模型。</span>
        </div>
      </div>
    </template>

    <!-- ===================== 模型站 ===================== -->
    <template v-else>
      <div v-if="!hasToken" class="notice glass">
        <el-icon class="notice-ic"><Key /></el-icon>
        <div class="notice-main">
          <div class="notice-title">尚未配置 ModelScope 访问令牌</div>
          <div class="notice-sub">
            模型站基于魔搭社区（ModelScope）。上传 / 下载需填写你自己的访问令牌（个人中心→访问令牌）。
          </div>
        </div>
        <el-button round class="cta-btn" @click="openSettings">前往设置</el-button>
      </div>

      <div class="toolbar glass">
        <div class="fw-field">
          <el-select v-model="hubFramework" class="fw-select" placeholder="架构" @change="onFrameworkChange">
            <el-option label="全部架构" value="" />
            <el-option v-for="f in frameworks" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </div>
        <div class="search">
          <el-icon><Search /></el-icon>
          <input
            v-model="hubQuery"
            type="text"
            placeholder="搜索模型站中的翻唱模型（留空浏览全部）…"
            @keyup.enter="doHubSearch"
          />
          <button v-if="hubQuery" class="search-clear" title="清除" @click="hubQuery = ''">
            <el-icon><Close /></el-icon>
          </button>
        </div>
        <el-button round class="cta-btn" :loading="hubSearching" :disabled="!hasToken" @click="doHubSearch">
          <el-icon v-if="!hubSearching" class="el-icon--left"><Search /></el-icon>搜索
        </el-button>
      </div>

      <p class="hub-hint muted">
        <el-icon><InfoFilled /></el-icon>
        仅展示由本软件上传、且通过清单校验的模型，避免无关模型干扰。下载后会自动导入「本地模型」。
      </p>

      <div v-if="hubItems.length" class="list glass">
        <div class="row" v-for="it in hubItems" :key="it.repo_id">
          <div class="row-cover hub"><el-icon><Connection /></el-icon></div>
          <div class="row-main">
            <div class="row-title" :title="it.name">
              {{ it.name }}
              <span class="fw-tag">{{ it.framework_label || it.framework || 'SVC' }}</span>
              <span v-if="it.has_diffusion" class="diff-tag">扩散</span>
            </div>
            <div class="row-sub">{{ it.sample_rate || '44.1kHz' }} · 作者 {{ it.author }}</div>
            <div v-if="downloadingRepo === it.repo_id" class="row-prog">
              <el-progress
                :percentage="Math.round(hubProg[it.repo_id]?.pct || 0)"
                :stroke-width="5"
                :show-text="false"
                striped
                striped-flow
              />
              <span class="prog-msg">{{ hubProg[it.repo_id]?.msg || '下载中…' }}</span>
            </div>
          </div>
          <div class="row-ops">
            <a v-if="it.url && it.url !== '#'" :href="it.url" target="_blank" rel="noreferrer" class="op" title="在 ModelScope 查看">
              <el-icon><Link /></el-icon>
            </a>
            <el-button
              round size="small" class="cta-btn"
              :loading="downloadingRepo === it.repo_id"
              @click="downloadHub(it)"
            >
              <el-icon v-if="downloadingRepo !== it.repo_id" class="el-icon--left"><Download /></el-icon>下载导入
            </el-button>
          </div>
        </div>
      </div>
      <div v-else-if="hubSearched && !hubSearching" class="empty glass">
        <el-icon class="empty-icon"><Connection /></el-icon>
        <p class="empty-title">没有找到相关模型</p>
        <p class="empty-sub">换个关键词，或把你的模型「分享到模型站」让社区也能用</p>
      </div>
      <div v-else-if="hasToken && !hubSearched" class="empty glass small">
        <span>点击「搜索」浏览模型站中的社区翻唱模型。</span>
      </div>
    </template>

    <!-- 分享到模型站弹窗（选择模型架构）-->
    <el-dialog v-model="uploadVisible" title="分享到模型站" width="460px" class="api-dialog">
      <div class="dialog-body">
        <p class="dialog-tip">
          将「{{ uploadTarget?.name }}」上传到你的 ModelScope <b>公开</b>仓库，供社区在模型站下载。
        </p>
        <label class="dialog-label">模型架构</label>
        <el-select v-model="uploadFramework" class="fw-select-full">
          <el-option v-for="f in frameworks" :key="f.id" :label="f.name" :value="f.id" />
        </el-select>
        <p class="dialog-tip" style="margin: 0">
          请选择该模型的框架类型，便于他人按类型筛选并正确使用（当前以 So-VITS-SVC 为主，后续将支持 RVC 等）。
        </p>
        <div v-if="!!uploadTarget && uploadingId === uploadTarget.id" class="upload-prog">
          <el-progress
            :percentage="Math.round(uploadProg.pct)"
            :stroke-width="8"
            striped
            striped-flow
          />
          <p class="prog-msg">{{ uploadProg.msg || '上传中…' }}</p>
        </div>
      </div>
      <template #footer>
        <el-button round @click="uploadVisible = false">取消</el-button>
        <el-button
          round class="cta-btn"
          :loading="!!uploadTarget && uploadingId === uploadTarget.id"
          @click="confirmUpload"
        >上传</el-button>
      </template>
    </el-dialog>

    <!-- ModelScope 设置弹窗 -->
    <el-dialog v-model="settingsVisible" title="ModelScope 设置" width="480px" class="api-dialog">
      <div class="dialog-body">
        <p class="dialog-tip">
          模型站基于
          <a href="https://www.modelscope.cn/my/myaccesstoken" target="_blank" rel="noreferrer">魔搭社区 ModelScope</a>。
          请登录后在「个人中心 → 访问令牌」获取令牌填入下方。令牌仅保存在本地，用于上传到你自己的命名空间。
        </p>
        <label class="dialog-label">访问令牌（Access Token）</label>
        <el-input
          v-model="tokenDraft"
          type="password"
          show-password
          placeholder="粘贴你的 ModelScope 访问令牌"
          size="large"
        />
        <div v-if="verifiedUser" class="verify-ok">
          <el-icon><CircleCheck /></el-icon> 已验证：{{ verifiedUser }}
        </div>
        <p v-if="!uploadReady" class="dialog-tip warn" style="margin: 0">
          <el-icon><WarningFilled /></el-icon>
          未检测到上传组件（.venv-hub）。搜索 / 下载不受影响；如需「分享到模型站」，请在安装器中安装「模型上传组件」。
        </p>
      </div>
      <template #footer>
        <el-button round @click="settingsVisible = false">取消</el-button>
        <el-button round class="ghost-btn" :loading="verifying" @click="verifyToken">验证</el-button>
        <el-button round class="cta-btn" :loading="savingToken" @click="saveToken">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Setting, FolderOpened, Connection, Document, Plus, Microphone, Star, Delete,
  Upload, Search, Close, Download, Key, Link, InfoFilled, CircleCheck, WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type HubModelItem, type ModelFramework } from '@/api'
import { useModelsStore, type ModelVM } from '@/stores/models'

defineOptions({ name: 'ModelsPage' })

const modelsStore = useModelsStore()
const tab = ref<'local' | 'hub'>('local')

/* 模型架构标签（so-vits-svc / rvc …），用于上传标注与搜索筛选 */
const frameworks = ref<ModelFramework[]>([])

function guessFramework(type: string): string {
  const t = (type || '').toLowerCase()
  if (t.includes('rvc')) return 'rvc'
  if (t.includes('ddsp')) return 'ddsp-svc'
  return 'so-vits-svc'
}

function frameworkLabel(id: string): string {
  return frameworks.value.find((f) => f.id === id)?.name || id || 'So-VITS-SVC'
}

/* ---------- 本地导入 ---------- */
/* 导入仅支持已实现推理引擎的框架（so-vits-svc / rvc） */
type ImportFw = 'so-vits-svc' | 'rvc'
const importFrameworks: { id: ImportFw; name: string }[] = [
  { id: 'so-vits-svc', name: 'So-VITS-SVC' },
  { id: 'rvc', name: 'RVC' },
]
const impFramework = ref<ImportFw>('so-vits-svc')
const imp = ref({ name: '', mainModel: '', mainConfig: '', diffusionModel: '', diffusionConfig: '', indexFile: '' })
const importing = ref(false)

function baseName(p: string): string {
  return p ? p.split(/[/\\]/).pop() || p : ''
}

const suggestedName = computed(() => baseName(imp.value.mainModel).replace(/\.[^.]+$/, ''))
const canImport = computed(() =>
  impFramework.value === 'rvc'
    ? !!imp.value.mainModel
    : !!imp.value.mainModel && !!imp.value.mainConfig,
)

async function pick(field: keyof typeof imp.value, kind: 'model' | 'config' | 'index') {
  const path =
    kind === 'index'
      ? await api.pickIndexFile()
      : kind === 'model'
        ? await api.pickModelFile()
        : await api.pickConfigFile()
  if (!path) return
  imp.value[field] = path
  // RVC：选择 .pth 主模型时，尝试自动带出同目录同名 .index（不存在则后端会忽略）
  if (impFramework.value === 'rvc' && field === 'mainModel' && !imp.value.indexFile) {
    imp.value.indexFile = path.replace(/\.[^.\\/]+$/, '.index')
  }
}

function resetImport() {
  imp.value = { name: '', mainModel: '', mainConfig: '', diffusionModel: '', diffusionConfig: '', indexFile: '' }
}

async function doImport() {
  if (!canImport.value) return
  importing.value = true
  try {
    const isRvc = impFramework.value === 'rvc'
    const created = await modelsStore.importModel({
      name: imp.value.name.trim() || undefined,
      framework: impFramework.value,
      main_model: imp.value.mainModel,
      main_config: isRvc ? undefined : imp.value.mainConfig,
      diffusion_model: isRvc ? null : imp.value.diffusionModel || null,
      diffusion_config: isRvc ? null : imp.value.diffusionConfig || null,
      index_file: isRvc ? imp.value.indexFile || null : null,
    })
    if (created) {
      ElMessage.success('已导入：' + created.name)
      resetImport()
    } else {
      ElMessage.error('导入失败，请检查所选文件')
    }
  } finally {
    importing.value = false
  }
}

async function setDefault(id: string) {
  if (await modelsStore.setDefault(id)) ElMessage.success('已设为默认模型')
}

async function removeModel(m: ModelVM) {
  try {
    await ElMessageBox.confirm(`确定删除「${m.name}」吗？本地文件会一并删除。`, '删除模型', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  if (await modelsStore.remove(m.id)) ElMessage.success('已删除')
  else ElMessage.error('删除失败')
}

/* ---------- 模型站令牌 ---------- */
const settingsVisible = ref(false)
const tokenDraft = ref('')
const savingToken = ref(false)
const verifying = ref(false)
const verifiedUser = ref('')
const hasToken = ref(false)
const uploadReady = ref(false)

async function openSettings() {
  tokenDraft.value = await api.getModelscopeToken()
  verifiedUser.value = ''
  settingsVisible.value = true
}

async function verifyToken() {
  const t = tokenDraft.value.trim()
  if (!t) {
    ElMessage.info('请先填写访问令牌')
    return
  }
  verifying.value = true
  try {
    const res = await api.verifyModelscopeToken(t)
    if (res.ok && res.username) {
      verifiedUser.value = res.username
      ElMessage.success('令牌有效：' + res.username)
    } else {
      verifiedUser.value = ''
      ElMessage.error(res.error || '令牌无效')
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
    ElMessage.success('已保存')
  } finally {
    savingToken.value = false
  }
}

/* ---------- 模型站搜索 / 下载 ---------- */
const hubQuery = ref('')
const hubFramework = ref('')
const hubSearching = ref(false)
const hubSearched = ref(false)
const hubItems = ref<HubModelItem[]>([])
const downloadingRepo = ref<string | null>(null)
/* 进度：下载按 repo_id 记录，上传单独记录 */
const hubProg = ref<Record<string, { pct: number; msg: string }>>({})
const uploadProg = ref<{ pct: number; msg: string }>({ pct: 0, msg: '' })

/** 轮询某个上传/下载操作的进度，返回一个停止函数。 */
function pollProgress(key: string, onTick: (pct: number, msg: string) => void): () => void {
  let stopped = false
  const tick = async () => {
    if (stopped) return
    try {
      const p = await api.hubProgress(key)
      if (!stopped) onTick(p.pct || 0, p.msg || '')
    } catch {
      /* 忽略单次轮询失败 */
    }
    if (!stopped) window.setTimeout(tick, 500)
  }
  tick()
  return () => { stopped = true }
}

function onFrameworkChange() {
  if (hasToken.value) doHubSearch()
}

async function doHubSearch() {
  if (!hasToken.value) {
    openSettings()
    return
  }
  hubSearching.value = true
  try {
    const res = await api.hubSearchModels(hubQuery.value.trim(), 1, hubFramework.value || undefined)
    hubSearched.value = true
    if (!res.ok) {
      hubItems.value = []
      ElMessage.error(res.error || '搜索失败')
      return
    }
    hubItems.value = res.items || []
  } finally {
    hubSearching.value = false
  }
}

async function downloadHub(it: HubModelItem) {
  downloadingRepo.value = it.repo_id
  hubProg.value = { ...hubProg.value, [it.repo_id]: { pct: 0, msg: '准备下载…' } }
  const stop = pollProgress(`dl:${it.repo_id}`, (pct, msg) => {
    hubProg.value = { ...hubProg.value, [it.repo_id]: { pct, msg } }
  })
  try {
    const res = await api.hubDownloadModel(it.repo_id)
    if (!res.ok || !res.model) {
      ElMessage.error(res.error || '下载失败')
      return
    }
    await modelsStore.load()
    ElMessage.success('已下载并导入：' + res.model.name)
  } finally {
    stop()
    downloadingRepo.value = null
    const next = { ...hubProg.value }
    delete next[it.repo_id]
    hubProg.value = next
  }
}

/* ---------- 分享到模型站（上传）---------- */
const uploadingId = ref<string | null>(null)
const uploadVisible = ref(false)
const uploadTarget = ref<ModelVM | null>(null)
const uploadFramework = ref('so-vits-svc')

function uploadModel(m: ModelVM) {
  if (!hasToken.value) {
    ElMessage.info('请先在「ModelScope 设置」填写访问令牌')
    openSettings()
    return
  }
  if (!uploadReady.value) {
    ElMessage.warning('未安装上传组件（.venv-hub），请在安装器中安装「模型上传组件」后重试')
    return
  }
  uploadTarget.value = m
  uploadFramework.value = guessFramework(m.type)
  uploadVisible.value = true
}

async function confirmUpload() {
  const m = uploadTarget.value
  if (!m) return
  uploadingId.value = m.id
  uploadProg.value = { pct: 0, msg: '准备上传…' }
  const stop = pollProgress(`ul:${m.id}`, (pct, msg) => {
    uploadProg.value = { pct, msg }
  })
  try {
    const res = await api.hubUploadModel(m.id, m.name, uploadFramework.value)
    if (res.ok) {
      uploadVisible.value = false
      ElMessage.success('上传成功，已发布到模型站')
    } else {
      ElMessage.error(res.error || '上传失败')
    }
  } finally {
    stop()
    uploadingId.value = null
  }
}

onMounted(async () => {
  await modelsStore.ensureLoaded()
  const [token, ready, fws] = await Promise.all([
    api.getModelscopeToken(),
    api.modelhubUploadReady(),
    api.listModelFrameworks(),
  ])
  hasToken.value = !!token
  uploadReady.value = ready
  frameworks.value = fws
})
</script>

<style scoped>
.page { max-width: 1320px; margin: 0 auto; padding: 28px 24px 60px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.eyebrow { color: var(--xb-primary); font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace; font-size: 14px; margin: 0 0 8px; }
.page-head h1 { font-size: 30px; font-weight: 800; margin: 0 0 8px; }
.page-sub { color: var(--xb-muted); font-size: 15px; margin: 0; }

.glass { position: relative; background: var(--xb-panel); border: 1px solid var(--xb-border); backdrop-filter: blur(16px); }
.cta-btn { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important; border: none !important; color: var(--xb-on-primary) !important; font-weight: 700; box-shadow: 0 0 18px rgba(var(--xb-primary-rgb), 0.35); }
.ghost-btn { background: rgba(var(--xb-primary-rgb), 0.06) !important; border: 1px solid var(--xb-border) !important; color: var(--xb-text) !important; font-weight: 600; }
.ghost-btn:hover { border-color: var(--xb-primary) !important; color: var(--xb-primary) !important; }

/* 标签 */
.tabs { display: inline-flex; gap: 6px; padding: 6px; border-radius: 10px; margin-bottom: 24px; }
.tab { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 7px; border: none; background: transparent; color: var(--xb-muted); font-weight: 700; font-size: 14px; cursor: pointer; transition: all 0.2s; }
.tab:hover { color: var(--xb-text); }
.tab.on { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); }
.tab-badge { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: rgba(var(--xb-fill-rgb), 0.18); }

.block { margin-bottom: 30px; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.block-head h2 { font-size: 20px; font-weight: 800; margin: 0; }
.muted { color: var(--xb-muted); font-size: 13px; }

/* 导入卡片 */
.import-card { border-radius: 10px; padding: 20px; }
.fw-row { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
.fw-row > label { font-size: 13px; font-weight: 600; color: var(--xb-text); }
.seg { display: inline-flex; gap: 4px; padding: 4px; border-radius: 9px; background: rgba(var(--xb-fill-rgb), 0.06); border: 1px solid var(--xb-border); }
.seg-btn { padding: 7px 18px; border-radius: 6px; border: none; background: transparent; color: var(--xb-muted); font-weight: 700; font-size: 13px; cursor: pointer; transition: all 0.2s; }
.seg-btn:hover { color: var(--xb-text); }
.seg-btn.on { background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); color: var(--xb-on-primary); }
.imp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.imp-field label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 7px; color: var(--xb-text); }
.imp-field label i { color: var(--xb-accent); font-style: normal; }
.picker { width: 100%; display: flex; align-items: center; gap: 10px; padding: 11px 14px; border-radius: 9px; border: 1px dashed var(--xb-border); background: rgba(var(--xb-fill-rgb), 0.04); color: var(--xb-muted); cursor: pointer; transition: all 0.2s; }
.picker:hover { border-color: var(--xb-primary); color: var(--xb-primary); }
.imp-field.filled .picker { border-style: solid; border-color: var(--xb-primary); color: var(--xb-text); }
.picker-text { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13.5px; }
.picker-arrow { opacity: 0.6; }
.imp-foot { display: flex; align-items: flex-end; gap: 16px; margin-top: 16px; }
.name-field { flex: 1; }
.name-field label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 7px; }
.name-field input { width: 100%; padding: 11px 14px; border-radius: 9px; border: 1px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), 0.04); color: var(--xb-text); outline: none; }
.name-field input:focus { border-color: var(--xb-primary); }

/* 工具条 */
.toolbar { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 6px; margin-bottom: 14px; }
.search { flex: 1; display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 9px; background: rgba(var(--xb-fill-rgb), 0.04); border: 1px solid var(--xb-border); color: var(--xb-muted); }
.search input { flex: 1; background: transparent; border: none; outline: none; color: var(--xb-text); font-size: 14px; }
.search input::placeholder { color: var(--xb-muted); }
.search:focus-within { border-color: var(--xb-primary); }
.search-clear { display: grid; place-items: center; border: none; background: none; color: var(--xb-muted); cursor: pointer; padding: 0; }
.search-clear:hover { color: var(--xb-accent); }
.hub-hint { display: flex; align-items: center; gap: 7px; margin: 0 0 18px; }

/* 列表 */
.list { border-radius: 6px; padding: 6px; }
.row { display: flex; align-items: center; gap: 14px; padding: 12px 14px; border-radius: 6px; transition: background 0.2s; }
.row:hover { background: rgba(var(--xb-primary-rgb), 0.05); }
.row + .row { border-top: 1px solid rgba(var(--xb-fill-rgb), 0.04); }
.row-cover { width: 40px; height: 40px; flex-shrink: 0; border-radius: 9px; display: grid; place-items: center; font-size: 18px; color: var(--xb-on-primary); background: linear-gradient(135deg, var(--xb-primary-2), var(--xb-accent)); }
.row-cover.hub { background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent)); }
.row-main { flex: 1; min-width: 0; }
.row-title { font-weight: 600; font-size: 14.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-sub { font-size: 12.5px; color: var(--xb-muted); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.def-tag, .diff-tag, .fw-tag { display: inline-block; margin-left: 8px; padding: 1px 7px; border-radius: 6px; font-size: 11px; font-weight: 700; vertical-align: middle; }
.def-tag { color: var(--xb-on-primary); background: var(--xb-primary); }
.diff-tag { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.14); border: 1px solid rgba(var(--xb-primary-rgb), 0.35); }
.fw-tag { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.14); border: 1px solid rgba(var(--xb-accent-rgb), 0.35); }

/* 架构筛选下拉 */
.fw-field { flex-shrink: 0; }
.fw-select { width: 140px; }
.fw-select :deep(.el-select__wrapper) { background: rgba(var(--xb-fill-rgb), 0.04); border: 1px solid var(--xb-border); border-radius: 9px; box-shadow: none; min-height: 42px; }
.fw-select :deep(.el-select__wrapper.is-focused) { border-color: var(--xb-primary); }
.fw-select :deep(.el-select__placeholder), .fw-select :deep(.el-select__selected-item) { color: var(--xb-text); }
.fw-select-full { width: 100%; }
.fw-select-full :deep(.el-select__wrapper) { background: rgba(var(--xb-fill-rgb), 0.04); border: 1px solid var(--xb-border); border-radius: 9px; box-shadow: none; min-height: 42px; }
.fw-select-full :deep(.el-select__wrapper.is-focused) { border-color: var(--xb-primary); }
.fw-select-full :deep(.el-select__selected-item) { color: var(--xb-text); }
.row-ops { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.op { width: 34px; height: 34px; border-radius: 8px; border: none; background: transparent; color: var(--xb-muted); cursor: pointer; display: grid; place-items: center; font-size: 16px; transition: all 0.2s; text-decoration: none; }
.op:hover { color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), 0.1); }
.op.danger:hover { color: var(--xb-accent); background: rgba(var(--xb-accent-rgb), 0.1); }

/* 提示条 */
.notice { display: flex; align-items: center; gap: 16px; padding: 18px 22px; border-radius: 6px; border-color: rgba(var(--xb-warn-rgb), 0.35); margin-bottom: 18px; }
.notice-ic { font-size: 26px; color: var(--xb-warn); flex-shrink: 0; }
.notice-main { flex: 1; }
.notice-title { font-weight: 700; font-size: 15px; }
.notice-sub { font-size: 13px; color: var(--xb-muted); margin-top: 4px; }

/* 空状态 */
.empty { border-radius: 6px; padding: 56px 20px; text-align: center; }
.empty.small { padding: 30px 20px; color: var(--xb-muted); font-size: 13.5px; }
.empty-icon { font-size: 46px; color: var(--xb-muted); opacity: 0.5; margin-bottom: 12px; }
.empty-title { font-size: 16px; font-weight: 700; margin: 0 0 6px; }
.empty-sub { font-size: 13px; color: var(--xb-muted); margin: 0; }

/* 弹窗 */
.dialog-body { display: flex; flex-direction: column; gap: 10px; }
.dialog-tip { font-size: 13px; color: var(--xb-muted); line-height: 1.6; margin: 0 0 6px; }
.dialog-tip a { color: var(--xb-primary); text-decoration: none; }
.dialog-tip a:hover { text-decoration: underline; }
.dialog-tip.warn { display: flex; align-items: center; gap: 6px; color: var(--xb-warn); }
.dialog-label { font-size: 13px; font-weight: 600; color: var(--xb-text); }
.verify-ok { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--xb-primary); font-weight: 600; }

/* 进度 */
.row-prog { display: flex; align-items: center; gap: 10px; margin-top: 7px; }
.row-prog :deep(.el-progress) { flex: 1; min-width: 0; }
.prog-msg { font-size: 12px; color: var(--xb-muted); white-space: nowrap; }
.row-prog .prog-msg { flex-shrink: 0; max-width: 46%; overflow: hidden; text-overflow: ellipsis; }
.upload-prog { margin-top: 6px; }
.upload-prog .prog-msg { margin: 6px 0 0; }

@media (max-width: 720px) {
  .page-head { flex-direction: column; align-items: flex-start; }
  .imp-grid { grid-template-columns: 1fr; }
  .row-ops .el-button span { display: none; }
}
</style>
