// 浏览器开发环境下的 mock 后端：内存态数据 + 模拟转换进度。
// 仅在未运行于 pywebview 时生效。

import type {
  CreateWorkPayload,
  ImportModelPayload,
  ModelDTO,
  SystemStatus,
  WorkDTO,
  PipelineStep,
  MusicSearchResult,
  MusicSongResult,
  MusicDownloadResult,
  DownloadedMusic,
  MusicSource,
  LyricsResult,
  HubTokenResult,
  HubSearchResult,
  HubDownloadResult,
  HubUploadResult,
  HubProgress,
  ModelFramework,
} from './types'

const now = () => new Date().toISOString()
const rid = (p: string) => p + Math.random().toString(36).slice(2, 12)
const fileName = (p: string) => p.split(/[/\\]/).pop() || p

// 浏览器环境下用真实的系统文件选择框（无法拿到完整本地路径，仅用于开发预览）。
function browserPickFile(accept: string): Promise<string | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.style.display = 'none'
    let done = false
    const finish = (val: string | null) => {
      if (done) return
      done = true
      input.remove()
      resolve(val)
    }
    input.onchange = () => finish(input.files?.[0]?.name ?? null)
    // 取消选择时通过窗口重新聚焦兜底
    window.addEventListener(
      'focus',
      () => setTimeout(() => finish(input.files?.[0]?.name ?? null), 400),
      { once: true },
    )
    document.body.appendChild(input)
    input.click()
  })
}

const mockModels: ModelDTO[] = [
  {
    id: 'm1', name: '我的音色 v2', type: 'So-VITS', sample_rate: '44.1kHz', size: '418 MB', imported_at: '06-10',
    main_model: { name: 'G_30000.pth', path: '' }, main_config: { name: 'config.json', path: '' },
    diffusion_model: { name: 'diffusion.pt', path: '' }, diffusion_config: { name: 'diffusion.yaml', path: '' },
  },
  {
    id: 'm2', name: '星野', type: 'So-VITS', sample_rate: '44.1kHz', size: '396 MB', imported_at: '06-08',
    main_model: { name: 'Hoshino_G.pth', path: '' }, main_config: { name: 'config.json', path: '' },
    diffusion_model: { name: 'model_diff.pt', path: '' }, diffusion_config: { name: 'diff.yaml', path: '' },
  },
]
let defaultModelId = 'm1'

// 音乐资源获取的模拟状态（仅浏览器开发环境）
let mockMusicKey = ''
let mockMusicSource = 'wy'
let mockMusicCookie = ''
const mockMusicSources: MusicSource[] = [
  { id: 'wy', name: '网易云音乐', cookie: false },
  { id: 'qq', name: 'QQ音乐', cookie: true },
]
const mockDownloaded: DownloadedMusic[] = []

// 模型站（ModelScope）模拟状态
let mockHubToken = ''
const mockFrameworks: ModelFramework[] = [
  { id: 'so-vits-svc', name: 'So-VITS-SVC' },
  { id: 'rvc', name: 'RVC' },
  { id: 'ddsp-svc', name: 'DDSP-SVC' },
  { id: 'other', name: '其他' },
]
const mockHubModels = [
  { repo_id: 'demo-user/xb-svcb-luotianyi-a1b2c3', name: '洛天依（社区）', type: 'So-VITS', framework: 'so-vits-svc', framework_label: 'So-VITS-SVC', sample_rate: '44.1kHz', author: 'demo-user', has_diffusion: true, url: '#' },
  { repo_id: 'demo-user/xb-svcb-reze-d4e5f6', name: 'Reze（社区）', type: 'RVC', framework: 'rvc', framework_label: 'RVC', sample_rate: '44.1kHz', author: 'demo-user', has_diffusion: false, url: '#' },
]

const baseSteps = (): PipelineStep[] => [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'f0', label: 'F0 提取', status: 'wait' },
  { key: 'infer', label: 'SVC 推理', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]

const multiSteps = (): PipelineStep[] => [
  { key: 'separate', label: '人声分离', status: 'wait' },
  { key: 'split', label: '歌词分割', status: 'wait' },
  { key: 'infer', label: '逐段推理', status: 'wait' },
  { key: 'merge', label: '人声合并', status: 'wait' },
  { key: 'mix', label: '混音合成', status: 'wait' },
]

