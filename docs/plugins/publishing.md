# 打包、发布与市场

XB-SVCB 插件通常以 `.xbplugin` 文件发布。该文件当前是 ZIP 压缩包；GitHub 市场只是一个 JSON 索引，宿主读取索引后从 GitHub 下载对应插件包。

当前市场没有签名、哈希校验、宿主版本兼容性解析、依赖解析、版本比较、自动升级或失败回滚。发布者必须在 README 和 Release 中提供清晰信息，用户也必须自行判断来源是否可信。

## 1. 发布产物

插件源码仓库与交付给用户的插件包不是同一个概念。

```text
GitHub 仓库
├─ src/plugin.ts
├─ frontend/src/
├─ plugin.py
├─ tests/
├─ package.json
├─ README.md
└─ LICENSE
        |
        | npm run pack
        v
my-plugin.xbplugin
├─ xb-svcb-plugin.json
├─ dist/frontend/index.html     # 自定义页面插件
├─ plugin.py                    # Python/混合插件
├─ vendor/                      # 可选 Python 依赖
└─ 其他未被打包器忽略的项目文件
```

宿主只要求包中有有效清单和清单引用的运行文件。源码、测试和 README 不是宿主运行所必需，但当前 SDK 打包器会包含未显式忽略的文件。

## 2. 生成插件包

在插件项目根目录执行：

```powershell
npm install
npm run pack
```

脚手架生成的 `npm run pack` 会依次执行：

```text
TypeScript/Vue 类型检查
        -> 前端构建
        -> 清单构建
        -> 清单校验
        -> ZIP 打包
```

默认输出位于插件目录旁边：

```text
projects/
├─ my-plugin/
└─ my-plugin.xbplugin
```

也可以显式指定目录和输出：

```powershell
xb-plugin pack . .\release\my-plugin-1.0.0.xbplugin
```

直接调用 `xb-plugin pack` 不会先运行 Vite、`tsx` 或 TypeScript 检查。只有脚手架生成的 npm 脚本会先执行完整 `validate`。

## 3. 打包器包含和忽略什么

当前 SDK 自动忽略以下名称：

```text
node_modules/
.git/
.venv/
__pycache__/
.pytest_cache/
*.xbplugin
```

以下内容不会自动忽略：

- `tests/`；
- `.env` 和其他自定义密钥文件；
- 源码和 source map；
- `package-lock.json`；
- README、截图和设计素材；
- Python `vendor/`；
- 任意自定义构建缓存目录。

当前没有 `.xbpluginignore` 或包文件白名单。执行打包前必须人工检查项目目录，确保没有令牌、私钥、Cookie、测试账号、私人音频、日志或不应发布的数据。

查看包内文件时，可以使用支持 ZIP 的归档工具。至少确认：

- 只有一个 `xb-svcb-plugin.json`；
- 清单和入口位于同一插件根结构中；
- `dist/frontend/index.html` 是最新构建结果；
- Python/混合插件包含清单声明的 `.py` 入口；
- `vendor/` 只包含实际使用且许可允许再分发的依赖；
- 包内没有另一个旧 `.xbplugin`。

## 4. 当前宿主限制

| 对象 | 当前上限 | 检查时机 |
| --- | --- | --- |
| `.xbplugin` 压缩文件 | 20 MB | 本地安装或市场下载 |
| ZIP 成员声明的解压后总大小 | 50 MB | 安装 |
| `xb-svcb-plugin.json` | 512 KB | 安装和插件扫描 |
| 自定义页面入口 HTML | 2 MB | 页面打开 |
| `assetData()` / `assetUrl()` 单个资源 | 10 MB | 资源读取 |
| Python Worker 单次调用 | 30 秒 | 生命周期、动作和钩子 |
| 页面 Client 请求 | 默认 30 秒 | 页面等待宿主响应 |

SDK 打包器当前不会在创建压缩包前执行全部大小限制。发布前自行检查压缩包大小：

