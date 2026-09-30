# 共享运行时与兼容布局

本文是当前运行环境布局的唯一说明。早期空间盘点、缓存恢复和实验安装记录已合并到这里；历史版本行为保留在 `docs/release-notes/`。

## 发布结论

NVIDIA CUDA126 和 CUDA128 默认使用两层共享环境。CPU 与 ROCm 10 使用隔离环境，所有组件均使用 64 位 CPython 3.12.x；不同组件的依赖仍单独解析。项目不再发布或新建 cu121 CUDA 栈。

| 硬件包  | 默认布局 | 主要目录                                                                                       |
| ------- | -------- | ---------------------------------------------------------------------------------------------- |
| CPU     | 隔离兼容 | `.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp`、`.venv-vocal` |
| ROCm 10 | 隔离     | `.venv-*`，包含 PyMSS；校验 ROCm 10、HIP 和 GPU 运算，失败时不会静默安装 CPU                 |
| CUDA126 | 两层共享 | `runtimes/core-cu126`、`runtimes/svc-cu126`                                                |
| CUDA128 | 两层共享 | `runtimes/core-cu128`、`runtimes/svc-cu128`                                                |

“共享”是依赖布局，不表示所有组件进入同一个 Python。两个共享层用于隔开 NumPy/protobuf/AudioTools 与旧 SVC/RVC 依赖之间的冲突。

ROCm 10 的 SVC、RVC 和 Vocal 共用 `runtimes/svc-rocm10`。RVC 的 DirectML 版本必须保持独立，安装到 `.venv-rvc-directml`，并通过 `runtime.json` 的 `rvc-directml` 路由选择；它不能与 ROCm Torch 混装在同一个环境中。推理参数显式使用 `device=directml` 时才会启动该解释器，`device=rocm` 或 `auto` 继续使用 ROCm 路由。

## 组件路由

