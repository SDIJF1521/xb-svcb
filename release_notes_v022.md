## v0.0.22 · AMD DirectML 适配 + 稳定性修复 + 路径迁移

> 本次更新为 Windows AMD Radeon 补齐 DirectML 推理链路，并把 NVIDIA CUDA、AMD DirectML 与 CPU 的设备选择、错误上报和环境探测统一到同一套协议。重点修复 AMD 长音频推理、RVC / SeedVC F0、DDSP 数值失真、数据目录迁移和 NVIDIA 回归问题。

> [!IMPORTANT]
> v0.0.22 继续使用分卷安装包。请同时下载 `XB-SVCB-Setup.exe` 和全部 `XB-SVCB-Setup-*.bin`，放在同一目录后再运行安装程序。

### 🎯 模型选择建议

- NVIDIA CUDA：SeedVC 推荐优先使用。
- AMD DirectML：SeedVC 仅保留为兼容测试路径，优先选 So-VITS-SVC 或 RVC。
- CPU / 其他显卡：SeedVC 不建议普通用户使用。

### 🎛️ AMD 推理支持

- So-VITS-SVC、RVC、SeedVC 与 DDSP-SVC 新增 Windows DirectML 推理路径；SeedVC 在非 NVIDIA 环境仅保留兼容路径。
- NVIDIA CUDA/CPU 的 `auto` 设备传递恢复为 v0.0.21 的上游原生 `device=None` 行为；所有 FP32、FFT、F0 和 checkpoint 兼容补丁只在实际后端为 DirectML 时安装。
- 推理设备值统一为 `auto`、`cuda`、`rocm`、`directml` 与 `cpu`；`amd`、`dml` 等旧别名会规范化到对应后端。
- DirectML 环境固定使用 `torch-directml 0.2.5.dev240914`、PyTorch `2.4.1` 与 Torchaudio `2.4.1`，防止后续依赖覆盖已注册的 DirectML 后端。
- RVC 与 So-VITS-SVC 的 DirectML 隔离环境固定使用 Python 3.10，修复 Python 3.9 导入 `torch-directml` 时出现 `'staticmethod' object is not callable`、随后被误报为驱动不可用的问题；CUDA/CPU 旧栈继续使用原有 Python 版本。
- So-VITS-SVC 的 Python 3.10 DirectML 依赖会把旧 `numpy 1.19.5`、`pyworld 0.3.0`、`scipy 1.7.3` 覆盖为有 cp310 轮子的兼容版本，避免安装阶段错误进入 NumPy 源码编译。
- RVC/SeedVC 上游的 ONNX DirectML RMVPE 在部分 Radeon 机器上会在打印节点分配警告后原生终止进程，无法由 Python 捕获；现在仅将 F0/RMVPE 固定到 CPU/PyTorch 稳定路径，HuBERT、RVC/SeedVC 主模型与声码器继续使用 AMD DirectML。
- RVC DirectML 在 5 分钟左右长音频、较高检索率下容易同时触发 `DML allocator out of memory` 与 `OpenBLAS malloc failed`；AMD 路径现在启用更短的 RVC 切片窗口并限制 BLAS/OMP 线程，降低长曲和 index 检索的瞬时显存/内存峰值。CUDA/CPU/ROCm 不进入该低显存配置。
- 修复 SeedVC 的 Mel `reflect pad/STFT` 与 CAMPPlus Kaldi FBank 在部分 DirectML 驱动上抛出空 `RuntimeError` 或因 `ComplexFloat` 原生终止的问题；两个确定性的音频特征阶段现在完整运行在 CPU，生成的实数特征立即返回 AMD GPU，Whisper、长度调节器、扩散模型和 BigVGAN 仍使用 DirectML。Whisper 分块特征提取同时显式传入 16 kHz 采样率，不再重复输出缺失 `sampling_rate` 的警告。
- SeedVC 的 RMVPE 已在 CPU 生成 F0，但上游会立刻把曲线搬回 DirectML执行 `log/median/exp`，部分 Radeon 驱动因此继续抛出空 `RuntimeError`；F0 统计、音高调整、512 档量化和小型 F0 Embedding 查表现在完整留在 CPU，查表得到的浮点特征再送回 AMD GPU。
- SeedVC 不再在 DirectML 异常后隐式用完整 CPU 重跑整曲，避免长音频数十分钟无进度；需要 CPU 时必须由用户明确选择，AMD/NVIDIA 的设备错误会立即保留 traceback 返回。
- 修复 So-VITS-SVC/RMVPE 与浅扩散模型通过 `torch.load(map_location=privateuseone)` 反序列化时，`torch-directml` 把 `torch.device` 当作适配器整数比较并抛出 `'>=' not supported` 的问题；DirectML checkpoint 现在先在 CPU 加载状态，再由上游 `.to(device)` 迁移到 AMD GPU。
- 修复 So-VITS-SVC 与 SeedVC 把 F0 粗化索引同 `f0_bin=256/512` 比较时，DirectML 尝试将越界常量转为 `uint8` 并报 `value cannot be converted to type uint8_t without overflow` 的问题；AMD 路径现在先把浮点索引安全裁剪到合法范围再转为嵌入索引，音高映射与正常输入下的原算法保持一致。DDSP-SVC 使用连续浮点 F0，不经过该离散索引路径。
- 显式选择 CUDA、ROCm 或 DirectML 时会校验实际设备；环境缺失、驱动不可用或后端不匹配会明确失败，不再静默回退 CPU。
- 多显卡机器优先选择 AMD Radeon 适配器，也可通过 `XB_DIRECTML_DEVICE` 指定 DirectML 设备索引。

