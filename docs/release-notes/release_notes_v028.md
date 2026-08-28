## v0.0.28 · 插件平台、宿主扩展与安装器修复

> 本次更新把完整插件平台、TypeScript/Python SDK、自定义页面宿主能力、GitHub 插件市场、安装器环境修复和 FFmpeg 回退统一归入 **v0.0.28**。重点是让插件能够以可审计的清单、独立开关和受控宿主 API 扩展 XB-SVCB，同时提高全新安装、环境修复与覆盖升级的稳定性。

> [!IMPORTANT]
> Python 和混合插件会以当前用户权限执行真实代码，独立 Worker 只提供崩溃与超时隔离，不是权限沙箱。请只安装可信来源的 `.xbplugin`；前端自定义页面继续运行在 `sandbox="allow-scripts"` iframe 中。

### 🧩 插件中心与 GitHub 市场

- 新增完整插件中心，提供插件总开关、单插件独立开关、已安装数量、权限与运行类型展示、打开页面、卸载和安全提示；新安装插件默认关闭，不会在用户确认前接入工作流。
- “安装本地插件包”会调用文件选择器读取 `.xbplugin` 或 `.zip`，校验清单、包大小、解压边界、入口路径和权限后安装到用户数据目录中的独立插件目录。
- 插件市场兼容 NoneBot2 风格 `plugins.json5` 索引，可配置 GitHub HTTPS raw/API 地址，展示作者、版本、标签、主页和运行类型，并从受信任的 GitHub 地址下载安装包。
- 插件市场、启用、安装、卸载和动作结果统一使用符合当前主题的 Element Plus 通知，不再在页面底部显示临时文本提示。

### 🐍 前端、Python 与混合运行时

- 插件清单支持 `frontend`、`python` 和 `hybrid` 三种运行类型，以及页面、字段、动作、权限、前端入口、Python 入口和 `before_create` 工作流补丁。
- Python/混合插件通过独立 Worker 导入入口，支持动作、`before_create` 钩子和 `on_enable` / `on_disable` 生命周期；插件 ID、入口目录和动作注册会在执行前校验，单次调用超过 30 秒会终止。
- 插件代码与数据分离保存到 `plugins/<plugin-id>` 和 `plugin-data/<plugin-id>`；替换安装同 ID 插件时保留数据目录，卸载时按安全边界清理插件内容。
- 打包版本包含零依赖 Python SDK、插件 Worker 和可用的插件 Python 解释器回退策略，源码与安装版都能运行可信的 Python 插件。

### 🖥️ 自定义页面与宿主 Client

- 自定义 HTML/Vue 页面通过 `srcdoc` 沙箱加载，支持读取上下文、运行插件动作、创建翻唱任务、读取包内资源和显示宿主通知；消息使用 token、请求 ID、来源检查和结构化克隆。
- 新增按插件 ID 隔离的页面持久化 API：`getStorage()`、`setStorage()` 和 `removeStorage()`，可保存 API key、来源选择和普通 JSON 偏好，不再依赖 opaque-origin iframe 的 localStorage。
- 新增插件内容全屏、软件窗口全屏、宿主全屏状态事件和始终可见的退出按钮；`Escape` 可结束宿主播放器或插件全屏。
- 新增受限的妖狐 M3U8 宿主播放器弹层。它只接受声明了 `network` 权限的 `m3u8.yaohud.cn` 地址并自动升级为 HTTPS，避免第三方播放器在插件沙箱中一直停在初始化状态。
- 插件页面扩大可用区域并优化“返回插件中心”按钮、加载状态和主题适配，紧凑页面与全屏页面都使用稳定尺寸，避免播放器或动态内容挤压布局。

### 🧰 Plugin SDK 与开发文档

- 新增 TypeScript 优先的清单构建器、`xb-plugin create` 脚手架、清单校验和 `.xbplugin` 打包 CLI，并提供无框架 Client、Vue `usePluginHost()` 与完整类型声明。
- 新增零依赖 Python SDK，提供动作、钩子、生命周期、上下文、配置和数据目录 API；前端、Python 和混合三类示例均可独立构建与打包。
- 插件文档拆分为快速开始、Vue 页面、清单与动作、Client API、Python、混合插件、测试调试、GitHub 市场发布和 API 速查，并同步记录持久化、全屏、播放器和沙箱限制。
- `.gitignore` 增加插件包、示例构建产物、插件虚拟环境及用户插件目录规则，减少本地测试产物误提交。

### 🛠️ 安装器、Python 与 FFmpeg 修复

- 环境搭建会优先识别并验证本机 Python 3.10 路径，统一检查各虚拟环境的解释器版本；环境缺失、不可运行或版本不匹配时会自动重建，避免 uv 缓存解释器与目标环境错配。
- So-VITS-SVC 补齐 Matplotlib 的 `contourpy`、`cycler`、`fonttools`、`kiwisolver`、`packaging`、`Pillow`、`pyparsing` 和日期依赖，并在环境就绪前执行真实导入校验。
- AI 歌声增强环境移除不需要的运行期 `wheel`，解决 `deepfilternet` 对 `packaging<24` 与新版 wheel 对 `packaging>=24` 的解析冲突。
- 修复安装路径或命令参数包含 `%`、`^` 等批处理特殊字符时的转义问题，并扩展安装器回归测试。
- 修复系统未安装 FFmpeg 时安装器错误跳过随包 FFmpeg 的问题；安装前只检查系统 PATH，缺失时正常释放内置 `ffmpeg` / `ffprobe`，安装后继续配置 `XB_FFMPEG_DIR`、`FFMPEG_HOME` 和 PATH。

### 📦 升级与数据兼容

- v0.0.28 继续使用分卷安装包。请把 `XB-SVCB-Setup.exe` 与同版本全部 `XB-SVCB-Setup-*.bin` 放在同一目录后运行。
- 安装目录携带 `README.md`、`release_notes_v028.md` 与 `docs/api.md`；作品、模型、编辑工程、主题、API 设置和插件数据继续沿用原用户数据目录。
- 应用本体、Python 项目、前端包、两份锁文件、Windows EXE 版本资源、Inno Setup、安装器文档和 API 文档统一同步为 **v0.0.28**。

### ✅ 验证

- Python 插件服务、安装器运行时和 PyPI 回退相关测试：**34 passed**。
- Plugin SDK 单元测试：**4 passed**；TypeScript 类型检查通过，SDK 发布包 dry-run 包含 Client、Vue 类型和 README。
- Vue TypeScript 类型检查和 Vite 生产构建通过；插件自定义页面脚本、清单校验和测试插件打包通过。
- installer/build.ps1 -ValidateOnly 通过，Inno Setup 校验编译成功并显示 **Release version: 0.0.28**。

