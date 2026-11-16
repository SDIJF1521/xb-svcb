[简体中文](testing.md) | [English](en/testing.md) | [日本語](ja/testing.md)

# 测试分组与验收边界

从项目根目录运行。测试工具和 SciPy 使用 uv 临时叠加环境，不往主程序环境安装 Torch：

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
```

缓存齐备后可加 `--offline`。`-rs` 显示每个跳过原因；测试退出成功不等于真实推理或发布验收通过。

## 分层与领域规则专项测试

架构改动、规则下沉或新增端口时必须同时跑这一组（它们把分层依赖方向、端口契约、
领域规则钉成断言）：

```powershell
uv run --project app --with pytest pytest app/tests/test_architecture.py app/tests/test_composition.py \
    app/tests/test_domain_entities.py app/tests/test_domain_editor_rules.py \
    app/tests/test_work_request.py app/tests/test_data_maintenance.py -q
```

- `test_architecture.py`：AST 检查各层 import 方向、唯一组合根、端口与适配器契约、
  表现层不访问门面私有成员；
- `test_composition.py`：在隔离数据目录里跑一次 `composition.build_api()`，确认装配完整；
- `test_domain_entities.py` / `test_domain_editor_rules.py`：实体映射、流水线步骤、
  编辑器归一化与歌词时序规则；
- `test_work_request.py` / `test_data_maintenance.py`：任务请求校验规则、数据目录切换与迁移。

规则说明见[分层架构约束（DDD）](ddd-architecture.md)。

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

## 发布验收顺序

历史通过数量容易随新增测试失效，不在文档中固化。每次发布按当前代码重新执行：

1. 运行全套 Python 测试并查看所有跳过原因。
2. 强制运行 `packaging_integration`，禁止因为缺 requirements 而跳过。
3. 运行 `installer/build.ps1 -ValidateOnly`，校验五种 Inno 配置和共享入口。
4. 构建目标硬件包，在全新目录完成 Setup.exe 安装、运行时创建和最终 Torch 校验。
5. 在目标 CPU、ROCm 10、DirectML、CUDA126、CUDA128 设备上分别执行真实模型与短音频验收；DDSP DirectML 实验输出还需试听。

共享配方的解析、原子激活、修复和回滚边界见 [共享运行时与兼容布局](runtime-consolidation.md)。自动化通过只说明代码层和打包规则满足断言，不等于真实模型推理或五类硬件都已验收。
