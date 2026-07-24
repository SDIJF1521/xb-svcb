# XB-SVCB 安装器

版本：`0.0.23`

安装器由 Inno Setup 读取 `installer/xb-svcb.iss` 构建，负责打包桌面本体、环境搭建脚本、自带模型和文档。

## 构建流程

1. 在 `web/` 执行 `npm run build` 构建前端。
2. 执行 `pyinstaller installer/xb-svcb-app.spec` 构建桌面本体。
3. 构建 `native/juce-vst3-host`，并把产物放入 `dist/XB-SVCB/engines/juce-vst3-host/`。
4. 校验内置前端、全部 worker（含 SeedVC / DDSP-SVC）与 JUCE Host。
5. 使用 Inno Setup 6 的 `ISCC.exe` 编译 `installer/xb-svcb.iss`。

本地发布构建建议使用 `installer/build.ps1` 作为一键入口。
`installer/build.ps1` 会校验应用、前端、版本号、全部 worker 和
`dist/XB-SVCB/engines/juce-vst3-host/xb-juce-vst3-host.exe`，任何一项缺失都不会继续生成安装器。

只检查 PowerShell、版本约束和 Inno Setup/Pascal 脚本，不压缩模型：

```powershell
./installer/build.ps1 -ValidateOnly
```

由于自带模型总量超过单文件上限，发布产物是一组不可拆分的文件：

- `XB-SVCB-Setup.exe`
- `XB-SVCB-Setup-1.bin`
- 后续编号的 `XB-SVCB-Setup-*.bin`（数量取决于本次模型体积）

安装时必须把 `exe` 和全部 `bin` 放在同一目录，发布 Release 时也必须同时上传。

JUCE VST3 Host 构建需要 CMake、C++ Build Tools 和 JUCE。开发机可设置：

```powershell
$env:XB_JUCE_DIR="C:\path\to\JUCE"
```

临时不打包插件 Host 时可运行 `installer/build.ps1 -SkipJuceHostBuild`。

## v0.0.23 安装器行为

- 应用、Windows EXE 版本资源、Python 项目、前端、两份锁文件和 Inno Setup 版本统一为 `0.0.23`。
- PyInstaller 明确收集 FastAPI、Starlette、Pydantic、python-multipart、Uvicorn 及动态加载的 HTTP/lifespan 模块，确保安装版可在软件内手动启动 API 服务。
- 安装包新增 `docs/api.md`，包含安全配置、完整调用流程、Python 示例、SeedVC 参考音频用法、接口清单和状态码。
- FastAPI 与桌面本体运行在同一 GUI 进程，不新增控制台程序或自动启动项；安装后默认不开放端口。
- 安装包内的桌面本体与前端新增酷我音乐曲库，包含搜索、后端代理试听、无损音质候选回退、Range 分段下载和内联歌词解析。
- 发布构建要求根目录存在 `release_notes_v023.md` 与 `docs/api.md`，缺失时不会生成安装器。

## v0.0.22 安装器行为

