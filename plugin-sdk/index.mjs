import { access, cp, mkdir, mkdtemp, readFile, readdir, rename, rm, stat, writeFile } from 'node:fs/promises'
import { createWriteStream } from 'node:fs'
import { basename, dirname, isAbsolute, join, relative as relativePath, resolve } from 'node:path'
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
const validRelativePath = (value, suffix) => {
  const raw = clean(value).replaceAll('\\', '/')
  if (!raw || raw.startsWith('/') || raw.includes('\0') || /^[a-zA-Z]:/.test(raw)) return false
  const parts = raw.split('/')
  if (parts.some(part => !part || part === '.' || part === '..')) return false
  return !suffix || suffix.test(parts.at(-1))
}
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
    python(entry = 'plugin.py', config = {}) { manifest.runtime = 'python'; manifest.python = { ...config, entry }; api.permission('python.execute'); return api },
    hybrid(entry = 'plugin.py', config = {}) { manifest.runtime = 'hybrid'; manifest.python = { ...config, entry }; api.permission('python.execute'); return api },
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
      if (!validRelativePath(entry, /\.py$/i)) {
        errors.push('Python 插件必须提供插件目录内的 .py 入口')
      }
      const requirements = clean(manifest.python?.requirements)
      if (requirements && !validRelativePath(requirements, /\.txt$/i)) {
        errors.push('python.requirements 必须指向插件目录内的 .txt 文件')
      }
      const vendor = clean(manifest.python?.vendor)
      if (vendor && !validRelativePath(vendor)) {
        errors.push('python.vendor 必须是插件目录内的相对目录')
      }
      if (!manifest.permissions?.includes('python.execute')) errors.push('Python 插件必须声明 python.execute 权限')
    }
    const frontendEntry = clean(manifest.frontend?.entry)
    if (frontendEntry && !validRelativePath(frontendEntry, /\.html?$/i)) {
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

async function ensureFile(source, relative, label) {
  const target = resolve(source, clean(relative).replaceAll('\\', '/'))
  const fromRoot = relativePath(source, target)
  const parentPrefix = `..${process.platform === 'win32' ? '\\' : '/'}`
  if (!fromRoot || fromRoot === '..' || fromRoot.startsWith(parentPrefix) || isAbsolute(fromRoot)) {
    throw new Error(`${label}路径非法：${relative}`)
  }
  let fileStat
  try {
    fileStat = await stat(target)
  } catch {
    throw new Error(`${label}不存在：${relative}`)
  }
  if (!fileStat.isFile()) throw new Error(`${label}不是文件：${relative}`)
  return { target, stat: fileStat }
}

/** Validate the on-disk build output before it is distributed to users. */
export async function validatePluginDirectory(directory) {
  const source = resolve(directory)
  const manifestPath = join(source, 'xb-svcb-plugin.json')
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  const result = validateManifest(manifest)
  if (!result.ok) return result
  const errors = []
  if (['python', 'hybrid'].includes(manifest.runtime)) {
    try {
      const { stat } = await ensureFile(source, manifest.python.entry, 'Python 入口')
      if (stat.size > 2 * 1024 * 1024) errors.push('Python 入口超过 2 MB')
    } catch (error) { errors.push(error.message) }
    if (manifest.python.requirements) {
      try { await ensureFile(source, manifest.python.requirements, 'Python requirements 文件') }
      catch (error) { errors.push(error.message) }
    }
    if (manifest.python.vendor) {
      try {
        const vendor = await stat(resolve(source, manifest.python.vendor.replaceAll('\\', '/')))
        if (!vendor.isDirectory()) errors.push(`Python vendor 不是目录：${manifest.python.vendor}`)
      } catch (error) {
        if (error?.code !== 'ENOENT') errors.push(`无法读取 Python vendor：${manifest.python.vendor}`)
      }
    }
  }
  const frontendEntry = clean(manifest.frontend?.entry)
  if (frontendEntry) {
    try {
      const { target, stat } = await ensureFile(source, frontendEntry, '前端入口')
      if (stat.size > 2 * 1024 * 1024) errors.push('前端入口超过 2 MB')
      const html = await readFile(target, 'utf8')
      // The host loads HTML through srcdoc. Unbundled local scripts/styles
      // resolve against the host page and fail on another machine.
      const assetPatterns = [
        /<(?:script|img|audio|video|source|iframe)[^>]+src\s*=\s*["'](?!https?:|data:|blob:|\/\/|#)([^"']+)/i,
        /<link[^>]+href\s*=\s*["'](?!https?:|data:|blob:|\/\/|#)([^"']+)/i,
        /<object[^>]+data\s*=\s*["'](?!https?:|data:|blob:|\/\/|#)([^"']+)/i,
        /url\(\s*["']?(?!https?:|data:|blob:|\/\/|#)([^)'"\s]+)/i,
      ]
      const localAsset = assetPatterns.map(pattern => pattern.exec(html)).find(Boolean)
      if (localAsset) errors.push(`前端入口仍引用外部本地资源：${localAsset[1]}，请使用 vite-plugin-singlefile 构建`)
    } catch (error) { errors.push(error.message) }
  }
  return { ok: errors.length === 0, errors, manifest: clone(manifest) }
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

async function commandSucceeds(command, args) {
  return new Promise(resolvePromise => {
    const child = spawn(command, args, { stdio: 'ignore', shell: false })
    child.on('error', () => resolvePromise(false))
    child.on('exit', code => resolvePromise(code === 0))
  })
}

async function python310Command() {
  const explicit = clean(process.env.XB_PLUGIN_BUILD_PYTHON)
  const candidates = [
    ...(explicit ? [{ command: explicit, prefix: [] }] : []),
    ...(process.platform === 'win32' ? [{ command: 'py', prefix: ['-3.10'] }] : []),
    { command: 'python3.10', prefix: [] },
    { command: 'python', prefix: [] },
  ]
  for (const candidate of candidates) {
    const probe = [
      ...candidate.prefix,
      '-c',
      'import sys;raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)',
    ]
    if (await commandSucceeds(candidate.command, probe)) return candidate
  }
  throw new Error('打包 Python 依赖需要 Python 3.10；可通过 XB_PLUGIN_BUILD_PYTHON 指定解释器')
}

function hasRequirements(content) {
  return content.split(/\r?\n/).some(line => {
    const value = line.trim()
    return value && !value.startsWith('#')
  })
}

async function bundlePythonRequirements(source, staging, manifest) {
  if (!['python', 'hybrid'].includes(manifest.runtime)) return
  let requirements = clean(manifest.python?.requirements)
  if (!requirements) {
    try {
      await access(join(source, 'requirements.txt'))
      requirements = 'requirements.txt'
    } catch { return }
  }
  const requirementsPath = resolve(source, requirements.replaceAll('\\', '/'))
  const content = await readFile(requirementsPath, 'utf8')
  if (!hasRequirements(content)) return
  if (/^\s*xb[-_]svcb[-_]plugin[-_]sdk(?:\s|[<=>@;]|$)/im.test(content)) {
    throw new Error('requirements 中不能包含 xb-svcb-plugin-sdk；运行时 SDK 由宿主提供')
  }
  const vendor = clean(manifest.python?.vendor, 'vendor') || 'vendor'
  const target = resolve(staging, vendor.replaceAll('\\', '/'))
  await rm(target, { recursive: true, force: true })
  await mkdir(target, { recursive: true })
  const python = await python310Command()
  const args = [
    ...python.prefix,
    '-m', 'pip', 'install',
    '--disable-pip-version-check',
    '--no-compile',
    '--upgrade',
    '--target', target,
    '--requirement', requirementsPath,
  ]
  await new Promise((resolvePromise, reject) => {
    const child = spawn(python.command, args, { cwd: source, stdio: 'inherit', shell: false })
    child.on('error', reject)
    child.on('exit', code => code === 0
      ? resolvePromise()
      : reject(new Error(`Python 依赖打包失败，pip 退出码 ${code}`)))
  })
}

async function directorySize(directory) {
  let total = 0
  const entries = await readdir(directory, { withFileTypes: true })
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) total += await directorySize(path)
    else if (entry.isFile()) total += (await stat(path)).size
  }
  return total
}

export async function packPlugin(directory, output = `${resolve(directory)}.xbplugin`) {
  const source = resolve(directory)
  const result = await validatePluginDirectory(source)
  if (!result.ok) throw new Error(`插件清单校验失败：\n- ${result.errors.join('\n- ')}`)
  const manifest = result.manifest
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
    await bundlePythonRequirements(source, staging, manifest)
    const unpackedBytes = await directorySize(staging)
    if (unpackedBytes > 50 * 1024 * 1024) {
      throw new Error(`插件解压后约 ${(unpackedBytes / 1024 / 1024).toFixed(1)} MB，超过 50 MB 限制`)
    }
    await zipDirectory(staging, resolve(output))
    const bundleBytes = (await stat(resolve(output))).size
    if (bundleBytes > 20 * 1024 * 1024) {
      await rm(resolve(output), { force: true })
      throw new Error(`插件包约 ${(bundleBytes / 1024 / 1024).toFixed(1)} MB，超过 20 MB 限制`)
    }
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
