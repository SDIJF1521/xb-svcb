<div align="center">

# 🎤 XB-SVCB · AI 翻唱工具

#### 开箱即用的桌面级 AI 翻唱工作站

**🎵 导入歌曲 ｜ 🎚️ 人声分离 ｜ 🌫️ 去混响 ｜ 🗣️ AI 歌声转换 ｜ 🎧 AI 歌声增强 ｜ 🎼 合并伴奏 ｜ 🎤 成品翻唱**

一条龙完成整首歌的 AI 翻唱 · 支持 **So-VITS-SVC / RVC 多框架推理** · **多人混合翻唱** · **AI 歌声增强工程** · **在线曲库** · **模型站** · **音频编辑器**

<br/>

[![License](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/SDIJF1521/xb-svcb?include_prereleases&label=release&color=ff6b9d)](https://github.com/SDIJF1521/xb-svcb/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/SDIJF1521/xb-svcb/total?color=brightgreen&label=downloads)](https://github.com/SDIJF1521/xb-svcb/releases)
[![Stars](https://img.shields.io/github/stars/SDIJF1521/xb-svcb?style=flat&color=yellow)](https://github.com/SDIJF1521/xb-svcb/stargazers)

[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#)
[![Python](https://img.shields.io/badge/python-3.9%20|%203.10-3776AB?logo=python&logoColor=white)](#)
[![Vue](https://img.shields.io/badge/Vue%203-Element%20Plus-42b883?logo=vuedotjs&logoColor=white)](#)
[![Engines](https://img.shields.io/badge/engines-So--VITS--SVC%20·%20RVC%20·%20SeedVC%20·%20DDSP--SVC-8a2be2)](#architecture)

<br/>

### ⬇️ [**点此下载安装器 · XB-SVCB-Setup.exe**](https://github.com/SDIJF1521/xb-svcb/releases/latest)

<sub>Windows 一键安装 · 内置前端与底模 · 无需手动配置 Python / Node</sub>

<sub>用户交流 / 反馈 QQ 群：**1038366109**</sub>

</div>

<a id="features"></a>

---

## ✨ 特性

- 🎚️ **全自动流水线** —— 一次点击走完「分离 → 去混响 → F0 → 推理 → 混音」。
- 🗣️ **真实 so-vits-svc 4.1 推理** —— 支持主模型 + 浅扩散，可调变调、F0 预测器、扩散步数。
- 🎛️ **多框架推理与统一管理（So-VITS-SVC / RVC / SeedVC / DDSP-SVC）** —— 推理引擎按模型「框架」可插拔：RVC 自动识别 `.index`，SeedVC 支持参考音频（建议 NVIDIA CUDA 用户优先使用），DDSP-SVC 支持 Rectified Flow checkpoint、F0、采样步数与共振峰偏移；导入、模型管理、创建页和编辑器局部重推理按框架切换专属参数。四个引擎的原始输出统一经过不混入原唱音色的自然度保护：桥接 0.38 秒以内句内停顿、压低长无声区的声码器残留，以受限缓慢增益恢复原干声微动态，并将默认输出精确补齐或裁切到源干声总时长。So-VITS-SVC 额外对 30 秒显存切片执行 120 ms 重叠淡化并降低随机声码器噪声；SeedVC 的质量范围提高到 20–50 步并降低过强 CFG 引导。
- 🧬 **多模型混合翻唱（可跨框架 · 合唱 · 可编辑时间轴）** —— 按歌名自动获取带时间轴歌词、或**导入本地 `.lrc`**，做时长对齐校验；提供**可编辑可视化时间轴**：拖动边界调整起止（自动吸附歌词时间）、缩放精修、拆分 / 合并 / 删除片段，**片段独立指派模型**；**一段可同时指派多个模型实现「合唱」**（多路人声等响度叠加 + 软限幅防破音）；**同一首歌可混用 So-VITS-SVC、RVC、SeedVC 与 DDSP-SVC 模型**；每个模型在完整人声上整轨推理，再「同源连唱合并、换人处交叉淡化」无缝拼成多人合唱。
- 🎛️ **Audio Editor Lite 音频编辑器** —— 从作品或本地音频创建编辑工程，支持工程选择页、多轨时间轴、真实波形、片段拖动/拉伸、精确播放头定位与剪切、切口交叉淡化、相邻片段渲染合并、片段声道分配（双声道 / L / R）、片段/音轨音频复制与剪贴板粘贴、音量包络、内置效果器、非模态 JUCE VST3 插件窗口、声卡回调块级实时插件处理、设备延迟状态、混音预览、时间轴拖动快进及 WAV / MP3 / FLAC 导出；支持 TXT / LRC 歌词导入与自动切句，可维护多角色并把片段分配给角色，内置独唱、对唱、主唱 + 和声、三角色剧情等时间轴模板。
- 🧠 **高级创作工作流** —— 歌声转换工作台支持「自动混音合成」「自动人声合并」「手动人声合并」「自动 + 编辑器二次调整」「全手动编辑」；其中人声合并只在多模型模式开放，避免单模型流程误用。
- 🎵 **在线资源获取（可播放校验）** —— 内置 **网易云 / QQ音乐 / 酷我音乐** 曲库的搜索、试听、下载（QQ 可填会员 Cookie 取高品质音频）；酷我支持无损音质候选回退、后端代理试听、Range 分段下载及内联歌词。下载前统一校验资源可播放性（魔数 / Content-Type / ffprobe），VIP / 无版权 / 失效链接不可下载；下载素材可一键进入翻唱。
- 🎬 **作品音乐播放页** —— 从作品库进入带过渡动画的独立播放器，支持进度 / 音量控制、歌词逐句跟随和点击跳转；歌词可导入 LRC，或选择网易云、QQ、酷我曲库并从多个搜索结果中指定歌曲序号通过 API 获取；每首作品还可关联图片或 MP4 MV 画面并持久化恢复。
- 🌐 **模型站（魔搭社区 · 后台传输）** —— 基于 **ModelScope** 一键**上传/下载**声音模型：填自己的访问令牌即可发布到自有公开仓库，按关键词**模糊搜索**（**分页加载**）社区模型并直接导入；带**架构标签**（So-VITS-SVC / RVC / SeedVC / DDSP-SVC）与**清单防污染**校验；上传/下载**挂后台执行、不阻塞操作**，大模型支持断点续传和重试，下载完成后立即进入可选模型列表。
- 🎼 **专业人声分离与双阶段修复** —— `5_HP-Karaoke-UVR` 分离 + `UVR-DeEcho-DeReverb` 去混响后，使用安装包内置的专用 `DeepFilterNet3` 模型修复分离伪影；修复前会分析 6 kHz 以上高频占比和人声音域，神经修复后只在有效人声窗口受控恢复高频辅音与高音泛音。翻唱模型输出还会再经过一次独立修复，再进入可选美声与混音。
- 🎧 **AI 歌声增强工程** —— 可调的 **AI 对齐**（默认 45%）先根据停顿切分并单调匹配原唱与 AI 人声句段，再用去音色化倒谱/动态特征执行带约束声学音素 DTW，生成间距约 300 ms 的高置信度时间锚点。密集锚点只负责参考 F0 的字音对应；只有同一句内至少三个相邻锚点方向一致、原始偏差超过 25 ms、按当前强度应用后仍达到 8 ms 时，才通过受限 Praat DurationTier 校正波形节奏，避免持续元音产生“电风扇”式周期调制，整轨时长始终不变。随后在同一次 PSOLA 重合成中执行自然修音（默认 45%）：参考映射后的原唱 F0，过滤误检、弱化半音吸附、限制最大修正并在乐句边缘渐入渐出，以保留颤音、滑音和清辅音；PSOLA 只覆盖连续人声区域，长数字静音恢复原始样本，0.45 秒以内句内空隙保持连续。AI 角色共振峰（默认 60%）只分析转换后目标声音自身在 250 Hz–4.5 kHz 的稳定宽带峰，不复制原唱的中频身份。另有独立可调的 **AI EQ**（默认 55%，宽带频谱自适应校正）、**AI Compressor**（默认 45%，按有效人声动态自动设阈值并补偿响度）、**AI Exciter**（默认 25%，带齿音保护的高频谐波增强）、**Stereo**（默认 30%，低频居中、单声道兼容的中侧扩展）和 **AI 响度包络**（默认 58%，从 AI 人声自身恢复局部响度起伏）。所有滑块只定义处理上限：引擎会先按整首素材推导高通、body、harsh、presence、air、压缩参数与 wet 上限，再按 20 ms 人声窗口动态收放角色共振峰、EQ、压缩、激励、声场、响度包络和并行母带；静音、弱呼吸与清辅音保留更多原声，高频占比突增时 Exciter 和 Stereo 自动退让。响度包络在效果链末端以约 70 ms 平滑轮廓执行最多 ±3 dB 的受限校正，并避开停顿和底噪。basic 的动态 wet 上限通常在 57%–72%，advanced 通常在 69%–84%，而不是固定比例。vocalfloor 对 0.5 秒以内句内停顿保持开启且最大只衰减 6 dB；advanced 额外保护最多 8% 的高频辅音/呼吸细节，并只做最大 ±1.25 dB 的参考宽带倾斜校正。美声任务的最终混音会测量人声与伴奏的 EBU R128 有效响度，让人声保持在伴奏下方约 2.5 dB，并用低比例并行总线压缩收拢共同峰值；增益始终受限，最终以 -1.5 dBFS 采样峰值限幅，为真峰值保留余量。
- ⚡ **GPU / CPU 自由切换** —— 自动识别 NVIDIA CUDA 与 AMD Radeon DirectML（含 **50 系/Blackwell 自动走 cu128 + torch 2.7**），长音频自动分段避免显存溢出。
- 🔌 **FastAPI 外部接入** —— 软件内手动启停本机或局域网 API，支持 API Key、流式上传大音频、模型管理、单模型/多模型/批量任务、推理历史与预设、作品管理和成品下载；Audio Editor Lite 也开放工程、音轨、片段、切分、分离、局部重推理与渲染接口。内置连通性测试、Swagger/ReDoc、Python 与 PowerShell 示例。
- 🎨 **主题系统与自定义主题** —— 暗色 / 亮色 / 自定义主题一键切换并记忆，切换时从主题按钮触发基于原生页面快照的圆形扩散动画；自定义主题支持调色、背景图片 / MP4 动态壁纸和动态粒子，默认提供亮色「晴空花园」示例，连 pywebview **原生窗口标题栏/边框**也会在动画结束后自然同步。
- 👤 **个性化** —— 自定义头像与昵称、内置全局消息通知中心；切换页面后仍持续同步任务进度与失败原因，已读状态可在多个前端窗口间同步。
- 📦 **开箱即用** —— 安装后通过 `XB-SVCB.exe` 启动完整桌面应用（自带应用图标与前端资源），打开界面无需另装 Python / Node。
- 🧩 **环境隔离** —— 重型 AI 任务跑在独立子环境（`.venv-svc` / `.venv-rvc` / `.venv-seedvc` / `.venv-ddsp` / `.venv-uvr` / `.venv-vocal`），互不污染。
- 🎧 **作品库** —— 试听 / 导出成品，单独试听伴奏与干声，失败任务一键查日志；删除作品同步真实清理本地生成文件。

> **最新版本 v0.0.28**：新增完整插件中心、NoneBot2 风格 GitHub 插件市场、前端/Python/混合运行时、TypeScript/Python SDK 和自定义页面宿主 API；页面配置支持按插件持久化，插件与软件窗口支持全屏，并为妖狐 M3U8 提供受限宿主播放器。安装器同时修复 Python 环境识别、So-VITS-SVC Matplotlib 依赖、Vocal packaging 冲突、特殊路径转义和系统缺少 FFmpeg 时的随包释放。详见 [v0.0.28 更新说明](release_notes_v028.md)、[插件开发文档](docs/plugins/README.md) 与 [API 接入文档](docs/api.md)。

> v0.0.27：模型站升级为带详情、版本、依赖、更新和试听素材的社区模型流程；AI 翻唱增加 DeepFilterNet3 分离人声/模型输出双阶段修复、高频保护与最高 1800 Hz 自适应音域，So-VITS-SVC 和 DDSP-SVC 可自动或手动使用 FCPE，并补齐 FCPE 离线依赖及失败回退；安装器预置按 Python、组件和 GPU 栈选择的离线 whl wheelhouse，所有分卷严格小于 2 GiB。详见 [v0.0.27 更新说明](release_notes_v027.md) 与 [API 接入文档](docs/api.md)。

> v0.0.26：AI 歌声增强升级为参考人声句段/音素动态对齐、受限局部节奏校正和自然 F0 修音，并加入 AI 角色共振峰、AI EQ、AI Compressor、AI Exciter、Stereo 与 AI 响度包络独立控制；同时优化持续元音的“电风扇”式微时拉伸伪影，提高人声响度，并在删除编辑工程或更换主题壁纸时同步清理对应本地文件。详见 [v0.0.26 更新说明](release_notes_v026.md) 与 [API 接入文档](docs/api.md)。

> v0.0.25：安装器前置依赖改为用户辅助检测与跳转下载，用户安装好 Python 后会自动安装 uv；FFmpeg、So-VITS-SVC、SeedVC、DDSP-SVC 改为随分卷自带，系统已有 FFmpeg 时自动跳过释放；作品播放页补齐歌词搜索多结果手动选择、QQ / 网易 / 酷我 API 来源选择、MV 画面导入与更细致的播放体验。详见 [v0.0.25 更新说明](release_notes_v025.md) 与 [API 接入文档](docs/api.md)。

> v0.0.24：引入 AI 歌声增强工程（basic / advanced 两级，vocalfloor 软衰减 + 原始人声频谱参考匹配 + Pedalboard 专业母带 DSP），DeepFilterNet 权重随安装包分发实现离线开箱即用；编辑器局部重推理支持自动增强。不改变 v0.0.23 的 NVIDIA CUDA、AMD DirectML、CPU 推理策略、外部 FastAPI 接入与酷我音乐曲库。详见 [v0.0.24 更新说明](release_notes_v024.md) 与 [API 接入文档](docs/api.md)。
> v0.0.23：FastAPI 外部接入扩展为模型管理、单模型/多模型/批量任务、历史与预设、作品管理以及 Audio Editor Lite 主要工作流；在线资源获取新增酷我音乐搜索、试听、无损下载和歌词解析。API 服务默认关闭，退出软件即释放端口。详见 [v0.0.23 更新说明](release_notes_v023.md)。

> v0.0.22：新增 Windows AMD Radeon DirectML 支持，UVR、So-VITS-SVC、RVC 与 SeedVC 可使用 AMD GPU；DDSP-SVC 在 AMD 机器暂用 CPU 稳定推理。设备 UI 根据各隔离环境实际能力显示 CUDA、ROCm、DirectML 或 CPU；启动探测使用并行缓存且不弹出 CMD。详见 [v0.0.22 更新说明](release_notes_v022.md)。

> v0.0.21：音频编辑器的 VST3 插件 UI 改为非模态置顶窗口，可与主界面播放和时间轴操作并行；同一 GUI 插件实例通过 JUCE 声卡回调处理可听音频，参数在下一音频块生效，并显示设备实际块大小与延迟；新增相邻音频片段渲染合并。详见 [v0.0.21 更新说明](release_notes_v021.md)。
>
> v0.0.20：新增 DDSP-SVC 6.3 完整推理链路、共振峰偏移和独立安装环境；消息中心改为跨页面全局同步；UVR 严格遵循 GPU / CPU 选择；编辑器支持 TXT / LRC 歌词导入、静音辅助自动切句、多角色管理和时间轴模板；暗色主题切换改用 WebView2 原生页面快照与平滑减速动画。详见 [v0.0.20 更新说明](release_notes_v020.md)。
>
> v0.0.19：音频编辑器支持播放中自动更新效果，新预览在后台渲染完成后保持当前时间点热切换；时间轴播放头改用标尺真实零点换算，修复选择线固定偏离鼠标并兼容横向滚动；在线歌词按妖狐官方响应读取 `data.lrctxt`、`data.lrc` 和 `data.music.lrcurl`，QQ 免费详情会通过歌曲 `mid` 回退到聚合歌词接口。详见 [v0.0.19 更新说明](release_notes_v019.md)。
>
> v0.0.18：新增 **SeedVC 完整推理链路**，支持导入 checkpoint + YAML 配置、选择目标音色参考音频、创建任务、模型站下载断点续传与跨框架混唱；下载完成后模型库和创建页会立即刷新；自定义主题背景升级为本地持久化的图片 / MP4 动态壁纸，修复浏览器开发模式预览丢失；在线曲库适配妖狐 API `V2.1.3.8`，移除已废弃的 `g` 参数并兼容会员音频与 URL 型歌词；安装器升级为显式分卷发布，构建时校验版本、前端、全部 worker、SeedVC 和 JUCE Host，安装后复核关键运行环境。详见 [v0.0.18 更新说明](release_notes_v018.md)。
>
> v0.0.17：聚焦 **音频编辑器效果器与插件 Host**——编辑器新增片段/音轨音频复制到系统剪贴板、从剪贴板把音频粘贴回音轨、音量包络，以及混响、降噪、噪声门、压缩、EQ、高通/低通、延迟、合唱、限幅、增益等内置效果器；外部插件效果器改为 `Python -> C++ JUCE VST3 Host -> VST3 Plugin GUI` 架构，前端插件窗口已拆成独立组件，支持 VST3 插件检查、原生 GUI 打开和插件 state 回写；局部重推理会清理旧缓存并剥离插件效果，避免效果器污染模型生成的干声音频；发布构建会强制校验并携带 `xb-juce-vst3-host.exe`，避免生成装完后插件系统不可用的安装包。
>
> v0.0.16：聚焦 **主题体验、音频编辑组织能力与安装稳定性**——前端主题切换改为接近 Element Plus 官网的圆形扩散过渡，并抽成 `ThemeSwitcher` / `CustomThemeEditor` / `ThemePresetList` / `ThemeBackground` 等组件；自定义主题支持亮色默认示例、色彩编辑、背景图片和动态粒子；音频编辑器新增多角色管理与时间轴模板，可为片段标注角色并快速生成独唱、对唱、和声、剧情分轨；安装器与应用版本同步到 `0.0.16`，UVR/RVC/SVC 环境搭建会保护 GPU torch 栈，避免有 NVIDIA GPU 的用户在部署 UVR 环境时被替换成 CPU 版 PyTorch。
>
> v0.0.15：聚焦 **数据目录迁移与 RVC 安装稳定性**——默认用户数据目录升级为 `.sb-svcb`，兼容旧目录并同时写入安装目录与用户 AppData 指针；首页将「选择目录」与「迁移数据」拆开，迁移过程显示复制进度，完成后当前会话立即重定向模型、作品、设置与编辑工程仓储；RVC 环境安装时会从自带底模预置 hubert/rmvpe 并修复 RMVPE checkpoint，缺失时走 HuggingFace 镜像，40 系及以下 NVIDIA 统一 cu121，50 系继续 cu128；安装脚本自动配置 HF/PyPI 镜像，降低首次安装和修复环境的网络失败率。
>
> v0.0.14：聚焦 **音频编辑工作台与安装器完整化**——编辑器支持添加/删除音轨、导入音频时选择目标音轨、可选人声分离、按歌词切分人声音频（支持 API 获取歌词或导入 `.lrc` 文件）；局部重新推理可微调模型与推理参数，时间轴为不同模型/框架分配更容易区分的颜色；安装器同步升级为单一 EXE 窗口流程，会先检查运行环境再选择安装路径，可自动检测/安装 Python、Git、ffmpeg、uv、CUDA 与 C++ Build Tools，CUDA 与 torch 栈会复核实际显卡，CPU 或不兼容显卡会跳过 CUDA 并安装 CPU 版 torch，前置依赖与运行环境搭建阶段会显示进度条，不再弹出 PowerShell/命令行窗口，日志写入安装目录，并可选择在安装器窗口内显示详细安装信息。
>
> v0.0.13：新增 **用户数据目录选择与迁移**——安装时可把 `.sb-svcb` 数据目录放到空间充足的磁盘，软件首页也可查看占用/剩余空间并一键迁移模型、作品、下载素材、编辑工程与缓存；手动人声合并改为真正的**逐段编辑工程**，每个参与 AI 独立成轨，轨内只包含该 AI 负责的分段音频；试听与导出统一走带交叉淡化的时间轴渲染，片段声道选择（双声道 / L / R）在编辑判断时即可听到真实效果。
>
> v0.0.12：聚焦 **稳定性与创作效率**——增强音频编辑器工程管理、工作流预设与复用、模型管理与传输体验、任务通知与日志入口；优化长音频处理、混音预览、时间轴操作和安装器环境修复流程；修复编辑器状态不同步、长音频导出偶发失败、模型站传输状态刷新不及时、以及主题/缩放后部分界面布局异常等问题。
>
> v0.0.11：新增 **Audio Editor Lite 音频编辑工作台**——可从作品或本地音频创建编辑工程，支持工程选择页、多轨时间轴、真实波形、片段拖动/拉伸、播放头剪切、切口交叉淡化、片段声道分配（双声道 / L / R）、局部重推理替换片段、混音播放时拖动时间轴快进；歌声转换新增高级工作流（自动混音、人声合并、自动 + 编辑器二次调整、全手动编辑），并限制人声合并仅在多模型模式开放；局部重推理新增 **1 秒最短片段保护**，顶栏导航收纳为主入口 +「资料库」，页面更清爽。
>
> v0.0.10：新增 **RTX 50 系显卡（Blackwell, sm_120）适配**——安装器自动识别 50 系并切换到 **cu128 + PyTorch 2.7** 专用栈（SVC / RVC 改用 Python 3.10，torchaudio 音频 I/O 走 soundfile，fairseq 重装并打 `weights_only` 补丁），彻底解决「仅升级 CUDA/torch 会哑音、效果不如 40 系/CPU」的问题，可用 `--cu128` / `--no-cu128` 手动切换，40 系及以下统一使用 cu121 栈；修复 **模型站只能搜到自己上传的模型**——改为按仓库名前缀 `xb-svcb` 全站搜索，即可发现所有人公开分享的模型（前缀 + 清单校验仍把关防污染）；时间轴 UI 稳健性增强（迷你时间轴总宽度固定、色块百分比钳制在轴内，长歌词不再撑破布局）。
>
> v0.0.9：混合翻唱升级 **可编辑可视化时间轴**——色块可**拖动左右边界**调整起止并**自动吸附歌词时间**、**缩放**放大局部精修、**拆分 / 合并 / 删除**片段，**片段与歌词解耦**、每段独立指派模型；**合唱多模型 UI 重构**（胶囊超 3 个折叠为「+N」、色块只显数量角标、弹窗与列表可滚动），多模型不再撑破布局；在线资源**下载前校验可播放性**（魔数 / Content-Type / ffprobe 探测，不可播放的不允许下载），歌词获取**新增导入本地 `.lrc` 时间轴歌词文件**。
>
> v0.0.8：混合翻唱新增 **「合唱」**——一句歌词可同时指派多个模型，多路人声按等响度叠加并经软限幅防破音；模型站**上传/下载挂后台执行**，不再阻塞前端操作，顶栏新增「传输」面板统一查看进度；**模型搜索与在线资源获取均支持分页「加载更多」**，减少单次查询等待。
>
> v0.0.7：新增 **RVC 推理**（基于 `rvc-python`）与**多框架推理抽象**——推理引擎按模型「框架」可插拔，导入/创建页按框架切换专属参数（protect / filter_radius / 版本 v1·v2），**混合翻唱可在同一首歌混用 RVC 与 so-vits-svc 模型**；RVC 跑在独立子环境 `.venv-rvc`，自动识别 `.index` 检索特征。
>
> v0.0.6：新增 **模型站（ModelScope 魔搭社区）**——用自己的访问令牌把本地模型一键发布到自有公开仓库，并按关键词**模糊搜索**、直接下载导入社区模型；模型带**架构标签**（So-VITS-SVC / RVC…）、**清单防污染**校验，上传/下载全程**进度条**实时反馈。
>
> v0.0.5：重做 **多模型混合翻唱** 合成——每个模型在完整人声上**整轨推理**，再「同一歌手连唱合并、仅在换人处交叉淡化」拼接，彻底消除逐句碎片推理带来的电流声 / 咔哒声 / 卡顿。
>
> v0.0.4：资源获取新增 **QQ音乐** 曲库（支持会员 Cookie 获取高品质音频）；新增 **多模型混合翻唱**（按歌词逐句指派不同模型）；删除作品时同步真实清理本地生成文件。

---

<a id="architecture"></a>

## 🏗️ 架构一览

XB-SVCB 采用“**桌面与 HTTP 共用业务核心，重型引擎和插件在独立进程运行**”的结构。安装版以 `XB-SVCB.exe` 为统一进程，内含 Vue 前端、pywebview Bridge、可选 FastAPI 服务、Python 业务代码与 worker 脚本；So-VITS-SVC、RVC、SeedVC、DDSP-SVC、UVR、模型站组件、VST3 插件和 Python 插件分别通过隔离环境或原生 Host 执行，插件前端则在受限 iframe 中通过宿主 Bridge 调用能力，避免依赖与插件崩溃相互污染。

```mermaid
flowchart TB
    DESKTOP_USER([桌面用户])
    API_CLIENT([外部程序 / 局域网客户端])
    PLUGIN_DEV([插件开发者])

    subgraph ENTRY["交互与接入层 · XB-SVCB.exe"]
        direction LR
        SHELL["pywebview 桌面壳<br/>单实例 / 原生窗口 / 文件选择"]
        WEB["Vue 3 + Element Plus<br/>创建 / 模型 / 曲库 / 作品 / 编辑器 / 插件中心 / API"]
        BRIDGE["Bridge API<br/>桌面调用 / 本地能力 / 插件服务"]
        HTTP["FastAPI /api/v1<br/>API Key / OpenAPI / 流式上传"]
        PLUGIN_HOST["插件页面宿主<br/>iframe / 主题 / 通知 / 全屏 / M3U8 播放器"]
        SHELL --> WEB --> BRIDGE
        WEB --> PLUGIN_HOST
    end

    subgraph CORE["共享 Python 业务核心"]
        direction LR
        FACADE["Api Facade<br/>桌面与 HTTP 共用契约"]
        APP["Application Services<br/>转换 / 作品 / 模型 / 系统编排"]
        QUEUE["共享串行推理队列<br/>单模型 / 多模型 / 批量任务"]
        ROUTER["EngineRegistry<br/>按模型框架统一路由"]
        EDITOR["AudioEditorService<br/>工程 / 时间轴 / 效果链 / 渲染"]
        CONNECT["Music / ModelHub / Theme Services<br/>曲库 / 模型站 / 主题媒体"]
        PLUGINS["PluginService<br/>清单 / 安装 / 开关 / 市场 / 页面"]
        FACADE --> APP
        FACADE --> EDITOR
        FACADE --> CONNECT
        FACADE --> PLUGINS
        APP --> QUEUE --> ROUTER
    end

    subgraph PLUGIN_RUNTIME["插件运行时"]
        direction LR
        IFRAME["插件前端 iframe<br/>HTML / JS / Vue bundle"]
        PWORKER["Python Plugin Worker<br/>每次动作独立进程 / 30 秒超时"]
        PYSDK["Python SDK<br/>Plugin / actions / hooks / context"]
        IFRAME <-->|postMessage / Client SDK| PLUGIN_HOST
        PWORKER --> PYSDK
    end

    subgraph RUNTIME["隔离运行时与原生进程"]
        direction LR
        UVR["UVR worker<br/>.venv-uvr"]
        SVC["So-VITS-SVC worker<br/>.venv-svc"]
        RVC["RVC worker<br/>.venv-rvc"]
        SEED["SeedVC worker + inference.py<br/>.venv-seedvc"]
        DDSP["DDSP-SVC 6.3 worker<br/>.venv-ddsp"]
        VOCAL["AI 歌声增强 worker<br/>.venv-vocal"]
        HUBWORKER["ModelScope worker<br/>.venv-hub"]
        FFMPEG["FFmpegEngine<br/>分离后处理 / 混音 / 酷我试听 / 导出"]
        JUCE["C++ JUCE VST3 Host<br/>检查 / GUI / state / 实时与离线处理"]
        VST["64 位 Windows VST3"]
        JUCE --> VST
    end

    subgraph STORAGE["本地数据与随包资产"]
        direction LR
        DATA[".xb_svcb 用户数据<br/>models / works / downloads / editor_projects<br/>api/uploads / plugins / plugin-data / cache / settings / theme/media"]
        ASSETS["assets/models 离线资产<br/>UVR / RMVPE / ContentVec / CampPlus / Whisper / BigVGAN / DeepFilterNet"]
    end

    subgraph ONLINE["外部服务"]
        direction LR
        MUSIC["妖狐音乐 API + 酷我 CDN<br/>网易云 / QQ音乐 / 酷我音乐 / 歌词"]
        HUB["ModelScope<br/>模型搜索 / 断点下载 / 上传"]
        GITHUB["GitHub Raw / Release<br/>market.json / .xbplugin"]
        YAOHU["妖狐影视 API + M3U8<br/>动漫搜索 / 详情 / 播放"]
    end

    subgraph SDK["插件开发与发布"]
        direction LR
        SDK_CORE["Plugin SDK<br/>Manifest / Client / Vue / Python"]
        BUNDLE[".xbplugin 插件包<br/>清单 + 前端 + Python"]
        PLUGIN_DEV --> SDK_CORE --> BUNDLE --> GITHUB
    end

    DESKTOP_USER --> SHELL
    API_CLIENT --> HTTP
    BRIDGE --> FACADE
    HTTP --> FACADE
    PLUGIN_HOST --> BRIDGE
    PLUGINS --> IFRAME
    PLUGINS --> PWORKER
    PLUGINS <--> DATA
    GITHUB --> PLUGINS
    PWORKER <--> DATA
    PWORKER --> YAOHU
    APP --> UVR
    APP --> FFMPEG
    ROUTER --> SVC
    ROUTER --> RVC
    ROUTER --> SEED
    ROUTER --> DDSP
    EDITOR --> FFMPEG
    EDITOR --> JUCE
    EDITOR -. 局部重推理 .-> ROUTER
    APP -. 歌声增强 .-> VOCAL
    EDITOR -. 重推理后增强 .-> VOCAL
    CONNECT --> HUBWORKER
    HUBWORKER <--> HUB
    CONNECT <--> MUSIC
    CONNECT -. 酷我代理试听 .-> FFMPEG
    ASSETS -. 本地优先 .-> UVR
    ASSETS -. 本地优先 .-> SVC
    ASSETS -. 本地优先 .-> RVC
    ASSETS -. 本地优先 .-> SEED
    ASSETS -. 本地优先 .-> DDSP
    ASSETS -. 本地优先 .-> VOCAL
    APP <--> DATA
    EDITOR <--> DATA
    CONNECT <--> DATA
    HTTP -. 上传文件 .-> DATA
```

**关键边界**

- **桌面与 HTTP 共用核心**：Vue 通过 pywebview Bridge、外部程序通过手动启用的 FastAPI 进入同一个 `Api` Facade，共用模型、作品、编辑工程和串行推理队列；HTTP 层只负责鉴权、DTO、上传与下载。
- **插件平台分层运行**：插件中心通过 PluginService 管理清单、安装、单插件开关和 GitHub 市场；自定义页面运行在受限 iframe，通过 Client SDK 与宿主 Bridge 通信，Python/混合插件的动作再交给独立 Worker 执行。
- **模型按框架路由**：`EngineRegistry` 统一接收模型与推理参数，再分别调用 So-VITS-SVC、RVC、SeedVC 或 DDSP-SVC；SeedVC 额外传入参考音频，DDSP-SVC 使用 Rectified Flow checkpoint 与 YAML 配置。
- **编辑器与插件隔离**：内置效果、混音和导出走 FFmpeg；VST3 加载与原生窗口由 JUCE Host 承载，局部重推理再回到统一引擎路由，重推理后可选自动调用 AI 歌声增强流水线。
- **在线服务可替换且受控**：网易云、QQ音乐和酷我音乐统一经过音乐服务适配；酷我试听由本地 FFmpeg 代理，模型站的重型依赖由 `.venv-hub` worker 隔离。
- **数据与程序分离**：模型、作品、下载素材、编辑工程、API 上传、缓存、设置及 `theme/media` 都写入可迁移的 `.xb_svcb`，覆盖升级不会替换用户数据。
- **离线资产优先**：安装包预置关键底模；worker 优先解析本地文件，仅在缺失时使用镜像或上游服务。

| 层 / 进程         | 主要实现                                                  | 职责与边界                                                     |
| ----------------- | --------------------------------------------------------- | -------------------------------------------------------------- |
| 交互与接入层      | pywebview + Vue 3 + FastAPI                               | 桌面交互、API Key 鉴权、OpenAPI、流式上传及受控文件下载        |
| 插件平台层        | PluginService + iframe Host + Plugin SDK + Python Worker | 插件安装、开关、GitHub 市场、页面 Bridge、动作与生命周期执行 |
| API 与业务层      | `api` + `application` + `domain`                    | 桌面/HTTP 共用契约、任务队列、模型/作品/曲库/编辑工程业务编排  |
| 基础设施层        | `infrastructure` + `EngineRegistry` + FFmpeg          | 路径、仓储、下载、音频处理和多框架引擎适配                     |
| AI 与模型站子进程 | SVC / RVC / SeedVC / DDSP-SVC / UVR / Vocal / Hub workers | 在独立`.venv-*` 中执行重型任务，隔离 Python、CUDA 与平台依赖 |
| 原生插件进程      | C++ / JUCE VST3 Host                                      | 插件检查、原生 GUI、实时播放、参数 state 回写与离线渲染        |
| 持久化层          | `.xb_svcb` + `assets/models`                          | 用户数据与 API 上传可迁移保存；随包资产优先供各 worker 使用    |
| 在线集成          | 妖狐音乐 API + 酷我 CDN + ModelScope                      | 三曲库/歌词、酷我代理试听与分段下载、模型搜索、上传和断点下载  |

---

<a id="quickstart"></a>

## 🚀 快速开始（最终用户）

> 推荐直接用图形安装器，无需任何命令行操作。

1. 在 [Releases](https://github.com/SDIJF1521/xb-svcb/releases/latest) 下载 **`XB-SVCB-Setup.exe`** 和同版本的全部 **`XB-SVCB-Setup-*.bin`**，放在同一目录后双击 EXE。
2. 在「选择安装位置」页**自定义安装路径**（默认 `%LOCALAPPDATA%\Programs\XB-SVCB`，无需管理员权限）。应用 exe 与全部依赖（`engines/`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp`、`.venv-uvr`、`.venv-vocal`、`models/`）都装进**这个目录**。
3. 在「选择用户数据存储位置」页选择 `.xb_svcb` 数据目录（默认 `{安装目录}\.xb_svcb`）。模型、作品、下载素材、编辑工程与缓存都会保存在这里，C 盘空间不足时建议选 D/E 盘。
4. 勾选「安装后立即搭建运行环境」，联网创建 AI 子环境（由 `setup_env.bat` 调 `install.py`，无 PowerShell）。
5. 通过桌面 / 开始菜单的 **XB-SVCB** 快捷方式启动。后续可在首页「数据存储位置」查看占用/剩余空间，并迁移到其它磁盘。

> 💡 **应用界面本身无需任何依赖即可打开**；FFmpeg、So-VITS-SVC、SeedVC、DDSP-SVC 源码、离线模型和 Python whl wheelhouse 由安装分卷携带。只有「搭建运行环境」需要 **Python 3.10+** 来创建匹配本机 GPU 的隔离环境；uv 与各 AI 子环境依赖会优先从安装包内的 `assets/wheels` 离线安装。若某步失败，可从开始菜单「搭建/修复运行环境」重试。

### 💾 数据存储与迁移

- 默认用户数据目录为 `.xb_svcb`，用于保存模型库、作品、在线下载素材、音频编辑工程、波形/渲染缓存、配置文件和 `theme/media` 自定义背景媒体。
- 安装时可在「选择用户数据存储位置」页把 `.xb_svcb` 放到空间充足的磁盘，避免占满 C 盘。
- 软件首页提供「数据存储位置」卡片，可查看当前目录、已用空间和所在磁盘可用空间。
- 点击「选择并迁移」会把现有数据复制到新目录；迁移前会检查目标目录可写、目标磁盘剩余空间是否足够、是否存在正在运行/排队的推理任务。
- 迁移完成后需要重启软件；重启后所有后续生成文件都会写入新目录，旧目录会在确认迁移标记后自动清理。
- 旧版本目录 `.sb-svcb` / `.xb_xvcb` / `.sv-xvcb` / `.xb-svcb` 仍会被兼容识别，升级时不会丢失已有数据。

### 📋 环境要求

| 软件                            | 用途                      | 说明                                                                                                                                       |
| ------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Python 3.10.5+**        | 运行安装器与主程序        | 安装时勾选*Add to PATH*                                                                                                                  |
| **uv**                    | 虚拟环境管理工具          | 安装器使用 uv 管理虚拟环境；用户安装好 Python 后会自动通过 pip 安装到用户目录                                                              |
| **ffmpeg**                | 音频转码 / 混音           | 安装分卷自带；系统 PATH 已有时优先使用系统版本并跳过随包释放                                                                               |
| **Git**（可选）           | 开发机获取引擎源码        | 图形安装包已自带 SVC/DDSP/SeedVC 源码；仅源码开发或重新准备发布载荷时需要                                                                  |
| **GPU 运行时**（可选）    | GPU 加速                  | NVIDIA 自动安装 cu121/cu128 PyTorch；Windows AMD Radeon 自动安装`torch-directml`；无兼容 GPU 时使用 CPU torch                            |
| **Node.js LTS**（含 npm） | 构建前端                  | 仅「从源码安装」需要                                                                                                                       |
| **C++ 生成工具**（可选）  | 编译依赖 / JUCE 插件 Host | 部分 Python 包需要 C++14 编译器；构建音频编辑器 VST3 插件 Host 需要 C++17 + CMake + JUCE；安装时勾选**Desktop development with C++** |

#### 🔗 安装链接

| 软件                               | 下载链接                                                                                                                                |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Python 3.10.5**            | [https://www.python.org/downloads/release/python-3105/](https://www.python.org/downloads/release/python-3105/)                           |
| **Git**                      | [https://git-scm.com/downloads](https://git-scm.com/downloads)                                                                           |
| **CUDA Toolkit 12.1 / 12.8** | [https://developer.nvidia.com/cuda-toolkit-archive](https://developer.nvidia.com/cuda-toolkit-archive)                                   |
| **ffmpeg**（仅源码安装）     | [https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)     |
| **Node.js LTS**              | [https://nodejs.org/](https://nodejs.org/)                                                                                               |
| **C++ Build Tools**          | [https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/](https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/) |
| **CMake**                    | [https://cmake.org/download/](https://cmake.org/download/)                                                                               |
| **JUCE**                     | [https://github.com/juce-framework/JUCE](https://github.com/juce-framework/JUCE)                                                         |

> 💡 **关于 CUDA**：安装器会先复核实际显卡，40 系及以下兼容 NVIDIA 使用 **cu121**，50 系 Blackwell 使用 **cu128**；CPU 或不兼容显卡会跳过 CUDA 并安装 CPU 版 torch。PyTorch wheel 已内置对应 CUDA 运行库，通常只需匹配的新 NVIDIA 驱动，完整 CUDA Toolkit 仅用于本地编译/工具链。

> 图形安装器会同时使用 `nvidia-smi` 与 `Win32_VideoController` 检测 NVIDIA：RTX 4060 应显示为 **cu121**，CUDA Toolkit 默认目录为 `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1`；RTX 50 系显示为 **cu128**，默认目录为 `...\CUDA\v12.8`。CPU / AMD DirectML 会明确跳过 CUDA，不会在后续安装阶段重新改成 CUDA。

> 🔴 **关于 AMD**：Windows 下检测到 AMD Radeon 时，UVR、So-VITS-SVC、RVC 与 SeedVC 安装 **DirectML + torch 2.4.1**；DDSP-SVC 暂时使用 CPU Torch，因为实机确认其完整 DirectML 图可能无异常返回却产生小声、静音或电流杂音。RVC/SeedVC 的 RMVPE 使用 CPU 稳定路径，其他受支持的神经网络仍由 AMD GPU 加速。**SeedVC 在 AMD/CPU 环境属于兼容路径，不建议非 NVIDIA 用户优先选择；AMD 用户推荐优先使用 So-VITS-SVC 或 RVC。**
>
> 🟢 **50 系显卡（RTX 5060/5070/5080/5090，Blackwell, sm_120）**：cu121 无 sm_120 内核，仅升级 torch 还会出哑音，因此安装器**检测到 50 系会自动切换到 cu128 + torch 2.7 的专用栈**（SVC / RVC 改用 Python 3.10，torchaudio I/O 走 soundfile，fairseq 重装并打 `weights_only` 补丁）。需安装 **CUDA 12.8 级别的新版 NVIDIA 驱动**；若检测不到兼容 NVIDIA 显卡，会自动回退 CPU 版 torch，避免装错 CUDA 栈。

- 安装建议：**建议直接用图形安装器**，无需任何命令行操作，选择仅此用户安装（用途一个盾标志的选项）。

#### 🧯 软件安装失败，解决方法

如果图形安装器搭建运行环境失败，可按下面步骤手动补齐依赖后重跑环境安装：

1. 安装 [Python 3.10.5](https://www.python.org/downloads/release/python-3105/)，安装时勾选 **Add Python to PATH**。
2. 重新运行安装器或开始菜单里的「搭建/修复运行环境」；脚本会自动安装 uv。若需要手动排障，也可以打开终端输入：

```bat
python -m pip install --user --upgrade uv
```

3. 按显卡型号安装 CUDA：RTX 50 系显卡安装 [CUDA Toolkit 12.8](https://developer.nvidia.com/cuda-toolkit-archive)，RTX 40 系及以下安装 [CUDA Toolkit 12.1](https://developer.nvidia.com/cuda-toolkit-archive)；CPU 用户可跳过 CUDA。
4. 确认安装目录下存在 `tools\ffmpeg\bin\ffmpeg.exe`；图形安装器会自动把该目录加入用户 `PATH`，无需另行下载。系统已有 ffmpeg 时此步骤会自动跳过。
5. 安装 [C++ Build Tools](https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/)，使用这个安装器安装 C++ 环境，建议勾选 **Desktop development with C++**。
6. 打开 XB-SVCB 软件安装路径文件夹，按住 `Shift` 右键，选择「在此处打开终端」，然后按显卡类型运行：

```bat
rem 50 系显卡（cu128）
python install\install.py --root "D:\XB-SVCB" --skip-app --skip-web --cu128 --only uvr svc rvc seedvc ddsp vocal hub models

rem 40 系及以下 NVIDIA 显卡（cu121）
python install\install.py --root "D:\XB-SVCB" --skip-app --skip-web --no-cu128 --only uvr svc rvc seedvc ddsp vocal hub models
```

> 如果安装路径不是 `D:\XB-SVCB`，请把命令里的 `D:\XB-SVCB` 改成实际安装目录。等待命令运行完毕后，软件运行环境即安装完成。

---

<a id="from-source"></a>

## 🛠️ 从源码搭建（开发者 / 高级用户）

环境搭建由 `install/install.py` 负责，入口是纯批处理 `setup_env.bat`（内部直接调 Python，**全程不涉及 PowerShell**）。在项目根目录运行：

```bat
setup_env.bat
```

将自动完成（全部落在项目目录内，便于卸载）：

| 步骤            | 产物                                                                      | 说明                                                                                                                                          |
| --------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (`app`)     | `app/.venv`                                                             | 主程序环境（pywebview）                                                                                                                       |
| 2 (`web`)     | `web/dist`                                                              | 前端构建产物                                                                                                                                  |
| 3 (`uvr`)     | `.venv-uvr`                                                             | 人声分离环境（audio-separator）                                                                                                               |
| 4 (`svc`)     | `engines/so-vits-svc` + `.venv-svc`                                   | so-vits-svc 4.1 仓库与推理环境（Python 3.9 / cu121；**50 系：Python 3.10 / cu128 + torch 2.7**）                                        |
| 5 (`rvc`)     | `.venv-rvc`                                                             | RVC 推理环境（`rvc-python`，Python 3.9 / cu121；**50 系：Python 3.10 / cu128 + torch 2.7**；安装时预置 hubert/rmvpe，缺失才镜像下载） |
| 6 (`seedvc`)  | `engines/seed-vc` + `.venv-seedvc`                                    | SeedVC 推理环境（官方 Seed-VC；模型导入 checkpoint + config，推理时选择目标音色参考音频；建议 NVIDIA CUDA 用户使用，AMD/CPU 不建议首选）      |
| 7 (`ddsp`)    | `engines/ddsp-svc` + `.venv-ddsp`                                     | DDSP-SVC 6.3、ContentVec、RMVPE 与 PC-NSF-HiFiGAN 推理环境                                                                                    |
| 8 (`vocal`)   | `.venv-vocal`                                                           | AI 歌声增强环境（DeepFilterNet + Pedalboard；安装时复制随包 DeepFilterNet 权重到缓存目录，命中后跳过联网下载）                                |
| 9 (`hub`)     | `.venv-hub`                                                             | 模型站上传组件（`modelscope` SDK；仅上传需要）                                                                                              |
| 10 (`models`) | `models/`、`engines/so-vits-svc/pretrain/`、`assets/models/seedvc/` | UVR、SVC/RVC、SeedVC、DDSP-SVC 与 DeepFilterNet 离线资产                                                                                      |

更细的控制可直接调用 `install.py`：

```bat
python install\install.py --cpu          rem CPU 版
python install\install.py --gpu          rem 自动选择 NVIDIA CUDA 或 AMD DirectML
python install\install.py --directml     rem 强制安装 AMD/Windows DirectML 版
python install\install.py --only svc     rem 只重跑某一步：app / web / uvr / svc / rvc / seedvc / ddsp / vocal / hub / models
python install\install.py --only rvc     rem 只搭建 RVC 推理环境 .venv-rvc（rvc-python）
python install\install.py --only seedvc  rem 只搭建 SeedVC 推理环境 .venv-seedvc
python install\install.py --only ddsp    rem 只搭建 DDSP-SVC 6.3 推理环境 .venv-ddsp
python install\install.py --only vocal   rem 只搭建 AI 歌声增强环境 .venv-vocal（DeepFilterNet + Pedalboard）
python install\install.py --skip-svc     rem 跳过 so-vits-svc（仅装壳 + 分离 + 前端）
```

音频编辑器的 VST3 插件系统需要额外构建 JUCE Host。安装 CMake、C++ Build Tools 和 JUCE 后：

```powershell
$env:XB_JUCE_DIR="C:\path\to\JUCE"
.\native\juce-vst3-host\build.ps1
```

构建产物会写到 `engines/juce-vst3-host/xb-juce-vst3-host.exe`，这也是源码运行时默认寻找的位置。

> 每一步都是**幂等**的：失败后重跑只补齐缺失部分。图形安装包会优先使用内置 `assets/wheels` 与离线模型；源码安装或 wheelhouse 缺失时才需要联网下载依赖/模型。

**国内加速 / 离线镜像**：图形安装包会设置 `XB_WHEELHOUSE=<安装目录>\assets\wheels` 与 `XB_WHEELHOUSE_STRICT=1`，Python 依赖优先按本机 Python 版本和 GPU 栈从本地 whl 安装；源码安装或缺少 wheelhouse 时，安装器会自动配置 `XB_HF_MIRROR` / `HF_ENDPOINT`（默认 `https://hf-mirror.com`）和 `XB_PYPI_MIRROR` / `PIP_INDEX_URL` / `UV_DEFAULT_INDEX`（默认清华 PyPI 镜像），底模与普通 Python 依赖优先走国内镜像，官方 PyPI 仅作兜底；torch 的 CUDA/CPU wheel 仍走 PyTorch 专用源，避免装错版本。GitHub 资源带 ghproxy 回退。仍不通时可手动覆盖后重跑 `python install\install.py --only models`：

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set HF_ENDPOINT=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
```

### 启动

```bat
run.bat
```

或手动：`app\.venv\Scripts\python.exe app\main.py`

---

<a id="fastapi"></a>

## 🔌 FastAPI 外部接入

v0.0.23 起可在软件的“资料库 -> API 接入”页手动启动 FastAPI 服务。默认只监听 `127.0.0.1:8765`；需要同一局域网内的其他设备调用时，可切换为局域网监听。软件不会自动开放端口，关闭软件后服务也会停止。

标准调用顺序为：

1. `POST /api/v1/uploads` 流式上传源音频，取得 `upload_id`。上传不设置文件大小上限，只受数据盘剩余空间限制。
2. `GET /api/v1/models` 获取模型和默认模型 ID。
3. `POST /api/v1/jobs` 创建任务；接口返回 `202`，任务进入与桌面端共用的推理队列。
4. 轮询 `GET /api/v1/jobs/{job_id}`，直到状态为 `done` 或 `failed`。
5. 成功后请求响应中的 `result_url` 下载成品。

除 `/health` 与接口文档外，请求必须携带软件页面显示的 `X-API-Key`。服务启动后可访问 `/docs`、`/redoc` 和 `/openapi.json`；软件内也提供真实鉴权测试和可复制的完整调用示例。HTTP API 可创建单模型、多模型和批量任务，并覆盖模型管理、作品管理及 Audio Editor Lite 的主要自动化流程。编辑工程响应使用受控音频 URL，不会泄露片段或插件的本机路径。详细字段、SeedVC 参考音频、多模型时间轴、编辑器接口和错误码见 [API 接入文档](docs/api.md)。

---

<a id="plugin-system"></a>
<a id="plugin-development"></a>

## 🔌 插件系统

v0.0.28 起，XB-SVCB 内置完整插件中心，可通过本地 `.xbplugin` 包或 GitHub 插件市场扩展工作台页面、翻唱参数预设、创建任务动作和流程钩子。插件安装后默认关闭，必须同时开启“插件功能”总开关和单个插件开关后才会运行，便于在不影响主流程的情况下逐个授权。

**用户使用**

1. 打开“插件中心”，开启插件功能总开关。
2. 选择“安装本地插件包”安装 `.xbplugin` / `.zip`，或填写 GitHub Raw/API 市场索引地址并刷新市场。
3. 安装后检查插件名称、版本、作者、权限和运行类型，再单独启用插件。
4. 对带页面的插件点击“打开”；对 Python / 混合插件，可在创建任务时通过动作或流程钩子参与翻唱流程。

**插件形态**

- **frontend**：声明式表单或自定义 Vue/TypeScript 页面，适合做参数面板、资源工具、任务创建助手和工作台页面。
- **python**：无页面的 Python 动作、生命周期和 `before_create` 翻唱钩子，适合预处理参数、生成配置或接入外部服务。
- **hybrid**：前端页面收集输入，再调用 Python 动作处理复杂逻辑，适合更完整的创作助手。

插件包以 `xb-svcb-plugin.json` 为入口，可包含 `dist/frontend/index.html`、`plugin.py`、`assets/` 和可选 `vendor/` 依赖。页面端通过 `@xb-svcb/plugin-sdk/client` 或 `@xb-svcb/plugin-sdk/vue` 调用宿主能力，包括 `runAction()`、`createWork()`、插件资源读取、通知、按插件 ID 隔离的持久化配置、插件全屏、软件窗口全屏和受限妖狐 M3U8 播放器。Python 端通过 `xb_svcb_plugin` SDK 获取上下文、动作输入、配置和插件数据目录。

**开发与打包**

```powershell
npx @xb-svcb/plugin-sdk create my-plugin `
  --id com.example.my-plugin `
  --name "我的插件" `
  --type frontend

cd my-plugin
npm install
npm run dev
npm run validate
npm run pack
```

`--type` 可选 `frontend`、`python` 或 `hybrid`；TypeScript 前端默认使用 Vue 3，也可用 `--framework vanilla` 创建原生 TypeScript 页面。发布前应至少完成 `npm run validate`、生成 `.xbplugin`，并在真实 XB-SVCB 插件中心完成一次全新安装、启用和动作执行测试。

**市场与安全边界**

插件市场使用 GitHub 上的 `market.json` / `plugins.json5` 索引，索引项指向 GitHub Release 中的 `.xbplugin` 包。当前市场不做签名、哈希校验、依赖解析、版本比较、自动更新或失败回滚；发布者需要在 Release 中写清楚兼容版本、权限、依赖和变更，用户也应只安装可信来源。

自定义页面运行在 `sandbox="allow-scripts"` iframe 中，不能直接读取宿主 DOM，只能通过宿主 Client API 调用受控能力。Python 和混合插件会以当前用户权限执行真实代码；独立 Worker 只提供崩溃隔离，不是权限沙箱。当前硬限制包括：插件包最大 20 MB、解压后最大 50 MB、清单最大 512 KB、自定义页面入口 HTML 最大 2 MB、单个插件资源最大 10 MB、页面请求和 Python Worker 单次调用默认 30 秒。

详细文档：

- 分章节教程：[插件开发文档](docs/plugins/README.md)
- 旧版全文指南：[插件开发完整指南](docs/plugin-development.md)
- SDK 命令与最小示例：[Plugin SDK README](plugin-sdk/README.md)
- 可直接构建的工程：[`plugin-sdk/examples`](plugin-sdk/examples)

---

<a id="usage"></a>

## 🎬 使用流程

1. **模型管理** —— 按框架导入模型：So-VITS-SVC 使用主模型 + 配置（可选浅扩散），RVC 使用 `.pth` + 可选 `.index`，SeedVC 使用 checkpoint + YAML，DDSP-SVC 使用 Rectified Flow `.pt` + `config.yaml`；也可在「模型站」搜索并下载社区模型。
2. **资源获取（可选）** —— 在「资源获取」页填好妖狐 API Key（QQ 想要高音质再填会员 Cookie），切换曲库（网易云 / QQ音乐 / 酷我音乐）搜索、试听并下载歌曲素材到本地。酷我试听由本地后端代理，较大的无损文件使用分段下载。
3. **新建翻唱** —— 上传或从已下载素材选歌，选择翻唱模式：

- **单模型** —— 选一个角色模型，设置变调 / F0 预测器 / 推理设备（GPU·CPU）等，整首歌统一演唱。
- **多模型混合** —— 勾选多个模型并分别设参；按歌名获取歌词、校验时长对齐（可整体偏移），再逐句指派模型。

4. **选择高级工作流（可选）** —— 默认走「自动混音合成」；多模型模式可选「自动人声合并」或「手动人声合并」；需要后期微调时选「自动 + 编辑器二次调整」，只想从素材开始剪辑时选「全手动编辑」。
5. **自动处理** —— 单模型：分离/去混响 → 分离人声修复与高频分析 → 自适应 F0 → 模型推理 → 输出人声修复 → 混音；多模型：分离/去混响 → 分离人声修复与高频分析 → 歌词分割 → 整轨逐模型推理 → 人声合并 → 输出人声修复 → 混音。检测到高音时会自动使用适合高音跟踪的 F0 路径、降低过度平滑并把可配置音高分析上限提高到最高 1800 Hz。可在创建任务时额外勾选「AI 歌声增强」，分别调节 AI 对齐、自然修音与 AI 角色共振峰等强度，再选择 basic / advanced 等级。
6. **作品库 / 音频编辑器** —— 试听 / 导出成品，单独试听**伴奏**与**干声**；失败任务一键打开日志；删除作品会真实清理其本地生成文件。需要微调时可从作品创建编辑工程，在音频编辑器中剪切、淡化、调声道、重推理片段并导出；局部重推理可勾选「重推理后自动增强」，高级层会以裁切出的原始干声保护辅音、呼吸和宽带平衡。

---

<a id="audio-editor"></a>

## 🎛️ Audio Editor Lite 音频编辑器

Audio Editor Lite 是内置的轻量多轨编辑工作台，用来完成自动翻唱后的二次调整，或直接把本地音频当作素材手动剪辑。它不是传统 DAW 的完整替代，而是围绕 AI 翻唱后期最常见的修补、对齐、淡化和导出流程设计。

**核心能力**

- **工程选择页**：音频编辑入口会先进入工程列表，可打开已有工程、导入音频新建工程、删除工程；编辑器内「退出」返回工程选择页，「放弃工程」会删除当前编辑工程。
- **真实波形时间轴**：桌面环境下由后端读取真实音频，按片段 `offset` 与片段时长生成波形；波形长度会随时间轴缩放和片段长度对齐。纯浏览器 dev 环境使用等宽模拟波形。
- **多轨片段编辑**：支持片段拖动、边界拉伸、播放头剪切、切口交叉淡化、静音、锁定、音量、淡入淡出。
- **音频剪贴板**：可将选中片段或整条音轨渲染为 WAV 并复制到操作系统剪贴板；也可把软件内复制的音频，或资源管理器复制的 WAV / MP3 / FLAC / M4A 等音频粘贴到选中音轨，多个文件会从播放头开始顺序铺开。
- **声道与预览**：片段可指定双声道 / 左声道 / 右声道；片段试听与混音预览都会按当前工程重新渲染，方便直接判断切口、淡化和声道摆位。时间轴点击与拖动以标尺真实零点换算，横向滚动后播放头仍与鼠标对齐。
- **效果器与插件**：片段可叠加混响、降噪、噪声门、压缩、EQ、高通、低通、延迟、合唱、限幅、增益等内置效果器；外部 VST3 效果器走 `Python -> C++ JUCE VST3 Host -> VST3 Plugin GUI`，前端提供组件化「插件窗口」弹窗，JUCE Host 负责 VST3 检查/加载、离线渲染、原生 GUI、state 回写与播放同步监听。目标插件前的片段信号会按播放头送入 GUI 所属实例，驱动插件频谱/VU；可听输出仍在后台重渲染后保持当前位置热切换。
- **外部插件兼容范围**：当前只支持 **64 位 Windows VST3 音频效果器**（通常为 `.vst3`），插件可以位于用户选择的任意目录，不限制在系统默认 VST3 目录。暂不支持 VST2 `.dll`、32 位插件、CLAP、AAX、AU，也不把需要 MIDI 音符的 VST3i 乐器作为人声音频效果器处理；外部侧链、特殊多总线和依赖额外采样库的插件仍取决于插件自身实现与资源完整性。
- **音量包络**：片段可启用多点音量包络，渲染时按时间线插值，适合做局部压低、渐强和句尾修整。
- **手动人声合并工程**：多模型「手动人声合并」不会先自动拼成完整人声，而是生成逐段可编辑素材；每个参与 AI 独立成轨，轨内只包含该 AI 负责的分段音频，导出默认为人声文件。
- **局部重推理**：可选中片段并指定模型重新推理替换；重推理会使用原始片段裁剪作为模型输入，清理旧推理缓存，替换后移除插件类效果并记录到片段 metadata，避免 VST3 插件效果污染新的模型干声；短于 **1 秒** 的片段会被前后端同时拦截。可勾选「重推理后自动增强」，单独调节 AI 对齐、自然修音、AI 角色共振峰、AI EQ、AI Compressor、AI Exciter、Stereo 与 AI 响度包络，高级层再以裁切出的原始干声保护真实辅音/呼吸细节；增强失败不阻塞重推理，设置会记忆到 `localStorage`。
- **导出格式**：编辑工程可导出 WAV / MP3 / FLAC。

---

<a id="multi-model"></a>

## 🧬 多模型混合翻唱流程

一首歌可以让**多个角色模型逐句轮唱**，合成一首「多人合唱 / 对唱」。整套流程分为**前台指派**与**后台合成**两段：

```mermaid
flowchart LR
    MUSIC["在线曲库<br/>网易云 / QQ音乐 / 酷我音乐"] --> SOURCE["源歌曲<br/>在线下载或本地导入"]
    LOCAL["本地 LRC / TXT"] --> ALIGN["歌词时间轴<br/>解析与时长对齐"]
    MUSIC -. 在线歌词 .-> ALIGN
    SOURCE --> SPLIT["UVR 人声分离 + 去混响"]
    SPLIT --> VOCAL["干净干声"]
    SPLIT --> INST["伴奏"]
    ALIGN --> ASSIGN["逐句指派角色模型<br/>支持同句合唱"]
    VOCAL --> INFER["各模型整轨推理<br/>SVC / RVC / SeedVC / DDSP-SVC"]
    ASSIGN --> MERGE["按时间轴取段<br/>同源连唱合并 / 换人交叉淡化 / 合唱等响叠加"]
    INFER --> MERGE
    MERGE --> MODE{"输出工作流"}
    MODE -->|自动混音| MIX["FFmpeg 人声 + 伴奏混音"]
    MODE -->|自动后编辑 / 手动合并| EDIT["Audio Editor Lite<br/>分轨 / 效果 / VST3 / 局部重推理"]
    INST --> MIX
    INST --> EDIT
    MIX --> MIXED["自动混音成品"]
    EDIT --> RENDER["工程 / 音轨 / 片段渲染<br/>WAV / MP3 / FLAC"]
    MIXED --> DELIVER(["作品库 / 文件导出"])
    RENDER --> DELIVER
```

**前台：选模型 → 取歌词 → 对齐 → 指派**

1. **选模型并设参** —— 在「新建翻唱」切到「多模型混合」，勾选多个角色模型；每个模型可单独设变调 / F0 预测器 / 扩散步数 / 推理设备（GPU·CPU）。
2. **获取歌词** —— 输入歌名（可选曲库与单曲序号），自动拉取带时间轴的 LRC 歌词。网易响应依次尝试 `data.lrctxt`、`data.lrc`、`data.music.lrcurl` 与 `data.music.lrc`；QQ 免费详情不直接带歌词时，从 `data.html` 提取歌曲 `mid` 并调用妖狐聚合歌词接口；酷我直接解析 `data.lyric.lrc` / `data.lyric.lrclist`，缺少 RID 时回查搜索结果。
3. **对齐校验** —— 比对歌词时间轴与音频实际时长；若有系统性偏差，用「整体偏移」滑杆整体平移到对齐。
4. **逐句指派（支持合唱）** —— 给每一句歌词选择由哪个模型演唱；**一句可同时选多个模型实现「合唱」**（界面会标注「合唱」）；未指派 / 标记为「间奏·不唱」的句子会保留原始（近静音）人声占位。

**后台：分离 → 整轨推理 → 合并 → 混音**

1. **人声分离 + 去混响** —— 与单模型一致，得到干净干声与伴奏。
2. **整轨逐模型推理** —— 每个参与模型都在**完整人声**上推理一次（而非逐句切片送推）。整轨上下文连续，避免短碎片产生的句首/句尾电流声与咔哒声。
3. **按时间轴合并（含合唱叠声）** —— 自动流程会把相邻、且指派给**同一组模型**的句子并成一个连续段，从对应整轨结果整块切出；**合唱句把多路人声按 `1/√N` 等响度叠加并经软限幅（`alimiter`）防破音**；仅在**真正换人处**用交叉淡化（`acrossfade`）无缝衔接，并多借少量素材补回交叉消耗，保证总时长与伴奏精确对齐、不漂移。
4. **手动人声合并** —— 该流程会跳过自动拼接，改为生成编辑器分段素材：一个 AI 一条轨，每个片段只包含该 AI 在对应时间段的声音；试听与导出时在拼接处应用交叉淡化。
5. **混音输出** —— 自动流程会把合并后的完整人声与原伴奏混音，得到多人合唱成品；手动人声合并则进入编辑器由用户调整后导出人声。

> 💡 间奏、前奏、尾奏等没有指派模型的区间会自动以原始人声（分离后近静音）填充，确保整条时间轴连续、不会错位。

---

<a id="model-hub"></a>

## 🌐 模型站（ModelScope 魔搭社区）

在「声音模型 → 模型站」标签页，可以把训练好的模型分享到社区，也能搜索并下载别人分享的模型。浏览和下载不要求本地 Access Token，模型传输会在软件内显示进度。

**方案要点（每人自有令牌 + 标记防污染）**

- **自有令牌**：在「ModelScope 设置」填入你自己的访问令牌（[个人中心 → 访问令牌](https://www.modelscope.cn/my/myaccesstoken)），仅保存在本地。上传只会发布到**你自己的命名空间**。
- **防污染**：上传的仓库统一带 `xb-svcb-` 前缀，并写入带签名标记的清单文件 `xb-svcb-model.json`（含 `magic` / 架构 / 各文件角色）。搜索/下载时只保留「带前缀且清单校验通过」的条目，避免被无关模型干扰。
- **架构标签**：上传时标注模型框架（**So-VITS-SVC** / RVC / SeedVC 等），便于他人按类型筛选；搜索结果可按架构过滤，为后续多框架兼容预留。

**搜索 / 下载**

1. 在搜索框输入关键词（支持中文、多词**模糊匹配**，留空浏览全部），可叠加架构筛选；浏览公开模型无需先填写访问令牌。
2. 命中结果会先列出**你自己命名空间**内的模型（上传后必定可见），再合并全站按标记搜索到的社区模型；列表支持按综合排序、下载排行和更新时间排序。
3. 搜索结果会显示版本、下载数、标签、依赖状态，以及可用的截图 / 试听素材；点「详情」可查看完整清单、依赖检查和版本信息。
4. 点「下载导入」即流式下载（按字节显示**进度条**），完成后自动导入到「本地模型」；从模型站导入的模型会记录来源仓库与版本，用于后续更新提醒。

**上传分享**

1. 在「本地模型」列表对某个模型点「分享到模型站」，确认/选择其框架架构，并填写版本、简介、标签，可选试听音频（需可解析音频，≤1GB）与截图。
2. 软件打包模型文件 + 生成清单后，经独立上传组件逐个文件上传（按文件显示**进度条**）；清单会记录文件角色、版本、依赖、展示素材和生态元数据。
3. 完成后即在你的 ModelScope 公开仓库可见，社区可搜索下载；已下载的来源模型支持检查远端版本并一键拉取最新版本导入。

> 💡 只有模型上传需要独立的 `.venv-hub`（含 `modelscope` SDK），由安装器的「模型上传组件」步骤创建；**搜索和下载仅用内置 httpx，无需该组件**。

---

## 📁 目录结构

```
翻唱工具/
├─ app/                              # Python 主程序与共享业务核心
│  ├─ api/                           #   pywebview Bridge 与 FastAPI HTTP 接入
│  ├─ application/                   #   转换、模型、曲库、作品、编辑器与 PluginService
│  ├─ domain/                        #   实体、枚举与核心业务模型
│  ├─ infrastructure/                #   引擎适配、仓储、FFmpeg、JUCE 与全部 worker
│  │  └─ plugin_worker.py            #     Python/混合插件独立进程入口
│  ├─ tests/                         #   后端、安装器与插件平台回归测试
│  ├─ config.py                      #   数据、引擎、插件和随包资源路径
│  ├─ main.py                        #   桌面应用入口
│  ├─ pyproject.toml
│  └─ uv.lock
├─ web/                              # Vue 3 + Vite + Element Plus 前端
│  ├─ public/
│  ├─ src/
│  │  ├─ api/                        #     Bridge/HTTP Client 与共享类型
│  │  ├─ components/                 #     布局、编辑器和主题组件
│  │  ├─ stores/                     #     Pinia 状态与通知/传输管理
│  │  └─ views/plugins/              #     插件中心与自定义页面宿主
│  ├─ package.json
│  └─ vite.config.ts
├─ plugin-sdk/                       # 插件开发、校验、打包与页面/Python SDK
│  ├─ bin/xb-plugin.mjs              #   create / validate / pack CLI
│  ├─ python/xb_svcb_plugin/         #   Python Plugin、Context、动作与钩子 API
│  ├─ examples/                      #   前端、Python、混合插件示例工程
│  ├─ tests/                         #   SDK 运行时测试
│  ├─ index.mjs                      #   清单构建与校验
│  ├─ client.mjs                     #   iframe 页面宿主 Client
│  └─ vue.mjs                        #   Vue 响应式宿主封装
├─ docs/
│  ├─ plugins/                       # 插件入门、清单、前端、Python、测试与发布
│  ├─ api.md                         # HTTP API 接入文档
│  └─ plugin-development.md          # 完整插件开发手册
├─ assets/
│  ├─ models/                        # 安装分卷携带的 UVR/SVC/RVC/SeedVC/DDSP/Vocal 底模
│  ├─ tools/ffmpeg/                  # 随包 FFmpeg 许可与构建时准备的二进制
│  └─ icon/                          # 应用与安装器图标
├─ native/juce-vst3-host/            # C++ / JUCE VST3 Host 源码与构建脚本
├─ installer/                        # PyInstaller + Inno Setup 发布构建
│  ├─ xb-svcb-app.spec
│  ├─ xb-svcb.iss
│  ├─ xb-svcb-version.txt
│  └─ build.ps1
├─ install/                          # 用户机环境检测、wheelhouse 与隔离环境部署
├─ setup_env.bat                     # 搭建/修复运行环境入口
├─ install_prereqs.bat               # 安装器前置依赖入口
├─ run.bat / run.ps1                 # 源码运行入口
├─ release_notes_v*.md               # 各版本更新说明
├─ CONTRIBUTING.md
└─ README.md
```

> 运行或构建时生成的 .xb_svcb/、.venv-*、engines/、models/、web/dist/、dist/ 与 .tmp/ 不属于主程序源码；本地插件项目 test-plugins/ 及 .xbplugin 包也独立于主仓库管理。

---

## ⚙️ 自定义路径（环境变量覆盖）

无需改代码，用环境变量即可指向自有的引擎 / 模型（优先级高于项目内默认）：

| 变量                            | 含义                                                                                                        |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `XB_DATA_DIR`                 | `.xb_svcb` 用户数据目录；兼容旧变量 `XB_SVCB_DATA_DIR` / `XB_SB_SVCB_DATA_DIR` / `XB_XVCB_DATA_DIR` |
| `XB_SOVITS_REPO`              | so-vits-svc 仓库根目录                                                                                      |
| `XB_SVC_PYTHON`               | 运行 SVC 推理的 Python 解释器                                                                               |
| `XB_RVC_PYTHON`               | 运行 RVC 推理的 Python 解释器                                                                               |
| `XB_SEEDVC_REPO`              | Seed-VC 仓库根目录，目录内需包含`inference.py`                                                            |
| `XB_SEEDVC_PYTHON`            | 运行 SeedVC 推理的 Python 解释器                                                                            |
| `XB_DDSP_REPO`                | DDSP-SVC 仓库根目录，目录内需包含`main_reflow.py`                                                         |
| `XB_DDSP_PYTHON`              | 运行 DDSP-SVC 推理的 Python 解释器                                                                          |
| `XB_UVR_PYTHON`               | 运行 audio-separator 的 Python 解释器                                                                       |
| `XB_VOCAL_ENHANCEMENT_PYTHON` | 运行 AI 歌声增强 worker（DeepFilterNet + Pedalboard）的 Python 解释器                                       |
| `XB_UVR_MODEL_DIR`            | UVR 模型目录                                                                                                |
| `XB_UVR_SEP_MODEL`            | 分离模型文件名（默认`5_HP-Karaoke-UVR.pth`）                                                              |
| `XB_UVR_DEREVERB_MODEL`       | 去混响模型文件名（默认`UVR-DeEcho-DeReverb.pth`）                                                         |
| `XB_HUB_PYTHON`               | 模型站上传 worker 使用的 Python 解释器                                                                      |
| `XB_JUCE_VST3_HOST`           | JUCE VST3 Host 路径（默认`engines/juce-vst3-host/xb-juce-vst3-host.exe`）                                 |

---

## 🧠 底模来源（自带优先，缺失才联网下载）

模型获取采用 **「自带优先」** 策略：若 `assets/models/` 内已随安装包附带对应文件，安装时**直接本地复制**（瞬间完成、不联网）；只有缺失项才回退到镜像下载。

| 模型                                                        | 用途                                 | 自带去向 / 下载来源                                                                                                                                                                 |
| ----------------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `checkpoint_best_legacy_500.pt`                           | ContentVec / RVC hubert 语音编码器   | `assets/models/pretrain/` → `engines/so-vits-svc/pretrain/`，并硬链接或复制为 `.venv-rvc/.../base_model/hubert_base.pt`；缺失则使用 Hugging Face 镜像                        |
| `nsf_hifigan/`                                            | NSF-HiFiGAN 声码器 / 浅扩散          | 部署到 so-vits-svc 与 DDSP-SVC 预训练模型目录；缺失则使用 openvpi/vocoders Releases                                                                                                 |
| `rmvpe.pt`                                                | SVC / RVC / SeedVC / DDSP 共用 RMVPE | 部署到 so-vits-svc、RVC base_model、SeedVC checkpoints 与 DDSP-SVC`pretrain/rmvpe/model.pt`；缺失则使用镜像下载                                                                   |
| DDSP ContentVec`pytorch_model.bin`                        | DDSP-SVC 内容编码器                  | 安装分卷离线携带并释放到`engines/ddsp-svc/pretrain/contentvec/`，无需目标机器另行下载                                                                                             |
| `fcpe.pt`                                                 | 高音域 FCPE F0 预测器                | 随安装分卷离线携带并部署到 So-VITS-SVC；检测到极高音时自动启用                                                                                                                      |
| `seedvc/campplus_cn_common.bin`                           | SeedVC 目标音色编码器                | worker 优先读取随包文件，并部署到`engines/seed-vc/checkpoints/`                                                                                                                   |
| `seedvc/whisper-small/`                                   | SeedVC 语音内容编码器                | worker 通过本地临时配置直接读取完整 Whisper Small 快照                                                                                                                              |
| `seedvc/bigvgan_v2_44khz_128band_512x/`                   | SeedVC 44.1kHz 声码器                | worker 通过本地临时配置直接读取 BigVGAN 快照                                                                                                                                        |
| `5_HP-Karaoke-UVR.pth` / `UVR-DeEcho-DeReverb.pth`      | 人声分离 / 去混响                    | `assets/models/uvr/` → `models/uvr/`；缺失则由 audio-separator 下载                                                                                                            |
| `vocal-enhancement/DeepFilterNet/.../model_120.ckpt.best` | AI 歌声增强神经降噪权重              | `assets/models/vocal-enhancement/DeepFilterNet/` → `models/vocal-enhancement/.local/DeepFilterNet/`（`init_df()` 命中后跳过联网下载）；缺失则由 DeepFilterNet 走官方缓存下载 |

> 自带模型为 Git LFS 管理的二进制大文件。构建脚本会校验关键权重大小，拒绝把 LFS 指针或残缺快照打进发布包；安装数据会拆成小于 2GB 的 `XB-SVCB-Setup-*.bin` 分卷，与 `XB-SVCB-Setup.exe` 一起通过 **GitHub Releases** 分发（详见 `assets/models/README.md`）。联网回退时底模走 **hf-mirror 镜像**，GitHub 资源带 **ghproxy 回退**并逐源重试。

---

<a id="faq"></a>

## ❓ 常见问题

<details>
<summary><b>so-vits-svc 依赖现场编译失败（numpy / pyworld 等 <code>could not get source code</code>）</b></summary>

<br/>

so-vits-svc 4.1 的依赖是为 **Python 3.8~3.9** 钉的旧版本，只有 3.9 及更低才有预编译 wheel，3.10 上会回退源码编译并失败。安装器已把 **SVC 引擎固定用 Python 3.9**（uv 自动下载），整套依赖直接装 wheel、零编译；UVR 分离环境仍用 3.10。旧版本升级时重跑 `--only svc` 会自动把 `.venv-svc` 重建为 3.9。

</details>

<details>
<summary><b>推理报 <code>No module named 'pkg_resources'</code></b></summary>

<br/>

`.venv-svc` 由 `uv venv` 创建，默认不含 setuptools，而 librosa 运行时需要 `pkg_resources`。**setuptools 81+ 已移除 pkg_resources**，必须钉 `<81`。安装器已自动给子环境装 `setuptools<81`；旧环境手动补：

```bat
uv pip install --python <安装目录>\.venv-svc\Scripts\python.exe "setuptools<81" wheel
```

</details>

<details>
<summary><b><code>playsound==1.3.0</code> 构建失败</b></summary>

<br/>

该包仅 WebUI 播放用、推理用不到。安装器已自动从依赖清单剔除 **playsound / gradio / pyaudio / sounddevice / onnxsim / onnxoptimizer**（实时变声与 ONNX 导出专用），无需理会。

</details>

<details>
<summary><b>底模下载超时（<code>WinError 10060</code> / huggingface 连不上）</b></summary>

<br/>

安装器会自动设置 `HF_ENDPOINT=https://hf-mirror.com`、`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 并换源重试。仍不行时设 `XB_HF_MIRROR` / `HF_ENDPOINT` / `XB_PYPI_MIRROR` / `XB_GH_MIRROR` 后重跑 `python install\install.py --only models`，或手动下载放入对应目录。

</details>

<details>
<summary><b>分离 / 去混响很慢</b></summary>

<br/>

CPU 模式下模型较慢。使用 `python install\install.py --gpu` 会自动选择 NVIDIA CUDA 或 AMD DirectML；NVIDIA 40 系及以下使用 cu121，**50 系（Blackwell）自动改用 cu128 + torch 2.7 专用栈**，AMD Radeon 使用 DirectML，无兼容 GPU 时继续使用 CPU torch。

</details>

<details>
<summary><b>其它</b></summary>

<br/>

- **中文歌名**：内部统一用 UTF-8 + 结果文件传递路径，支持中文文件名。
- **任务失败**：在「作品库」点失败项「打开日志」，查看 `run.log` 与各步骤子进程输出定位原因。
- **fairseq 安装失败**：安装「Microsoft C++ Build Tools」后重跑 `--only svc`，或设 `XB_SVC_PYTHON` 指向已配好的环境。

</details>

---

<a id="roadmap"></a>

## 🗺️ 发展规划（Roadmap）

> 产品定位：**XB-SVCB = AI 语音转换平台 + 模型中心 + 混唱工作台 + 音频编辑器 + 创作工作流管理**。
> 从「一条龙翻唱工具」逐步演进为完整的 **AI 翻唱创作平台**。下列清单会随版本推进持续勾选更新。

### 🎯 1.0 版本目标（核心能力）

- [X] So-VITS-SVC 推理
- [X] 模型站
- [X] 模型上传 / 下载
- [X] 多模型混唱
- [X] RVC 支持
- [X] SeedVC 支持
- [X] DDSP-SVC 6.3 支持
- [X] 可视化时间轴
- [X] 音频编辑器
- [X] 多框架统一管理
- [X] 编辑工程系统

### ⭐ 当前最优先实现顺序

考虑个人开发者精力，已完成 **RVC + SeedVC + DDSP-SVC + 时间轴混唱 + 基础音频编辑**，下一步优先补自动化与工程化能力：

1. 自动切句增强（静音检测与 TXT 歌词自动切句已完成）
2. 预设参数保存
3. 模型元数据标准化与自动检测
4. 工程导入导出
5. 更多框架接入与自动识别
6. 模型兼容性与导入校验增强

### 📌 分阶段清单

<details open>
<summary><b>阶段一 · 推理生态完善（近期）</b> —— 支持主流 VC 模型、完善模型管理、提升推理体验</summary>

<br/>

- [X] RVC 支持
- [X] RVC Index 自动识别
- [X] SeedVC 支持
- [X] 后端统一接口抽象
- [X] 模型元数据标准化
- [X] 模型自动检测与修复
- [X] 推理任务队列
- [X] 批量推理
- [X] 推理历史记录
- [X] 预设参数保存
- [X] 模型收藏功能

</details>

<details>
<summary><b>阶段二 · 混合翻唱系统（优先级最高）</b> —— 解决多人翻唱制作困难</summary>

<br/>

- [X] 可视化时间轴
- [X] 时间轴缩放
- [X] 时间轴拖拽编辑（边界拖动 + 吸附歌词时间）
- [X] 音频波形显示（音频编辑器真实波形）
- [X] 自动切句
- [X] 静音检测切句
- [X] 片段模型分配（片段与歌词解耦，独立指派）
- [X] 批量模型分配（一键全部指派）
- [X] 句内合唱（一句多模型同唱）
- [X] 片段拆分 / 合并 / 删除
- [X] 多角色管理
- [X] 时间轴模板
- [X] 歌词导入（LRC）
- [X] 歌词导入（TXT）
- [X] 歌词辅助显示
- [X] 歌词时间轴编辑（拖动片段边界即调整）
- [ ] 自动歌词识别
- [ ] 自动时间轴生成

</details>

<details>
<summary><b>阶段三 · 音频编辑器</b> —— 减少对第三方软件的依赖</summary>

<br/>

- [X] 音频裁剪
- [X] 音频切片
- [X] 音频拼接
- [X] 淡入淡出
- [X] 音量调节
- [X] 片段/音轨音频复制到系统剪贴板
- [X] 从剪贴板粘贴音频到音轨
- [X] 音量包络
- [X] 内置效果器与 JUCE VST3 插件 Host
- [X] 多轨道编辑（人声 / 伴奏 / 和声轨道）
- [X] 真实波形显示
- [X] 片段声道分配（双声道 / L / R）
- [X] 局部重推理替换片段
- [X] 工程选择 / 删除 / 放弃工程
- [X] 实时试听（播放中效果自动重渲染并热切换）
- [X] 音频格式转换
- [X] 导出 WAV / FLAC / MP3

</details>

<details>
<summary><b>阶段四 · 模型生态</b> —— 建立模型共享生态</summary>

<br/>

- [X] 模型标签系统（架构标签）
- [X] 模型搜索优化（模糊搜索 + 分页加载）
- [X] 模型版本管理
- [X] 模型更新提醒
- [X] 一键升级模型
- [X] 模型依赖检查
- [X] 模型截图展示
- [X] 模型试听功能

</details>

<details>
<summary><b>阶段五 · 多框架支持</b> —— 统一管理多种 AI 语音转换模型</summary>

<br/>

- [X] Seed-VC
- [ ] Diffusion-SVC
- [ ] OpenVoice
- [ ] GPT-SoVITS 推理
- [ ] CosyVoice
- [ ] Fish Speech
- [X] 多框架统一模型管理
- [ ] 框架自动识别
- [ ] 跨框架混合工程
- [ ] 跨框架时间轴编排

</details>

<details>
<summary><b>阶段六 · 创作工具增强</b> —— 从推理工具升级为创作平台</summary>

<br/>

- [X] 编辑工程系统
- [ ] 自动保存
- [ ] 工程导入导出
- [X] 多工程管理（音频编辑工程列表）
- [ ] 作品库（封面管理 / 作品分类）
- [ ] 一键导出视频
- [ ] 字幕生成
- [ ] 歌词视频生成
- [ ] MV 模板支持

</details>

<details>
<summary><b>阶段七 · 硬件兼容</b> —— 扩大用户覆盖范围</summary>

<br/>

- [X] AMD GPU 支持（Windows DirectML；四个歌声模型框架 + UVR）
- [X] DirectML 支持
- [X] UVR ONNX Runtime DirectML 推理
- [ ] Intel GPU 支持
- [ ] Ascend 昇腾支持
- [ ] CPU 推理优化
- [ ] 多 GPU 调度

</details>

---

## 📦 构建发布安装包（开发者）

最终用户使用的图形安装器由 PyInstaller 与 Inno Setup 共同生成。发布前需准备 Node.js、应用虚拟环境、CMake、C++ Build Tools、JUCE 和 Inno Setup 6：

1. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)（提供 `ISCC.exe`）。
2. 安装 CMake、C++ Build Tools 和 JUCE，并设置 `XB_JUCE_DIR` 指向 JUCE 源码目录。
3. 可先运行轻量校验，检查版本、worker、SeedVC 离线权重和 Inno Setup/Pascal 脚本，不压缩数 GB 模型或下载 whl：

```powershell
./installer/build.ps1 -ValidateOnly
```

4. 在项目根目录运行完整构建：

```powershell
./installer/build.ps1
```

5. 完整构建会以 `--clean` 运行 `install/prepare_wheelhouse.py`，重新生成 `assets/wheels` 并写入 `assets/wheels/wheelhouse.json`；只有确认 wheelhouse 已存在且完整时，才可临时使用 `-SkipWheelhouse`。
6. 将 `dist/XB-SVCB-Setup.exe` 与全部 `dist/XB-SVCB-Setup-*.bin` 一起上传到 GitHub Releases；用户下载后也必须把这些文件放在同一目录。

```mermaid
flowchart LR
    CHECK["发布前校验<br/>版本 / API 文档 / workers / 模型权重"] --> WEB["Vite 构建<br/>web/dist"]
    WEB --> APP["PyInstaller<br/>XB-SVCB.exe + FastAPI + 前端 + workers"]
    APP --> HOST["CMake + JUCE<br/>VST3 Host"]
    HOST --> STAGE["发布目录完整性校验<br/>应用 / 前端 / workers / Host / 安装脚本"]

    ASSETS["assets/models 离线资产<br/>UVR / SVC / RVC / SeedVC / DDSP / DeepFilterNet"] --> ISCC["Inno Setup 6<br/>分卷打包"]
    WHEELS["assets/wheels 离线 whl<br/>py310/py39 + CPU/DirectML/cu121/cu128"] --> ISCC
    STAGE --> ISCC

    ISCC --> EXE["XB-SVCB-Setup.exe<br/>安装引导程序"]
    ISCC --> BIN["XB-SVCB-Setup-*.bin<br/>每卷小于 2 GB"]
    EXE --> INSTALL["用户安装向导<br/>安装路径 / GPU 栈 / 环境搭建"]
    BIN --> INSTALL
    INSTALL --> READY["组件校验<br/>完成或稍后单步修复"]
```

| 文件                              | 作用                                                                      |
| --------------------------------- | ------------------------------------------------------------------------- |
| `installer/xb-svcb.iss`         | Inno Setup 脚本：分卷、快捷方式、安装后环境搭建、完整性检查与卸载清理     |
| `installer/build.ps1`           | 构建前端、PyInstaller 应用和 JUCE Host，校验发布目录并调用 ISCC           |
| `installer/xb-svcb-app.spec`    | 定义 PyInstaller 运行目录、内置前端及所有 AI worker                       |
| `install/install.py`            | 创建 SVC / RVC / SeedVC / DDSP-SVC / UVR / Vocal / Hub 隔离环境并部署底模 |
| `install/prepare_wheelhouse.py` | 发布构建时预下载 Windows whl，并生成`assets/wheels/wheelhouse.json`     |
| `setup_env.bat`                 | 用户机搭建或修复运行环境入口（纯 batch，无 PowerShell）                   |
| `install_prereqs.bat`           | 图形安装器调用的前置依赖检查与安装入口                                    |

**设计说明**

- 构建会强制核对 `app/config.py`、`pyproject.toml`、Python 锁文件、前端包及 Inno Setup 的版本号，避免混装不同版本。
- PyInstaller 运行目录内包含当前 `web/dist` 与 SVC / RVC / SeedVC / DDSP-SVC / UVR / Vocal / Hub workers，最终用户无需安装 Node.js。
- 安装器携带预构建的 `xb-juce-vst3-host.exe`；开发者仅在确认已有正确产物时使用 `-SkipJuceHostBuild`。
- `assets/models/` 包含 UVR、SVC/RVC 底模、SeedVC 所需 RMVPE、CampPlus、Whisper Small、BigVGAN，以及 AI 歌声增强所需的 DeepFilterNet3 权重；缺少或疑似 LFS 指针时构建直接失败（DeepFilterNet 权重校验阈值 8 MB）。
- `assets/wheels/` 包含 `uv` bootstrap wheel，以及按 `py310/cpu`、`py310/directml`、`py310/cu121`、`py310/cu128` 分组的 Python 依赖；对 SVC/RVC 的 py39 和 DirectML 下 DDSP/Vocal 这类 torch 版本冲突环境，会额外使用组件子目录；安装器会写入 `XB_WHEELHOUSE_STRICT=1`，缺 whl 时直接报错，避免在用户机器临时解析/编译。
- Inno Setup 使用 `DiskSpanning` 生成小于 2GB 的 `.bin` 分卷。EXE 不是完整离线包，发布和安装时都不能遗漏任何分卷。
- 安装完成后会复核应用组件、UVR、SeedVC、DDSP-SVC 与 AI 歌声增强的 Python、worker 和上游推理入口；失败时给出修复命令和日志位置。
- 卸载时清理安装目录内生成的 `.venv-*`、`engines/` 和 `models/`；可迁移的 `.xb_svcb` 用户数据默认保留。

---

<a id="thanks"></a>

## 🙏 致谢

- 🧁 **模型来源** —— 目前软件内可用 / 演示的**绝大部分声音模型，均由「白菜工厂1145号员工」提供**。在此特别致谢 🙏，正是这些模型让本工具能开箱即用地体验完整翻唱流程。
- 📌 模型版权归原作者所有，请在其授权范围内使用；如有侵权或需要下架，请联系作者处理。
- 🛠️ 同时感谢上游开源项目：[so-vits-svc](https://github.com/svc-develop-team/so-vits-svc)、[rvc-python](https://github.com/daswer123/rvc-python) / RVC、[Seed-VC](https://github.com/Plachtaa/seed-vc)、[DDSP-SVC](https://github.com/yxlllc/DDSP-SVC)、[Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)、[DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)、[Pedalboard](https://github.com/spotify/pedalboard)、[ModelScope 魔搭社区](https://www.modelscope.cn/) 等。
- 🚀 后续会把更多模型逐一上传到「模型站」，方便在软件内直接搜索下载。

---

## 📄 许可

本项目自身代码采用 **[GNU General Public License v3.0 only（GPL-3.0-only）](LICENSE)**。Copyright © 2026 SDIJF1521。

> ⚠️ 本项目依赖/附带的第三方组件各自遵循其原始协议，使用与再分发时请遵守：
>
> - **so-vits-svc 4.1**（`svc-develop-team/so-vits-svc`）：源码随安装分卷携带，遵循上游 **AGPL-3.0**。
> - **DDSP-SVC 6.3**（`yxlllc/DDSP-SVC`）：源码随安装分卷携带，遵循上游 **MIT License**。
> - **底模**：ContentVec、NSF-HiFiGAN、RMVPE、FCPE 等各有其许可。
> - **UVR 模型**：`5_HP-Karaoke-UVR`、`UVR-DeEcho-DeReverb` 等遵循 Ultimate Vocal Remover 项目相应许可。
>
> GPL-3.0-only 仅覆盖本仓库自有代码，不改变上述第三方组件、模型和资源的原始授权条款。