| 共享层                          | 组件                                   | 说明                   |
| ------------------------------- | -------------------------------------- | ---------------------- |
| `core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC                  | 统一的现代核心配方     |
| `svc-cu126` / `svc-cu128`   | So-VITS-SVC、RVC、Vocal/DeepFilterNet3 | 兼容旧模型框架的共享层 |

应用不再根据固定目录猜测当前布局。安装成功后，`install/runtime_manifest.py` 把每个组件的相对 Python 路径写入 `runtime.json`；应用优先读取该文件，再回退到旧 `.venv-*`，以支持已有安装升级。

PyMSS、插件和 ModelScope Hub 不应被文档描述成 AI 两层共享环境的固定成员。它们按各自实现和依赖要求安装，不能因为使用了某个现有解释器就改变 core/svc 的发布边界。

## 安装入口

- `install/install_shared.py`：CUDA126/CUDA128 的共享编排入口，只暴露已验证的共享策略。
- `install/install.py`：组件安装公共实现，同时保留 CPU、ROCm 10 和旧隔离安装兼容入口。
- `setup_env.bat`：用户统一修复入口。安装包写入的 `installer_env.cmd` 会记录 `XB_RUNTIME_LAYOUT` 和 `XB_GPU_STACK`；CUDA 修复继续走共享入口，CPU/ROCm 10 继续走隔离入口。
- `setup_shared_env.bat`：开发者显式测试共享布局的入口。

安装器传递的固定参数：

```text
CUDA126: --gpu --cu126 --consolidated
CUDA128: --gpu --cu128 --consolidated --core-profile core-cu128
ROCm 10: --rocm10
CPU:      --cpu
```

只安装独立 DirectML RVC 环境：

```powershell
python install/install.py --directml --only rvc
```

ROCm RVC 默认保留 rvc-python 的 fp16 GPU 路径。若目标驱动或模型在 fp16 下不稳定，可临时设置 `XB_RVC_ROCM_FP32=1` 重试；worker 日志中的 `RVC_COMPONENT_DEVICES` 和 `RVC_TIMING` 会分别显示组件设备及模型/后处理耗时。

`--consolidated` 仍由旧公共实现识别，但在发布流程中它表示 CUDA 共享布局，不再作为面向用户的实验开关。旧安装若没有 `XB_RUNTIME_LAYOUT`，无参数运行 `setup_env.bat` 仍保持兼容行为；显式传入 `--cu126`、`--cu128` 或 `--consolidated` 会选择共享入口。

## 配方与离线材料

CUDA128 的固定核心配方位于：

- `install/runtime_profiles/core-cu128/requirements.lock`
- `install/runtime_profiles/core-cu128/profile.json`
- `assets/runtime/core-cu128/compat/`
- `assets/runtime/core-cu128/candidate/`
- `assets/runtime/core-cu128/rollback/`

固定配方使用 NumPy 2.2.6、protobuf 7.36.0、TensorBoardX 2.6.5 和本地 AudioTools 兼容 wheel。哈希和重建方式见 [core-cu128 配方说明](../install/runtime_profiles/core-cu128/README.md)。CUDA126 复用已验证的兼容材料，但使用自己的 Torch cu126 wheels 和运行时目录，绝不回退 cu121。

`install/prepare_wheelhouse.py` 准备四栈缓存，`installer/stage_wheelhouse.py` 在构建专用包时只暂存目标栈需要的 wheels。运行环境全部校验通过后，安装器删除用户安装目录中的 `assets/wheels`；如果失败则保留，便于离线重试。

CUDA 安装包构建还必须携带 `assets/runtime/core-cu128/candidate` 和 `compat`。这些二进制
材料不提交 Git，可在构建时用 `installer/build.ps1 -RuntimeAssets <备份目录>` 同步；构建器
会校验 profile 锁文件及每个 wheel 的 SHA-256，避免把缺少 `protobuf==7.36.0` 的包发布出去。

## 原子安装与激活

共享安装遵守以下边界：

1. UVR、SeedVC、DDSP 作为 core 组整体预解析，不能只修改其中一部分后就发布全部路由。
2. SVC、RVC、Vocal 安装期间延后最终 `pip check`，待完整共享层安装结束后统一校验。
3. 只有 Python 可执行、依赖检查、Torch/CUDA、关键模块导入和兼容探针全部通过，才更新 `runtime.json`。
4. 失败不会把半成品环境声明为可用，也不会自动删除旧 `.venv-*` 或用户模型。
5. 修复必须继续使用同一布局；CUDA 共享安装不应切换到旧隔离入口逐项覆盖包版本。

## 验证命令

只做安装器与脚本校验：

```powershell
& .\installer\build.ps1 -ValidateOnly
```

只解析 CUDA128 core 配方，不安装：

```powershell
& .\setup_shared_env.bat --cu128 --only uvr seedvc ddsp --preflight-only
```

检查已安装共享环境：

```powershell
& .\runtimes\core-cu128\Scripts\python.exe -B .\install\audit_runtime.py --root . --require-cuda
& uv pip check --python .\runtimes\core-cu128\Scripts\python.exe
& uv pip check --python .\runtimes\svc-cu128\Scripts\python.exe
```

自动化测试边界和命令见 [测试说明](testing.md)。配方解析、重复安装、漂移检测、恢复、模块导入、CUDA 小张量和安装器预检都已有回归覆盖；这些检查仍不能替代在目标显卡上的真实模型、真实音频和完整 Setup.exe 验收。

## 旧安装与清理规则

旧 `.venv-*` 是兼容回退，不属于新 CUDA 安装的目标布局。不要在安装过程中主动删除它们：只有在 `runtime.json` 已指向新环境、真实推理验收通过、没有外部快捷方式或手工脚本引用后，才由用户单独清理。

以下内容不是源码清理对象：

- `runtimes/` 下正在使用的本机环境。
- `.xb_svcb` 或自定义数据目录中的模型、作品、编辑工程与日志。
- 全局 uv 缓存；它可能被其他项目复用。
- `assets/runtime/core-cu128` 的配方、兼容和回滚材料。

仓库中的 `.tmp/`、`build/`、`dist/`、`assets/wheels/` 和 `assets/tools/python312/` 是可重建或本机生成内容，已通过 `.gitignore` 排除；是否删除本机副本应与源码提交分开决定。
