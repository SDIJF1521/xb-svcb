import { fields, plugin, validateManifest, writeManifest } from '@xb-svcb/plugin-sdk'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const definition = plugin('example.hello', '我的第一个翻唱助手', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('用一组简单参数创建一条 AI 翻唱任务。')
  .author('Your Name')
  .beforeCreate({ f0_method: 'rmvpe', device: 'auto' })
  .page('start', '快速开始', {
    description: '填写源音频和模型信息，然后创建翻唱。',
    fields: [
      fields.text('source_path', '源音频路径', { placeholder: 'D:/Music/song.wav', help: '请填写本机音频文件的完整路径。' }),
      fields.text('model_id', '模型 ID', { placeholder: 'model_xxx', help: '可以从模型库或翻唱页找到模型 ID。' }),
      fields.text('title', '作品标题', { default: '我的第一首翻唱' }),
      fields.number('pitch', '升降调', { default: 0, help: '半音数，0 表示不变调。' }),
    ],
    actions: ['create'],
  })
  .createWork('create', '开始翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: { pitch: '{{pitch}}' },
  })

const result = validateManifest(definition)
if (!result.ok) throw new Error(result.errors.join('\n'))
const sourceDirectory = fileURLToPath(new URL('.', import.meta.url))
const directory = join(sourceDirectory, '..')
await writeManifest(definition, directory)
console.log('xb-svcb-plugin.json 已生成')
