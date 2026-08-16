import type { ComputedRef, DeepReadonly, Ref } from 'vue'

import type {
  CreateWorkPayload,
  CreatedWork,
  HostAssetResult,
  HostMessageResult,
  NotifyType,
  PluginFullscreenResult,
  PluginHostContext,
  WindowFullscreenResult,
  YaohuPlayerResult,
} from '@xb-svcb/plugin-sdk/client'
import type { Manifest, Page } from '@xb-svcb/plugin-sdk'

export interface UsePluginHostOptions {
  /** Load plugin, page and theme context when the component is mounted. */
  loadContext?: boolean
}

export interface UsePluginHostResult {
  hosted: DeepReadonly<Ref<boolean>>
  context: DeepReadonly<Ref<PluginHostContext | null>>
  plugin: ComputedRef<Manifest | undefined>
  page: ComputedRef<Page | undefined>
  theme: ComputedRef<string>
  loading: DeepReadonly<Ref<boolean>>
  error: DeepReadonly<Ref<Error | null>>
  refreshContext(): Promise<PluginHostContext | undefined>
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
  clearError(): void
}

export declare function usePluginHost(options?: UsePluginHostOptions): UsePluginHostResult
