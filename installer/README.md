# XB-SVCB 安装器

版本：`0.0.14`

安装器由 Inno Setup 读取 `installer/xb-svcb.iss` 构建，负责打包桌面本体、环境搭建脚本、自带模型和文档。

## 构建流程

1. 在 `web/` 执行 `npm run build` 构建前端。
2. 执行 `pyinstaller installer/xb-svcb-app.spec` 构建桌面本体。
3. 使用 Inno Setup 6 的 `ISCC.exe` 编译 `installer/xb-svcb.iss`。

本地发布构建建议使用 `installer/build.ps1` 作为一键入口。

## v0.0.14 安装器行为

- 应用版本为 `0.0.14`。
- 可检测并按用户选择安装/配置 Python 3.10、Git、ffmpeg、uv、CUDA Toolkit 和 Microsoft C++ Build Tools。
- 已存在的前置依赖会自动跳过。
- 页面顺序为环境检查与前置依赖策略、安装路径、GPU 栈、依赖路径、用户数据路径。
- CUDA 栈会复核实际显卡：CPU 或不兼容显卡跳过 CUDA 并安装 CPU 版 torch；40 系及以下兼容 NVIDIA 使用 cu121/cu118；50 系 Blackwell 使用 cu128。
- 运行环境搭建在安装器流程内隐藏执行，不再弹出 PowerShell 或 cmd 窗口。
- 前置依赖安装/环境变量配置与虚拟环境搭建阶段会继续推进安装页进度条。
- 前置依赖页面提供「在安装器窗口显示详细安装信息」可选项，勾选后会在安装完成前显示详情页。
- 安装日志写入 `{app}\install_logs`，完成页会显示最后日志摘要。
