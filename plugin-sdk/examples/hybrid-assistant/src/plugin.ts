import { fields, plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('example.hybrid-assistant', '混合翻唱助手', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .description('前端表单收集参数，Python 动作生成翻唱任务。')
  .author('XB-SVCB Plugin SDK')
  .permission('filesystem.data')
  .page('start', '智能翻唱', {
    fields: [
      fields.text('source_path', '源音频路径', { placeholder: 'D:/Music/song.wav' }),
      fields.text('model_id', '模型 ID', { placeholder: 'model_xxx' }),
      fields.text('title', '标题', { default: '混合插件翻唱' }),
      fields.select('style', '声音风格', [
        { label: '自然', value: 'natural' },
        { label: '明亮', value: 'bright' },
      ], { default: 'natural' }),
    ],
    actions: ['create'],
  })
  .pythonAction('create', '创建翻唱', 'create_cover')

await writeManifest(app, '.')
