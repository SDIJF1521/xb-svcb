# 合并运行时：空间盘点与候选清单

2026-08-29 本机只读快照。**没有删除旧环境、模型、缓存或用户数据，没有执行模型去重。**

## 结论

旧环境候选约 **3.32 GiB**，尚未共享存储的重复模型约 **2.03 GiB**，合计约 **5.35 GiB 的候选瘦身规模**。这是逻辑文件大小估算，不是已经释放的磁盘空间，也不是可立即删除的清单。实际释放量还受 NTFS 分配、压缩、其他引用和清理方式影响。

| 目录 | 逻辑大小 | 当前用途与处理意见 |
| --- | ---: | --- |
| `.venv-uvr` | 6.659 GiB | UVR、SeedVC、DDSP 当前共用；必须保留 |
| `app/.venv` | 66.1 MiB | 主程序与插件 Python；保留 |
| `.venv-uvr-demo` | 3.318 GiB | Python 3.12 旧实验环境；当前配置/启动代码未发现引用，列为待确认候选 |
| `runtimes/core-cu128` | 4.61 MiB | 未激活的早期创建目录；不是当前共享环境，列为待确认候选 |
| `.tmp` | 49.9 MiB | 包含迁移报告、探针和旧 wheel；先保存审计记录，不能整目录盲删 |
| `assets/runtime/core-cu128` | 47.9 MiB | 长期兼容构建及回滚材料；保留 |
| `assets/models` | 3.469 GiB | 模型安装来源和部分运行时模型；保留所需路径 |
| `engines` | 3.648 GiB | 引擎源码及运行模型；不能作为缓存清理 |
| `models` | 0.326 GiB | 当前 UVR 默认模型目录；不能直接删 |
| `.git/lfs/objects` | 2.087 GiB | Git LFS 对象库；本轮不列入回收额度 |

根目录没有 `.venv-seedvc` 或 `.venv-ddsp`，不计算不存在的环境所能节省的空间。

## 重复模型：必须保留路径，不能直接删其中一份

仅比较模型目录中至少 32 MiB、大小相同的文件，再核验 SHA-256；同大小但内容不同的文件不会合并。以下潜在节省已按真实文件标识排除已有硬链接。

| 模型 | 相同内容所在位置 | 尚可共享的逻辑大小 |
| --- | --- | ---: |
| ContentVec legacy | `assets/models/pretrain/checkpoint_best_legacy_500.pt`；`engines/so-vits-svc/pretrain/checkpoint_best_legacy_500.pt` | 1.239 GiB |
| RMVPE | `assets/models/pretrain/rmvpe.pt`；SVC 的 `pretrain/rmvpe.pt`；DDSP 的 `pretrain/rmvpe/model.pt` | 0.343 GiB；三个路径实际上只有两份内容存储 |
| UVR DeEcho/DeReverb | `assets/models/uvr/UVR-DeEcho-DeReverb.pth`；`models/uvr/UVR-DeEcho-DeReverb.pth` | 0.208 GiB |
| UVR 5_HP | `assets/models/uvr/5_HP-Karaoke-UVR.pth`；`models/uvr/5_HP-Karaoke-UVR.pth` | 0.118 GiB |
| FCPE | `assets/models/pretrain/fcpe.pt`；`engines/so-vits-svc/pretrain/fcpe.pt` | 0.064 GiB |
| SVC NSF-HiFiGAN | `assets/models/pretrain/nsf_hifigan/model`；`engines/so-vits-svc/pretrain/nsf_hifigan/model` | 0.053 GiB |
| DDSP PC-NSF-HiFiGAN | `assets/models/pretrain/pc_nsf_hifigan/model.ckpt`；DDSP 的 `pretrain/nsf_hifigan/model` | 0；已经是硬链接 |

安装器读取 `assets/models`，运行路径分别读取引擎模型目录或 `models/uvr`。后续若获准去重，应复用同卷硬链接并保留各路径，操作前重查哈希、占用与目标；更新权重必须通过临时文件替换，不能原地改写共享文件。

## 全局 uv 缓存：不能按本项目用途直接判定可删

`C:/Users/A/AppData/Local/uv/cache` 快照逻辑大小约 **34.03 GiB**。按文件标识去重后约 33.85 GiB，仍不是可释放空间承诺；包含其他项目、旧版 uv 缓存及可能仍要复用的 Torch。

五个较大的 `.tmp*` 子目录合计约 **7.69 GiB**，可能是历史下载/解压残留，但仅凭命名不能确认。先确认没有相关 uv/安装进程与占用、是否仍需恢复下载，再单独处理。此数不加入上述 5.35 GiB。

新验证确认：旧 `wheels-v5` 有 torchvision 的同版本缓存，但当前 uv 的 v6 安装未直接命中。现已通过逐文件校验后导出 71 个本地 wheel 完成完整配方安装，零新增下载；没有改写内部缓存格式。清空全局缓存可能反而迫使重新下载。详见 [安装验证记录](runtime-install-validation.md)。

后续创建的完整测试环境位于 `%TEMP%/xb-core-install-check-dba559a410ff43f2bce9748e74cc2fbc`，未计入上面的早期快照。目录逻辑大小约 6.84 GiB，其中大部分与 uv 缓存硬链接共享，自身独占逻辑大小上界约 243 MiB。该目录及早期四包验证目录都未被应用引用，可在保留复查材料后另行清理；本轮仍未删除。

## 活动引用与保护范围

- 实际加载 `app/config.py` 后，UVR、SeedVC、DDSP 都解析到 `E:/xb-svcb/.venv-uvr/Scripts/python.exe`，插件解析到 `app/.venv`。
- `runtime.json` 未改变；没有继承的 Python 路径覆盖变量。共享环境 `.pth` 未引用旧实验目录。
- 检查了项目启动代码、相关配置及用户模型/设置路径；未发现指向 `.venv-uvr-demo` 或遗留 core 目录的活动配置。手工终端使用、外部快捷方式和全部文件句柄不在此保证范围内。
- 进程快照未观察到项目 Python worker；这不是后续操作时仍无占用的保证。
- `data_home.json` 指向 `D:/XB-SVCB/.xb_svcb`；模型注册、作品、音频等用户数据必须保留。本轮没有递归扫描或处理用户音频。

## 复查方法

```powershell
.\app\.venv\Scripts\python.exe -B install\audit_storage.py --uv-cache C:/Users/A/AppData/Local/uv/cache --output .tmp/storage-audit.json
```

脚本只读目录并写所指定报告，不删除或移动文件；不跟随重解析点。Windows 使用真实文件 stat 取得标识及硬链接计数，避免把 `DirEntry.stat` 的零值误认为独立文件。本次扫描没有读取错误；后续如有错误，不能将不完整扫描视为完整可回收清单。

下一步应先审阅候选并确认旧 demo 环境不再手动使用，再单独授权清理/模型硬链接化。当前真实推理尚未验收，因此仍建议保留现用环境及回滚材料。
