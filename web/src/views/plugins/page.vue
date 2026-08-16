<template>
  <div class="page">
    <div class="page-head">
      <div>
        <p class="eyebrow">// PLUGIN PAGE</p>
        <h1>{{ pageTitle }}</h1>
        <p class="page-sub">{{ pageDescription }}</p>
      </div>
      <el-button class="back-btn" type="primary" plain @click="router.push('/plugins')"><el-icon><ArrowLeft /></el-icon><span>返回插件中心</span></el-button>
    </div>

    <section v-if="plugin && plugin.enabled && enabled && hasFrontendEntry" :class="['plugin-frame', 'glass', { 'plugin-fullscreen': pluginFullscreen }]">
      <el-button
        v-if="pluginFullscreen"
        class="plugin-fullscreen-exit"
        type="primary"
        title="退出插件全屏"
        @click="exitPluginFullscreen"
      >
        <el-icon><Close /></el-icon><span>退出全屏</span>
      </el-button>
      <div v-if="frontendLoading" class="empty">正在载入插件页面…</div>
      <div v-else-if="frontendError" class="empty error">{{ frontendError }}</div>
      <iframe
        v-else
        ref="iframeRef"
        title="插件沙箱页面"
        sandbox="allow-scripts"
        allow="fullscreen; autoplay; encrypted-media; picture-in-picture"
        allowfullscreen
        :srcdoc="iframeSrcdoc"
      />
    </section>

    <section v-else-if="plugin && page && plugin.enabled && enabled" class="plugin-form glass">
      <el-form label-position="top">
        <el-form-item v-for="field in page.fields" :key="field.id" :label="field.label || field.id">
          <el-switch v-if="field.type === 'switch'" v-model="values[field.id]" />
          <el-select v-else-if="field.type === 'select'" v-model="values[field.id]" style="width: 100%">
            <el-option
              v-for="option in field.options || []"
              :key="String(option.value)"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-input
            v-else-if="field.type === 'textarea'"
            :model-value="textValue(field.id)"
            type="textarea"
            :rows="4"
            :placeholder="field.placeholder"
            @update:model-value="setTextValue(field.id, $event)"
          />
          <el-input
            v-else
            :model-value="textValue(field.id)"
            :type="field.type === 'number' ? 'number' : 'text'"
            :placeholder="field.placeholder"
            @update:model-value="setTextValue(field.id, $event)"
          />
          <small v-if="field.help">{{ field.help }}</small>
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button v-for="action in actions" :key="action.id" type="primary" @click="run(action.id)">
          {{ action.label }}
        </el-button>
      </div>
    </section>

    <section v-else class="empty glass">此插件已关闭，或全局插件功能未开启。</section>
    <Teleport to="body">
      <div
        v-if="yaohuPlayerVisible"
        class="yaohu-player-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="妖狐 M3U8 播放器"
        @click.self="closeYaohuPlayer"
      >
        <section class="yaohu-player-window">
          <header class="yaohu-player-head">
            <div>
              <strong>妖狐 M3U8 播放器</strong>
              <small>播放器由妖狐页面提供</small>
            </div>
            <el-button circle title="关闭播放器" aria-label="关闭播放器" @click="closeYaohuPlayer">
              <el-icon><Close /></el-icon>
            </el-button>
          </header>
          <iframe
            :src="yaohuPlayerUrl"
            title="妖狐 M3U8 播放器"
            referrerpolicy="no-referrer"
            allow="fullscreen; autoplay; encrypted-media; picture-in-picture"
            allowfullscreen
          />
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRaw } from 'vue'
import 'element-plus/es/components/notification/style/css'
import { ElNotification } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Close } from '@element-plus/icons-vue'
import { api, type PluginInfo } from '@/api'

defineOptions({ name: 'PluginDynamicPage' })

