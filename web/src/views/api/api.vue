<template>
  <div class="api-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">DEVELOPER ACCESS</p>
        <h1>API 接入</h1>
        <p class="subtitle">FastAPI 服务默认关闭，只在本次软件运行期间由你手动启用。</p>
      </div>
      <div class="head-actions">
        <span class="service-state" :class="{ running: status.running }">
          <i></i>{{ status.running ? '服务运行中' : '服务已停止' }}
        </span>
        <el-button
          v-if="!status.running"
          type="primary"
          :loading="busy === 'start'"
          @click="startServer"
        >
          <el-icon><VideoPlay /></el-icon>
          启动服务
        </el-button>
        <el-button
          v-else
          type="danger"
          plain
          :loading="busy === 'stop'"
          @click="stopServer"
        >
          <el-icon><SwitchButton /></el-icon>
          停止服务
        </el-button>
      </div>
    </header>

    <section class="control-band">
      <div class="section-title">
        <div>
          <h2>服务配置</h2>
          <p>修改监听范围或端口前需要先停止服务。</p>
        </div>
        <el-button :disabled="status.running" :loading="busy === 'save'" @click="saveConfig">
          <el-icon><DocumentChecked /></el-icon>
          保存配置
        </el-button>
      </div>

      <div class="settings-grid">
        <label class="field-group">
          <span>监听范围</span>
          <el-radio-group v-model="draft.scope" :disabled="status.running">
            <el-radio-button value="local">仅本机</el-radio-button>
            <el-radio-button value="lan">局域网</el-radio-button>
          </el-radio-group>
          <small>{{ scopeHint }}</small>
        </label>

        <label class="field-group port-field">
          <span>监听端口</span>
          <el-input-number
            v-model="draft.port"
            :min="1024"
            :max="65535"
            controls-position="right"
            :disabled="status.running"
          />
          <small>防火墙或其他程序占用端口时，请更换端口。</small>
        </label>

        <div class="field-group key-field">
          <span>API Key</span>
          <div class="input-actions">
            <el-input v-model="status.api_key" readonly show-password />
            <el-button title="复制 API Key" @click="copyText(status.api_key, 'API Key')">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
            <el-button
              title="重新生成 API Key"
              :disabled="status.running"
              :loading="busy === 'key'"
              @click="regenerateKey"
            >
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <small>调用受保护接口时通过 <code>X-API-Key</code> 请求头发送。</small>
        </div>
      </div>

      <div class="address-block">
        <span class="address-label">访问地址</span>
        <div class="address-list">
          <button
            v-for="url in status.base_urls"
            :key="url"
            class="address-row"
            title="复制地址"
            @click="copyText(url, '访问地址')"
          >
            <code>{{ url }}</code>
            <el-icon><CopyDocument /></el-icon>
          </button>
        </div>
        <div class="runtime-actions">
          <el-button :disabled="!status.running" :loading="busy === 'test'" @click="testServer">
            <el-icon><Connection /></el-icon>
            连通性测试
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
      <p v-if="status.last_error && !status.running" class="last-error">{{ status.last_error }}</p>
    </section>

    <section class="docs-band">
      <div class="section-title">
        <div>
          <h2>调用文档</h2>
          <p>典型流程：上传音频、读取模型、创建任务、轮询状态、下载成品。</p>
        </div>
        <el-segmented v-model="sampleLanguage" :options="sampleOptions" />
      </div>

      <div class="docs-layout">
        <div class="code-panel">
          <div class="code-head">
            <span>{{ sampleLanguage === 'python' ? 'Python · requests' : 'PowerShell · Invoke-RestMethod' }}</span>
            <button title="复制示例" @click="copyText(activeSample, '调用示例')">
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
          <pre><code>{{ activeSample }}</code></pre>
        </div>

        <div class="endpoint-panel">
          <div class="endpoint-head">
            <span>v1 接口</span>
            <small>所有受保护接口均需 X-API-Key</small>
          </div>
          <div class="endpoint-list">
            <div v-for="item in endpoints" :key="item.method + item.path" class="endpoint-row">
              <span class="method" :class="item.method.toLowerCase()">{{ item.method }}</span>
              <code>{{ item.path }}</code>
              <span>{{ item.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="notes-grid">
        <div>
          <el-icon><UploadFilled /></el-icon>
          <span>上传限制</span>
          <p>不设置文件大小上限，按流式写入磁盘；支持 WAV、FLAC、MP3、M4A、AAC、OGG、Opus 及常见视频容器。</p>
        </div>
        <div>
          <el-icon><Lock /></el-icon>
          <span>外部访问</span>
          <p>局域网模式监听所有网卡。仅在可信网络使用，并在调用方妥善保存 API Key。</p>
        </div>
        <div>
          <el-icon><Timer /></el-icon>
          <span>异步任务</span>
          <p>创建接口返回 202；轮询任务到 done 后，再通过 result_url 下载音频。</p>
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
  CopyDocument,
  DocumentChecked,
  Lock,
  Notebook,
  Reading,
  Refresh,
  SwitchButton,
  Timer,
  UploadFilled,
  VideoPlay,
  WarningFilled,
} from '@element-plus/icons-vue'
import { api, type HttpApiScope, type HttpApiStatus, type HttpApiTestResult } from '@/api'

defineOptions({ name: 'ApiAccess' })

const emptyStatus: HttpApiStatus = {
  running: false,
  scope: 'local',
  host: '127.0.0.1',
  port: 8765,
  api_key: '',
  base_urls: ['http://127.0.0.1:8765'],
  docs_url: 'http://127.0.0.1:8765/docs',
  redoc_url: 'http://127.0.0.1:8765/redoc',
}

const status = reactive<HttpApiStatus>({ ...emptyStatus })
const draft = reactive<{ scope: HttpApiScope; port: number }>({ scope: 'local', port: 8765 })
const busy = ref<'start' | 'stop' | 'save' | 'test' | 'key' | ''>('')
const testResult = ref<HttpApiTestResult | null>(null)
const sampleLanguage = ref<'python' | 'powershell'>('python')
const sampleOptions = [
  { label: 'Python', value: 'python' },
  { label: 'PowerShell', value: 'powershell' },
]
let refreshTimer: number | undefined
let initialized = false

const baseUrl = computed(() => status.base_urls[0] || `http://127.0.0.1:${status.port}`)
const scopeHint = computed(() =>
  draft.scope === 'local'
    ? '只有当前电脑上的程序可以调用。'
    : '同一局域网内的设备可以通过本机 IP 调用。',
)

const pythonSample = computed(() => `import time
from pathlib import Path
import requests

BASE_URL = "${baseUrl.value}"
HEADERS = {"X-API-Key": "${status.api_key || '<API_KEY>'}"}

# 1. 上传源音频
with open("song.wav", "rb") as audio:
    upload = requests.post(
        f"{BASE_URL}/api/v1/uploads",
        headers=HEADERS,
        files={"file": ("song.wav", audio, "audio/wav")},
        timeout=None,
    ).json()

# 2. 获取模型并创建翻唱任务
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

# 3. 等待任务完成
while True:
    current = requests.get(
        f"{BASE_URL}/api/v1/jobs/{job['id']}", headers=HEADERS
    ).json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "任务失败")

# 4. 下载成品
result = requests.get(f"{BASE_URL}{current['result_url']}", headers=HEADERS, timeout=None)
result.raise_for_status()
Path("cover.wav").write_bytes(result.content)`)

const powershellSample = computed(() => `$BaseUrl = "${baseUrl.value}"
$Headers = @{ "X-API-Key" = "${status.api_key || '<API_KEY>'}" }

# PowerShell 7：上传源音频
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

function applyStatus(next: HttpApiStatus, syncDraft = true) {
  Object.assign(status, next)
  if (syncDraft) {
    draft.scope = next.scope
    draft.port = next.port
  }
}

async function refreshStatus(silent = false) {
  try {
    const next = await api.getHttpApiStatus()
    applyStatus(next, !initialized || next.running)
    initialized = true
  } catch (error) {
    if (!silent) ElMessage.error(error instanceof Error ? error.message : '读取 API 状态失败')
  }
}

async function saveConfig() {
  busy.value = 'save'
  try {
    const result = await api.configureHttpApi({ ...draft })
    applyStatus(result)
    result.ok ? ElMessage.success('API 配置已保存') : ElMessage.error(result.error || '保存失败')
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
    result.ok ? ElMessage.success(result.message || 'API 服务已启动') : ElMessage.error(result.error || '启动失败')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'API 服务启动失败')
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
    result.ok ? ElMessage.success('API 服务已停止') : ElMessage.error(result.error || '停止失败')
  } finally {
    busy.value = ''
  }
}

async function regenerateKey() {
  busy.value = 'key'
  try {
    const result = await api.regenerateHttpApiKey()
    applyStatus(result)
    result.ok ? ElMessage.success('已生成新的 API Key') : ElMessage.error(result.error || '更新失败')
  } finally {
    busy.value = ''
  }
}

async function testServer() {
  busy.value = 'test'
  try {
    testResult.value = await api.testHttpApi()
    testResult.value.ok
      ? ElMessage.success('连通性测试通过')
      : ElMessage.error(testResult.value.error || '连通性测试失败')
  } finally {
    busy.value = ''
  }
}

async function openDocs(kind: 'docs' | 'redoc') {
  const opened = await api.openHttpApiDocs(kind)
  if (!opened) ElMessage.error('无法打开接口文档，请确认 API 服务正在运行')
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
  ElMessage.success(`${label}已复制`)
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
.input-actions,
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
.docs-band {
  border: 1px solid var(--xb-border);
  background: var(--xb-panel);
  border-radius: 8px;
  padding: 24px;
  backdrop-filter: blur(18px);
}
.docs-band { margin-top: 18px; }
.section-title { justify-content: space-between; gap: 20px; margin-bottom: 22px; }

.settings-grid {
  display: grid;
  grid-template-columns: minmax(240px, 0.8fr) minmax(180px, 0.55fr) minmax(340px, 1.5fr);
  gap: 22px;
}
.field-group { display: flex; flex-direction: column; align-items: stretch; gap: 9px; min-width: 0; }
.field-group > span, .address-label { font-size: 12px; font-weight: 650; color: var(--xb-text); }
.field-group small { min-height: 30px; color: var(--xb-muted); font-size: 11.5px; line-height: 1.45; }
.field-group code { color: var(--xb-primary); }
.port-field :deep(.el-input-number) { width: 100%; }
.input-actions { gap: 8px; min-width: 0; }
.input-actions :deep(.el-input) { flex: 1; width: 0; min-width: 0; }
.input-actions .el-button { width: 36px; padding: 0; flex-shrink: 0; }

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
  .key-field { grid-column: 1 / -1; }
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
  .control-band, .docs-band { padding: 18px 14px; }
  .section-title { align-items: flex-start; flex-direction: column; }
  .settings-grid { grid-template-columns: 1fr; }
  .key-field { grid-column: auto; }
  .input-actions { display: grid; grid-template-columns: minmax(0, 1fr) 36px 36px; width: 100%; }
  .input-actions :deep(.el-input) { width: 100%; }
  .address-block { flex-direction: column; }
  .runtime-actions { width: 100%; padding-left: 0; flex-wrap: wrap; }
  .runtime-actions .el-button { margin-left: 0; }
  .notes-grid { grid-template-columns: 1fr; }
  .endpoint-row { grid-template-columns: 50px minmax(0, 1fr); }
  .endpoint-row > span:last-child { grid-column: 2; }
}
</style>