```powershell
Get-Item .\release\my-plugin-1.0.0.xbplugin | Select-Object Name, Length
```

入口 HTML 大小：

```powershell
Get-Item .\dist\frontend\index.html | Select-Object Name, Length
```

2 MB 的页面上限包含内联后的 Vue runtime、组件库、JavaScript 和 CSS。大型 UI 库应按需引入；图片、音频和数据文件应放在插件包中，通过 `assetUrl()` 读取，而不是全部导入页面 bundle。

`assetUrl()` 返回 Data URL，单个资源仍受 10 MB 限制。模型、数据集或大音频不适合作为插件资源发布。

## 5. 清单发布检查

发布前重新生成清单，不要直接手改 `xb-svcb-plugin.json`：

```powershell
npm run validate
```

检查这些稳定字段：

| 字段 | 发布要求 |
| --- | --- |
| `id` | 发布后保持不变；同 ID 安装会被视为替换安装 |
| `name` | 与 README、Release 和市场名称一致 |
| `version` | 每次发布递增；当前宿主只按普通字符串显示 |
| `runtime` | 与实际入口一致 |
| `permissions` | 声明插件真实使用的能力 |
| `frontend.entry` | 指向包内构建后的 HTML，不是 Vite 源文件 |
| `python.entry` | 指向包内相对 `.py` 文件 |
| `pages[].actions` | 只引用清单实际存在的动作 ID |
| Python action handler | 与 `@plugin.action()` 注册名一致 |

当前宿主不验证语义化版本，也不会因为 `1.10.0` 大于 `1.9.0` 自动提示更新。仍建议作者使用 SemVer，方便用户和 Release 页面理解变更。

## 6. Python 依赖发布

宿主使用专用 Python 3.10 运行时，只保证标准库和 `xb_svcb_plugin`。其他 Python 依赖写入固定版本的 `requirements.txt`：

```powershell
httpx==0.28.1
```

发布前确认：

- 依赖及其传递依赖允许再分发；
- 仓库和插件包保留要求的许可证或版权声明；
- `npm run pack` 使用 Python 3.10 成功生成包内 `vendor/`；
- 没有把开发机 `.venv` 整体复制到 `vendor/`；
- 没有安装时自动执行 `pip install` 的脚本；
- `vendor/` 加入后仍满足 20 MB/50 MB 限制。

SDK 只在发布者执行 `npm run pack` 时解析 `requirements.txt`；宿主和市场安装时不会联网安装缺失依赖，也没有插件间依赖声明。

## 7. GitHub Release

推荐一个插件使用一个公开 GitHub 仓库，仓库名称可以采用：

```text
xb-svcb-plugin-<name>
```

建议仓库至少包含：

```text
README.md
LICENSE
package.json
package-lock.json
src/plugin.ts
frontend/                   # 前端/混合插件
vite.config.ts              # 自定义 TypeScript 页面
plugin.py                   # Python/混合插件
tests/
xb-svcb-plugin.json         # 可选提交，但必须与源码同步
dist/frontend/index.html    # 可选提交，但 Release 包必须包含
```

README 至少说明：

- 插件功能和界面截图；
- 插件 ID、版本和运行类型；
- 需要的 XB-SVCB 版本，由作者人工测试并声明；
- 每项权限的使用原因；
- Python 代码会以当前用户权限运行；
- 网络访问、读写目录和外部进程行为；
- 配置项和数据目录；
- 第三方依赖及许可证；
- 安装、启用、更新和卸载方式；
- 卸载会删除 `plugin-data/<plugin-id>`；
- 已知限制和未覆盖平台。

发布步骤：

