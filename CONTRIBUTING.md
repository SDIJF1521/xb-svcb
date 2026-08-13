# 参与贡献

感谢你愿意改进 XB-SVCB。项目包含桌面应用、Web 前端、多个相互隔离的 AI
运行环境和 Windows 安装器。提交改动前，请先阅读本指南和
[README.md](README.md) 中的架构及源码搭建说明。

## 反馈问题

提交 Issue 前，请先搜索[现有 Issue](https://github.com/SDIJF1521/xb-svcb/issues)，确认问题尚未被报告。

Bug 报告应尽量包含：

- XB-SVCB 版本、Windows 版本和安装方式；
- Python、GPU 型号、显卡驱动及实际使用的推理后端（CPU、DirectML、cu121 或 cu128）；
- 可重复执行的最小步骤、预期结果和实际结果；
- 完整错误信息及相关日志；
- 必要时提供经过脱敏的截图或最小音频样本。

请勿上传 API Key、Cookie、本机绝对路径中的个人信息、受版权保护的完整音频、未获授权的模型或其他敏感数据。安全问题不要公开披露，请通过仓库所有者可用的私密联系方式报告。

功能建议应说明使用场景、期望行为、可接受的替代方案，以及是否会影响现有工程或模型兼容性。较大的功能、架构调整和新引擎接入，建议先通过 Issue 对齐范围，再开始实现。

## 开发环境

项目主要面向 Windows。基础开发需要：

- Git；
- Python 3.10.5 或更高版本；
- [uv](https://docs.astral.sh/uv/)；
- Node.js `^20.19.0` 或 `>=22.12.0`，以及 npm；
- 涉及音频处理时需要 ffmpeg；
- 涉及 VST3 Host 时需要 CMake、支持 C++17 的 Visual Studio Build Tools 和 JUCE；
- 涉及安装包时需要 Inno Setup 6。

克隆自己的 Fork 后，从 `master` 创建主题分支：

```powershell
git clone https://github.com/<你的账号>/xb-svcb.git
cd xb-svcb
git switch -c fix/简短说明
```

只开发桌面后端和前端时，可以安装最小环境：

```powershell
python -m pip install --user --upgrade uv
python install\install.py --only app web
uv pip install --python app\.venv\Scripts\python.exe pytest numpy
```

`app` 步骤创建 `app/.venv`，`web` 步骤使用 `npm ci` 安装锁定依赖并生成
`web/dist`。最后一条命令补充当前测试套件需要、但不属于桌面应用运行时依赖的工具。

如需调试完整推理链路，请在项目根目录运行：

```powershell
.\setup_env.bat
```

该命令会创建多个 `.venv-*` 环境并下载较大的引擎和模型。也可以只安装需要的组件，例如：

```powershell
python install\install.py --only uvr svc
python install\install.py --cpu --only rvc
```

不要在不同引擎之间共用虚拟环境。SVC、RVC、SeedVC、DDSP-SVC、UVR、
Vocal 和 Hub 的依赖与 GPU 栈彼此隔离，这是项目运行稳定性的必要条件。

## 本地运行

前端可以独立使用 mock API 开发：

```powershell
cd web
npm run dev
```

需要同时调试 pywebview Bridge 时，保持 Vite 服务运行，并在另一个终端执行：

```powershell
app\.venv\Scripts\python.exe app\main.py --dev
```

生产资源模式需要先运行 `npm run build`，再执行根目录的 `run.ps1` 或 `run.bat`。

## 项目结构

- `app/api/`：pywebview Bridge 与 FastAPI 表现层；
- `app/application/`：业务用例和服务编排；
- `app/domain/`：实体、枚举和领域数据结构；
- `app/infrastructure/`：存储、音频、引擎和系统集成；
- `app/tests/`：Python 单元测试与回归测试；
- `web/src/`：Vue 3、Pinia、Element Plus 前端；
- `install/`：依赖解析、隔离环境和离线资源准备；
- `installer/`：PyInstaller、Inno Setup 和发布校验；
- `native/juce-vst3-host/`：JUCE VST3 Host；
- `docs/`：外部 API 等专题文档。

保持依赖方向清晰：表现层调用应用层，应用层组织领域逻辑，基础设施实现外部系统能力。桌面 Bridge 与 HTTP API 应复用同一业务服务，不要复制业务规则。前端对桌面能力的调用应继续通过 `web/src/api/` 的统一入口，并保留浏览器 mock 行为。

## 编码约定

- 遵循相邻代码已有的命名、类型标注和组织方式，保持改动聚焦；
- Python 使用 4 个空格缩进；TypeScript、Vue 和 C++ 遵循对应目录的现有风格；
- 为非显然的兼容逻辑补充简短注释，避免重复描述代码；
- 用户可见文案、错误信息和文档使用清晰一致的中文；
- `.bat` 文件保持 CRLF，其他文件遵循仓库现有行尾；
- 修改依赖时同步提交 `app/uv.lock` 或 `web/package-lock.json`；
- 自动生成的前端类型声明只在确有变化时提交；
- 不要顺便格式化或重构与当前问题无关的文件。

仓库目前没有统一的 lint 命令。不要在 PR 中声称已通过不存在的 lint 流程；请至少完成下述类型检查、构建和相关测试。

## 测试

Python 全量测试：

```powershell
app\.venv\Scripts\python.exe -m pytest app\tests
```

开发时可以只运行相关文件或用例：

```powershell
app\.venv\Scripts\python.exe -m pytest app\tests\test_http_api.py -q
app\.venv\Scripts\python.exe -m pytest app\tests -k "seedvc" -q
```

前端测试、类型检查和生产构建：

```powershell
cd web
npm run test:unit -- --run
npm run type-check
npm run build
```

按改动范围增加验证：

- Bridge 或 HTTP API 改动应覆盖成功、校验失败、鉴权和路径信息泄漏场景；
- 推理改动应覆盖 CPU，并在声称支持的硬件上验证对应 GPU 后端；
- 音频算法改动应使用可再分发的最小样本，并检查静音、削波、非有限值、声道和采样率；
- 安装器改动应至少运行 `.\installer\build.ps1 -ValidateOnly`；
- VST3 Host 改动应重新构建原生程序，并使用兼容与不兼容插件验证回退路径；
- UI 改动应在桌面 pywebview 和浏览器开发模式中检查，覆盖项目支持的最小窗口尺寸。

无法执行的硬件或集成测试必须在 PR 描述中明确列出，不要把 mock 测试描述为真实 GPU 或真实模型验证。

## 提交规范

提交信息使用简短、明确的中文或英文，描述一次逻辑改动，例如：

```text
修复 SeedVC 参考音频路径校验
test: cover expired API key rejection
```

一个提交尽量只解决一个问题。提交前检查：

```powershell
git status --short
git diff --check
```

不要提交以下内容：

- `.venv*`、`node_modules`、`web/dist`、`build`、本地缓存或日志；
- 用户数据目录、作品、测试输出和调试音频；
- 未经项目维护者确认的大模型、引擎副本或安装包分卷；
- API Key、令牌、Cookie、个人数据或其他凭据。

模型与离线资产可能使用 Git LFS。修改 `assets/models/` 前请先确认许可证、来源、体积和发布方式，不要用占位文件或损坏的 LFS 指针替换现有资产。

## Pull Request

向 `master` 提交 Pull Request，并在描述中包含：

- 变更目的和实现方式；
- 关联的 Issue；
- 实际执行的测试命令及结果；
- 未验证事项和已知风险；
- UI 改动的前后截图，或音频改动的可复现评估方式；
- 依赖、数据格式、API、安装流程或硬件兼容性的变化。

PR 应保持可审查的体积，并包含行为改动对应的测试和文档。评审意见处理后，请避免无关的强制推送或历史重写。

普通功能和修复 PR 不要自行修改版本号或新增发布说明。发布时版本必须在
`app/config.py`、`app/pyproject.toml`、`app/uv.lock`、`web/package.json`、
`web/package-lock.json`、安装器版本资源与 Inno Setup 脚本之间保持一致，由发布改动统一完成。

## 许可证

提交代码即表示你有权按本项目的 [GPL-3.0](LICENSE) 许可证提供该贡献。引入第三方代码、模型、数据或二进制文件时，必须保留必要的版权和许可证信息，并确认其许可证与项目及分发方式兼容。
