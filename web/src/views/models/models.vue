<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <p class="eyebrow">// 我的模型</p>
        <h1>SVC 模型库</h1>
        <p class="page-sub">导入并管理你的 SVC 歌声模型，翻唱时可直接调用</p>
      </div>
      <el-button size="large" round class="cta-btn" @click="openImport">
        <el-icon class="el-icon--left"><FolderAdd /></el-icon>导入模型
      </el-button>
    </div>

    <!-- 概览 -->
    <div class="summary">
      <div class="sum-card glass" v-for="s in summary" :key="s.label">
        <div class="sum-num">{{ s.value }}</div>
        <div class="sum-label">{{ s.label }}</div>
      </div>
    </div>

    <!-- 工具条 -->
    <div class="toolbar">
      <div class="seg">
        <button
          v-for="t in typeTabs"
          :key="t"
          class="seg-item"
          :class="{ active: typeFilter === t }"
          @click="typeFilter = t"
        >{{ t }}</button>
      </div>
      <div class="search">
        <el-icon><Search /></el-icon>
        <input v-model="keyword" type="text" placeholder="搜索模型名称…" />
      </div>
    </div>

    <!-- 模型网格 -->
    <div class="grid">
      <div
        class="model-card glass"
        v-for="m in filteredModels"
        :key="m.id"
        :class="{ default: m.id === defaultId }"
      >
        <div class="mc-top">
          <div class="mc-icon" :style="{ '--mc': m.color }">
            <el-icon><Microphone /></el-icon>
          </div>
          <span class="mc-type">{{ m.type }}</span>
        </div>

        <div class="mc-name" :title="m.name">{{ m.name }}</div>
        <span v-if="m.id === defaultId" class="mc-default-tag">
          <el-icon><Star /></el-icon> 默认
        </span>

        <div class="mc-specs">
          <div><span>主模型</span><b :title="m.mainModel">{{ m.mainModel }}</b></div>
          <div><span>扩散模型</span><b :title="m.diffusionModel">{{ m.diffusionModel }}</b></div>
          <div><span>大小 / 导入</span><b>{{ m.size }} · {{ m.date }}</b></div>
        </div>

        <div class="mc-actions">
          <button class="mc-btn primary" @click="useModel(m)">
            <el-icon><Microphone /></el-icon>去翻唱
          </button>
          <button class="mc-btn" :disabled="m.id === defaultId" @click="setDefault(m.id)" title="设为默认">
            <el-icon><Star /></el-icon>
          </button>
          <button class="mc-btn danger" @click="removeModel(m.id)" title="删除">
            <el-icon><Delete /></el-icon>
          </button>
        </div>
      </div>

      <!-- 导入卡片 -->
      <button class="import-card" @click="openImport">
        <el-icon><FolderAdd /></el-icon>
        <span>导入 SVC 模型</span>
        <small>主模型 + 扩散模型</small>
      </button>
    </div>

    <!-- 导入对话框：手动从本地选择四个文件 -->
    <div v-if="showImport" class="modal-mask" @click.self="closeImport">
      <div class="modal glass">
        <div class="corner tl"></div>
        <div class="corner tr"></div>
        <div class="corner bl"></div>
        <div class="corner br"></div>
        <div class="modal-head">
          <h2>导入模型</h2>
          <button class="icon-x" @click="closeImport"><el-icon><Close /></el-icon></button>
        </div>

        <p class="modal-desc">从本地手动选择文件。主模型与扩散模型共同参与推理，二者及各自配置文件均需导入。</p>

        <div class="form-field">
          <label>模型名称</label>
          <input v-model="form.name" class="text-input" type="text" placeholder="为这组模型取个名字（可选）" />
        </div>

        <div class="picker-group">
          <div class="group-title"><span class="dot main"></span>主模型</div>
          <button class="picker" :class="{ filled: form.mainModel }" @click="pick('mainModel', 'model')">
            <el-icon><component :is="form.mainModel ? Document : FolderAdd" /></el-icon>
            <span class="picker-text">{{ form.mainModel ? baseName(form.mainModel) : '选择主模型权重 (.pth/.pt/.onnx)' }}</span>
            <el-icon v-if="form.mainModel" class="picker-ok"><Select /></el-icon>
          </button>
          <button class="picker" :class="{ filled: form.mainConfig }" @click="pick('mainConfig', 'config')">
            <el-icon><component :is="form.mainConfig ? Document : FolderAdd" /></el-icon>
            <span class="picker-text">{{ form.mainConfig ? baseName(form.mainConfig) : '选择主模型配置 (.json/.yaml)' }}</span>
            <el-icon v-if="form.mainConfig" class="picker-ok"><Select /></el-icon>
          </button>
        </div>

        <div class="picker-group">
          <div class="group-title"><span class="dot diff"></span>扩散模型</div>
          <button class="picker" :class="{ filled: form.diffusionModel }" @click="pick('diffusionModel', 'model')">
            <el-icon><component :is="form.diffusionModel ? Document : FolderAdd" /></el-icon>
            <span class="picker-text">{{ form.diffusionModel ? baseName(form.diffusionModel) : '选择扩散模型权重 (.pt/.pth)' }}</span>
            <el-icon v-if="form.diffusionModel" class="picker-ok"><Select /></el-icon>
          </button>
          <button class="picker" :class="{ filled: form.diffusionConfig }" @click="pick('diffusionConfig', 'config')">
            <el-icon><component :is="form.diffusionConfig ? Document : FolderAdd" /></el-icon>
            <span class="picker-text">{{ form.diffusionConfig ? baseName(form.diffusionConfig) : '选择扩散模型配置 (.yaml/.json)' }}</span>
            <el-icon v-if="form.diffusionConfig" class="picker-ok"><Select /></el-icon>
          </button>
        </div>

        <p class="modal-note"><el-icon><Select /></el-icon> 文件将复制保存到本地模型目录，不会上传云端。</p>

        <div class="modal-foot">
          <el-button round class="ghost-btn" @click="closeImport">取消</el-button>
          <el-button round class="cta-btn" :disabled="!canImport" :loading="importing" @click="confirmImport">
            导入模型
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  FolderAdd,
  Search,
  Microphone,
  Star,
  Delete,
  Close,
  Document,
  Select,
} from '@element-plus/icons-vue'
import { api } from '@/api'
import { useModelsStore, type ModelVM } from '@/stores/models'

