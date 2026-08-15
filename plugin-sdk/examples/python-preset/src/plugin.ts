import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('example.python-preset', 'Python 翻唱预设', '1.0.0')
  .python('plugin.py')
  .description('纯 Python 插件：在每次创建翻唱前调整缺失的默认参数。')
  .author('XB-SVCB Plugin SDK')
  .permission('filesystem.data')

await writeManifest(app, '.')
