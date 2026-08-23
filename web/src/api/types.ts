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

export type InferenceDeviceBackend = 'auto' | 'cuda' | 'rocm' | 'directml' | 'cpu'

export interface InferenceDeviceOption {
  value: InferenceDeviceBackend
  label: string
  backend: InferenceDeviceBackend
  name?: string
  frameworks: string[]
}

export interface InferenceDeviceRuntime {
  ok: boolean
  torch_version: string
  backends: InferenceDeviceBackend[]
  devices: { backend: InferenceDeviceBackend; name: string; index: number }[]
  preferred: InferenceDeviceBackend
  error?: string
}

export interface InferenceDeviceCapabilities {
  preferred: InferenceDeviceBackend
  options: InferenceDeviceOption[]
  frameworks: Record<string, InferenceDeviceRuntime>
}

export interface ThemeMediaPickResult {
  ok: boolean
  cancelled?: boolean
  error?: string
  path?: string
  kind?: 'image' | 'video'
  mime?: string
  name?: string
}

export interface SystemStatus {
  ready: boolean
  tools: ToolStatus[]
  inference_devices?: InferenceDeviceCapabilities
}

export type HttpApiScope = 'local' | 'lan'

export interface HttpApiStatus {
  running: boolean
  scope: HttpApiScope
  host: string
  port: number
  api_key: string
  base_urls: string[]
  docs_url: string
  redoc_url: string
  last_error?: string
  ok?: boolean
  message?: string
  error?: string
}

export interface HttpApiTestResult {
  ok: boolean
  latency_ms?: number
  model_count?: number
  message?: string
  error?: string
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
  /** 模型框架：so-vits-svc（默认）/ rvc / seed-vc / ddsp-svc。 */
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
  | 'realtime_cover'
  | 'ai_enhancement'

export type VocalEnhancementLevel = 'basic' | 'advanced'

export interface VocalEnhancementOptions {
  enabled: boolean
  level: VocalEnhancementLevel
  /** 增强推理设备。 */
  device?: string
  /** 自然修音强度（0~1），保留颤音与滑音。 */
  pitch_correction: number
  /** AI 对齐强度（0~1），参考原唱校正局部抢拍与拖拍。 */
  timing_alignment: number
  /** AI 角色共振峰强度（0~1）。 */
  timbre_focus: number
  /** AI EQ 自适应宽带校正强度（0~1）。 */
  ai_eq: number
  /** AI Compressor 自适应动态控制强度（0~1）。 */
  ai_compressor: number
  /** AI Exciter 高频谐波增强强度（0~1）。 */
  ai_exciter: number
  /** Stereo 单声道兼容立体声宽度（0~1）。 */
  stereo_width: number
  /** AI 响度包络恢复强度（0~1），只校正局部响度起伏。 */
  loudness_envelope: number
}

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
  /** SeedVC：本次推理的目标音色参考音频。 */
  reference_audio?: string
  /** DDSP-SVC：Rectified Flow 采样步数。 */
  ddsp_infer_steps?: number
  /** DDSP-SVC：共振峰偏移（-2~2 半音，仅 pitch augmentation 模型有效）。 */
  ddsp_formant_shift?: number
  /** So-VITS / DDSP-SVC：目标说话人名称或 id。 */
  speaker?: string
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
  vocal_enhancement?: VocalEnhancementOptions
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
  /** 模型推理后的可选 AI 美声/歌声增强流程。 */
  vocal_enhancement?: VocalEnhancementOptions
  /** 翻唱模式：single=单模型（默认）；multi=多模型混合。 */
  mode?: 'single' | 'multi'
  /** 多模型混合时参与的模型与参数。 */
  models?: BlendModel[]
  /** 多模型混合时每句歌词的模型指派。 */
  segments?: BlendSegment[]
  /** 独立 AI 增强：待处理的已完成翻唱作品 ID。 */
  target_work_id?: string
  /** 独立 AI 增强：与翻唱作品对应的原始歌曲路径。 */
  original_audio_path?: string
  /** 独立 AI 增强：用户直接导入的待增强翻唱音频。 */
  target_audio_path?: string
}

export interface CreateBatchWorkPayload extends CreateWorkPayload {
  source_paths: string[]
}

export type RealtimeCoverState =
  | 'preparing'
  | 'buffering'
  | 'ready'
  | 'live'
  | 'done'
  | 'failed'
  | 'stopped'
  | 'missing'

export interface RealtimeCoverPayload {
  source_path?: string
  input_mode?: 'file' | 'system'
  title?: string
  mode: 'single'
  model_id?: string
  params?: InferenceParams
  chunk_seconds: number
  buffer_seconds: number
  vocal_gain_db: number
  instrumental_gain_db: number
  input_device?: string
  accompaniment_device?: string
  output_device?: string
  sample_rate?: number
}

