## v0.0.32 · Python 3.12、ROCm 10 与 DirectML 推理修复

本版覆盖 `5616756805648139997bf8c64549fd47b519f849`（含）至 `ac0da7a` 的更新。发布包统一使用 64 位 CPython 3.12，增加 ROCm 10 专用安装包，并继续修复 DirectML 与 ROCm 上的模型推理和离线安装问题。

### 安装包与运行时

- 提供 CPU、ROCm 10、DirectML、CUDA126、CUDA128 五套硬件专用安装包；`build.ps1` 和 `build-all-packages.ps1` 支持 `-Help` / `--help` 查看参数。构建器会核对应用、前端、锁文件、EXE 资源和安装器版本。
- 应用、插件和各推理环境统一迁移到 64 位 CPython 3.12。旧虚拟环境需要重建，旧 `cp310`/`py39` wheelhouse 不能直接用于新安装包。
- ROCm 10 使用 AMD Windows 官方 Torch 套件，安装后检查 ROCm/HIP 标记、GPU 可用性及实际张量运算。So-VITS-SVC、RVC、Vocal 共用 `runtimes/svc-rocm10`；UVR、SeedVC、DDSP 与 PyMSS 仍使用各自的运行环境。
- RVC 可额外安装 `.venv-rvc-directml`。显式选择 DirectML 时才切换到该解释器，自动或 ROCm 模式继续使用 ROCm；两种 Torch 不混装。DirectML 专用包仍单独提供，PyMSS 不宣称支持 DirectML。
- ROCm 安装/修复在修改共享环境前检查是否有进程占用 Torch/HIP DLL，避免在运行中的模型进程上覆盖二进制依赖；`uv pip check` 失败时保留具体冲突输出。离线暂存还会核验 ROCm wheel 的 HIP/ROCm 标记，拒绝错误硬件栈。
- CUDA128 核心配方补齐 `gin-config` 等依赖及哈希；修复 RTX 50 系安装失败。安装器和构建脚本对 Python 3.12、运行时材料及五种硬件栈的校验同步更新。

### 推理与模型兼容

- So-VITS-SVC DirectML 的 F0 粗化保留上游越界音高映射；长音频声源相位在 CPU 以高精度累计，避免 DirectML 单精度累加漂移。浅扩散系数的单元素索引改在 CPU 上完成，修复 DirectML 将非零时间步误读为第 0 项造成的扩散强度错误；主模型、扩散网络和声码器仍在 DirectML 上执行。
- So-VITS-SVC 的 ROCm 路径限制不稳定的 MIOpen ASM 求解器；CPU/ROCm 统一处理半精度 checkpoint 与 FP32 输入。配置启用音量嵌入但 checkpoint 缺少相应权重时，关闭未训练的随机嵌入；对损坏权重和直流/非有限音频输出增加检查。
- RVC 的 ROCm 路径保留 GPU FP16，必要时可用 `XB_RVC_ROCM_FP32=1` 切换；FAISS 与 BLAS 线程数受控，降低检索时的 CPU/内存竞争。RVC 日志补充实际组件设备和推理耗时，DirectML 与 ROCm 各自使用对应解释器。
- DDSP 根据配置和 checkpoint 选择经典、Diffusion 或 RectifiedFlow 6.1/6.2/6.3 加载器；旧模型使用兼容环境。DirectML 对 DDSP 6.3 仍是显式选择的实验路径，自动模式使用 CPU，输出需试听确认。
- SeedVC、UVR、PyMSS 和人声增强链路补齐 Python 3.12/ROCm 10 兼容处理；AMD 上的 ONNX 模型仍使用 CPU provider，不能把它写成 ROCm GPU 加速。

### API 与界面

- API 默认端口改为 `8760`。局域网监听可绑定域名；本机监听清空域名。API Key 改为多条管理，支持名称、有效期、启停和删除；鉴权只接受启用且未过期的 Key，旧单 Key 配置可迁移。
- 桌面音频拖入改为分块传输，支持大于旧 50 MB 限制的文件；文件扩展名大小写统一识别，导入失败会清理未完成的临时文件。
- 创建页在模型列表加载后初始化默认模型选择；设备能力展示会合并 RVC 独立 DirectML 环境，并明确 PyMSS 与 DDSP 的实际设备限制。

### 升级与验收

- 原有模型、作品和编辑工程不因 Python 环境重建而转换。安装或修复时选用 64 位 CPython 3.12，并下载与硬件一致的整套 EXE 和同名前缀 BIN 分卷。
- 从 0.0.31 升级时，先安装 0.0.32 包，再在新安装目录运行 `setup_env.bat` 修复环境，让解释器与 0.0.32 的 wheels 和 `runtime.json` 路由一致；旧 CUDA128 `gin-config` 手动补丁不应应用到新版配方。
- 已新增 API、音频导入、模型兼容、设备、安装器和 wheelhouse 回归测试。代码检查不能替代目标显卡上使用真实模型和同一段音频进行安装与音质验收；DDSP DirectML 实验路径尤其需要人工试听。

安装与修复步骤见 [源码安装与启动](../getting-started.md)，环境布局见 [共享运行时与兼容布局](../runtime-consolidation.md)，ROCm 依赖细节见 [Python 3.12 与 ROCm 10](../python312-rocm10.md)，API 调用见 [FastAPI 接入文档](../api.md)。
