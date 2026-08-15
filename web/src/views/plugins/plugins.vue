<template>
  <div class="page">
    <div class="page-head">
      <div class="heading-wrap">
        <div class="heading-icon"><el-icon><Grid /></el-icon></div>
        <div><p class="eyebrow">// EXTENSIONS / WORKSPACE</p><h1>插件中心</h1><p class="page-sub">扩展翻唱流程，安装用户页面，把工作台变成你的工作台</p></div>
      </div>
      <div class="master-control" :class="{ active: enabled }"><el-tag :type="enabled ? 'success' : 'warning'" effect="light">{{ enabled ? '插件运行中' : '插件已暂停' }}</el-tag><el-switch v-model="enabled" :loading="saving" inline-prompt active-text="开" inactive-text="关" @change="saveEnabled" /></div>
    </div>

    <div class="status-banner" :class="{ active: enabled }"><div class="status-mark"><el-icon><CircleCheck /></el-icon></div><div class="status-copy"><strong>{{ enabled ? '扩展能力已接入当前工作流' : '扩展能力当前处于暂停状态' }}</strong><span>{{ enabled ? '已授权的插件页面和翻唱钩子可以正常使用。' : '开启后仍需单独启用每个插件，现有翻唱流程不会受到影响。' }}</span></div><span class="status-count">{{ plugins.length }} 个已安装</span></div>

    <section class="settings glass">
      <div class="section-head">
        <div class="section-title"><span class="section-kicker">01</span><div><h2>插件功能</h2><p>控制扩展运行环境与市场来源</p></div></div>
      </div>
      <p class="security">{{ status.security }}</p>
      <div class="market-row">
        <label for="market-url">插件市场索引</label>
        <el-input id="market-url" v-model="marketUrl" placeholder="https://raw.githubusercontent.com/<owner>/<repo>/<branch>/assets/plugins.json5" @change="saveMarket" />
        <el-button :loading="marketLoading" @click="loadMarket">刷新市场</el-button>
      </div>
      <div class="local-row">
        <el-button class="install-btn" :loading="localInstalling" @click="installLocal"><el-icon><Upload /></el-icon>安装本地插件包</el-button><input ref="pluginFileInput" class="plugin-file-input" type="file" accept=".xbplugin,.zip,application/zip" @change="installSelectedLocal">
        <span class="dev-path"><span>开发目录</span><code>{{ status.development_dir || '加载中…' }}</code></span>
      </div>
    </section>

    <section v-if="market.length" class="section">
      <div class="section-head"><div class="section-title"><span class="section-kicker">02</span><div><h2>插件市场</h2><p>兼容 NoneBot2 风格 plugins.json5 索引</p></div></div><span class="section-note">NONEBOT2 / GITHUB JSON5</span></div>
      <div class="plugin-grid">
        <article v-for="item in market" :key="item.id" class="plugin-card glass">
          <div class="plugin-title"><div class="plugin-identity"><div class="plugin-avatar market"><el-icon><Grid /></el-icon></div><div><h3>{{ item.name }}</h3><span>{{ marketSubtitle(item) }}</span></div></div><span class="tag">{{ item.is_official ? '官方' : '市场' }}</span></div>
          <p>{{ item.description || '暂无说明' }}</p>
          <div v-if="item.tags?.length" class="market-tags"><el-tag v-for="tag in item.tags" :key="tag.label" size="small" effect="plain">{{ tag.label }}</el-tag></div>
          <footer><span class="author">{{ item.author || item.project_link || '未知作者' }}</span><el-button size="small" :disabled="!item.bundle_url" :loading="installingMarketUrl === item.bundle_url" @click="installMarket(item.bundle_url || '')">{{ item.bundle_url ? '安装' : '仅索引' }} <el-icon><ArrowRight /></el-icon></el-button></footer>
        </article>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><div class="section-title"><span class="section-kicker">03</span><div><h2>已安装插件</h2><p>每个插件都需要单独授权后才能运行</p></div></div><span class="section-note">LOCAL RUNTIME</span></div>
      <div v-if="plugins.length" class="plugin-grid">
        <article v-for="plugin in plugins" :key="plugin.id" class="plugin-card glass">
          <div class="plugin-title"><div class="plugin-identity"><div class="plugin-avatar" :class="plugin.runtime"><el-icon><component :is="plugin.runtime === 'frontend' ? Grid : Cpu" /></el-icon></div><div><h3>{{ plugin.name }}</h3><span>{{ plugin.id }} · v{{ plugin.version }}</span></div></div><el-switch :model-value="plugin.enabled" inline-prompt active-text="开" inactive-text="关" @change="togglePlugin(plugin, $event)" /></div>
          <div class="runtime-row"><span class="runtime-tag" :class="plugin.runtime">{{ runtimeLabel(plugin.runtime) }}</span><span v-if="plugin.permissions.length" class="permission-text">{{ permissionSummary(plugin.permissions) }}</span></div>
          <p>{{ plugin.description || '暂无说明' }}</p>
          <footer>
            <span class="author">{{ plugin.author || '未知作者' }}</span>
            <span class="card-actions"><el-button v-if="plugin.pages.length || plugin.frontend?.entry" size="small" :disabled="!enabled || !plugin.enabled" @click="openPlugin(plugin)">打开</el-button><el-button size="small" type="danger" plain @click="removePlugin(plugin.id)">卸载</el-button></span>
          </footer>
        </article>
      </div>
      <div v-else class="empty glass">尚未安装插件。可从 GitHub 市场安装，或选择本地 <code>.xbplugin</code> 包。</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/es/components/message-box/style/css'
