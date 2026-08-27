# 启动与模型推理链路

本文说明 Python 后端和模型运行时的实际启动关系。详细时序图见[启动与推理时序图](archify/xb-svcb-startup-inference.sequence.html)。

## 1. 桌面应用启动

    run.bat
      -> app/.venv/Scripts/python.exe app/main.py
      -> app/main.py
      -> resolve_url()
      -> build_api()
      -> pywebview.create_window(..., js_api=api)
      -> webview.start()

生产模式加载 web/dist/index.html，内置 HTTP server 提供静态资源；--dev 模式则加载 Vite 地址。启动阶段不会把所有模型 checkpoint 加载进主进程。

## 2. 后端装配

build_api() 是组合根，主要负责把路径、存储、模型服务、作品服务、转换服务、编辑器服务、实时服务和插件服务组装到 Api 外观上。Vue 调用的 window.pywebview.api.* 方法最终进入这些应用服务。

FastAPI 是可选入口。用户在应用内手动启动后，Uvicorn 在 GUI 进程后台线程中监听端口；HTTP 路由调用同一个 Api 和同一批应用服务，不会另起一套业务核心。

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
      -> FFmpeg：混音、转码和输出
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
