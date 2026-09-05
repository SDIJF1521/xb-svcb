## v0.0.31 · 共享运行时、首次引导与高音/美声稳定性

> v0.0.31 收拢了从 `540ca2e38fafb1599ef773748a4970e00523f7ad` 起到当前 HEAD 的全部变动：CUDA 发布栈改为硬件专用包与两层共享运行时，同时继续修复高音保护误触发、So-VITS-SVC 推理异常、RVC DirectML F0 推理、模型输出高频噪声和 AI 歌声增强过度处理的问题。

### 📦 安装器与运行时布局

- 发布包拆分为 CPU、DirectML、CUDA126、CUDA128 四套硬件专用安装包；每套只携带目标硬件栈需要的离线 wheels。
- NVIDIA 最低 CUDA wheel 栈统一为 cu126，不再新建或分发 cu121 CUDA 环境；RTX 50 系 Blackwell 使用 cu128，40 系及以下使用 cu126。
- CUDA126/CUDA128 默认采用两层共享布局：UVR、SeedVC、DDSP-SVC 使用 `runtimes/core-*`，So-VITS-SVC、RVC、Vocal/DeepFilterNet3 使用 `runtimes/svc-*`。
- CPU 与 DirectML 继续使用 `.venv-*` 隔离兼容布局；CPU 的 SVC/RVC 环境也统一为 CPython 3.10，不再要求额外准备 Python 3.9。
- 安装器新增 Python 3.10 `python.exe` 手动选择页，只接受可运行的 64 位 CPython 3.10.x，并会跳过 WindowsApps 的 Microsoft Store 占位程序。
- `installer_env.cmd` 会记录 `XB_RUNTIME_LAYOUT`、`XB_GPU_STACK` 和锁定的 Python 路径；后续运行 `setup_env.bat` 修复 CUDA 包时会继续走共享入口。
- 安装完成校验改为按 `runtime.json` 解析真实解释器路由，再验证 Python、Torch、CUDA/DirectML 和关键 worker；环境全部通过后自动清理安装目录中的 `assets/wheels`。

### 🧱 Wheelhouse、底模与构建

- 新增 `install/install_shared.py`、`runtime_manifest.py`、`audit_runtime.py`、`core_recipe.py`、`validate_core_install.py` 等运行时脚本，明确共享环境的安装、探测、校验和原子激活边界。
- 新增 `installer/stage_wheelhouse.py` 与 `installer/build-all-packages.ps1`，支持顺序构建四套安装包，并拒绝使用陈旧的 py39 CPU wheelhouse 生成新包。
- 构建流程会复用固定工具链，检测并重建陈旧 wheelhouse 环境，避免历史约束文件或单栈选择被错误复用。
- 新增 `assets/models/model-manifest.json` 与 `install/model_manifest.py`，记录随包底模、UVR、SeedVC、DDSP-SVC 和 DeepFilterNet 权重的来源、运行时位置、大小与 SHA-256 校验。
- 底模部署优先使用硬链接，跨盘或失败时回退复制；已有同尺寸权重只有哈希一致才复用，避免损坏文件被误判可用。

### 🎼 高音保护与推理质量

- 高音保护收敛为用户可理解的开关：关闭后不会再执行自动高音重试、F0 上限扩展或自动阈值修正。
- 新增“全参数手动调整”开关。关闭时只发送常用推理参数，目标说话人、F0 过滤阈值、手动高音起点等高级字段恢复安全默认值。
- 高音阈值优先读取当前模型的 `inference_profile`、`f0_max`、`f0_max_hz` 或 `max_f0`，不同模型不再共用一个固定高音边界。
- 高音保护从“检测到高 F0 就整体重推”改为先跑基线推理，再只对确认坍塌或错误音高的高音区域执行受限降调重试，并把通过质量门的区域合回基线渲染。
- 重试次数可通过 `high_pitch_guard_rounds` 控制，取值范围为 0 到 8；失败候选会因新增窄带高频啸叫、音高仍坍塌或未改善原问题而被拒绝。
- 修复高频修复算法泄漏和高音保护误爆高音区的问题，降低普通清辅音、气声、短暂噪声被误当作高音处理的概率。
- So-VITS-SVC、RVC、实时翻唱和编辑器局部重推理复用同一套高音掉音检测、分区重试和候选质量判断，减少不同入口效果不一致。
- RVC DirectML 会先在 CPU 反序列化 torchcrepe checkpoint，再交回 DirectML 执行，避免 AMD 显卡路径在 F0 推理前因 `privateuseone` 设备映射失败。

