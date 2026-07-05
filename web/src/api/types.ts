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

export interface DataStorageStatus {
  data_dir: string
  used_bytes: number
  used: string
  free_bytes: number
  free: string
  total_bytes?: number
  total?: string
  pointer_file?: string
  pointer_files?: string[]
}

export interface DataMigrationResult extends DataStorageStatus {
  ok: boolean
  error?: string
  message?: string
  restart_required?: boolean
  old_data_dir?: string
}

export interface DataDirSwitchResult extends DataStorageStatus {
  ok: boolean
  error?: string
  message?: string
  restart_required?: boolean
}

export type DataMigrationStatusName = 'idle' | 'running' | 'done' | 'failed'

export interface DataMigrationProgress {
  status: DataMigrationStatusName
  phase: string
  message: string
  target_dir?: string
  copied_bytes: number
  copied: string
  total_bytes: number
  total: string
  percent: number
  error?: string
  result?: DataMigrationResult
}

export interface DataMigrationStartResult extends DataMigrationProgress {
  ok: boolean
  started?: boolean
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
  /** 模型框架：so-vits-svc / rvc / …（缺省 so-vits-svc）。 */
  framework?: string
  /** RVC 检索特征文件（.index），可选。 */
  index_file?: ModelFileDTO | null
  favorite?: boolean
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface ModelInspectIssue {
  key: string
  level: 'error' | 'warn' | string
  message: string
}

export interface ModelInspectResult {
  ok: boolean
  error?: string
  model?: ModelDTO
  issues: ModelInspectIssue[]
  fixed?: string[]
}

export interface ModelFrameworkSummary {
  id: string
  name: string
  count: number
  size_bytes: number
  size: string
  default_model_id?: string | null
  default_model_name?: string
  supported: boolean
}

export interface ModelLibraryOverview {
  total: number
  total_size_bytes: number
  total_size: string
  default_model_id?: string | null
  frameworks: ModelFrameworkSummary[]
}

export interface ImportModelPayload {
  name?: string
  /** 模型框架：so-vits-svc（默认）/ rvc。 */
  framework?: string
  main_model: string
  /** so-vits 必填；RVC 不需要。 */
  main_config?: string
  diffusion_model?: string | null
  diffusion_config?: string | null
  /** RVC 检索特征文件（.index），可选。 */
  index_file?: string | null
}

export interface PipelineStep {
  key: string
  label: string
  status: StepStatus
}

export type CreateWorkflow =
  | 'auto_mix'
  | 'auto_vocal_merge'
  | 'manual_vocal_merge'
  | 'auto_then_editor'
  | 'full_manual_editor'

export interface InferenceParams {
  pitch?: number
  f0_method?: string
  index_rate?: number
  rms_mix?: number
  uvr_model?: string
  diffusion_ratio?: number
  device?: string
  /** RVC：清辅音/呼吸保护 (0~0.5)。 */
  protect?: number
  /** RVC：F0 中值滤波半径 (0~7)。 */
  filter_radius?: number
  /** RVC：模型版本 v1 / v2。 */
  rvc_version?: string
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
  workflow?: CreateWorkflow
  segments?: BlendSegment[]
  queue_position?: number
  history?: InferenceHistoryItem[]
}

export interface InferenceHistoryItem {
  work_id?: string
  title?: string
  model?: string
  workflow?: CreateWorkflow | string
  status: JobStatus | string
  progress?: number
  output_path?: string | null
  error?: string | null
  finished_at: string
}

export interface InferenceQueueStatus {
  running: boolean
  pending: string[]
  size: number
}

export interface InferencePreset {
  id: string
  name: string
  params: InferenceParams
  updated_at: string
}

/** 多模型混合：某一句歌词指派给一个或多个模型的时间区间。 */
export interface BlendSegment {
  start: number
  end: number
  /** 兼容字段：单模型时的主模型 id（取 model_ids 首个）。 */
  model_id: string
  /** 合唱：参与同唱该句的模型 id 列表（>1 即多模型合唱）。 */
  model_ids?: string[]
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
  workflow?: CreateWorkflow
  /** 翻唱模式：single=单模型（默认）；multi=多模型混合。 */
  mode?: 'single' | 'multi'
  /** 多模型混合时参与的模型与参数。 */
  models?: BlendModel[]
  /** 多模型混合时每句歌词的模型指派。 */
  segments?: BlendSegment[]
}

export interface CreateBatchWorkPayload extends CreateWorkPayload {
  source_paths: string[]
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
  /** 当前页码（从 1 开始）。 */
  page?: number
  page_size?: number
  /** 是否还有更多结果可「加载更多」。 */
  has_more?: boolean
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

export interface LyricsFileResult {
  ok: boolean
  cancelled?: boolean
  error?: string
  path?: string
  name?: string
  text?: string
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
  page_size?: number
  /** 是否还有更多结果可「加载更多」。 */
  has_more?: boolean
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

/** 启动后台上传/下载任务的返回。 */
export interface HubStartResult {
  ok: boolean
  error?: string
  /** 任务 key，形如 'dl:<repo_id>' 或 'ul:<model_id>'。 */
  key?: string
  /** 该任务已在进行中（重复触发时）。 */
  already?: boolean
}

/** 后台传输任务（上传/下载）记录，含实时进度。 */
export interface HubJob {
  key: string
  kind: 'upload' | 'download'
  title: string
  status: 'running' | 'done' | 'failed'
  error?: string | null
  result?: { model?: ModelDTO; url?: string; repo_id?: string } | null
  created_at?: string
  pct: number
  msg: string
  phase: string
}

// ---- 音频编辑器（Audio Editor Lite）----

export type EditorTrackType = 'source' | 'vocal' | 'bgm' | 'ai' | 'effect' | 'audio'
export type EditorClipChannel = 'stereo' | 'left' | 'right'

export interface EditorClip {
  id: string
  name: string
  start: number
  end: number
  offset: number
  volume: number
  mute: boolean
  file: string
  effects: { type: string; [key: string]: unknown }[]
  locked: boolean
  fade_in: number
  fade_out: number
  channel?: EditorClipChannel
  metadata: Record<string, unknown>
}

export interface EditorTrack {
  id: string
  name: string
  type: EditorTrackType | string
  clips: EditorClip[]
  locked?: boolean
  mute?: boolean
  volume?: number
}

export interface EditorProject {
  id: string
  title: string
  tracks: EditorTrack[]
  duration: number
  sample_rate: number
  waveform_cache: Record<string, unknown>
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface EditorProjectSummary {
  id: string
  title: string
  duration: number
  tracks: number
  updated_at: string
}

export interface EditorWaveform {
  ok: boolean
  clip_id?: string
  bins?: number
  peaks: number[]
}

export interface EditorRerunResult {
  ok: boolean
  error?: string
  project?: EditorProject
  clip?: EditorClip
}

export interface EditorSilenceSplitOptions {
  threshold_db?: number
  noise_db?: number
  min_silence?: number
  min_clip?: number
  crossfade?: number
  padding?: number
  adaptive?: boolean
}

export interface EditorSilenceInterval {
  start: number
  end: number
  duration: number
}

export interface EditorSilenceSplitResult {
  ok: boolean
  error?: string
  project?: EditorProject
  clips?: EditorClip[]
  cuts?: number[]
  relative_cuts?: number[]
  silences?: EditorSilenceInterval[]
}

export interface EditorTrackMutationResult {
  ok: boolean
  error?: string
  project?: EditorProject
  track?: EditorTrack
  clip?: EditorClip
  removed_track_id?: string
}

export interface EditorSeparationResult {
  ok: boolean
  error?: string
  project?: EditorProject
  tracks?: EditorTrack[]
  clips?: EditorClip[]
  simulated?: boolean
}

export interface EditorLyricSplitOptions {
  padding?: number
  min_clip?: number
  time_mode?: 'project' | 'clip'
}

export interface EditorLyricLine {
  time: number
  text: string
}

export interface EditorLyricSplitResult {
  ok: boolean
  error?: string
  project?: EditorProject
  clips?: EditorClip[]
  lines?: EditorLyricLine[]
}
