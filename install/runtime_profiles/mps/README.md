# macOS / Apple Silicon (MPS) 运行时配方

适用范围：macOS 14+、Apple Silicon（arm64）、CPython 3.12、PyTorch 2.7.1（PyPI macOS wheel，自带 MPS）。

## 入口

```bash
# 全量（含前端构建与底模部署）
python3.12 install/install.py --mps

# 只搭某几个组件（可与 Windows 侧 --only 用法一致）
python3.12 install/install.py --mps --only app plugins seedvc ddsp

# So-VITS-SVC 语音编码器：默认 onnx（无需本地编译）
python3.12 install/install.py --mps --only svc
# 需要 fairseq 版编码器时（从 sdist 编译，需 Xcode CLT）
python3.12 install/install.py --mps --only svc --svc-encoder fairseq
```

也可以直接调用独立入口：`python3.12 install/install_macos.py --only svc`。

## 固定组合

| 组件 | 解释器 | 关键依赖 |
| --- | --- | --- |
| 主程序 | `app/.venv` | `uv sync --project app`（pywebview → pyobjc，macOS 原生后端） |
| 插件运行时 | `.venv-plugins` | 无第三方依赖 |
| UVR 分离 | `.venv-uvr` | `torch==2.7.1` + `audio-separator[cpu]==0.44.2`（Apple Silicon 上自动使用 MPS / CoreML） |
| PyMSS 分离 | `.venv-pymss` | `torch==2.7.1` + `pymss==2.0.18` + 可选 `mlx`（上游 auto 在 Apple Silicon 优先 MLX，失败回退 MPS） |
| So-VITS-SVC | `.venv-svc` | `torch==2.7.1` + `onnxruntime`（默认）或 `fairseq-fixed==0.12.3.1`（可选） |
| RVC | `.venv-rvc` | `torch==2.7.1` + `fairseq-fixed==0.12.3.1` + `rvc-python==0.1.5+xb312` |
| SeedVC | `.venv-seedvc` | `torch==2.7.1` + `transformers==4.46.3` + `funasr`（无 fairseq） |
| DDSP-SVC | `.venv-ddsp` | `torch==2.7.1` + `transformers==4.46.3`（Transformers HuBERT，无 fairseq） |
| 歌声增强 | `.venv-vocal` | `deepfilternet[soundfile]==0.5.6` + `pedalboard==0.9.24` + `praat-parselmouth==0.4.6`（CPU） |
| 模型上传 | `.venv-hub` | `modelscope` |

环境布局为 **isolated**（每个组件一个 venv），路由写入项目根 `runtime.json`：

```json
{
  "version": 1,
  "stack": "mps",
  "layout": "isolated",
  "python": { "svc": ".venv-svc/bin/python", "...": "..." }
}
```

`app/config.py` 通过清单解析这些解释器；未写入清单的组件会回退到约定目录名。

## 与 Windows 配方的差异（有意保留）

1. **不使用平台锁文件**：Windows 侧 `uv pip compile --python-platform windows` 与离线
   wheelhouse 全部跳过，直接解析 PyPI 上带 MPS 的 macOS arm64 wheel。
2. **不启用共享运行时**：`--consolidated` / `--preflight-only` / `--core-profile` 与 `--mps`
   互斥。
3. **torch / torchaudio 由本配方管理**：上游 requirements 里的旧钉死（如
   `fairseq==0.12.2`）会被剔除或替换，因为它们在 CPython 3.12 上不可安装。
4. **SeedVC 忽略上游 `requirements-mac.txt`**：该文件用 `--extra-index-url .../cu121`
   拉 CUDA 版 torch，在 Apple Silicon 上不可用；本配方沿用 Windows 侧的
   剔除/覆盖规则，torch 单独安装。
5. **RVC 复用 3.12 兼容 wheel**：`install/build_rvc_compat.py` 产出的
   `rvc_python-0.1.5+xb312-py3-none-any.whl` 平台无关，直接把
   `fairseq==0.12.2`、`faiss-cpu==1.7.3`、`numpy<=1.23.5` 等旧钉死替换为可用版本。

## 已验证结论（调研与实测）

* `fairseq-fixed==0.12.3.1` 在 Apple Silicon 上**可从 sdist 编译成功**
  （实测生成 `fairseq_fixed-0.12.3.1-cp313-cp313-macosx_11_0_arm64.whl`），
  因此在 fairseq 路径下无需等待上游发布 mac wheel。
* MPS 算子覆盖：`complex64`、`torch.complex`、`stft/istft`、`rfft/irfft`、
  `view_as_real`、fp16 matmul、bool `interpolate`、负+正混合 `pad`、长序列 `cumsum`、
  `linalg.solve`、`conv_transpose1d` 全部可用；**唯一硬缺口是 `float64`**。
* `pyworld` 在 macOS arm64 上没有 wheel，只能本地编译（Xcode CLT）；失败时
  `dio` / `harvest` / `pm` 三个 F0 预测器不可用，但 `rmvpe` / `fcpe` / `crepe`
  三个纯 torch 预测器不受影响。

## 已知限制

* 本配方只覆盖「启动 + MPS 推理」；系统音频实时变声（Windows WASAPI 回环）、
  JUCE VST3 插件宿主、macOS 打包/安装器不在范围内。
* 性能显著低于 CUDA 机器；目标是可用与正确，而不是吞吐。
* `mlx` 需要 macOS 14+，安装失败不影响 MPS 路径。
