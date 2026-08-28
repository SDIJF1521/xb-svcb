## v0.0.24 · 全新 AI 歌声增强工程 + DeepFilterNet 离线化

> 本次更新为 AI 翻唱全链路引入全新的「AI 歌声增强工程」：针对 AI vocoder 留下的电子噪声与机械感设计 vocalfloor 软衰减、原始人声频谱参考匹配与 Pedalboard 专业母带 DSP，并直接把 DeepFilterNet 权重打包进安装器，全新机器离线开箱即用。

> [!IMPORTANT]
> v0.0.24 继续使用分卷安装包。请同时下载 `XB-SVCB-Setup.exe` 和全部 `XB-SVCB-Setup-*.bin`，放在同一目录后再运行安装程序。

### 🎵 作品播放页与歌词搜索

- 作品库和首页的播放按钮会以过渡动画进入独立音乐播放页，提供播放进度、音量、跳转和导出控制。
- 播放页支持歌词逐句跟随高亮、点击歌词跳转，以及导入本地 LRC 文件。
- API 歌词支持先按歌名 / 歌手搜索，再从网易云音乐、QQ 音乐或酷我音乐候选结果中选择具体序号获取对应版本歌词；曲库设置仍可在本地保存。
- 每首作品可导入图片或 MP4 MV 画面，关联按作品保存，重新打开播放页会自动恢复。

### 🎤 全新 AI 歌声增强工程

- 🎙️ **两层增强等级**：新增 `basic` 与 `advanced` 两个层级。basic 层做 DeepFilterNet 神经降噪 + 基础美声 EQ；advanced 层在 basic 之上叠加频谱参考匹配与精细母带 EQ + 胶水压缩。等级可在创建翻唱任务或编辑器重推理时选择，默认关闭。
- 🔻 **vocalfloor 软衰减**：SVC 推理在静音段会留下 -35~-45 dB 的电子噪声（vocalfloor）。采用 150 ms 指数衰减到 -75 dB 的软衰减策略，在抑制电子噪声的同时保留呼吸声与空间混响，避免硬性静音带来的突兀感。
- 🎚️ **频谱参考匹配**：AI vocoder 典型地在 80-600 Hz 中低频与 2.5k-16k 高频出现能量缺陷。advanced 层以原始人声（或编辑器裁切出的干声）作为参考，按频段对齐 AI 翻唱频谱，比盲目 EQ 更精准，避免破坏音色平衡。
- 🎛️ **Pedalboard 精细母带 DSP**：advanced 层包含去齿音、温暖中低频、低频厚度、presence、高频空气感与胶水压缩，针对 AI 翻唱频谱缺陷做精细整形。不叠加 Distortion/Chorus/Reverb 等会"合成器化"的效果，避免加重 AI 感。
- 🔄 **完整流水线**：UVR 分离 → AI 翻唱推理 → 增强（vocalfloor 软衰减 + 频谱参考匹配）→ DeepFilterNet → Pedalboard 母带。
- 🧹 **不采用 VoiceFixer 方案**：VoiceFixer 是为修复损坏语音录音设计的神经修复模型，对高质量 AI 翻唱会破坏原始音色与伴奏细节，效果反而变差。本次全新设计的增强工程不引入 VoiceFixer，并清理了安装器中遗留的 VoiceFixer 预装。

### 🎙️ 编辑器局部重推理支持自动增强

- ⚡ **重推理后自动增强**：Audio Editor Lite 的局部重推理现可勾选「重推理后自动增强」，复用同一套增强流水线，以裁切出的干声作为参考进行频谱匹配。
- 🧩 **失败不阻塞**：增强子步骤失败不会阻塞重推理本身，原始重推理结果仍然保留，仅在前端提示增强未完成。
- 💾 **偏好持久化**：开关状态与等级选择默认关闭，记忆到 `localStorage`，下次打开工程自动恢复。

### 📦 DeepFilterNet 模型离线化

- 🗂️ **权重随安装包分发**：`model_120.ckpt.best` 直接打包进 `assets/models/vocal-enhancement/DeepFilterNet/`，安装时由 `copy_bundled` 复制到运行时缓存目录，`init_df()` 命中本地文件后跳过联网下载。
- 🌐 **全新机器开箱即用**：不再依赖首次生成时联网拉取 DeepFilterNet 权重，离线环境与国内网络不稳定场景下也能立即完成增强。
- 🧪 **构建期 LFS 校验**：`installer/build.ps1` 新增 `Require-FileSize` 校验，确保 DeepFilterNet 权重不小于 8 MB，拒绝把 Git LFS 指针或残缺文件打进安装包。

### 🔧 安装器与依赖清理

- 🪦 **VoiceFixer 预装移除**：移除安装器中 `pip --no-deps voicefixer==0.1.3` 安装步骤、probe 脚本和 `runtime.ready` 中的版本记录，减少冗余依赖与安装体积。
- 📝 **文档与注释同步**：`app/config.py`、`app/api/http_server.py`、`app/infrastructure/vocal_enhancement.py` 与 `assets/models/README.md` 中所有 VoiceFixer 引用都已移除或更新为「DeepFilterNet + Pedalboard」，避免误导用户和后续开发者。
- 📋 **高级层 API 描述**：`/api/v1` 文档中 `level` 参数的 `advanced` 描述为「额外做频谱参考匹配与专业母带 DSP」，与实际行为一致。

### 🛡️ 兼容性

- 通道平衡不受影响：vocalfloor 软衰减、频谱匹配、DeepFilterNet 与 Pedalboard 母带均独立处理声道或对立体声施加 EQ 而不改变平衡，左右声道结构保持原样。
- v0.0.23 的 NVIDIA CUDA、AMD DirectML 与 CPU 推理策略、外部 FastAPI 接入和酷我音乐曲库均保持不变。
- 已安装 v0.0.23 的用户可覆盖升级；模型、作品、下载素材、编辑工程、API 上传、设置、消息状态和主题媒体继续使用原数据目录。

### ✅ 验证

- DeepFilterNet 本地化路径校验：在干净的 `LOCALAPPDATA` 下设置环境变量后 `init_df()` 成功命中 `<安装目录>/models/vocal-enhancement/.local/DeepFilterNet/DeepFilterNet/Cache/DeepFilterNet3/checkpoints/model_120.ckpt.best`，跳过联网下载。
- 安装器 `copy_bundled` 链路验证：模型文件按预期从 `assets/models/vocal-enhancement/DeepFilterNet/` 复制到运行时缓存目录。
- `installer/build.ps1 -ValidateOnly` 通过 Inno Setup 6 脚本编译校验；`Require-FileSize` 阈值设为 8 MB（8388608 字节），实际权重约 8.31 MB。
- Python 编译、前端 TypeScript 检查与生产构建均通过。

### 📦 安装与升级

- 应用本体、Python 项目、前端包、两份锁文件、Windows EXE 版本资源和 Inno Setup 均已同步为 **v0.0.24**。
- 安装器会把 `README.md`、`release_notes_v024.md` 与 `docs/api.md` 一起释放到安装目录，便于离线查看功能、升级说明和 API 契约。
- 已安装旧版可覆盖升级；模型、作品、下载素材、编辑工程、API 上传、设置、消息状态和主题媒体继续使用原数据目录。
- 下载 `XB-SVCB-Setup.exe` 和同一版本的全部 `XB-SVCB-Setup-*.bin`，放在同一目录后运行 EXE；缺少任何分卷都无法完成安装。
