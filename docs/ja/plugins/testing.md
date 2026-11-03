[简体中文](../../plugins/testing.md) | [English](../../en/plugins/testing.md) | **日本語**

# Pluginのテストとdebug

一つのcommandだけでは動作を保証できません。source、build output、archive、host導入、runtime call、実業務payloadを別々に検証します。

## Test level

| Level | 確認できること | 確認できないこと |
| --- | --- | --- |
| `typecheck` | Vue/TypeScript型 | runtime / manifest validity |
| `build` | frontendとmanifest生成 | host導入 |
| `xb-plugin validate` | manifest形式とallowlist | entry存在、Python import、action登録 |
| `pack` | archive生成 | 全size制限、secret不在 |
| Host install | ZIP safety、size、manifest、entry | action/task payload |
| Runtime acceptance | page、Python、hook、task作成 | 他hardware/app version |

```powershell
npm run typecheck
npm run build
npm run validate
npm run pack
```

scaffoldの`validate`はtypecheck、frontend/manifest build、manifest検証です。scaffold経由`pack`はvalidateしますが、CLIを直接呼ぶとsource buildしません。`.env`、test、source map、custom cacheは自動除外されないためfinal ZIPを確認します。

## Manifest unit test

manifest builderをfunctionとしてexportし、runtime、permission、page、action、validationをassertします。

```ts
import { describe, expect, it } from 'vitest'
import { validateManifest } from '@xb-svcb/plugin-sdk'
import { buildPlugin } from '../src/plugin'

describe('manifest', () => {
  it('is valid', () => {
    const manifest = buildPlugin().build()
    expect(validateManifest(manifest)).toEqual({ ok: true, errors: [] })
    expect(manifest.id).toBe('com.example.plugin')
  })
})
```

testからimportするmoduleでfile生成をside effectにせず、`writeManifest()`は専用build entryへ置きます。

## Page Client mock

protocol testではparent `message` listenerでrequest ID/methodを取得し、token付きresponseをdispatchします。成功、host reject、timeout、不正response、並行request、cleanupを検証します。protocolが対象なら`host.runAction()`だけをmockしないでください。

component testは`@xb-svcb/plugin-sdk/vue`をmockしてrefとasync spyを返します。

```ts
vi.mock('@xb-svcb/plugin-sdk/vue', () => ({
  usePluginHost: () => ({
    hosted: ref(true), loading: ref(false), error: ref(),
    runAction: vi.fn().mockResolvedValue({ type: 'message', message: 'ok' }),
  }),
}))
```

必須validation、loading/disabled、resolve、reject、browser preview、narrow layout、keyboard、重複通知なしを確認します。jsdomではsandbox、Data URL media、実host messageを保証できません。

## Browser preview

`npm run dev`はrender、local form state、client validation、responsive layout、theme media queryを確認します。`isHosted()`はfalseなのでcontext、action、storage、resource、fullscreen、player、Pythonは確認できません。

## Python unit test

純functionを分離し、temporary contextでhandlerをtestします。

```python
from pathlib import Path
from xb_svcb_plugin import PluginContext
ctx = PluginContext(
    plugin_id="com.example.plugin", plugin_dir=Path("."),
    data_dir=tmp_path, config={},
)
```

sync/async action、`ActionResult` normalize、不足・不正値、idempotent hook、unknown field保持、config保存、data path、exceptionを検証します。hostと同じPython 3.12 architectureでsyntax/import testします。local testだけではpackage `vendor/`、entry path、worker timeout、host task validationを保証しません。

## 実host受け入れ

1. final archiveをpackし内容とsizeを確認。
2. Plugin Centerへ導入しruntime/permissionを確認。
3. 初期無効を確認しglobalと個別switchを有効化。
4. page、全action、resource、storage、error pathを確認。
5. task actionは短い実taskを作りhookが一度適用されることを確認。

同ID更新ではcode置換、plugin無効化、設定/data保持、再有効時のidempotent migrationを確認します。uninstallはcode/dataを削除するため、必要dataは先にexportします。

## Worker debug

`py_compile` -> local import -> handler unit test -> manifest action/handler mapping -> final archive entry/vendor -> lifecycle -> installed action -> app logの順で確認します。各callはfresh processです。local venvだけにある未宣言依存が典型原因です。

## Release gate

typecheck、unit test、validate、archive確認、fresh install、同ID更新、enable/disable、全action/hook、実task、negative path、timeout、size、license、実GitHub Release URLからの導入を必須にします。Marketplaceは互換性を強制しないため、検証したXB-SVCB/SDK versionを記録してください。
