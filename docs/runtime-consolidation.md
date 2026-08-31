# 运行环境整合记录

分支：`codex/runtime-consolidation`。以下为 2026-08-29 本机实测，不代表所有设备或发布版本。

## 当前结论

**已找到并在本机应用可统一的 NumPy/protobuf 实验配方。** UVR、SeedVC、DDSP 的原始上游要求不能直接合并，但更换旧 TensorBoardX 并制作本地 AudioTools 兼容构建后，整体依赖解析和关键运行检查均通过。完整模型音频验收、性能对比及旧环境清理仍未完成，不能称为发布验收通过。

本机现有 `runtime.json` 现已将 UVR、SeedVC、DDSP 都指向 `runtimes/core-cu128/Scripts/python.exe`。原 `.venv-uvr` 已整体迁移为该 cu128 主环境；cu126 目录仅保留为未激活的实验环境。迁移前保存的旧版 wheel 和配方材料仍保留，没有删除模型权重。

| 包 | 修改前 | 当前实验版本 |
| --- | --- | --- |
| NumPy | 1.26.4 | 2.2.6 |
| protobuf | 3.19.6 | 7.36.0 |
| TensorBoardX | 2.6 | 2.6.5 |
| descript-audiotools | 0.7.2 | 0.7.2+xb1（本地兼容构建） |

本机采用最小四包增量修改；`uv pip check` 检查 146 个已安装包，全部兼容。后续固化已以这 146 个包的实际版本为基准重新整体解析，消除了早期临时解析结果中 setuptools、packaging、msgpack、platformdirs 的版本差异。新配方固定 147 项；唯一额外项 `hf-xet==1.6.0` 是平台标记差异引入的下载辅助包，现有环境可缺少，元数据校验会单列说明。没有为固定配方重装现有环境。

## 当前运行检查

| 检查项 | 实测结果 |
| --- | --- |
| Python | 3.10.21 |
| Torch / torchaudio / torchvision | 2.7.1+cu128 / 2.7.1+cu128 / 0.22.1+cu128 |
| CUDA | RTX 5060 Ti 可用，小张量计算通过 |
| UVR VR 模块导入 | 通过 |
| UVR MDX 模块导入 | 通过；修改前 protobuf 缺少 `runtime_version` 的错误已消失 |
| SeedVC inference / LengthRegulator 导入 | 通过 |
| DDSP / Reflow vocoder 导入 | 通过 |
| ONNX 序列化、校验与执行 | 简单 Identity 图经 ONNX Runtime 执行通过；不是 MDX 权重推理 |
| SeedVC 音频前处理 | 重采样、梅尔谱、crossfade、AudioSignal STFT 通过 |
| DDSP 音频前处理 | WORLD/Praat 音高、音量提取通过 |
| TensorBoard / TensorBoardX | 标量日志写入并读回通过 |
| 本地 UVR VR 真实权重 | `5_HP-Karaoke-UVR.pth`、`UVR-DeEcho-DeReverb.pth` 对两秒合成音频分离完成；波形有限值、采样率和长度检查通过，不代表歌曲质量验收 |
| SeedVC/DDSP 完整模型音频、质量与性能 | 尚未验收 |

## 原始冲突与处理依据

修改前依赖元数据检查确认：

- `audio-separator==0.44.2` 要求 `numpy>=2`；SeedVC 和 DDSP requirements 要求 `numpy==1.26.4`。
- `ml_dtypes==0.6.0` 要求 `numpy>=2.0.0`，修改前实际为 1.26.4。
- `onnx-weekly==1.23.0.dev20260824` 要求 `protobuf>=6.31.1`，修改前实际为 3.19.6。
- SeedVC 的 `descript-audio-codec` 依赖链引入 `descript-audiotools==0.7.2`，后者要求 `protobuf>=3.9.2,<3.20`。

不能仅从版本锁定推断代码一定无法兼容。对照测试中，NumPy 1.26.4/2.2.6 的关键路径均通过。protobuf 7.36.0 下 AudioTools、TensorBoard、UVR、SeedVC、DDSP 通过，而 TensorBoardX 2.6 因旧生成代码直接构造 descriptor 而失败；升级 2.6.5 后通过，没有强制纯 Python protobuf 或禁用版本检查。

