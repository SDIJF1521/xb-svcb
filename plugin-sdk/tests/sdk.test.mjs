import assert from 'node:assert/strict'
import test from 'node:test'

import { plugin, validateManifest } from '../index.mjs'

test('validator rejects Python actions on frontend-only plugins', () => {
  const definition = plugin('com.example.frontend', 'Frontend')
    .pythonAction('run', 'Run', 'run')

  const result = validateManifest(definition)
  assert.equal(result.ok, false)
  assert.match(result.errors.join('\n'), /Python 动作只能用于/)
})

test('validator rejects absolute Python and frontend entries', () => {
  const pythonResult = validateManifest(
    plugin('com.example.python', 'Python').python('C:/outside.py'),
  )
  const frontendResult = validateManifest(
    plugin('com.example.frontend', 'Frontend').frontend('\\outside\\index.html'),
  )

  assert.equal(pythonResult.ok, false)
  assert.equal(frontendResult.ok, false)
})

test('client completes a host request and enforces timeouts', async () => {
  let listener
  const parent = {
    postMessage(message) {
      if (message.method === 'slow') return
      queueMicrotask(() => listener({
        source: parent,
        data: {
          channel: 'xb-svcb-plugin',
          type: 'response',
          token: 'test-token',
          id: message.id,
          ok: true,
          result: { plugin: { id: 'com.example.frontend' } },
        },
      }))
    },
  }

  globalThis.parent = parent
  globalThis.__XB_SVCB_PLUGIN__ = { token: 'test-token' }
  globalThis.addEventListener = (type, callback) => {
    if (type === 'message') listener = callback
  }

  const { isHosted, request } = await import(`../client.mjs?test=${Date.now()}`)
  assert.equal(isHosted(), true)
  assert.deepEqual(await request('getContext'), { plugin: { id: 'com.example.frontend' } })
  await assert.rejects(request('slow', {}, { timeoutMs: 5 }), /调用超时/)

  delete globalThis.parent
  delete globalThis.__XB_SVCB_PLUGIN__
  delete globalThis.addEventListener
})

test('Vue composable exposes reactive host state without requiring a component wrapper', async () => {
  const { usePluginHost } = await import('../vue.mjs')
  const pluginHost = usePluginHost({ loadContext: false })

  assert.equal(pluginHost.hosted.value, false)
  assert.equal(pluginHost.loading.value, false)
  assert.equal(pluginHost.context.value, null)
  assert.equal(typeof pluginHost.runAction, 'function')
  assert.equal(typeof pluginHost.createWork, 'function')
  assert.equal(typeof pluginHost.getStorage, 'function')
  assert.equal(typeof pluginHost.togglePluginFullscreen, 'function')
  assert.equal(typeof pluginHost.openYaohuPlayer, 'function')
})
