# XB-SVCB 安装器

版本：`0.0.17`

安装器由 Inno Setup 读取 `installer/xb-svcb.iss` 构建，负责打包桌面本体、环境搭建脚本、自带模型和文档。

## 构建流程

1. 在 `web/` 执行 `npm run build` 构建前端。
2. 执行 `pyinstaller installer/xb-svcb-app.spec` 构建桌面本体。
3. 构建 `native/juce-vst3-host`，并把产物放入 `dist/XB-SVCB/engines/juce-vst3-host/`。
4. 使用 Inno Setup 6 的 `ISCC.exe` 编译 `installer/xb-svcb.iss`。

本地发布构建建议使用 `installer/build.ps1` 作为一键入口。
`installer/build.ps1` 会强制校验 `dist/XB-SVCB/engines/juce-vst3-host/xb-juce-vst3-host.exe`，缺失时不会继续生成安装器。

JUCE VST3 Host 构建需要 CMake、C++ Build Tools 和 JUCE。开发机可设置：

```powershell
$env:XB_JUCE_DIR="C:\path\to\JUCE"
```

临时不打包插件 Host 时可运行 `installer/build.ps1 -SkipJuceHostBuild`。

## v0.0.17 安装器行为

- 应用版本为 `0.0.17`。
- 发布包会强制携带 `engines/juce-vst3-host/xb-juce-vst3-host.exe`，缺失时构建脚本会停止，不生成不可用的安装器。
- 安装流程会检查随包释放的 JUCE VST3 Host，缺失时写入安装日志，便于定位插件系统不可用原因。
- 用户机安装后直接使用随包释放的 Host，不会下载 JUCE SDK，也不会在安装现场编译插件主机。
- 音频编辑器新增复制音轨/片段音频、从剪贴板粘贴音频到音轨、音量包络、内置效果器和 JUCE VST3 插件 Host 相关桥接。
- v0.0.17 前端包包含组件化的导入音频弹窗和插件窗口弹窗；桌面本体包含局部重推理的插件效果隔离逻辑，避免效果器污染模型生成的人声。

## v0.0.16 安装器行为

- 应用版本为 `0.0.16`。
- 发布包同步包含新版前端主题系统、自定义主题编辑器、多角色管理和时间轴模板。
- 发布包会携带音频编辑器的 JUCE VST3 Host，用于效果器插件扫描、离线渲染和原生插件 GUI。
- 用户机安装时不会下载 JUCE SDK 或现场编译 Host；`install_prereqs.bat` 只检查随包释放的 Host 是否存在，缺失时在安装日志中告警。
- UVR/RVC/SVC 环境部署会复核并保护 GPU torch 栈；检测到兼容 NVIDIA GPU 时不再在 UVR 安装阶段把 GPU 版 PyTorch 替换成 CPU 版。
- CUDA 策略保持一致：40 系及以下兼容 NVIDIA 使用 cu121，50 系 Blackwell 使用 cu128；CPU 或不兼容显卡才回退 CPU torch。
- 继续沿用 `.sb-svcb` 用户数据目录、镜像源配置、安装日志和隐藏命令行窗口的安装流程。

## v0.0.15 安装器行为

- 应用版本为 `0.0.15`。
- 用户数据目录默认使用 `.sb-svcb`；选择磁盘根目录或普通非空目录时，会自动在其中创建 `.sb-svcb` 子目录。
- 安装器同时写入安装目录和用户 AppData 下的数据目录指针，升级/迁移后更稳。
- 安装流程默认配置 HuggingFace 镜像与清华 PyPI 镜像，并写入修复环境时可复用的环境变量。
- 可检测并按用户选择安装/配置 Python 3.10、Git、ffmpeg、uv、CUDA Toolkit 和 Microsoft C++ Build Tools。
- 已存在的前置依赖会自动跳过。
- 页面顺序为环境检查与前置依赖策略、安装路径、GPU 栈、依赖路径、用户数据路径。
- CUDA 栈会复核实际显卡：CPU 或不兼容显卡跳过 CUDA 并安装 CPU 版 torch；40 系及以下兼容 NVIDIA 使用 cu121；50 系 Blackwell 使用 cu128。
- 运行环境搭建在安装器流程内隐藏执行，不再弹出 PowerShell 或 cmd 窗口。
- 前置依赖安装/环境变量配置与虚拟环境搭建阶段会继续推进安装页进度条。
- 前置依赖页面提供「在安装器窗口显示详细安装信息」可选项，勾选后会在安装完成前显示详情页。
- 安装日志写入 `{app}\install_logs`，完成页会显示最后日志摘要。