1. 更新 `src/plugin.ts` 中的插件版本。
2. 在干净依赖环境执行 `npm run validate` 和全部单元测试。
3. 执行 `npm run pack`。
4. 使用最终包完成真实安装测试。
5. 创建与版本一致的 Git tag，例如 `v1.0.0`。
6. 创建 GitHub Release，并上传 `.xbplugin` 资产。
7. 从 Release 页面实际下载一次资产并安装，确认不是 HTML 错误页。
8. 最后更新 `market.json`。

Release 资产名称建议带版本：

```text
my-plugin-1.0.0.xbplugin
```

不要复用同一个 URL 静默替换内容。保留旧 Release 资产，便于用户在手动回退时重新安装旧版本。

## 8. `market.json`

市场索引是包含 `plugins` 数组的 JSON 对象：

```json
{
  "plugins": [
    {
      "id": "com.example.hybrid-cover",
      "name": "混合翻唱助手",
      "version": "1.0.0",
      "description": "Vue 页面收集参数，Python 生成翻唱任务。",
      "author": "Your Name",
      "bundle_url": "https://github.com/OWNER/REPO/releases/download/v1.0.0/hybrid-cover-1.0.0.xbplugin"
    }
  ]
}
```

当前字段处理规则：

| 字段 | 是否必须 | 当前行为 |
| --- | --- | --- |
| `id` | 是 | 必须符合 3-64 位小写插件 ID 格式，否则整条记录被跳过 |
| `bundle_url` | 是 | 必须是允许的 GitHub HTTPS 地址，否则整条记录被跳过 |
| `name` | 否 | 缺失时市场卡片使用 `id` |
| `version` | 否 | 缺失时显示为空；宿主不比较版本 |
| `description` | 否 | 缺失时显示默认提示 |
| `author` | 否 | 缺失时显示“未知作者” |

未知字段会被忽略。无效记录会被跳过，市场页面不会逐条显示索引校验错误。若顶层不是对象、`plugins` 不是数组或 JSON 无法解析，市场会为空或返回读取失败。

市场中的 `id`、`name` 和 `version` 只用于展示。当前安装流程不会把市场记录与下载包的清单交叉校验；真正安装的插件 ID 和版本来自包内 `xb-svcb-plugin.json`。发布者必须确保二者一致。

## 9. 市场索引地址

把 `market.json` 提交到公开 GitHub 仓库后，在插件中心填写 Raw 地址：

```text
https://raw.githubusercontent.com/OWNER/REPO/main/market.json
```

当前宿主只接受 HTTPS，并允许以下 GitHub 主机范围：

```text
github.com
api.github.com
*.github.com
githubusercontent.com
*.githubusercontent.com
```

索引请求会跟随跳转，但最终 URL 仍必须位于允许的 GitHub 主机。索引请求超时为 20 秒。

插件包下载同样要求起始 URL 和最终跳转 URL 都属于允许的 GitHub HTTPS 主机，下载超时为 30 秒。GitHub Release 常见的 `githubusercontent.com` 资产跳转已被允许。

当前宿主不会携带 GitHub 登录凭据、Personal Access Token 或私有仓库授权。需要认证的私有仓库和私有 Release 不能视为受支持的市场来源。

## 10. 当前市场没有什么

以下能力当前尚未实现，发布文档和插件 README 不应暗示宿主已经提供：

### 10.1 没有签名或发布者身份验证

宿主不会验证 GPG、Sigstore、GitHub Artifact Attestation 或其他代码签名。GitHub 用户名、仓库名和 `author` 都不构成密码学身份保证。

### 10.2 没有哈希校验

`market.json` 没有 `sha256` 等受宿主识别的字段。宿主下载后不会把文件摘要与索引比较。

发布者可以在 Release 说明中提供 SHA-256 供用户手工核对：

```powershell
Get-FileHash .\my-plugin-1.0.0.xbplugin -Algorithm SHA256
```

即使把摘要添加为市场自定义字段，当前宿主也会忽略它。

### 10.3 没有宿主或 SDK 兼容性解析