const route = useRoute()
const router = useRouter()
const plugin = ref<PluginInfo>()
const enabled = ref(false)
const values = ref<Record<string, string | number | boolean>>({})
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeSrcdoc = ref('')
const frontendLoading = ref(false)
const frontendError = ref('')
const pluginFullscreen = ref(false)
const token = ref('')
const yaohuPlayerUrl = ref('')
const yaohuPlayerVisible = ref(false)

const page = computed(() => plugin.value?.pages.find((item) => item.id === route.params.pageId))
const actions = computed(() => plugin.value?.actions.filter((action) => !page.value?.actions?.length || page.value.actions.includes(action.id)) || [])
const hasFrontendEntry = computed(() => Boolean(plugin.value?.frontend?.entry))
const pageTitle = computed(() => page.value?.title || plugin.value?.name || '插件页面')
const pageDescription = computed(() => page.value?.description || plugin.value?.description || '')

function textValue(id: string): string | number | undefined {
  const value = values.value[id]
  return typeof value === 'boolean' ? String(value) : value
}

function setTextValue(id: string, value: string | number | undefined) {
  values.value[id] = value ?? ''
}

const bridgeScript = `
(function () {
  var config = window.__XB_SVCB_PLUGIN__ || {};
  var seq = 0;
  var pending = {};
  window.addEventListener('message', function (event) {
    if (event.source !== parent) return;
    var data = event.data;
    if (!data || data.channel !== 'xb-svcb-plugin' || data.token !== config.token) return;
    if (data.type === 'event') {
      window.dispatchEvent(new CustomEvent('xb-svcb-host-event', {
        detail: { name: data.name, payload: data.payload || {} }
      }));
      return;
    }
    if (data.type !== 'response') return;
    var waiter = pending[data.id];
    if (!waiter) return;
    delete pending[data.id];
    if (data.ok) waiter.resolve(data.result);
    else waiter.reject(new Error(data.error || '插件宿主调用失败'));
  });
  function request(method, payload) {
    if (!config.token) return Promise.reject(new Error('当前页面不在 XB-SVCB 插件宿主中运行'));
    var id = 'req_' + Date.now() + '_' + (++seq);
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage({ channel: 'xb-svcb-plugin', type: 'request', token: config.token, id: id, method: method, payload: payload || {} }, '*');
    });
  }
  window.XBSVCB = {
    getContext: function () { return request('getContext'); },
    runAction: function (actionId, values) { return request('runAction', { actionId: actionId, values: values || {} }); },
    createWork: function (payload) { return request('createWork', { payload: payload || {} }); },
    assetData: function (path) { return request('assetData', { path: path }); },
    assetUrl: function (path) { return request('assetData', { path: path }).then(function (result) { return result.data; }); },
    notify: function (message, type) { return request('notify', { message: message, type: type || 'success' }); },
    getStorage: function (key, fallback) { return request('getStorage', { key: key, fallback: fallback }); },
    setStorage: function (key, value) { return request('setStorage', { key: key, value: value }); },
    removeStorage: function (key) { return request('removeStorage', { key: key }); },
    toggleWindowFullscreen: function () { return request('toggleWindowFullscreen'); },
    togglePluginFullscreen: function (enabled) { return request('togglePluginFullscreen', { enabled: enabled }); },
    openYaohuPlayer: function (url) { return request('openYaohuPlayer', { url: url }); }
  };
  window.dispatchEvent(new CustomEvent('xb-svcb-ready', { detail: window.XBSVCB }));
})();`