- 应用、Windows EXE 版本资源、Python 项目、前端、两份锁文件和 Inno Setup 版本统一为 `0.0.22`。
- GPU 栈自动识别 NVIDIA CUDA、AMD Radeon DirectML 和 CPU；DirectML 为 So-VITS-SVC、RVC、SeedVC、DDSP-SVC 与 UVR 分别部署锁定的 `torch-directml` 环境并做真实张量校验。SeedVC 在非 NVIDIA 环境仅作为兼容路径保留，不建议 AMD/CPU 用户优先选择。
- RVC 与 So-VITS-SVC 的 DirectML 环境使用 Python 3.10，避免 Python 3.9 无法导入当前 `torch-directml`；SeedVC/DDSP-SVC 不再在 DirectML Torch 安装后执行空 pip 命令。
- So-VITS-SVC DirectML 在 Python 3.10 下覆盖旧 NumPy/PyWorld/SciPy 钉版本，使用可安装的 cp310 兼容组合，不再现场编译 `numpy 1.19.5`。
- UVR 的 AMD 环境固定使用 `audio-separator[dml]` 与 `onnxruntime-directml`；VR `.pth` 与 MDX `.onnx` 模型分别校验 Torch DirectML 设备和 ONNX DirectML provider。
- UVR DirectML 安装校验会正常初始化临时 Separator；不再使用会跳过设备初始化的 `info_only=True`，避免把已可用的 Radeon 环境误报为失败。
- GPU 检测同时使用 `nvidia-smi` 与 `Win32_VideoController` 回退；RTX 4060 等 NVIDIA 显卡不会再因安装器进程的 System32/PATH 视图差异被显示为 CPU。
- 自动模式把界面确认的 CPU、CUDA 或 DirectML 结果明确传给后续步骤，避免界面显示 CPU、Python 安装阶段却重新检测并改装 CUDA。NVIDIA 模式会填写 CUDA Toolkit `v12.1` / `v12.8` 默认目录。
- CUDA Toolkit 已拆为独立的 NVIDIA 专用目录页；CPU 与 AMD DirectML 会完全跳过该页，不再因为空 CUDA 路径无法进入下一步。
- 修复 `Program Files (x86)` 中括号被批处理块误解析导致前置步骤中断；安装结束会真实导入五个隔离环境的 Torch 并校验 CUDA / DirectML，不再仅凭 `python.exe` 存在就误报完成。
- 用户 PATH 与镜像/CUDA 变量改用 Python `winreg` 一次性写入，避免 `reg.exe` 在 94% 持续占用 CPU；长 PATH、`%变量%` 和括号会保持原样，失败会中止前置步骤并写入日志。
- 应用启动时的环境探测统一使用 Windows `CREATE_NO_WINDOW`，不会再为 UVR/SVC/RVC/SeedVC/DDSP 探测闪出黑色 CMD 窗口。
- 五个隔离环境改为并行探测并按环境签名缓存 24 小时；重启应用可直接恢复检测结果，更新环境后自动重新探测。
- 首页“集成工具”改用自适应网格，长版本号、显卡名称和异常状态不会再把工具名称挤成竖排或溢出卡片。
- 发布构建要求根目录存在 `release_notes_v022.md`，安装后将其与主 `README.md` 一起释放到应用目录。
- `installer/build.ps1 -ValidateOnly` 会检查 v0.0.22 版本一致性、发布文档、内置模型和 Inno Setup/Pascal 脚本。

## v0.0.21 安装器行为

- 应用、Python 项目、前端、两份锁文件和 Inno Setup 版本统一为 `0.0.21`。
- PyInstaller 包含音频片段渲染合并、插件窗口并行交互、插件 state/播放位置同步、JUCE 块级实时播放和 HTML Audio 回退的当前本体与前端。
- JUCE VST3 Host 使用非随主窗口失焦关闭的置顶原生插件窗口，继续随安装包离线释放到 `engines/juce-vst3-host`。
- 随包 Host 当前仅支持 64 位 Windows VST3 音频效果器；VST2 `.dll`、32 位插件、CLAP、AAX、AU 和需要 MIDI 音符的 VST3i 乐器不受支持。
- JUCE Host 通过 `AudioDeviceManager` 把目标插件处理结果与其余工程底轨混合后送入声卡；实际设备、缓冲大小和延迟由前端显示，安装器继续携带编译好的 Host。
- 发布构建要求根目录存在 `release_notes_v021.md`，安装后将其与主 `README.md` 一起释放到应用目录。
- 分卷安装方式保持不变：必须共同发布 `XB-SVCB-Setup.exe` 与全部 `XB-SVCB-Setup-*.bin`。
- `installer/build.ps1 -ValidateOnly` 会检查 v0.0.21 版本一致性、发布文档、内置模型和 Inno Setup/Pascal 脚本。

## v0.0.20 安装器行为

