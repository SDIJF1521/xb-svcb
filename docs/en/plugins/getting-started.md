[简体中文](../../plugins/getting-started.md) | **English** | [日本語](../../ja/plugins/getting-started.md)

# Quick Start

Create, validate, package, and install a Vue 3 frontend plugin.

## Requirements

- Node.js `^20.19.0` or `>=22.12.0`, npm, and an XB-SVCB build with plugin support.
- Python 3.12.x for Python/hybrid plugins. The host supplies the Python SDK; local tests install `plugin-sdk/python` manually.

```powershell
node --version
npm --version
python --version
```

Inside the XB-SVCB repository use `node plugin-sdk\bin\xb-plugin.mjs`. After npm publication use `npx @xb-svcb/plugin-sdk`.

## Create a Project

```powershell
npx @xb-svcb/plugin-sdk create my-first-plugin `
  --id com.example.my-first-plugin `
  --name "My First Plugin" `
  --type frontend `
  --author "Your Name"
```

| Option | Required | Default | Meaning |
| --- | --- | --- | --- |
| `<dir>` | Yes | none | New project directory |
| `--id` | Yes | none | Stable 3-64 character lowercase plugin ID |
| `--name` | Yes | none | Display name |
| `--type` | No | `frontend` | `frontend`, `python`, or `hybrid` |
| `--language` | No | `ts` | `ts` or `js` |
| `--framework` | No | `vue` for TS frontend | `vue` or `vanilla` |
| `--version` | No | `1.0.0` | Initial version |
| `--author` | No | empty | Author or organization |

Vue requires TypeScript; `--language js --framework vue` is rejected. Common alternatives:

```powershell
npx @xb-svcb/plugin-sdk create vanilla-plugin --id com.example.vanilla --name "Vanilla" --framework vanilla
npx @xb-svcb/plugin-sdk create python-plugin --id com.example.python --name "Python" --type python
npx @xb-svcb/plugin-sdk create hybrid-plugin --id com.example.hybrid --name "Hybrid" --type hybrid
npx @xb-svcb/plugin-sdk create js-plugin --id com.example.javascript --name "JS" --language js
```

## Generated Vue Project

```text
my-first-plugin/
├─ package.json
├─ tsconfig.json
├─ vite.config.ts
├─ src/plugin.ts                  # manifest source
├─ frontend/index.html
├─ frontend/src/main.ts
├─ frontend/src/App.vue
├─ frontend/src/style.css
├─ dist/frontend/index.html      # generated
└─ xb-svcb-plugin.json           # generated
```

Hybrid projects also contain `plugin.py`; Python-only projects omit Vite and `frontend/`. Do not edit `dist/` or `xb-svcb-plugin.json` by hand.

## Install and Edit

```powershell
cd my-first-plugin
npm install
```

Edit `frontend/src/App.vue` for UI and `src/plugin.ts` for metadata:

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.my-first-plugin', 'My Cover Workspace', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('A cover utility built with Vue.')
  .author('Your Name')

await writeManifest(app, '.')
```

The ID is the stable installation, configuration, and upgrade key. Do not change it after publication.

## Preview, Build, and Package

```powershell
npm run dev
npm run typecheck
npm run build
npm run validate
npm run pack
```

| Command | Result |
| --- | --- |
| `dev` | Vite preview; no host token or real host calls |
| `typecheck` | `vue-tsc --noEmit` |
| `build:frontend` | Single-file `dist/frontend/index.html` |
| `build:manifest` | `xb-svcb-plugin.json` from `src/plugin.ts` |
| `build` | Frontend and manifest |
| `validate` | Typecheck, build, and manifest validation |
| `pack` | Validation plus `.xbplugin` archive |

In a normal browser `isHosted()` is false. Test component state and layout there, then test real actions in XB-SVCB.

## Install and Verify

Open **Plugin Center**, enable global plugins, install the local `.xbplugin`, review runtime and permissions, enable the plugin, and open it. Reinstalling the same ID replaces the code and disables it, so enable it again.

Verify metadata, page layout, console, host-mode UI, `runAction()`, disabled-plugin rejection, and global-switch rejection.

CLI validation does not prove entry files exist in the final archive, Python imports and handlers work, package size is valid, or task payloads satisfy host rules. Complete at least one real installation before release.

Next: [Vue Pages](frontend-vue.md), [Manifest](manifest.md), [Client API](client-api.md), [Hybrid Plugins](hybrid.md), and [Testing](testing.md).