function makeToken() {
  return `xb_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

function injectBridge(html: string) {
  const config = `<script>window.__XB_SVCB_PLUGIN__=${JSON.stringify({ token: token.value })};<\/script>`
  const bridge = `<script>${bridgeScript}<\/script>`
  const injection = `${config}${bridge}`
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head([^>]*)>/i, `<head$1>${injection}`)
  return `<!doctype html><html><head>${injection}</head><body>${html}</body></html>`
}

async function load() {
  const [status, plugins] = await Promise.all([api.getPluginStatus(), api.listPlugins()])
  enabled.value = status.enabled
  plugin.value = plugins.find((item) => item.id === route.params.pluginId)
  values.value = {}
  if (hasFrontendEntry.value) {
    await loadFrontend()
    return
  }
  for (const field of page.value?.fields || []) {
    values.value[field.id] = field.default ?? (field.type === 'switch' ? false : '')
  }
}

async function loadFrontend() {
  if (!plugin.value) return
  frontendLoading.value = true
  frontendError.value = ''
  token.value = makeToken()
  const result = await api.getPluginFrontendDocument(plugin.value.id)
  frontendLoading.value = false
  if (!result.ok || !result.html) {
    frontendError.value = result.error || '插件页面加载失败。'
    iframeSrcdoc.value = ''
    return
  }
  iframeSrcdoc.value = injectBridge(result.html)
}

async function run(actionId: string) {
  if (!plugin.value) return
  const result = await api.runPluginAction(plugin.value.id, actionId, values.value)
  if (!result.ok) {
    notify('error', result.error || '插件操作失败')
    return
  }
  if (result.type === 'create_work' && result.payload) {
    const work = await api.createWork(result.payload)
    notify('success', `已创建翻唱任务：${work.title}`)
    router.push('/works')
  } else {
    notify('success', result.message || '插件操作已完成')
  }
}

function notify(type: unknown, message: unknown) {
  const next = type === 'error' || type === 'warning' || type === 'info' ? type : 'success'
  const titles = { success: '操作完成', warning: '需要注意', info: '提示', error: '操作失败' }
  const text = String(message || '插件操作已完成')
  ElNotification({
    type: next,
    title: titles[next],
    message: text,
    position: 'top-right',
    customClass: 'xb-notification-center',
    duration: next === 'error' ? 4200 : 2600,
    showClose: true,
  })
}

async function handlePluginRequest(event: MessageEvent) {
  if (!iframeRef.value || event.source !== iframeRef.value.contentWindow) return
  const message = event.data
  if (!message || message.channel !== 'xb-svcb-plugin' || message.type !== 'request' || message.token !== token.value) return
  try {
    const result = await dispatchPluginRequest(String(message.method || ''), message.payload || {})
    postPluginResponse(message.id, true, result)
  } catch (error) {
    postPluginResponse(message.id, false, undefined, error instanceof Error ? error.message : String(error))
  }
}

function cloneForPostMessage(value: unknown) {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(toRaw(value)))
}

function pluginStorageKey(key: unknown) {
  if (!plugin.value) throw new Error('插件未加载')
  const normalized = String(key || '').trim()
  if (!/^[a-zA-Z0-9._-]{1,80}$/.test(normalized)) {
    throw new Error('插件存储键只能包含字母、数字、点、下划线和连字符，且长度不能超过 80')
  }
  return 'xb-plugin-storage:' + plugin.value.id + ':' + normalized
}

function normalizeYaohuPlayerUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) throw new Error('妖狐播放器地址不能为空')
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    throw new Error('妖狐播放器地址无效')
  }
  if (url.hostname.toLowerCase() !== 'm3u8.yaohud.cn') throw new Error('只允许打开妖狐 M3U8 播放器')
  url.protocol = 'https:'
  return url.toString()
}

function closeYaohuPlayer() {
  yaohuPlayerVisible.value = false
  yaohuPlayerUrl.value = ''
  document.documentElement.classList.remove('xb-yaohu-player-open')
}
function postPluginEvent(name: string, payload: Record<string, unknown>) {
  iframeRef.value?.contentWindow?.postMessage({
    channel: 'xb-svcb-plugin',
    type: 'event',
    token: token.value,
    name,
    payload: cloneForPostMessage(payload),
  }, '*')
}

function setPluginFullscreen(value: boolean, notifyPlugin = false) {
  pluginFullscreen.value = value
  document.documentElement.classList.toggle('xb-plugin-fullscreen', value)
  if (notifyPlugin) postPluginEvent('pluginFullscreenChanged', { fullscreen: value })
}

function exitPluginFullscreen() {
  setPluginFullscreen(false, true)
}

function handleFullscreenKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (yaohuPlayerVisible.value) {
    closeYaohuPlayer()
    return
  }
  if (pluginFullscreen.value) exitPluginFullscreen()
}

async function dispatchPluginRequest(method: string, payload: Record<string, unknown>) {
  if (!plugin.value) throw new Error('插件未加载')
  if (method === 'getContext') return {
    plugin: cloneForPostMessage(plugin.value),
    page: cloneForPostMessage(page.value),
    theme: localStorage.getItem('xb-theme') || '',
  }
  if (method === 'runAction') {
    const actionId = String(payload.actionId || '')
    const result = await api.runPluginAction(plugin.value.id, actionId, (payload.values as Record<string, unknown>) || {})
    if (!result.ok) throw new Error(result.error || '插件动作执行失败')
    if (result.type === 'create_work' && result.payload) {
      const work = await api.createWork(result.payload)
      notify('success', `已创建翻唱任务：${work.title}`)
      return { ...result, work }
    }
    if (result.message) notify('success', result.message)
    return result
  }
  if (method === 'createWork') {
    const work = await api.createWork((payload.payload as Record<string, unknown>) || {})
    notify('success', `已创建翻唱任务：${work.title}`)
    return work
  }
  if (method === 'assetData') {
    const result = await api.getPluginFrontendAssetData(plugin.value.id, String(payload.path || ''))
    if (!result.ok) throw new Error(result.error || '插件资源读取失败')
    return result
  }
  if (method === 'notify') {
    notify(payload.type, payload.message)
    return true
  }
  if (method === 'getStorage') {
    const fallback = cloneForPostMessage(payload.fallback)
    const storageKey = pluginStorageKey(payload.key)
    const stored = localStorage.getItem(storageKey)
    if (stored === null) return fallback
    try {
      return JSON.parse(stored)
    } catch {
      localStorage.removeItem(storageKey)
      return fallback
    }
  }
  if (method === 'setStorage') {
    const value = cloneForPostMessage(payload.value)
    if (value === undefined) throw new Error('插件持久化数据不能为 undefined')
    localStorage.setItem(pluginStorageKey(payload.key), JSON.stringify(value))
    return true
  }
  if (method === 'removeStorage') {
    localStorage.removeItem(pluginStorageKey(payload.key))
    return true
  }
  if (method === 'openYaohuPlayer') {
    if (!plugin.value.permissions.includes('network')) throw new Error('插件未声明网络权限')
    yaohuPlayerUrl.value = normalizeYaohuPlayerUrl(payload.url)
    yaohuPlayerVisible.value = true
    document.documentElement.classList.add('xb-yaohu-player-open')
    return { opened: true, url: yaohuPlayerUrl.value }
  }
  if (method === 'togglePluginFullscreen') {
    setPluginFullscreen(typeof payload.enabled === 'boolean' ? payload.enabled : !pluginFullscreen.value)
    return { ok: true, fullscreen: pluginFullscreen.value }
  }
  if (method === 'toggleWindowFullscreen') {
    const result = await api.toggleWindowFullscreen()
    if (!result.ok) throw new Error(result.error || '切换软件全屏失败')
    return result
  }
  throw new Error(`不支持的插件宿主方法：${method}`)
}

function postPluginResponse(id: string, ok: boolean, result?: unknown, error?: string) {
  iframeRef.value?.contentWindow?.postMessage({
    channel: 'xb-svcb-plugin',
    type: 'response',
    token: token.value,
    id,
    ok,
    result: cloneForPostMessage(result),
    error,
  }, '*')
}

onMounted(() => {
  window.addEventListener('message', handlePluginRequest)
  window.addEventListener('keydown', handleFullscreenKeydown)
  void load()
})
onBeforeUnmount(() => {
  closeYaohuPlayer()
  setPluginFullscreen(false)
  window.removeEventListener('message', handlePluginRequest)
  window.removeEventListener('keydown', handleFullscreenKeydown)
})
</script>

<style scoped>
.page { width: min(1680px, calc(100% - 56px)); max-width: none; margin: 0 auto; padding: 30px 0 64px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
.eyebrow { color: var(--xb-primary); margin: 0 0 6px; font-size: 12px; }
.page-head h1 { margin: 0 0 6px; }
.page-sub, small { color: var(--xb-muted); }
.glass { background: var(--xb-panel); border: 1px solid var(--xb-border); border-radius: 8px; }
.plugin-form { padding: 24px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.empty { padding: 42px; text-align: center; color: var(--xb-muted); }
.empty.error { color: var(--xb-danger); }
.back-btn { min-height: 40px; border-color: rgba(var(--xb-primary-rgb), .36); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); font-weight: 700; }
.back-btn:hover { border-color: rgba(var(--xb-primary-rgb), .62); color: var(--xb-on-primary); background: var(--xb-brand-gradient); }
.back-btn :deep(.el-icon) { margin-right: 6px; }
.plugin-frame { min-height: min(980px, calc(100dvh - 245px)); overflow: hidden; }
:global(html.xb-plugin-fullscreen),
:global(html.xb-plugin-fullscreen body) { overflow: hidden; }
:global(html.xb-plugin-fullscreen .layout-main) { z-index: 100; }
:global(html.xb-plugin-fullscreen .app-header) { visibility: hidden; pointer-events: none; }
.plugin-frame.plugin-fullscreen { position: fixed; inset: 0; z-index: 10000; width: 100vw; height: 100dvh; min-height: 100dvh; border: 0; border-radius: 0; background: #02050a; }
.plugin-fullscreen-exit { position: fixed; top: 14px; right: 14px; z-index: 10002; min-height: 38px; display: inline-flex; align-items: center; gap: 6px; border-color: rgba(var(--xb-primary-rgb), .54); color: var(--xb-on-primary); background: var(--xb-brand-gradient); box-shadow: 0 10px 28px rgba(0, 0, 0, .34); font-weight: 750; }
.plugin-fullscreen-exit:hover { transform: translateY(-1px); box-shadow: 0 13px 32px rgba(0, 0, 0, .42); }
.plugin-frame iframe { display: block; width: 100%; height: min(980px, calc(100dvh - 245px)); min-height: 720px; border: 0; background: transparent; }
.plugin-frame.plugin-fullscreen iframe { height: 100dvh; min-height: 100dvh; background: #02050a; }
small { display: block; padding-top: 5px; }
:global(html.xb-yaohu-player-open),
:global(html.xb-yaohu-player-open body) { overflow: hidden; }
.yaohu-player-backdrop { position: fixed; inset: 0; z-index: 12000; display: grid; place-items: center; padding: 16px; background: rgba(2, 5, 10, .74); backdrop-filter: blur(10px); }
.yaohu-player-window { display: grid; grid-template-rows: auto minmax(0, 1fr); width: min(1500px, 100%); height: min(920px, 100%); min-height: 0; overflow: hidden; border: 1px solid var(--xb-border); border-radius: 8px; background: #02050a; box-shadow: 0 24px 80px rgba(0, 0, 0, .52); }
.yaohu-player-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 58px; padding: 10px 14px 10px 18px; border-bottom: 1px solid var(--xb-border); color: var(--xb-text); background: var(--xb-panel); }
.yaohu-player-head strong { display: block; font-size: 15px; }
.yaohu-player-head small { padding-top: 2px; font-size: 12px; }
.yaohu-player-window iframe { display: block; width: 100%; height: 100%; min-height: 0; border: 0; background: #000; }
@media (max-width: 720px) {
  .page { width: calc(100% - 28px); padding: 22px 0 48px; }
  .page-head { align-items: stretch; flex-direction: column; }
  .plugin-frame, .plugin-frame iframe { height: calc(100dvh - 220px); min-height: 560px; }
}
</style>