本地 AudioTools 构建 `0.7.2+xb1` 保留 0.7.2 功能代码，只改变本地版本标记及依赖声明（protobuf==7.36.0、tensorboard==2.20.0）。构建前验证源文件 RECORD 哈希，重建 wheel RECORD，并保留许可信息和变更来源。**这属于项目维护的实验兼容构建，不是上游已宣布支持 protobuf 7。** 未使用 `--override protobuf` 或忽略 `pip check` 掩盖旧约束。

参考：[protobuf 跨版本兼容说明](https://protobuf.dev/support/cross-version-runtime-guarantee/)、[AudioTools 上游依赖声明](https://github.com/descriptinc/audiotools/blob/master/setup.py)、[TensorBoardX 发布页](https://pypi.org/project/tensorboardX/)。

## 本轮完成的防护

1. `--consolidated` 在创建/改装模型环境前整体解析三组依赖；不允许只安装一部分却激活全部路由。缺少引擎 requirements 时直接提示，不自动删除或重新获取源码。
2. 后续共享安装使用同一个解析结果约束版本；解析冲突不再触发整环境 `--reinstall`。安装后还必须通过 `uv pip check` 和关键模块导入检查。
3. Torch 构建版本匹配且可以实际导入时，跳过强制重装。CUDA 三件套在 UVR 依赖安装时固定版本，防止宽泛的 torchvision 依赖拉入另一套 Torch。
4. `runtime.json` 原子更新、保留其他组件的映射。应用和安装包按显式配置、有效清单、旧路径的顺序找解释器，不把遗留 core 目录视为已激活。清单的相对路径以清单所在目录为基准。
5. 旧清单已让多个组件共用环境时，阻止单独“修复”其中一个组件。移除清单只改变路由，不会撤销已经发生的包版本覆盖，不能当成完整回滚。
6. 大模型只在同内容时去重；同大小但 SHA-256 不同的文件保留。部署采用临时文件后替换，避免覆盖硬链接时连带修改原文件；跨卷自动复制。未对本机既有权重执行去重或清理。

注意：预检会读取包元数据，本轮用联网元数据完成了整体解析；Torch 索引提供独立元数据文件，未下载或重装 Torch。要保证离线可设 `UV_OFFLINE=1`，但缓存不足会报错。必须用 `--preflight-only` 才是仅解析；不带该参数的安装阶段可能下载模型或大包。

## 兼容配方入口

长期配方：`install/runtime_profiles/core-cu128/requirements.lock` 和 `profile.json`。
兼容 wheel：`assets/runtime/core-cu128/compat/descript_audiotools-0.7.2+xb1-py3-none-any.whl`。
SHA-256：`22eb8ec9db1c52a16ed3c2202f61b02ba9249c3038066e06097a1912ac1d8b27`。
旧临时构建仍保留；新构建仅改变来源记录和 RECORD，不改功能文件，且没有重装环境。
详见 [固定配方、离线重建及回滚边界](../install/runtime_profiles/core-cu128/README.md)。

只解析，不改装环境：

```powershell
.\app\.venv\Scripts\python.exe -B install\install.py --consolidated --cu128 --only uvr seedvc ddsp --core-profile core-cu128 --preflight-only
```

中间约束写入 `.tmp/core-cu128.constraints.txt`，可由长期配方重新生成。仅 cu128 已验证；不自动用于 CPU/cu121/DirectML。未显式选择配方或候选 wheel 时保留上游原始要求，冲突会停止。不要单独运行旧 requirements，否则可能覆盖共享环境版本。固定配方使用 uv 的 `--torch-backend cu128` 按包选择 Torch 源，避免普通包受到 Torch 索引旧版本的限制。

复现构建使用 `install/build_core_compat.py --source-wheel <保存的原版0.7.2 wheel> --output-dir <输出目录>`，不安装依赖。仍支持原版 site-packages 输入，两种来源产生相同构建结果；当前已修改环境不能作为原版输入。`--support-wheel <路径>` 可复用缓存中已编译的辅助 wheel，固定配方还会验证这些文件的哈希，预检禁止现场源码构建。

## 离线自检

从项目根目录执行，用待检查的模型环境 Python：

```powershell
.\runtimes\core-cu128\Scripts\python.exe -B install\audit_runtime.py --root . --require-cuda --output .tmp\runtime-audit.json
```

CPU 环境去掉 `--require-cuda`。检查脚本只读取包元数据、启动离线导入子进程；指定 `--output` 时另外写一份 JSON 报告，不安装依赖或下载模型。退出码 1 表示有失败，详情在报告中。每个模块有超时限制，检查通过也不等同于音频验收通过。

最新本机报告（未纳入版本控制）：

- `.tmp/core-compat-migration/audit-after.json`：真实共享环境的依赖和导入结果。
- `.tmp/core-compat-migration/probes-after.json`：同一环境、没有跨环境加载替换的五项检查。
- `.tmp/core-compat-migration/uvr-audio/result.json`：两个本地 VR 权重的短音频结果。纯音测试的人声轨接近静音，库按阈值不写出文件；检查了写入前的真实波形，未将缺文件误算成成功输出。
- `.tmp/core-compat-migration/before.json` / `after.json`：四个小包及 Torch 三件套修改前后版本。
- `assets/runtime/core-cu128/rollback/`：已校验 SHA-256 的四个原版 wheel，长期保存；临时目录中的原件也保留。

`.tmp/runtime-audit.json` 是修改前失败报告，不代表当前状态。回滚包仅用于恢复修改前版本；修改前状态本身存在 UVR MDX 依赖冲突，不能当成已验证健康版本。

## 下一阶段迁移计划

| 分组 | 处理方式 |
| --- | --- |
| UVR + SeedVC + DDSP | 本机已使用同一 Python、NumPy 2.2.6 和 protobuf 7.36.0，继续完整模型验收 |
| Vocal / SVC / RVC / PyMSS / 插件 / DirectML | 继续独立，分别验证后再考虑减少环境数量 |

执行顺序：

1. 保持当前 `runtimes/core-cu128` 主环境，完整验收之前不清理它或其他旧环境。
2. SeedVC 主模型及 Whisper、BigVGAN、CampPlus 权重已由用户下载，四个 SHA-256 和本地路径识别通过；DDSP 仍需 6.3 RectifiedFlow 主模型和对应配置。真实音频验收按用户要求暂缓。
3. 147 包完整配方在独立空环境安装、无改动重复安装、四包漂移检测及恢复、依赖/导入/CUDA 基础检查均已通过。通过校验重封装旧缓存解决了 torchvision 等缓存缺口，本轮零新增下载；尚不是安装 EXE/其他电脑/真实音频验收。见 [安装与修复验证](runtime-install-validation.md)。
4. 用短音频分别测试 UVR VR/MDX、SeedVC 转换、DDSP 转换，再验收完整流程。届时需要 SeedVC 主模型、DDSP 配套权重/配置，以及短音频；先确认本地是否已有，不盲目下载。
5. 对比空间占用、启动时间、显存和输出效果，确认没有活动引用后才清理旧环境。

空间盘点已完成：旧环境及未共享的重复模型合计约 5.35 GiB 候选规模，已排除现有硬链接重复计算；没有删除任何旧环境或权重。全局 uv 缓存另行列出，不计入承诺可回收空间。见 [空间盘点与候选清单](runtime-storage-audit.md)。

## 验证记录与限制

- 固化后全套回归：330 通过、15 跳过、0 失败。原先两项 Python 检测失败已修复；两项 wheelhouse 断言移入独立测试数据后通过，另设真实源码集成检查，没有删除原有断言。
- 15 项跳过中，14 项是主程序测试解释器缺少 Torch；随后用现有共享解释器叠加临时 pytest 对 `test_inference_devices.py` 补跑，30 项全部通过，包含这 14 项。未向主程序或共享环境安装 Torch/pytest。
- 剩余 1 项为打包集成缺少 SVC requirements；严格发布模式下会失败而非跳过。见 [测试分组](testing.md)。
- 未执行安装包编译、发布、SeedVC/DDSP 完整模型音频验收，也没有完成全部环境整合或空间回收。
- 后两项继续验证：新增 18 项安装/存储防护回归，全套 348 通过、15 跳过；共享解释器补跑设备辅助测试 30 项通过。现用 146 包仍匹配配方，`pip check` 通过，Torch 和路由未改动。独立四包部署测试使用 `--no-deps`，不能代替完整运行时验收。
- 缓存复用继续验证：新增 14 项回归，全套 362 通过、15 跳过。完整 147 包空环境安装使用正常依赖解析，不用 `--no-deps`；重复安装及故障注入后的修复通过，5 项导入/CUDA 与 5 项兼容性探针通过。生产环境仍维持原 146 包和原路由。
