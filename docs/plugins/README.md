# XB-SVCB 插件开发文档

这套文档面向插件作者。完成这里的教程不需要阅读 XB-SVCB 主项目源码；清单 SDK、页面 Client、Vue composable、Python SDK、打包格式、安装行为和当前运行限制都在文档中说明。

旧版单文件指南仍保留在[插件开发完整指南](../plugin-development.md)，适合全文搜索。日常开发建议使用下面的分章节文档。

## 从哪里开始

| 目标 | 建议阅读顺序 | 最终产物 |
| --- | --- | --- |
| 第一次写插件 | [快速开始](getting-started.md) -> [Vue 页面](frontend-vue.md) | 可安装的 Vue 前端插件 |
| 做翻唱参数工具 | [快速开始](getting-started.md) -> [清单与动作](manifest.md) | 声明式表单或创建任务动作 |
| 执行 Python | [Python 插件](python.md) -> [测试与调试](testing.md) | Python 动作或流程钩子 |
| Vue 调用 Python | [混合插件](hybrid.md) -> [页面 Client API](client-api.md) | Vue + Python 混合插件 |
| 发布到市场 | [打包、发布与市场](publishing.md) | GitHub Release 与 `market.json` |

如果你只想查某个函数、字段或限制，直接打开 [API 速查](reference.md)。如果你遇到安装、启用或动作执行失败，从 [测试与调试](testing.md) 开始更快。

## 文档目录

- [快速开始](getting-started.md)：环境、CLI 参数、目录结构、构建、安装和第一个修改。
- [Vue 3 自定义页面](frontend-vue.md)：`App.vue`、组件、composable、状态、主题、路由、资源和 UI 库。
- [清单、页面与动作](manifest.md)：所有清单字段、字段组件、动作、插值、工作流补丁与校验规则。
- [页面 Client API](client-api.md)：无框架 Client 与 Vue `usePluginHost()` 的参数、返回值、错误和完整示例。
- [Python 插件](python.md)：动作、钩子、生命周期、上下文、配置、异步函数、依赖和 Worker 模型。
- [混合插件](hybrid.md)：Vue 收集输入、Python 处理、创建翻唱任务和完整项目模板。
- [测试与调试](testing.md)：类型检查、单元测试、浏览器预览、宿主调试、日志和常见故障定位。
- [打包、发布与市场](publishing.md)：包内容、限制、GitHub Release、市场索引、升级与发布检查表。
- [API 速查](reference.md)：TypeScript、Client、Vue、Python、CLI、包格式、运行限制和常见失败点。
## 一次完整开发流程

```text
创建脚手架
  -> 修改 src/plugin.ts 或 build.mjs
  -> 编写 frontend/ 页面或 plugin.py 后端
  -> npm install
  -> npm run dev                # 仅前端预览
  -> npm run typecheck
  -> npm run validate
  -> npm run pack
  -> 在插件中心安装 .xbplugin
  -> 开启全局插件功能
  -> 单独启用插件
  -> 打开页面、运行动作、创建一次真实测试任务
```

`npm run validate` 证明清单结构和本地构建通过；真实安装测试证明包内容、入口文件、宿主通信、Python 运行环境和业务参数都可用。发布前两步都要做。

## 插件由什么组成

```text
开发文件                              构建产物                     宿主行为

src/plugin.ts ---------------------> xb-svcb-plugin.json ------> 读取元数据、页面、动作和权限
frontend/src/App.vue + components -> dist/frontend/index.html -> 在 sandbox iframe 中执行页面
plugin.py / python package ------------------------------------> 在独立 Python Worker 中执行
```

一个插件至少需要 `xb-svcb-plugin.json`。其他部分按插件类型选择：

| 运行类型 | 自定义页面 | Python | 典型用途 |
| --- | --- | --- | --- |
| `frontend` | 可选 | 否 | Vue 工具页、声明式表单、消息和创建翻唱任务 |
| `python` | 可省略 | 是 | 流程钩子、后台参数处理、配置记录 |
| `hybrid` | 可选 | 是 | Vue 页面调用 Python 动作 |
典型安装后的目录会被规范化为：

```text
<plugins>/<plugin-id>/
├─ xb-svcb-plugin.json
├─ dist/frontend/index.html         # 可选，自定义页面入口
├─ plugin.py 或 backend/__init__.py # 可选，Python 入口
├─ assets/                          # 可选，只读资源
└─ vendor/                          # 可选，Python 第三方依赖
```

插件持久数据不写在安装目录，而写在宿主分配的数据目录。Python 中通过 `ctx.data_dir` 访问，页面端当前没有直接读写数据目录的 API。

## 两套 TypeScript API

不要混淆以下入口：

```ts
// 开发机运行：生成清单、校验和打包
import { plugin, fields, writeManifest } from '@xb-svcb/plugin-sdk'

// 插件页面运行：调用宿主
import { host, isHosted } from '@xb-svcb/plugin-sdk/client'

// Vue 组件运行：宿主 API 的响应式封装
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

`src/plugin.ts` 不会在用户应用中执行。`frontend/src/` 会被 Vite 编译进页面，并在用户启用插件后执行。

## 运行与安全边界

- 所有插件安装后默认关闭；插件总开关和单插件开关都开启后才运行。
- 自定义页面运行在 `sandbox="allow-scripts"` iframe 中，不能读取宿主 DOM。
- 页面只能通过 Client SDK 使用宿主提供的能力。
- 页面宿主调用使用 `postMessage` token、请求 ID 和 30 秒默认超时。
- Python Worker 提供进程崩溃隔离，不是权限沙箱；Python 代码具有当前用户权限。
- Python 动作、钩子和生命周期每次调用都会启动新的 Worker 并重新导入入口。
- 权限字段用于声明、审计和用户提示，不能阻止 Python 访问未声明的操作系统资源。
- 只启用可信来源的 Python 或混合插件。

## 当前限制

- 插件包最大 20 MB，解压后最大 50 MB。
- `xb-svcb-plugin.json` 最大 512 KB。
- 自定义页面入口 HTML 最大 2 MB。
- 通过 `assetUrl()` 读取的单个资源最大 10 MB。
- 页面 Client 请求默认 30 秒超时。
- Python Worker 单次操作默认 30 秒超时。
- 一个插件只有一个 `frontend.entry`；多个页面共享入口，并通过 `context.page.id` 区分。
- 当前插件中心通常只打开 `pages[0]`，多页面体验建议在自定义 Vue 页面内实现。
- 插件市场和远程安装仅接受 GitHub HTTPS raw/API 下载地址。

这些限制是当前宿主实现的一部分。发布插件前应在目标 XB-SVCB 版本中重新验证。
## 最容易混淆的边界

- `src/plugin.ts` 或 `build.mjs` 在开发机执行，用来生成清单；它不会在用户的 XB-SVCB 页面中执行。
- `frontend/src/` 会被构建进 `dist/frontend/index.html`，并在 sandbox iframe 中运行。
- `plugin.py` 在独立 Python Worker 中运行，不和页面共享内存。
- `page.actions` 只影响声明式页面按钮显示；自定义页面能调用插件顶层 `actions` 中的任意动作。
- `CreateWorkPayload` 的 TypeScript 字段大多是可选的，但真实创建任务仍需要满足宿主业务规则。
- `before_create` 会作用于所有正式创建任务，包括插件页面通过 `createWork()` 或 `create_work` 动作创建的任务。
- 重新安装同 ID 插件会替换代码目录并将插件设为关闭，数据目录会保留。
