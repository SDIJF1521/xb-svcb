[简体中文](../../plugins/getting-started.md) | [English](../../en/plugins/getting-started.md) | **日本語**

# Quick Start

Vue 3 frontend pluginを作成、検証、package化、導入します。

## 必要環境

- Node.js `^20.19.0`または`>=22.12.0`、npm、plugin対応XB-SVCB。
- Python/hybridにはPython 3.12.x。hostはPython SDKを提供し、local testだけ`plugin-sdk/python`を手動導入します。

```powershell
node --version
npm --version
python --version
```

XB-SVCB repository内では`node plugin-sdk\bin\xb-plugin.mjs`、npm公開後は`npx @xb-svcb/plugin-sdk`を使います。

## Project作成

```powershell
npx @xb-svcb/plugin-sdk create my-first-plugin `
  --id com.example.my-first-plugin `
  --name "初めてのプラグイン" `
  --type frontend `
  --author "Your Name"
```

| Option | 必須 | 既定 | 内容 |
| --- | --- | --- | --- |
| `<dir>` | Yes | なし | 新project directory |
| `--id` | Yes | なし | 3-64文字の安定したlowercase ID |
| `--name` | Yes | なし | 表示名 |
| `--type` | No | `frontend` | `frontend`、`python`、`hybrid` |
| `--language` | No | `ts` | `ts`または`js` |
| `--framework` | No | TS frontendは`vue` | `vue`または`vanilla` |
| `--version` | No | `1.0.0` | 初期version |
| `--author` | No | 空 | 作者・組織 |

VueはTypeScript必須で、`--language js --framework vue`は拒否されます。

```powershell
npx @xb-svcb/plugin-sdk create vanilla-plugin --id com.example.vanilla --name "Vanilla" --framework vanilla
npx @xb-svcb/plugin-sdk create python-plugin --id com.example.python --name "Python" --type python
npx @xb-svcb/plugin-sdk create hybrid-plugin --id com.example.hybrid --name "Hybrid" --type hybrid
npx @xb-svcb/plugin-sdk create js-plugin --id com.example.javascript --name "JS" --language js
```

## 生成されるVue project

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

hybridには`plugin.py`も生成され、Python-onlyにはViteと`frontend/`がありません。`dist/`とmanifestを手動編集しないでください。

## 導入と編集

```powershell
cd my-first-plugin
npm install
```

UIは`frontend/src/App.vue`、metadataは`src/plugin.ts`を変更します。

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.my-first-plugin', 'カバー作業ツール', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('Vueで作成したカバーツール。')
  .author('Your Name')

await writeManifest(app, '.')
```

IDは導入、設定、更新の安定keyです。公開後は変更しないでください。

## Preview、build、package

```powershell
npm run dev
npm run typecheck
npm run build
npm run validate
npm run pack
```

| Command | 結果 |
| --- | --- |
| `dev` | Vite preview。host tokenと実host callなし |
| `typecheck` | `vue-tsc --noEmit` |
| `build:frontend` | single-file `dist/frontend/index.html` |
| `build:manifest` | `src/plugin.ts`からmanifest生成 |
| `build` | frontendとmanifest |
| `validate` | typecheck、build、manifest検証 |
| `pack` | 検証と`.xbplugin`作成 |

通常browserでは`isHosted()`がfalseです。layoutとstateをpreviewし、実actionはXB-SVCBで検証します。

## 導入と検証

「Plugin Center」でglobal pluginを有効化し、`.xbplugin`を導入し、runtimeとpermissionを確認してpluginを有効化します。同一ID再導入ではcodeを置換して無効になるため再度有効化してください。

metadata、page layout、console、host mode表示、`runAction()`、plugin無効時とglobal無効時の拒否を確認します。

CLI検証だけでは最終archiveのentry、Python importとhandler、package size、task payloadの業務規則を保証しません。公開前に実導入を完了してください。

次: [Vueページ](frontend-vue.md)、[Manifest](manifest.md)、[Client API](client-api.md)、[Hybrid](hybrid.md)、[テスト](testing.md)。