defineOptions({ name: 'ModelsPage' })

const router = useRouter()
const modelsStore = useModelsStore()
const { models, defaultId } = storeToRefs(modelsStore)

const showImport = ref(false)
const importing = ref(false)
const keyword = ref('')

const typeTabs = ['全部', 'SVC', 'So-VITS', 'RVC']
const typeFilter = ref('全部')

const form = reactive({
  name: '',
  mainModel: '',
  mainConfig: '',
  diffusionModel: '',
  diffusionConfig: '',
})

const canImport = computed(
  () =>
    !!form.mainModel &&
    !!form.mainConfig &&
    !!form.diffusionModel &&
    !!form.diffusionConfig,
)

const baseName = (p: string) => p.split(/[/\\]/).pop() || p

const summary = computed(() => [
  { value: models.value.length, label: '已导入模型' },
  { value: new Set(models.value.map((m) => m.type)).size, label: '模型类型' },
  { value: models.value.length ? `${models.value.length} 个` : '0 个', label: '本地存储' },
])

const filteredModels = computed(() =>
  models.value.filter((m) => {
    const okType = typeFilter.value === '全部' || m.type === typeFilter.value
    const okKw = !keyword.value || m.name.toLowerCase().includes(keyword.value.toLowerCase())
    return okType && okKw
  }),
)

const useModel = async (m: ModelVM) => {
  await modelsStore.setDefault(m.id)
  router.push('/create')
}

