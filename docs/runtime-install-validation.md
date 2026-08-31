# 合并运行时：安装与修复验证

2026-08-29，分支 `codex/runtime-consolidation`。真实模型推理按用户要求暂缓。

## 结论

**147 包固定配方已在独立空环境中完整安装通过**，重复安装、依赖校验、版本核对、模拟漂移后恢复、离线模块导入和 CUDA 小张量检查均通过。本轮零新增下载；未修改现用 `.venv-uvr`、Torch、模型权重或 `runtime.json`。

这是本机 Python 依赖层的干净安装验收，不是安装 EXE 全流程、其他电脑部署或真实模型音频验收；后几项仍未完成。

| 检查 | 本机结果 | 边界 |
| --- | --- | --- |
| 固定 147 项整体解析 | 通过 | 解析不代表 wheel 全部已缓存 |
| 现用环境安装预演 | 只计划更新 AudioTools 本地来源记录、增加 hf-xet；没有重装 Torch 三件套 | `--dry-run`，没有执行安装 |
| 四包离线首次安装 | 通过 | NumPy、protobuf、TensorBoardX、AudioTools；使用 `--no-deps`，不是完整依赖安装 |
| 四包重复安装 | 通过 | 包元数据文件大小、修改时间均未变化 |
| 四包回滚再恢复配方 | 通过 | 仅版本恢复；旧版本组合不是已知健康环境 |
| 147 包干净环境安装 | 通过 | 空环境开始，正常依赖解析安装，未使用 `--no-deps` |
| 147 包重复安装 | 通过 | `Checked 147 packages`，全部包元数据文件未改写 |
| 完整环境内的四包漂移/修复 | 通过 | 旧四包触发 3 项依赖冲突；完整配方只替换四包，其他 143 包元数据未变 |
| 离线导入/CUDA/兼容性探针 | 通过 | 5 项运行时导入及 CUDA 小张量；5 项前处理/ONNX/TensorBoard 探针，不是音频权重推理 |
| 共享安装部分失败 | 回归通过 | 停止后续共享步骤、不更新路由；不会自动撤销已经修改的包 |
| 固定配方最终校验 | 回归通过 | 安装后逐项比较版本/平台；有漂移不更新路由 |
| 单独修复 UVR/SeedVC/DDSP | 拒绝危险操作 | 已共享环境必须作为一组按同一配方处理 |

全套回归 **362 通过、15 跳过、0 失败**。其中 14 个 Torch 辅助逻辑跳过项此前用共享解释器另行补跑，所在文件 30 项全部通过；其余 1 项缺 SVC 源码 requirements，严格发布模式仍会失败。没有执行模型权重推理或安装包编译。

本轮新增缓存完整性/不可覆盖/错误版本拒绝测试，并修复了安装器配方模块加载对工作目录和测试顺序的隐式依赖：现在按脚本同目录加载，不要求外部先修改 `sys.path`。

收尾又用本轮新建的完整环境补跑设备辅助测试，30 项全部通过；安装器 `--core-profile core-cu128 --preflight-only` 在 `UV_OFFLINE=1` 下整体解析 147 项通过。

## 缓存缺口及解决方式

当前工具是 uv 0.12.5。下载缓存中有 `wheels-v5` 与 `wheels-v6`；上一轮 v6 安装请求首先停在：

```text
torchvision==0.22.1+cu128
torchvision-0.22.1+cu128-cp310-cp310-win_amd64.whl
```

