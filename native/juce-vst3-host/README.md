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

- 首先支持 VST3 效果插件，仅乐器和 MIDI 专用插件不作为编辑器目标。
- 插件架构必须与主机架构匹配，例如 64 位主机搭配 64 位插件。
- `inspect` 只检查请求里指定的插件文件，不做全盘插件扫描；前端负责让用户选择插件路径。
- `render` 用于片段效果链的离线渲染，Python 会把片段音频交给 Host，Host 加载 VST3 后输出处理后的 WAV。
- `show-editor` 会在顶层 JUCE 窗口中打开插件的原生编辑器。该请求会保留一个 `parent_window` 字段，以便未来在 Windows 中嵌入 HWND 时复用相同协议。
- 当编辑器窗口处于打开状态时，主机会定期将插件状态和归一化参数值写入 `state_output` JSON 文件。Python 在会话关闭/同步时读取该文件，并将状态保存到编辑器项目中。
- 插件效果只作为音频编辑器片段效果链使用；局部重推理在 Python 层会使用原始片段裁剪作为模型输入，并在替换片段后移除插件类效果，避免插件处理结果污染 AI 生成的人声。
- 安装器只携带编译好的 `xb-juce-vst3-host.exe`。最终用户安装软件时不需要下载 JUCE SDK，也不需要现场编译 Host。
