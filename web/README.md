# XB-SVCB Vue 前端

版本：`0.0.31`

这里是 XB-SVCB 桌面应用的 Vue 3 + Vite 前端。生产构建产物会由 `installer/xb-svcb-app.spec` 打进 `XB-SVCB.exe`。

## v0.0.31 版本说明

- 前端版本与应用本体、Python 锁文件、EXE 版本资源和安装器版本统一为 `0.0.31`。
- 本版新增首次使用交互引导、首页/创建页拖拽音频、模型重命名和高音保护高级参数控制。
- 详细更新内容见 [v0.0.31 更新说明](../docs/release-notes/release_notes_v031.md)。

## v0.0.29 重点

- 新增实时翻唱页面，提供歌曲文件实时播放和系统音频变声两种模式；系统模式限制单个 RVC/SeedVC 模型，并提供回环输入、独立输出、块时长、预缓冲、增益和模型参数设置。
- 系统音频变声状态页显示设备、处理进度和实时倍率；启动错误使用 Element Plus 消息组件提示，输入输出设备相同等配置问题会显示明确原因。
- 实时输出按固定时间块调度，并在相邻块间进行重叠交叉淡化，减少硬拼接带来的卡顿；文件模式支持实时分块播放、作品登记和导出。
- 新增 AI 增强工程页面与编辑器片段增强入口，支持本地原始歌曲和在线曲库资源作为参考。
- 前端版本同步到 `0.0.29`，与应用本体、Python 锁文件、EXE 版本资源和安装器版本一致。

## 开发

    npm install
    npm run dev

另开终端启动 Python 桌面壳：

    ..\app\.venv\Scripts\python.exe ..\app\main.py --dev

## 构建与测试

    npm run type-check
    npm run build
    npm run test:unit -- --run

输出目录为 web/dist。

## 目录职责

- src/api/：Bridge、HTTP mock、类型定义。
- src/stores/：模型、作品、系统、主题、通知和传输状态。
- src/views/：创建翻唱、实时翻唱、编辑器、作品、音乐、模型站、API 等页面。
- src/components/：布局、编辑器、主题和通用交互组件。

后端调用通过 window.pywebview.api 完成；浏览器开发模式可使用 mock 或开发服务进行页面调试。前后端接口变更时，应同步检查 src/api/types.ts、app/api/bridge.py 和 docs/api.md。

更多内容见 [项目文档总目录](../docs/README.md)。