只读检查发现 v5 条目引用 `archive-v0/jEz1pKh7OqxSllTqfNwhh`，其中 METADATA 是同一个 torchvision 版本。uv 官方说明缓存桶会版本化，不同版本不保证复用条目，见 [官方缓存说明](https://docs.astral.sh/uv/concepts/cache/#cache-versioning)。所以“以前下载过”不保证当前安装命令命中缓存，不能直接要求用户重下 Torch。

本轮新增 `install/recover_cached_wheel.py`：从匹配版本/平台的旧缓存读取文件，逐个核验 RECORD 中的 SHA-256 与长度，拒绝额外文件、路径跳转、缺文件、版本不符及覆盖已有导出，然后生成本地 wheel 和来源记录。不修改 uv 内部缓存布局，不从现用环境复制包。

共恢复 **71 个缓存包，导出 wheel 合计 246,061,431 字节（约 234.7 MiB）**。只调整 ZIP 封装和 RECORD 路径格式，功能文件与依赖元数据不改。这些是本地重封装包，**不是与上游原始 ZIP 哈希一致的重新下载包**；cached RECORD 验证本地内容完整性，不代表独立验证发布者身份。Torch/torchaudio 由当前可用缓存直接复用，未重新下载或重封装。

上一轮从官方 PyPI 下载的 29 个小 wheel，共 **28,767,077 字节（约 27.4 MiB）**，本轮直接复用。本轮下载列表为空。下载防护仍保留：小包单个上限 64 MiB、累计 200 MiB，Torch 系列及大型 GPU 依赖不自动下载。此次安装依赖“既有 uv 缓存 + 本地 wheel”，尚未形成可脱离这台机器缓存的完整离线分发包。

## 可复用工具与报告

- `install/validate_core_install.py`：只允许 `%TEMP%/xb-core-install-check-*` 下的独立环境；完整模式还要求环境为空。默认离线，`--fill-small-cache` 才允许受限下载。
- `--compat-only`：验证四个本地 wheel 的安装、重复安装、回滚和恢复。不能把该结果当成完整依赖检查通过。
- `--recover-cache <uv缓存>`：优先校验并导出已有缓存；`--wheel-dir <目录>` 可重复指定，复用已保存 wheel。
- `--repair-check`：仅对已匹配完整配方的独立测试环境注入旧四包，再用完整配方离线修复；不用于生产环境。
- `.tmp/core-install-validation.json`：上一轮安装停止报告，保留作历史，不代表当前结果。
- `.tmp/core-compat-install-validation.json`：上一轮四包实测，`ok=true`。
- `.tmp/core-install-validation-cache-reuse.json`：本轮完整安装，`fresh_install_ok=true`、`repeat_metadata_unchanged=true`、147 项版本匹配，下载列表为空。
- `.tmp/core-full-repair-validation.json`：完整环境内的四包漂移检测及恢复，`ok=true`，其他包元数据未变。
- `.tmp/core-fresh-runtime-audit.json`：5 项导入检查、RTX 5060 Ti CUDA 小张量通过，依赖冲突为空。
- `.tmp/core-fresh-compat-probes.json`：5 项兼容性探针全部通过。

早期四包测试目录保留在：

```text
C:/Users/A/AppData/Local/Temp/xb-core-install-check-7045b7997adb45e59f001254cdf88324
```

该目录目前只装有四个兼容包，不是可用的模型运行时，也没有被应用引用。文件逻辑大小约 71.2 MiB，其中约 43.5 MiB 与 uv 缓存硬链接共享；另含上述小 wheel。为保留缓存与复查材料，本轮未删除。若后续重做“完整首次安装”，另建空白验证环境，不复用此四包环境冒充干净安装。

本轮完整配方验证目录：

```text
C:/Users/A/AppData/Local/Temp/xb-core-install-check-dba559a410ff43f2bce9748e74cc2fbc
```

其中 `venv` 含完整 147 包，`recovered-wheels` 保存导出包和来源记录。全部文件逻辑大小约 6.84 GiB，但大部分与 C 盘 uv 缓存硬链接共享；目录自身独占逻辑大小上界约 243 MiB，不是另复制一套 6.84 GiB 的 Torch。没有将应用路由切换至该临时环境，也没有清理它。

复现需新建空环境（不要把生产路径作为 sandbox），例如：

```powershell
$checkDir = Join-Path $env:TEMP ('xb-core-install-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checkDir
uv venv --offline --python .venv-uvr/Scripts/python.exe "$checkDir/venv"
.\app\.venv\Scripts\python.exe -B install/validate_core_install.py --sandbox $checkDir --recover-cache C:/Users/A/AppData/Local/uv/cache --wheel-dir C:/Users/A/AppData/Local/Temp/xb-core-install-check-7045b7997adb45e59f001254cdf88324/small-wheels --wheel-dir C:/Users/A/AppData/Local/Temp/xb-core-install-check-dba559a410ff43f2bce9748e74cc2fbc/recovered-wheels --output .tmp/core-install-validation-repeat.json
```

这里没有 `--fill-small-cache`，因此缺包也不会联网下载。临时目录若被系统清理，需要重新准备材料；此命令不是承诺安装器所有步骤已端到端通过。

现用环境复核：146 项版本均匹配固定配方，唯一未安装项是可选 `hf-xet`，`uv pip check` 通过。`runtime.json` SHA-256：

```text
381bee8386ddafd35ce94b5a1970781b9f48e830b6f4339e5bc163fd86e7ee2e
```

安装失败后“未更新路由”不等于原环境完全未改变；本轮因此把实际安装操作限制在独立验证目录。不要用删除 `runtime.json` 代替回滚。