const setDefault = (id: string) => modelsStore.setDefault(id)
const removeModel = (id: string) => modelsStore.remove(id)

function openImport() {
  form.name = ''
  form.mainModel = ''
  form.mainConfig = ''
  form.diffusionModel = ''
  form.diffusionConfig = ''
  showImport.value = true
}

function closeImport() {
  if (!importing.value) showImport.value = false
}

async function pick(field: keyof typeof form, kind: 'model' | 'config') {
  const path = kind === 'model' ? await api.pickModelFile() : await api.pickConfigFile()
  if (path) form[field] = path
}

async function confirmImport() {
  if (!canImport.value || importing.value) return
  importing.value = true
  try {
    const created = await modelsStore.importModel({
      name: form.name || undefined,
      main_model: form.mainModel,
      main_config: form.mainConfig,
      diffusion_model: form.diffusionModel,
      diffusion_config: form.diffusionConfig,
    })
    if (created) showImport.value = false
  } finally {
    importing.value = false
  }
}

onMounted(() => modelsStore.ensureLoaded())
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
  color: #05060d !important;
  font-weight: 700;
  box-shadow: 0 0 22px rgba(0, 240, 255, 0.4);
}
.ghost-btn {
  background: rgba(0, 240, 255, 0.06) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}

/* 概览 */
.summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  margin-bottom: 24px;
}
.sum-card { border-radius: 6px; padding: 18px 22px; }
.sum-num { font-size: 26px; font-weight: 800; color: var(--xb-primary); }
.sum-label { font-size: 13px; color: var(--xb-muted); margin-top: 4px; }

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
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.02);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}
.seg-item:hover { color: var(--xb-text); border-color: rgba(0, 240, 255, 0.45); }
.seg-item.active {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
  background: rgba(0, 240, 255, 0.1);
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.04);
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

