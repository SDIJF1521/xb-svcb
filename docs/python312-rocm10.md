# Python 3.12 与 AMD ROCm 10

应用、插件和全部推理子环境统一使用 **64 位 CPython 3.12.x**。安装器发现旧解释器时按原有流程重建对应虚拟环境；模型和项目数据无需转换。离线发布必须重新准备 `py312` wheelhouse，不能直接改名或复制 `cp310-cp310` wheel。带 `abi3` 标记的 wheel 按其真实兼容标签处理。

## AMD 安装

```powershell
./install.ps1 --rocm10
# 已安装程序修复环境
./setup_env.bat --rocm10
```

AMD 自动检测和图形安装包使用 `rocm10` 栈；`--rocm` 是同一选项的别名。
运行时 API 设备值仍为 `rocm`。ROCm PyTorch 使用 `torch.cuda` 接口，设备名为 `cuda:0`，实际后端依据 `torch.version.hip` 判断。

默认使用 AMD 官方源 `https://stable.repo.amd.com/rocm/whl-next/`，对应命令为：

```powershell
python -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-all]==2.13.0+rocm10.0.0" "torchvision[device-all]==0.28.0+rocm10.0.0" "torchaudio==2.11.0.2+rocm10.0.0"
python -m pip install pymss==2.0.18
```

已验证这三个版本均有 Windows CPython 3.12 wheel，并完成它们与 PyMSS 2.0.18 的依赖解析。`device-all` 会安装 AMD 提供的各显卡架构包，离线打包也必须包含这些传递依赖。安装器先安装官方 Torch 套件，再安装 PyMSS，后续安装始终约束这三个版本，最后检查依赖一致性、PyMSS 导入和 HIP 运算。

可选择提供 Python 3.12 / 当前操作系统 / ROCm 10 wheel 的镜像，并按镜像版本固定 Torch 配套包：

```powershell
$env:XB_TORCH_ROCM_INDEX = 'https://your-mirror.example/rocm10/simple'
$env:XB_ROCM_TORCH_VERSION = '2.13.0+rocm10.0.0'
$env:XB_ROCM_TORCHAUDIO_VERSION = '2.11.0.2+rocm10.0.0'
$env:XB_ROCM_TORCHVISION_VERSION = '<对应 torchvision 版本>'
./install.ps1 --rocm10
```

Torch、torchvision、torchaudio 使用各自的官方版本号，不能假设它们相同。安装后必须通过 ROCm 主版本 10、HIP 存在性、GPU 可用性和实际张量运算校验；CPU 或 NVIDIA CUDA Torch 不会被当作 AMD 安装成功。不支持的显卡或驱动需要显式选择 `--cpu`。Windows 原生支持从 ROCm 7.2.1 / Adrenalin 26.2.2 / Python 3.12 开始，但 ROCm 10 的实际显卡和驱动要求应以 AMD 当前发布说明为准，旧版本的最低驱动不代表 ROCm 10 已通过实机验证。

离线安装包在暂存阶段还会读取 Torch wheel 内的 `torch/version.py`，校验 ROCm 10 与 HIP 标记，拒绝混入 DirectML 的依赖目录。已下载验证官方 Windows cp312 wheel：`torch.version.rocm == '10.0.0'`，而 `torch.version.hip == '7.15.26333'`；两者版本号不同，不能用 HIP 主版本代替 ROCm 主版本。源与版本不匹配时会停止打包，需要重新准备对应的 wheelhouse。

PyMSS 在独立 `.venv-pymss` 环境安装同一 ROCm 栈，支持 AMD 加速。`auto` 会识别 HIP 并回报 `rocm`，显式 `rocm` 不可用时直接报错。PyMSS 不支持 DirectML。旧 DirectML worker 兼容代码仅用于已有环境，新的 AMD 安装和发布入口均选择 ROCm 10。

## DDSP 与 SeedVC 模型

DDSP 按 `model.type` 分流至官方加载器：Sins、CombSub、CombSubFast、CombSubSuperFast、Diffusion、DiffusionNew、DiffusionFast，以及 RectifiedFlow 6.1 / 6.2 / 6.3。旧版加载器固定到官方源码提交，使用 `.venv-ddsp-legacy` 的 Python 3.12 / fairseq-fixed 环境；它与 6.3 使用相同硬件栈。浅扩散可导入配套 DDSP 权重和配置。RectifiedFlow 根据辅助网络字段与编码器权重格式判断版本；定制配置可显式设置 `xb_ddsp_version: '6.1'`、`'6.2'` 或 `'6.3'`。

SeedVC 从配置读取 F0 开关，覆盖 44.1 kHz F0、22.05 kHz 非 F0、XLSR tiny 和上游支持的自定义编码器/声码器组合；V2 根据 `VoiceConversionWrapper` 配置选择官方 V2 推理，主权重为 CFM，可附带 AR 权重，未提供时遵循上游下载行为。非 F0 模型及 V2 不支持半音变调，变调参数必须为 0。

导入时复制配置明确引用的本地编码器、声码器和 Hugging Face 模型目录，保持模型原有配置；缺失的定制底模会报告具体路径。各变体可能需要额外下载与自身架构匹配的底模，默认安装包不包含所有变体权重。CPU 使用 FP32，ROCm 使用 HIP；SeedVC 的 WAV 保存兼容新版 torchaudio，无需 TorchCodec。以上为加载与运行路径兼容，不能替代各实际权重的推理验收。

UVR 的 PyTorch 模型使用 ROCm；Windows ONNX Runtime 默认仍为 CPU provider，不能把 CUDA provider 用于 AMD。不同 UVR 模型的加速能力需单独验收。

## 依赖迁移

SVC/RVC/Vocal 使用 NumPy 1.26.4、SciPy 1.13.1 和支持 3.12 的依赖。SVC 改用提供 Windows cp312 wheel 的 `fairseq-fixed==0.12.3.1`（导入名仍为 `fairseq`）。

RVC 上游 0.1.5 固定旧 fairseq、NumPy、faiss 和 OmegaConf，无法在 3.12 直接解析。`install/build_rvc_compat.py` 先验证原 wheel 的 RECORD，再生成 `rvc-python==0.1.5+xb312`，只调整这四项依赖、Python 版本声明和本地包版本，保留上游推理代码及许可。离线打包时同样构建该 wheel，不跳过依赖一致性检查。

验收需覆盖各模型的导入、短音频真实推理、CPU/CUDA 回归和 ROCm 10 实机测试。普通单元测试和 wheel 元数据检查不能代替这些验收。