const mockWorks: WorkDTO[] = [
  { id: 'w1', title: '星辰大海 (AI 翻唱)', model: 'MyVoice_v2.pth', model_id: 'm1', status: 'done', progress: 100, duration: '03:42', format: 'WAV', size: '38 MB', created_at: now(), time: '今天 14:20', steps: baseSteps().map((s) => ({ ...s, status: 'done' })), output: 'demo.wav' },
  { id: 'w2', title: '夜空中最亮的星 (AI 翻唱)', model: 'Hoshino_so-vits.pth', model_id: 'm2', status: 'done', progress: 100, duration: '04:05', format: 'FLAC', size: '42 MB', created_at: now(), time: '今天 13:08', steps: baseSteps().map((s) => ({ ...s, status: 'done' })), output: 'demo.flac' },
  { id: 'w4', title: '起风了 (AI 翻唱)', model: 'Ethereal_so-vits.pth', model_id: 'm5', status: 'done', progress: 100, duration: '05:11', format: 'MP3', size: '11 MB', created_at: now(), time: '昨天', steps: baseSteps().map((s) => ({ ...s, status: 'done' })), output: 'demo.mp3' },
]

function advance(work: WorkDTO) {
  const total = work.steps.length
  let i = 0
  work.status = 'running'
  const tick = () => {
    const prev = work.steps[i - 1]
    if (prev) prev.status = 'done'
    if (i >= total) {
      work.status = 'done'
      work.progress = 100
      work.duration = '03:30'
      work.format = 'WAV'
      work.size = '36 MB'
      work.output = 'output.wav'
      return
    }
    const cur = work.steps[i]
    if (cur) cur.status = 'active'
    work.progress = Math.round((i / total) * 100)
    i += 1
    setTimeout(tick, 900)
  }
  tick()
}