export interface SystemAudioDevice {
  id: string
  name: string
  kind: 'input' | 'output'
  loopback?: boolean
  system_mix?: boolean
}

export interface RealtimeCoverStatus {
  id: string
  status: RealtimeCoverState
  message?: string
  error?: string | null
  duration?: number
  chunk_seconds?: number
  buffer_seconds?: number
  ready_seconds?: number
  processed_seconds?: number
  realtime_factor?: number | null
  input_silent?: boolean
  ready_chunks?: number
  total_chunks?: number
  mode?: 'single'
  input_mode?: 'file' | 'system'
  output_path?: string | null
  work_id?: string | null
}

export interface RealtimeCoverChunk {
  ok: boolean
  pending?: boolean
  error?: string
  index?: number
  start?: number
  end?: number
  duration?: number
  model_ids?: string[]
  audio?: string
}

// ---- 音乐资源获取（妖狐 API）----

/** 可选曲库（网易云 / QQ音乐 / 酷我音乐 …）。 */
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
  /** 酷我返回的歌曲 RID，用于标识搜索结果；歌词按同一次搜索的 query+n 获取。 */
  rid?: string
  subtitle?: string
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
  vipmusicurl?: string
  /** 酷我 vipmusic 返回的实际音频格式。 */
  format?: string
  /** 酷我 vipmusic 返回的音质描述。 */
  quality?: string
  /** 酷我歌曲 RID。 */
  rid?: string
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