- 应用、Python 项目、前端、两份锁文件和 Inno Setup 版本统一为 `0.0.20`。
- 新增 DDSP-SVC 6.3 安装步骤，部署 `engines/ddsp-svc`、`.venv-ddsp`、ContentVec、RMVPE 和 PC-NSF-HiFiGAN；PC-NSF-HiFiGAN 2025.02 随安装器离线提供，不再依赖 GitHub Release 下载。
- UVR 与 DDSP-SVC GPU 环境固定使用匹配的 CUDA Torch，并在各自安装结束后验证 `torch.cuda.is_available()`，避免 GPU 选择静默运行在 CPU。
- PyInstaller 继续打包 `ddsp_worker.py`、`uvr_worker.py` 与当前编辑器/消息中心前端。
- 安装器内置优化后的主题前端：WebView2 使用原生页面快照完成暗色/亮色过渡，并在动画结束后同步原生窗口外观。
- 发布构建要求根目录存在 `release_notes_v020.md`，安装后将其与主 `README.md` 一起释放到应用目录。
- 分卷安装方式保持不变：必须共同发布 `XB-SVCB-Setup.exe` 与全部 `XB-SVCB-Setup-*.bin`。
- `installer/build.ps1 -ValidateOnly` 会检查 v0.0.20 版本一致性、发布文档和 Inno Setup/Pascal 脚本。
- 发布构建会校验 DDSP 声码器权重至少 32 MiB 且 `config.json` 包含 `pc_aug=true`，防止普通 NSF-HiFiGAN 或 LFS 指针误入安装包。

## v0.0.19 安装器行为

- 应用、Python 项目、前端、锁文件和 Inno Setup 版本统一为 `0.0.19`。
- PyInstaller 包含播放中效果热更新、精确时间轴定位和妖狐官方歌词响应适配后的当前前端与应用本体。
- 安装器继续携带全部 SVC / RVC / UVR / SeedVC / Hub workers、SeedVC 离线权重和 JUCE VST3 Host。
- 发布构建要求根目录存在 `release_notes_v019.md`，安装后将其与主 `README.md` 一起释放到应用目录。
- 分卷安装方式保持不变：必须共同发布 `XB-SVCB-Setup.exe` 与全部 `XB-SVCB-Setup-*.bin`。
- `installer/build.ps1 -ValidateOnly` 会在不重新压缩模型的情况下检查 v0.0.19 版本一致性、发布文档和 Inno Setup/Pascal 脚本。

## v0.0.18 安装器行为

- 应用、前端和安装器版本统一为 `0.0.18`。
- PyInstaller 包含当前前端、音乐 API 兼容逻辑、SeedVC 引擎以及 SVC / RVC / UVR / SeedVC / Hub workers。
- 运行环境安装新增 `engines/seed-vc` 与 `.venv-seedvc`，覆盖 CPU、cu121 和 Blackwell/cu128 栈。
- 发布构建拒绝应用、前端与 Inno Setup 版本号不一致的产物，并检查内置前端、全部 worker 和 JUCE Host。
- 安装包使用小于 2GB 的分卷数据文件；`XB-SVCB-Setup.exe` 与全部 `XB-SVCB-Setup-*.bin` 必须共同发布。
- 安装完成后校验应用组件、UVR 与 SeedVC 运行环境；数据目录说明包含持久化主题媒体。
- SeedVC 环境会过滤仅供上游评测使用的 `resemblyzer` / `webrtcvad`，Windows + Python 3.10 无需现场编译该扩展。
- 安装包预置 SeedVC 所需 RMVPE、CampPlus、Whisper Small 与 BigVGAN；构建时校验权重大小，避免 LFS 指针或残缺快照进入发布包。
- 提供 `installer/build.ps1 -ValidateOnly`，无需压缩模型即可检查版本、PowerShell 与 Inno Setup/Pascal 脚本。
- 安装目录包含 `README.md` 与 `release_notes_v018.md`，便于离线查看功能和升级说明。

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
- 使用 `.xb_svcb` 用户数据目录，并继续沿用镜像源配置、安装日志和隐藏命令行窗口的安装流程。

## v0.0.15 安装器行为

- 应用版本为 `0.0.15`。
- 用户数据目录默认使用 `.xb_svcb`；选择磁盘根目录或普通非空目录时，会自动在其中创建 `.xb_svcb` 子目录。
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
