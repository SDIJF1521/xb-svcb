// 浏览器开发环境下的 mock 后端：内存态数据 + 模拟转换进度。
// 仅在未运行于 pywebview 时生效。

import type {
  CreateWorkflow,
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
  HubStartResult,
  HubJob,
  ModelFramework,
  EditorProject,
  EditorProjectSummary,
  EditorWaveform,
  EditorRerunResult,
} from './types'

const now = () => new Date().toISOString()
const rid = (p: string) => p + Math.random().toString(36).slice(2, 12)
const fileName = (p: string) => p.split(/[/\\]/).pop() || p
const editorFormat = (fmt = 'wav') => {
  const value = fmt.trim().toLowerCase().replace(/^\./, '')
  return ['wav', 'mp3', 'flac'].includes(value) ? value : 'wav'
}

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
  { key: 'infer', label: '模型推理', status: 'wait' },
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

const cloneProject = (p: EditorProject): EditorProject => JSON.parse(JSON.stringify(p)) as EditorProject
const mockEditorProjects: EditorProject[] = []
const mockEditorHistory: Record<string, EditorProject[]> = {}
const mockEditorFuture: Record<string, EditorProject[]> = {}
const mockMinRerunClipSeconds = 1
const mockWorkflowKeys: CreateWorkflow[] = [
  'auto_mix',
  'auto_vocal_merge',
  'manual_vocal_merge',
  'auto_then_editor',
  'full_manual_editor',
]
const mockVocalMergeWorkflows: CreateWorkflow[] = ['auto_vocal_merge', 'manual_vocal_merge']

function normalizeMockWorkflow(value: unknown, isMulti: boolean): CreateWorkflow {
  const workflow = mockWorkflowKeys.includes(value as CreateWorkflow)
    ? value as CreateWorkflow
    : 'auto_mix'
  return !isMulti && mockVocalMergeWorkflows.includes(workflow) ? 'auto_mix' : workflow
}

function projectDuration(project: EditorProject): number {
  return Math.max(0.05, ...project.tracks.flatMap((t) => t.clips.map((c) => c.end || 0)))
}

