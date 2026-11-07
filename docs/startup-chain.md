[简体中文](startup-chain.md) | [English](en/startup-chain.md) | [日本語](ja/startup-chain.md)

# 启动与模型推理链路

本文说明 Python 后端和模型运行时的实际启动关系。详细时序图见[启动与推理时序图](archify/xb-svcb-startup-inference.sequence.html)。

## 1. 桌面应用启动

    run.bat
      -> app/.venv/Scripts/python.exe app/main.py
      -> app/main.py
      -> resolve_url()
      -> app/composition.py: build_api()
      -> pywebview.create_window(..., js_api=api)
      -> webview.start()

生产模式加载 web/dist/index.html，内置 HTTP server 提供静态资源；--dev 模式则加载 Vite 地址。启动阶段不会把所有模型 checkpoint 加载进主进程。

## 2. 后端装配

`app/composition.py` 的 `build_api()` 是组合根：先创建基础设施适配器（FFmpeg、UVR、PyMSS、各引擎、JSON 仓储、主题媒体/音频导入/工作文件/编辑器工程存储、数据目录搬运），
再用它们注入 `app/application/` 的用例服务（作品、转换、模型、编辑器与渲染、实时、插件、媒体、数据维护），最后装成 `api/bridge.py` 的 `Api` 外观。
用例服务只依赖 `application/ports.py` 声明的端口，不再 import 基础设施；Vue 调用的 `window.pywebview.api.*` 方法最终进入这些用例服务。

分层红线与端口清单见[分层架构约束（DDD）](ddd-architecture.md)，由 `app/tests/test_architecture.py` 自动校验。

FastAPI 是可选入口。用户在应用内手动启动后，Uvicorn 在 GUI 进程后台线程中监听端口；HTTP 路由调用同一个 Api 和同一批应用服务，不会另起一套业务核心。

模型 Worker 的 Python 由 `runtime.json` 路由。CUDA126/CUDA128 默认把 UVR、SeedVC、DDSP 路由到 `runtimes/core-*`，把 SVC、RVC、Vocal 路由到 `runtimes/svc-*`；CPU、ROCm 10 和旧安装可以继续路由到 `.venv-*`。Worker 进程隔离不等于依赖隔离，共享层内的组件仍使用同一套已校验依赖。

## 3. 普通翻唱任务

    选择音频和模型
      -> Api Facade
      -> Application Services
      -> 创建任务记录
      -> 进入串行推理队列
      -> UVR Worker：人声分离 / 去混响
      -> EngineRegistry：按 framework 路由
      -> Model Worker：加载 checkpoint 并推理
      -> Vocal Enhancement：按需增强
      -> FFmpeg：按 LUFS 测量平衡人声与伴奏后混音、转码和输出
      -> 保存作品与任务状态
      -> 前端轮询/推送并展示结果

这里的“Model Worker -> FFmpeg”是流程上的先后关系，不代表模型 Worker 进程直接执行 FFmpeg。业务服务负责组织各阶段、传递临时文件并更新任务状态。

## 4. 多模型与编辑器任务

- 多模型任务先解析歌词或时间轴，把片段分配给一个或多个模型。
- 每个模型在自己的引擎环境中生成对应人声，再由应用服务按时间轴合并和交叉淡化。
- 编辑器的局部重推理只重新处理目标片段，随后刷新波形、缓存和工程撤销记录。
- VST3 效果器通过 native/juce-vst3-host 与 Python 音频服务衔接，不进入模型干声推理过程。

## 5. 实时任务

实时模式与普通任务的主要区别是 Worker 生命周期：

    启动实时会话
      -> 常驻 UVR Worker
      -> 常驻 RVC / SeedVC Worker
      -> 读取歌曲文件或 WASAPI/VB-CABLE 音频块
      -> 预缓冲和重叠上下文
      -> 人声转换
      -> 等功率交叉淡化
      -> 保留伴奏并实时播放

系统音频模式限制为单模型，以保证固定块处理和实时延迟可控。文件模式可以登记作品并导出结果。

## 6. 退出流程

app/main.py 的 finally 块会依次停止 API 和后台服务、清空当前用户数据目录的 temp 内容、释放单实例句柄。模型和作品等持久数据不会因正常退出被清除。

运行时目录、安装入口和修复边界见[共享运行时与兼容布局](runtime-consolidation.md)。