### 🎧 AI 歌声增强与高频噪声

- AI 歌声增强各阶段新增质量门，会拒绝空文件、静音段抬噪、响度塌陷、削波、过度高频或不自然的候选结果，失败时回退上一阶段输出而不中断任务。
- 新增模型高频残留识别，对短促尖刺和持续噪声型空气频段分别处理，避免 DeepFilter、参考频谱匹配或细节回填把模型自带哨声放大。
- 参考人声现在只作为频谱、包络和高音主体的引导，不再把未对齐的高频波形直接混入模型输出，降低相位打架、电音感和啸叫。
- 高音保护已触发时，美声链路自动采用更保守的高频染色、压缩和激励强度，并补偿高音主体能量。
- Praat PSOLA 自然修音增加结果验收，检测到疑似风扇声、空渲染、采样率变化或能量异常时自动丢弃候选。
- 翻唱增强可先对原始参考歌曲分离/去混响，再用于自然修音、节奏对齐和音色参考，减少伴奏串音参与增强判断。

### 🧭 前端工作流

- 新增首次使用交互引导，覆盖首页、翻唱工作台、前期处理、多模型时间轴、AI 歌声增强、实时翻唱、资源获取、模型站、作品库、播放器、编辑器、API 和插件入口。
- 首页和创建页支持拖拽音频。桌面端可把文件导入临时区并带到翻唱工作台，浏览器开发模式保留文件选择回退；单个拖入文件限制为 50MB。
- 创建页新增手动参数开关、高音保护轮次、F0 过滤阈值和模型说话人字段，并保证预设只恢复数值，不会偷偷开启高级参数。
- 多模型模式下每个模型都可独立保存高音保护、轮次、F0、说话人、共振峰、RVC、SeedVC 和 DDSP-SVC 参数。
- 生成完成后的内置播放器增加进度显示和拖动定位，方便直接检查副歌、高音段和修复结果。
- 模型管理页支持直接重命名模型显示名称，不修改模型 ID、权重、配置或来源记录。

### 🔌 API 与桌面桥接

- FastAPI 推理参数新增 `high_pitch_guard_rounds`、`f0_filter_threshold` 和 `manual_params_enabled`；多模型请求会把顶层高音保护配置正确传播到未单独覆盖的模型项。
- 新增 `PATCH /api/v1/models/{model_id}`，用于修改模型显示名称。
- 桌面 Bridge 新增 `rename_model` 和 `import_audio_data`，前者服务于模型重命名，后者用于保存拖入/浏览器读取的音频数据。
- API 文档同步补充 PyMSS、人声处理、局部重推理高音保护、模型重命名和编辑器时间拉伸说明。

### 📝 文档与测试覆盖

- 新增 [共享运行时与兼容布局](../runtime-consolidation.md)，集中说明 CUDA 两层共享环境、CPU/DirectML 兼容布局、`runtime.json` 路由和修复边界。
- 新增 [测试分组与验收边界](../testing.md)，区分 runtime、installer、packaging、packaging_integration 和真实模型推理验收。
- `README.md`、源码安装文档、开发发布文档、架构说明、安装器说明和模型资产说明已同步到 0.0.31 的运行时和发布方式。
- 新增或更新安装器、wheelhouse、runtime manifest、模型资产、AI 增强、高音保护、实时翻唱、HTTP API 和 PyMSS 状态相关回归测试。

### ⚠️ 升级说明

- 用户的模型、作品、编辑工程、主题媒体、API 设置和插件数据继续保留，升级不会清空用户数据。
- NVIDIA 用户请按硬件重新选择 CUDA126 或 CUDA128 安装包；旧 cu121 CUDA 安装需要通过新安装器或 `setup_env.bat` 迁移到当前共享布局。
- 若升级后环境状态异常，请从安装目录运行 `setup_env.bat`；CUDA 包会根据 `installer_env.cmd` 继续修复共享运行时，CPU/DirectML 包继续修复隔离环境。
- 从旧 py39 CPU wheelhouse 或本地构建缓存升级发布包时，请重新生成 wheelhouse，避免把缺少 cp310 wheels 的缓存带入 0.0.31 安装器。