/** 在线试听结果（酷我返回 data URI，其它曲库返回直链）。 */
export interface MusicPreviewResult {
  ok: boolean
  error?: string
  src?: string
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

export interface PluginStatus {
  enabled: boolean
  market_url: string
  development_dir: string
  security: string
  ok?: boolean
  error?: string
}

export interface PluginField {
  id: string
  label?: string
  type: 'text' | 'number' | 'select' | 'switch' | 'textarea'
  default?: string | number | boolean
  options?: { label: string; value: string | number }[]
  placeholder?: string
  help?: string
}

export interface PluginPage {
  id: string
  title: string
  description?: string
  fields: PluginField[]
  actions?: string[]
}

export interface PluginFrontend {
  entry?: string
}

export interface PluginAction {
  id: string
  label: string
  type: 'message' | 'create_work' | 'python'
  message?: string
}

export interface PluginInfo {
  id: string
  name: string
  version: string
  description: string
  author: string
  runtime: 'frontend' | 'python' | 'hybrid'
  frontend?: PluginFrontend
  permissions: string[]
  pages: PluginPage[]
  actions: PluginAction[]
  enabled: boolean
  installed: boolean
  path: string
}

export interface PluginMarketTag {
  label: string
  color?: string
}

export interface PluginMarketItem {
  id: string
  module_name?: string
  project_link?: string
  name: string
  version: string
  description: string
  author: string
  bundle_url?: string
  homepage?: string
  tags?: PluginMarketTag[]
  is_official?: boolean
}

export interface PluginMarketResult {
  ok: boolean
  items: PluginMarketItem[]
  error?: string
}

export interface PluginInstallResult {
  ok: boolean
  plugin?: PluginInfo
  message?: string
  error?: string
}

export interface PluginActionResult {
  ok: boolean
  type?: 'message' | 'create_work'
  message?: string
  payload?: CreateWorkPayload
  error?: string
}

export interface PluginFrontendDocumentResult {
  ok: boolean
  entry?: string
  html?: string
  error?: string
}

export interface PluginFrontendAssetResult {
  ok: boolean
  name?: string
  mime?: string
  data?: string
  error?: string
}

export interface HubModelAsset {
  path: string
  name: string
  kind: 'image' | 'audio' | string
  mime?: string
}

export interface HubModelDependency {
  id: string
  name: string
  required: boolean
  kind: string
  present?: boolean
  ok: boolean
  message: string
}

export interface HubModelVersion {
  version: string
  uploaded_at?: string
  repo_id?: string
  current?: boolean
}

export interface HubModelUpdateInfo {
  installed: boolean
  available: boolean
  model_id?: string
  model_name?: string
  installed_version?: string
  latest_version?: string
  installed_models?: {
    model_id: string
    model_name: string
    installed_version: string
    installed_at: string
    source_uploaded_at?: string
  }[]
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
  description?: string
  tags?: string[]
  version?: string
  uploaded_at?: string
  downloads?: number
  local_downloads?: number
  download_count?: number
  likes?: number
  screenshots?: HubModelAsset[]
  preview_audio?: HubModelAsset | null
  dependency_ok?: boolean
  dependencies?: HubModelDependency[]
  versions?: HubModelVersion[]
  update?: HubModelUpdateInfo
  score?: number
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

export interface HubUploadOptions {
  version?: string
  description?: string
  tags?: string[]
  preview_audio?: string
  screenshots?: string[]
}

export interface HubModelDetailResult {
  ok: boolean
  error?: string
  item?: HubModelItem
}

export interface HubAssetDataResult {
  ok: boolean
  error?: string
  name?: string
  mime?: string
  data?: string
  url?: string
}

export interface HubModelUpdateItem {
  model_id: string
  model_name: string
  repo_id: string
  installed_version: string
  latest_version: string
  uploaded_at: string
  framework: string
}

export interface HubModelUpdateResult {
  ok: boolean
  error?: string
  items?: HubModelUpdateItem[]
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
export type EditorEffectType =
  | 'reverb'
  | 'denoise'
  | 'noise_gate'
  | 'compressor'
  | 'eq'
  | 'delay'
  | 'chorus'
  | 'limiter'
  | 'gain'
  | 'highpass'
  | 'lowpass'
  | 'plugin'

export interface EditorClipEffect {
  id: string
  type: EditorEffectType | string
  name: string
  enabled: boolean
  params: Record<string, unknown>
}

export interface EditorVolumeEnvelopePoint {
  time: number
  volume: number
}

export interface EditorRole {
  id: string
  name: string
  color: string
  model_id?: string
  pitch?: number
  notes?: string
}

export interface EditorTimelineTemplateRole {
  name: string
  color: string
  pitch?: number
  notes?: string
}

export interface EditorTimelineTemplateTrack {
  name: string
  type: EditorTrackType | string
  roleIndex?: number
}

export interface EditorTimelineTemplate {
  id: string
  name: string
  description: string
  roles: EditorTimelineTemplateRole[]
  tracks: EditorTimelineTemplateTrack[]
}

export interface EditorClip {
  id: string
  name: string
  start: number
  end: number
  offset: number
  volume: number
  mute: boolean
  file: string
  effects: EditorClipEffect[]
  locked: boolean
  fade_in: number
  fade_out: number
  channel?: EditorClipChannel
  volume_envelope?: EditorVolumeEnvelopePoint[]
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
  metadata?: Record<string, unknown>
}

export interface EditorProject {
  id: string
  title: string
  tracks: EditorTrack[]
  roles?: EditorRole[]
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

export interface EditorAudioCopyResult {
  ok: boolean
  error?: string
  path: string
  clipboard?: boolean
}

export interface EditorClipMergeResult {
  ok: boolean
  error?: string
  project?: EditorProject
  clip?: EditorClip
  merged_clip_ids?: string[]
  path?: string
}

export interface EditorPluginHostStatus {
  ok: boolean
  ready: boolean
  host_path: string
  protocol: number
  schema: string
  message?: string
  error?: string
  monitor_ready?: boolean
  realtime_ready?: boolean
  realtime_reason?: string
  monitor?: EditorPluginMonitorStatus
}

export interface EditorPluginTransport {
  playing: boolean
  audible?: boolean
  output_enabled?: boolean
  position_seconds: number
  seek_revision?: number
}

export interface EditorPluginMonitorStatus {
  ready?: boolean
  realtime_ready?: boolean
  audio_output_ready?: boolean
  effect_capable?: boolean
  playhead_ready?: boolean
  output_enabled?: boolean
  playing?: boolean
  ended?: boolean
  position_seconds?: number
  duration_seconds?: number
  blocks?: number
  peak?: number
  output_peak?: number
  safety_bypassed?: boolean
  silent_output_ms?: number
  device_name?: string
  sample_rate?: number
  block_size?: number
  latency_samples?: number
  latency_ms?: number
  xruns?: number
  error?: string
}

export interface EditorPluginInspectResult extends EditorPluginHostStatus {
  plugin?: Record<string, unknown>
}

export interface EditorPluginWindowResult extends EditorPluginHostStatus {
  session_id?: string
  state_path?: string
}

export interface EditorPluginCloseResult extends EditorPluginHostStatus {
  closed?: boolean
  state_path?: string
  plugin?: Record<string, unknown>
  project?: EditorProject
}

export interface EditorPluginSyncResult extends EditorPluginCloseResult {}

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

export interface EditorAudioPasteResult extends EditorTrackMutationResult {
  clips?: EditorClip[]
  paths?: string[]
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
  auto_silence?: boolean
  threshold_db?: number
  min_silence?: number
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
  timing?: 'timestamp' | 'auto'
}