### 🧪 UVR AMD 加速

- UVR 纳入 DirectML 支持，随包的 `5_HP-Karaoke-UVR.pth` 与 `UVR-DeEcho-DeReverb.pth` 可通过 `torch-directml` 在 AMD GPU 上运行。
- MDX `.onnx` 模型通过 `onnxruntime-directml` 的 `DmlExecutionProvider` 加速；worker 会校验 provider，避免界面显示 DirectML、实际却使用 CPU。
- `auto` 在 AMD UVR 环境自动选择 DirectML；显式选择 DirectML 时，启动、模型加载或分离失败都会原样上报。
- 修复 UVR 安装校验使用 `info_only=True` 导致 `audio-separator` 跳过设备初始化、`torch_device` 恒为 `None` 并误报 DirectML 失败；校验现在会正常初始化临时 Separator 并同时核对 Torch 与 ONNX DirectML provider。
- 安装器固定使用 `audio-separator[dml] 0.44.2`，并在 CUDA、DirectML、CPU 栈之间切换时清理冲突的 ONNX Runtime 发行包。

### 🛠️ DirectML 兼容处理

- DirectML 不支持的 ComplexFloat STFT/ISTFT 中间运算保留在 CPU，实数频谱和模型张量继续在 AMD GPU 上运行。
- 修复 DirectML 不允许单次 padding 同时包含正值与负值、导致 So-VITS-SVC HiFiGAN 和 DDSP-SVC NSF-HiFiGAN 报 `must be all positive or all negative` 的问题；混合 padding 现在等价拆分为 GPU 切片裁剪和纯正值 padding。
- UVR VR 5.1 去混响网络中 DirectML 不支持的双向 LSTM 使用 CPU 混合执行，前后卷积与全连接层继续保留在 GPU。
- DDSP-SVC 的 CombSub 复数合成阶段使用 CPU 兼容路径，神经网络控制与模型推理保留在 DirectML。
- DirectML 环境强制使用 FP32，并兼容旧模型代码中无条件调用 `half()` 或 CUDA autocast 的路径。
- So-VITS-SVC 浅扩散 NSF-HiFiGAN 中显式调用 `.double()` 的相位累加张量在 DirectML 上保持 FP32，修复扩散采样完成后在 `cumsum/sin` 处仅抛出空 `RuntimeError` 的问题；CPU/CUDA 张量的 FP64 转换保持原样。
- DirectML Bool 张量没有最近邻插值内核；So-VITS-SVC/DDSP-SVC 声码器的清浊音掩码在进入 `interpolate(mode='nearest')` 时现在按等值的 FP32 0/1 信号计算，修复 `compute_indices_weights_nearest not implemented for Bool`，其他张量类型与后端保持原样。
- F0、重采样和音频张量迁移按实际后端处理，避免硬编码 `cuda` 导致 AMD 环境启动失败。
- RVC 子进程日志增加退出码，原生运行时崩溃不再被最后几行 ONNX Runtime 性能警告掩盖。

