# 测试分组与验收边界

从项目根目录运行。测试工具和 SciPy 使用 uv 临时叠加环境，不往主程序环境安装 Torch：

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
```

缓存齐备后可加 `--offline`。`-rs` 显示每个跳过原因；测试退出成功不等于真实推理或发布验收通过。

## 分组

| 标记 | 内容 | 选择方式 |
| --- | --- | --- |
| `runtime` | 配方、路由、worker、音频处理辅助逻辑；不是完整模型推理 | `-m runtime` |
| `installer` | Python 探测、安装/修复保护等 | `-m installer` |
| `packaging` | 离线打包计划及打包规则 | `-m packaging` |
| `packaging_integration` | 使用项目真实引擎 requirements 的打包计划检查 | `-m packaging_integration` |
| `model_inference` | 为真实权重/音频验收预留的标记，默认不执行 | `-m model_inference --run-model-inference` |

最后一组目前没有自动化验收用例；空集合不是通过。手工真实推理已按用户要求暂缓。
其余业务/API 测试仍留在全套测试中，不强行归入运行时或安装测试。

例如，只跑打包单元测试：

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest -m "packaging and not packaging_integration" -q -rs
```

## 之前四项失败的处理

- Python 探测两项：移除了不可靠的 `if exist "python.exe\"` 目录判断。
  本机 C 盘的有效 Python 可错误命中此判断。现在实际执行版本探针，目录/非 Python 程序仍拒绝。
  原有正例与失效路径回退测试保留，补充目录名为 `python.exe` 的反例。
- 原来的两个打包断言移至 `test_wheelhouse_plan.py`，使用临时引擎 requirements，原有版本/隔离断言保留。
  生成的中间 requirements 放在对应测试根目录，不改写上游文件。
- 另有一个真实源码集成检查：缺少 SVC/SeedVC/DDSP requirements 时列出组件及绝对路径并跳过。
  不将缺输入解释成模型依赖失败，也不删除覆盖范围。

发布检查必须强制要求输入齐备：

```powershell
uv run --project app --with pytest pytest -m packaging_integration --require-packaging-inputs -q
```

此模式下缺文件会失败，不能靠跳过获得发布绿灯。它仍只是打包计划检查，不是 Inno 编译或全新安装验收。

## 2026-08-29 回归记录

全套：330 通过、15 跳过、0 失败；有一个 Starlette/httpx 弃用提示，未修改无关依赖。
15 项跳过为 14 项当前测试解释器缺少 Torch 的辅助逻辑测试，以及 1 项缺 SVC requirements 的打包集成检查。
真实共享环境包含 Torch/CUDA，不能把这里的跳过解释为没有显卡。

随后使用现有模型环境补跑了设备辅助测试，30 项全部通过，包含上述 14 个跳过项：

```powershell
uv run --offline --no-project --python .venv-uvr/Scripts/python.exe --with pytest python -B -m pytest app/tests/test_inference_devices.py -q -rs
```

pytest 放在临时叠加环境，不往共享环境安装工具，也不下载 Torch。这不是模型权重推理。

固定配方的整体解析、已安装版本对比、14 个本地 wheel 哈希均已验证。
随后继续安装/存储验证，新增 `test_install_validation.py` 的 18 项回归，全套为 **348 通过、15 跳过、0 失败**；使用共享解释器补跑设备辅助测试仍为 30 项全部通过。

独立临时环境中已实测四包离线安装、重复安装、回滚和恢复配方（使用 `--no-deps`，只证明四包部署行为）。147 包全新安装在当前 uv 未命中 torchvision 缓存处停止；没有将其标为通过。真实模型音频、安装包编译和旧环境清理未执行。详见 [安装与修复验证](runtime-install-validation.md) 和 [空间盘点](runtime-storage-audit.md)。

继续解决缓存后：全套 **362 通过、15 跳过、0 失败**。新增 13 项缓存恢复安全测试、1 项安装器不依赖调用方 `sys.path` 的测试。
上述缓存阻塞已解决：147 包在新空环境中正常解析安装、重复安装和精确版本核对均通过；在完整环境内注入旧四包时检测出预期的 3 项冲突，完整配方修复只改四包，其余包（含 Torch）元数据未变。随后 5 项导入/CUDA 检查与 5 项兼容性探针通过。真实音频推理、安装 EXE 全流程与旧文件清理仍未执行。

在本轮新建的完整环境中，设备辅助测试另行补跑 30 项通过；安装器固定配方预检在 `UV_OFFLINE=1` 下再次通过。