/* 网格 */
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
}
.model-card {
  border-radius: 6px;
  padding: 20px;
  transition: transform 0.25s, border-color 0.25s, box-shadow 0.25s;
}
.model-card:hover {
  transform: translateY(-4px);
  border-color: rgba(0, 240, 255, 0.5);
  box-shadow: 0 0 24px rgba(0, 240, 255, 0.12);
}
.model-card.default { border-color: rgba(255, 174, 0, 0.45); }
.mc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.mc-icon {
  width: 46px; height: 46px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 21px;
  color: #05060d;
  background: var(--mc);
  box-shadow: 0 0 16px color-mix(in srgb, var(--mc) 45%, transparent);
}
.mc-type {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 6px;
  color: var(--xb-primary);
  background: rgba(0, 240, 255, 0.1);
  border: 1px solid rgba(0, 240, 255, 0.25);
}
.mc-name {
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mc-default-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #ffae00;
  margin-top: 6px;
}
.mc-specs {
  margin: 14px 0;
  padding: 14px 0;
  border-top: 1px solid var(--xb-border);
  border-bottom: 1px solid var(--xb-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mc-specs div {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.mc-specs span { color: var(--xb-muted); }
.mc-specs b { font-weight: 600; }
.mc-actions { display: flex; gap: 8px; }
.mc-btn {
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.03);
  color: var(--xb-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  padding: 0 12px;
  transition: all 0.2s;
}
.mc-btn.primary {
  flex: 1;
  color: var(--xb-primary);
  border-color: rgba(0, 240, 255, 0.4);
  background: rgba(0, 240, 255, 0.08);
}
.mc-btn.primary:hover { background: var(--xb-primary); color: #05060d; }
.mc-btn:hover { color: var(--xb-text); border-color: rgba(0, 240, 255, 0.45); }
.mc-btn.danger:hover { color: var(--xb-accent); border-color: var(--xb-accent); background: rgba(255, 46, 136, 0.1); }
.mc-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 导入卡片 */
.import-card {
  border-radius: 6px;
  border: 1.5px dashed rgba(0, 240, 255, 0.3);
  background: rgba(0, 240, 255, 0.03);
  color: var(--xb-muted);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  font-size: 15px;
  font-weight: 600;
  transition: all 0.25s;
}
.import-card .el-icon { font-size: 32px; color: var(--xb-primary); }
.import-card small { font-size: 12px; font-weight: 400; }
.import-card:hover {
  border-color: var(--xb-primary);
  background: rgba(0, 240, 255, 0.08);
  color: var(--xb-text);
}

/* 切角 */
.corner { position: absolute; width: 14px; height: 14px; border-color: var(--xb-primary); }
.corner.tl { top: -1px; left: -1px; border-top: 2px solid; border-left: 2px solid; }
.corner.tr { top: -1px; right: -1px; border-top: 2px solid; border-right: 2px solid; }
.corner.bl { bottom: -1px; left: -1px; border-bottom: 2px solid; border-left: 2px solid; }
.corner.br { bottom: -1px; right: -1px; border-bottom: 2px solid; border-right: 2px solid; }

/* 弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(3, 4, 10, 0.7);
  backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  padding: 24px;
}
.modal {
  width: 100%;
  max-width: 520px;
  border-radius: 8px;
  padding: 26px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6), 0 0 50px rgba(0, 240, 255, 0.1);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.modal-head h2 { font-size: 19px; font-weight: 800; margin: 0; }
.modal-desc { font-size: 13px; color: var(--xb-muted); line-height: 1.6; margin: 0 0 18px; }
.form-field { margin-bottom: 18px; }
.form-field label { display: block; font-size: 13px; color: var(--xb-text); margin-bottom: 8px; font-weight: 500; }
.text-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--xb-border);
  color: var(--xb-text);
  font-size: 14px;
  outline: none;
}
.text-input:focus { border-color: var(--xb-primary); }
.text-input::placeholder { color: var(--xb-muted); }
.picker-group { margin-bottom: 16px; }
.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--xb-text);
  margin-bottom: 10px;
}
.group-title .dot { width: 8px; height: 8px; border-radius: 50%; }
.group-title .dot.main { background: var(--xb-primary); box-shadow: 0 0 8px var(--xb-primary); }
.group-title .dot.diff { background: var(--xb-accent); box-shadow: 0 0 8px var(--xb-accent); }
.picker {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.02);
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13.5px;
  text-align: left;
  transition: all 0.2s;
  margin-bottom: 8px;
}
.picker:hover { border-color: rgba(0, 240, 255, 0.45); color: var(--xb-text); }
.picker.filled { color: var(--xb-text); border-color: rgba(0, 240, 255, 0.4); background: rgba(0, 240, 255, 0.05); }
.picker .picker-text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.picker-ok { color: #19f59a; }
.modal-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--xb-muted);
  margin: 4px 0 18px;
}
.modal-note .el-icon { color: #19f59a; }
.icon-x {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 17px;
}
.icon-x:hover { color: var(--xb-accent); background: rgba(255, 46, 136, 0.1); }
.modal-drop {
  border: 1.5px dashed rgba(0, 240, 255, 0.3);
  border-radius: 8px;
  padding: 36px 20px;
  text-align: center;
  background: rgba(0, 240, 255, 0.03);
}
.md-icon { font-size: 44px; color: var(--xb-primary); margin-bottom: 10px; }
.md-main { font-size: 15px; font-weight: 600; margin: 0 0 6px; }
.md-sub { font-size: 12.5px; color: var(--xb-muted); margin: 0; }
.modal-tips {
  list-style: none;
  padding: 0;
  margin: 18px 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal-tips li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--xb-muted);
}
.modal-tips .el-icon { color: #19f59a; }
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1080px) {
  .grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 860px) {
  .grid { grid-template-columns: repeat(2, 1fr); }
  .summary { grid-template-columns: 1fr; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .search { width: 100%; }
}
@media (max-width: 520px) {
  .grid { grid-template-columns: 1fr; }
  .page-head { flex-direction: column; align-items: flex-start; }
}
</style>
