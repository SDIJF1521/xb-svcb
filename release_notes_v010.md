## v0.0.10 · 50 系显卡（Blackwell）适配 + 模型站搜索修复 + 时间轴稳健性

### 新增
- 🟢 **RTX 50 系显卡（Blackwell, sm_120）适配**：安装器自动识别 50 系并切换到 **cu128 + PyTorch 2.7** 专用栈，彻底解决“仅升级 CUDA/torch 会哑音、效果不如 40 系/CPU”的问题。
  - **自动探测**：按 `nvidia-smi` 算力（compute_cap ≥ 12.0）判定，名称回退匹配 RTX 50xx。
  - **SVC / RVC 专用环境**：50 系下改用 **Python 3.10 + cu128 torch 2.7.1**；SVC 推理把 `torchaudio` 音频 I/O 改走 `soundfile`（规避 torch 2.7 的 torchcodec 哑音），`numpy` / `pyworld` 等依赖切到 3.10 兼容版。
  - **fairseq 兼容**：50 系下重装 fairseq 并对 `checkpoint_utils` 打 `weights_only=False` 补丁，修复新 torch 加载 hubert / 字典 / 主模型时的 “Weights only load failed”。
  - **开关**：可用 `--cu128` 强制启用、`--no-cu128` 强制回退老栈；40 系及以下完全沿用原 cu121/cu118 已验证组合，零回归。

### 修复
- 🔎 **模型站只能搜到自己上传的模型**：发现他人模型这一路原本按内部标记 `xb-svcb-voice-model` 全站搜索，但该标记仅存在于 README / 清单中、不会被 ModelScope 的名称/描述索引命中，导致只剩“自己命名空间”有结果。改为按仓库名前缀 `xb-svcb` 搜索（每个上传仓库名都带该前缀），即可发现所有人公开分享的模型；真伪仍由前缀过滤 + 清单 magic 校验把关。
- 🎚️ **时间轴 UI 稳健性**：迷你时间轴总宽度固定、不再被拉伸的片段等比例放大；色块 left/width 百分比钳制在轴内，长歌词等内容不再撑破布局（`grid` 列补 `min-width:0`）。编辑统一在弹窗中进行，缩略预览保留。

### 说明
- 50 系适配建议在实机验证：装完后跑一遍分离 / SVC / RVC，确认无 `sm_120` 警告、无哑音、RVC 不报 weights_only 错误。fairseq 在 Python 3.10 下如需现场编译，请确保已装 **C++ Build Tools**。
- 需安装 **CUDA 12.8 级别的新版 NVIDIA 驱动**（50 系本就要求新驱动）。

### 安装
- 下载并运行 `XB-SVCB-Setup.exe` 一键安装（约 2 GB，含分离 / so-vits-svc / RVC / 模型站组件）。
- 40 系及以下 GPU 加速需 CUDA 12.1 运行库：https://developer.nvidia.com/cuda-12-1-0-download-archive
- 50 系（Blackwell）需 CUDA 12.8 级新版驱动；安装器会自动改装 cu128 + torch 2.7 栈。
