# 快速开始

本章从空目录创建一个 Vue 3 前端插件，解释生成的每个关键文件，并完成类型检查、构建、打包和安装。

## 1. 准备环境

前端或混合插件需要：

- Node.js `^20.19.0` 或 `>=22.12.0`；
- npm；
- 支持插件功能的 XB-SVCB；
- 支持 TypeScript/Vue 的编辑器。

Python 或混合插件另外需要 Python 3.10+。宿主运行时会提供 Python SDK，本地单元测试时才需要手动安装 `plugin-sdk/python`。

```powershell
node --version
npm --version
python --version
```

## 2. 选择 SDK 来源

在 XB-SVCB 仓库中开发 SDK 时，直接运行本地 CLI：

```powershell
node plugin-sdk\bin\xb-plugin.mjs --help
```

SDK 发布到 npm 后，可以使用：

```powershell
npx @xb-svcb/plugin-sdk --help
```

下文使用 `npx @xb-svcb/plugin-sdk`。本地开发时替换为 `node <仓库>\plugin-sdk\bin\xb-plugin.mjs`。

## 3. 创建项目

```powershell
npx @xb-svcb/plugin-sdk create my-first-plugin `
  --id com.example.my-first-plugin `
  --name "我的第一个插件" `
  --type frontend `
  --author "Your Name"
```

TypeScript 前端默认使用 Vue 3。命令参数：

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `<dir>` | 是 | 无 | 新项目目录 |
| `--id` | 是 | 无 | 稳定插件 ID，3-64 位小写标识符 |
| `--name` | 是 | 无 | 插件中心显示名称 |
| `--type` | 否 | `frontend` | `frontend`、`python`、`hybrid` |
| `--language` | 否 | `ts` | `ts` 或 `js` |
| `--framework` | 否 | TypeScript 前端为 `vue` | `vue` 或 `vanilla` |
| `--version` | 否 | `1.0.0` | 初始版本 |
| `--author` | 否 | 空 | 作者或组织 |

Vue 脚手架要求 TypeScript；`--language js --framework vue` 会被 CLI 拒绝。

常见变体：

```powershell
# 原生 TypeScript 页面
npx @xb-svcb/plugin-sdk create vanilla-plugin `
  --id com.example.vanilla-plugin `
  --name "Vanilla Plugin" `
  --framework vanilla

# 纯 Python 插件
npx @xb-svcb/plugin-sdk create python-plugin `
  --id com.example.python-plugin `
  --name "Python Plugin" `
  --type python

# Vue + Python 混合插件
npx @xb-svcb/plugin-sdk create hybrid-plugin `
  --id com.example.hybrid-plugin `
  --name "Hybrid Plugin" `
  --type hybrid

# 无构建 JavaScript 页面
npx @xb-svcb/plugin-sdk create js-plugin `
  --id com.example.js-plugin `
  --name "JS Plugin" `
  --language js
```

## 4. 认识生成目录

默认 Vue 前端项目：

```text
my-first-plugin/
├─ package.json
├─ package-lock.json             # npm install 后生成
├─ tsconfig.json
├─ vite.config.ts
├─ src/
│  └─ plugin.ts                  # 清单源文件
├─ frontend/
│  ├─ index.html                 # Vite HTML 入口
│  └─ src/
│     ├─ main.ts                 # createApp(App).mount(...)
│     ├─ App.vue                 # 页面布局
│     ├─ style.css               # 全局样式
│     ├─ env.d.ts
│     └─ components/
│        └─ GreetingForm.vue     # 示例业务组件
├─ dist/frontend/index.html      # npm run build 后生成
└─ xb-svcb-plugin.json           # 清单构建结果
```

混合项目还会生成 `plugin.py`；纯 Python 项目不会生成 `frontend/` 和 Vite 配置。

不要手工编辑 `dist/` 或 `xb-svcb-plugin.json`。它们会在每次构建时重新生成。

## 5. 安装依赖

```powershell
cd my-first-plugin
npm install
```

默认 Vue 项目依赖：

