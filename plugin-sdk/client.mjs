let sequence = 0
const pending = new Map()
const defaultTimeoutMs = 30_000

function runtimeConfig() {
  return globalThis.__XB_SVCB_PLUGIN__ || {}
}

export function isHosted() {
  return Boolean(runtimeConfig().token && globalThis.parent)
}

function post(message) {
  globalThis.parent?.postMessage(message, '*')
}

if (typeof globalThis.addEventListener === 'function') {
  globalThis.addEventListener('message', event => {
    if (event.source !== globalThis.parent) return
    const data = event.data
    if (!data || data.channel !== 'xb-svcb-plugin' || data.type !== 'response') return
    const config = runtimeConfig()
    if (data.token !== config.token) return
    const waiter = pending.get(data.id)
    if (!waiter) return
    pending.delete(data.id)
    clearTimeout(waiter.timer)
    if (data.ok) waiter.resolve(data.result)
    else waiter.reject(new Error(data.error || '插件宿主调用失败'))
  })
}

export function request(method, payload = {}, options = {}) {
  const config = runtimeConfig()
  if (!config.token) return Promise.reject(new Error('当前页面不在 XB-SVCB 插件宿主中运行'))
  const id = `req_${Date.now()}_${++sequence}`
  const timeoutMs = Number.isFinite(options.timeoutMs) ? Math.max(0, options.timeoutMs) : defaultTimeoutMs
  return new Promise((resolve, reject) => {
    const timer = timeoutMs > 0
      ? setTimeout(() => {
          pending.delete(id)
          reject(new Error(`插件宿主调用超时：${method}`))
        }, timeoutMs)
      : undefined
    pending.set(id, { resolve, reject, timer })
    post({ channel: 'xb-svcb-plugin', type: 'request', token: config.token, id, method, payload })
  })
}

export const host = {
  getContext: () => request('getContext'),
  runAction: (actionId, values = {}) => request('runAction', { actionId, values }),
  createWork: payload => request('createWork', { payload }),
  assetData: path => request('assetData', { path }),
  assetUrl: path => request('assetData', { path }).then(result => result.data),
  notify: (message, type = 'success') => request('notify', { message, type }),
  getStorage: (key, fallback) => request('getStorage', { key, fallback }),
  setStorage: (key, value) => request('setStorage', { key, value }),
  removeStorage: key => request('removeStorage', { key }),
  togglePluginFullscreen: enabled => request('togglePluginFullscreen', { enabled }),
  toggleWindowFullscreen: () => request('toggleWindowFullscreen'),
  openYaohuPlayer: url => request('openYaohuPlayer', { url }),
}

if (typeof globalThis === 'object' && !globalThis.XBSVCB) {
  globalThis.XBSVCB = host
}
