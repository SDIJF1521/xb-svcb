// 与后端 (app/) 应用层返回结构对应的类型定义

export type JobStatus = 'queue' | 'running' | 'done' | 'failed'
export type StepStatus = 'wait' | 'active' | 'done' | 'failed'

export interface ToolStatus {
  key: string
  name: string
  desc: string
  version: string
  status: string
  ok: boolean
}

export interface SystemStatus {
  ready: boolean
  tools: ToolStatus[]
}

export interface ModelFileDTO {
  name: string
  path: string
}

export interface ModelDTO {
  id: string
  name: string
  type: string
  sample_rate: string
  size: string
  imported_at: string
  main_model: ModelFileDTO
  main_config: ModelFileDTO
  diffusion_model?: ModelFileDTO | null
  diffusion_config?: ModelFileDTO | null
}

export interface ImportModelPayload {
  name?: string
  main_model: string
  main_config: string
  diffusion_model?: string | null
  diffusion_config?: string | null
}

export interface PipelineStep {
  key: string
  label: string
  status: StepStatus
}

export interface InferenceParams {
  pitch?: number
  f0_method?: string
  index_rate?: number
  rms_mix?: number
  uvr_model?: string
  diffusion_ratio?: number
  device?: string
}

export interface WorkDTO {
  id: string
  title: string
  model: string
  model_id: string
  status: JobStatus
  progress: number
  duration: string
  format: string
  size: string
  created_at: string
  time: string
  source_path?: string | null
  output_path?: string | null
  output?: string | null
  instrumental_path?: string | null
  vocals_path?: string | null
  error?: string | null
  log_path?: string | null
  params?: InferenceParams
  steps: PipelineStep[]
  mode?: 'single' | 'multi'
  segments?: BlendSegment[]
}

/** 多模型混合：某一句歌词指派给某个模型的时间区间。 */
export interface BlendSegment {
  start: number
  end: number
  model_id: string
}

/** 多模型混合：参与本次翻唱的模型及其各自参数。 */
export interface BlendModel {
  model_id: string
  params: InferenceParams
}

export interface CreateWorkPayload {
  title?: string
  model_id?: string
  source_path?: string | null
  params?: InferenceParams
  /** 翻唱模式：single=单模型（默认）；multi=多模型混合。 */
  mode?: 'single' | 'multi'
  /** 多模型混合时参与的模型与参数。 */
  models?: BlendModel[]
  /** 多模型混合时每句歌词的模型指派。 */
  segments?: BlendSegment[]
}

// ---- 音乐资源获取（妖狐 API）----

/** 可选曲库（网易云 / QQ音乐 …）。 */
export interface MusicSource {
  id: string
  name: string
  /** 是否支持配置会员 Cookie（仅 QQ音乐）。 */
  cookie: boolean
}

/** 搜索结果中的单条歌曲索引项。 */
export interface MusicSearchItem {
  n: number
  name: string
  singer: string
  album: string
  /** 收费标记，如「[收费]」（仅部分曲库返回）。 */
  pay?: string
}

export interface MusicSearchResult {
  ok: boolean
  error?: string
  keyword?: string
  source?: string
  songs?: MusicSearchItem[]
}

/** 单曲详情（含播放与下载地址）。 */
export interface MusicSongDetail {
  name: string
  singer: string
  album: string
  title: string
  picture: string
  url: string
  musicurl: string
  lrc: string
}

export interface MusicSongResult {
  ok: boolean
  error?: string
  song?: MusicSongDetail
}

/** 下载结果。 */
export interface MusicDownloadResult {
  ok: boolean
  error?: string
  path?: string
  name?: string
  size?: string
}

/** 已下载到本地的歌曲。 */
export interface DownloadedMusic {
  name: string
  path: string
  size: string
}

/** 一句带时间轴的歌词（time 为秒）。 */
export interface LyricLine {
  time: number
  text: string
}

export interface LyricsResult {
  ok: boolean
  error?: string
  lines?: LyricLine[]
  name?: string
  singer?: string
}

// ---- 模型站（ModelScope 魔搭社区）----

/** 校验 ModelScope 访问令牌的结果。 */
export interface HubTokenResult {
  ok: boolean
  error?: string
  username?: string
  email?: string
}

/** 模型架构标签（so-vits-svc / rvc …）。 */
export interface ModelFramework {
  id: string
  name: string
}

/** 模型站搜索到的一个（经清单校验、确为本软件上传的）模型。 */
export interface HubModelItem {
  repo_id: string
  name: string
  type: string
  /** 模型架构 id，如 so-vits-svc / rvc。 */
  framework: string
  /** 模型架构显示名。 */
  framework_label: string
  sample_rate: string
  author: string
  has_diffusion: boolean
  url: string
}

export interface HubSearchResult {
  ok: boolean
  error?: string
  items?: HubModelItem[]
  page?: number
}

/** 下载结果：成功时附带导入到本地模型库的模型。 */
export interface HubDownloadResult {
  ok: boolean
  error?: string
  model?: ModelDTO
}

/** 上传结果。 */
export interface HubUploadResult {
  ok: boolean
  error?: string
  url?: string
  repo_id?: string
}

/** 上传/下载进度（前端轮询）。 */
export interface HubProgress {
  phase: string
  pct: number
  msg: string
  done: number
  total: number
}
