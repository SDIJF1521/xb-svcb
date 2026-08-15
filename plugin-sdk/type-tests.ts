import {
  fields,
  plugin,
  validateManifest,
  type Action,
  type BeforeCreateParams,
  type Manifest,
  type PluginPermission,
} from '@xb-svcb/plugin-sdk'
import {
  host,
  isHosted,
  request,
  type CreateWorkPayload,
  type PluginHostContext,
  type RequestOptions,
} from '@xb-svcb/plugin-sdk/client'
import {
  usePluginHost,
  type UsePluginHostOptions,
  type UsePluginHostResult,
} from '@xb-svcb/plugin-sdk/vue'

const permissions = ['filesystem.data', 'network'] satisfies PluginPermission[]
const defaults = { f0_method: 'rmvpe', pitch: 0 } satisfies BeforeCreateParams

const app = plugin('example.type-test', 'TypeScript 类型测试')
  .frontend('frontend/index.html')
  .permission(permissions)
  .beforeCreate(defaults)
  .page('main', '首页', {
    fields: [
      fields.text('title', '标题', { default: '我的翻唱' }),
      fields.number('pitch', '升降调', { default: 0 }),
      fields.switch('enhance', '增强', { default: true }),
      fields.select('style', '风格', [{ label: '自然', value: 'natural' }], { default: 'natural' }),
    ],
    actions: ['create'],
  })
  .createWork('create', '创建翻唱', { title: '{{title}}' })

const manifest: Manifest = app.build()
const action: Action | undefined = manifest.actions[0]
validateManifest({ manifest, action })

plugin('example.hybrid-frontend', '混合页面')
  .hybrid('plugin.py')
  .frontendEntry('frontend/index.html')

const requestOptions = { timeoutMs: 5_000 } satisfies RequestOptions
const hosted: boolean = isHosted()
const contextPromise: Promise<PluginHostContext> = host.getContext()
const customPromise: Promise<{ value: string }> = request('custom', {}, requestOptions)
const workPayload = {
  title: 'TypeScript 页面任务',
  workflow: 'auto_mix',
  params: { pitch: 0, f0_method: 'rmvpe' },
} satisfies CreateWorkPayload
const workPromise = host.createWork(workPayload)
const vueOptions = { loadContext: true } satisfies UsePluginHostOptions
const vueHost: UsePluginHostResult = usePluginHost(vueOptions)
void [hosted, contextPromise, customPromise, workPromise, vueHost]
