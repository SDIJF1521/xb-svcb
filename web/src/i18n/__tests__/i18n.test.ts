import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  applyStoredLocaleBeforeMount,
  setLocale,
  translate,
  translateLogText,
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

  it('keeps the Japanese cover workspace workflow fully localized', () => {
    setLocale('ja-JP')
    expect([
      '自动输出人声 + 伴奏的完整成品',
      '先自动出成品，再进入编辑器微调',
      '不启动自动推理，直接创建编辑工程',
      '提取干声与伴奏（UVR / PyMSS）',
      'DeepFilterNet3 清理分离伪影并保护高频细节',
      '分析音高曲线',
      '加载模型进行歌声转换',
    ].map((item) => translateUiText(item))).toEqual([
      'ボーカルと伴奏を自動でミックスして完成音源を出力',
      '自動生成後、エディターで細かく調整',
      '自動推論を行わず、編集プロジェクトを直接作成',
      'ボーカルと伴奏を抽出（UVR / PyMSS）',
      'DeepFilterNet3で分離ノイズを除去し、高域のディテールを保護',
      'ピッチカーブを解析',
      'モデルを読み込んで歌声を変換',
    ])
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

  it('translates realtime voice changer, PyMSS and VB-CABLE copy', () => {
    const cableNote =
      'VB-CABLE：输入用麦克风时，输出可直接选“CABLE Output”；应用会自动写入同一条虚拟线的 CABLE Input，OBS/语音软件仍选择 CABLE Output 接收。'

    setLocale('en-US')
    expect(translateUiText('混合音频 · 保留伴奏')).toBe('Mixed Audio · Keep Instrumental')
    expect(translateUiText('纯人声 · 直播低延迟')).toBe('Dry Vocal · Live Low Latency')
    expect(translateUiText('人声分离引擎')).toBe('Vocal Separation Engine')
    expect(translateUiText('端到端延迟')).toBe('End-to-end Latency')
    expect(translateUiText('1.50 秒')).toBe('1.50 s')
    expect(translateUiText('1 块 · 0.50 秒')).toBe('Blocks 1 · 0.50 s')
    expect(translateUiText('实时播放已停止')).toBe('Realtime playback stopped')
    expect(translateUiText('实时音频来源')).toBe('Realtime Audio Source')
    expect(translateUiText('+2 半音')).toBe('+2 semitones')
    expect(translateUiText('4 步')).toBe('4 steps')
    expect(translateUiText('自动 · v2')).toBe('Auto · v2')
    expect(translateUiText(cableNote)).toContain('CABLE Output')
    expect(translateUiText(cableNote)).not.toBe(cableNote)

    setLocale('ja-JP')
    expect(translateUiText('纯人声 · 直播低延迟')).toBe('ドライボーカル · 低遅延ライブ')
    expect(translateUiText('处理负载')).toBe('処理負荷')
    expect(translateUiText('1.50 秒')).toBe('1.50秒')
    expect(translateUiText('1 块 · 0.50 秒')).toBe('ブロック 1 · 0.50秒')
    expect(translateUiText('实时播放已停止')).toBe('リアルタイム再生を停止しました')
    expect(translateUiText('实时音频来源')).toBe('リアルタイム音声ソース')
    expect(translateUiText('+2 半音')).toBe('+2半音')
    expect(translateUiText('4 步')).toBe('4ステップ')
  })

  it('persists the selected locale and updates the document language', async () => {
    setLocale('ja-JP')
    await nextTick()
    expect(localStorage.getItem('xb-locale')).toBe('ja-JP')
    expect(document.documentElement.lang).toBe('ja-JP')

    applyStoredLocaleBeforeMount()
    expect(document.documentElement.dataset.locale).toBe('ja-JP')
  })

  it('localizes backend run logs line by line and keeps the timestamp', () => {
    const log = [
      '[12:00:00] 源文件: C:/music/a.wav | 时长: 12.3s | 设备: cuda:0',
      '[12:00:01]   模型推理完成',
      '[12:00:02] 任务完成 ✅',
      '[12:00:02] 本行没有对应译文',
    ].join('\n')

    setLocale('en-US')
    const en = translateLogText(log).split('\n')
    expect(en[0]).toBe('[12:00:00] Source: C:/music/a.wav | Duration: 12.3s | Device: cuda:0')
    expect(en[1]).toBe('[12:00:01]   Model inference complete')
    expect(en[2]).toBe('[12:00:02] Task complete ✅')
    // 没有词条的行原样保留，不影响可读性
    expect(en[3]).toBe('[12:00:02] 本行没有对应译文')

    setLocale('ja-JP')
    const ja = translateLogText(log).split('\n')
    expect(ja[1]).toBe('[12:00:01]   モデル推論が完了しました')
    expect(ja[2]).toBe('[12:00:02] タスク完了 ✅')
  })

  it('leaves simplified Chinese logs untouched', () => {
    setLocale('zh-CN')
    const log = '[12:00:01]   模型推理完成'
    expect(translateLogText(log)).toBe(log)
  })

  it('localizes the workflow run log header and step lines', () => {
    const log = [
      '=== My Mix (自定义工作流) ===',
      '开始时间: 2026-11-13T21:33:39',
      '工作流: My Flow',
      '[21:33:39] [1/11] 输入音频 开始',
      '[21:33:39]   源音频已统一转码: source.wav',
      '[21:33:39] [2/11] 人声分离 开始',
    ].join('\n')

    setLocale('en-US')
    const en = translateLogText(log).split('\n')
    expect(en[0]).toBe('=== My Mix (custom workflow) ===')
    expect(en[1]).toBe('Started at: 2026-11-13T21:33:39')
    // 工作流名是用户数据，不翻译
    expect(en[2]).toBe('Workflow: My Flow')
    expect(en[3]).toBe('[21:33:39] [1/11] Input audio started')
    expect(en[4]).toBe('[21:33:39]   Source audio transcoded: source.wav')
    expect(en[5]).toBe('[21:33:39] [2/11] Vocal separation started')

    setLocale('ja-JP')
    const ja = translateLogText(log).split('\n')
    expect(ja[0]).toBe('=== My Mix（カスタムワークフロー）===')
    expect(ja[1]).toBe('開始時間：2026-11-13T21:33:39')
  })

  it('localizes the workflow canvas hints and toasts', () => {
    setLocale('en-US')
    expect(
      translateUiText(
        '点击节点右上角 ⚙ 打开设置 · 右键菜单可复制 / 粘贴 / 断开连线 · 点击连线可删除',
      ),
    ).toContain('to delete it')
    expect(translateUiText('已断开 2 条连线')).toBe('Disconnected 2 connections')
    expect(translateUiText('已按乐器生成 3 条音轨，可直接播放或调整音量/效果')).toBe(
      'Generated 3 instrument tracks; play them directly or adjust volume and effects',
    )
    expect(translateUiText('1.25x 速度')).toBe('1.25x speed')
    // 作品名 / 模型名属于用户数据，不能被改写
    expect(translateUiText('确定删除「My Song」吗？')).toBe('Delete “My Song”?')

    setLocale('ja-JP')
    expect(translateUiText('已保存工作流')).toBe('保存済みワークフロー')
    expect(translateUiText('打开设置')).toBe('設定を開く')
  })
})
