# XB-SVCB 安装器

版本：`0.0.30`

安装器由 Inno Setup 读取 `installer/xb-svcb.iss` 构建，负责打包桌面本体、环境搭建脚本、自带模型和文档。

## 构建流程

1. 在 `web/` 执行 `npm run build` 构建前端。
2. 执行 `pyinstaller installer/xb-svcb-app.spec` 构建桌面本体。
3. 准备 Windows FFmpeg 与 So-VITS-SVC、SeedVC、DDSP-SVC 固定分支源码；本地缺失时由发布构建下载到忽略目录。
4. 构建 `native/juce-vst3-host`，并把产物放入 `dist/XB-SVCB/engines/juce-vst3-host/`。
5. 以 `--clean` 运行 `install/prepare_wheelhouse.py` 预下载/预构建 Windows x64 whl，重新生成 `assets/wheels/wheelhouse.json`。
6. 校验内置前端、全部 worker、离线载荷、wheelhouse 与 JUCE Host。
7. 使用 Inno Setup 6 的 `ISCC.exe` 编译 `installer/xb-svcb.iss`。

本地发布构建建议使用 `installer/build.ps1` 作为一键入口。
`installer/build.ps1` 会校验应用、前端、版本号、全部 worker 和
`dist/XB-SVCB/engines/juce-vst3-host/xb-juce-vst3-host.exe`，任何一项缺失都不会继续生成安装器。
如果只需要刷新 `XB-SVCB-Setup.exe` 而保留现有 `XB-SVCB-Setup-*.bin` 不动，可在 `dist` 已有完整分卷的前提下使用 `./installer/build.ps1 -BootstrapperOnly`。

只检查 PowerShell、版本约束和 Inno Setup/Pascal 脚本，不压缩模型：

```powershell
./installer/build.ps1 -ValidateOnly
```

## v0.0.30 安装器行为

- 应用、Python 项目、前端包、锁文件、Windows EXE 版本资源和 Inno Setup 版本统一为 `0.0.30`。
- Python 前置检测必须执行真实的 3.10+ 解释器探测；旧环境变量、WindowsApps 别名和仅存在但不可运行的 `python.exe` 均不会被认定为已安装。
- 安装完成后的各隔离环境校验会再次执行 Python/Torch 导入检查，并把不可运行的环境标记为失败，避免安装器显示成功而软件启动后降级。
- 本版本新增 PyMSS 人声处理环境：安装器为其创建独立 `.venv-pymss` 并准备隔离依赖和模型目录；模型站仅允许人声分离与和声去除两类模型，PyMSS 缺失时只标记可选组件不可用，不阻塞其他引擎。
- PyMSS 固定使用 Torch 2.7.1；Blackwell/其他 NVIDIA 分别使用 `cu128`/`cu126` wheel，依赖放在 `assets\\wheels\\pymss\\py310\\cu126` / `cu128`，不会覆盖其他引擎的 Torch。构建 `--clean` 会同时清理旧 wheelhouse 约束文件。
- PyMSS worker 在隔离环境内解析 `auto` 设备，优先 CUDA/ROCm/DirectML/MPS；只有明确选择 CPU 才使用 CPU，`mlx` 保持 PyMSS 原生 Apple Silicon 路径。DirectML 仅在隔离环境实际具备兼容的 `torch-directml` 时启用；目前其 Torch 2.4.1 固定版本与 PyMSS 2.0.x 的 Torch 2.7.1 要求冲突，安装器会明确保留 CPU PyMSS，避免误报 GPU 就绪。
- 音频编辑器波形采用有限并发和区间批量采样；片段新增 `time_stretch`（25%-400%），编辑器会同步调整片段时长，倍率贯穿预览、插件监听、实时混音与导出，旧工程自动按 100% 处理。
- 编辑器试听和实时预览通过缓存 MP3 传输，降低长音频首播延迟；工程导出与复制格式不变。
- 编辑器重推理纳入选择性高音保护；实际触发保护且启用 AI 美声时自动降低高频染色参数，避免恢复高音后出现过度合成感。
- 安装目录携带 `release_notes_v030.md`、`README.md` 与 `docs/api.md`；覆盖升级继续保留作品、模型、编辑工程、主题、API 设置和插件数据。
- 高音保护、高音域 F0 自适应和 FCPE 失败回退纳入本版本运行环境与安装验证范围。

