# 开发与发布

## 推荐工作流

    安装源码环境
      -> 修改 app / web
      -> 运行 Python 和前端测试
      -> 构建 web/dist
      -> 启动桌面应用验证 Bridge
      -> 验证 FastAPI、模型和 Worker
      -> 构建 JUCE Host（需要时）
      -> 执行发布校验
      -> 构建 Inno Setup 安装包

## 后端开发

主程序依赖定义在 app/pyproject.toml，运行时入口是 app/main.py。建议从 app/api/bridge.py 和 app/application/ 开始阅读业务调用，再进入 app/infrastructure/ 查看具体引擎和 Worker。

运行测试：

    cd app
    uv run pytest

重点测试范围包括模型服务、推理回归、设备探测、HTTP API、实时翻唱、编辑器、插件和安装器运行时。

## 前端开发

    cd web
    npm install
    npm run dev
    npm run type-check
    npm run build
    npm run test:unit -- --run

前端构建输出为 web/dist。生产桌面应用会把这个目录作为内置资源加载。

## JUCE VST3 Host

设置 JUCE 路径并构建：

    $env:XB_JUCE_DIR="C:\path\to\JUCE"
    .\native\juce-vst3-host\build.ps1

产物应位于 engines/juce-vst3-host/xb-juce-vst3-host.exe。更多限制和插件兼容说明见安装器说明。

## 安装包构建

轻量校验：

    .\installer\build.ps1 -ValidateOnly

完整构建：

    .\installer\build.ps1

构建流程大致为：

1. 校验应用、前端、版本号和关键运行载荷。
2. 构建 Vue 前端。
3. 使用 PyInstaller 生成桌面应用及其内置资源。
4. 构建或复用 JUCE VST3 Host。
5. 准备离线模型、wheelhouse 和运行环境载荷。
6. 使用 Inno Setup 生成 XB-SVCB-Setup.exe 和多个小于 2GB 的 .bin 分卷。

发布时必须同时上传 EXE 和全部 BIN 文件。安装器说明、运行环境列表和分卷规则见 installer/README.md。

## 文档维护约定

- 根 README 只放项目概览、快速开始和文档链接。
- API 细节只维护在 docs/api.md。
- 插件内容优先维护在 docs/plugins/，旧版单文件指南仅作兼容和全文搜索。
- 架构源数据放在 docs/archify/*.json，HTML 是可交付查看产物。
- 版本更新说明统一放在 docs/release-notes/release_notes_vXYZ.md，README 只链接当前版本。
- 修改启动流程、目录结构、环境名称或 API 合同时同步更新对应文档。
