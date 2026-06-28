// 前端统一 API 入口：桌面环境调用 pywebview 后端，浏览器回退 mock。

import { invoke } from './bridge'
import { mock } from './mock'
import type {
  CreateWorkPayload,
  CreateBatchWorkPayload,
  InferenceHistoryItem,
  InferencePreset,
  InferenceQueueStatus,
  ImportModelPayload,
  ModelLibraryOverview,
  ModelInspectResult,
  ModelDTO,
  SystemStatus,
  WorkDTO,
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
  EditorSilenceSplitOptions,
  EditorSilenceSplitResult,
  DataMigrationResult,
  DataStorageStatus,
} from './types'

export * from './types'
export { isDesktop, whenReady } from './bridge'

export const api = {
  getSystemStatus: () =>
    invoke<SystemStatus>('get_system_status', [], () => mock.getSystemStatus()),

  getDataStorageStatus: () =>
    invoke<DataStorageStatus>('get_data_storage_status', [], () =>
      mock.getDataStorageStatus(),
    ),

  pickDataDir: () =>
    invoke<string>('pick_data_dir', [], () => mock.pickDataDir()),

  migrateDataDir: (targetDir: string) =>
    invoke<DataMigrationResult>('migrate_data_dir', [targetDir], () =>
      mock.migrateDataDir(targetDir),
    ),

  listModels: () => invoke<ModelDTO[]>('list_models', [], () => mock.listModels()),

  getModelLibraryOverview: () =>
    invoke<ModelLibraryOverview>('get_model_library_overview', [], () =>
      mock.getModelLibraryOverview(),
    ),

  getDefaultModel: () =>
    invoke<string | null>('get_default_model', [], () => mock.getDefaultModel()),

  pickModelFile: () =>
    invoke<string | null>('pick_model_file', [], () => mock.pickModelFile()),

  pickConfigFile: () =>
    invoke<string | null>('pick_config_file', [], () => mock.pickConfigFile()),

  pickIndexFile: () =>
    invoke<string | null>('pick_index_file', [], () => mock.pickIndexFile()),

  importModel: (payload: ImportModelPayload) =>
    invoke<ModelDTO | null>('import_model', [payload], () => mock.importModel(payload)),

  setDefaultModel: (id: string) =>
    invoke<boolean>('set_default_model', [id], () => mock.setDefaultModel(id)),

  deleteModel: (id: string) =>
    invoke<boolean>('delete_model', [id], () => mock.deleteModel(id)),

  inspectModel: (id: string, repair = false) =>
    invoke<ModelInspectResult>('inspect_model', [id, repair], () =>
      mock.inspectModel(id, repair),
    ),

  toggleModelFavorite: (id: string) =>
    invoke<ModelDTO | null>('toggle_model_favorite', [id], () =>
      mock.toggleModelFavorite(id),
    ),

  pickAudioFile: () =>
    invoke<string | null>('pick_audio_file', [], () => mock.pickAudioFile()),

  pickAudioFiles: () =>
    invoke<string[]>('pick_audio_files', [], () => mock.pickAudioFiles()),

  listWorks: () => invoke<WorkDTO[]>('list_works', [], () => mock.listWorks()),

  getWork: (id: string) =>
    invoke<WorkDTO | null>('get_work', [id], () => mock.getWork(id)),

  createWork: (payload: CreateWorkPayload) =>
    invoke<WorkDTO>('create_work', [payload], () => mock.createWork(payload)),

  createBatchWork: (payload: CreateBatchWorkPayload) =>
    invoke<WorkDTO[]>('create_batch_work', [payload], () => mock.createBatchWork(payload)),

  getInferenceQueue: () =>
    invoke<InferenceQueueStatus>('get_inference_queue', [], () => mock.getInferenceQueue()),

  listInferenceHistory: (limit = 50) =>
    invoke<InferenceHistoryItem[]>('list_inference_history', [limit], () =>
      mock.listInferenceHistory(limit),
    ),

  listInferencePresets: () =>
    invoke<InferencePreset[]>('list_inference_presets', [], () => mock.listInferencePresets()),

  saveInferencePreset: (name: string, params: Record<string, unknown>) =>
    invoke<InferencePreset>('save_inference_preset', [name, params], () =>
      mock.saveInferencePreset(name, params),
    ),

  deleteInferencePreset: (id: string) =>
    invoke<boolean>('delete_inference_preset', [id], () => mock.deleteInferencePreset(id)),

  retryWork: (id: string) =>
    invoke<boolean>('retry_work', [id], () => mock.retryWork(id)),

  renameWork: (id: string, title: string) =>
    invoke<boolean>('rename_work', [id, title], () => mock.renameWork(id, title)),

  deleteWork: (id: string) =>
    invoke<boolean>('delete_work', [id], () => mock.deleteWork(id)),

  openWorkLog: (id: string) =>
    invoke<boolean>('open_work_log', [id], () => mock.openWorkLog(id)),

  openPath: (path: string) =>
    invoke<boolean>('open_path', [path], () => mock.openPath(path)),

  getWorkAudio: (id: string) =>
    invoke<string>('get_work_audio', [id], () => mock.getWorkAudio(id)),

  getStemAudio: (id: string, kind: 'output' | 'instrumental' | 'vocals') =>
    invoke<string>('get_stem_audio', [id, kind], () => mock.getStemAudio(id, kind)),

  exportWork: (id: string) =>
    invoke<string>('export_work', [id], () => mock.exportWork(id)),

  // ---- 音乐资源获取 ----
  getMusicApiKey: () =>
    invoke<string>('get_music_api_key', [], () => mock.getMusicApiKey()),

  setMusicApiKey: (key: string) =>
    invoke<boolean>('set_music_api_key', [key], () => mock.setMusicApiKey(key)),

  listMusicSources: () =>
    invoke<MusicSource[]>('list_music_sources', [], () => mock.listMusicSources()),

  getMusicSource: () =>
    invoke<string>('get_music_source', [], () => mock.getMusicSource()),

  setMusicSource: (source: string) =>
    invoke<boolean>('set_music_source', [source], () => mock.setMusicSource(source)),

  getMusicCookie: () =>
    invoke<string>('get_music_cookie', [], () => mock.getMusicCookie()),

  setMusicCookie: (cookie: string) =>
    invoke<boolean>('set_music_cookie', [cookie], () => mock.setMusicCookie(cookie)),

  searchMusic: (msg: string, page = 1, pageSize = 15, source?: string) =>
    invoke<MusicSearchResult>('search_music', [msg, page, pageSize, source], () =>
      mock.searchMusic(msg, page, pageSize, source),
    ),

  getMusicSong: (msg: string, n: number, source?: string) =>
    invoke<MusicSongResult>('get_music_song', [msg, n, source], () => mock.getMusicSong(msg, n, source)),

  downloadMusic: (msg: string, n: number, source?: string) =>
    invoke<MusicDownloadResult>('download_music', [msg, n, source], () => mock.downloadMusic(msg, n, source)),

  getMusicLyrics: (msg: string, n: number, source?: string) =>
    invoke<LyricsResult>('get_music_lyrics', [msg, n, source], () => mock.getMusicLyrics(msg, n, source)),

  listMusic: () =>
    invoke<DownloadedMusic[]>('list_music', [], () => mock.listMusic()),

  deleteMusic: (path: string) =>
    invoke<boolean>('delete_music', [path], () => mock.deleteMusic(path)),

  getAudioDuration: (path: string) =>
    invoke<number>('get_audio_duration', [path], () => mock.getAudioDuration(path)),

  // ---- 模型站（ModelScope 魔搭社区）----
  getModelscopeToken: () =>
    invoke<string>('get_modelscope_token', [], () => mock.getModelscopeToken()),

  setModelscopeToken: (token: string) =>
    invoke<boolean>('set_modelscope_token', [token], () => mock.setModelscopeToken(token)),

  verifyModelscopeToken: (token?: string) =>
    invoke<HubTokenResult>('verify_modelscope_token', [token], () =>
      mock.verifyModelscopeToken(token),
    ),

  modelhubUploadReady: () =>
    invoke<boolean>('modelhub_upload_ready', [], () => mock.modelhubUploadReady()),

  listModelFrameworks: () =>
    invoke<ModelFramework[]>('list_model_frameworks', [], () => mock.listModelFrameworks()),

  hubSearchModels: (query = '', page = 1, framework?: string, pageSize = 12) =>
    invoke<HubSearchResult>('hub_search_models', [query, page, framework, pageSize], () =>
      mock.hubSearchModels(query, page, framework, pageSize),
    ),

  hubDownloadModel: (repoId: string) =>
    invoke<HubDownloadResult>('hub_download_model', [repoId], () =>
      mock.hubDownloadModel(repoId),
    ),

  hubUploadModel: (modelId: string, name?: string, framework?: string) =>
    invoke<HubUploadResult>('hub_upload_model', [modelId, name, framework], () =>
      mock.hubUploadModel(modelId, name, framework),
    ),

  hubProgress: (key: string) =>
    invoke<HubProgress>('hub_progress', [key], () => mock.hubProgress(key)),

  // 后台传输：上传/下载挂后台，不阻塞前端
  hubStartDownload: (repoId: string) =>
    invoke<HubStartResult>('hub_start_download', [repoId], () =>
      mock.hubStartDownload(repoId),
    ),

  hubStartUpload: (modelId: string, name?: string, framework?: string) =>
    invoke<HubStartResult>('hub_start_upload', [modelId, name, framework], () =>
      mock.hubStartUpload(modelId, name, framework),
    ),

  hubListJobs: () =>
    invoke<HubJob[]>('hub_list_jobs', [], () => mock.hubListJobs()),

  hubClearJob: (key: string) =>
    invoke<boolean>('hub_clear_job', [key], () => mock.hubClearJob(key)),

  // ---- 音频编辑器 ----
  listEditorProjects: () =>
    invoke<EditorProjectSummary[]>('list_editor_projects', [], () => mock.listEditorProjects()),

  getEditorProject: (projectId: string) =>
    invoke<EditorProject | null>('get_editor_project', [projectId], () =>
      mock.getEditorProject(projectId),
    ),

  deleteEditorProject: (projectId: string) =>
    invoke<boolean>('delete_editor_project', [projectId], () =>
      mock.deleteEditorProject(projectId),
    ),

  createEditorProjectFromAudio: (path: string, title?: string) =>
    invoke<EditorProject | null>('create_editor_project_from_audio', [path, title], () =>
      mock.createEditorProjectFromAudio(path, title),
    ),

  createEditorProjectFromWork: (workId: string) =>
    invoke<EditorProject | null>('create_editor_project_from_work', [workId], () =>
      mock.createEditorProjectFromWork(workId),
    ),

  saveEditorProject: (project: EditorProject) =>
    invoke<EditorProject | null>('save_editor_project', [project], () =>
      mock.saveEditorProject(project),
    ),

  undoEditorProject: (projectId: string) =>
    invoke<EditorProject | null>('undo_editor_project', [projectId], () =>
      mock.undoEditorProject(projectId),
    ),

  redoEditorProject: (projectId: string) =>
    invoke<EditorProject | null>('redo_editor_project', [projectId], () =>
      mock.redoEditorProject(projectId),
    ),

  getEditorClipAudio: (projectId: string, clipId: string) =>
    invoke<string>('get_editor_clip_audio', [projectId, clipId], () =>
      mock.getEditorClipAudio(projectId, clipId),
    ),

  renderEditorPreview: (projectId: string) =>
    invoke<string>('render_editor_preview', [projectId], () => mock.renderEditorPreview(projectId)),

  renderEditorProject: (projectId: string, fmt = 'wav') =>
    invoke<string>('render_editor_project', [projectId, fmt], () =>
      mock.renderEditorProject(projectId, fmt),
    ),

  exportEditorProject: (projectId: string, fmt = 'wav') =>
    invoke<string>('export_editor_project', [projectId, fmt], () =>
      mock.exportEditorProject(projectId, fmt),
    ),

  getEditorWaveform: (projectId: string, clipId: string, bins = 160) =>
    invoke<EditorWaveform>('get_editor_waveform', [projectId, clipId, bins], () =>
      mock.getEditorWaveform(projectId, clipId, bins),
    ),

  preloadEditorWaveforms: (projectId: string, bins = 160) =>
    invoke<boolean>('preload_editor_waveforms', [projectId, bins], () =>
      mock.preloadEditorWaveforms(projectId, bins),
    ),

  splitEditorClipBySilence: (
    projectId: string,
    trackId: string,
    clipId: string,
    options?: EditorSilenceSplitOptions,
  ) =>
    invoke<EditorSilenceSplitResult>(
      'split_editor_clip_by_silence',
      [projectId, trackId, clipId, options],
      () => mock.splitEditorClipBySilence(projectId, trackId, clipId, options),
    ),

  rerunEditorClip: (
    projectId: string,
    trackId: string,
    clipId: string,
    modelId: string,
    params?: Record<string, unknown>,
  ) =>
    invoke<EditorRerunResult>('rerun_editor_clip', [projectId, trackId, clipId, modelId, params], () =>
      mock.rerunEditorClip(projectId, trackId, clipId, modelId, params),
    ),
}

const palette = ['#00f0ff', '#2f6bff', '#ff2e88', '#19f59a', '#ffae00', '#b65cff', '#5ce0c8', '#ff7ac0']

/** 按索引/字符串稳定地分配一个主题色。 */
export function pickColor(seed: number | string): string {
  if (typeof seed === 'number') return palette[seed % palette.length] as string
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return palette[h % palette.length] as string
}