- `vue`：页面运行时；
- `@vitejs/plugin-vue`：编译 `.vue`；
- `vue-tsc`：检查 `.vue` 和 `.ts`；
- `vite-plugin-singlefile`：把 JS 和 CSS 内联到单一 HTML；
- `@xb-svcb/plugin-sdk`：清单、Client 和 Vue SDK；
- `tsx`：执行 `src/plugin.ts`。

## 6. 第一次修改

打开 `frontend/src/App.vue`，修改标题和布局：

```vue
<template>
  <main class="my-plugin-page">
    <header>
      <h1>我的翻唱工作台</h1>
      <p>由 Vue 插件提供</p>
    </header>

    <GreetingForm />
  </main>
</template>
```

打开 `src/plugin.ts`，修改元数据：

```ts
const app = plugin('com.example.my-first-plugin', '我的翻唱工作台', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('使用 Vue 编写的翻唱工具。')
  .author('Your Name')
```

插件 ID 是安装、配置和升级的稳定标识，发布后不要更改。

## 7. 浏览器预览

```powershell
npm run dev
```

Vite 预览适合检查 Vue 组件、响应式布局、表单状态、本地交互和样式。浏览器中没有 XB-SVCB 宿主 token，因此 `isHosted()` 为 `false`，真实动作、任务创建和插件资源 API 不会执行。脚手架示例会显示“开发预览”提示。

## 8. 理解构建命令

```powershell
npm run typecheck
npm run build
npm run validate
npm run pack
```

| 命令 | 执行内容 | 输出 |
| --- | --- | --- |
| `npm run dev` | Vite 开发服务器 | 无持久构建产物 |
| `npm run typecheck` | `vue-tsc --noEmit` | 无 |
| `npm run build:frontend` | Vite + singlefile | `dist/frontend/index.html` |
| `npm run build:manifest` | `tsx src/plugin.ts` | `xb-svcb-plugin.json` |
| `npm run build` | 页面构建 + 清单构建 | 两项构建产物 |
| `npm run validate` | 类型检查 + 构建 + 清单校验 | 更新构建产物 |
| `npm run pack` | validate + 压缩 | `<project>.xbplugin` |

`npm run validate` 是提交代码前的最低检查，`npm run pack` 是交付用户前的最低检查。

## 9. 安装到 XB-SVCB

1. 打开 XB-SVCB 的“插件中心”。
2. 开启插件功能总开关。
3. 点击“安装本地插件包”。
4. 选择生成的 `.xbplugin`。
5. 阅读插件运行类型和权限。
6. 单独启用插件。
7. 点击插件卡片上的“打开”。

新安装插件默认关闭。只开启总开关不会自动启用任何插件。

## 10. 第一个完整验证

修改组件后执行：

```powershell
npm run validate
npm run pack
```

然后在插件中心重新安装生成的包。当前安装行为会替换同 ID 插件并将其设为关闭，因此需要再次启用。

验证清单：

- 插件名称、版本和作者正确；
- 自定义 Vue 页面能打开；
- 页面没有空白、溢出或控制台错误；
- 浏览器开发提示在宿主中不再显示；
- `runAction()` 返回结果；
- 禁用插件后页面不能继续使用；
- 关闭插件总开关后动作被拒绝。

## 11. CLI 校验不负责什么

`npm run validate` 会检查 TypeScript、构建页面、生成清单并校验清单形状，但不会证明插件在宿主中一定可用。它不会检查：

- `frontend.entry` 文件是否真的存在；
- Python 入口能否导入；
- 清单中的 Python handler 是否已注册；
- 最终包是否超过宿主大小限制；
- 页面宿主调用是否符合真实任务数据要求。

这些检查发生在安装、启用或实际调用阶段，因此发布前必须完成一次真实安装测试。

## 12. 下一步

- 页面布局、组件和状态：[Vue 3 自定义页面](frontend-vue.md)
- 注册字段与动作：[清单、页面与动作](manifest.md)
- 页面调用宿主：[页面 Client API](client-api.md)
- 页面调用 Python：[混合插件](hybrid.md)
- 报错定位：[测试与调试](testing.md)