import { ElMessageBox, ElNotification } from 'element-plus'
import { ArrowRight, CircleCheck, Cpu, Grid, Upload } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { api, type PluginInfo, type PluginInstallResult, type PluginMarketItem, type PluginStatus } from '@/api'

defineOptions({ name: 'PluginsPage' })
const router = useRouter()
const status = ref<PluginStatus>({ enabled: false, market_url: '', development_dir: '', security: '' })
const enabled = ref(false)
const marketUrl = ref('')
const plugins = ref<PluginInfo[]>([])
const market = ref<PluginMarketItem[]>([])
const saving = ref(false)
const marketLoading = ref(false)
const localInstalling = ref(false)
const installingMarketUrl = ref('')
const pluginFileInput = ref<HTMLInputElement | null>(null)

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : String(error || fallback)
}

function notify(type: 'success' | 'warning' | 'info' | 'error', message: string) {
  const titles = { success: '操作完成', warning: '需要注意', info: '提示', error: '操作失败' }
  ElNotification({
    type,
    title: titles[type],
    message,
    position: 'top-right',
    customClass: 'xb-notification-center',
    duration: type === 'error' ? 4200 : 2600,
    showClose: true,
  })
}
const notifySuccess = (message: string) => notify('success', message)
const notifyInfo = (message: string) => notify('info', message)
const notifyError = (message: string) => notify('error', message)

function installSuccessMessage(result: PluginInstallResult) {
  return result.plugin?.path ? '插件已安装到：' + result.plugin.path : (result.message || '插件已安装')
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error || new Error('无法读取插件包'))
    reader.onload = () => {
      const value = String(reader.result || '')
      resolve(value.includes(',') ? (value.split(',', 2)[1] || '') : value)
    }
    reader.readAsDataURL(file)
  })
}

