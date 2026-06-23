## v0.0.7 · RVC 兼容 + 多框架推理抽象

### 新增
- 🎛️ **多框架推理（So-VITS-SVC / RVC）**：推理引擎按模型「框架」可插拔，内置 **RVC**（基于 `rvc-python`），自动识别 `.index` 检索特征。
- 导入 / 创建页按框架切换专属参数（`protect` / `filter_radius` / 版本 `v1·v2`）。
- 🧬 **混合翻唱可跨框架**：同一首歌可混用 RVC 与 so-vits-svc 模型，整轨逐模型推理后无缝拼接。
- RVC 运行在独立子环境 `.venv-rvc`（Python 3.9 / cu118，首启自动下载 hubert / rmvpe 底模）。
- 模型站上传 / 下载透传框架标签，清单 `files` 支持 RVC `.index`。

### 优化
- 推理页步骤名「SVC 推理」统一改为「模型推理」；模型选择支持按框架筛选；系统状态页新增 **RVC 推理引擎** 项。

### 安装
- 下载并运行 `XB-SVCB-Setup.exe` 一键安装（约 2 GB，含分离 / so-vits-svc / RVC / 模型站组件）。
- GPU 加速需 NVIDIA 显卡 + CUDA 12.1 运行库：https://developer.nvidia.com/cuda-12-1-0-download-archive
