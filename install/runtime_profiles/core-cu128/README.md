# core-cu128 固定实验配方

适用范围：Windows x86_64、CPython 3.10、Torch 2.7.1+cu128，UVR / SeedVC / DDSP 共享环境。
已验证 uv 0.12.5。必须支持 `uv pip compile/install --torch-backend cu128`。
真实模型音频验收暂缓，仍是实验配方。本机完整 147 包空环境安装、重复安装与模拟修复已通过；不等同于发布验收或安装 EXE 全流程验收。

## 保存了什么

- `requirements.lock`：全部精确版本，不包含机器绝对路径。现有 146 个包均与此一致。
- `profile.json`：锁文件 SHA-256、14 个本地 wheel 的路径/大小/SHA-256，以及验收和回滚限制。
- `assets/runtime/core-cu128/compat/`：本地 AudioTools 兼容 wheel 和六个已构建的辅助 wheel。
- `assets/runtime/core-cu128/candidate/`：这次迁移使用的 NumPy、protobuf、TensorBoardX 三个新版 wheel。
- `assets/runtime/core-cu128/rollback/`：四个迁移前 wheel。只用于恢复原版本，不是完整虚拟环境备份。

二进制 wheel 不提交 Git；本机已从临时目录校验复制，原件未删除。请将
`assets/runtime/core-cu128/` 随自己的备份保存。Inno 配置会在该目录存在时携带这些材料，
但本轮没有编译或发布新安装包。仅克隆源码不会获得这些二进制材料。
缺失时 `--core-profile` 会明确拒绝执行；不得通过删除哈希检查绕过。

锁文件共有 147 项：比现有环境多出的 `hf-xet==1.6.0` 是下载传输辅助包。
本机 `platform.machine()` 返回 `AMD64`，上游依赖标记使用小写，目标平台解析则包含该依赖。
因此固定其版本供新安装使用，但现有 HTTP 下载路径可缺少它；校验结果会单列 `missing_optional`。
这不是第二套模型运行配方，也不会为通过校验自动安装它。

固定版本不等于完整离线 wheelhouse：没有保存全部 147 个包的 wheel，尤其没有另外下载 Torch。
来源于仓库的依赖仍需对应版本可获取；只有上述 14 个本地材料做了逐文件哈希固定。

早期验证曾通过 `install/validate_core_install.py --recover-cache ... --wheel-dir ...` 复用既有下载和旧缓存。缓存包只有在 RECORD 校验通过后才允许在独立临时目录重封装；这不等于取得上游原始 ZIP 的哈希认证，也不会自动成为长期发布材料。当前激活、验证与修复边界见 [共享运行时与兼容布局](../../../docs/runtime-consolidation.md)。

## 校验（不安装、不下载）

在项目根目录执行：

```powershell
.\app\.venv\Scripts\python.exe -B install\core_recipe.py --python runtimes\core-cu128\Scripts\python.exe
```

先检查锁文件和全部本地材料，再比较解释器、平台和已安装包版本。
缺包、版本变化、额外包或哈希不匹配都会报错。它不取代 `uv pip check`、导入检查或真实推理。

## 安装器预检入口

```powershell
.\app\.venv\Scripts\python.exe -B install\install.py --consolidated --cu128 --only uvr seedvc ddsp --core-profile core-cu128 --preflight-only
```

此命令验证兼容材料，读取当前上游 requirements，带上全部固定版本进行整体解析，
并检查结果没有缺项、新增项或版本漂移。Torch 使用专用 `--torch-backend cu128`，
普通依赖不再被 PyTorch 通用索引上的旧版本遮蔽。后续安装也使用同一来源规则和解析约束。

仅生成的中间约束位于 `.tmp/core-cu128.constraints.txt`，可以重新生成；
长期配方和兼容材料不依赖 `.tmp`。预检可能读取联网元数据，不安装依赖或模型。
设置 `$env:UV_OFFLINE="1"` 可禁止联网，但首次运行可能因缓存不足失败。
不要在尚未准备好下载/安装时移除 `--preflight-only`。

`--core-compat-wheel` 保留用于开发其他候选构建，它不承诺全部精确版本；
日常复现本配方使用 `--core-profile core-cu128`，两者互斥。
未选择任何配方时仍按原始上游要求解析，冲突会停止。

## 离线重建 AudioTools

无需安装原版依赖，只需保存的原版 wheel：

```powershell
.\app\.venv\Scripts\python.exe -B install\build_core_compat.py --source-wheel assets\runtime\core-cu128\rollback\descript_audiotools-0.7.2-py2.py3-none-any.whl --output-dir assets\runtime\core-cu128\compat
```

构建器先验证源 RECORD；只改本地版本、protobuf/TensorBoard 依赖声明及来源记录，保留许可。
输入可来自 wheel 或原版 site-packages，来源摘要不包含安装器追加的 RECORD 行，因此可重建一致结果。
不会覆盖同名但内容不同的 wheel。

当前输出 SHA-256：`22eb8ec9db1c52a16ed3c2202f61b02ba9249c3038066e06097a1912ac1d8b27`。
早期临时构建的摘要为 `10099d81d610a6c5ea48cc47798c60c4879fc2e987e12d434b21112b0dcae429`。
两者功能文件相同；区别是来源记录改为可重复构建的格式及 RECORD 校验行。
当前已安装包没有因此重装，其 `direct_url.json` 可能仍记录历史临时路径，该路径不参与运行导入。

## 回滚边界

原版四包为 NumPy 1.26.4、protobuf 3.19.6、TensorBoardX 2.6、AudioTools 0.7.2。
**该历史状态本身存在 UVR MDX 依赖冲突，不能称为已验证健康回退点。**
恢复四包不能恢复整个环境，也不能只删除 `runtime.json` 就撤销包修改。
当前不执行回滚，不删除旧环境。确需恢复历史状态时：

1. 停止应用和推理 worker，另行备份当前环境/路由；用上面的校验命令确认材料未损坏。
2. 只使用 `rollback/` 中四个精确文件，显式指定目标环境：

```powershell
uv pip install --python runtimes\core-cu128\Scripts\python.exe --no-index --no-deps assets\runtime\core-cu128\rollback\numpy-1.26.4-cp310-cp310-win_amd64.whl assets\runtime\core-cu128\rollback\protobuf-3.19.6-cp310-cp310-win_amd64.whl assets\runtime\core-cu128\rollback\tensorboardX-2.6-py2.py3-none-any.whl assets\runtime\core-cu128\rollback\descript_audiotools-0.7.2-py2.py3-none-any.whl
```

3. 重新检查依赖/导入并单独处理解释器路由，不宣称恢复后所有组件可用。

这里的 `--no-deps` 仅用于明确恢复这四个历史版本，避免触碰 Torch；
绝不用于安装当前共享配方或掩盖依赖冲突。回滚动作未在当前共享环境执行验证。
