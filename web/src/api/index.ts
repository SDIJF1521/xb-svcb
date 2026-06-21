// 前端统一 API 入口：桌面环境调用 pywebview 后端，浏览器回退 mock。

import { invoke } from './bridge'
import { mock } from './mock'
import type {
  CreateWorkPayload,
  ImportModelPayload,
  ModelDTO,
  SystemStatus,
  WorkDTO,
  MusicSearchResult,
  MusicSongResult,
  MusicDownloadResult,
  DownloadedMusic,
  MusicSource,
  LyricsResult,
} from './types'

export * from './types'
export { isDesktop, whenReady } from './bridge'

export const api = {
  getSystemStatus: () =>
    invoke<SystemStatus>('get_system_status', [], () => mock.getSystemStatus()),

  listModels: () => invoke<ModelDTO[]>('list_models', [], () => mock.listModels()),

  getDefaultModel: () =>
    invoke<string | null>('get_default_model', [], () => mock.getDefaultModel()),

  pickModelFile: () =>
    invoke<string | null>('pick_model_file', [], () => mock.pickModelFile()),

  pickConfigFile: () =>
    invoke<string | null>('pick_config_file', [], () => mock.pickConfigFile()),

  importModel: (payload: ImportModelPayload) =>
    invoke<ModelDTO | null>('import_model', [payload], () => mock.importModel(payload)),

  setDefaultModel: (id: string) =>
    invoke<boolean>('set_default_model', [id], () => mock.setDefaultModel(id)),

  deleteModel: (id: string) =>
    invoke<boolean>('delete_model', [id], () => mock.deleteModel(id)),

  pickAudioFile: () =>
    invoke<string | null>('pick_audio_file', [], () => mock.pickAudioFile()),

  listWorks: () => invoke<WorkDTO[]>('list_works', [], () => mock.listWorks()),

  getWork: (id: string) =>
    invoke<WorkDTO | null>('get_work', [id], () => mock.getWork(id)),

  createWork: (payload: CreateWorkPayload) =>
    invoke<WorkDTO>('create_work', [payload], () => mock.createWork(payload)),

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

  searchMusic: (msg: string, g = 13, source?: string) =>
    invoke<MusicSearchResult>('search_music', [msg, g, source], () => mock.searchMusic(msg, g, source)),

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
}

const palette = ['#00f0ff', '#2f6bff', '#ff2e88', '#19f59a', '#ffae00', '#b65cff', '#5ce0c8', '#ff7ac0']

/** 按索引/字符串稳定地分配一个主题色。 */
export function pickColor(seed: number | string): string {
  if (typeof seed === 'number') return palette[seed % palette.length] as string
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return palette[h % palette.length] as string
}