### 🧭 自适应设备 UI

- 系统状态会分别探测 UVR、So-VITS-SVC、RVC、SeedVC 与 DDSP-SVC 隔离环境，并返回各环境实际可用设备、显卡名称和首选后端。
- 创建翻唱页面只显示 UVR 与当前歌声模型框架共同支持的设备；CUDA 环境显示 NVIDIA CUDA，AMD 环境显示 AMD DirectML。
- 切换模型框架或运行环境后，已经失效的设备偏好会自动恢复为 `auto`，避免提交当前环境无法执行的选项。
- 编辑器局部重推理继续按所选歌声框架过滤设备；独立 UVR 分离使用当前 UVR 环境的自动首选设备。

### 📦 安装与升级

- 更正用户数据目录名称：新安装统一使用 `.xb_svcb`；已有默认 `.sb-svcb` 会在启动时安全同盘重命名，同时更新 `models.json`、`works.json`、编辑工程中的绝对路径和数据指针，失败时自动回滚继续使用旧目录，模型、作品与设置不会丢失。
- 修复数据目录改名后旧绝对模型路径触发引擎“降级演示音”，让 NVIDIA 输出固定 15 秒单音杂音的问题；真实模型任务缺少环境、权重、配置或输入时现在明确失败，四种歌声引擎都不再用正弦波冒充成功推理。
- Windows 安装器会检测 AMD Radeon；未检测到兼容 NVIDIA 显卡时自动选择 DirectML，也可使用 `--directml` 强制搭建 AMD 环境。
- 已安装 v0.0.22 早期 AMD 环境的测试机只需更新应用本体中的公共设备兼容层及 SVC/F0/RVC/SeedVC worker；这些混合执行与 checkpoint 加载修复不要求重建 `.venv-svc`、`.venv-rvc` 或 `.venv-seedvc`。
- 修复 RTX 4060 等 NVIDIA 显卡在图形安装器中被误报为“CPU 或未检测到兼容 GPU”的问题；`nvidia-smi` 不可见或查询失败时会通过 `Win32_VideoController` 名称继续识别 NVIDIA。
- 修复图形安装器与后续 Python 安装阶段重复检测造成的栈不一致；自动模式现在明确传递最终 CPU、cu121、cu128 或 DirectML 结果，CUDA Toolkit 目录按 NVIDIA 栈恢复为 `v12.1` / `v12.8` 默认路径。
- CUDA Toolkit 目录从通用依赖页拆成 NVIDIA 专用页，仅在 cu121 / cu128 模式出现；CPU 与 AMD DirectML 用户直接跳过，不再被空 CUDA 目录阻止进入下一步。
- 修复 C++ Build Tools 默认路径包含 `Program Files (x86)` 时被批处理括号误解析、导致环境搭建中断的问题。
- 修复安装器在 94% 写入用户环境变量时因 `reg.exe` 异常占用 CPU 而无限等待的问题；PATH 和镜像/CUDA 变量改由 Python `winreg` 结构化写入，兼容长 PATH、`%变量%` 与括号，并在失败时返回明确错误。
- 修复 SeedVC 与 DDSP-SVC 的 DirectML 安装分支在 Torch 已安装后又执行空 `uv pip install`、导致两个环境必然失败的问题。
- DDSP-SVC 上游未限制 Transformers 版本，近期 5.x 会在 HuBERT 导入阶段要求 Torch 新版 `DTensor`，与 DirectML 固定的 Torch 2.4.1 不兼容；安装器现固定 `transformers==4.46.3`，并在安装结束前真实导入 DDSP 使用的 HuBERT 类，已有环境可原地运行 DDSP 修复完成降级。
- DDSP-SVC 的 RMVPE 与部分底模加载器未指定 `map_location`，遇到由 CUDA 环境保存的 checkpoint 时会在 AMD 机器上报 `Attempting to deserialize object on a CUDA device`；DirectML worker 现在统一先在 CPU 反序列化 DDSP、RMVPE、ContentVec 与声码器状态，再由各上游加载器迁移到 AMD GPU。
- DDSP-SVC 自带 RMVPE 的双向 GRU 在 DirectML 上会触发不完整的 `_thnn_fused_gru_cell` CPU 单算子回退；AMD 环境现在仅让 RMVPE F0 网络完整运行在 CPU，输出 NumPy F0 后再由上游送回 DirectML，DDSP 主模型、Rectified Flow 与声码器继续使用 AMD GPU。
- DDSP-SVC Rectified Flow 的 `SinusoidalPosEmb` 在部分 DirectML 驱动上会于第一个采样步的 `sin/cos` 组合抛出空 `RuntimeError`；每步仅数百个值的时间编码现在在 CPU 生成后立即送回 DirectML，Flow 的 Linear/卷积和完整采样循环仍在 AMD GPU。
- 修复 DDSP-SVC 与 SeedVC 错误共用 `10–50` 步质量映射、导致 30% 设置只运行 22 步而明显低于 DDSP 6.3 官方 50 步默认值的问题；DDSP 前端现使用 50–100 步范围，worker 同时读取模型 `infer.infer_step` 并拒绝低于模型作者的推荐步数，旧客户端传入低值也会自动提升。
- 实机确认 DDSP-SVC 的完整 DirectML 图可能不抛异常却产生极小声、静音或电流杂音，这属于无法由返回码、峰值或 RMS 可靠识别的静默数值失真；AMD 环境下 DDSP 现改用完整 CPU 稳定推理，并从 DDSP 设备列表移除 DirectML。UVR、So-VITS-SVC、RVC、SeedVC 的 AMD 加速不受影响。中间人声仍使用浮点 WAV，写出前保留 NaN/Inf、近静音、峰值和 RMS 质检。
- 安装完成前会真实导入 UVR、So-VITS-SVC、RVC、SeedVC、DDSP-SVC 五个环境的 Torch，并核对 CUDA / DirectML；半安装环境会明确失败，不再静默进入降级模式。
- 启动时的隔离环境设备探测加入 `CREATE_NO_WINDOW`，消除连续闪出的黑色 CMD 窗口。
- 五个隔离环境改为一次并行探测，结果按环境文件签名缓存 24 小时；软件重新启动时可直接恢复设备状态，环境更新后缓存会自动失效，不再每次串行导入五套 Torch。
- 修复首页“集成工具”卡片被长显卡名称挤成竖排、状态文字溢出的问题；版本、设备和异常状态现在会在桌面及移动布局中稳定换行或省略显示。
- 已安装旧版本可运行 `python install\install.py --directml` 重建全部 AMD 推理环境，或使用 `python install\install.py --directml --only uvr` 只重建 UVR。
- 应用本体、Windows EXE 版本资源、Python 项目、前端包、两份锁文件和 Inno Setup 版本均已同步为 **v0.0.22**。
- 安装器会把 `README.md` 与 `release_notes_v022.md` 一起释放到安装目录。

### ✅ 验证

- 后端设备与 UVR 定向测试通过，覆盖 AMD 适配器优先、显式 DirectML 禁止静默回退和实际设备回传。
- 启动探测测试覆盖 Windows 隐藏子进程、跨进程缓存复用和环境签名失效；五环境首次并行探测约 3.5 秒，后续独立进程读取缓存约 0.02 秒。
- 前端设备自适应单测、TypeScript 类型检查与生产构建通过。
- DirectML 真实张量、混合 STFT/ISTFT、Torchaudio 重采样与 DDSP CombSub 兼容路径完成运行测试。
- UVR 使用修改后的 worker 完成两次真实短音频推理：`5_HP-Karaoke-UVR.pth` 生成有效人声与伴奏，`UVR-DeEcho-DeReverb.pth` 生成无混响与混响残留轨；两次均回报 `UVR_DEVICE directml`。
- 当前开发机没有物理 AMD 显卡；DirectML 路径已在可用 DirectML 适配器上验证，仍建议在目标 Radeon 机器上完成长音频与四框架整曲验收。