async function load() {
  try {
    status.value = await api.getPluginStatus()
    enabled.value = status.value.enabled
    marketUrl.value = status.value.market_url
    plugins.value = await api.listPlugins()
  } catch (error) {
    notifyError(errorMessage(error, '加载插件中心失败'))
  }
}
async function saveEnabled() {
  const previous = status.value.enabled
  saving.value = true
  try {
    const next = await api.configurePlugins({ enabled: enabled.value })
    if (next.ok === false) {
      enabled.value = previous
      notifyError(next.error || '保存失败')
      return
    }
    status.value = next
  } catch (error) {
    enabled.value = previous
    notifyError(errorMessage(error, '保存插件设置失败'))
  } finally {
    saving.value = false
  }
}
async function saveMarket(): Promise<boolean> {
  try {
    const next = await api.configurePlugins({ market_url: marketUrl.value.trim() })
    if (next.ok === false) {
      notifyError(next.error || '市场地址无效')
      return false
    }
    status.value = next
    return true
  } catch (error) {
    notifyError(errorMessage(error, '保存市场地址失败'))
    return false
  }
}
async function loadMarket() {
  if (!(await saveMarket())) return
  marketLoading.value = true
  try {
    const result = await api.fetchPluginMarket()
    if (!result.ok) {
      notifyError(result.error || '市场加载失败')
      return
    }
    market.value = result.items
    if (!market.value.length) notifyInfo('市场中没有可安装的插件')
  } catch (error) {
    notifyError(errorMessage(error, '市场加载失败'))
  } finally {
    marketLoading.value = false
  }
}
function installLocal() {
  if (localInstalling.value) return
  const input = pluginFileInput.value
  if (!input) {
    notifyError('插件包选择器未就绪')
    return
  }
  input.value = ''
  input.click()
}

async function installSelectedLocal(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 20 * 1024 * 1024) {
    notifyError('插件包超过 20 MB 限制')
    return
  }
  localInstalling.value = true
  try {
    const data = await readFileAsBase64(file)
    const result = await api.installPluginBundleData(file.name, data)
    if (!result.ok) {
      notifyError(result.error || '安装失败')
      return
    }
    notifySuccess(installSuccessMessage(result))
    await load()
  } catch (error) {
    notifyError(errorMessage(error, '安装本地插件包失败'))
  } finally {
    localInstalling.value = false
  }
}
function marketSubtitle(item: PluginMarketItem) {
  const parts = [item.module_name || item.id]
  if (item.project_link) parts.push(item.project_link)
  if (item.version) parts.push('v' + item.version)
  return parts.join(' · ')
}

