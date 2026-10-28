import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  applyStoredLocaleBeforeMount,
  setLocale,
  translate,
  translateUiText,
} from '@/i18n'

describe('application localization', () => {
  beforeEach(() => {
    localStorage.clear()
    setLocale('zh-CN')
  })

  it('translates keyed navigation messages into English and Japanese', () => {
    setLocale('en-US')
    expect(translate('nav.cover')).toBe('AI Cover')
    expect(translate('header.noResult', { query: 'demo' })).toBe('No results for “demo”')

    setLocale('ja-JP')
    expect(translate('nav.editor')).toBe('音声編集')
    expect(translate('language.title')).toBe('表示言語')
  })

  it('only translates complete known UI phrases and preserves whitespace', () => {
    setLocale('en-US')
    expect(translateUiText('  选择模型  ')).toBe('  Choose Model  ')
    expect(translateUiText('用户作品名称')).toBe('用户作品名称')
    expect(translateUiText('// 我的作品')).toBe('// My Works')
  })

  it('translates secondary editor copy and dynamic messages', () => {
    setLocale('en-US')
    expect(translateUiText('删除音轨')).toBe('Delete Track')
    expect(translateUiText('已导入 3 个音频资源')).toBe('Imported 3 audio files')
    expect(translateUiText('确定删除「demo」吗？')).toBe('Delete “demo”?')

    setLocale('ja-JP')
    expect(translateUiText('删除音轨')).toBe('トラックを削除')
    expect(translateUiText('已导入 3 个音频资源')).toBe('3件の音声をインポートしました')
    expect(translateUiText('插件包超过 20 MB 限制')).toBe('Plugin package exceeds the 20 MB limit')
  })

  it('translates editor tabs, plugin status, and multi-model parameters', () => {
    setLocale('en-US')
    expect(['片段', '效果', '人声', '重推理', 'AI 增强'].map((item) => translateUiText(item)))
      .toEqual(['Clip', 'Effects', 'Vocal', 'Re-inference', 'AI Enhance'])
    expect(translateUiText('扩展能力已接入当前工作流')).toBe('Extensions are connected to the current workflow')
    expect(['变调', '保护轮次', '扩散步数', '采样步数', '扩散占比', '共振峰偏移', '参考音频', '清辅音保护', '检索比率', '说话人', '设备', '版本'].map((item) => translateUiText(item)))
      .toEqual(['Pitch Shift', 'Protection Rounds', 'Diffusion Steps', 'Sampling Steps', 'Diffusion Ratio', 'Formant Shift', 'Reference Audio', 'Consonant Protection', 'Index Rate', 'Speaker', 'Device', 'Version'])
  })

  it('translates lyric assignment, timeline editing, and editor lyric controls', () => {
    setLocale('en-US')
    expect(translateUiText('按歌名在线获取，或导入带时间轴的歌词文件（.lrc），再为每句指派演唱模型'))
      .toContain('import a timed .lrc file')
    expect(translateUiText('共 52 句；未知音频时长，建议核对偏移'))
      .toBe('52 phrases; audio duration is unknown. Check the offset.')
    expect(['时间轴编辑', '放大编辑', '整体偏移', '普通 TXT 每行一句，或粘贴带时间戳的 LRC', '自动切句'].map((item) => translateUiText(item)))
      .toEqual(['Timeline Editor', 'Expand Editor', 'Overall Offset', 'Plain TXT: one phrase per line, or paste timestamped LRC', 'Auto Split'])

    setLocale('ja-JP')
    expect(translateUiText('歌词分句指派')).toBe('歌詞フレーズごとに割り当て')
    expect(translateUiText('共 52 句；未知音频时长，建议核对偏移'))
      .toBe('全52フレーズ。音声の長さが不明なため、オフセットを確認してください')
    expect(translateUiText('普通 TXT 每行一句，或粘贴带时间戳的 LRC'))
      .toContain('タイムスタンプ付きLRC')
    expect([translateUiText('独唱基础'), translateUiText('主唱、人声、伴奏三轨结构')])
      .toEqual(['ソロ基本構成', 'メイン、参照ボーカル、伴奏の3トラック構成'])
  })

  it('translates asynchronous integrated-tool descriptions and statuses', () => {
    setLocale('en-US')
    expect(translateUiText('可选的 PyMSS 音乐源分离引擎，模型可从 PyMSS 模型站下载'))
      .toContain('PyMSS Model Hub')
    expect(translateUiText('环境已就绪 · 模型未下载（请在模型管理页下载）'))
      .toBe('Environment ready · Model not downloaded (download it in Model Management)')
    expect(translateUiText('加载 SeedVC checkpoint + 目标参考音频进行 zero-shot 歌声转换'))
      .toContain('target reference audio')

    setLocale('ja-JP')
    expect(translateUiText('模型目录未就绪')).toBe('モデルディレクトリが準備されていません')
    expect(translateUiText('加载 SeedVC checkpoint + 目标参考音频进行 zero-shot 歌声转换'))
      .toContain('ゼロショット歌声変換')
    expect(translateUiText('加载用户 RVC 模型（.pth + 可选 .index）进行歌声转换推理'))
      .toContain('ユーザーのRVCモデル')
  })

  it('translates API documentation, model hub, and re-inference log copy', () => {
    setLocale('en-US')
    expect(translateUiText('典型流程：上传音频、读取模型、创建任务、轮询状态、下载成品。'))
      .toContain('Typical flow')
    expect(translateUiText('PyMSS 音乐源分离模型站')).toBe('PyMSS Source Separation Model Hub')
    expect(translateUiText('片段已替换，已移除 2 个插件效果避免污染干声'))
      .toContain('removed 2 plugin effects')

    setLocale('ja-JP')
    expect(translateUiText('所有受保护接口均需 X-API-Key')).toContain('X-API-Key')
    expect(translateUiText('模型详情')).toBe('モデル詳細')
    expect(translateUiText('正在提交重推理任务')).toBe('再推論タスクを送信中')
    expect(translateUiText('=== 重推理成功 ===')).toBe('=== 再推論に成功 ===')
  })

  it('translates notification status text and relative times', () => {
    setLocale('en-US')
    expect(translateUiText('翻唱完成，可试听 / 导出')).toBe('Cover complete, preview / export available')
    expect(translateUiText('处理中 42%')).toBe('Processing 42%')
    expect(translateUiText('昨天 16:00')).toBe('Yesterday 16:00')

    setLocale('ja-JP')
    expect(translateUiText('处理中 42%')).toBe('処理中 42%')
    expect(translateUiText('昨天 16:00')).toBe('昨日 16:00')
  })

  it('persists the selected locale and updates the document language', async () => {
    setLocale('ja-JP')
    await nextTick()
    expect(localStorage.getItem('xb-locale')).toBe('ja-JP')
    expect(document.documentElement.lang).toBe('ja-JP')

    applyStoredLocaleBeforeMount()
    expect(document.documentElement.dataset.locale).toBe('ja-JP')
  })
})
