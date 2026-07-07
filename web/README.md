# XB-SVCB 前端

版本：`0.0.17`

这里是 XB-SVCB 桌面应用的 Vue 3 + Vite 前端。生产构建产物会由 `installer/xb-svcb-app.spec` 打进 `XB-SVCB.exe`。

## 开发

```sh
npm install
npm run dev
```

## 构建

```sh
npm run build
```

构建输出目录是 `web/dist`，随后由桌面本体打包流程内置进应用。

## v0.0.17 重点

- 前端版本同步到 `0.0.17`。
- 音频编辑器新增效果器面板能力：音量包络、内置效果器参数、插件路径选择和 JUCE VST3 插件窗口入口。
- 新增片段/音轨音频复制入口、工具栏/轨道级粘贴入口，以及 `Ctrl/Cmd + V` 从系统剪贴板粘贴音频到播放头的快捷操作。
- 插件窗口与导入音频弹窗拆分为 `web/src/components/editor/EditorPluginDialog.vue`、`web/src/components/editor/EditorImportTrackDialog.vue`，编辑器页面只保留编排与状态管理，符合组件化维护边界。
- 前端 API 新增 JUCE Host 状态检查、插件检查、插件 GUI 打开/关闭、插件 state 同步、音频复制和剪贴板粘贴结果类型。
- 局部重推理完成后会提示被移除的插件类效果，避免用户误以为 VST3 处理已经写入新的 AI 干声。

## v0.0.16 重点

- 主题切换改为从顶栏主题按钮扩散的圆形过渡，切换暗色、亮色和自定义主题时保留旧主题作为圈外画面。
- 主题功能拆成 `ThemeSwitcher`、`ThemePresetList`、`CustomThemeEditor`、`ThemeBackground` 等组件，减少布局层和顶栏中的主题逻辑。
- 自定义主题支持编辑色彩、添加背景图片、开启动态粒子，并提供亮色「晴空花园」默认示例。
- 音频编辑器新增多角色管理和时间轴模板入口，可快速生成独唱、对唱、主唱 + 和声、三角色剧情等工程结构。

## v0.0.15 重点

- 首页数据存储卡片拆分为「选择目录」与「迁移数据」两个动作。
- 数据迁移过程显示进度条、当前阶段和已复制/总大小。
- 前端 API 新增数据目录直接切换、后台迁移启动和迁移状态轮询。
- 桌面后端缺少新版 API 时会给出明确错误，并兼容旧迁移入口。
