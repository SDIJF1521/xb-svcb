## v0.0.22 · AMD DirectML 全链路适配

> 本次更新为 Windows AMD Radeon 显卡补齐完整推理链路。四个歌声模型框架、人声分离、F0 处理、安装器和设备 UI 现在使用同一套环境能力检测与设备选择协议。

> [!IMPORTANT]
> v0.0.22 继续使用分卷安装包。请同时下载 `XB-SVCB-Setup.exe` 和全部 `XB-SVCB-Setup-*.bin`，放在同一目录后再运行安装程序。

### AMD 推理支持

- So-VITS-SVC、RVC、SeedVC 与 DDSP-SVC 新增 Windows DirectML 推理路径。
- 推理设备值统一为 `auto`、`cuda`、`rocm`、`directml` 与 `cpu`；`amd`、`dml` 等旧别名会规范化到对应后端。
- DirectML 环境固定使用 `torch-directml 0.2.5.dev240914`、PyTorch `2.4.1` 与 Torchaudio `2.4.1`，防止后续依赖覆盖已注册的 DirectML 后端。
- 显式选择 CUDA、ROCm 或 DirectML 时会校验实际设备；环境缺失、驱动不可用或后端不匹配会明确失败，不再静默回退 CPU。
- 多显卡机器优先选择 AMD Radeon 适配器，也可通过 `XB_DIRECTML_DEVICE` 指定 DirectML 设备索引。

### UVR AMD 加速

- UVR 纳入 DirectML 支持，随包的 `5_HP-Karaoke-UVR.pth` 与 `UVR-DeEcho-DeReverb.pth` 可通过 `torch-directml` 在 AMD GPU 上运行。
- MDX `.onnx` 模型通过 `onnxruntime-directml` 的 `DmlExecutionProvider` 加速；worker 会校验 provider，避免界面显示 DirectML、实际却使用 CPU。
- `auto` 在 AMD UVR 环境自动选择 DirectML；显式选择 DirectML 时，启动、模型加载或分离失败都会原样上报。
- 安装器固定使用 `audio-separator[dml] 0.44.2`，并在 CUDA、DirectML、CPU 栈之间切换时清理冲突的 ONNX Runtime 发行包。

### DirectML 兼容处理

- DirectML 不支持的 ComplexFloat STFT/ISTFT 中间运算保留在 CPU，实数频谱和模型张量继续在 AMD GPU 上运行。
- UVR VR 5.1 去混响网络中 DirectML 不支持的双向 LSTM 使用 CPU 混合执行，前后卷积与全连接层继续保留在 GPU。
- DDSP-SVC 的 CombSub 复数合成阶段使用 CPU 兼容路径，神经网络控制与模型推理保留在 DirectML。
- DirectML 环境强制使用 FP32，并兼容旧模型代码中无条件调用 `half()` 或 CUDA autocast 的路径。
- F0、重采样和音频张量迁移按实际后端处理，避免硬编码 `cuda` 导致 AMD 环境启动失败。

### 自适应设备 UI

- 系统状态会分别探测 UVR、So-VITS-SVC、RVC、SeedVC 与 DDSP-SVC 隔离环境，并返回各环境实际可用设备、显卡名称和首选后端。
- 创建翻唱页面只显示 UVR 与当前歌声模型框架共同支持的设备；CUDA 环境显示 NVIDIA CUDA，AMD 环境显示 AMD DirectML。
- 切换模型框架或运行环境后，已经失效的设备偏好会自动恢复为 `auto`，避免提交当前环境无法执行的选项。
- 编辑器局部重推理继续按所选歌声框架过滤设备；独立 UVR 分离使用当前 UVR 环境的自动首选设备。

### 安装与升级

- Windows 安装器会检测 AMD Radeon；未检测到兼容 NVIDIA 显卡时自动选择 DirectML，也可使用 `--directml` 强制搭建 AMD 环境。
- 已安装旧版本可运行 `python install\install.py --directml` 重建全部 AMD 推理环境，或使用 `python install\install.py --directml --only uvr` 只重建 UVR。
- 应用本体、Python 项目、前端包、两份锁文件和 Inno Setup 版本均已同步为 **v0.0.22**。
- 安装器会把 `README.md` 与 `release_notes_v022.md` 一起释放到安装目录。

### 验证

- 后端设备与 UVR 定向测试通过，覆盖 AMD 适配器优先、显式 DirectML 禁止静默回退和实际设备回传。
- 前端设备自适应单测、TypeScript 类型检查与生产构建通过。
- DirectML 真实张量、混合 STFT/ISTFT、Torchaudio 重采样与 DDSP CombSub 兼容路径完成运行测试。
- UVR 使用修改后的 worker 完成两次真实短音频推理：`5_HP-Karaoke-UVR.pth` 生成有效人声与伴奏，`UVR-DeEcho-DeReverb.pth` 生成无混响与混响残留轨；两次均回报 `UVR_DEVICE directml`。
- 当前开发机没有物理 AMD 显卡；DirectML 路径已在可用 DirectML 适配器上验证，仍建议在目标 Radeon 机器上完成长音频与四框架整曲验收。
