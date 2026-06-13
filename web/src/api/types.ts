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
}

export interface CreateWorkPayload {
  title?: string
  model_id?: string
  source_path?: string | null
  params?: InferenceParams
}
