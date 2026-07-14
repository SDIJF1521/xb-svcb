## v0.0.18 · SeedVC + 动态主题背景 + 在线曲库兼容 + 安装器强化

### 新增

- **SeedVC 完整推理链路**：支持导入 SeedVC checkpoint（`.pth`）与 YAML 配置（`.yml` / `.yaml`），推理时选择目标音色参考音频。
- **SeedVC 独立运行环境**：新增 `engines/seed-vc` 与 `.venv-seedvc`，支持 CPU、NVIDIA cu121 和 RTX 50 系 Blackwell/cu128 安装栈。
- **多框架统一管理扩展**：模型导入、模型列表、创建任务、任务参数、模型站清单和引擎路由均支持 `seed-vc`，可与 So-VITS-SVC、RVC 一起参与跨框架混唱。
- **图片 / MP4 自定义背景**：主题编辑器可选择静态图片或 MP4 动态壁纸，支持遮罩、缩略图、编辑器预览、整页预览与持久化保存。
- **主题媒体本地持久化**：桌面端会把选中的背景媒体复制到用户数据目录 `theme/media`，重启后继续可用。

### 优化

- **在线曲库 UI 对齐新接口**：移除已失效的“每页数量”和“加载更多”，一次展示上游曲库实际返回的完整列表，并显示曲库名称、关键词和结果数量。
- **QQ音乐候选地址增强**：试听与下载优先尝试 `vipmusicurl`，失败后继续尝试普通 `musicurl` / `url`。
- **URL 型歌词兼容**：网易云或 QQ音乐返回歌词 URL 时，后端会先获取歌词正文再解析时间轴。
- **安装器发布校验**：构建前检查应用、前端、Inno Setup 版本一致性，并验证前端入口、全部 AI worker、SeedVC 与 JUCE VST3 Host。
- **大体积分卷安装包**：Inno Setup 显式生成小于 2GB 的 `.bin` 分卷，避免自带模型超过单文件发布限制。
- **安装后运行时检查**：安装器会复核应用组件、UVR、SeedVC Python、SeedVC worker 与 `inference.py`，失败时给出修复命令和日志位置。
- **轻量安装器验证**：新增 `installer/build.ps1 -ValidateOnly`，无需重新压缩数 GB 模型即可验证版本、PowerShell 和 Inno Setup/Pascal 代码。

### 修复

- **修复妖狐 API 搜索全部失败**：妖狐 API `V2.1.3.8` 已移除 `g` 参数，旧版会收到“参数 g 未配置，禁止传递”；v0.0.18 不再发送该参数。
- **修复开发模式背景预览丢失**：浏览器 mock 文件输入框不再触发主题弹窗的外部点击关闭，图片和 MP4 选择后可立即预览。
- **修复桌面背景媒体重启失效**：本地文件不再仅保存临时浏览器 URL，而是通过桌面桥接复制并重新解析。
- **修复陈旧发布目录被误打包**：缺少新版前端、SeedVC worker 或 JUCE Host 时，发布构建会直接停止。
- **修复 Windows 下 SeedVC 环境安装失败**：正式推理不再安装仅供上游评测使用的 `resemblyzer` / `webrtcvad`，避免 Python 3.10 因缺少预编译 wheel 而调用本机 Visual Studio 编译失败。
- **修复 SeedVC 首次推理依赖镜像失败**：安装包预置 RMVPE、CampPlus、Whisper Small 与 BigVGAN，worker 会对已知官方配置生成本地临时配置，不再因 `hf-mirror.com` TLS/网络异常中断任务。
- **修复模型下载后不能立即选择**：后台下载完成后会等待本地模型库刷新；重新进入模型页、创建页或编辑器时也会强制读取最新模型清单。
- **模型下载支持断点续传**：大模型使用 `.part` 暂存、HTTP Range 续传和三次重试；软件或网络中断后再次点击同一模型可继续，成功导入前不再删除断点文件。

### 兼容说明

- SeedVC 模型需要 checkpoint、匹配的 YAML 配置，以及本次推理使用的目标音色参考音频。
- 在线曲库结果数量由妖狐 API 决定；当前实测 QQ音乐通常返回 10 条，网易云返回约 13 条，上游可能调整。
- 自定义视频背景目前支持 MP4。大型视频会增加用户数据目录占用，桌面端选择上限为 200MB。
- 安装包是多文件集合，必须把 `XB-SVCB-Setup.exe` 与所有 `XB-SVCB-Setup-*.bin` 放在同一目录。

### 安装

- 下载 `XB-SVCB-Setup.exe` 和同一版本的全部 `XB-SVCB-Setup-*.bin`，放到同一目录后运行 EXE。
- 应用本体、前端包、Python 锁文件和安装器版本均已同步为 **v0.0.18**。
- 已安装旧版的用户可覆盖升级；模型、作品、下载素材、编辑工程、设置和主题媒体继续使用原数据目录。
- 首次使用 SeedVC 时需要搭建对应环境；安装失败可在安装目录运行 `setup_env.bat --only seedvc` 重试。
- 若曾遇到 `Failed to build webrtcvad==2.0.10`，使用本次更新后的安装文件覆盖安装，再执行 `setup_env.bat --only seedvc` 即可修复残缺环境。