## v0.0.29 安装器行为

- 应用、Python 项目、前端包、锁文件、Windows EXE 版本资源和 Inno Setup 版本统一为 `0.0.29`。
- 前置依赖页检测 VB-CABLE；缺失时显示用户手动安装入口，不会静默安装虚拟声卡驱动，安装完成后可重新检测。
- 安装目录携带 `release_notes_v029.md`、`README.md` 与 `docs/api.md`；覆盖升级继续保留作品、模型、编辑工程、主题、API 设置和插件数据。
- 实时翻唱系统音频模式使用 Windows 音频回环/虚拟音频线，要求用户将播放器输出切换到 VB-CABLE 或其他虚拟线路，并在软件中选择独立的输出设备。
- 关闭软件时会停止实时后台服务并清空当前用户数据目录下 `temp` 的生成内容，保留目录本身供下次启动复用。

## v0.0.28 安装器行为

- 应用、Python 项目、前端包、锁文件、Windows EXE 版本资源和 Inno Setup 版本统一为 `0.0.28`。
- 前置依赖页新增 VB-CABLE 检测；它是系统音频变声器的可选外部组件。安装器不会静默安装驱动，缺失时提供 VB-Audio 官方下载入口，用户完成驱动安装后可点击重新检测。
- 安装版携带插件 Python SDK 与 `plugin_worker.py`，支持前端、Python 和混合插件；插件代码与数据继续保存到用户数据目录，不写入安装目录。
- 环境搭建统一验证本机 Python 3.10 和各组件虚拟环境版本，损坏或版本不匹配时自动重建；So-VITS-SVC 会补齐并验证 Matplotlib 导入链。
- AI 歌声增强环境不再安装会引发 `packaging` 版本冲突的运行期 wheel 包，离线 wheelhouse 继续按组件和 GPU 栈选择。
- 系统 PATH 没有可用 `ffmpeg` / `ffprobe` 时正常释放安装分卷内置 FFmpeg，不再因安装前检查应用目录而误判资源已存在。
- 安装目录携带最新 `release_notes_v028.md`、`README.md` 与 `docs/api.md`，覆盖升级保留作品、模型、编辑工程、主题、API 设置和插件数据。

## v0.0.27 安装器行为

- 应用、Python 项目、前端包、锁文件、Windows EXE 版本资源和 Inno Setup 版本统一为 `0.0.27`。
- 安装包内置的 `DeepFilterNet3` 现在同时用于分离干声与翻唱模型输出的双阶段修复；运行时会分析高频和高音域，修复后受控恢复辅音/泛音，无需首次运行再下载模型。原先排除的 `fcpe.pt` 也改为随分卷携带，供 So-VITS/DDSP 极高音 F0 自动切换。
- 发布构建会把 `uv` 与各 AI 子环境依赖预下载/预构建为 whl，按 `py310/cpu`、`py310/directml`、`py310/cu121`、`py310/cu128` 分组，并对 SVC/RVC py39、DirectML 下 DDSP/Vocal 等 torch 版本冲突环境使用组件子目录；PyMSS 另有独立的 `py310/cu126` / `py310/cu128` 子目录。安装/修复环境时根据用户机器的 Python 版本、GPU 栈和组件自动 `--no-index --no-build --find-links` 离线安装对应 whl。
- Inno Setup 分卷固定为 `1,900,000,000` 字节，发布构建会拒绝任何达到 2 GiB 的数据卷。
- 安装目录携带最新 `release_notes_v027.md`、`README.md` 与 `docs/api.md`，旧数据目录可继续覆盖升级使用。
- 分卷发布方式、离线模型、内置 FFmpeg、GPU 环境策略和离线 wheelhouse 不要求用户重新下载已有作品或模型。

## v0.0.26 安装器行为

