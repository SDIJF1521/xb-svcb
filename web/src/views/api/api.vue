<template>
  <div class="api-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">DEVELOPER ACCESS</p>
        <h1>{{ translateUiText('API 接入') }}</h1>
        <p class="subtitle">{{ translateUiText('FastAPI 服务默认关闭，只在本次软件运行期间由你手动启用。') }}</p>
      </div>
      <div class="head-actions">
        <span class="service-state" :class="{ running: status.running }">
          <i></i>{{ translateUiText(status.running ? '服务运行中' : '服务已停止') }}
        </span>
        <el-button
          v-if="!status.running"
          type="primary"
          :loading="busy === 'start'"
          @click="startServer"
        >
          <el-icon><VideoPlay /></el-icon>
          {{ translateUiText('启动服务') }}
        </el-button>
        <el-button
          v-else
          type="danger"
          plain
          :loading="busy === 'stop'"
          @click="stopServer"
        >
          <el-icon><SwitchButton /></el-icon>
          {{ translateUiText('停止服务') }}
        </el-button>
      </div>
    </header>

    <section class="control-band" data-guide="api-service">
      <div class="section-title">
        <div>
          <h2>{{ translateUiText('服务配置') }}</h2>
          <p>{{ translateUiText('修改监听范围或端口前需要先停止服务。') }}</p>
        </div>
        <el-button :disabled="status.running" :loading="busy === 'save'" @click="saveConfig">
          <el-icon><DocumentChecked /></el-icon>
          {{ translateUiText('保存配置') }}
        </el-button>
      </div>

      <div class="settings-grid">
        <label class="field-group">
          <span>{{ translateUiText('监听范围') }}</span>
          <el-radio-group v-model="draft.scope" :disabled="status.running">
            <el-radio-button value="local">{{ translateUiText('仅本机') }}</el-radio-button>
            <el-radio-button value="lan">{{ translateUiText('局域网') }}</el-radio-button>
          </el-radio-group>
          <small>{{ scopeHint }}</small>
        </label>

        <label class="field-group port-field">
          <span>{{ translateUiText('监听端口') }}</span>
          <el-input-number
            v-model="draft.port"
            :min="1024"
            :max="65535"
            controls-position="right"
            :disabled="status.running"
          />
          <small>{{ translateUiText('防火墙或其他程序占用端口时，请更换端口。') }}</small>
        </label>

        <div class="field-group domain-field">
          <span>{{ translateUiText('绑定域名') }}</span>
          <el-input
            v-model="draft.domain"
            :placeholder="translateUiText('例如 test.juzidc.cn')"
            :style="domainInputStyle"
            :disabled="status.running || draft.scope === 'local'"
          />
          <small>{{ translateUiText(draft.scope === 'local' ? '仅局域网监听模式支持绑定域名。' : '使用前请将域名 DNS 解析到本机公网IP。') }}</small>
        </div>

      </div>



      <div class="address-block">
        <span class="address-label">{{ translateUiText('访问地址') }}</span>
        <div class="address-list">
          <button
            v-for="url in status.base_urls"
            :key="url"
            class="address-row"
            :title="translateUiText('复制地址')"
            @click="copyText(url, '访问地址')"
          >
            <code>{{ url }}</code>
            <el-icon><CopyDocument /></el-icon>
          </button>
        </div>
        <div class="runtime-actions">
          <el-button :disabled="!status.running" :loading="busy === 'test'" @click="testServer">
            <el-icon><Connection /></el-icon>
            {{ translateUiText('连通性测试') }}
          </el-button>
          <el-button :disabled="!status.running" @click="openDocs('docs')">
            <el-icon><Notebook /></el-icon>
            Swagger
          </el-button>
          <el-button :disabled="!status.running" @click="openDocs('redoc')">
            <el-icon><Reading /></el-icon>
            ReDoc
          </el-button>
        </div>
      </div>

      <div v-if="testResult" class="test-result" :class="{ ok: testResult.ok }">
        <el-icon><component :is="testResult.ok ? CircleCheck : WarningFilled" /></el-icon>
        <span>{{ testResult.message || testResult.error }}</span>
        <code v-if="testResult.ok">{{ testResult.latency_ms }} ms · {{ testResult.model_count }} 个模型</code>
      </div>
      <p v-if="status.last_error && !status.running" class="last-error">{{ translateUiText(status.last_error) }}</p>
    </section>

    <section class="key-band" data-guide="api-keys">
      <div class="section-title">
        <div>
          <h2>{{ translateUiText('API 密钥') }}</h2>
          <p>{{ translateUiText('每个密钥可单独设置有效期和启用状态，修改前请先停止服务。') }}</p>
        </div>
        <el-button type="primary" plain :disabled="status.running" @click="openKeyDialog()">
          <el-icon><Plus /></el-icon>
          {{ translateUiText('添加密钥') }}
        </el-button>
      </div>
      <div class="key-list">
        <article v-for="item in status.api_keys" :key="item.id" class="key-card">
          <div class="key-card-head">
            <strong>{{ item.name }}</strong>
            <el-tag :type="item.enabled && !item.expired ? 'success' : 'info'" size="small">
              {{ translateUiText(item.expired ? '已过期' : item.enabled ? '已启用' : '已禁用') }}
            </el-tag>
          </div>
          <div class="key-secret-row">
            <code :title="translateUiText('单击复制完整 API 密钥')" @click="copyApiKey(item)">{{ visibleKeys[item.id] ? item.secret : maskKey(item.secret) }}</code>
            <el-button text :title="translateUiText('复制 API 密钥')" @click="copyApiKey(item)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
            <el-button text :title="translateUiText(visibleKeys[item.id] ? '隐藏 API 密钥' : '显示 API 密钥')" @click="toggleKeyVisible(item.id)">
              <el-icon><Hide v-if="visibleKeys[item.id]" /><View v-else /></el-icon>
            </el-button>
          </div>
          <div class="key-card-info">
            <span>{{ translateUiText('创建于') }} {{ formatKeyDate(item.created_at) }}</span>
            <span>{{ item.expires_at ? `${translateUiText('到期于')} ${formatKeyDate(item.expires_at)}` : translateUiText('永不过期') }}</span>
          </div>
          <div class="key-card-actions">
            <el-switch
              :model-value="item.enabled"
              :disabled="status.running || item.expired"
              :active-text="translateUiText('启用')"
              :inactive-text="translateUiText('禁用')"
              @change="toggleKey(item, Boolean($event))"
            />
            <el-button text :disabled="status.running" @click="openKeyDialog(item)">
              <el-icon><Edit /></el-icon>{{ translateUiText('编辑') }}
            </el-button>
            <el-button text type="danger" :disabled="status.running || status.api_keys.length <= 1" @click="removeKey(item)">
              <el-icon><Delete /></el-icon>{{ translateUiText('删除') }}
            </el-button>
          </div>
        </article>
        <el-empty v-if="!status.api_keys.length" :description="translateUiText('暂无 API 密钥')" :image-size="64" />
      </div>
    </section>

    <el-dialog v-model="keyDialogVisible" :title="translateUiText(editingKeyId ? '编辑 API Key' : '添加 API Key')" width="min(460px, calc(100vw - 32px))">
      <el-form label-position="top">
        <el-form-item :label="translateUiText('名称')">
          <el-input v-model="keyForm.name" maxlength="40" show-word-limit :placeholder="translateUiText('例如：生产环境')" />
        </el-form-item>
        <el-form-item :label="translateUiText('有效期')">
          <el-date-picker
            v-model="keyForm.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            :placeholder="translateUiText('留空表示永不过期')"
            clearable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="translateUiText('状态')">
          <el-switch v-model="keyForm.enabled" :active-text="translateUiText('启用')" :inactive-text="translateUiText('禁用')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="keyDialogVisible = false">{{ translateUiText('取消') }}</el-button>
        <el-button type="primary" :loading="busy === 'key-save'" @click="saveKey">{{ translateUiText('保存') }}</el-button>
      </template>
    </el-dialog>

    <section class="docs-band" data-guide="api-docs">
    <div class="section-title">
      <div>
        <h2>{{ translateUiText('调用文档') }}</h2>
        <p>{{ translateUiText('典型流程：上传音频、读取模型、创建任务、轮询状态、下载成品。') }}</p>
      </div>
      <el-segmented v-model="sampleLanguage" :options="sampleOptions" />
    </div>

    <div class="docs-layout">
      <div class="code-panel">
        <div class="code-head">
          <span>{{ sampleLanguage === 'python' ? 'Python · requests' : 'PowerShell · Invoke-RestMethod' }}</span>
          <button :title="translateUiText('复制示例')" @click="copyText(activeSample, '调用示例')">
            <el-icon><CopyDocument /></el-icon>
          </button>
        </div>
        <pre><code>{{ activeSample }}</code></pre>
      </div>

      <div class="endpoint-panel">
        <div class="endpoint-head">
          <span>{{ translateUiText('v1 接口') }}</span>
          <small>{{ translateUiText('所有受保护接口均需 X-API-Key') }}</small>
        </div>
        <div class="endpoint-list">
          <div v-for="item in endpoints" :key="item.method + item.path" class="endpoint-row">
            <span class="method" :class="item.method.toLowerCase()">{{ item.method }}</span>
            <code>{{ item.path }}</code>
            <span>{{ translateUiText(item.label) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="notes-grid">
      <div>
        <el-icon><UploadFilled /></el-icon>
        <span>{{ translateUiText('上传限制') }}</span>
        <p>{{ translateUiText('不设置文件大小上限，按流式写入磁盘；支持 WAV、FLAC、MP3、M4A、AAC、OGG、Opus 及常见视频容器。') }}</p>
      </div>
      <div>
        <el-icon><Lock /></el-icon>
        <span>{{ translateUiText('外部访问') }}</span>
        <p>{{ translateUiText('局域网模式监听所有网卡。仅在可信网络使用，并在调用方妥善保存 API Key。') }}</p>
      </div>
      <div>
        <el-icon><Timer /></el-icon>
        <span>{{ translateUiText('异步任务') }}</span>
        <p>{{ translateUiText('创建接口返回 202；轮询任务到 done 后，再通过 result_url 下载音频。') }}</p>
      </div>
    </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  Connection,
  Delete,
  Edit,
  Hide,
  Plus,
  CopyDocument,
  DocumentChecked,
  Lock,
  Notebook,
  Reading,
  SwitchButton,
  Timer,
  UploadFilled,
  VideoPlay,
  View,
  WarningFilled,
} from '@element-plus/icons-vue'
import { api, type HttpApiKey, type HttpApiKeyResult, type HttpApiScope, type HttpApiStatus, type HttpApiTestResult } from '@/api'
import { translateUiText, useI18n } from '@/i18n'

defineOptions({ name: 'ApiAccess' })

const { locale } = useI18n()

const emptyStatus: HttpApiStatus = {
  running: false,
  scope: 'local',
  host: '127.0.0.1',
  port: 8760,
  domain: '',
  domain_url: '',
  api_key: '',
  api_keys: [],
  base_urls: ['http://127.0.0.1:8760'],
  docs_url: 'http://127.0.0.1:8760/docs',
  redoc_url: 'http://127.0.0.1:8760/redoc',
}

const status = reactive<HttpApiStatus>({ ...emptyStatus })
const visibleKeys = reactive<Record<string, boolean>>({})
const keyDialogVisible = ref(false)
const editingKeyId = ref<string | null>(null)
const keyForm = reactive<{ name: string; expires_at: string | null; enabled: boolean }>({ name: '', expires_at: null, enabled: true })
const draft = reactive<{ scope: HttpApiScope; port: number; domain: string }>({ scope: 'local', port: 8760, domain: '' })
const busy = ref<'start' | 'stop' | 'save' | 'test' | 'key-save' | ''>('')
const testResult = ref<HttpApiTestResult | null>(null)
const sampleLanguage = ref<'python' | 'powershell'>('python')
const sampleOptions = [
  { label: 'Python', value: 'python' },
  { label: 'PowerShell', value: 'powershell' },
]
let refreshTimer: number | undefined
let initialized = false

const baseUrl = computed(() => status.base_urls[0] || `http://127.0.0.1:${status.port}`)
const scopeHint = computed(() => {
  locale.value
  return draft.scope === 'local'
    ? translateUiText('只有当前电脑上的程序可以调用。')
    : translateUiText('同一局域网内的设备可以通过本机 IP 调用。')
})

const domainInputStyle = computed(() => {
  const hintLength = 'for example test.juzidc.cn'.length
  const length = Math.max(draft.domain.length, hintLength)
  return { width: `${Math.min(420, Math.max(190, length * 8 + 28))}px`, maxWidth: '100%' }
})

const sampleCopy = computed(() => {
  if (locale.value === 'ja-JP') {
    return {
      upload: '元音声をアップロード',
      create: 'モデルを取得してカバータスクを作成',
      wait: 'タスク完了まで待機',
      download: '完成音声をダウンロード',
      jobFailed: 'タスクに失敗しました',
      powershellUpload: 'PowerShell 7：元音声をアップロード',
    }
  }
  if (locale.value === 'en-US') {
    return {
      upload: 'Upload source audio',
      create: 'Get a model and create a cover job',
      wait: 'Wait for the job to finish',
      download: 'Download the result',
      jobFailed: 'Job failed',
      powershellUpload: 'PowerShell 7: upload source audio',
    }
  }
  return {
    upload: '上传源音频',
    create: '获取模型并创建翻唱任务',
    wait: '等待任务完成',
    download: '下载成品',
    jobFailed: '任务失败',
    powershellUpload: 'PowerShell 7：上传源音频',
  }
})

const pythonSample = computed(() => `import time
from pathlib import Path
import requests

BASE_URL = "${baseUrl.value}"
HEADERS = {"X-API-Key": "${status.api_key || '<API_KEY>'}"}

# 1. ${sampleCopy.value.upload}
with open("song.wav", "rb") as audio:
    upload = requests.post(
        f"{BASE_URL}/api/v1/uploads",
        headers=HEADERS,
        files={"file": ("song.wav", audio, "audio/wav")},
        timeout=None,
    ).json()

# 2. ${sampleCopy.value.create}
models = requests.get(f"{BASE_URL}/api/v1/models", headers=HEADERS).json()
job = requests.post(
    f"{BASE_URL}/api/v1/jobs",
    headers=HEADERS,
    json={
        "source_upload_id": upload["upload_id"],
        "model_id": models["default_id"] or models["items"][0]["id"],
        "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
    },
).json()

# 3. ${sampleCopy.value.wait}
while True:
    current = requests.get(
        f"{BASE_URL}/api/v1/jobs/{job['id']}", headers=HEADERS
    ).json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "${sampleCopy.value.jobFailed}")

# 4. ${sampleCopy.value.download}
result = requests.get(f"{BASE_URL}{current['result_url']}", headers=HEADERS, timeout=None)
result.raise_for_status()
Path("cover.wav").write_bytes(result.content)`)

const powershellSample = computed(() => `$BaseUrl = "${baseUrl.value}"
$Headers = @{ "X-API-Key" = "${status.api_key || '<API_KEY>'}" }

# ${sampleCopy.value.powershellUpload}
$Upload = Invoke-RestMethod -Method Post \`
  -Uri "$BaseUrl/api/v1/uploads" \`
  -Headers $Headers \`
  -Form @{ file = Get-Item ".\\song.wav" }

$Models = Invoke-RestMethod -Uri "$BaseUrl/api/v1/models" -Headers $Headers
$ModelId = if ($Models.default_id) { $Models.default_id } else { $Models.items[0].id }
$Body = @{
  source_upload_id = $Upload.upload_id
  model_id = $ModelId
  params = @{ pitch = 0; f0_method = "rmvpe"; device = "auto" }
} | ConvertTo-Json -Depth 4

$Job = Invoke-RestMethod -Method Post \`
  -Uri "$BaseUrl/api/v1/jobs" -Headers $Headers \`
  -ContentType "application/json" -Body $Body

do {
  Start-Sleep -Seconds 2
  $Current = Invoke-RestMethod -Uri "$BaseUrl/api/v1/jobs/$($Job.id)" -Headers $Headers
} while ($Current.status -notin @("done", "failed"))

if ($Current.status -ne "done") { throw $Current.error }
Invoke-WebRequest -Uri "$BaseUrl$($Current.result_url)" \`
  -Headers $Headers -OutFile ".\\cover.wav"`)

const activeSample = computed(() =>
  sampleLanguage.value === 'python' ? pythonSample.value : powershellSample.value,
)

const endpoints = [
  { method: 'GET', path: '/health', label: '服务健康检查（无需密钥）' },
  { method: 'GET', path: '/api/v1/system', label: '推理环境状态' },
  { method: 'GET', path: '/api/v1/models', label: '模型列表与默认模型' },
  { method: 'POST', path: '/api/v1/uploads', label: '上传源音频或参考音频' },
  { method: 'DELETE', path: '/api/v1/uploads/{upload_id}', label: '删除上传文件' },
  { method: 'POST', path: '/api/v1/jobs', label: '创建翻唱任务' },
  { method: 'GET', path: '/api/v1/jobs/{job_id}', label: '查询任务进度' },
  { method: 'GET', path: '/api/v1/jobs/{job_id}/audio', label: '下载生成音频' },
  { method: 'POST', path: '/api/v1/jobs/{job_id}/retry', label: '重试失败任务' },
]

function maskKey(value: string) {
  if (!value) return ''
  return value.length <= 16 ? '************' : `${value.slice(0, 9)}********${value.slice(-5)}`
}

function formatKeyDate(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function copyApiKey(item: HttpApiKey) {
  await copyText(item.secret, item.name || 'API Key')
}

function toggleKeyVisible(keyId: string) {
  visibleKeys[keyId] = !visibleKeys[keyId]
}

function openKeyDialog(item?: HttpApiKey) {
  editingKeyId.value = item?.id || null
  keyForm.name = item?.name || ''
  keyForm.expires_at = item?.expires_at ? item.expires_at.replace(/Z$/, '').slice(0, 19) : null
  keyForm.enabled = item?.enabled ?? true
  keyDialogVisible.value = true
}

function applyKeyResult(result: HttpApiKeyResult) {
  if (result.items) status.api_keys = result.items
  if (result.key) status.api_key = result.key.secret
}

async function saveKey() {
  busy.value = 'key-save'
  try {
    const payload = { ...keyForm }
    const result = editingKeyId.value
      ? await api.updateHttpApiKey(editingKeyId.value, payload)
      : await api.createHttpApiKey(payload)
    applyKeyResult(result)
    if (!result.ok) {
      ElMessage.error(translateUiText(result.error || 'API 密钥操作失败'))
      return
    }
    keyDialogVisible.value = false
    ElMessage.success(translateUiText(editingKeyId.value ? 'API 密钥已更新' : 'API 密钥已创建'))
  } finally {
    busy.value = ''
  }
}

async function toggleKey(item: HttpApiKey, enabled: boolean) {
  const result = await api.updateHttpApiKey(item.id, { enabled })
  applyKeyResult(result)
  if (!result.ok) ElMessage.error(translateUiText(result.error || 'API 密钥操作失败'))
}

async function removeKey(item: HttpApiKey) {
  if (!window.confirm(translateUiText(`确定删除 API Key「${item.name}」吗？`))) return
  const result = await api.deleteHttpApiKey(item.id)
  applyKeyResult(result)
  result.ok ? ElMessage.success(translateUiText('API 密钥已删除')) : ElMessage.error(translateUiText(result.error || 'API 密钥操作失败'))
}

function applyStatus(next: HttpApiStatus, syncDraft = true) {
  Object.assign(status, next)
  if (syncDraft) {
    draft.scope = next.scope
    draft.port = next.port
    draft.domain = next.domain || ''
  }
}

async function refreshStatus(silent = false) {
  try {
    const next = await api.getHttpApiStatus()
    applyStatus(next, !initialized || next.running)
    initialized = true
  } catch (error) {
    if (!silent) ElMessage.error(translateUiText(error instanceof Error ? error.message : '读取 API 状态失败'))
  }
}

async function saveConfig() {
  busy.value = 'save'
  try {
    const result = await api.configureHttpApi({ ...draft })
    applyStatus(result)
    result.ok ? ElMessage.success(translateUiText('API 配置已保存')) : ElMessage.error(translateUiText(result.error || '保存失败'))
  } finally {
    busy.value = ''
  }
}

async function startServer() {
  busy.value = 'start'
  testResult.value = null
  try {
    const result = await api.startHttpApi({ ...draft })
    applyStatus(result)
    result.ok ? ElMessage.success(translateUiText(result.message || 'API 服务已启动')) : ElMessage.error(translateUiText(result.error || '启动失败'))
  } catch (error) {
    ElMessage.error(translateUiText(error instanceof Error ? error.message : 'API 服务启动失败'))
  } finally {
    busy.value = ''
  }
}

async function stopServer() {
  busy.value = 'stop'
  testResult.value = null
  try {
    const result = await api.stopHttpApi()
    applyStatus(result)
    result.ok ? ElMessage.success(translateUiText('API 服务已停止')) : ElMessage.error(translateUiText(result.error || '停止失败'))
  } finally {
    busy.value = ''
  }
}


async function testServer() {
  busy.value = 'test'
  try {
    testResult.value = await api.testHttpApi()
    testResult.value.ok
      ? ElMessage.success(translateUiText('连通性测试通过'))
      : ElMessage.error(translateUiText(testResult.value.error || '连通性测试失败'))
  } finally {
    busy.value = ''
  }
}

async function openDocs(kind: 'docs' | 'redoc') {
  const opened = await api.openHttpApiDocs(kind)
  if (!opened) ElMessage.error(translateUiText('无法打开接口文档，请确认 API 服务正在运行'))
}

async function copyText(value: string, label: string) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const node = document.createElement('textarea')
    node.value = value
    node.style.position = 'fixed'
    node.style.opacity = '0'
    document.body.appendChild(node)
    node.select()
    document.execCommand('copy')
    node.remove()
  }
  ElMessage.success(translateUiText(`${label}已复制`))
}

