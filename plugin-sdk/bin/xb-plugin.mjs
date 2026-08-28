#!/usr/bin/env node
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { plugin, writeManifest, packPlugin, validatePluginDirectory } from '../index.mjs'

const args = process.argv.slice(2)
const command = args.shift()
const option = name => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : undefined }
const help = () => console.log(`XB-SVCB Plugin SDK\n\n命令：\n  xb-plugin create <dir> --id <id> --name <name> [--type frontend|python|hybrid] [--language ts|js] [--framework vue|vanilla]\n  xb-plugin validate <dir>\n  xb-plugin pack <dir> [output.xbplugin]\n`)

try {
  if (command === 'create') {
    const directory = args[0]
    if (!directory || !option('--id') || !option('--name')) throw new Error('create 需要 <dir>、--id 和 --name')
    const type = option('--type') || 'frontend'
    if (!['frontend', 'python', 'hybrid'].includes(type)) throw new Error('--type 只能是 frontend、python 或 hybrid')
    const language = option('--language') || 'ts'
    if (!['ts', 'js'].includes(language)) throw new Error('--language 只能是 ts 或 js')
    const framework = type === 'python' ? 'none' : (option('--framework') || (language === 'ts' ? 'vue' : 'vanilla'))
    if (!['none', 'vue', 'vanilla'].includes(framework)) throw new Error('--framework 只能是 vue 或 vanilla')
    if (language === 'js' && framework === 'vue') throw new Error('Vue 脚手架需要 TypeScript，请使用 --language ts')
    const target = resolve(directory)
    await mkdir(target, { recursive: true })
    const id = option('--id'); const name = option('--name'); const author = option('--author') || ''
    const version = option('--version') || '1.0.0'
    const frontendEntry = language === 'ts' ? 'dist/frontend/index.html' : 'frontend/index.html'
    const runtime = type === 'frontend'
      ? `frontend('${frontendEntry}')`
      : type === 'python'
        ? "python('plugin.py', { requirements: 'requirements.txt' })"
        : `hybrid('plugin.py', { requirements: 'requirements.txt' })\n  .frontendEntry('${frontendEntry}')`
    const actionLine = type === 'frontend'
      ? ".message('hello', '打招呼', '你好，{{name}}！')"
      : type === 'hybrid' ? ".pythonAction('hello', '运行 Python', 'hello')" : ''
    const build = `import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'\n\nconst app = plugin(${JSON.stringify(id)}, ${JSON.stringify(name)}, ${JSON.stringify(version)})\n  .author(${JSON.stringify(author)})\n  .${runtime}${actionLine ? `\n  ${actionLine}` : ''}\n\nawait writeManifest(app, '.')\n`
    const sourceDirectory = language === 'ts' ? join(target, 'src') : target
    const sourceFile = language === 'ts' ? join(sourceDirectory, 'plugin.ts') : join(sourceDirectory, 'build.mjs')
    await mkdir(sourceDirectory, { recursive: true })
    await writeFile(sourceFile, build, 'utf8')
    const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
    const sdkDependency = sdkRoot.toLowerCase().includes('node_modules') ? '^0.1.0' : `file:${sdkRoot.replaceAll('\\', '/')}`
    const packageJson = language === 'ts'
      ? (() => {
          const hasFrontend = type !== 'python'
          const usesVue = hasFrontend && framework === 'vue'
          const scripts = {
            'build:manifest': 'tsx src/plugin.ts',
            ...(hasFrontend ? { 'build:frontend': 'vite build', dev: 'vite' } : {}),
            build: hasFrontend ? 'npm run build:frontend && npm run build:manifest' : 'npm run build:manifest',
            typecheck: usesVue ? 'vue-tsc --noEmit' : 'tsc --noEmit',
            validate: 'npm run typecheck && npm run build && xb-plugin validate .',
            pack: 'npm run validate && xb-plugin pack .',
          }
          const devDependencies = {
            '@xb-svcb/plugin-sdk': sdkDependency,
            '@types/node': '^24.12.2',
            tsx: '^4.21.0',
            typescript: '~6.0.0',
            ...(hasFrontend ? { vite: '^8.0.8', 'vite-plugin-singlefile': '^2.3.0' } : {}),
            ...(usesVue ? { '@vitejs/plugin-vue': '^6.0.6', 'vue-tsc': '^3.2.6' } : {}),
          }
          return {
            private: true,
            type: 'module',
            engines: { node: '^20.19.0 || >=22.12.0' },
            scripts,
            devDependencies,
            ...(usesVue ? { dependencies: { vue: '^3.5.32' } } : {}),
          }
        })()
      : {
          private: true,
          type: 'module',
          scripts: {
            build: 'node build.mjs',
            validate: 'npm run build && xb-plugin validate .',
            pack: 'npm run validate && xb-plugin pack .',
          },
          devDependencies: { '@xb-svcb/plugin-sdk': sdkDependency },
        }
    await writeFile(join(target, 'package.json'), JSON.stringify(packageJson, null, 2) + '\n', 'utf8')
    if (type !== 'python') {
      const frontendDirectory = join(target, 'frontend')
      await mkdir(frontendDirectory, { recursive: true })
      if (language === 'ts') {
        const frontendSource = join(frontendDirectory, 'src')
        await mkdir(frontendSource, { recursive: true })
        if (framework === 'vue') {
          const componentsDirectory = join(frontendSource, 'components')
          await mkdir(componentsDirectory, { recursive: true })
          await writeFile(join(frontendDirectory, 'index.html'), `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${name}</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
`, 'utf8')
          await writeFile(join(frontendSource, 'main.ts'), `import { createApp } from 'vue'

import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
`, 'utf8')
          await writeFile(join(frontendSource, 'App.vue'), `<script setup lang="ts">
import GreetingForm from './components/GreetingForm.vue'
</script>

<template>
  <main class="plugin-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">VUE 3 PLUGIN</p>
        <h1>${name}</h1>
        <p class="subtitle">这个布局和所有组件都可以自由修改。</p>
      </div>
      <span class="status">TypeScript</span>
    </header>

    <GreetingForm />
  </main>
</template>
`, 'utf8')
          await writeFile(join(componentsDirectory, 'GreetingForm.vue'), `<script setup lang="ts">
import { ref } from 'vue'

import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const name = ref('朋友')
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()

async function submit() {
  if (!hosted.value) {
    output.value = '当前是浏览器开发预览；安装插件后可调用真实宿主动作。'
    return
  }
  try {
    const result = await runAction('hello', { name: name.value })
    output.value = JSON.stringify(result, null, 2)
  } catch {
    output.value = error.value?.message || '插件动作执行失败'
  }
}
</script>

<template>
  <section class="tool-panel">
    <label for="name">你的名字</label>
    <div class="input-row">
      <input id="name" v-model="name" autocomplete="name">
      <button type="button" :disabled="loading" @click="submit">
        {{ loading ? '执行中…' : '调用插件动作' }}
      </button>
    </div>
    <pre v-if="output" aria-live="polite">{{ output }}</pre>
  </section>
</template>
`, 'utf8')
          await writeFile(join(frontendSource, 'style.css'), `:root { color-scheme: light dark; font-family: Inter, "Microsoft YaHei", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; color: #e8edf2; background: #15191d; }
button, input { font: inherit; }
.plugin-page { width: min(760px, 100%); margin: 0 auto; padding: 28px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 22px; border-bottom: 1px solid #343b42; }
.eyebrow { margin: 0 0 8px; color: #65d8c4; font-size: 11px; }
h1 { margin: 0; font-size: 26px; }
.subtitle { margin: 8px 0 0; color: #9ca8b2; font-size: 13px; }
.status { padding: 5px 8px; border: 1px solid #3a766c; border-radius: 5px; color: #83ead7; font-size: 11px; }
.tool-panel { display: grid; gap: 12px; margin-top: 24px; padding: 20px; border: 1px solid #343b42; border-radius: 8px; background: #1c2227; }
label { color: #b8c2ca; font-size: 13px; }
.input-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }
input { min-height: 40px; border: 1px solid #46515a; border-radius: 6px; padding: 0 12px; color: inherit; background: #111518; }
button { min-height: 40px; border: 0; border-radius: 6px; padding: 0 16px; color: #071411; background: #79dfcd; font-weight: 700; cursor: pointer; }
button:disabled { cursor: wait; opacity: .55; }
pre { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #a9ebbd; }
@media (max-width: 560px) { .plugin-page { padding: 20px 16px; } .page-header { flex-direction: column; } .input-row { grid-template-columns: 1fr; } }
`, 'utf8')
          await writeFile(join(frontendSource, 'env.d.ts'), `/// <reference types="vite/client" />
`, 'utf8')
          await writeFile(join(target, 'vite.config.ts'), `import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
  root: 'frontend',
  plugins: [vue(), viteSingleFile()],
  build: {
    outDir: '../dist/frontend',
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
  },
})
`, 'utf8')
        } else {
        await writeFile(join(frontendDirectory, 'index.html'), `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${name}</title>
</head>
<body>
  <main>
    <h1>${name}</h1>
    <label>你的名字 <input id="name" value="朋友"></label>
    <button id="hello">调用插件动作</button>
    <pre id="output" aria-live="polite"></pre>
  </main>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
`, 'utf8')
        await writeFile(join(frontendSource, 'main.ts'), `import { host, isHosted } from '@xb-svcb/plugin-sdk/client'
import './style.css'

function element<T extends Element>(selector: string): T {
  const value = document.querySelector<T>(selector)
  if (!value) throw new Error('缺少页面元素：' + selector)
  return value
}

const nameInput = element<HTMLInputElement>('#name')
const button = element<HTMLButtonElement>('#hello')
const output = element<HTMLPreElement>('#output')

button.addEventListener('click', async () => {
  if (!isHosted()) {
    output.textContent = '当前是浏览器开发预览；请在 XB-SVCB 插件中心安装后测试宿主动作。'
    return
  }
  button.disabled = true
  try {
    const result = await host.runAction('hello', { name: nameInput.value })
    output.textContent = JSON.stringify(result, null, 2)
  } catch (error) {
    output.textContent = error instanceof Error ? error.message : String(error)
  } finally {
    button.disabled = false
  }
})
`, 'utf8')
        await writeFile(join(frontendSource, 'style.css'), `:root { color-scheme: light dark; font-family: Inter, "Microsoft YaHei", sans-serif; }
body { margin: 0; color: #e8edf7; background: #111827; }
main { display: grid; gap: 14px; max-width: 640px; margin: 0 auto; padding: 28px; }
label { display: grid; gap: 6px; color: #aeb7ca; font-size: 13px; }
input { min-height: 38px; border: 1px solid #334155; border-radius: 8px; padding: 0 12px; color: inherit; background: #0f172a; }
button { width: fit-content; min-height: 38px; border: 0; border-radius: 8px; padding: 0 16px; color: #08111f; background: #67e8f9; font-weight: 700; cursor: pointer; }
button:disabled { cursor: wait; opacity: .55; }
pre { min-height: 24px; white-space: pre-wrap; overflow-wrap: anywhere; color: #a7f3d0; }
`, 'utf8')
        await writeFile(join(target, 'vite.config.ts'), `import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
  root: 'frontend',
  plugins: [viteSingleFile()],
  build: {
    outDir: '../dist/frontend',
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
  },
})
`, 'utf8')
        }
      } else {
        await writeFile(join(frontendDirectory, 'index.html'), `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${name}</title>
</head>
<body>
  <main>
    <h1>${name}</h1>
    <label>你的名字 <input id="name" value="朋友"></label>
    <button id="hello">调用插件动作</button>
    <pre id="output"></pre>
  </main>
  <script>
    const output = document.querySelector('#output')
    document.querySelector('#hello').addEventListener('click', async () => {
      try {
        const name = document.querySelector('#name').value
        const result = await XBSVCB.runAction('hello', { name })
        output.textContent = JSON.stringify(result, null, 2)
      } catch (error) {
        output.textContent = error instanceof Error ? error.message : String(error)
      }
    })
  </script>
</body>
</html>
`, 'utf8')
      }
    }
    if (language === 'ts') {
      const hasFrontend = type !== 'python'
      const usesVue = hasFrontend && framework === 'vue'
      await writeFile(join(target, 'tsconfig.json'), JSON.stringify({
        compilerOptions: {
          target: 'ES2022',
          module: 'ESNext',
          moduleResolution: 'Bundler',
          strict: true,
          noEmit: true,
          verbatimModuleSyntax: true,
          skipLibCheck: true,
          lib: hasFrontend ? ['ES2022', 'DOM', 'DOM.Iterable'] : ['ES2022'],
          types: hasFrontend ? ['node', 'vite/client'] : ['node'],
        },
        include: hasFrontend
          ? ['src/**/*.ts', 'frontend/**/*.ts', ...(usesVue ? ['frontend/**/*.vue'] : []), 'vite.config.ts']
          : ['src/**/*.ts'],
      }, null, 2) + '\n', 'utf8')
    }
    if (type !== 'frontend') {
      const python = `from xb_svcb_plugin import ActionResult, Plugin, PluginContext\n\nplugin = Plugin(${JSON.stringify(id)})\n\n@plugin.action("hello")\ndef hello(ctx: PluginContext, values: dict):\n    return ActionResult.message_result(f"你好，{values.get('name') or '朋友'}！")\n\n@plugin.before_create\ndef before_create(ctx: PluginContext, payload: dict):\n    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")\n    return payload\n`
      await writeFile(join(target, 'plugin.py'), python, 'utf8')
      await writeFile(
        join(target, 'requirements.txt'),
        '# Add pinned third-party dependencies here, one per line.\n',
        'utf8',
      )
    }
    const definition = plugin(id, name, version).author(author)
    if (type === 'frontend') definition.frontend(frontendEntry).message('hello', '打招呼', '你好，{{name}}！')
    if (type === 'python') definition.python('plugin.py', { requirements: 'requirements.txt' })
    if (type === 'hybrid') definition.hybrid('plugin.py', { requirements: 'requirements.txt' }).frontendEntry(frontendEntry).pythonAction('hello', '运行 Python', 'hello')
    await writeManifest(definition, target)
    console.log(`已创建插件：${resolve(directory)}`)
    const editable = language === 'ts' ? 'src/plugin.ts' : 'build.mjs'
    const editableFiles = [editable]
    if (type !== 'python') {
      if (framework === 'vue') editableFiles.push('frontend/src/App.vue', 'frontend/src/components/GreetingForm.vue')
      else if (language === 'ts') editableFiles.push('frontend/index.html', 'frontend/src/main.ts')
      else editableFiles.push('frontend/index.html')
    }
    if (type !== 'frontend') editableFiles.push('plugin.py', 'requirements.txt')
    const typecheckHint = language === 'ts' ? '、npm run typecheck' : ''
    console.log(`下一步：编辑 ${editableFiles.join('、')}，然后运行 npm install${typecheckHint}、npm run validate、npm run pack。`)
  } else if (command === 'validate') {
    const directory = resolve(args[0] || '.')
    const result = await validatePluginDirectory(directory)
    if (!result.ok) { console.error(result.errors.map(item => `- ${item}`).join('\n')); process.exitCode = 1 } else console.log(`插件目录有效：${file}`)
  } else if (command === 'pack') {
    const output = await packPlugin(args[0] || '.', args[1])
    console.log(`已打包：${output}`)
  } else help()
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exitCode = 1
}