async function installMarket(url: string) {
  if (!url) {
    notifyInfo('该市场条目没有提供可安装的插件包')
    return
  }
  if (installingMarketUrl.value) return
  installingMarketUrl.value = url
  try {
    const result = await api.installPluginFromMarket(url)
    if (!result.ok) {
      notifyError(result.error || '安装失败')
      return
    }
    notifySuccess(installSuccessMessage(result))
    await load()
  } catch (error) {
    notifyError(errorMessage(error, '安装市场插件失败'))
  } finally {
    installingMarketUrl.value = ''
  }
}
async function togglePlugin(plugin: PluginInfo, value: string | number | boolean) {
  const next = Boolean(value)
  if (next && plugin.runtime !== 'frontend') {
    try {
      await ElMessageBox.confirm(
        '此插件包含 Python 代码，将以当前用户权限运行，可能访问文件、网络或启动进程。请仅启用你信任且已检查来源的插件。',
        '启用 Python 插件',
        { type: 'warning', confirmButtonText: '我信任并启用', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  try {
    if (await api.setPluginEnabled(plugin.id, next)) plugin.enabled = next
    else notifyError(next ? '插件入口加载失败，未启用。请检查 Python 版本和插件日志。' : '更新插件状态失败')
  } catch (error) {
    notifyError(errorMessage(error, next ? '启用插件失败' : '禁用插件失败'))
  }
}
function runtimeLabel(runtime: PluginInfo['runtime']) {
  return ({ frontend: '纯前端', python: '纯 Python', hybrid: '前端 + Python' })[runtime]
}
function permissionSummary(permissions: string[]) {
  return permissions.includes('python.execute') ? '包含可执行代码' : `${permissions.length} 项权限`
}
function openPlugin(plugin: PluginInfo) {
  const page = plugin.pages[0]
  if (page) router.push(`/plugins/${plugin.id}/${page.id}`)
  else if (plugin.frontend?.entry) router.push(`/plugins/${plugin.id}/app`)
}
async function removePlugin(id: string) {
  try {
    await ElMessageBox.confirm('卸载会删除此插件的本地文件，是否继续？', '卸载插件', { type: 'warning' })
  } catch { return }
  try {
    if (await api.uninstallPlugin(id)) {
      notifySuccess('插件已卸载')
      await load()
    } else {
      notifyError('卸载插件失败')
    }
  } catch (error) {
    notifyError(errorMessage(error, '卸载插件失败'))
  }
}
onMounted(load)
</script>

<style scoped>
.page { max-width: 1240px; margin: 0 auto; padding: 34px 28px 70px; }
.page-head, .section-head, .market-row, .local-row, .plugin-title, footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.page-head { margin-bottom: 18px; }.heading-wrap { display: flex; align-items: center; gap: 15px; }.heading-icon { width: 48px; height: 48px; display: grid; place-items: center; color: var(--xb-on-primary); font-size: 23px; border-radius: 12px; background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)); box-shadow: 0 0 24px rgba(var(--xb-primary-rgb), .25); }.eyebrow { color: var(--xb-primary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0 0 7px; font-size: 11px; letter-spacing: .08em; }.page-head h1, h2, h3, p { margin-top: 0; }.page-head h1 { margin-bottom: 6px; font-size: 30px; letter-spacing: .01em; }.page-sub, .section-head p, .plugin-card p { color: var(--xb-muted); margin-bottom: 0; }.master-control { display: flex; align-items: center; gap: 13px; padding: 10px 13px 10px 15px; border: 1px solid var(--xb-border); border-radius: 10px; background: rgba(var(--xb-fill-rgb), .035); }.master-control.active { border-color: rgba(var(--xb-success-rgb), .4); background: rgba(var(--xb-success-rgb), .07); }.master-state { display: inline-flex; align-items: center; gap: 8px; color: var(--xb-muted); font-size: 12px; white-space: nowrap; }.master-control.active .master-state { color: var(--xb-success); }.master-state i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 10px currentColor; }
.status-banner { display: flex; align-items: center; gap: 13px; min-height: 62px; margin-bottom: 25px; padding: 13px 16px; border: 1px solid rgba(var(--xb-warn-rgb), .28); border-left: 3px solid var(--xb-warn); border-radius: 8px; background: rgba(var(--xb-warn-rgb), .065); }.status-banner.active { border-color: rgba(var(--xb-success-rgb), .3); border-left-color: var(--xb-success); background: rgba(var(--xb-success-rgb), .065); }.status-mark { width: 32px; height: 32px; display: grid; place-items: center; flex-shrink: 0; color: var(--xb-warn); font-size: 19px; }.status-banner.active .status-mark { color: var(--xb-success); }.status-copy { display: grid; gap: 4px; flex: 1; }.status-copy strong { color: var(--xb-text); font-size: 13px; }.status-copy span { color: var(--xb-muted); font-size: 12px; }.status-count, .section-note { color: var(--xb-muted); font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .06em; white-space: nowrap; }
.glass { background: var(--xb-panel); border: 1px solid var(--xb-border); border-radius: 8px; backdrop-filter: blur(15px); }.settings { padding: 22px; }.section { margin-top: 30px; }.section-head { margin-bottom: 15px; }.section-title { display: flex; align-items: center; gap: 11px; }.section-kicker { color: var(--xb-primary); font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }.section-head h2 { margin-bottom: 5px; font-size: 18px; }.security { color: var(--xb-muted); font-size: 12px; line-height: 1.5; margin: 18px 0 0; padding: 11px 13px; background: rgba(var(--xb-success-rgb), .07); border-left: 3px solid var(--xb-success); }.market-row { margin-top: 18px; }.market-row label { min-width: 108px; color: var(--xb-text); font-size: 12px; font-weight: 650; }.market-row :deep(.el-input) { flex: 1; }.market-row :deep(.el-input__wrapper) { min-height: 40px; background: rgba(var(--xb-fill-rgb), .045); box-shadow: 0 0 0 1px var(--xb-border) inset; }.local-row { justify-content: flex-start; margin-top: 15px; color: var(--xb-muted); font-size: 12px; }.plugin-file-input { display: none; }.install-btn { background: rgba(var(--xb-primary-rgb), .1) !important; border-color: rgba(var(--xb-primary-rgb), .35) !important; color: var(--xb-primary) !important; }.dev-path { display: inline-flex; align-items: center; gap: 9px; min-width: 0; }.dev-path > span { color: var(--xb-muted); }.dev-path code { max-width: 560px; overflow: hidden; color: var(--xb-primary); text-overflow: ellipsis; white-space: nowrap; }code { color: var(--xb-primary); overflow-wrap: anywhere; }.plugin-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; }.plugin-card { position: relative; min-height: 188px; padding: 19px; display: flex; flex-direction: column; gap: 15px; overflow: hidden; transition: border-color .2s ease, transform .2s ease, box-shadow .2s ease; }.plugin-card::before { content: ''; position: absolute; inset: 0 0 auto; height: 2px; background: linear-gradient(90deg, var(--xb-primary), transparent 70%); opacity: .65; }.plugin-card:hover { border-color: rgba(var(--xb-primary-rgb), .48); transform: translateY(-2px); box-shadow: 0 10px 26px rgba(0, 0, 0, .14); }.plugin-title h3 { margin-bottom: 4px; font-size: 16px; }.plugin-title span, footer { color: var(--xb-muted); font-size: 11px; }.plugin-identity { display: flex; align-items: center; gap: 11px; min-width: 0; }.plugin-avatar { width: 37px; height: 37px; display: grid; place-items: center; flex-shrink: 0; border: 1px solid rgba(var(--xb-primary-rgb), .3); border-radius: 9px; color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .1); font-size: 18px; }.plugin-avatar.market { color: var(--xb-accent); border-color: rgba(var(--xb-accent-rgb), .3); background: rgba(var(--xb-accent-rgb), .1); }.tag { padding: 4px 7px; color: var(--xb-primary) !important; border: 1px solid rgba(var(--xb-primary-rgb), .25); border-radius: 5px; background: rgba(var(--xb-primary-rgb), .08); font-size: 10px !important; }.plugin-card p { font-size: 13px; line-height: 1.6; flex: 1; }.plugin-card footer { padding-top: 12px; border-top: 1px solid rgba(var(--xb-fill-rgb), .08); }.author { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.card-actions { display: flex; gap: 8px; }.card-actions :deep(.el-button), .plugin-card footer :deep(.el-button) { display: inline-flex; align-items: center; gap: 5px; }.empty { padding: 42px 24px; color: var(--xb-muted); text-align: center; }
.market-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: -4px; }
.runtime-row { display: flex; align-items: center; gap: 8px; margin-top: -5px; }.runtime-tag { padding: 3px 7px; border: 1px solid var(--xb-border); border-radius: 5px; color: var(--xb-muted); background: rgba(var(--xb-fill-rgb), .045); font-size: 10px; }.runtime-tag.python, .runtime-tag.hybrid { color: var(--xb-warn); border-color: rgba(var(--xb-warn-rgb), .32); background: rgba(var(--xb-warn-rgb), .08); }.plugin-avatar.python, .plugin-avatar.hybrid { color: var(--xb-warn); border-color: rgba(var(--xb-warn-rgb), .3); background: rgba(var(--xb-warn-rgb), .1); }.permission-text { color: var(--xb-muted); font-size: 10px; }
@media (max-width: 720px) { .page { padding: 24px 15px 52px; }.page-head, .market-row { align-items: stretch; flex-direction: column; }.master-control { justify-content: space-between; }.status-banner { align-items: flex-start; }.status-count { display: none; }.local-row { align-items: flex-start; flex-direction: column; }.dev-path { width: 100%; align-items: flex-start; flex-direction: column; gap: 4px; }.dev-path code { max-width: 100%; }.section-note { display: none; } }
</style>