export const mock = {
  getSystemStatus(): SystemStatus {
    return {
      ready: true,
      tools: [
        { key: 'uvr', name: 'Ultimate Vocal Remover', desc: '人声 / 伴奏分离引擎，自动提取翻唱所需干声', version: 'v5.6', status: '已就绪', ok: true },
        { key: 'ffmpeg', name: 'ffmpeg', desc: '音频转码 / 重采样 / 剪辑，统一格式与采样率', version: 'v6.1', status: '已就绪', ok: true },
        { key: 'svc', name: 'SVC 推理引擎', desc: '加载用户 SVC 模型进行歌声转换推理', version: 'torch', status: 'cuda', ok: true },
      ],
    }
  },
  listModels(): ModelDTO[] {
    return [...mockModels]
  },
  getDefaultModel(): string | null {
    return defaultModelId
  },
  pickModelFile(): Promise<string | null> {
    return browserPickFile('.pth,.pt,.onnx,.ckpt')
  },
  pickConfigFile(): Promise<string | null> {
    return browserPickFile('.json,.yaml,.yml')
  },
  importModel(payload: ImportModelPayload): ModelDTO | null {
    if (!payload.main_model || !payload.main_config) return null
    const m: ModelDTO = {
      id: rid('mdl_'),
      name: payload.name || fileName(payload.main_model).replace(/\.[^.]+$/, ''),
      type: fileName(payload.main_model).toLowerCase().includes('rvc') ? 'RVC' : 'So-VITS',
      sample_rate: '44.1kHz',
      size: '400 MB',
      imported_at: new Date().toISOString().slice(5, 10),
      main_model: { name: fileName(payload.main_model), path: payload.main_model },
      main_config: { name: fileName(payload.main_config), path: payload.main_config },
      diffusion_model: payload.diffusion_model
        ? { name: fileName(payload.diffusion_model), path: payload.diffusion_model }
        : null,
      diffusion_config: payload.diffusion_config
        ? { name: fileName(payload.diffusion_config), path: payload.diffusion_config }
        : null,
    }
    mockModels.unshift(m)
    return m
  },
  setDefaultModel(id: string): boolean {
    if (mockModels.some((m) => m.id === id)) {
      defaultModelId = id
      return true
    }
    return false
  },
  deleteModel(id: string): boolean {
    const idx = mockModels.findIndex((m) => m.id === id)
    if (idx >= 0) {
      mockModels.splice(idx, 1)
      if (defaultModelId === id) defaultModelId = mockModels[0]?.id ?? ''
      return true
    }
    return false
  },
  pickAudioFile(): string | null {
    return `C:/music/示例歌曲_${Date.now()}.mp3`
  },
  listWorks(): WorkDTO[] {
    return mockWorks.map((w) => ({ ...w, steps: w.steps.map((s) => ({ ...s })) }))
  },
  getWork(id: string): WorkDTO | null {
    const w = mockWorks.find((x) => x.id === id)
    return w ? { ...w, steps: w.steps.map((s) => ({ ...s })) } : null
  },
  createWork(payload: CreateWorkPayload): WorkDTO {
    const isMulti = payload.mode === 'multi'
    const model = mockModels.find((m) => m.id === (payload.model_id || defaultModelId))
    const rawTitle = payload.title || (payload.source_path ? payload.source_path.split(/[/\\]/).pop()?.replace(/\.[^.]+$/, '') : '') || '未命名翻唱'
    const work: WorkDTO = {
      id: rid('wrk_'),
      title: `${rawTitle} (${isMulti ? '混合翻唱' : 'AI 翻唱'})`,
      model: isMulti ? `多模型混合（${payload.models?.length || 0} 个）` : (model?.name || '默认模型'),
      model_id: payload.models?.[0]?.model_id || model?.id || '',
      status: 'queue',
      progress: 0,
      duration: '—',
      format: '—',
      size: '—',
      created_at: now(),
      time: '刚刚',
      source_path: payload.source_path,
      params: payload.params,
      mode: isMulti ? 'multi' : 'single',
      segments: payload.segments,
      steps: isMulti ? multiSteps() : baseSteps(),
    }
    mockWorks.unshift(work)
    advance(work)
    return { ...work, steps: work.steps.map((s) => ({ ...s })) }
  },
  retryWork(id: string): boolean {
    const w = mockWorks.find((x) => x.id === id)
    if (!w) return false
    w.steps = baseSteps()
    w.progress = 0
    advance(w)
    return true
  },
  renameWork(id: string, title: string): boolean {
    const w = mockWorks.find((x) => x.id === id)
    if (!w || !title.trim()) return false
    w.title = title.trim()
    return true
  },
  deleteWork(id: string): boolean {
    const idx = mockWorks.findIndex((w) => w.id === id)
    if (idx >= 0) {
      mockWorks.splice(idx, 1)
      return true
    }
    return false
  },
  openWorkLog(id: string): boolean {
    console.info('[mock] openWorkLog', id)
    return false
  },
  openPath(path: string): boolean {
    console.info('[mock] openPath', path)
    return false
  },
  getWorkAudio(id: string): string {
    console.info('[mock] getWorkAudio', id)
    return ''
  },
  getStemAudio(id: string, kind: string): string {
    console.info('[mock] getStemAudio', id, kind)
    return ''
  },
  exportWork(id: string): string {
    console.info('[mock] exportWork', id)
    return ''
  },

  // ---- 音乐资源获取（浏览器开发环境模拟）----
  getMusicApiKey(): string {
    return mockMusicKey
  },
  setMusicApiKey(key: string): boolean {
    mockMusicKey = key.trim()
    return true
  },
  listMusicSources(): MusicSource[] {
    return [...mockMusicSources]
  },
  getMusicSource(): string {
    return mockMusicSource
  },
  setMusicSource(source: string): boolean {
    if (mockMusicSources.some((s) => s.id === source)) {
      mockMusicSource = source
      return true
    }
    return false
  },
  getMusicCookie(): string {
    return mockMusicCookie
  },
  setMusicCookie(cookie: string): boolean {
    mockMusicCookie = cookie.trim()
    return true
  },
  searchMusic(msg: string, g = 13, source = mockMusicSource): MusicSearchResult {
    if (!mockMusicKey) return { ok: false, error: '未配置 API Key，请先在「API 设置」中填写' }
    if (!msg.trim()) return { ok: false, error: '请输入搜索关键词' }
    const songs = Array.from({ length: Math.min(g, 8) }, (_, i) => ({
      n: i + 1,
      name: `${msg}${i === 0 ? '' : `（版本 ${i + 1}）`}`,
      singer: ['洛天依', '国风堂', '云梦', 'Reze'][i % 4] as string,
      album: msg,
      pay: source === 'qq' && i % 3 === 0 ? '[收费]' : '',
    }))
    return { ok: true, keyword: msg, source, songs }
  },
  getMusicSong(msg: string, n: number, _source = mockMusicSource): MusicSongResult {
    void _source
    if (!mockMusicKey) return { ok: false, error: '未配置 API Key' }
    return {
      ok: true,
      song: {
        name: `${msg}`,
        singer: '示例歌手',
        album: msg,
        title: `${msg} — 示例歌手`,
        picture: '',
        url: '',
        musicurl: '',
        lrc: `[00:00.00]${msg}（第 ${n} 首）\n[00:03.00]浏览器开发环境为模拟数据`,
      },
    }
  },
  downloadMusic(msg: string, n: number, _source = mockMusicSource): MusicDownloadResult {
    void _source
    if (!mockMusicKey) return { ok: false, error: '未配置 API Key' }
    const name = `${msg} - 示例歌手${n > 1 ? ` (${n})` : ''}`
    const item: DownloadedMusic = { name, path: `C:/music/${name}.mp3`, size: '8.2 MB' }
    mockDownloaded.unshift(item)
    return { ok: true, path: item.path, name: item.name, size: item.size }
  },
  listMusic(): DownloadedMusic[] {
    return [...mockDownloaded]
  },
  deleteMusic(path: string): boolean {
    const idx = mockDownloaded.findIndex((m) => m.path === path)
    if (idx >= 0) {
      mockDownloaded.splice(idx, 1)
      return true
    }
    return false
  },
  getMusicLyrics(msg: string, n: number, _source = mockMusicSource): LyricsResult {
    void n
    void _source
    if (!mockMusicKey) return { ok: false, error: '未配置 API Key' }
    const lines = Array.from({ length: 12 }, (_, i) => ({
      time: 8 + i * 12.5,
      text: `${msg} 第 ${i + 1} 句歌词（模拟）`,
    }))
    return { ok: true, lines, name: msg, singer: '示例歌手' }
  },
  getAudioDuration(path: string): number {
    void path
    return 165
  },

  // ---- 模型站（浏览器开发环境模拟）----
  getModelscopeToken(): string {
    return mockHubToken
  },
  setModelscopeToken(token: string): boolean {
    mockHubToken = token.trim()
    return true
  },
  verifyModelscopeToken(token?: string): HubTokenResult {
    const t = (token ?? mockHubToken).trim()
    if (!t) return { ok: false, error: '未填写 ModelScope 访问令牌' }
    return { ok: true, username: 'demo-user', email: 'demo@example.com' }
  },
  modelhubUploadReady(): boolean {
    return true
  },
  listModelFrameworks(): ModelFramework[] {
    return [...mockFrameworks]
  },
  hubSearchModels(query = '', page = 1, framework?: string): HubSearchResult {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const fw = (framework || '').trim().toLowerCase()
    const items = mockHubModels.filter((m) => {
      const hay = `${m.name} ${m.repo_id}`.toLowerCase()
      const hit = tokens.every((t) => hay.includes(t))
      return hit && (!fw || m.framework === fw)
    })
    return { ok: true, items, page }
  },
  hubDownloadModel(repoId: string): HubDownloadResult {
    const hit = mockHubModels.find((m) => m.repo_id === repoId)
    if (!hit) return { ok: false, error: '未找到该模型' }
    const m: ModelDTO = {
      id: rid('mdl_'),
      name: hit.name,
      type: hit.type,
      sample_rate: hit.sample_rate,
      size: '400 MB',
      imported_at: new Date().toISOString().slice(5, 10),
      main_model: { name: 'G_30000.pth', path: '' },
      main_config: { name: 'config.json', path: '' },
      diffusion_model: hit.has_diffusion ? { name: 'diffusion.pt', path: '' } : null,
      diffusion_config: hit.has_diffusion ? { name: 'diffusion.yaml', path: '' } : null,
    }
    mockModels.unshift(m)
    return { ok: true, model: m }
  },
  hubUploadModel(modelId: string, name?: string, framework?: string): HubUploadResult {
    void framework
    if (!mockHubToken) return { ok: false, error: '未填写 ModelScope 访问令牌' }
    const model = mockModels.find((m) => m.id === modelId)
    if (!model) return { ok: false, error: '本地模型不存在' }
    const repo = `demo-user/xb-svcb-${(name || model.name).toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${Math.random().toString(36).slice(2, 8)}`
    return { ok: true, url: '#', repo_id: repo }
  },

  hubProgress(key: string): HubProgress {
    const cur = (mockProgress[key] ?? 0) + 20
    mockProgress[key] = cur
    const pct = Math.min(100, cur)
    return {
      phase: pct >= 100 ? 'done' : 'upload',
      pct,
      msg: pct >= 100 ? '完成' : `处理中 ${pct}%`,
      done: pct,
      total: 100,
    }
  },
}

const mockProgress: Record<string, number> = {}