onMounted(async () => {
  await refreshStatus()
  refreshTimer = window.setInterval(() => refreshStatus(true), 2500)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.api-page {
  width: min(1280px, calc(100% - 48px));
  margin: 0 auto;
  padding: 38px 0 64px;
  color: var(--xb-text);
}

.page-head,
.section-title,
.head-actions,
.address-block,
.runtime-actions,
.test-result,
.endpoint-row,
.notes-grid > div {
  display: flex;
  align-items: center;
}

.page-head {
  justify-content: space-between;
  gap: 28px;
  margin-bottom: 26px;
}

.eyebrow {
  margin: 0 0 7px;
  color: var(--xb-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

h1 { margin: 0; font-size: 30px; line-height: 1.2; letter-spacing: 0; }
h2 { margin: 0; font-size: 17px; letter-spacing: 0; }
.subtitle, .section-title p { margin: 7px 0 0; color: var(--xb-muted); font-size: 13px; }
.subtitle { color: var(--xb-text); opacity: 0.66; }
.head-actions { gap: 14px; flex-shrink: 0; }

.service-state {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--xb-text);
  opacity: 0.72;
  font-size: 13px;
}
.service-state i { width: 8px; height: 8px; border-radius: 50%; background: var(--xb-muted); }
.service-state.running { color: var(--xb-success); opacity: 1; }
.service-state.running i { background: var(--xb-success); box-shadow: 0 0 10px rgba(25, 245, 154, 0.55); }

.control-band,
.key-band,
.docs-band {
  border: 1px solid var(--xb-border);
  background: var(--xb-panel);
  border-radius: 8px;
  padding: 24px;
  backdrop-filter: blur(18px);
}
.key-band { margin-top: 18px; }
.docs-band { margin-top: 18px; }
.section-title { justify-content: space-between; gap: 20px; margin-bottom: 22px; }

.settings-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(150px, 0.45fr) minmax(220px, 1fr);
  gap: 22px;
}
.field-group { display: flex; flex-direction: column; align-items: stretch; gap: 9px; min-width: 0; }
.field-group > span, .address-label { font-size: 12px; font-weight: 650; color: var(--xb-text); }
.field-group small { min-height: 30px; color: var(--xb-muted); font-size: 11.5px; line-height: 1.45; }
.field-group code { color: var(--xb-primary); }
.port-field :deep(.el-input-number) { width: 100%; }
.domain-field :deep(.el-input) { min-width: 190px; max-width: 100%; }
.key-card-head, .key-secret-row, .key-card-actions { display: flex; align-items: center; }
.key-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.key-card { min-width: 0; padding: 14px; border: 1px solid var(--xb-border); border-radius: 7px; background: rgba(var(--xb-fill-rgb), 0.035); }
.key-card-head { justify-content: space-between; gap: 10px; }
.key-card-head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.key-secret-row { gap: 3px; margin-top: 12px; padding: 7px 8px; border: 1px solid var(--xb-border); border-radius: 5px; background: rgba(4, 6, 12, 0.45); }
.key-secret-row code { flex: 1; min-width: 0; overflow: hidden; color: var(--xb-primary); cursor: pointer; text-overflow: ellipsis; white-space: nowrap; }
.key-secret-row .el-button { width: 30px; padding: 0; }
.key-card-info { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; color: var(--xb-muted); font-size: 11px; }
.key-card-actions { justify-content: flex-end; flex-wrap: wrap; gap: 2px; margin-top: 10px; }
.key-card-actions .el-switch { margin-right: auto; }

.address-block {
  gap: 14px;
  min-height: 48px;
  margin-top: 19px;
  padding-top: 19px;
  border-top: 1px solid var(--xb-border);
}
.address-label { flex-shrink: 0; }
.address-list { display: flex; flex: 1; flex-wrap: wrap; gap: 8px; min-width: 0; }
.address-row {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  max-width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 5px;
  color: var(--xb-text);
  background: rgba(var(--xb-fill-rgb), 0.04);
  cursor: pointer;
}
.address-row:hover { border-color: var(--xb-primary); color: var(--xb-primary); }
.address-row code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-actions { gap: 8px; flex-shrink: 0; }

.test-result {
  gap: 9px;
  margin-top: 16px;
  padding: 11px 13px;
  border: 1px solid rgba(var(--xb-accent-rgb), 0.35);
  border-radius: 5px;
  color: var(--xb-accent);
  background: rgba(var(--xb-accent-rgb), 0.07);
  font-size: 12.5px;
}
.test-result.ok { border-color: rgba(25, 245, 154, 0.3); color: var(--xb-success); background: rgba(25, 245, 154, 0.06); }
.test-result code { margin-left: auto; color: inherit; }
.last-error { margin: 14px 0 0; color: var(--xb-accent); font-size: 12px; }

.docs-layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(340px, 0.75fr); gap: 18px; }
.code-panel, .endpoint-panel { min-width: 0; overflow: hidden; border: 1px solid var(--xb-border); border-radius: 6px; background: rgba(4, 6, 12, 0.74); }
.code-head, .endpoint-head { display: flex; align-items: center; justify-content: space-between; height: 42px; padding: 0 13px; border-bottom: 1px solid var(--xb-border); color: var(--xb-muted); font-size: 12px; }
.code-head button { display: grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: 4px; color: var(--xb-muted); background: transparent; cursor: pointer; }
.code-head button:hover { color: var(--xb-primary); background: rgba(var(--xb-fill-rgb), 0.08); }
pre { height: 446px; margin: 0; padding: 16px; overflow: auto; color: #d8e4f2; font-size: 12px; line-height: 1.62; tab-size: 2; }
pre code { font-family: Consolas, 'Courier New', monospace; }
.endpoint-head small { font-size: 10.5px; }
.endpoint-list { padding: 7px; }
.endpoint-row { display: grid; grid-template-columns: 52px minmax(170px, 1fr) minmax(110px, 0.7fr); gap: 9px; min-height: 46px; padding: 7px 8px; border-bottom: 1px solid var(--xb-border); font-size: 11.5px; }
.endpoint-row:last-child { border-bottom: 0; }
.endpoint-row > span:last-child { color: var(--xb-muted); }
.endpoint-row code { overflow: hidden; color: var(--xb-text); text-overflow: ellipsis; white-space: nowrap; }
.method { width: 44px; padding: 4px 0; border-radius: 3px; text-align: center; font-size: 10px; font-weight: 800; }
.method.get { color: #55d7ff; background: rgba(85, 215, 255, 0.11); }
.method.post { color: #34e29a; background: rgba(52, 226, 154, 0.11); }
.method.delete { color: #ff6b8e; background: rgba(255, 107, 142, 0.11); }

.notes-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 18px; }
.notes-grid > div { display: grid; grid-template-columns: 22px 1fr; align-items: start; column-gap: 10px; padding: 14px; border-left: 2px solid var(--xb-border); background: rgba(var(--xb-fill-rgb), 0.035); }
.notes-grid .el-icon { grid-row: 1 / 3; margin-top: 1px; color: var(--xb-primary); font-size: 17px; }
.notes-grid span { font-size: 12.5px; font-weight: 650; }
.notes-grid p { margin: 5px 0 0; color: var(--xb-muted); font-size: 11.5px; line-height: 1.55; }

@media (max-width: 1100px) {
  .settings-grid { grid-template-columns: 1fr 1fr; }
  .address-block { align-items: flex-start; flex-wrap: wrap; }
  .runtime-actions { width: 100%; padding-left: 70px; }
  .docs-layout { grid-template-columns: 1fr; }
  pre { height: 380px; }
}

@media (max-width: 720px) {
  .api-page { width: calc(100% - 28px); padding-top: 24px; }
  .page-head { width: 100%; align-items: flex-start; flex-direction: column; }
  .page-head > div:first-child { width: 100%; min-width: 0; }
  .head-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; width: 100%; max-width: 100%; }
  .head-actions > .el-button { margin-left: 0; }
  .service-state { min-width: 0; white-space: nowrap; }
  .control-band, .key-band, .docs-band { padding: 18px 14px; }
  .section-title { align-items: flex-start; flex-direction: column; }
  .settings-grid { grid-template-columns: 1fr; }
  .domain-field :deep(.el-input) { width: 100% !important; min-width: 0; }
  .key-list { grid-template-columns: 1fr; }
  .key-card-actions { justify-content: flex-start; }
  .key-card-actions .el-switch { width: 100%; margin-right: 0; margin-bottom: 2px; }
  .address-block { flex-direction: column; }
  .runtime-actions { width: 100%; padding-left: 0; flex-wrap: wrap; }
  .runtime-actions .el-button { margin-left: 0; }
  .notes-grid { grid-template-columns: 1fr; }
  .endpoint-row { grid-template-columns: 50px minmax(0, 1fr); }
  .endpoint-row > span:last-child { grid-column: 2; }
}
</style>
