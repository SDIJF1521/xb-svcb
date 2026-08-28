export type FieldType = 'text' | 'number' | 'select' | 'switch' | 'textarea'
export type ActionType = 'message' | 'create_work' | 'python'
export type PluginRuntime = 'frontend' | 'python' | 'hybrid'
export type PluginPermission =
  | 'python.execute'
  | 'filesystem.plugin'
  | 'filesystem.data'
  | 'network'
  | 'process'
  | 'environment'

export type SelectValue = string | number

export interface FieldOption<Value extends SelectValue = SelectValue> {
  label: string
  value: Value
}

export interface CommonFieldOptions {
  placeholder?: string
  help?: string
}

export interface TextField extends CommonFieldOptions {
  id: string
  label: string
  type: 'text'
  default?: string
}

export interface TextareaField extends CommonFieldOptions {
  id: string
  label: string
  type: 'textarea'
  default?: string
}

export interface NumberField extends CommonFieldOptions {
  id: string
  label: string
  type: 'number'
  default?: number
}

export interface SwitchField {
  id: string
  label: string
  type: 'switch'
  default?: boolean
  help?: string
}

export interface SelectField<Value extends SelectValue = SelectValue> {
  id: string
  label: string
  type: 'select'
  options: FieldOption<Value>[]
  default?: Value
  placeholder?: string
  help?: string
}

export type Field = TextField | TextareaField | NumberField | SwitchField | SelectField

export type TextFieldOptions = Omit<TextField, 'id' | 'label' | 'type'>
export type TextareaFieldOptions = Omit<TextareaField, 'id' | 'label' | 'type'>
export type NumberFieldOptions = Omit<NumberField, 'id' | 'label' | 'type'>
export type SwitchFieldOptions = Omit<SwitchField, 'id' | 'label' | 'type'>
export type SelectFieldOptions<Value extends SelectValue = SelectValue> = Omit<
  SelectField<Value>,
  'id' | 'label' | 'type' | 'options'
>

export interface PageConfig {
  description?: string
  fields: readonly Field[]
  actions?: readonly string[]
}

export interface Page {
  id: string
  title: string
  description?: string
  fields: Field[]
  actions?: string[]
}

export interface FrontendConfig {
  entry?: string
}

export interface PythonConfig {
  entry?: string
  /** Relative requirements file bundled into vendor/ by packPlugin(). */
  requirements?: string
  /** Relative dependency directory. Defaults to vendor. */
  vendor?: string
}

export interface MessageAction {
  id: string
  label: string
  type: 'message'
  message: string
}

export interface CreateWorkAction {
  [key: string]: unknown
  id: string
  label: string
  type: 'create_work'
  payload: Record<string, unknown>
}

export interface PythonAction {
  [key: string]: unknown
  id: string
  label: string
  type: 'python'
  handler: string
}

export type Action = MessageAction | CreateWorkAction | PythonAction

export interface BeforeCreateParams {
  pitch?: number
  f0_method?: string
  index_rate?: number
  rms_mix?: number
  uvr_model?: string
  diffusion_ratio?: number
  device?: string
  protect?: number
  filter_radius?: number
  rvc_version?: string
  ddsp_infer_steps?: number
  ddsp_formant_shift?: number
  speaker?: string | number
}

export interface Manifest {
  id: string
  name: string
  version: string
  description: string
  author: string
  runtime: PluginRuntime
  python: PythonConfig
  frontend: FrontendConfig
  permissions: PluginPermission[]
  pages: Page[]
  actions: Action[]
  workflow: { before_create?: { params: BeforeCreateParams } }
}

export interface ValidationResult {
  ok: boolean
  errors: string[]
  manifest?: Manifest
}

export interface PluginBuilder {
  description(value: string): PluginBuilder
  author(value: string): PluginBuilder
  frontend(config?: string | FrontendConfig): PluginBuilder
  frontendEntry(entry: string, config?: Omit<FrontendConfig, 'entry'>): PluginBuilder
  python(entry?: string, config?: Omit<PythonConfig, 'entry'>): PluginBuilder
  hybrid(entry?: string, config?: Omit<PythonConfig, 'entry'>): PluginBuilder
  permission(...values: (PluginPermission | readonly PluginPermission[])[]): PluginBuilder
  page(value: Page): PluginBuilder
  page(id: string, title: string, configure?: PageConfig | PageConfigurator): PluginBuilder
  action(value: Action): PluginBuilder
  message(id: string, label: string, text: string): PluginBuilder
  createWork(
    id: string,
    label: string,
    payload: Record<string, unknown>,
    options?: Record<string, unknown>,
  ): PluginBuilder
  pythonAction(
    id: string,
    label: string,
    handler?: string,
    options?: Record<string, unknown>,
  ): PluginBuilder
  beforeCreate(params: BeforeCreateParams): PluginBuilder
  build(): Manifest
}

export interface FieldFactories {
  text(id: string, label: string, options?: TextFieldOptions): TextField
  number(id: string, label: string, options?: NumberFieldOptions): NumberField
  select<Value extends SelectValue>(
    id: string,
    label: string,
    options: readonly FieldOption<Value>[],
    config?: SelectFieldOptions<Value>,
  ): SelectField<Value>
  switch(id: string, label: string, options?: SwitchFieldOptions): SwitchField
  textarea(id: string, label: string, options?: TextareaFieldOptions): TextareaField
}

export type PageConfigurator = (helpers: { fields: FieldFactories }) => PageConfig

export declare const fields: FieldFactories
export declare function page(id: string, title: string, configure?: PageConfig | PageConfigurator): Page
export declare function messageAction(id: string, label: string, message: string): MessageAction
export declare function createWorkAction(
  id: string,
  label: string,
  payload: Record<string, unknown>,
  options?: Record<string, unknown>,
): CreateWorkAction
export declare function pythonAction(
  id: string,
  label: string,
  handler?: string,
  options?: Record<string, unknown>,
): PythonAction
export declare function plugin(id: string, name: string, version?: string): PluginBuilder
export declare function validateManifest(input: unknown): ValidationResult
export declare function validatePluginDirectory(directory: string): Promise<ValidationResult>
export declare function writeManifest(manifest: Manifest | PluginBuilder, directory: string): Promise<string>
export declare function packPlugin(directory: string, output?: string): Promise<string>
export declare function createPlugin(options: {
  directory: string
  id: string
  name: string
  version?: string
  description?: string
  author?: string
}): Promise<PluginBuilder>
export declare const allowedParams: ReadonlySet<keyof BeforeCreateParams>
