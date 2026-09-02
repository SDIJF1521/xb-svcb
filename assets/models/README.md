# 自带模型（随安装包分发）

此目录存放底模、SeedVC 离线模型与 UVR 分离模型。安装器会
**优先从这里本地复制**到运行目录，复制不到的项才回退联网镜像下载，从而避免缓慢的下载。

模型资产的统一清单位于 [model-manifest.json](model-manifest.json)。它记录每个
引擎需要的自带文件、安装后的目标位置和最小体积。清单不代替用户导入的
SeedVC/DDSP 主模型；这两类模型仍由模型管理页导入。

> 注意：模型为 Git LFS 管理的二进制大文件。构建发布包前必须先拉取完整 LFS 内容；
> `installer/build.ps1` 会检查关键文件大小，拒绝把 LFS 指针或残缺文件打进安装器。

## 目录结构

```
assets/models/
├─ pretrain/
│  ├─ checkpoint_best_legacy_500.pt   # ContentVec（so-vits-svc 4.1 默认语音编码器 vec768l12）~1.2 GB
│  ├─ rmvpe.pt                        # RMVPE F0 预测器 ~351 MB
│  ├─ fcpe.pt                         # FCPE F0 预测器（可选）~66 MB
│  ├─ nsf_hifigan/                    # NSF-HiFiGAN 声码器
│  │  ├─ config.json
│  │  ├─ model
│  │  └─ NOTICE*.txt
│  └─ pc_nsf_hifigan/                 # DDSP-SVC PC-NSF-HiFiGAN 2025.02
│     ├─ config.json                  # pc_aug=true
│     ├─ model.ckpt                   # 安装时规范命名为 model
│     └─ NOTICE*.txt
├─ seedvc/
│  ├─ campplus_cn_common.bin           # SeedVC 音色编码器
│  ├─ whisper-small/                   # OpenAI Whisper Small 本地快照
│  └─ bigvgan_v2_44khz_128band_512x/  # BigVGAN 44.1kHz 声码器本地快照
├─ uvr/
│  ├─ 5_HP-Karaoke-UVR.pth            # 人声/伴奏分离 ~121 MB
│  └─ UVR-DeEcho-DeReverb.pth         # 去混响 ~213 MB
└─ vocal-enhancement/
   └─ DeepFilterNet/DeepFilterNet/Cache/DeepFilterNet3/checkpoints/
      └─ model_120.ckpt.best           # DeepFilterNet3 神经降噪权重 ~8 MB
```

## 复制 / 安装去向

| 自带文件 | 安装后位置 |
| --- | --- |
| `pretrain/*` | `<安装目录>/engines/so-vits-svc/pretrain/`；其中 `checkpoint_best_legacy_500.pt` / `rmvpe.pt` 也会部署到 RVC，`rmvpe.pt` / `pc_nsf_hifigan` 会离线部署到 DDSP-SVC |
| `seedvc/*` | SeedVC worker 直接读取；RMVPE 与 CampPlus 同时硬链接或复制到 `<安装目录>/engines/seed-vc/checkpoints/` |
| `uvr/*.pth` | `<安装目录>/models/uvr/` |
| `vocal-enhancement/DeepFilterNet/*` | `<安装目录>/models/vocal-enhancement/.local/DeepFilterNet/`（`init_df()` 命中后跳过联网下载） |

缺某个文件时安装器会自动联网下载（底模走 HuggingFace 镜像，UVR 走 audio-separator，DeepFilterNet 走官方缓存）。

## 模型资产检查

在项目根目录执行：

```powershell
python install/model_manifest.py --location source
python install/model_manifest.py --location runtime --strict
```

`source` 检查安装包/源码内的自带模型，`runtime` 检查安装后各引擎实际读取
的位置。默认只检查存在性和最小体积；需要生成或校验自带资产的 SHA-256 时执行：

```powershell
python install/model_manifest.py --write-hashes --location source
python install/model_manifest.py --verify-hash --location source --strict
```

由于部分 runtime 文件会被安装器规范化、改名或来自不同上游快照，runtime
只有在清单单独提供 `runtime_sha256` 时才做哈希比对。哈希校验不会在应用启动
时自动扫描大型权重，以免每次启动都读取数 GB 文件。