function makeEditorProject(title: string, source = 'C:/music/demo.wav'): EditorProject {
  const id = rid('edt_')
  const created = now()
  return {
    id,
    title,
    duration: 160,
    sample_rate: 44100,
    waveform_cache: {},
    metadata: { source_path: source, mode: 'mock' },
    created_at: created,
    updated_at: created,
    tracks: [
      {
        id: rid('trk_'),
        name: '人声轨',
        type: 'vocal',
        volume: 1,
        mute: false,
        locked: false,
        clips: [
          { id: rid('clp_'), name: 'verse vocal', start: 8, end: 42, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: false, fade_in: 0.08, fade_out: 0.08, channel: 'stereo', metadata: {} },
          { id: rid('clp_'), name: 'chorus vocal', start: 48, end: 84, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: false, fade_in: 0.08, fade_out: 0.08, channel: 'stereo', metadata: {} },
        ],
      },
      {
        id: rid('trk_'),
        name: 'BGM 轨',
        type: 'bgm',
        volume: 0.86,
        mute: false,
        locked: false,
        clips: [
          { id: rid('clp_'), name: 'instrumental', start: 0, end: 160, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: true, fade_in: 0, fade_out: 0, channel: 'stereo', metadata: {} },
        ],
      },
      {
        id: rid('trk_'),
        name: 'AI 转换轨',
        type: 'ai',
        volume: 1,
        mute: false,
        locked: false,
        clips: [
          { id: rid('clp_'), name: 'AI take', start: 88, end: 126, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: false, fade_in: 0.06, fade_out: 0.06, channel: 'stereo', metadata: {} },
        ],
      },
    ],
  }
}

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
        { key: 'svc', name: 'So-VITS-SVC 推理引擎', desc: '加载用户 So-VITS-SVC 模型进行歌声转换推理', version: 'torch', status: 'cuda', ok: true },
        { key: 'rvc', name: 'RVC 推理引擎', desc: '加载用户 RVC 模型（.pth + 可选 .index）进行歌声转换推理', version: 'rvc-python', status: 'cuda', ok: true },
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
  pickIndexFile(): Promise<string | null> {
    return browserPickFile('.index')
  },
  importModel(payload: ImportModelPayload): ModelDTO | null {
    if (!payload.main_model) return null
    const framework = payload.framework || 'so-vits-svc'
    const isRvc = framework === 'rvc'
    if (!isRvc && !payload.main_config) return null
    const m: ModelDTO = {
      id: rid('mdl_'),
      name: payload.name || fileName(payload.main_model).replace(/\.[^.]+$/, ''),
      type: isRvc ? 'RVC' : 'So-VITS',
      framework,
      sample_rate: '44.1kHz',
      size: '400 MB',
      imported_at: new Date().toISOString().slice(5, 10),
      main_model: { name: fileName(payload.main_model), path: payload.main_model },
      main_config: payload.main_config
        ? { name: fileName(payload.main_config), path: payload.main_config }
        : { name: '', path: '' },
      diffusion_model: payload.diffusion_model
        ? { name: fileName(payload.diffusion_model), path: payload.diffusion_model }
        : null,
      diffusion_config: payload.diffusion_config
        ? { name: fileName(payload.diffusion_config), path: payload.diffusion_config }
        : null,
      index_file: payload.index_file
        ? { name: fileName(payload.index_file), path: payload.index_file }
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
    const workflow = normalizeMockWorkflow(payload.workflow, isMulti)
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
      workflow,
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
    w.steps = w.mode === 'multi' ? multiSteps() : baseSteps()
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
  searchMusic(msg: string, page = 1, pageSize = 15, source = mockMusicSource): MusicSearchResult {
    if (!mockMusicKey) return { ok: false, error: '未配置 API Key，请先在「API 设置」中填写' }
    if (!msg.trim()) return { ok: false, error: '请输入搜索关键词' }
    const total = 23 // 模拟全站约 23 条结果
    const g = Math.min(total, page * pageSize)
    const songs = Array.from({ length: g }, (_, i) => ({
      n: i + 1,
      name: `${msg}${i === 0 ? '' : `（版本 ${i + 1}）`}`,
      singer: ['洛天依', '国风堂', '云梦', 'Reze'][i % 4] as string,
      album: msg,
      pay: source === 'qq' && i % 3 === 0 ? '[收费]' : '',
    }))
    return { ok: true, keyword: msg, source, songs, page, page_size: pageSize, has_more: g < total }
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
  hubSearchModels(query = '', page = 1, framework?: string, pageSize = 12): HubSearchResult {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const fw = (framework || '').trim().toLowerCase()
    const all = mockHubModels.filter((m) => {
      const hay = `${m.name} ${m.repo_id}`.toLowerCase()
      const hit = tokens.every((t) => hay.includes(t))
      return hit && (!fw || m.framework === fw)
    })
    const startIdx = (page - 1) * pageSize
    const items = all.slice(startIdx, startIdx + pageSize)
    return { ok: true, items, page, page_size: pageSize, has_more: startIdx + pageSize < all.length }
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

  hubStartDownload(repoId: string): HubStartResult {
    const key = `dl:${repoId}`
    mockProgress[key] = 0
    mockJobs[key] = {
      key,
      kind: 'download',
      title: repoId,
      status: 'running',
      pct: 0,
      msg: '排队中…',
      phase: 'start',
      created_at: new Date().toISOString(),
    }
    return { ok: true, key }
  },
  hubStartUpload(modelId: string, name?: string, framework?: string): HubStartResult {
    void framework
    if (!mockHubToken) return { ok: false, error: '未填写 ModelScope 访问令牌' }
    const model = mockModels.find((m) => m.id === modelId)
    const key = `ul:${modelId}`
    mockProgress[key] = 0
    mockJobs[key] = {
      key,
      kind: 'upload',
      title: name || model?.name || modelId,
      status: 'running',
      pct: 0,
      msg: '排队中…',
      phase: 'start',
      created_at: new Date().toISOString(),
    }
    return { ok: true, key }
  },
  hubListJobs(): HubJob[] {
    // 每次轮询推进进度，到 100% 标记完成（下载完成时模拟导入一条本地模型）
    for (const key of Object.keys(mockJobs)) {
      const job = mockJobs[key]!
      if (job.status !== 'running') continue
      const cur = Math.min(100, (mockProgress[key] ?? 0) + 20)
      mockProgress[key] = cur
      job.pct = cur
      job.msg = cur >= 100 ? '完成' : `处理中 ${cur}%`
      job.phase = cur >= 100 ? 'done' : job.kind
      if (cur >= 100) {
        job.status = 'done'
        if (job.kind === 'download') {
          const m: ModelDTO = {
            id: rid('mdl_'),
            name: job.title.split('/').pop() || job.title,
            type: 'So-VITS',
            sample_rate: '44.1kHz',
            size: '400 MB',
            imported_at: new Date().toISOString().slice(5, 10),
            main_model: { name: 'G_30000.pth', path: '' },
            main_config: { name: 'config.json', path: '' },
            diffusion_model: null,
            diffusion_config: null,
          }
          mockModels.unshift(m)
          job.result = { model: m }
        }
      }
    }
    return Object.values(mockJobs).sort((a, b) =>
      String(b.created_at).localeCompare(String(a.created_at)),
    )
  },
  hubClearJob(key: string): boolean {
    delete mockJobs[key]
    delete mockProgress[key]
    return true
  },

  // ---- 音频编辑器（浏览器开发环境模拟）----
  listEditorProjects(): EditorProjectSummary[] {
    return mockEditorProjects.map((p) => ({
      id: p.id,
      title: p.title,
      duration: p.duration,
      tracks: p.tracks.length,
      updated_at: p.updated_at,
    }))
  },
  getEditorProject(projectId: string): EditorProject | null {
    const p = mockEditorProjects.find((x) => x.id === projectId)
    return p ? cloneProject(p) : null
  },
  deleteEditorProject(projectId: string): boolean {
    const idx = mockEditorProjects.findIndex((p) => p.id === projectId)
    if (idx < 0) return false
    mockEditorProjects.splice(idx, 1)
    delete mockEditorHistory[projectId]
    delete mockEditorFuture[projectId]
    return true
  },
  createEditorProjectFromAudio(path: string, title?: string): EditorProject | null {
    if (!path) return null
    const project = makeEditorProject(title || fileName(path).replace(/\.[^.]+$/, ''), path)
    mockEditorProjects.unshift(project)
    mockEditorHistory[project.id] = []
    mockEditorFuture[project.id] = []
    return cloneProject(project)
  },
  createEditorProjectFromWork(workId: string): EditorProject | null {
    const work = mockWorks.find((w) => w.id === workId)
    if (!work) return null
    let project: EditorProject
    if (work.mode === 'multi' && work.segments?.length) {
      const created = now()
      const source = work.source_path || work.output || 'demo.wav'
      const duration = Math.max(160, ...work.segments.map((s) => s.end || 0))
      const vocalExport = work.workflow === 'manual_vocal_merge'
      const orderedSegments = [...work.segments].sort((a, b) => (a.start || 0) - (b.start || 0))
      const segmentCrossfade = 0.06
      const segmentHalfCrossfade = segmentCrossfade / 2
      const modelIds: string[] = []
      for (const seg of orderedSegments) {
        for (const id of seg.model_ids || [seg.model_id]) {
          if (id && !modelIds.includes(id)) modelIds.push(id)
        }
      }
      project = {
        id: rid('edt_'),
        title: `${work.title} · 编辑`,
        duration,
        sample_rate: 44100,
        waveform_cache: {},
        metadata: {
          work_id: workId,
          mode: 'from_work',
          workflow: work.workflow || 'auto_mix',
          export_mode: vocalExport ? 'vocal' : 'mix',
        },
        created_at: created,
        updated_at: created,
        tracks: [
          {
            id: rid('trk_'),
            name: '原始音频',
            type: 'source',
            volume: 1,
            mute: true,
            locked: true,
            clips: [
              { id: rid('clp_'), name: 'source', start: 0, end: duration, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: true, fade_in: 0, fade_out: 0, channel: 'stereo', metadata: { work_id: workId, stem: 'source' } },
            ],
          },
          {
            id: rid('trk_'),
            name: 'BGM 轨',
            type: 'bgm',
            volume: 0.86,
            mute: vocalExport,
            locked: false,
            clips: [
              { id: rid('clp_'), name: 'instrumental', start: 0, end: duration, offset: 0, volume: 1, mute: false, file: source, effects: [], locked: false, fade_in: 0, fade_out: 0, channel: 'stereo', metadata: { work_id: workId, stem: 'bgm' } },
            ],
          },
          ...modelIds.map((modelId) => {
            const model = mockModels.find((m) => m.id === modelId)
            return {
              id: rid('trk_'),
              name: `AI · ${model?.name || modelId}`,
              type: 'ai',
              volume: 1,
              mute: false,
              locked: false,
              clips: orderedSegments
                .filter((seg) => (seg.model_ids || [seg.model_id]).includes(modelId))
                .map((seg) => {
                  const idx = orderedSegments.indexOf(seg)
                  const hasPrev = idx > 0 && (orderedSegments[idx - 1]?.model_ids || [orderedSegments[idx - 1]?.model_id]).some(Boolean)
                  const hasNext = idx >= 0 && idx + 1 < orderedSegments.length && (orderedSegments[idx + 1]?.model_ids || [orderedSegments[idx + 1]?.model_id]).some(Boolean)
                  const start = Math.max(0, (seg.start || 0) - (hasPrev ? segmentHalfCrossfade : 0))
                  const end = Math.min(duration, (seg.end || 0) + (hasNext ? segmentHalfCrossfade : 0))
                  return {
                    id: rid('clp_'),
                    name: `${model?.name || modelId} ${Math.floor((seg.start || 0) / 60)}:${String(Math.floor(seg.start || 0) % 60).padStart(2, '0')}`,
                    start,
                    end,
                    offset: 0,
                    volume: 1,
                    mute: false,
                    file: `C:/mock/editor-segments/${workId}/${modelId}/seg_${Math.round(start * 1000)}_${Math.round(end * 1000)}.wav`,
                    effects: [],
                    locked: false,
                    fade_in: hasPrev ? segmentCrossfade : 0,
                    fade_out: hasNext ? segmentCrossfade : 0,
                    channel: 'stereo' as const,
                    metadata: {
                      work_id: workId,
                      stem: 'ai_model_segment',
                      model_id: modelId,
                      source_start: seg.start,
                      source_end: seg.end,
                    },
                  }
                }),
            }
          }),
        ],
      }
    } else {
      project = makeEditorProject(`${work.title} · 编辑`, work.output || 'demo.wav')
    }
    project.metadata.work_id = workId
    mockEditorProjects.unshift(project)
    mockEditorHistory[project.id] = []
    mockEditorFuture[project.id] = []
    return cloneProject(project)
  },
  saveEditorProject(project: EditorProject): EditorProject | null {
    const idx = mockEditorProjects.findIndex((p) => p.id === project.id)
    const next = cloneProject(project)
    next.duration = projectDuration(next)
    next.updated_at = now()
    if (idx >= 0) {
      mockEditorHistory[next.id] = [...(mockEditorHistory[next.id] || []), cloneProject(mockEditorProjects[idx]!)]
      mockEditorFuture[next.id] = []
      mockEditorProjects[idx] = next
    } else {
      mockEditorProjects.unshift(next)
      mockEditorHistory[next.id] = []
      mockEditorFuture[next.id] = []
    }
    return cloneProject(next)
  },
  undoEditorProject(projectId: string): EditorProject | null {
    const idx = mockEditorProjects.findIndex((p) => p.id === projectId)
    const hist = mockEditorHistory[projectId] || []
    if (idx < 0 || !hist.length) return idx >= 0 ? cloneProject(mockEditorProjects[idx]!) : null
    const current = mockEditorProjects[idx]!
    const prev = hist.pop()!
    mockEditorFuture[projectId] = [...(mockEditorFuture[projectId] || []), cloneProject(current)]
    mockEditorProjects[idx] = cloneProject(prev)
    return cloneProject(prev)
  },
  redoEditorProject(projectId: string): EditorProject | null {
    const idx = mockEditorProjects.findIndex((p) => p.id === projectId)
    const future = mockEditorFuture[projectId] || []
    if (idx < 0 || !future.length) return idx >= 0 ? cloneProject(mockEditorProjects[idx]!) : null
    const current = mockEditorProjects[idx]!
    const next = future.pop()!
    mockEditorHistory[projectId] = [...(mockEditorHistory[projectId] || []), cloneProject(current)]
    mockEditorProjects[idx] = cloneProject(next)
    return cloneProject(next)
  },
  getEditorClipAudio(projectId: string, clipId: string): string {
    console.info('[mock] getEditorClipAudio', projectId, clipId)
    return ''
  },
  renderEditorPreview(projectId: string): string {
    console.info('[mock] renderEditorPreview', projectId)
    return ''
  },
  renderEditorProject(projectId: string, fmt = 'wav'): string {
    return `C:/exports/${projectId}.${editorFormat(fmt)}`
  },
  exportEditorProject(projectId: string, fmt = 'wav'): string {
    return `C:/exports/${projectId}.${editorFormat(fmt)}`
  },
  getEditorWaveform(_projectId: string, clipId: string, bins = 160): EditorWaveform {
    const count = Math.max(16, Math.min(900, bins))
    const peaks = Array.from({ length: count }, (_, i) => {
      const a = Math.abs(Math.sin(i * 0.18))
      const b = Math.abs(Math.sin(i * 0.047 + 1.2))
      return Number(Math.min(1, 0.18 + a * 0.52 + b * 0.22).toFixed(4))
    })
    return { ok: true, clip_id: clipId, bins: count, peaks }
  },
  preloadEditorWaveforms(projectId: string, bins = 160): boolean {
    console.info('[mock] preloadEditorWaveforms', projectId, bins)
    return true
  },
  rerunEditorClip(
    projectId: string,
    trackId: string,
    clipId: string,
    modelId: string,
    _params?: Record<string, unknown>,
  ): EditorRerunResult {
    const project = mockEditorProjects.find((p) => p.id === projectId)
    if (!project) return { ok: false, error: '工程不存在' }
    const track = project.tracks.find((t) => t.id === trackId)
    const clip = track?.clips.find((c) => c.id === clipId)
    if (!track || !clip) return { ok: false, error: '片段不存在' }
    if ((clip.end || 0) - (clip.start || 0) < mockMinRerunClipSeconds) {
      return { ok: false, error: `片段过短：至少 ${mockMinRerunClipSeconds.toFixed(2)} 秒才能重推理` }
    }
    clip.name = `${clip.name} · ${modelId}`
    clip.metadata = { ...(clip.metadata || {}), rerun_model_id: modelId }
    project.updated_at = now()
    return { ok: true, project: cloneProject(project), clip: { ...clip } }
  },
}

const mockProgress: Record<string, number> = {}
const mockJobs: Record<string, HubJob> = {}
