# XB JUCE VST3 Host（VST3 插件主机）

这是音频编辑器外部效果器链的本地 C++ 主机，负责 VST3 插件检查、离线渲染、打开插件原生 GUI，并把插件 state 回写给 Python 编辑器服务。

运行时链：

```text
Python（业务逻辑、AI、编辑器界面）
  -> C++（JUCE VST3 Host）
  -> VST3 Plugin GUI（插件原生窗口）
```

Python 桥接器会使用一个 JSON 请求文件来调用此可执行文件：

```text
xb-juce-vst3-host inspect <request.json>
xb-juce-vst3-host render <request.json>
xb-juce-vst3-host show-editor <request.json>
```

支持的请求方案：`xb-svcb.juce-vst3-host.v1`，协议 `1`。

## 构建

安装 CMake、C++17 编译器和 JUCE，然后运行：

```powershell
$env:XB_JUCE_DIR="C:\path\to\JUCE"
.\native\juce-vst3-host\build.ps1
```

可执行文件写入到：

```text
engines/juce-vst3-host/xb-juce-vst3-host.exe
```

这是 `app/config.py` 使用的默认路径。你也可以通过以下方式覆盖它：

```powershell
$env:XB_JUCE_VST3_HOST="C:\path\to\xb-juce-vst3-host.exe"
```

如果你没有本地的 JUCE 检出版本，构建脚本可以请求 CMake 来获取它：

```powershell
.\native\juce-vst3-host\build.ps1 -FetchJuce
```

如果上一次下载被中断，出现 `Failed to remove directory ... build/_deps/juce-src`，先清理 JUCE 下载缓存再重试：

```powershell
.\native\juce-vst3-host\build.ps1 -FetchJuce -CleanFetch
```

## 兼容性

- 当前仅编译并支持 64 位 Windows VST3 音频效果器；插件文件可以位于请求指定的任意目录，不依赖固定扫描目录。
- VST2 `.dll`、32 位插件、CLAP、AAX、AU 和需要 MIDI 音符驱动的 VST3i 乐器不在当前 Host 的人声音频处理范围内。外部侧链和特殊多总线布局是否可用取决于插件实现。
- 插件架构必须与主机架构匹配，例如 64 位主机搭配 64 位插件。
- `inspect` 只检查请求里指定的插件文件，不做全盘插件扫描；前端负责让用户选择插件路径。
- `render` 用于片段效果链的离线渲染，Python 会把片段音频交给 Host，Host 加载 VST3 后输出处理后的 WAV。
- `show-editor` 会在可调整大小的顶层 JUCE 窗口中打开插件原生编辑器；窗口保持置顶，主应用重新获得焦点时不会隐藏或结束插件会话。该请求保留 `parent_window` 字段，以便未来嵌入 Windows HWND 时复用相同协议。
- 播放期间状态文件只写传输、设备、峰值和轻量插件信息；暂停后以低频刷新参数值，关闭会话时停止音频回调并抓取完整插件 state，避免状态序列化阻塞音频或 GUI 线程。
- `show-editor` 可接收 `monitor_input`、`bed_input`、`transport_control`、工程时长和片段时间范围。Host 使用 `AudioDeviceManager` 的声卡回调读取两路 WAV，把目标信号送入 GUI 所属的同一个 `AudioPluginInstance::processBlock`，再与底轨混合输出。
- Host 首选请求 `128 samples`，但使用声卡驱动最终接受的实际缓冲和采样率；不同采样率之间在回调内转换，状态文件会报告设备名、块大小、延迟、播放位置、峰值和 xrun。
- 插件实例按实际声卡格式首次创建，窗口进入消息循环并完成首轮初始化后才启动音频设备。每次 `processBlock` 使用本次回调的有效样本视图，不把内部预分配容量当成插件块大小。
- GUI 插件实例绑定 `AudioPlayHead`，处理块内可读取播放/暂停、样本与秒位置、BPM、拍号、PPQ 和小节起点；依赖宿主传输的频谱历史、时间曲线和节拍同步插件可以正常刷新。
- 控制协议使用独立 `output_enabled` 开关。前端确认原生握手后才开启可听输出；HTML Audio 回退仍可只驱动插件仪表，不会与 JUCE 重复发声。
- Python 会话桥保证 `output_enabled` 全局独占：激活一个会话时立即关闭其他会话的声卡输出，其他插件仍可接收同步音频用于 GUI 仪表。
- 乐器/MIDI、零输入或零输出插件不会作为音频效果器接管输出，离线 `render` 也会拒绝生成静音文件。有效效果器连续有输入但无输出超过延迟保护窗口，或返回非有限采样时，实时回调自动使用干声保护并在状态文件中报告 `safety_bypassed`。
- 插件效果只作为音频编辑器片段效果链使用；局部重推理在 Python 层会使用原始片段裁剪作为模型输入，并在替换片段后移除插件类效果，避免插件处理结果污染 AI 生成的人声。
- 安装器只携带编译好的 `xb-juce-vst3-host.exe`。最终用户安装软件时不需要下载 JUCE SDK，也不需要现场编译 Host。
