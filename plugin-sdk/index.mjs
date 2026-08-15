import { cp, mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { createWriteStream } from 'node:fs'
import { dirname, join, resolve, basename } from 'node:path'
import { spawn } from 'node:child_process'
import { tmpdir } from 'node:os'

const idPattern = /^[a-z0-9][a-z0-9._-]{2,63}$/
const fieldTypes = new Set(['text', 'number', 'select', 'switch', 'textarea'])
const actionTypes = new Set(['message', 'create_work', 'python'])
const runtimeTypes = new Set(['frontend', 'python', 'hybrid'])
const permissionTypes = new Set(['python.execute', 'filesystem.plugin', 'filesystem.data', 'network', 'process', 'environment'])
const allowedParams = new Set([
  'pitch', 'f0_method', 'index_rate', 'rms_mix', 'uvr_model', 'diffusion_ratio',
  'device', 'protect', 'filter_radius', 'rvc_version', 'ddsp_infer_steps',
  'ddsp_formant_shift', 'speaker',
])

const clean = (value, fallback = '') => String(value ?? fallback).trim()
const clone = value => JSON.parse(JSON.stringify(value))
const normalizeFrontend = value => {
  if (!value) return {}
  if (typeof value === 'string') return { entry: value }
  return { ...value }
}

export const fields = {
  text: (id, label, options = {}) => ({ id, label, type: 'text', ...options }),
  number: (id, label, options = {}) => ({ id, label, type: 'number', ...options }),
  select: (id, label, options, config = {}) => ({ id, label, type: 'select', options, ...config }),
  switch: (id, label, options = {}) => ({ id, label, type: 'switch', ...options }),
  textarea: (id, label, options = {}) => ({ id, label, type: 'textarea', ...options }),
}

export function page(id, title, configure = {}) {
  const value = typeof configure === 'function' ? configure({ fields }) : configure
  return { id, title, ...(value || {}) }
}

export function messageAction(id, label, message) {
  return { id, label, type: 'message', message }
}

export function createWorkAction(id, label, payload, options = {}) {
  return { id, label, type: 'create_work', payload, ...options }
}

export function pythonAction(id, label, handler = id, options = {}) {
  return { id, label, type: 'python', handler, ...options }
}

export function plugin(id, name, version = '1.0.0') {
  const manifest = {
    id, name, version, description: '', author: '', runtime: 'frontend', python: {}, frontend: {},
    permissions: [], pages: [], actions: [], workflow: {},
  }
  const api = {
    description(value) { manifest.description = value; return api },
    author(value) { manifest.author = value; return api },
    frontend(config) { manifest.runtime = 'frontend'; manifest.python = {}; manifest.frontend = normalizeFrontend(config); return api },
    frontendEntry(entry, config = {}) { manifest.frontend = { ...config, entry }; return api },
    python(entry = 'plugin.py') { manifest.runtime = 'python'; manifest.python = { entry }; api.permission('python.execute'); return api },
    hybrid(entry = 'plugin.py') { manifest.runtime = 'hybrid'; manifest.python = { entry }; api.permission('python.execute'); return api },
    permission(...values) { for (const value of values.flat()) if (!manifest.permissions.includes(value)) manifest.permissions.push(value); return api },
    page(value, title, configure) {
      manifest.pages.push(typeof value === 'object' ? value : page(value, title, configure))
      return api
    },
    action(value) { manifest.actions.push(value); return api },
    message(id, label, text) { return api.action(messageAction(id, label, text)) },
    createWork(id, label, payload, options) { return api.action(createWorkAction(id, label, payload, options)) },
    pythonAction(id, label, handler = id, options) { return api.action(pythonAction(id, label, handler, options)) },
    beforeCreate(params) {
      manifest.workflow = { ...manifest.workflow, before_create: { params: { ...params } } }
      return api
    },
    build() { return clone(manifest) },
  }
  return api
}

function validateField(field, path, errors) {
  if (!field || typeof field !== 'object') return errors.push(`${path} 必须是对象`)
  if (!idPattern.test(clean(field.id))) errors.push(`${path}.id 必须是 3-64 位小写标识符`)
  if (!fieldTypes.has(field.type)) errors.push(`${path}.type 不支持：${field.type}`)
  if (field.type === 'select' && (!Array.isArray(field.options) || !field.options.length)) errors.push(`${path}.options 必须是非空数组`)
}

export function validateManifest(input) {
  const manifest = input?.build ? input.build() : input
  const errors = []
  if (!manifest || typeof manifest !== 'object') errors.push('插件清单必须是对象')
  else {
    for (const key of ['id', 'name', 'version']) if (!clean(manifest[key])) errors.push(`缺少 ${key}`)
    if (!idPattern.test(clean(manifest.id))) errors.push('id 必须是 3-64 位小写标识符，例如 com.example.my-plugin')
    if (!Array.isArray(manifest.pages)) errors.push('pages 必须是数组')
    if (!Array.isArray(manifest.actions)) errors.push('actions 必须是数组')
    if (!runtimeTypes.has(manifest.runtime || 'frontend')) errors.push(`runtime 不支持：${manifest.runtime}`)
    if (['python', 'hybrid'].includes(manifest.runtime)) {
      const entry = clean(manifest.python?.entry)
      if (!entry || !entry.toLowerCase().endsWith('.py') || entry.includes('..') || entry.startsWith('/') || entry.startsWith('\\') || /^[a-zA-Z]:/.test(entry)) {
        errors.push('Python 插件必须提供插件目录内的 .py 入口')
      }
      if (!manifest.permissions?.includes('python.execute')) errors.push('Python 插件必须声明 python.execute 权限')
    }
    const frontendEntry = clean(manifest.frontend?.entry)
    if (frontendEntry && (!/\.html?$/i.test(frontendEntry) || frontendEntry.includes('..') || frontendEntry.startsWith('/') || frontendEntry.startsWith('\\') || /^[a-zA-Z]:/.test(frontendEntry))) {
      errors.push('frontend.entry 必须指向插件目录内的 .html 文件')
    }
    if (!Array.isArray(manifest.permissions)) errors.push('permissions 必须是数组')
    else for (const permission of manifest.permissions) if (!permissionTypes.has(permission)) errors.push(`不支持的权限：${permission}`)
    for (const [index, item] of (manifest.pages || []).entries()) {
      if (!idPattern.test(clean(item?.id))) errors.push(`pages[${index}].id 无效`)
      if (!clean(item?.title)) errors.push(`pages[${index}].title 不能为空`)
      if (!Array.isArray(item?.fields)) errors.push(`pages[${index}].fields 必须是数组`)
      for (const [fieldIndex, field] of (item?.fields || []).entries()) validateField(field, `pages[${index}].fields[${fieldIndex}]`, errors)
    }
    for (const [index, action] of (manifest.actions || []).entries()) {
      if (!idPattern.test(clean(action?.id))) errors.push(`actions[${index}].id 无效`)
      if (!clean(action?.label)) errors.push(`actions[${index}].label 不能为空`)
      if (!actionTypes.has(action?.type)) errors.push(`actions[${index}].type 不支持：${action?.type}`)
      if (action?.type === 'create_work' && (!action.payload || typeof action.payload !== 'object')) errors.push(`actions[${index}].payload 必须是对象`)
      if (action?.type === 'python' && !/^[a-zA-Z_][a-zA-Z0-9_]{0,63}$/.test(clean(action.handler))) errors.push(`actions[${index}].handler 无效`)
      if (action?.type === 'python' && !['python', 'hybrid'].includes(manifest.runtime)) errors.push(`actions[${index}] 的 Python 动作只能用于 python 或 hybrid 插件`)
    }
    const params = manifest.workflow?.before_create?.params || {}
    for (const key of Object.keys(params)) if (!allowedParams.has(key)) errors.push(`workflow.before_create.params.${key} 不在允许列表中`)
  }
  return { ok: errors.length === 0, errors, manifest: manifest ? clone(manifest) : undefined }
}

export async function writeManifest(manifestOrBuilder, directory) {
  const result = validateManifest(manifestOrBuilder)
  if (!result.ok) throw new Error(`插件清单校验失败：\n- ${result.errors.join('\n- ')}`)
  const target = resolve(directory)
  await mkdir(target, { recursive: true })
  const file = join(target, 'xb-svcb-plugin.json')
  await writeFile(file, `${JSON.stringify(result.manifest, null, 2)}\n`, 'utf8')
  return file
}

async function zipDirectory(source, output) {
  const command = process.platform === 'win32' ? 'powershell.exe' : 'zip'
  const requestedOutput = resolve(output)
  const archiveOutput = process.platform === 'win32' && requestedOutput.toLowerCase().endsWith('.xbplugin')
    ? `${requestedOutput}.zip`
    : requestedOutput
  const args = process.platform === 'win32'
    ? ['-NoProfile', '-Command', `Compress-Archive -Path ${JSON.stringify(join(source, '*'))} -DestinationPath ${JSON.stringify(archiveOutput)} -Force`]
    : ['-r', archiveOutput, '.']
  await new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { cwd: source, stdio: 'inherit', shell: false })
    child.on('error', reject)
    child.on('exit', code => code === 0 ? resolvePromise() : reject(new Error(`压缩命令退出码 ${code}`)))
  })
  if (archiveOutput !== requestedOutput) await rename(archiveOutput, requestedOutput)
}

export async function packPlugin(directory, output = `${resolve(directory)}.xbplugin`) {
  const source = resolve(directory)
  const manifestPath = join(source, 'xb-svcb-plugin.json')
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  const result = validateManifest(manifest)
  if (!result.ok) throw new Error(`插件清单校验失败：\n- ${result.errors.join('\n- ')}`)
  await mkdir(dirname(resolve(output)), { recursive: true })
  const temporary = await mkdtemp(join(tmpdir(), 'xb-plugin-pack-'))
  const staging = join(temporary, 'plugin')
  const ignored = new Set(['node_modules', '.git', '.venv', '__pycache__', '.pytest_cache'])
  try {
    await cp(source, staging, {
      recursive: true,
      filter: candidate => {
        const name = basename(candidate)
        return !ignored.has(name) && !name.toLowerCase().endsWith('.xbplugin')
      },
    })
    await zipDirectory(staging, resolve(output))
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }
  return resolve(output)
}

export async function createPlugin({ directory, id, name, version = '1.0.0', description = '', author = '' }) {
  const builder = plugin(id, name, version).description(description).author(author)
  await writeManifest(builder, directory)
  return builder
}

export { allowedParams }