- 应用、Python 项目、前端包、锁文件、Windows EXE 版本资源和 Inno Setup 版本统一为 `0.0.26`。
- 安装包新增 `vocal_tuning_worker.py`，并在安装前校验 AI 对齐/自然修音 worker 与 AI 歌声增强 worker 均已进入 `_internal/infrastructure`。
- `.venv-vocal` 新增 `praat-parselmouth==0.4.6`，供参考人声动态对齐、DurationTier 受限时间校正和 PitchTier 自然修音使用；`runtime.ready` 同步记录该依赖。
- 安装目录携带 `release_notes_v026.md`、`README.md` 与 `docs/api.md`，旧数据目录可继续覆盖升级使用。

## v0.0.25 安装器行为

- 前置依赖改为用户辅助模式：安装器只检测 Python 3.10+、Git、Microsoft C++ Build Tools、CUDA Toolkit 与显卡驱动，不会调用 winget 或系统安装器；uv 会在 Python 可用后通过 pip 自动安装到用户目录；FFmpeg 已由安装分卷提供，不要求用户另行安装。
- FFmpeg 作为安装包分卷资源随包携带：系统 PATH 已有 `ffmpeg` 时跳过释放；否则释放到 `{app}\\tools\\ffmpeg`，并自动配置 `PATH`、`XB_FFMPEG_DIR` 与 `FFMPEG_HOME`。
- So-VITS-SVC、SeedVC、DDSP-SVC 引擎源码和离线模型随安装包分卷携带；安装时检测到已释放的源码会跳过 Git/ZIP 获取，Python venv 仍按目标机器的 GPU 栈创建。
- GPU 栈页面之后提供逐项下载按钮，自动跳转 Python、Git、Visual C++、NVIDIA CUDA 或 AMD 驱动的官方/可信页面；用户安装后可点击“重新检测”。
- 依赖检查脚本和 `install.py` 会在检测到 Python 后自动安装或修复 uv，并写入用户环境变量，然后继续搭建 AI 虚拟环境。
- 已安装的前置依赖可直接跳过；安装器仍会隐藏执行环境搭建脚本，并把完整日志写入 `{app}\\install_logs`。

由于自带模型总量超过单文件上限，发布产物是一组不可拆分的文件：

- `XB-SVCB-Setup.exe`
- `XB-SVCB-Setup-1.bin`
- 后续编号的 `XB-SVCB-Setup-*.bin`（数量取决于本次模型体积）

`DiskSliceSize` 固定为 `1,900,000,000` 字节，构建结束还会逐个校验产物必须小于 2 GiB。安装时必须把 `exe` 和全部 `bin` 放在同一目录，发布 Release 时也必须同时上传。

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
- 自动模式把界面确认的 CPU、CUDA 或 DirectML 结果明确传给后续步骤，避免界面显示 CPU、Python 安装阶段却重新检测并改装 CUDA。NVIDIA 模式会填写 CUDA Toolkit `v12.6` / `v12.8` 默认目录。
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
- PyInstaller 继续打包 `ddsp_worker.py`、`uvr_worker.py`、`pymss_worker.py` 与当前编辑器/消息中心前端。
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
- 可检测并按用户辅助流程配置 Python 3.10、Git、CUDA Toolkit 和 Microsoft C++ Build Tools；uv 在 Python 可用后自动安装，FFmpeg 则由安装分卷提供。
- 已存在的前置依赖会自动跳过。
- 页面顺序为环境检查、安装路径、GPU 栈、前置依赖下载辅助、依赖路径、用户数据路径。
- CUDA 栈会复核实际显卡：CPU 或不兼容显卡跳过 CUDA 并安装 CPU 版 torch；40 系及以下兼容 NVIDIA 使用 cu121；50 系 Blackwell 使用 cu128。
- 运行环境搭建在安装器流程内隐藏执行，不再弹出 PowerShell 或 cmd 窗口。
- 前置依赖安装/环境变量配置与虚拟环境搭建阶段会继续推进安装页进度条。
- 前置依赖页面提供「在安装器窗口显示详细安装信息」可选项，勾选后会在安装完成前显示详情页。
- 安装日志写入 `{app}\install_logs`，完成页会显示最后日志摘要。
