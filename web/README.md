# XB-SVCB Vue 前端

XB-SVCB 的 Vue 3 + Vite 前端。生产构建产物会由 PyInstaller 打进 XB-SVCB.exe，源码开发时由 pywebview 加载 Vite 开发服务器。

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
