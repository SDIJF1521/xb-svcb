ls

c

## v0.0.20 · DDSP-SVC 6.3 + 全局消息同步 + UVR 设备修复 + 编辑器工作流

> 本次更新完成 DDSP-SVC 6.3 从模型导入到成品混音的完整链路，统一消息状态与设备选择，补齐 TXT 歌词、多角色和时间轴模板工作流，并优化暗色主题切换体验。

> [!IMPORTANT]
> v0.0.20 继续使用分卷安装包。请同时下载 `XB-SVCB-Setup.exe` 和全部 `XB-SVCB-Setup-*.bin`，放在同一目录后再运行安装程序。

### DDSP-SVC 6.3

- 支持导入 DDSP-SVC Rectified Flow 的 `model.pt` 与 `config.yaml`，并在模型库中按 `ddsp-svc` 框架独立管理。
- 新增 DDSP-SVC Engine 与隔离 worker，创建页、多模型混唱和编辑器局部重推理均按框架路由。
- 支持变调、RMVPE / CREPE / Harvest / Parselmouth、说话人 ID 和 10 至 50 步 Rectified Flow 采样。
- 新增共振峰偏移微调，范围 `-2.00` 至 `+2.00` 半音、步进 `0.05`，映射上游 `formant_shift_key`；仅 pitch augmentation 模型有效。
- worker 按模型 YAML 读取 `f0_min` / `f0_max`，兼容高音域模型，不再强制使用上游默认范围。
- 底模链路使用 ContentVec、RMVPE 与 PC-NSF-HiFiGAN 2025.02；PC-NSF-HiFiGAN 随安装器离线提供，缺失时才联网获取，并保留兼容声码器回退。

### UVR 与设备

- 修复任务选择 GPU 但 `.venv-uvr` 安装为 CPU Torch 时，audio-separator 静默使用 CPU 的问题。
- UVR 分离与去混响严格继承用户选择的 `cuda` / `cpu`；CUDA 不可用时给出明确错误，不再无提示降级。
- 任务日志新增实际分离设备和去混响设备，便于确认 GPU 是否生效。
- 安装器为 40 系及以下 NVIDIA GPU 固定 `torch 2.5.1+cu121`，Blackwell 使用 cu128 栈，并在安装后执行 CUDA 可用性校验。
- DDSP-SVC 安装步骤同样会复核实际 CUDA Torch；校正或驱动异常时明确失败，不再误报 GPU 环境就绪。

### 消息中心

- 消息状态迁移到全局 Pinia store，作品进度、任务完成/失败和系统状态可跨页面同步。
- 各前端窗口持续刷新同一后端任务状态，并通过 BroadcastChannel / localStorage 同步已读状态，不再因顶栏组件重建而重复或丢失通知。
- 作品 store 合并轮询请求并维护任务终态，减少页面切换造成的状态断层。

### 音频编辑器

- 歌词文件选择支持 `.txt` 与 `.lrc`，兼容 UTF-8 BOM、UTF-8 和 GB18030。
- LRC 继续按工程时间或片段时间中的时间戳切分。
- 普通 TXT 可按每行或中文/英文句末标点识别歌词句子，自动生成时间轴切点。
- TXT 自动切句优先吸附片段中的静音中心；没有合适静音时按每句歌词长度比例分配时间。
- 多角色管理支持角色增删、颜色、关联模型、变调、备注和选中片段分配，角色数据随编辑工程持久化。
- 内置独唱、双人对唱、主唱和声与三角色剧情时间轴模板，模板轨道和角色映射随工程保存。

### 兼容与性能

- DDSP-SVC 当前实测可用显存下限约为 `4.5GB`；建议至少 6GB，推荐 8GB。4GB 显卡只建议尝试短音频或改用 CPU。
- DDSP-SVC 会按静音切片逐段推理，峰值显存取决于最长连续非静音片段；采样步数主要影响耗时。
- 本版本不导入或解析 SVCFusion `.sf_pkg` 工程包；DDSP 模型使用 checkpoint 与 YAML 原始文件导入。
- 优化暗色主题切换：WebView2 优先使用原生页面快照，圆形扩散改为平滑减速，动画完成后再同步原生标题栏；兼容路径修复滚动页错位并柔化过渡边缘。
- 已安装旧版可覆盖升级；模型、作品、下载素材、编辑工程、设置、消息已读状态和主题媒体继续使用原数据目录。

### 验证

- 芙芙 DDSP-SVC 6.3 模型完成 269.6 秒全流程测试：UVR 分离、去混响、DDSP 推理和自动混音全部成功。
- 非零共振峰偏移 `+0.65` 完成实际 CUDA 推理并生成有效 44.1kHz WAV。
- UVR 分别以 GPU 和 CPU 实测，worker 对应返回 `UVR_DEVICE cuda` 与 `UVR_DEVICE cpu`。
- 后端 `26` 项测试、前端类型检查、`2` 项前端单测与正式构建通过。

### 安装与升级

- 应用本体、Python 项目、前端包、两份锁文件和 Inno Setup 版本均同步为 **v0.0.20**。
- 安装器会把 `README.md` 与 `release_notes_v020.md` 一起释放到安装目录。
- 首次使用 DDSP-SVC 或修复 UVR GPU 环境，可在安装目录执行 `setup_env.bat`，或运行 `python install\install.py --only ddsp uvr --gpu`。
- 下载 `XB-SVCB-Setup.exe` 和同一版本的全部 `XB-SVCB-Setup-*.bin`，放在同一目录后运行 EXE。