清单和市场目前没有宿主识别的 `min_app_version`、`max_app_version`、`sdk_version` 或 API schema 版本。插件中心不会阻止用户在未测试的 XB-SVCB 版本中安装插件。

作者只能在 README、Release 说明和测试记录中人工声明已验证版本。应用或 SDK 发生不兼容变化时，需要发布新插件版本并说明迁移要求。

### 10.4 没有版本比较和自动升级

插件中心不会比较市场版本与已安装版本，不会显示“可更新”，也不会后台下载或自动升级。市场卡片当前始终提供“安装”操作。

安装同 ID 包会直接替换插件代码并把插件设为关闭；`plugin-data/<plugin-id>` 会保留。版本号变大、变小或相同都不会改变这一行为。

### 10.5 没有依赖解析

市场不会安装 npm 依赖、Python requirements、系统工具或其他插件。SDK 打包结果必须自带运行所需前端 bundle 和允许再分发的 Python `vendor/` 内容。

### 10.6 没有自动回滚

替换安装若在入口或文件校验阶段失败，宿主会恢复旧插件代码。启用后才暴露的业务错误仍需要作者发布修复版本；插件数据是否能被旧版本读取由插件作者负责。

## 11. 更新、回退与数据

同 ID 安装的当前行为：

```text
旧插件代码目录 -> 被新包替换
插件开关       -> 重置为关闭
plugin-data    -> 保留
版本比较       -> 不执行
数据迁移       -> 不自动执行
```

如果新版本改变配置格式，应在 `on_enable` 中执行可重复的数据迁移，并在迁移前校验旧数据。由于 Worker 每次调用都会重新加载入口，迁移完成状态必须写入 `ctx.config`。

回退旧包时宿主不会反向迁移配置。破坏性配置升级应先备份旧数据，或由插件提供导出/导入动作。

卸载与更新不同：卸载会删除插件代码和 `plugin-data/<plugin-id>`，且没有自动恢复。

## 12. 安全发布

前端页面在 `sandbox="allow-scripts"` iframe 中运行，但仍能通过获准的 Client API 创建任务、执行插件动作和读取插件自身资源。Python/混合插件会以当前用户权限执行，Worker 不是安全沙箱。

权限声明当前用于展示、审计和用户提示，不是操作系统访问控制。发布者应遵守以下要求：

- 只声明实际需要的权限，并在 README 解释原因；
- 不读取与插件功能无关的文件、环境变量、浏览器数据或凭据；
- 不静默下载并执行程序；
- 不把密钥写入清单、页面 bundle、Python 源码或市场索引；
- 网络请求使用 HTTPS，并明确发送了哪些用户数据；
- 外部进程使用固定可审计参数，避免拼接未经校验的输入；
- 对 `vendor/` 做许可证和供应链审查；
- 公开源码，使用户可以对照 Release 资产审查。

## 13. 发布检查表

### 代码与测试

- 从干净依赖安装完成构建、类型检查和测试；
- Vue 页面在浏览器预览和真实宿主中均检查过；
- Python handler、钩子、配置和异常路径有测试；
- 最终 `.xbplugin` 完成全新安装和同 ID 更新检查。

### 包内容

- 清单 ID 稳定，版本已更新；
- 包内只有一个清单；
- 前端和 Python 入口都存在；
- 没有 `node_modules`、虚拟环境、缓存、旧包或秘密数据；
- 压缩包、解压内容、HTML 和资源满足当前限制；
- 第三方许可证随包或仓库提供。

### GitHub

- tag、Release、清单和市场版本一致；
- `bundle_url` 指向真实 Release 资产；
- 从 Release URL 下载的文件可被 XB-SVCB 安装；
- README 写明权限、数据、依赖、兼容性和卸载行为；
- `market.json` 是有效 JSON，记录 ID 与包内清单一致；
- 已明确当前没有签名、哈希验证、兼容性解析和自动升级。

发布前测试流程见[测试与调试](testing.md)。
