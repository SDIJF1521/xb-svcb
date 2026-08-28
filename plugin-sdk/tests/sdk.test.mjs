import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import test from 'node:test'

import { plugin, validateManifest, validatePluginDirectory } from '../index.mjs'

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

test('validator rejects ambiguous relative runtime paths', () => {
  const result = validateManifest(
    plugin('com.example.paths', 'Paths')
      .hybrid('backend\\.\\plugin.py', { requirements: 'deps//requirements.txt' })
      .frontendEntry('dist/./index.html'),
  )

  assert.equal(result.ok, false)
  assert.match(result.errors.join('\n'), /Python 插件必须提供/)
  assert.match(result.errors.join('\n'), /python\.requirements/)
  assert.match(result.errors.join('\n'), /frontend\.entry/)
})

test('directory validator catches missing runtime files before packaging', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xb-sdk-test-'))
  try {
    const manifest = plugin('com.example.hybrid', 'Hybrid')
      .hybrid('plugin.py', { requirements: 'requirements.txt', vendor: 'deps/vendor' })
      .frontendEntry('dist/frontend/index.html')
      .build()
    await writeFile(join(directory, 'xb-svcb-plugin.json'), JSON.stringify(manifest), 'utf8')

    const result = await validatePluginDirectory(directory)
    assert.equal(result.ok, false)
    assert.match(result.errors.join('\n'), /Python 入口不存在/)
    assert.match(result.errors.join('\n'), /requirements 文件不存在/)
    assert.match(result.errors.join('\n'), /前端入口不存在/)
    assert.doesNotMatch(result.errors.join('\n'), /vendor 不存在/)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('directory validator rejects frontend builds with relative script assets', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xb-sdk-test-'))
  try {
    const manifest = plugin('com.example.hybrid', 'Hybrid')
      .hybrid('plugin.py')
      .frontendEntry('dist/frontend/index.html')
      .build()
    await mkdir(join(directory, 'dist/frontend'), { recursive: true })
    await writeFile(join(directory, 'plugin.py'), 'pass\n', 'utf8')
    await writeFile(
      join(directory, 'dist/frontend/index.html'),
      '<script type="module" src="./assets/index.js"></script>',
      'utf8',
    )
    await writeFile(join(directory, 'xb-svcb-plugin.json'), JSON.stringify(manifest), 'utf8')

    const result = await validatePluginDirectory(directory)
    assert.equal(result.ok, false)
    assert.match(result.errors.join('\n'), /vite-plugin-singlefile/)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('directory validator rejects relative CSS asset URLs', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xb-sdk-test-'))
  try {
    const manifest = plugin('com.example.styles', 'Styles')
      .frontend('index.html')
      .build()
    await writeFile(join(directory, 'index.html'), '<style>body{background:url("./background.png")}</style>', 'utf8')
    await writeFile(join(directory, 'xb-svcb-plugin.json'), JSON.stringify(manifest), 'utf8')

    const result = await validatePluginDirectory(directory)
    assert.equal(result.ok, false)
    assert.match(result.errors.join('\n'), /\.\/background\.png/)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
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
