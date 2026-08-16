import type { BeforeCreateParams, Manifest, Page } from '@xb-svcb/plugin-sdk'

export type CreateWorkflow =
  | 'auto_mix'
  | 'auto_vocal_merge'
  | 'manual_vocal_merge'
  | 'auto_then_editor'
  | 'full_manual_editor'

export interface InferenceParams extends BeforeCreateParams {
  reference_audio?: string
}

export interface VocalEnhancementOptions {
  enabled: boolean
  level: 'basic' | 'advanced'
  pitch_correction: number
  timing_alignment: number
  timbre_focus: number
  ai_eq: number
  ai_compressor: number
  ai_exciter: number
  stereo_width: number
  loudness_envelope: number
}

export interface BlendModel {
  model_id: string
  params: InferenceParams
}

export interface BlendSegment {
  start: number
  end: number
  model_id: string
  model_ids?: string[]
}

export interface CreateWorkPayload {
  title?: string
  model_id?: string
  source_path?: string | null
  params?: InferenceParams
  workflow?: CreateWorkflow
  vocal_enhancement?: VocalEnhancementOptions
  mode?: 'single' | 'multi'
  models?: BlendModel[]
  segments?: BlendSegment[]
}

export interface CreatedWork {
  [key: string]: unknown
  id: string
  title: string
  model_id?: string
  source_path?: string | null
  status?: string
  progress?: number
}

export interface PluginHostContext {
  plugin: Manifest
  page?: Page
  theme?: string
}

export interface HostMessageResult {
  ok?: boolean
  type?: 'message' | 'create_work'
  message?: string
  payload?: CreateWorkPayload
  work?: CreatedWork
  error?: string
}

export interface HostAssetResult {
  ok: boolean
  name: string
  mime: string
  data: string
  error?: string
}

export type NotifyType = 'success' | 'warning' | 'info' | 'error'

export interface PluginFullscreenResult {
  ok: true
  fullscreen: boolean
}

export interface WindowFullscreenResult {
  ok: boolean
  fullscreen?: boolean
  error?: string
}

export interface YaohuPlayerResult {
  opened: true
  url: string
}

export interface RequestOptions {
  /** Set to 0 to disable the timeout. Defaults to 30 seconds. */
  timeoutMs?: number
}

export interface PluginHost {
  getContext(): Promise<PluginHostContext>
  runAction(actionId: string, values?: Record<string, unknown>): Promise<HostMessageResult>
  createWork(payload: CreateWorkPayload): Promise<CreatedWork>
  assetData(path: string): Promise<HostAssetResult>
  assetUrl(path: string): Promise<string>
  notify(message: string, type?: NotifyType): Promise<true>
  getStorage<T = unknown>(key: string, fallback?: T): Promise<T>
  setStorage(key: string, value: unknown): Promise<true>
  removeStorage(key: string): Promise<true>
  togglePluginFullscreen(enabled?: boolean): Promise<PluginFullscreenResult>
  toggleWindowFullscreen(): Promise<WindowFullscreenResult>
  openYaohuPlayer(url: string): Promise<YaohuPlayerResult>
}

export declare function isHosted(): boolean
export declare function request<T = unknown>(
  method: string,
  payload?: Record<string, unknown>,
  options?: RequestOptions,
): Promise<T>
export declare const host: PluginHost

declare global {
  var __XB_SVCB_PLUGIN__: { token?: string } | undefined
  var XBSVCB: PluginHost | undefined
}
