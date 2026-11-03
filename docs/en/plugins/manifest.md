[简体中文](../../plugins/manifest.md) | **English** | [日本語](../../ja/plugins/manifest.md)

# Manifest, Pages, and Actions

`xb-svcb-plugin.json` is the host's plugin entry point. Maintain `src/plugin.ts` and generate JSON instead of editing the build output.

## Minimal Manifest

```json
{"id":"com.example.hello","name":"Hello Plugin","version":"1.0.0","description":"","author":"","runtime":"frontend","python":{},"frontend":{},"permissions":[],"pages":[],"actions":[],"workflow":{}}
```

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'
const app = plugin('com.example.hello', 'Hello Plugin', '1.0.0')
await writeManifest(app, '.')
```

## Top-level Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | Yes | 3-64 lowercase characters matching `^[a-z0-9][a-z0-9._-]{2,63}$` |
| `name` / `version` | Yes | Display name (80 chars) and version (32 chars) |
| `description` / `author` | No | 400 / 80 characters |
| `runtime` | Yes | `frontend`, `python`, or `hybrid` |
| `python` / `frontend` | Yes | Runtime entry configuration |
| `permissions` | Yes | Declared capabilities |
| `pages` / `actions` | Yes | UI metadata and callable actions |
| `workflow` | Yes | Static cover-workflow extension |

Never change a published ID. Python entry paths must be relative `.py` files without `..`; frontend entries must be relative `.html`/`.htm`, normally `dist/frontend/index.html`.

## Runtime Builders

```ts
plugin('com.example.frontend', 'Frontend').frontend('dist/frontend/index.html')
plugin('com.example.python', 'Python').python('plugin.py')
plugin('com.example.hybrid', 'Hybrid').hybrid('plugin.py').frontendEntry('dist/frontend/index.html')
```

`.frontend()` sets frontend runtime and clears Python configuration. `.python()` and `.hybrid()` default to `plugin.py` and add `python.execute`. `.frontendEntry()` changes only the page entry.

## Pages and Fields

```ts
.page('home', 'Quick Cover', {
  description: 'Enter parameters and create a task.',
  fields: [],
  actions: ['create'],
})
```

Without `frontend.entry`, the host renders `fields` and `actions`. With an entry, it loads the custom page and hides the declarative form. Custom pages receive `context.page`; they may call any top-level action regardless of `page.actions`. The center normally opens only `pages[0]`, so implement tabs or memory routing inside one Vue entry.

```ts
import { fields } from '@xb-svcb/plugin-sdk'

const pageFields = [
  fields.text('title', 'Title', { default: 'My cover' }),
  fields.textarea('notes', 'Notes', { placeholder: 'Optional' }),
  fields.number('pitch', 'Pitch', { default: 0 }),
  fields.switch('enhance', 'Enhance', { default: true }),
  fields.select('device', 'Device', [
    { label: 'Automatic', value: 'auto' },
    { label: 'CPU', value: 'cpu' },
  ], { default: 'auto' }),
]
```

Every field has `id`, `label`, `type`, optional `default`, and optional `help`; all except switches support `placeholder`. Selects require non-empty `{label, value}` options. TypeScript enforces number, boolean, and option-compatible defaults.

## Actions

```ts
.message('hello', 'Say hello', 'Hello, {{name}}!')
.createWork('create', 'Create cover', {
  source_path: '{{source_path}}', model_id: '{{model_id}}',
  title: '{{title}}', workflow: 'auto_mix', params: { pitch: '{{pitch}}' },
})
.pythonAction('analyse', 'Analyse', 'analyse_values')
```

Message actions return `{type:'message', message}`. Create-work actions return `{type:'create_work', payload}` and the host invokes the real task API. For Python actions, the action ID is called by the page and the handler name must match `@plugin.action()`; they require Python/hybrid runtime.

Actions share `id`, `label`, and `type`. IDs use plugin-ID rules; handler names are Python identifiers up to 64 characters.

## Placeholder Interpolation

Only explicit `{{fieldId}}` placeholders are supported. A whole-string placeholder retains number/boolean type; embedded values become strings. Names start with a letter, contain only letters, digits, and underscores, and are at most 41 characters. Missing values leave the placeholder intact. Objects and arrays are processed recursively. Validate required fields before submission.

## Static `beforeCreate`

```ts
.beforeCreate({ f0_method: 'rmvpe', pitch: 0, device: 'auto' })
```

It fills missing `params` without overwriting user choices. Allowed keys are `pitch`, `f0_method`, `index_rate`, `rms_mix`, `uvr_model`, `diffusion_ratio`, `device`, `protect`, `filter_radius`, `rvc_version`, `ddsp_infer_steps`, `ddsp_formant_shift`, and `speaker`. Use a Python `before_create` hook for conditions, full-request changes, or batches.

## Permissions and Builder API

Declare `python.execute`, `filesystem.plugin`, `filesystem.data`, `network`, `process`, or `environment`. Python/hybrid adds `python.execute`. These are disclosure and audit metadata, not OS sandbox controls.

```text
plugin(id, name, version?) -> PluginBuilder
.description() .author() .frontend() .frontendEntry() .python() .hybrid()
.permission() .page() .action() .message() .createWork() .pythonAction()
.beforeCreate() .build()
```

Standalone factories include `page`, `messageAction`, `createWorkAction`, and `pythonAction`. `.build()` returns a deep JSON copy without validation. `writeManifest()` validates, creates the destination, writes the manifest, and returns its absolute path.

## Validation Boundaries

The SDK validates metadata, IDs, enums, field/action types, path shapes, `python.execute`, select options, Python handler syntax, and the static patch allowlist. It does not verify files exist, Python imports, handler registration, duplicate IDs, page action references, frontend execution, package sizes, or host business requirements. Build, package, and install in a real host.

Do not call `.frontend()` after `.hybrid()`; use `.frontendEntry()`. Always pass `{fields: []}` when creating an empty page. Field IDs containing `.` or `-` cannot be interpolation names.
