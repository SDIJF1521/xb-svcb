; ============================================================
;  XB-SVCB · AI 翻唱工具  安装脚本（Inno Setup 6+）
;
;  编译方式（开发者侧）：
;    1) 先构建前端：在 web/ 执行 npm ci && npm run build
;    2) 再用 PyInstaller 打出应用 exe：pyinstaller installer/xb-svcb-app.spec（产物 dist/XB-SVCB/）
;       （以上两步可用 installer/build.ps1 一键完成）
;    3) 安装 Inno Setup（含 ISCC.exe）：https://jrsoftware.org/isinfo.php
;    4) 用 ISCC 编译本脚本；未传宏时默认生成 CUDA128 共享运行时包
;
;  安装器在用户机上的行为：
;    - 释放打包好的应用本体 XB-SVCB.exe（前端与 worker 已内置，无需 Python 也能起界面）
;    - 可选“搭建运行环境”：CUDA126/128 创建两层共享环境，ROCm 10 共享 SVC 组，CPU/DirectML 使用隔离环境
;    - 创建开始菜单与桌面快捷方式（指向 XB-SVCB.exe）
;
;  用户机前置：安装器只检测缺失的 Python/Git/C++ Build Tools/CUDA Toolkit，
;  FFmpeg 由安装包分卷内置（检测到系统 ffmpeg 时跳过释放）；uv 会在 Python 可用后
;  自动安装到用户目录；其他依赖提供跳转官方/可信下载页面的按钮。
;  JUCE VST3 Host 是发布包内置的原生组件，不在用户机现场编译。
;  NVIDIA 前置 CUDA 版本固定：50 系使用 CUDA 12.8，50 系以下使用 CUDA 12.6；
;  AMD/CPU 不显示 CUDA 前置项。PyTorch/PyMSS wheel 的内部栈名与此显示版本分开管理。
;  应用界面本身由 exe 自带，无需 Node / Python。
; ============================================================

#define MyAppName "XB-SVCB"
#define MyAppShort "XB-SVCB"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "XB-SVCB"
#define MyAppExe "XB-SVCB.exe"
#ifndef XB_PACKAGE_STACK
  #define XB_PACKAGE_STACK "cu128"
#endif
#ifndef XB_OUTPUT_BASENAME
  #define XB_OUTPUT_BASENAME "XB-SVCB-Setup-CUDA128"
#endif

[Setup]
AppId={{B9C2F4E7-1A3D-4E6B-9C8A-2F5D7E1B3A40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
AppPublisher={#MyAppPublisher}
LicenseFile=..\LICENSE
; 默认装到用户可写目录，避免在 Program Files 内建 venv / 下模型需要管理员权限
DefaultDirName={localappdata}\Programs\{#MyAppShort}
DefaultGroupName={#MyAppShort}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 显式展示「选择安装位置」页，允许用户自定义安装路径（exe 与全部依赖都装到此目录）
DisableDirPage=no
UsePreviousAppDir=yes
DirExistsWarning=auto
DisableProgramGroupPage=auto
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename={#XB_OUTPUT_BASENAME}
; 自带模型超过单个安装文件上限，显式输出 bootstrapper + 小于 2GB 的分卷数据文件。
; 发布时 XB-SVCB-Setup.exe 与所有 XB-SVCB-Setup-*.bin 必须放在同一目录。
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
; 安装器与卸载项图标
SetupIconFile=..\web\public\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
; Vendor non-English language files so release builds do not depend on the
; optional translations installed on a particular build machine.
Name: "zhcn"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ja"; MessagesFile: "languages\Japanese.isl"

[CustomMessages]
zhcn.CreateDesktopIcon=创建桌面快捷方式
en.CreateDesktopIcon=Create a desktop shortcut
ja.CreateDesktopIcon=デスクトップにショートカットを作成する
zhcn.AdditionalIcons=快捷方式：
en.AdditionalIcons=Shortcuts:
ja.AdditionalIcons=ショートカット:
zhcn.RepairEnvironment=搭建/修复运行环境
en.RepairEnvironment=Set up or repair runtime
ja.RepairEnvironment=ランタイムをセットアップまたは修復
zhcn.UninstallApp=卸载 %1
en.UninstallApp=Uninstall %1
ja.UninstallApp=%1 をアンインストール
zhcn.LaunchApp=立即启动 %1
en.LaunchApp=Launch %1 now
ja.LaunchApp=%1 を今すぐ起動

zhcn.Detected=已检测到
en.Detected=Detected
ja.Detected=検出済み
zhcn.NotDetected=未检测到
en.NotDetected=Not detected
ja.NotDetected=未検出
zhcn.LockedPython=已锁定 %1
en.LockedPython=Selected %1
ja.LockedPython=%1 を選択済み
zhcn.PythonMissing=安装包内置 Python 缺失或不可运行
en.PythonMissing=The bundled Python runtime is missing or not runnable
ja.PythonMissing=同梱 Python ランタイムが見つからないか実行できません
zhcn.OpenDownloadFailed=无法打开下载页面：%1%n请复制链接到浏览器中打开。
en.OpenDownloadFailed=Could not open the download page: %1%nCopy the link and open it in your browser.
ja.OpenDownloadFailed=ダウンロードページを開けませんでした: %1%nリンクをコピーしてブラウザーで開いてください。
zhcn.UvAutoInstallInfo=uv 会使用安装包内置 Python 3.12.x 自动准备，无需手动下载。
en.UvAutoInstallInfo=uv is prepared automatically with bundled Python 3.12.x. No manual download is required.
ja.UvAutoInstallInfo=uv は同梱 Python 3.12.x で自動的に準備されます。手動ダウンロードは不要です。

zhcn.EnvironmentPageTitle=环境检查与前置依赖
en.EnvironmentPageTitle=Environment and prerequisites
ja.EnvironmentPageTitle=環境と前提条件
zhcn.EnvironmentPageSubtitle=先检查运行环境，再选择安装路径
en.EnvironmentPageSubtitle=Check the runtime before choosing the install location
ja.EnvironmentPageSubtitle=インストール先を選択する前にランタイムを確認します
zhcn.EnvironmentSummaryIntro=安装器会先检查运行环境，再进入安装路径选择。当前检测结果：
en.EnvironmentSummaryIntro=Setup checks the runtime before the install location. Current results:
ja.EnvironmentSummaryIntro=インストール先を選択する前にランタイムを確認します。現在の結果:
zhcn.BundledFfmpegHint=（未检测到时使用安装包内置版本）
en.BundledFfmpegHint= (the bundled version will be used if missing)
ja.BundledFfmpegHint= (未検出の場合は同梱版を使用します)
zhcn.UvHint=（安装时自动准备；不会托管 Python）
en.UvHint= (prepared automatically during setup; Python is not managed)
ja.UvHint= (セットアップ中に自動準備されます。Python は管理しません)
zhcn.VbCableHint=（系统音频变声可选，未安装时请手动安装）
en.VbCableHint= (optional for system-wide voice conversion; install manually if needed)
ja.VbCableHint= (システム音声変換では任意です。必要な場合は手動でインストールしてください)
zhcn.JuceBundled=随安装包内置，安装后检查
en.JuceBundled=Bundled; verified after installation
ja.JuceBundled=同梱済み。インストール後に確認します
zhcn.PythonSelectionHint=Python 3.12.x 已随安装包提供，无需另外安装或选择。
en.PythonSelectionHint=Python 3.12.x is included with setup; no separate installation or selection is required.
ja.PythonSelectionHint=Python 3.12.x はセットアップに同梱されるため、別途インストールまたは選択する必要はありません。
zhcn.BuildRuntimeOption=安装后立即搭建运行环境（创建 AI 子环境、复制自带模型；仅 Python 依赖需联网，耗时较长）
en.BuildRuntimeOption=Set up the runtime after installation (creates AI environments and copies bundled models; Python packages require internet access and may take time)
ja.BuildRuntimeOption=インストール後にランタイムをセットアップする (AI 環境を作成して同梱モデルをコピーします。Python パッケージにはインターネット接続が必要で時間がかかります)
zhcn.ConfigureEnvironmentOption=配置 PATH / CUDA_PATH / VSINSTALLDIR 等用户环境变量（不安装软件）
en.ConfigureEnvironmentOption=Configure user environment variables such as PATH / CUDA_PATH / VSINSTALLDIR (does not install system software)
ja.ConfigureEnvironmentOption=PATH / CUDA_PATH / VSINSTALLDIR などのユーザー環境変数を設定する (システムソフトウェアはインストールしません)
zhcn.ShowDetailsOption=在安装器窗口显示详细安装信息（可选；完整日志仍会写入安装目录）
en.ShowDetailsOption=Show detailed setup output (optional; the full log is always saved in the install directory)
ja.ShowDetailsOption=セットアップの詳細を表示する (任意。完全なログはインストール先に保存されます)

zhcn.GpuPageTitle=GPU 推理栈
en.GpuPageTitle=GPU inference stack
ja.GpuPageTitle=GPU 推論スタック
zhcn.GpuPageSubtitle=选择本机要使用的推理依赖栈
en.GpuPageSubtitle=Choose the inference stack for this computer
ja.GpuPageSubtitle=このコンピューターで使用する推論スタックを選択します
zhcn.GpuPageDescription=安装器会复核实际显卡：NVIDIA 使用匹配的 CUDA 栈，AMD Radeon 使用 ROCm 10；没有兼容 GPU 时安装 CPU 版。
en.GpuPageDescription=Setup verifies the installed GPU: NVIDIA uses the matching CUDA stack, AMD Radeon uses ROCm 10, and systems without a compatible GPU use the CPU build.
ja.GpuPageDescription=セットアップが GPU を確認します。NVIDIA は対応する CUDA、AMD Radeon は ROCm 10、対応 GPU がない場合は CPU 版を使用します。
zhcn.GpuAuto=自动检测（推荐）
en.GpuAuto=Auto detect (recommended)
ja.GpuAuto=自動検出 (推奨)
zhcn.GpuCpu=CPU 模式
en.GpuCpu=CPU mode
ja.GpuCpu=CPU モード
zhcn.GpuCuda126=NVIDIA 50 系以下：共享 CUDA 12.6（cu126）
en.GpuCuda126=NVIDIA pre-50 series: shared CUDA 12.6 (cu126)
ja.GpuCuda126=NVIDIA 50 シリーズ未満: 共有 CUDA 12.6 (cu126)
zhcn.GpuCuda128=NVIDIA 50 系 Blackwell：CUDA 12.8（cu128）
en.GpuCuda128=NVIDIA 50 series Blackwell: CUDA 12.8 (cu128)
ja.GpuCuda128=NVIDIA 50 シリーズ Blackwell: CUDA 12.8 (cu128)
zhcn.GpuRocm10=AMD Radeon：ROCm 10
en.GpuRocm10=AMD Radeon: ROCm 10
ja.GpuRocm10=AMD Radeon: ROCm 10
zhcn.GpuLabelCuda128=NVIDIA 50 系 / Blackwell，固定使用 CUDA 12.8（cu128 torch）
en.GpuLabelCuda128=NVIDIA 50 series / Blackwell using CUDA 12.8 (cu128 torch)
ja.GpuLabelCuda128=NVIDIA 50 シリーズ / Blackwell、CUDA 12.8 (cu128 torch)
zhcn.GpuLabelCuda126=NVIDIA 50 系以下兼容显卡，使用共享 CUDA 12.6（cu126 torch）
en.GpuLabelCuda126=Compatible pre-50-series NVIDIA GPU using shared CUDA 12.6 (cu126 torch)
ja.GpuLabelCuda126=NVIDIA 50 シリーズ未満の対応 GPU、共有 CUDA 12.6 (cu126 torch)
zhcn.GpuLabelRocm10=AMD Radeon，使用 ROCm 10 与 ROCm Torch
en.GpuLabelRocm10=AMD Radeon using ROCm 10 and ROCm Torch
ja.GpuLabelRocm10=AMD Radeon、ROCm 10 と ROCm Torch
zhcn.GpuLabelDirectml=AMD Radeon，使用 Windows DirectML
en.GpuLabelDirectml=AMD Radeon using Windows DirectML
ja.GpuLabelDirectml=AMD Radeon、Windows DirectML
zhcn.GpuLabelCpu=CPU 或未检测到兼容 GPU，安装 CPU 版 torch
en.GpuLabelCpu=CPU or no compatible GPU detected; installs the CPU build of torch
ja.GpuLabelCpu=CPU または対応 GPU が未検出。CPU 版 torch をインストールします

zhcn.DownloadPageTitle=下载前置依赖
en.DownloadPageTitle=Download prerequisites
ja.DownloadPageTitle=前提条件のダウンロード
zhcn.DownloadPageSubtitle=Python 和 FFmpeg 已内置；其他系统依赖由用户安装
en.DownloadPageSubtitle=Python and FFmpeg are bundled; install other system dependencies manually
ja.DownloadPageSubtitle=Python と FFmpeg は同梱済みです。その他のシステム依存関係は手動でインストールします
zhcn.DownloadPageIntro=安装器已内置 Python 3.12 和 FFmpeg，不会自动运行 winget 或弹出其他系统安装程序。通过右侧按钮获取缺失的其他系统依赖，安装后点击“重新检测”。
en.DownloadPageIntro=Setup includes Python 3.12 and FFmpeg and does not run winget or launch other system installers. Use the buttons to obtain other missing system dependencies, then select "Check again".
ja.DownloadPageIntro=Python 3.12 と FFmpeg は同梱されています。winget や他のシステムインストーラーは自動実行しません。右側のボタンから不足している他の依存関係を入手し、インストール後に「再確認」を選択してください。
zhcn.DownloadPython=安装包已内置
en.DownloadPython=Included with setup
ja.DownloadPython=セットアップに同梱
zhcn.OpenGitDownload=打开 Git 下载
en.OpenGitDownload=Open Git download
ja.OpenGitDownload=Git のダウンロードを開く
zhcn.AutoInstall=自动安装
en.AutoInstall=Automatic
ja.AutoInstall=自動インストール
zhcn.OpenCppDownload=打开 C++ 下载
en.OpenCppDownload=Open C++ download
ja.OpenCppDownload=C++ のダウンロードを開く
zhcn.OpenCudaDownload=打开 CUDA 下载
en.OpenCudaDownload=Open CUDA download
ja.OpenCudaDownload=CUDA のダウンロードを開く
zhcn.OpenDriverDownload=打开驱动下载
en.OpenDriverDownload=Open driver download
ja.OpenDriverDownload=ドライバーのダウンロードを開く
zhcn.OpenVbCableDownload=打开 VB-CABLE 下载
en.OpenVbCableDownload=Open VB-CABLE download
ja.OpenVbCableDownload=VB-CABLE のダウンロードを開く
zhcn.CheckAgain=重新检测
en.CheckAgain=Check again
ja.CheckAgain=再確認

zhcn.PythonPageTitle=内置 Python 3.12
en.PythonPageTitle=Bundled Python 3.12
ja.PythonPageTitle=同梱 Python 3.12
zhcn.PythonPageSubtitle=安装器将使用随软件提供的 Python 运行时
en.PythonPageSubtitle=Setup uses the Python runtime shipped with the application
ja.PythonPageSubtitle=アプリに同梱された Python ランタイムを使用します
zhcn.PythonPageDescription=无需单独安装或选择 Python。安装器固定使用内置的 64 位 CPython 3.12.x。
en.PythonPageDescription=No separate Python installation or selection is required. Setup always uses bundled 64-bit CPython 3.12.x.
ja.PythonPageDescription=Python を別途インストールまたは選択する必要はありません。同梱の 64 ビット CPython 3.12.x を常に使用します。
zhcn.BundledPython=内置 Python（随安装器提供）
en.BundledPython=Bundled Python (included with setup)
ja.BundledPython=同梱 Python（セットアップに含まれます）
zhcn.PrereqPathTitle=前置依赖安装/查找路径
en.PrereqPathTitle=Prerequisite locations
ja.PrereqPathTitle=前提条件の場所
zhcn.PrereqPathSubtitle=选择依赖安装位置或已有路径
en.PrereqPathSubtitle=Select existing dependency locations
ja.PrereqPathSubtitle=既存の依存関係の場所を選択します
zhcn.PrereqPathDescription=如果刚安装的依赖尚未加入 PATH，可在这里填写其安装目录；安装器不会在这些位置自动安装。
en.PrereqPathDescription=If a newly installed dependency is not yet on PATH, enter its directory here. Setup will not install software into these locations.
ja.PrereqPathDescription=インストールした依存関係が PATH に未登録の場合は場所を指定してください。セットアップはこれらの場所へソフトウェアをインストールしません。
zhcn.CudaPathTitle=CUDA Toolkit 路径
en.CudaPathTitle=CUDA Toolkit location
ja.CudaPathTitle=CUDA Toolkit の場所
zhcn.CudaPathSubtitle=选择 CUDA Toolkit 安装位置或已有目录
en.CudaPathSubtitle=Select the CUDA Toolkit installation or an existing directory
ja.CudaPathSubtitle=CUDA Toolkit のインストール先または既存の場所を選択します
zhcn.CudaPathDescription=此页面只对 NVIDIA 显卡显示：50 系固定推荐 CUDA 12.8，50 系以下固定推荐 CUDA 12.6；PyTorch wheel 已包含推理运行库，Toolkit 用于配套工具链。
en.CudaPathDescription=This page is shown only for NVIDIA GPUs. CUDA 12.8 is recommended for the 50 series and CUDA 12.6 for earlier GPUs. PyTorch wheels include the inference runtime; the Toolkit provides supporting tools.
ja.CudaPathDescription=NVIDIA GPU でのみ表示されます。50 シリーズは CUDA 12.8、それ以前は CUDA 12.6 を推奨します。推論ランタイムは PyTorch wheel に含まれ、Toolkit は補助ツール用です。
zhcn.DataPageTitle=选择用户数据存储位置
en.DataPageTitle=Choose the user data location
ja.DataPageTitle=ユーザーデータの保存先
zhcn.DataPageSubtitle=模型、作品、下载素材、编辑工程与主题媒体保存在哪里？
en.DataPageSubtitle=Where should models, works, downloads, editor projects, and theme media be stored?
ja.DataPageSubtitle=モデル、作品、ダウンロード、編集プロジェクト、テーマメディアの保存先を選択します
zhcn.DataPageDescription=建议选择空间充足的磁盘。该目录后续也可以在软件首页迁移。
en.DataPageDescription=Choose a drive with enough free space. You can migrate this directory later from the app home page.
ja.DataPageDescription=十分な空き容量のあるドライブを選択してください。後からアプリのホーム画面で移行できます。
zhcn.DetailsPageTitle=详细安装信息
en.DetailsPageTitle=Detailed setup output
ja.DetailsPageTitle=セットアップの詳細
zhcn.DetailsPageSubtitle=运行环境搭建输出
en.DetailsPageSubtitle=Runtime setup output
ja.DetailsPageSubtitle=ランタイムセットアップの出力
zhcn.DetailsWaiting=安装详情会显示在这里；完整日志也会保存到安装目录。
en.DetailsWaiting=Setup details appear here. The full log is also saved in the install directory.
ja.DetailsWaiting=セットアップの詳細がここに表示されます。完全なログはインストール先にも保存されます。
zhcn.RuntimeNotStarted=尚未开始搭建运行环境。
en.RuntimeNotStarted=Runtime setup has not started.
ja.RuntimeNotStarted=ランタイムのセットアップはまだ開始されていません。
zhcn.FieldPython=Python 3.12.x：
en.FieldPython=Python 3.12.x:
ja.FieldPython=Python 3.12.x:
zhcn.FieldGit=Git：
en.FieldGit=Git:
ja.FieldGit=Git:
zhcn.FieldUv=uv：
en.FieldUv=uv:
ja.FieldUv=uv:
zhcn.FieldCpp=Microsoft C++ Build Tools：
en.FieldCpp=Microsoft C++ Build Tools:
ja.FieldCpp=Microsoft C++ Build Tools:
zhcn.FieldCuda=CUDA Toolkit：
en.FieldCuda=CUDA Toolkit:
ja.FieldCuda=CUDA Toolkit:
zhcn.FieldDriver=显卡驱动：
en.FieldDriver=GPU driver:
ja.FieldDriver=GPU ドライバー:
zhcn.FieldVbCable=VB-CABLE 虚拟音频线：
en.FieldVbCable=VB-CABLE virtual audio cable:
ja.FieldVbCable=VB-CABLE 仮想オーディオケーブル:
zhcn.FieldGpuStack=GPU 推理栈：
en.FieldGpuStack=GPU inference stack:
ja.FieldGpuStack=GPU 推論スタック:
zhcn.FieldJuce=JUCE VST3 Host：
en.FieldJuce=JUCE VST3 Host:
ja.FieldJuce=JUCE VST3 Host:
zhcn.UvDetected=uv：已检测到
en.UvDetected=uv: Detected
ja.UvDetected=uv: 検出済み
zhcn.UvPrepareWithPython=uv：安装时使用所选 Python 自动准备
en.UvPrepareWithPython=uv: Will be prepared automatically using the selected Python
ja.UvPrepareWithPython=uv: 選択した Python を使用して自動準備します
zhcn.UvWaitingForPython=uv：等待 Python 安装完成后自动安装
en.UvWaitingForPython=uv: Will be installed automatically after Python is available
ja.UvWaitingForPython=uv: Python の準備後に自動インストールします
zhcn.VbCableStatusHint=（系统音频变声需要；普通歌曲翻唱不需要）
en.VbCableStatusHint= (required for system-wide voice conversion; not needed for regular song covers)
ja.VbCableStatusHint= (システム音声変換に必要です。通常の楽曲カバーには不要です)
zhcn.DownloadCuda=下载 CUDA %1
en.DownloadCuda=Download CUDA %1
ja.DownloadCuda=CUDA %1 をダウンロード
zhcn.AmdDriverConfirm=AMD Radeon 驱动：请确认已安装
en.AmdDriverConfirm=AMD Radeon driver: Confirm it is installed
ja.AmdDriverConfirm=AMD Radeon ドライバー: インストール済みか確認してください
zhcn.NvidiaDriverConfirm=NVIDIA 显卡驱动：请确认已安装
en.NvidiaDriverConfirm=NVIDIA GPU driver: Confirm it is installed
ja.NvidiaDriverConfirm=NVIDIA GPU ドライバー: インストール済みか確認してください
zhcn.PythonExecutableLabel=Python 3.12 python.exe：
en.PythonExecutableLabel=Python 3.12 python.exe:
ja.PythonExecutableLabel=Python 3.12 python.exe:
zhcn.GitDirectoryLabel=Git 目录：
en.GitDirectoryLabel=Git directory:
ja.GitDirectoryLabel=Git ディレクトリ:
zhcn.FfmpegDirectoryLabel=FFmpeg 目录（分卷内置，系统已安装则跳过）：
en.FfmpegDirectoryLabel=FFmpeg directory (bundled; skipped when a system copy exists):
ja.FfmpegDirectoryLabel=FFmpeg ディレクトリ (同梱済み。システムにある場合はスキップ):
zhcn.CppDirectoryLabel=C++ Build Tools 目录：
en.CppDirectoryLabel=C++ Build Tools directory:
ja.CppDirectoryLabel=C++ Build Tools ディレクトリ:
zhcn.CudaDirectoryLabel=CUDA Toolkit 目录：
en.CudaDirectoryLabel=CUDA Toolkit directory:
ja.CudaDirectoryLabel=CUDA Toolkit ディレクトリ:
zhcn.DataDirectoryLabel=用户数据目录：
en.DataDirectoryLabel=User data directory:
ja.DataDirectoryLabel=ユーザーデータディレクトリ:
zhcn.RunningInstallStep=正在执行安装步骤...
en.RunningInstallStep=Running setup step...
ja.RunningInstallStep=セットアップ処理を実行しています...
zhcn.FullLogFile=完整日志文件：%1
en.FullLogFile=Full log file: %1
ja.FullLogFile=完全なログファイル: %1
zhcn.InvalidPython=请选择一个可运行的 64 位 CPython 3.12.x python.exe。
en.InvalidPython=Select a working 64-bit CPython 3.12.x python.exe.
ja.InvalidPython=実行可能な 64 ビット CPython 3.12.x python.exe を選択してください。
zhcn.CannotCreateDataDir=无法创建用户数据目录：%1%n请换一个有写入权限、空间充足的位置。
en.CannotCreateDataDir=Could not create the user data directory: %1%nChoose a writable location with enough free space.
ja.CannotCreateDataDir=ユーザーデータディレクトリを作成できませんでした: %1%n書き込み可能で十分な空き容量のある場所を選択してください。
zhcn.MissingPrereqConfirm=仍有一个或多个前置依赖未检测到。可以在下一页填写已有安装路径，也可以返回并安装缺失项。是否继续？
en.MissingPrereqConfirm=One or more prerequisites are still missing. You can enter existing locations on the next page or go back and install the missing items. Continue?
ja.MissingPrereqConfirm=未検出の前提条件があります。次のページで既存の場所を指定するか、戻って不足項目をインストールできます。続行しますか？
zhcn.FinishedLog=运行环境安装详情已写入：%1%n安装过程不会打开 PowerShell 或命令行窗口；如需排查失败，请查看该日志。
en.FinishedLog=Runtime setup details were saved to: %1%nSetup did not open PowerShell or a command window. Use this log to investigate failures.
ja.FinishedLog=ランタイムセットアップの詳細を保存しました: %1%nPowerShell やコマンドウィンドウは開いていません。問題の調査にはこのログを使用してください。
zhcn.LastLogSummary=最后日志摘要：
en.LastLogSummary=Last log summary:
ja.LastLogSummary=最後のログ概要:
zhcn.LogStep=步骤：%1
en.LogStep=Step: %1
ja.LogStep=処理: %1
zhcn.LogStarted=开始时间：%1
en.LogStarted=Started: %1
ja.LogStarted=開始時刻: %1
zhcn.LogArguments=参数：%1
en.LogArguments=Arguments: %1
ja.LogArguments=引数: %1
zhcn.LogFile=日志文件：%1
en.LogFile=Log file: %1
ja.LogFile=ログファイル: %1
zhcn.DetailsLog=安装详情日志：%1
en.DetailsLog=Setup details log: %1
ja.DetailsLog=セットアップ詳細ログ: %1
zhcn.BatchFailed=%1 执行失败，退出码：%2%n安装文件已经复制完成。可以稍后从开始菜单运行“搭建/修复运行环境”重试。%n%n详细日志：%3
en.BatchFailed=%1 failed with exit code %2.%nThe application files were copied. Retry later from "Set up or repair runtime" in the Start menu.%n%nLog: %3
ja.BatchFailed=%1 が終了コード %2 で失敗しました。%nアプリケーションファイルはコピー済みです。後でスタートメニューの「ランタイムをセットアップまたは修復」から再試行できます。%n%nログ: %3
zhcn.StepCompleted=%1完成
en.StepCompleted=%1 complete
ja.StepCompleted=%1 完了
zhcn.BundledValidationTitle=应用本体与内置组件校验
en.BundledValidationTitle=Application and bundled component validation
ja.BundledValidationTitle=アプリケーションと同梱コンポーネントの検証
zhcn.BundledValidationOk=[ok] 应用本体、前端、AI workers、FFmpeg、引擎源码、离线模型、Python wheels 与 JUCE Host 完整。
en.BundledValidationOk=[ok] Application, frontend, AI workers, FFmpeg, engine sources, offline models, Python wheels, and JUCE Host are complete.
ja.BundledValidationOk=[ok] アプリ、フロントエンド、AI worker、FFmpeg、エンジンソース、オフラインモデル、Python wheel、JUCE Host は完全です。
zhcn.BundledValidationFailed=[fail] 发布包缺少必要组件：
en.BundledValidationFailed=[fail] Required package components are missing:
ja.BundledValidationFailed=[fail] 必要なパッケージコンポーネントが不足しています:
zhcn.BundledValidationDialog=安装包缺少必要组件，部分功能将不可用：%n%1%n%n请重新下载安装器的完整分卷文件。
en.BundledValidationDialog=Required package components are missing and some features will be unavailable:%n%1%n%nDownload the complete installer and all matching split files again.
ja.BundledValidationDialog=必要なパッケージコンポーネントが不足しているため、一部機能を利用できません:%n%1%n%n完全なインストーラーと対応する分割ファイルを再ダウンロードしてください。
zhcn.RuntimeValidationTitle=%1 运行环境最终校验
en.RuntimeValidationTitle=%1 runtime final validation
ja.RuntimeValidationTitle=%1 ランタイムの最終検証
zhcn.RuntimeReady=[ok] %1 运行环境可被软件识别。
en.RuntimeReady=[ok] The %1 runtime is available to the app.
ja.RuntimeReady=[ok] %1 ランタイムをアプリで使用できます。
zhcn.RuntimeIncomplete=[fail] %1 运行环境不完整，软件会显示降级模式。
en.RuntimeIncomplete=[fail] The %1 runtime is incomplete; the app will use degraded mode.
ja.RuntimeIncomplete=[fail] %1 ランタイムが不完全なため、アプリは縮退モードになります。
zhcn.InstallDirectory=安装目录：%1
en.InstallDirectory=Install directory: %1
ja.InstallDirectory=インストール先: %1
zhcn.MissingItems=缺失项：
en.MissingItems=Missing items:
ja.MissingItems=不足項目:
zhcn.PythonNotRunnable=%1 Python 不可运行
en.PythonNotRunnable=%1 Python is not runnable
ja.PythonNotRunnable=%1 Python を実行できません
zhcn.RepairSuggestion=建议：从开始菜单运行“搭建/修复运行环境”，或在安装目录执行 %1。
en.RepairSuggestion=Suggestion: Run "Set up or repair runtime" from the Start menu, or run %1 in the install directory.
ja.RepairSuggestion=スタートメニューの「ランタイムをセットアップまたは修復」を実行するか、インストール先で %1 を実行してください。
zhcn.RuntimeValidationDialog=%1 运行环境最终校验失败。%n%n缺失项：%n%2%n%n可稍后在安装目录执行：%3%n%n详细日志：%4
en.RuntimeValidationDialog=%1 runtime validation failed.%n%nMissing items:%n%2%n%nRun this later in the install directory: %3%n%nLog: %4
ja.RuntimeValidationDialog=%1 ランタイムの検証に失敗しました。%n%n不足項目:%n%2%n%n後でインストール先から実行してください: %3%n%nログ: %4
zhcn.TorchMissingPython=[fail] %1 缺少 Python：%2
en.TorchMissingPython=[fail] %1 is missing Python: %2
ja.TorchMissingPython=[fail] %1 に Python がありません: %2
zhcn.TorchReady=[ok] %1 Torch 可导入且设备栈匹配。
en.TorchReady=[ok] %1 Torch imports successfully and matches the device stack.
ja.TorchReady=[ok] %1 の Torch を読み込め、デバイススタックも一致しています。
zhcn.TorchInvalid=[fail] %1 Torch 损坏、未完成或与所选 GPU 栈不匹配。
en.TorchInvalid=[fail] %1 Torch is corrupt, incomplete, or does not match the selected GPU stack.
ja.TorchInvalid=[fail] %1 の Torch が破損、不完全、または選択した GPU スタックと一致しません。
zhcn.TorchValidationTitle=AI 运行环境真实 Torch 校验
en.TorchValidationTitle=AI runtime Torch validation
ja.TorchValidationTitle=AI ランタイムの Torch 検証
zhcn.AllRuntimeFailed=一个或多个 AI 环境没有完整安装，软件会显示降级模式。%n请不要直接启动软件；先从开始菜单运行“搭建/修复运行环境”，或在安装目录重新执行 setup_env.bat。%n%n详细日志：%1
en.AllRuntimeFailed=One or more AI runtimes were not installed completely, so the app will use degraded mode.%nBefore launching the app, run "Set up or repair runtime" from the Start menu or run setup_env.bat in the install directory.%n%nLog: %1
ja.AllRuntimeFailed=1 つ以上の AI ランタイムが完全にインストールされていないため、アプリは縮退モードになります。%nアプリを起動する前に、スタートメニューの「ランタイムをセットアップまたは修復」またはインストール先の setup_env.bat を実行してください。%n%nログ: %1
zhcn.WheelsAlreadyRemoved=[ok] 离线 wheels 已不存在，无需清理。
en.WheelsAlreadyRemoved=[ok] Offline wheels are already absent; no cleanup is needed.
ja.WheelsAlreadyRemoved=[ok] オフライン wheel は既に削除されています。
zhcn.WheelsRemoved=[ok] 运行环境校验通过，已自动删除离线 wheels：%1
en.WheelsRemoved=[ok] Runtime validation passed and offline wheels were removed: %1
ja.WheelsRemoved=[ok] ランタイム検証に合格し、オフライン wheel を削除しました: %1
zhcn.WheelsCleanupFailed=[warn] 运行环境已就绪，但离线 wheels 清理失败，可稍后手动删除：%1
en.WheelsCleanupFailed=[warn] The runtime is ready, but offline wheel cleanup failed. Delete them manually later: %1
ja.WheelsCleanupFailed=[warn] ランタイムは準備できましたが、オフライン wheel の削除に失敗しました。後で手動削除してください: %1
zhcn.RuntimeCacheCleaned=运行环境搭建完成，已清理安装缓存
en.RuntimeCacheCleaned=Runtime setup complete; installation cache cleaned
ja.RuntimeCacheCleaned=ランタイムのセットアップが完了し、インストールキャッシュを削除しました
zhcn.RuntimePreparing=准备搭建运行环境…
en.RuntimePreparing=Preparing runtime setup...
ja.RuntimePreparing=ランタイムセットアップを準備しています...
zhcn.PrereqsConfiguring=正在检测前置依赖并配置环境变量…
en.PrereqsConfiguring=Checking prerequisites and configuring environment variables...
ja.PrereqsConfiguring=前提条件を確認し、環境変数を設定しています...
zhcn.RuntimeBuilding=正在搭建运行环境（创建子环境、复制模型、安装 Python 依赖）…
en.RuntimeBuilding=Setting up runtimes (creating environments, copying models, and installing Python packages)...
ja.RuntimeBuilding=ランタイムをセットアップしています (環境作成、モデルのコピー、Python パッケージのインストール)...
zhcn.RuntimeValidationPartial=部分运行环境校验失败，请查看安装详情日志
en.RuntimeValidationPartial=Some runtime checks failed. Review the setup details log
ja.RuntimeValidationPartial=一部のランタイム検証に失敗しました。セットアップ詳細ログを確認してください
zhcn.PluginsName=Python 插件
en.PluginsName=Python plugins
ja.PluginsName=Python プラグイン
zhcn.VocalName=AI 歌声增强
en.VocalName=AI vocal enhancement
ja.VocalName=AI ボーカル補正

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkablealone

#ifndef XB_VALIDATE_ONLY
[Files]
; 应用本体：PyInstaller 打包产物（XB-SVCB.exe + _internal，含前端与 worker 脚本）
Source: "..\dist\XB-SVCB\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 环境搭建脚本（纯 batch + Python，安装过程不涉及 PowerShell）
Source: "..\install\install.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\install_shared.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\audit_runtime.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\runtime_manifest.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\build_core_compat.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\probe_core_compat.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\core_recipe.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\runtime_profiles\*"; DestDir: "{app}\install\runtime_profiles"; Flags: recursesubdirs createallsubdirs ignoreversion
; Hash-verified shared-core compatibility artifacts. The official build script
; requires these for CUDA packages before invoking Inno Setup.
Source: "..\assets\runtime\*"; DestDir: "{app}\assets\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression skipifsourcedoesntexist
Source: "..\install\configure_user_env.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\detect_python.bat"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\build_rvc_compat.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\setup_env.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup_shared_env.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_prereqs.bat"; DestDir: "{app}"; Flags: ignoreversion
; 应用图标（供 .bat 快捷方式引用；exe 已内嵌同一图标）
Source: "..\web\public\favicon.ico"; DestDir: "{app}"; DestName: "xb-svcb.ico"; Flags: ignoreversion
; Python 与 FFmpeg 都随分卷离线携带，不依赖用户机器上的全局安装。
Source: "..\.tmp\python312-runtime\*"; DestDir: "{app}\tools\python312"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
Source: "..\assets\tools\ffmpeg\*"; DestDir: "{app}\tools\ffmpeg"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
; 三个歌声引擎源码随分卷携带。模型由 assets/models 统一提供，排除仓库元数据、缓存、
; 示例与重复权重，安装后 install.py 会检测到源码并跳过 Git/ZIP 获取。
Source: "..\.tmp\bundled-engines\so-vits-svc\*"; DestDir: "{app}\engines\so-vits-svc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\.tmp\bundled-engines\ddsp-svc\*"; DestDir: "{app}\engines\ddsp-svc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\.tmp\bundled-engines\seed-vc\*"; DestDir: "{app}\engines\seed-vc"; Flags: recursesubdirs createallsubdirs ignoreversion
; 自带底模与 UVR 模型（随安装包分发；安装时由 install.py 本地复制，免联网慢下载）
; 模型为已压缩的二进制权重，用 nocompression 跳过再压缩，显著加快编译与安装速度
; FCPE 用于检测到极高音时自动扩展 F0 覆盖；分卷仍由 DiskSliceSize 控制在 2 GB 内
Source: "..\assets\models\*"; DestDir: "{app}\assets\models"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
; Python 依赖 wheelhouse：build.ps1 已按安装包类型筛选，只携带一个硬件栈。
Source: "..\.tmp\installer-wheelhouse\*"; DestDir: "{app}\assets\wheels"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\release-notes\release_notes_v0_1_0.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion
Source: "..\docs\release-notes\release_notes_v0_1_0.en.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion
Source: "..\docs\release-notes\release_notes_v0_1_0.ja.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion
Source: "..\docs\api.md"; DestDir: "{app}\docs"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\{cm:RepairEnvironment}"; Filename: "{app}\setup_env.bat"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\{cm:UninstallApp,{#MyAppShort}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\xb-svcb.ico"

[Run]
; 提供安装完成后直接启动选项（默认不勾）
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchApp,{#MyAppShort}}"; \
  WorkingDir: "{app}"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; 卸载时清理安装目录内生成的环境与下载物（用户数据在 .xb_svcb，保留）
Type: filesandordirs; Name: "{app}\.venv-uvr"
Type: filesandordirs; Name: "{app}\.venv-plugins"
Type: filesandordirs; Name: "{app}\.venv-svc"
Type: filesandordirs; Name: "{app}\.venv-rvc"
Type: filesandordirs; Name: "{app}\.venv-rvc-directml"
Type: filesandordirs; Name: "{app}\.venv-seedvc"
Type: filesandordirs; Name: "{app}\.venv-ddsp"
Type: filesandordirs; Name: "{app}\.venv-ddsp-legacy"
Type: filesandordirs; Name: "{app}\.venv-hub"
Type: filesandordirs; Name: "{app}\runtimes"
Type: files; Name: "{app}\runtime.json"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\models"

[Code]
const
  CudaToolkitPreBlackwellVersion = '12.6';
  CudaToolkitBlackwellVersion = '12.8';
  CudaToolkitPreBlackwellUrl = 'https://developer.nvidia.com/cuda-12-6-0-download-archive';
  CudaToolkitBlackwellUrl = 'https://developer.nvidia.com/cuda-12-8-0-download-archive';

var
  DataDirPage: TInputDirWizardPage;
  PrereqPage: TInputOptionWizardPage;
  GpuStackPage: TInputOptionWizardPage;
  PrereqDownloadPage: TWizardPage;
  PrereqDownloadIntro: TNewStaticText;
  PythonStatusLabel: TNewStaticText;
  GitStatusLabel: TNewStaticText;
  UvStatusLabel: TNewStaticText;
  CppStatusLabel: TNewStaticText;
  CudaStatusLabel: TNewStaticText;
  DriverStatusLabel: TNewStaticText;
  VbCableStatusLabel: TNewStaticText;
  PythonDownloadButton: TNewButton;
  GitDownloadButton: TNewButton;
  UvDownloadButton: TNewButton;
  CppDownloadButton: TNewButton;
  CudaDownloadButton: TNewButton;
  DriverDownloadButton: TNewButton;
  VbCableDownloadButton: TNewButton;
  RefreshPrereqButton: TNewButton;
  PythonPathPage: TInputFileWizardPage;
  PrereqPathPage: TInputDirWizardPage;
  CudaPathPage: TInputDirWizardPage;
  DetailsPage: TWizardPage;
  DetailsInfoLabel: TNewStaticText;
  DetailsMemo: TNewMemo;
  LastInstallLog: String;
  LastInstallSummary: String;
  InstallDetailText: String;
  CurrentLogPath: String;
  EnvProgressStart: Integer;
  EnvProgressEnd: Integer;
  EnvProgressCurrent: Integer;
  EnvProgressTicks: Integer;
  EnvProgressMarkerSeen: Boolean;
  DetectedGpuStackCache: String;

function M(const Key: String): String;
begin
  Result := CustomMessage(Key);
end;

function M1(const Key, Value: String): String;
begin
  Result := FmtMessage(CustomMessage(Key), [Value]);
end;

function M2(const Key, Value1, Value2: String): String;
begin
  Result := FmtMessage(CustomMessage(Key), [Value1, Value2]);
end;

function M3(const Key, Value1, Value2, Value3: String): String;
begin
  Result := FmtMessage(CustomMessage(Key), [Value1, Value2, Value3]);
end;

function M4(const Key, Value1, Value2, Value3, Value4: String): String;
begin
  Result := FmtMessage(CustomMessage(Key), [Value1, Value2, Value3, Value4]);
end;

function JsonEscape(const S: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    if S[I] = '\' then
      Result := Result + '\\'
    else if S[I] = '"' then
      Result := Result + '\"'
    else
      Result := Result + S[I];
  end;
end;

function PathJoin(const A, B: String): String;
begin
  Result := AddBackslash(A) + B;
end;

function IsDriveRootPath(const S: String): Boolean;
begin
  Result := Uppercase(AddBackslash(S)) = Uppercase(AddBackslash(ExtractFileDrive(S)));
end;

function DirectoryHasEntries(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(PathJoin(Dir, '*'), FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function IsXbDataDir(const Dir: String): Boolean;
begin
  Result :=
    FileExists(PathJoin(Dir, '.xb_svcb_data')) or
    FileExists(PathJoin(Dir, '.sb-svcb_data')) or
    FileExists(PathJoin(Dir, '.xb_xvcb_data')) or
    FileExists(PathJoin(Dir, '.sv-xvcb_data')) or
    FileExists(PathJoin(Dir, 'models.json')) or
    FileExists(PathJoin(Dir, 'works.json')) or
    FileExists(PathJoin(Dir, 'settings.json'));
end;

function ResolveInstallerDataDir(const Raw: String): String;
var
  Selected: String;
begin
  Selected := RemoveBackslashUnlessRoot(ExpandConstant(Raw));
  if Selected = '' then
    Selected := ExpandConstant('{app}\.xb_svcb');

  if IsDriveRootPath(Selected) then
    Result := PathJoin(Selected, '.xb_svcb')
  else if DirExists(Selected) and DirectoryHasEntries(Selected) and (not IsXbDataDir(Selected)) then
    Result := PathJoin(Selected, '.xb_svcb')
  else
    Result := Selected;
end;

function BatchEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '^', '^^', True);
  StringChangeEx(Result, '%', '%%', True);
  StringChangeEx(Result, '"', '', True);
end;

function BoolFlag(Value: Boolean): String;
begin
  if Value then
    Result := '1'
  else
    Result := '0';
end;

function TailText(const S: String; MaxLen: Integer): String;
begin
  if Length(S) <= MaxLen then
    Result := S
  else
    Result := '...' + Copy(S, Length(S) - MaxLen + 1, MaxLen);
end;

function CmdAvailable(const Exe: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/c where ' + Exe + ' >nul 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function CommandSucceeds(const CommandLine: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/d /c ' + CommandLine + ' >nul 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PythonFileAvailable(const FileName: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if (FileName = '') or (not FileExists(FileName)) then
    Exit;
  Result := Exec(FileName,
    '-c "import sys; raise SystemExit(0 if sys.implementation.name == ''cpython'' and sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function CommandOutput(const CommandLine: String): String; forward;

function PythonPathCommandExecutable(const CommandName: String): String;
var
  Output, Line, LowerLine: String;
  NewLinePos: Integer;
begin
  Result := '';
  if not CmdAvailable(CommandName) then
    Exit;
  Output := CommandOutput('where ' + CommandName);
  { Test every PATH result. WindowsApps aliases are deliberately skipped. }
  while Output <> '' do
  begin
    NewLinePos := Pos(#13, Output);
    if NewLinePos = 0 then
    begin
      Line := Trim(Output);
      Output := '';
    end
    else
    begin
      Line := Trim(Copy(Output, 1, NewLinePos - 1));
      Output := Copy(Output, NewLinePos + 1, Length(Output));
      if (Output <> '') and (Output[1] = #10) then
        Output := Copy(Output, 2, Length(Output));
    end;
    LowerLine := LowerCase(Line);
    if (Line <> '') and FileExists(Line) and
       (Pos('\windowsapps\', LowerLine) = 0) and
       PythonFileAvailable(Line) then
    begin
      Result := Line;
      Exit;
    end;
  end;
end;

function PythonPathCommandAvailable(const CommandName: String): Boolean;
begin
  Result := PythonPathCommandExecutable(CommandName) <> '';
end;

function DetectPython312Executable(): String;
var
  Candidate: String;
begin
  Result := '';
  Candidate := GetEnv('XB_PYTHON_EXE');
  if PythonFileAvailable(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;
  Candidate := ExpandConstant('{localappdata}\Programs\Python\Python312\python.exe');
  if PythonFileAvailable(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;
  if CmdAvailable('py') then
  begin
    Candidate := Trim(CommandOutput(
      'py -3.12 -c "import sys; print(sys.executable)"'));
    if PythonFileAvailable(Candidate) then
    begin
      Result := Candidate;
      Exit;
    end;
  end;
  Result := PythonPathCommandExecutable('python');
end;

function PythonAvailable(const CustomExecutable: String): Boolean;
begin
  if CustomExecutable <> '' then
    Result := PythonFileAvailable(CustomExecutable)
  else
    Result := DetectPython312Executable() <> '';
end;

function SystemFfmpegAvailable(): Boolean;
begin
  { This function is used by [Files] Check before the app dir is initialized. }
  Result := CommandSucceeds('ffmpeg -version') and CommandSucceeds('ffprobe -version');
end;

function CommandOutput(const CommandLine: String): String;
var
  ResultCode: Integer;
  TempFile: String;
  Text: AnsiString;
begin
  Result := '';
  TempFile := ExpandConstant('{tmp}\xb_svcb_cmd_output.txt');
  DeleteFile(TempFile);
  if Exec(ExpandConstant('{cmd}'), '/c ' + CommandLine + ' > "' + TempFile + '" 2>nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    if LoadStringFromFile(TempFile, Text) then
      Result := String(Text);
  end;
  DeleteFile(TempFile);
end;

function CmdPath(const S: String): String;
begin
  if (Pos('\', S) > 0) or (Pos(' ', S) > 0) then
    Result := '"' + S + '"'
  else
    Result := S;
end;

function NvidiaSmiCommand(): String;
var
  Candidate: String;
begin
  Result := '';
  if CmdAvailable('nvidia-smi') then
  begin
    Result := 'nvidia-smi';
    Exit;
  end;

  Candidate := ExpandConstant('{win}\System32\nvidia-smi.exe');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{win}\Sysnative\nvidia-smi.exe');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{autopf}\NVIDIA Corporation\NVSMI\nvidia-smi.exe');
  if FileExists(Candidate) then
    Result := Candidate;
end;

function ContainsText(const S, Needle: String): Boolean;
begin
  Result := Pos(Uppercase(Needle), Uppercase(S)) > 0;
end;

function VbCableAvailable(): Boolean;
var
  DeviceNames: String;
begin
  { VB-CABLE registers both endpoints. Registry checks are fast; the device
    name check handles manual installs whose registry layout differs. }
  Result := RegKeyExists(HKLM, 'SOFTWARE\VB-Audio\VBCABLE') or
    RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\VB-Audio\VBCABLE');
  if Result then
    Exit;

  DeviceNames := CommandOutput(
    'powershell.exe -NoProfile -NonInteractive -Command "(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue).Name; (Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FriendlyName)"');
  Result := ContainsText(DeviceNames, 'CABLE Input') and
    ContainsText(DeviceNames, 'CABLE Output');
end;

function HasComputeMajorAtLeast(const Text: String; MinMajor: Integer): Boolean;
var
  I, Major: Integer;
  Token: String;
begin
  Result := False;
  Token := '';
  I := 1;
  while I <= Length(Text) do
  begin
    if (Text[I] >= '0') and (Text[I] <= '9') then
    begin
      Token := Token + Text[I];
      I := I + 1;
    end
    else
    begin
      if Token <> '' then
      begin
        Major := StrToInt(Token);
        if Major >= MinMajor then
        begin
          Result := True;
          Exit;
        end;
        Token := '';
      end;
      while I <= Length(Text) do
      begin
        if Text[I] = #10 then
        begin
          I := I + 1;
          Break;
        end;
        I := I + 1;
      end;
    end;
  end;
  if Token <> '' then
  begin
    Major := StrToInt(Token);
    Result := Major >= MinMajor;
  end;
end;

function GpuStackFromAdapterNames(const Names: String): String;
begin
  Result := 'cpu';
  if ContainsText(Names, 'RTX 50') or ContainsText(Names, 'RTX50') then
    Result := 'cu128'
  else if ContainsText(Names, 'NVIDIA') or ContainsText(Names, 'GeForce') then
    Result := 'cu126'
  else if ContainsText(Names, 'AMD') or ContainsText(Names, 'Radeon') then
    Result := 'rocm10';
end;

function DetectedGpuStackName(): String;
var
  Caps, Names, Smi: String;
begin
  if DetectedGpuStackCache <> '' then
  begin
    Result := DetectedGpuStackCache;
    Exit;
  end;

  Result := 'cpu';
  Smi := NvidiaSmiCommand();
  if Smi <> '' then
  begin
    Caps := CommandOutput(CmdPath(Smi) + ' --query-gpu=compute_cap --format=csv,noheader');
    { Query the adapter name even when compute_cap is present.  Some driver
      versions expose a pre-Blackwell/placeholder capability for RTX 50xx;
      the name must still force the cu128 shared recipe. }
    Names := CommandOutput(CmdPath(Smi) + ' --query-gpu=name --format=csv,noheader');
    if Caps <> '' then
    begin
      if HasComputeMajorAtLeast(Caps, 12) then
        Result := 'cu128'
      else if HasComputeMajorAtLeast(Caps, 5) then
        Result := 'cu126';
    end;

    if ContainsText(Names, 'RTX 50') or ContainsText(Names, 'RTX50') then
      Result := 'cu128'
    else if Result = 'cpu' then
    begin
      Result := GpuStackFromAdapterNames(Names);
    end;
  end;

  if Result = 'cpu' then
  begin
    Names := CommandOutput(
      'powershell.exe -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name"');
    Result := GpuStackFromAdapterNames(Names);
  end;

  DetectedGpuStackCache := Result;
end;

function InstallerGpuStackName(): String;
begin
  if '{#XB_PACKAGE_STACK}' <> 'universal' then
    Result := '{#XB_PACKAGE_STACK}'
  else
    Result := DetectedGpuStackName();
end;

function CudaToolkitVersionForStack(const Stack: String): String;
begin
  { 这里必须只返回固定的推荐版本，不能从系统 nvcc 输出推导版本。 }
  if Stack = 'cu128' then
    Result := CudaToolkitBlackwellVersion
  else if Stack = 'cu126' then
    Result := CudaToolkitPreBlackwellVersion
  else
    Result := '';
end;

function CudaToolkitDownloadUrlForStack(const Stack: String): String;
begin
  { 下载链接同样固定，不能跟随系统已安装的 CUDA 版本变化。 }
  if Stack = 'cu128' then
    Result := CudaToolkitBlackwellUrl
  else if Stack = 'cu126' then
    Result := CudaToolkitPreBlackwellUrl
  else
    Result := '';
end;

function DefaultCudaToolkitDirForStack(const Stack: String): String;
begin
  if Stack = 'cu128' then
    Result := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v' + CudaToolkitBlackwellVersion)
  else if Stack = 'cu126' then
    Result := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v' + CudaToolkitPreBlackwellVersion)
  else
    Result := '';
end;

function CudaNvccPath(const Version: String): String;
begin
  Result := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v' + Version + '\bin\nvcc.exe');
end;

function CudaNvccMatchesVersion(const NvccPath, Version: String): Boolean;
var
  Output: String;
begin
  Result := False;
  if (NvccPath = '') or (not FileExists(NvccPath)) then
    Exit;
  Output := CommandOutput(CmdPath(NvccPath) + ' --version 2>&1');
  { PyTorch wheels carry their own CUDA runtime. A newer Toolkit is only a
    compiler/tooling version and is compatible with the packaged cu128 stack
    for this application, so accept CUDA 13.x as newer than the recommendation. }
  Result := ContainsText(Output, 'release ' + Version) or
    ContainsText(Output, 'release 13.');
end;

function CudaToolkitAvailable(const Version, ToolkitDir: String): Boolean;
var
  PathNvccOutput: String;
begin
  PathNvccOutput := '';
  if CmdAvailable('nvcc') then
    PathNvccOutput := CommandOutput('nvcc --version 2>&1');
  Result :=
    CudaNvccMatchesVersion(CudaNvccPath(Version), Version) or
    ((ToolkitDir <> '') and CudaNvccMatchesVersion(ToolkitDir + '\bin\nvcc.exe', Version)) or
    ((GetEnv('CUDA_PATH') <> '') and
      CudaNvccMatchesVersion(GetEnv('CUDA_PATH') + '\bin\nvcc.exe', Version)) or
    ((PathNvccOutput <> '') and
      (ContainsText(PathNvccOutput, 'release ' + Version) or
       ContainsText(PathNvccOutput, 'release 13.')));
end;

function GpuStackLabel(const Stack: String): String;
begin
  if Stack = 'cu128' then
    Result := M('GpuLabelCuda128')
  else if Stack = 'cu126' then
    Result := M('GpuLabelCuda126')
  else if Stack = 'rocm10' then
    Result := M('GpuLabelRocm10')
  else if Stack = 'directml' then
    Result := M('GpuLabelDirectml')
  else
    Result := M('GpuLabelCpu');
end;

function NvidiaGpuDetected(): Boolean;
var
  Stack: String;
begin
  Stack := InstallerGpuStackName();
  Result := (Stack = 'cu126') or (Stack = 'cu128');
end;

function DetectedCudaVersion(): String;
begin
  Result := CudaToolkitVersionForStack(InstallerGpuStackName());
end;

function ShowInstallDetails(): Boolean;
begin
  Result := PrereqPage.Values[0] and PrereqPage.Values[2];
end;

function BuildEnvSelected(): Boolean;
begin
  Result := PrereqPage.Values[0];
end;

function EnvConfigureSelected(): Boolean;
begin
  Result := PrereqPage.Values[1];
end;

function StatusText(Ok: Boolean): String;
begin
  if Ok then
    Result := M('Detected')
  else
    Result := M('NotDetected');
end;

function EnvironmentCheckSummary(): String;
var
  DetectedStack, PythonStatus: String;
begin
  DetectedStack := InstallerGpuStackName();
  PythonStatus := M('BundledPython');
  Result :=
    M('EnvironmentSummaryIntro') + #13#10 +
    '  ' + M('FieldPython') + ' ' + PythonStatus + #13#10 +
    '  ' + M('FieldGit') + ' ' + StatusText(CmdAvailable('git')) + #13#10 +
    '  ffmpeg / ffprobe: ' + StatusText(SystemFfmpegAvailable()) + M('BundledFfmpegHint') + #13#10 +
    '  ' + M('FieldUv') + ' ' + StatusText(CmdAvailable('uv')) + M('UvHint') + #13#10;
  if (DetectedStack = 'cu126') or (DetectedStack = 'cu128') then
    Result := Result + '  CUDA Toolkit ' + DetectedCudaVersion() + ': ' +
      StatusText(CudaToolkitAvailable(DetectedCudaVersion(), DefaultCudaToolkitDirForStack(DetectedStack))) + #13#10;
  Result := Result +
    '  VB-CABLE: ' + StatusText(VbCableAvailable()) + M('VbCableHint') + #13#10 +
    '  ' + M('FieldJuce') + ' ' + M('JuceBundled') + #13#10 +
    '  ' + M('FieldGpuStack') + ' ' + GpuStackLabel(DetectedStack) + #13#10 +
    M('PythonSelectionHint');
end;

procedure OpenDownloadUrl(const URL: String);
var
  ErrorCode: Integer;
begin
  if not ShellExec('open', URL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox(M1('OpenDownloadFailed', URL), mbError, MB_OK);
end;

procedure PythonDownloadClick(Sender: TObject);
begin
  OpenDownloadUrl('https://www.python.org/downloads/windows/');
end;

procedure GitDownloadClick(Sender: TObject);
begin
  OpenDownloadUrl('https://git-scm.com/download/win');
end;

procedure UvDownloadClick(Sender: TObject);
begin
  MsgBox(M('UvAutoInstallInfo'), mbInformation, MB_OK);
end;

procedure CppDownloadClick(Sender: TObject);
begin
  OpenDownloadUrl('https://visualstudio.microsoft.com/visual-cpp-build-tools/');
end;

procedure CudaDownloadClick(Sender: TObject);
var
  Url: String;
begin
  Url := CudaToolkitDownloadUrlForStack(InstallerGpuStackName());
  if Url <> '' then
    OpenDownloadUrl(Url);
end;

procedure VbCableDownloadClick(Sender: TObject);
begin
  OpenDownloadUrl('https://vb-audio.com/Cable/');
end;

function GpuStackName(): String; forward;

procedure DriverDownloadClick(Sender: TObject);
begin
  if (GpuStackName() = 'rocm10') or (GpuStackName() = 'directml') then
    OpenDownloadUrl('https://www.amd.com/en/support/download/drivers.html')
  else
    OpenDownloadUrl('https://www.nvidia.com/download/index.aspx');
end;

procedure CreateDownloadRow(const LabelText, ButtonText: String; RowTop: Integer;
  var StatusLabel: TNewStaticText; var DownloadButton: TNewButton);
begin
  StatusLabel := TNewStaticText.Create(PrereqDownloadPage);
  StatusLabel.AutoSize := False;
  StatusLabel.WordWrap := False;
  StatusLabel.Left := 0;
  StatusLabel.Top := ScaleY(RowTop);
  StatusLabel.Height := ScaleY(28);
  StatusLabel.Caption := LabelText;
  StatusLabel.Parent := PrereqDownloadPage.Surface;

  DownloadButton := TNewButton.Create(PrereqDownloadPage);
  DownloadButton.Width := ScaleX(150);
  DownloadButton.Height := ScaleY(26);
  DownloadButton.Left := PrereqDownloadPage.SurfaceWidth - DownloadButton.Width;
  DownloadButton.Top := ScaleY(RowTop - 2);
  DownloadButton.Caption := ButtonText;
  DownloadButton.Parent := PrereqDownloadPage.Surface;
  StatusLabel.Width := DownloadButton.Left - ScaleX(12);
end;

function CommandOrFileAvailable(const Command, PathA, PathB, PathC: String): Boolean;
begin
  Result := CmdAvailable(Command) or
    ((PathA <> '') and FileExists(PathA)) or
    ((PathB <> '') and FileExists(PathB)) or
    ((PathC <> '') and FileExists(PathC));
end;

procedure RefreshPrereqDownloadStatus;
var
  IsNvidia, IsAmd, PythonReady: Boolean;
  DetectedStack, CudaVersion, GitPath, SelectedPython, PythonDir: String;
  CudaPath: String;
  UserProfilePath, UvStandalonePath, UvPythonScriptsPath, UvUserScriptsPath: String;
begin
  GitPath := ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe');
  UserProfilePath := GetEnv('USERPROFILE');
  if UserProfilePath <> '' then
    UvStandalonePath := PathJoin(UserProfilePath, '.local\bin\uv.exe')
  else
    UvStandalonePath := '';
  SelectedPython := ExpandConstant('{app}\tools\python312\python.exe');
  PythonPathPage.Values[0] := SelectedPython;
  PythonReady := True;
  PythonDir := ExtractFileDir(SelectedPython);
  UvPythonScriptsPath := PathJoin(PythonDir, 'Scripts\uv.exe');
  UvUserScriptsPath := ExpandConstant('{userappdata}\Python\Python312\Scripts\uv.exe');
  PythonStatusLabel.Caption := M('FieldPython') + ' ' + M('BundledPython');
  GitStatusLabel.Caption := M('FieldGit') + ' ' +
    StatusText(CommandOrFileAvailable('git', GitPath,
      ExpandConstant('{autopf}\Git\cmd\git.exe'), ''));
  if CommandOrFileAvailable('uv', UvStandalonePath, UvPythonScriptsPath, UvUserScriptsPath) or
     FileExists(UvPythonScriptsPath) then
    UvStatusLabel.Caption := M('UvDetected')
  else if PythonReady then
    UvStatusLabel.Caption := M('UvPrepareWithPython')
  else
    UvStatusLabel.Caption := M('UvWaitingForPython');
  CppStatusLabel.Caption := M('FieldCpp') + ' ' +
    StatusText(CmdAvailable('cl') or
      FileExists(ExpandConstant('{pf32}\Microsoft Visual Studio\Installer\vswhere.exe')));
  VbCableStatusLabel.Caption := 'VB-CABLE: ' + StatusText(VbCableAvailable()) +
    M('VbCableStatusHint');

  DetectedStack := InstallerGpuStackName();
  IsNvidia := (DetectedStack = 'cu126') or (DetectedStack = 'cu128');
  IsAmd := (DetectedStack = 'rocm10') or (DetectedStack = 'directml');
  CudaStatusLabel.Visible := IsNvidia;
  CudaDownloadButton.Visible := IsNvidia;
  DriverStatusLabel.Visible := IsNvidia or IsAmd;
  DriverDownloadButton.Visible := IsNvidia or IsAmd;
  if IsNvidia then
  begin
    CudaVersion := DetectedCudaVersion();
    CudaPath := CudaPathPage.Values[0];
    if CudaPath = '' then
      CudaPath := DefaultCudaToolkitDirForStack(DetectedStack);
    CudaDownloadButton.Caption := M1('DownloadCuda', CudaVersion);
    if CudaToolkitAvailable(CudaVersion, CudaPath) then
      CudaStatusLabel.Caption := 'CUDA Toolkit ' + CudaVersion + ': ' + M('Detected')
    else
      CudaStatusLabel.Caption := 'CUDA Toolkit ' + CudaVersion + ': ' + M('NotDetected');
  end
  else
  begin
    CudaStatusLabel.Caption := '';
    CudaDownloadButton.Caption := M('OpenCudaDownload');
  end;
  if IsAmd then
    DriverStatusLabel.Caption := M('AmdDriverConfirm')
  else if IsNvidia then
    DriverStatusLabel.Caption := M('NvidiaDriverConfirm')
  else
    DriverStatusLabel.Caption := '';
end;

procedure RefreshPrereqClick(Sender: TObject);
begin
  RefreshPrereqDownloadStatus;
end;

function RequiredPrereqMissing(): Boolean;
var
  DetectedStack, CudaPath: String;
begin
  Result := not CommandOrFileAvailable('git', ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe'),
      ExpandConstant('{autopf}\Git\cmd\git.exe'), '') or
    not (CmdAvailable('cl') or
      FileExists(ExpandConstant('{pf32}\Microsoft Visual Studio\Installer\vswhere.exe')));
  DetectedStack := InstallerGpuStackName();
  CudaPath := CudaPathPage.Values[0];
  if CudaPath = '' then
    CudaPath := DefaultCudaToolkitDirForStack(DetectedStack);
  if DetectedStack = 'cu128' then
    Result := Result or (not CudaToolkitAvailable(CudaToolkitBlackwellVersion, CudaPath))
  else if DetectedStack = 'cu126' then
    Result := Result or (not CudaToolkitAvailable(CudaToolkitPreBlackwellVersion, CudaPath));
end;

procedure SetEnvProgress(Position: Integer; const Detail: String);
begin
  if Position < 0 then
    Position := 0;
  if Position > 100 then
    Position := 100;
  EnvProgressCurrent := Position;
  WizardForm.ProgressGauge.Position := Position;
  if Detail <> '' then
    WizardForm.FilenameLabel.Caption := Detail;
  WizardForm.Update;
end;

procedure BeginEnvProgress(const Status: String; StartPos, EndPos: Integer);
begin
  EnvProgressStart := StartPos;
  EnvProgressEnd := EndPos;
  EnvProgressCurrent := StartPos;
  EnvProgressTicks := 0;
  EnvProgressMarkerSeen := False;
  WizardForm.StatusLabel.Caption := Status;
  SetEnvProgress(StartPos, Status);
end;

procedure AdvanceEnvProgress(const Detail: String);
var
  Span, NextPos: Integer;
begin
  Inc(EnvProgressTicks);
  Span := EnvProgressEnd - EnvProgressStart;
  if Span < 1 then
    Span := 1;
  NextPos := EnvProgressStart + (EnvProgressTicks mod Span);
  if NextPos >= EnvProgressEnd then
    NextPos := EnvProgressEnd - 1;
  if NextPos > EnvProgressCurrent then
    SetEnvProgress(NextPos, Detail)
  else if Detail <> '' then
    WizardForm.FilenameLabel.Caption := Detail;
end;

procedure FinishEnvProgress(const Detail: String);
begin
  SetEnvProgress(EnvProgressEnd, Detail);
end;

function ApplyProgressMarker(const Line: String): Boolean;
var
  Prefix, Rest, NumText, Detail: String;
  SpacePos, Percent, Span, Target: Integer;
begin
  Result := False;
  Prefix := '[XB-PROGRESS] ';
  if Copy(Line, 1, Length(Prefix)) = Prefix then
  begin
    Rest := Copy(Line, Length(Prefix) + 1, Length(Line));
    SpacePos := Pos(' ', Rest);
    if SpacePos > 0 then
    begin
      NumText := Copy(Rest, 1, SpacePos - 1);
      Detail := Trim(Copy(Rest, SpacePos + 1, Length(Rest)));
    end
    else
    begin
      NumText := Rest;
      Detail := '';
    end;

    Percent := StrToInt(NumText);
    if Percent < 0 then
      Percent := 0;
    if Percent > 100 then
      Percent := 100;

    Span := EnvProgressEnd - EnvProgressStart;
    if Span < 0 then
      Span := 0;
    Target := EnvProgressStart + (Span * Percent) div 100;
    if Target < EnvProgressCurrent then
      Target := EnvProgressCurrent;
    if Detail = '' then
      Detail := M('RunningInstallStep');

    EnvProgressMarkerSeen := True;
    SetEnvProgress(Target, TailText(Detail, 120));
    Result := True;
  end;
end;

procedure RefreshDetailsMemo();
begin
  if (DetailsMemo <> nil) and ShowInstallDetails() then
    DetailsMemo.Text := InstallDetailText;
  if (DetailsInfoLabel <> nil) and ShowInstallDetails() then
    DetailsInfoLabel.Caption := M1('FullLogFile', LastInstallLog);
end;

procedure AppendInstallDetail(const Line: String);
var
  DisplayLine: String;
begin
  DisplayLine := Line;
  if InstallDetailText = '' then
    InstallDetailText := DisplayLine
  else
    InstallDetailText := InstallDetailText + #13#10 + DisplayLine;
  InstallDetailText := TailText(InstallDetailText, 50000);
  LastInstallSummary := TailText(InstallDetailText, 1600);
  if ShowInstallDetails() then
  begin
    RefreshDetailsMemo();
    if Trim(DisplayLine) <> '' then
      WizardForm.FilenameLabel.Caption := TailText(DisplayLine, 120);
  end;
  if Trim(DisplayLine) <> '' then
  begin
    if not ApplyProgressMarker(DisplayLine) then
    begin
      if EnvProgressMarkerSeen then
        WizardForm.FilenameLabel.Caption := TailText(DisplayLine, 120)
      else
        AdvanceEnvProgress(TailText(DisplayLine, 120));
    end;
  end;
end;

procedure InstallOutputLog(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
begin
  Line := S;
  if Error then
    Line := '[err] ' + Line;
  if CurrentLogPath <> '' then
    SaveStringToFile(CurrentLogPath, Line + #13#10, True);
  AppendInstallDetail(Line);
end;

procedure ConsumeInstallLogChunk(const Chunk: String; var PendingLine: String);
var
  Line: String;
  NewLinePos: Integer;
begin
  if Chunk = '' then
    Exit;
  PendingLine := PendingLine + Chunk;
  while True do
  begin
    NewLinePos := Pos(#10, PendingLine);
    if NewLinePos = 0 then
      Break;
    Line := Copy(PendingLine, 1, NewLinePos - 1);
    Delete(PendingLine, 1, NewLinePos);
    if (Length(Line) > 0) and (Line[Length(Line)] = #13) then
      Delete(Line, Length(Line), 1);
    AppendInstallDetail(Line);
  end;
end;

function ReadInstallLogDelta(const LogPath: String; var SeenText, PendingLine: String): Boolean;
var
  LogText: AnsiString;
  CurrentText, Delta: String;
begin
  Result := False;
  if not LoadStringFromFile(LogPath, LogText) then
    Exit;
  CurrentText := String(LogText);
  if (Length(CurrentText) < Length(SeenText)) or
     (Copy(CurrentText, 1, Length(SeenText)) <> SeenText) then
  begin
    SeenText := '';
    PendingLine := '';
  end;
  Delta := Copy(CurrentText, Length(SeenText) + 1, Length(CurrentText));
  SeenText := CurrentText;
  if Delta <> '' then
  begin
    ConsumeInstallLogChunk(Delta, PendingLine);
    Result := True;
  end;
end;

procedure FlushInstallLogLine(var PendingLine: String);
begin
  if PendingLine <> '' then
  begin
    AppendInstallDetail(PendingLine);
    PendingLine := '';
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  PrereqPage := CreateInputOptionPage(
    wpWelcome,
    M('EnvironmentPageTitle'),
    M('EnvironmentPageSubtitle'),
    EnvironmentCheckSummary(),
    False,
    False
  );
  PrereqPage.Add(M('BuildRuntimeOption'));
  PrereqPage.Add(M('ConfigureEnvironmentOption'));
  PrereqPage.Add(M('ShowDetailsOption'));
  PrereqPage.Values[0] := True;
  PrereqPage.Values[1] := True;
  PrereqPage.Values[2] := False;

  GpuStackPage := CreateInputOptionPage(
    wpSelectDir,
    M('GpuPageTitle'),
    M('GpuPageSubtitle'),
    M('GpuPageDescription'),
    True,
    False
  );
  GpuStackPage.Add(M('GpuAuto'));
  GpuStackPage.Add(M('GpuCpu'));
  GpuStackPage.Add(M('GpuCuda126'));
  GpuStackPage.Add(M('GpuCuda128'));
  GpuStackPage.Add(M('GpuRocm10'));
  GpuStackPage.Values[0] := True;

  PrereqDownloadPage := CreateCustomPage(
    GpuStackPage.ID,
    M('DownloadPageTitle'),
    M('DownloadPageSubtitle')
  );

  PrereqDownloadIntro := TNewStaticText.Create(PrereqDownloadPage);
  PrereqDownloadIntro.AutoSize := False;
  PrereqDownloadIntro.WordWrap := True;
  PrereqDownloadIntro.Left := 0;
  PrereqDownloadIntro.Top := 0;
  PrereqDownloadIntro.Width := PrereqDownloadPage.SurfaceWidth;
  PrereqDownloadIntro.Height := ScaleY(48);
  PrereqDownloadIntro.Caption := M('DownloadPageIntro');
  PrereqDownloadIntro.Parent := PrereqDownloadPage.Surface;

  CreateDownloadRow(M('FieldPython'), M('DownloadPython'), 56, PythonStatusLabel, PythonDownloadButton);
  PythonDownloadButton.OnClick := @PythonDownloadClick;
  PythonDownloadButton.Enabled := False;
  CreateDownloadRow(M('FieldGit'), M('OpenGitDownload'), 88, GitStatusLabel, GitDownloadButton);
  GitDownloadButton.OnClick := @GitDownloadClick;
  CreateDownloadRow(M('FieldUv'), M('AutoInstall'), 120, UvStatusLabel, UvDownloadButton);
  UvDownloadButton.OnClick := @UvDownloadClick;
  UvDownloadButton.Enabled := False;
  CreateDownloadRow(M('FieldCpp'), M('OpenCppDownload'), 152, CppStatusLabel, CppDownloadButton);
  CppDownloadButton.OnClick := @CppDownloadClick;
  CreateDownloadRow(M('FieldCuda'), M('OpenCudaDownload'), 184, CudaStatusLabel, CudaDownloadButton);
  CudaDownloadButton.OnClick := @CudaDownloadClick;
  CreateDownloadRow(M('FieldDriver'), M('OpenDriverDownload'), 216, DriverStatusLabel, DriverDownloadButton);
  DriverDownloadButton.OnClick := @DriverDownloadClick;
  CreateDownloadRow(M('FieldVbCable'), M('OpenVbCableDownload'), 248, VbCableStatusLabel, VbCableDownloadButton);
  VbCableDownloadButton.OnClick := @VbCableDownloadClick;

  RefreshPrereqButton := TNewButton.Create(PrereqDownloadPage);
  RefreshPrereqButton.Width := ScaleX(150);
  RefreshPrereqButton.Height := ScaleY(28);
  RefreshPrereqButton.Left := PrereqDownloadPage.SurfaceWidth - RefreshPrereqButton.Width;
  RefreshPrereqButton.Top := ScaleY(286);
  RefreshPrereqButton.Caption := M('CheckAgain');
  RefreshPrereqButton.OnClick := @RefreshPrereqClick;
  RefreshPrereqButton.Parent := PrereqDownloadPage.Surface;

  PythonPathPage := CreateInputFilePage(
    PrereqDownloadPage.ID,
    M('PythonPageTitle'),
    M('PythonPageSubtitle'),
    M('PythonPageDescription')
  );
  PythonPathPage.Add(M('PythonExecutableLabel'),
    'Python executable|python.exe|Executable files|*.exe|All files|*.*', '.exe');
  // The app directory is not initialized during InitializeWizard. This page
  // is skipped for bundled-Python builds and gets its final path later.
  PythonPathPage.Values[0] := '';

  PrereqPathPage := CreateInputDirPage(
    PythonPathPage.ID,
    M('PrereqPathTitle'),
    M('PrereqPathSubtitle'),
    M('PrereqPathDescription'),
    False,
    ''
  );
  PrereqPathPage.Add(M('GitDirectoryLabel'));
  PrereqPathPage.Add(M('FfmpegDirectoryLabel'));
  PrereqPathPage.Add(M('CppDirectoryLabel'));

  CudaPathPage := CreateInputDirPage(
    PrereqPathPage.ID,
    M('CudaPathTitle'),
    M('CudaPathSubtitle'),
    M('CudaPathDescription'),
    False,
    ''
  );
  CudaPathPage.Add(M('CudaDirectoryLabel'));

  DataDirPage := CreateInputDirPage(
    CudaPathPage.ID,
    M('DataPageTitle'),
    M('DataPageSubtitle'),
    M('DataPageDescription'),
    False,
    ''
  );
  DataDirPage.Add(M('DataDirectoryLabel'));

  DetailsPage := CreateCustomPage(
    wpInstalling,
    M('DetailsPageTitle'),
    M('DetailsPageSubtitle')
  );

  DetailsInfoLabel := TNewStaticText.Create(DetailsPage);
  DetailsInfoLabel.AutoSize := False;
  DetailsInfoLabel.WordWrap := True;
  DetailsInfoLabel.Width := DetailsPage.SurfaceWidth;
  DetailsInfoLabel.Height := ScaleY(32);
  DetailsInfoLabel.Caption := M('DetailsWaiting');
  DetailsInfoLabel.Parent := DetailsPage.Surface;

  DetailsMemo := TNewMemo.Create(DetailsPage);
  DetailsMemo.Top := DetailsInfoLabel.Top + DetailsInfoLabel.Height + ScaleY(8);
  DetailsMemo.Width := DetailsPage.SurfaceWidth;
  DetailsMemo.Height := DetailsPage.SurfaceHeight - DetailsMemo.Top;
  DetailsMemo.ScrollBars := ssVertical;
  DetailsMemo.ReadOnly := True;
  DetailsMemo.Text := M('RuntimeNotStarted');
  DetailsMemo.Parent := DetailsPage.Surface;
end;

function RequestedGpuStackName(): String;
begin
  if '{#XB_PACKAGE_STACK}' <> 'universal' then
  begin
    Result := '{#XB_PACKAGE_STACK}';
    Exit;
  end;
  Result := 'auto';
  if GpuStackPage.Values[1] then
    Result := 'cpu'
  else if GpuStackPage.Values[2] then
    Result := 'cu126'
  else if GpuStackPage.Values[3] then
    Result := 'cu128'
  else if GpuStackPage.Values[4] then
    Result := 'rocm10';
end;

function GpuStackName(): String;
var
  Requested, Detected: String;
begin
  Requested := RequestedGpuStackName();
  if Requested <> 'auto' then
  begin
    Result := Requested;
    Exit;
  end;

  Detected := DetectedGpuStackName();
  if Detected = 'cpu' then
    Result := 'cpu'
  else
    Result := Detected;
end;

function GpuInstallArgs(): String;
var
  Requested, Stack: String;
begin
  Requested := RequestedGpuStackName();
  if Requested = 'cpu' then
    Result := '--cpu'
  else if Requested = 'cu128' then
    { RTX 50/Blackwell uses the validated two-layer shared layout:
      UVR+SeedVC+DDSP in core-cu128, and SVC+RVC+Vocal in svc-cu128. }
    Result := '--gpu --cu128 --consolidated --core-profile core-cu128'
  else if Requested = 'cu126' then
    Result := '--gpu --cu126 --consolidated'
  else if Requested = 'rocm10' then
    Result := '--rocm10'
  else if Requested = 'directml' then
    Result := '--directml'
  else
  begin
    Stack := GpuStackName();
    if Stack = 'cu128' then
      Result := '--gpu --cu128 --consolidated --core-profile core-cu128'
    else if Stack = 'cu126' then
      Result := '--gpu --cu126 --consolidated'
    else if Stack = 'rocm10' then
      Result := '--rocm10'
    else if Stack = 'directml' then
      Result := '--directml'
    else
      Result := '--cpu';
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = DataDirPage.ID then
  begin
    if DataDirPage.Values[0] = '' then
      DataDirPage.Values[0] := ExpandConstant('{app}\.xb_svcb');
  end;
  if CurPageID = PrereqPathPage.ID then
  begin
    if PrereqPathPage.Values[0] = '' then
      PrereqPathPage.Values[0] := ExpandConstant('{localappdata}\Programs\Git');
    if PrereqPathPage.Values[1] = '' then
      PrereqPathPage.Values[1] := ExpandConstant('{app}\tools\ffmpeg');
    if PrereqPathPage.Values[2] = '' then
      PrereqPathPage.Values[2] := ExpandConstant('{pf32}\Microsoft Visual Studio\2022\BuildTools');
  end;
  if CurPageID = PythonPathPage.ID then
    PythonPathPage.Values[0] := ExpandConstant('{app}\tools\python312\python.exe');
  if CurPageID = PrereqDownloadPage.ID then
  begin
    if CudaPathPage.Values[0] = '' then
      CudaPathPage.Values[0] := DefaultCudaToolkitDirForStack(InstallerGpuStackName());
    RefreshPrereqDownloadStatus;
  end;
  if CurPageID = CudaPathPage.ID then
  begin
    if (CudaPathPage.Values[0] = '') or
       ContainsText(CudaPathPage.Values[0], '\NVIDIA GPU Computing Toolkit\CUDA\v12.') then
    begin
      if (GetEnv('CUDA_PATH') <> '') and
         CudaToolkitAvailable(DetectedCudaVersion(), GetEnv('CUDA_PATH')) then
        CudaPathPage.Values[0] := GetEnv('CUDA_PATH')
      else
        CudaPathPage.Values[0] := DefaultCudaToolkitDirForStack(InstallerGpuStackName());
    end;
  end;
  if CurPageID = wpFinished then
  begin
    if LastInstallLog <> '' then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
        M1('FinishedLog', LastInstallLog);
    if LastInstallSummary <> '' then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
        M('LastLogSummary') + #13#10 + LastInstallSummary;
  end;
  if CurPageID = DetailsPage.ID then
    RefreshDetailsMemo();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = GpuStackPage.ID then
    Result := ('{#XB_PACKAGE_STACK}' <> 'universal') or (not BuildEnvSelected());
  if PageID = PythonPathPage.ID then
    Result := True;
  if (PageID = PrereqDownloadPage.ID) or (PageID = PrereqPathPage.ID) then
    Result := (not BuildEnvSelected()) and (not EnvConfigureSelected());
  if PageID = CudaPathPage.ID then
    Result := (not BuildEnvSelected()) or (not NvidiaGpuDetected());
  if PageID = DetailsPage.ID then
    Result := not ShowInstallDetails();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  DataDir: String;
begin
  Result := True;
  if CurPageID = PythonPathPage.ID then
  begin
    if not PythonFileAvailable(PythonPathPage.Values[0]) then
    begin
      MsgBox(M('InvalidPython'), mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
  if CurPageID = DataDirPage.ID then
  begin
    DataDir := ResolveInstallerDataDir(DataDirPage.Values[0]);
    if not ForceDirectories(DataDir) then
    begin
      MsgBox(M1('CannotCreateDataDir', DataDir), mbError, MB_OK);
      Result := False;
      Exit;
    end;
    DataDirPage.Values[0] := DataDir;
  end;
  if CurPageID = PrereqDownloadPage.ID then
  begin
    RefreshPrereqDownloadStatus;
    if RequiredPrereqMissing() then
      if MsgBox(M('MissingPrereqConfirm'), mbConfirmation, MB_YESNO) <> IDYES then
        Result := False;
  end;
end;

procedure WriteInstallerEnv();
var
  Payload, Stack, RuntimeLayout, SelectedPython, SelectedPythonDir: String;
begin
  Stack := GpuStackName();
  if (Stack = 'cu126') or (Stack = 'cu128') then
    RuntimeLayout := 'shared'
  else
    RuntimeLayout := 'isolated';
  SelectedPython := ExpandConstant('{app}\tools\python312\python.exe');
  SelectedPythonDir := ExtractFileDir(SelectedPython);
  Payload := '@echo off' + #13#10 +
    'set "XB_FROM_INSTALLER=1"' + #13#10 +
    'set "XB_ENV_CONFIGURE=' + BoolFlag(EnvConfigureSelected()) + '"' + #13#10 +
    'set "XB_GPU_STACK_REQUESTED=' + BatchEscape(RequestedGpuStackName()) + '"' + #13#10 +
    'set "XB_GPU_STACK=' + BatchEscape(Stack) + '"' + #13#10 +
    'set "XB_RUNTIME_LAYOUT=' + RuntimeLayout + '"' + #13#10 +
    'set "XB_PYTHON_EXE=' + BatchEscape(SelectedPython) + '"' + #13#10 +
    'set "XB_PYTHON_312_EXE=' + BatchEscape(SelectedPython) + '"' + #13#10 +
    'set "XB_PYTHON_DIR=' + BatchEscape(SelectedPythonDir) + '"' + #13#10 +
    'set "UV_PYTHON=' + BatchEscape(SelectedPython) + '"' + #13#10 +
    'set "UV_NO_MANAGED_PYTHON=1"' + #13#10 +
    'set "UV_PYTHON_DOWNLOADS=never"' + #13#10 +
    'set "XB_GIT_DIR=' + BatchEscape(PrereqPathPage.Values[0]) + '"' + #13#10 +
    'set "XB_FFMPEG_DIR=' + BatchEscape(PrereqPathPage.Values[1]) + '"' + #13#10 +
    'set "XB_CUDA_DIR=' + BatchEscape(CudaPathPage.Values[0]) + '"' + #13#10 +
    'set "XB_VSBT_DIR=' + BatchEscape(PrereqPathPage.Values[2]) + '"' + #13#10 +
    'set "XB_HF_MIRROR=https://hf-mirror.com"' + #13#10 +
    'set "HF_ENDPOINT=https://hf-mirror.com"' + #13#10 +
    'set "HUGGINGFACE_HUB_ENDPOINT=https://hf-mirror.com"' + #13#10 +
    'set "XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"' + #13#10 +
    'set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"' + #13#10 +
    'set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"' + #13#10 +
    'set "XB_WHEELHOUSE=' + BatchEscape(ExpandConstant('{app}\assets\wheels')) + '"' + #13#10 +
    'set "XB_WHEELHOUSE_STRICT=1"' + #13#10 +
    'set "UV_LINK_MODE=copy"' + #13#10 +
    'set "PIP_DISABLE_PIP_VERSION_CHECK=1"' + #13#10;
  SaveStringToFile(ExpandConstant('{app}\installer_env.cmd'), Payload, False);
end;

function RunSetupBatch(const BatchName, Args, Status: String; ProgressStart, ProgressEnd: Integer): Boolean;
var
  ResultCode, ProcessId: Integer;
  PollTicks: Integer;
  CmdLine, LogDir, LogPath, MarkerPath, StepName: String;
  SeenText, PendingLine, MarkerText: String;
  FinalLogText: AnsiString;
begin
  BeginEnvProgress(Status, ProgressStart, ProgressEnd);
  StepName := BatchName;
  StringChangeEx(StepName, '.bat', '', True);
  LogDir := ExpandConstant('{app}\install_logs');
  ForceDirectories(LogDir);
  LogPath := LogDir + '\' + StepName + '.log';
  MarkerPath := LogDir + '\' + StepName + '.exitcode';
  DeleteFile(MarkerPath);
  LastInstallLog := LogPath;
  CurrentLogPath := LogPath;
  SaveStringToFile(LogPath,
    'XB-SVCB installer step: ' + BatchName + #13#10 +
    'Started at: ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + #13#10 +
    'Command args: ' + Args + #13#10 +
    '------------------------------------------------------------' + #13#10,
    False);
  AppendInstallDetail('');
  AppendInstallDetail('============================================================');
  AppendInstallDetail(M1('LogStep', BatchName));
  AppendInstallDetail(M1('LogStarted', GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':')));
  AppendInstallDetail(M1('LogArguments', Args));
  AppendInstallDetail(M1('LogFile', LogPath));
  AppendInstallDetail('------------------------------------------------------------');
  WizardForm.FilenameLabel.Caption := M1('DetailsLog', LogPath);
  { Delayed expansion evaluates !errorlevel! after the batch returns. The
    marker avoids relying on ewNoWait's ResultCode, which can be 259 when the
    short-lived cmd wrapper has already exited before it is opened. }
  CmdLine := '/d /v:on /c call "' + ExpandConstant('{app}\') + BatchName + '"';
  if Args <> '' then
    CmdLine := CmdLine + ' ' + Args;
  CmdLine := CmdLine + ' >> "' + LogPath + '" 2>&1 & >"' + MarkerPath + '" echo !errorlevel!';
  ProcessId := 0;
  PollTicks := 0;
  SeenText := '';
  PendingLine := '';
  if LoadStringFromFile(LogPath, FinalLogText) then
    SeenText := FinalLogText;
  try
    { Start the batch asynchronously. The polling loop keeps the Inno window
      repainting while uv/pip performs long wheel installs. }
    Result := Exec(ExpandConstant('{cmd}'), CmdLine, ExpandConstant('{app}'),
      SW_HIDE, ewNoWait, ProcessId);
    if not Result then
    begin
      ResultCode := ProcessId;
      AppendInstallDetail('[installer] ' + SysErrorMessage(ResultCode));
    end;

    if Result then
    begin
      repeat
        ReadInstallLogDelta(LogPath, SeenText, PendingLine);
        Inc(PollTicks);
        if PollTicks >= 8 then
        begin
          PollTicks := 0;
          if EnvProgressCurrent < EnvProgressEnd - 1 then
            SetEnvProgress(EnvProgressCurrent + 1, M('RunningInstallStep'));
        end;
        WizardForm.Update;
        Sleep(250);
      until FileExists(MarkerPath);
      if LoadStringFromFile(MarkerPath, FinalLogText) then
      begin
        MarkerText := Trim(String(FinalLogText));
        ResultCode := StrToIntDef(MarkerText, -1);
      end
      else
        ResultCode := -1;
      ReadInstallLogDelta(LogPath, SeenText, PendingLine);
      FlushInstallLogLine(PendingLine);
    end;
  except
    AppendInstallDetail('[installer] ' + GetExceptionMessage);
    ResultCode := -1;
    Result := False;
  end;
  CurrentLogPath := '';
  if LoadStringFromFile(LogPath, FinalLogText) then
    LastInstallSummary := TailText(FinalLogText, 1600);
  if (not Result) or (ResultCode <> 0) then
  begin
    MsgBox(M3('BatchFailed', BatchName, IntToStr(ResultCode), LogPath), mbError, MB_OK);
    Result := False;
  end;
  if Result then
    FinishEnvProgress(M1('StepCompleted', Status));
end;

procedure AppendInstallValidation(const Line: String);
begin
  AppendInstallDetail(Line);
  if LastInstallLog <> '' then
    SaveStringToFile(LastInstallLog, Line + #13#10, True);
end;

function AddMissingRuntimeFile(const MissingText, ItemLabel, FilePath: String): String;
begin
  Result := MissingText;
  if Result <> '' then
    Result := Result + #13#10;
  Result := Result + ' - ' + ItemLabel + ': ' + FilePath;
end;

function ValidateBundledRuntime(): Boolean;
var
  AppDir, InternalDir, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  InternalDir := PathJoin(AppDir, '_internal');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M('BundledValidationTitle'));

  if not FileExists(PathJoin(AppDir, '{#MyAppExe}')) then
    Missing := AddMissingRuntimeFile(Missing, 'Application executable', PathJoin(AppDir, '{#MyAppExe}'));
  if not FileExists(PathJoin(InternalDir, 'web\dist\index.html')) then
    Missing := AddMissingRuntimeFile(Missing, 'Web frontend entry', PathJoin(InternalDir, 'web\dist\index.html'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\plugin_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python plugin worker', PathJoin(InternalDir, 'infrastructure\plugin_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'plugin_sdk_python\xb_svcb_plugin\__init__.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python plugin SDK', PathJoin(InternalDir, 'plugin_sdk_python\xb_svcb_plugin\__init__.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\uvr_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR worker', PathJoin(InternalDir, 'infrastructure\uvr_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\pymss_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'PyMSS worker', PathJoin(InternalDir, 'infrastructure\pymss_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\svc_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'SVC worker', PathJoin(InternalDir, 'infrastructure\svc_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\rvc_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'RVC worker', PathJoin(InternalDir, 'infrastructure\rvc_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\seedvc_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC worker', PathJoin(InternalDir, 'infrastructure\seedvc_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\ddsp_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC worker', PathJoin(InternalDir, 'infrastructure\ddsp_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\vocal_enhancement_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'AI vocal enhancement worker', PathJoin(InternalDir, 'infrastructure\vocal_enhancement_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\formant_pitch_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'High-note protection worker', PathJoin(InternalDir, 'infrastructure\formant_pitch_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\vocal_tuning_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'AI alignment and tuning worker', PathJoin(InternalDir, 'infrastructure\vocal_tuning_worker.py'));
  if not FileExists(PathJoin(AppDir, 'install\configure_user_env.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'User environment configuration tool', PathJoin(AppDir, 'install\configure_user_env.py'));
  if not FileExists(PathJoin(AppDir, 'install\detect_python.bat')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python runtime detector', PathJoin(AppDir, 'install\detect_python.bat'));
  if not PythonFileAvailable(PathJoin(AppDir, 'tools\python312\python.exe')) then
    Missing := AddMissingRuntimeFile(Missing, 'Bundled CPython 3.12 runtime', PathJoin(AppDir, 'tools\python312\python.exe'));
  if not FileExists(PathJoin(AppDir, 'tools\ffmpeg\bin\ffmpeg.exe')) then
    Missing := AddMissingRuntimeFile(Missing, 'Bundled FFmpeg executable', PathJoin(AppDir, 'tools\ffmpeg\bin\ffmpeg.exe'));
  if not FileExists(PathJoin(AppDir, 'tools\ffmpeg\bin\ffprobe.exe')) then
    Missing := AddMissingRuntimeFile(Missing, 'Bundled ffprobe executable', PathJoin(AppDir, 'tools\ffmpeg\bin\ffprobe.exe'));
  if not FileExists(PathJoin(AppDir, 'engines\so-vits-svc\inference\infer_tool.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'So-VITS-SVC bundled source', PathJoin(AppDir, 'engines\so-vits-svc\inference\infer_tool.py'));
  if not FileExists(PathJoin(AppDir, 'engines\seed-vc\inference.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC bundled source', PathJoin(AppDir, 'engines\seed-vc\inference.py'));
  if not FileExists(PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC bundled source', PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py'));
  if not FileExists(PathJoin(AppDir, 'assets\models\pretrain\rmvpe.pt')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC RMVPE', PathJoin(AppDir, 'assets\models\pretrain\rmvpe.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\pretrain\fcpe.pt')) then
    Missing := AddMissingRuntimeFile(Missing, 'High-range FCPE', PathJoin(AppDir, 'assets\models\pretrain\fcpe.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\campplus_cn_common.bin')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC CampPlus', PathJoin(AppDir, 'assets\models\seedvc\campplus_cn_common.bin'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\whisper-small\model.safetensors')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC Whisper Small', PathJoin(AppDir, 'assets\models\seedvc\whisper-small\model.safetensors'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\bigvgan_v2_44khz_128band_512x\bigvgan_generator.pt')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC BigVGAN', PathJoin(AppDir, 'assets\models\seedvc\bigvgan_v2_44khz_128band_512x\bigvgan_generator.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\checkpoints\model_120.ckpt.best')) then
    Missing := AddMissingRuntimeFile(Missing, 'DeepFilterNet weights', PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\checkpoints\model_120.ckpt.best'));
  if not FileExists(PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\config.ini')) then
    Missing := AddMissingRuntimeFile(Missing, 'DeepFilterNet configuration', PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\config.ini'));
  if not FileExists(PathJoin(AppDir, 'assets\wheels\wheelhouse.json')) then
    Missing := AddMissingRuntimeFile(Missing, 'Offline Python wheel manifest', PathJoin(AppDir, 'assets\wheels\wheelhouse.json'));
  { CUDA shared installs need the exact candidate/compatibility wheels that
    install_shared.py passes to uv. Keep this check at install time too, so
    an old or incomplete split package cannot report a false overall [ok]. }
  if (InstallerGpuStackName() = 'cu126') or (InstallerGpuStackName() = 'cu128') then
  begin
    if not FileExists(PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\numpy-2.2.6-cp312-cp312-win_amd64.whl')) then
      Missing := AddMissingRuntimeFile(Missing, 'CUDA shared-core NumPy candidate', PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\numpy-2.2.6-cp312-cp312-win_amd64.whl'));
    if not FileExists(PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\protobuf-7.36.0-cp310-abi3-win_amd64.whl')) then
      Missing := AddMissingRuntimeFile(Missing, 'CUDA shared-core protobuf candidate', PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\protobuf-7.36.0-cp310-abi3-win_amd64.whl'));
    if not FileExists(PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\tensorboardx-2.6.5-py3-none-any.whl')) then
      Missing := AddMissingRuntimeFile(Missing, 'CUDA shared-core TensorBoardX candidate', PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\tensorboardx-2.6.5-py3-none-any.whl'));
    if not FileExists(PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\onnx_weekly-1.23.0.dev20260831-cp312-abi3-win_amd64.whl')) then
      Missing := AddMissingRuntimeFile(Missing, 'CUDA shared-core ONNX Weekly candidate', PathJoin(AppDir, 'assets\runtime\core-cu128\candidate\onnx_weekly-1.23.0.dev20260831-cp312-abi3-win_amd64.whl'));
    if not FileExists(PathJoin(AppDir, 'assets\runtime\core-cu128\compat\descript_audiotools-0.7.2+xb1-py3-none-any.whl')) then
      Missing := AddMissingRuntimeFile(Missing, 'CUDA shared-core AudioTools compatibility wheel', PathJoin(AppDir, 'assets\runtime\core-cu128\compat\descript_audiotools-0.7.2+xb1-py3-none-any.whl'));
  end;
  if not FileExists(PathJoin(AppDir, 'engines\juce-vst3-host\xb-juce-vst3-host.exe')) then
    Missing := AddMissingRuntimeFile(Missing, 'JUCE VST3 Host', PathJoin(AppDir, 'engines\juce-vst3-host\xb-juce-vst3-host.exe'));

  Result := Missing = '';
  if Result then
    AppendInstallValidation(M('BundledValidationOk'))
  else
  begin
    AppendInstallValidation(M('BundledValidationFailed'));
    AppendInstallValidation(Missing);
    MsgBox(M1('BundledValidationDialog', Missing), mbError, MB_OK);
  end;
end;

function ValidatePluginRuntime(): Boolean;
var
  AppDir, InternalDir, PluginPython, PluginWorker, PluginSdk, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  InternalDir := PathJoin(AppDir, '_internal');
  PluginPython := PathJoin(AppDir, '.venv-plugins\Scripts\python.exe');
  PluginWorker := PathJoin(InternalDir, 'infrastructure\plugin_worker.py');
  PluginSdk := PathJoin(InternalDir, 'plugin_sdk_python\xb_svcb_plugin\__init__.py');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M1('RuntimeValidationTitle', M('PluginsName')));

  if not FileExists(PluginPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-plugins Python', PluginPython);
  if FileExists(PluginPython) and not PythonFileAvailable(PluginPython) then
    Missing := AddMissingRuntimeFile(Missing, M1('PythonNotRunnable', '.venv-plugins'), PluginPython);
  if not FileExists(PluginWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'Python plugin worker', PluginWorker);
  if not FileExists(PluginSdk) then
    Missing := AddMissingRuntimeFile(Missing, 'Python plugin SDK', PluginSdk);

  Result := Missing = '';
  if Result then
    AppendInstallValidation(M1('RuntimeReady', M('PluginsName')))
  else
  begin
    AppendInstallValidation(M1('RuntimeIncomplete', M('PluginsName')));
    AppendInstallValidation(Missing);
    AppendInstallValidation(M1('RepairSuggestion', 'setup_env.bat --only plugins'));
    MsgBox(M4('RuntimeValidationDialog', M('PluginsName'), Missing,
      'setup_env.bat --only plugins', LastInstallLog), mbError, MB_OK);
  end;
end;

function RuntimePython(const AppDir, Component, LegacyRelative: String): String;
var
  HelperPython, Resolver, Resolved, TempFile: String;
  ResultCode: Integer;
  Text: AnsiString;
begin
  Result := PathJoin(AppDir, LegacyRelative);
  Resolver := PathJoin(AppDir, 'install\runtime_manifest.py');
  { Runtime validation runs after environment setup, so use one of the newly
    created application environments rather than requiring a bundled Python. }
  HelperPython := PathJoin(AppDir, '.venv-plugins\Scripts\python.exe');
  if not PythonFileAvailable(HelperPython) then
    HelperPython := PathJoin(AppDir, '.venv-uvr\Scripts\python.exe');
  if not FileExists(Resolver) or not PythonFileAvailable(HelperPython) then
    Exit;
  { Match app routing: explicit override, manifest, then legacy. Never infer
    activation from a leftover core directory or the currently detected GPU.
    Let Python write the result itself so cmd.exe quoting/redirection cannot
    turn a valid manifest route into a silent legacy-path fallback. }
  TempFile := ExpandConstant('{tmp}\xb_svcb_runtime_' + Component + '.txt');
  DeleteFile(TempFile);
  if Exec(HelperPython, CmdPath(Resolver) +
      ' --root ' + CmdPath(AppDir) + ' --component ' + Component +
      ' --legacy ' + CmdPath(LegacyRelative) +
      ' --output-file ' + CmdPath(TempFile),
      AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode) and
      (ResultCode = 0) and LoadStringFromFile(TempFile, Text) then
    Resolved := Trim(String(Text))
  else
    Resolved := '';
  DeleteFile(TempFile);
  if (Resolved <> '') and FileExists(Resolved) then
    Result := Resolved;
end;

function ValidateUvrRuntime(): Boolean;
var
  AppDir, UvrPython, UvrWorker, UvrModel, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  UvrPython := RuntimePython(AppDir, 'uvr', '.venv-uvr\Scripts\python.exe');
  UvrWorker := PathJoin(AppDir, '_internal\infrastructure\uvr_worker.py');
  UvrModel := PathJoin(AppDir, 'models\uvr\5_HP-Karaoke-UVR.pth');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M1('RuntimeValidationTitle', 'UVR'));
  AppendInstallValidation(M1('InstallDirectory', AppDir));

  if not FileExists(UvrPython) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR Python', UvrPython);
  if FileExists(UvrPython) and not PythonFileAvailable(UvrPython) then
    Missing := AddMissingRuntimeFile(Missing, M1('PythonNotRunnable', 'UVR'), UvrPython);
  if not FileExists(UvrWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR worker', UvrWorker);
  if not FileExists(UvrModel) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR separation model', UvrModel);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation(M1('RuntimeReady', 'UVR'));
    Exit;
  end;

  AppendInstallValidation(M1('RuntimeIncomplete', 'UVR'));
  AppendInstallValidation(M('MissingItems'));
  AppendInstallValidation(Missing);
  AppendInstallValidation(M1('RepairSuggestion', 'setup_env.bat --only uvr seedvc ddsp models'));

  MsgBox(M4('RuntimeValidationDialog', 'UVR', Missing,
    'setup_env.bat --only uvr seedvc ddsp models', LastInstallLog), mbError, MB_OK);
end;

function ValidateSeedVcRuntime(): Boolean;
var
  AppDir, SeedPython, SeedWorker, SeedInference, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  SeedPython := RuntimePython(AppDir, 'seedvc', '.venv-seedvc\Scripts\python.exe');
  SeedWorker := PathJoin(AppDir, '_internal\infrastructure\seedvc_worker.py');
  SeedInference := PathJoin(AppDir, 'engines\seed-vc\inference.py');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M1('RuntimeValidationTitle', 'SeedVC'));

  if not FileExists(SeedPython) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC Python', SeedPython);
  if FileExists(SeedPython) and not PythonFileAvailable(SeedPython) then
    Missing := AddMissingRuntimeFile(Missing, M1('PythonNotRunnable', 'SeedVC'), SeedPython);
  if not FileExists(SeedWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC worker', SeedWorker);
  if not FileExists(SeedInference) then
    Missing := AddMissingRuntimeFile(Missing, 'Seed-VC inference.py', SeedInference);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation(M1('RuntimeReady', 'SeedVC'));
    Exit;
  end;

  AppendInstallValidation(M1('RuntimeIncomplete', 'SeedVC'));
  AppendInstallValidation(M('MissingItems'));
  AppendInstallValidation(Missing);
  AppendInstallValidation(M1('RepairSuggestion', 'setup_env.bat --only uvr seedvc ddsp'));

  MsgBox(M4('RuntimeValidationDialog', 'SeedVC', Missing,
    'setup_env.bat --only uvr seedvc ddsp', LastInstallLog), mbError, MB_OK);
end;

function ValidateDdspRuntime(): Boolean;
var
  AppDir, DdspPython, DdspWorker, DdspInference, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  DdspPython := RuntimePython(AppDir, 'ddsp', '.venv-ddsp\Scripts\python.exe');
  DdspWorker := PathJoin(AppDir, '_internal\infrastructure\ddsp_worker.py');
  DdspInference := PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M1('RuntimeValidationTitle', 'DDSP-SVC'));

  if not FileExists(DdspPython) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC Python', DdspPython);
  if FileExists(DdspPython) and not PythonFileAvailable(DdspPython) then
    Missing := AddMissingRuntimeFile(Missing, M1('PythonNotRunnable', 'DDSP-SVC'), DdspPython);
  if not FileExists(DdspWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC worker', DdspWorker);
  if not FileExists(DdspInference) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC main_reflow.py', DdspInference);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation(M1('RuntimeReady', 'DDSP-SVC'));
    Exit;
  end;

  AppendInstallValidation(M1('RuntimeIncomplete', 'DDSP-SVC'));
  AppendInstallValidation(M('MissingItems'));
  AppendInstallValidation(Missing);
  AppendInstallValidation(M1('RepairSuggestion', 'setup_env.bat --only uvr seedvc ddsp'));
end;

function ValidateVocalRuntime(): Boolean;
var
  AppDir, VocalPython, VocalWorker, TuningWorker, FormantWorker, VocalReady, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  VocalPython := RuntimePython(AppDir, 'vocal', '.venv-vocal\Scripts\python.exe');
  VocalWorker := PathJoin(AppDir, '_internal\infrastructure\vocal_enhancement_worker.py');
  TuningWorker := PathJoin(AppDir, '_internal\infrastructure\vocal_tuning_worker.py');
  FormantWorker := PathJoin(AppDir, '_internal\infrastructure\formant_pitch_worker.py');
  VocalReady := PathJoin(AppDir, 'models\vocal-enhancement\runtime.ready');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M1('RuntimeValidationTitle', M('VocalName')));

  if not FileExists(VocalPython) then
    Missing := AddMissingRuntimeFile(Missing, M('VocalName') + ' Python', VocalPython);
  if FileExists(VocalPython) and not PythonFileAvailable(VocalPython) then
    Missing := AddMissingRuntimeFile(Missing, M1('PythonNotRunnable', M('VocalName')), VocalPython);
  if not FileExists(VocalWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'AI vocal enhancement worker', VocalWorker);
  if not FileExists(TuningWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'AI alignment and tuning worker', TuningWorker);
  if not FileExists(FormantWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'High-note protection worker', FormantWorker);
  if not FileExists(VocalReady) then
    Missing := AddMissingRuntimeFile(Missing, 'runtime.ready marker', VocalReady);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation(M1('RuntimeReady', M('VocalName')));
    Exit;
  end;

  AppendInstallValidation(M1('RuntimeIncomplete', M('VocalName')));
  AppendInstallValidation(M('MissingItems'));
  AppendInstallValidation(Missing);
  AppendInstallValidation(M1('RepairSuggestion', 'setup_env.bat --only vocal'));
end;

function ValidateTorchRuntime(const PythonPath, RuntimeLabel: String;
  RequireDirectML: Boolean): Boolean;
var
  ResultCode: Integer;
  CheckCode: String;
begin
  Result := False;
  if not FileExists(PythonPath) then
  begin
    AppendInstallValidation(M2('TorchMissingPython', RuntimeLabel, PythonPath));
    Exit;
  end;

  if GpuStackName() = 'rocm10' then
    CheckCode := 'import torch; assert getattr(torch.version,''hip'',None); assert str(getattr(torch.version,''rocm'','''')).split(''.'')[0] == ''10''; assert torch.cuda.is_available(); assert (torch.ones(4,device=''cuda'')*2).sum().cpu().item() == 8'
  else if (GpuStackName() = 'cu126') or (GpuStackName() = 'cu128') then
    CheckCode := 'import torch; assert hasattr(torch,''__version__''); assert torch.cuda.is_available()'
  else if (GpuStackName() = 'directml') and RequireDirectML then
    CheckCode := 'import torch,torch_directml; assert torch_directml.is_available(); x=torch.ones(1,device=torch_directml.device()); assert x.cpu().item() == 1'
  else
    CheckCode := 'import torch; assert hasattr(torch,''__version__'')';

  Result := Exec(PythonPath, '-c "' + CheckCode + '"', ExpandConstant('{app}'),
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if Result then
    AppendInstallValidation(M1('TorchReady', RuntimeLabel))
  else
    AppendInstallValidation(M1('TorchInvalid', RuntimeLabel));
end;

function ValidateAllInferenceRuntimes(): Boolean;
var
  AppDir: String;
  CurrentReady: Boolean;
begin
  AppDir := ExpandConstant('{app}');
  Result := True;
  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation(M('TorchValidationTitle'));

  CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'uvr', '.venv-uvr\Scripts\python.exe'), 'UVR', True);
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'svc', '.venv-svc\Scripts\python.exe'), 'So-VITS-SVC', True);
  Result := Result and CurrentReady;
  if GpuStackName() = 'directml' then
    CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'rvc-directml', '.venv-rvc-directml\Scripts\python.exe'), 'RVC', True)
  else
    CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'rvc', '.venv-rvc\Scripts\python.exe'), 'RVC', True);
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'seedvc', '.venv-seedvc\Scripts\python.exe'), 'SeedVC', True);
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'ddsp', '.venv-ddsp\Scripts\python.exe'), 'DDSP-SVC', True);
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-ddsp-legacy\Scripts\python.exe'), 'DDSP-SVC legacy', False);
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(RuntimePython(AppDir, 'vocal', '.venv-vocal\Scripts\python.exe'), M('VocalName'), False);
  Result := Result and CurrentReady;

  if not Result then
    MsgBox(M1('AllRuntimeFailed', LastInstallLog), mbError, MB_OK);
end;

procedure CleanupBundledWheelhouse();
var
  WheelhouseDir: String;
begin
  WheelhouseDir := ExpandConstant('{app}\assets\wheels');
  if not DirExists(WheelhouseDir) then
  begin
    AppendInstallValidation(M('WheelsAlreadyRemoved'));
    Exit;
  end;
  if DelTree(WheelhouseDir, True, True, True) then
  begin
    AppendInstallValidation(M1('WheelsRemoved', WheelhouseDir));
    SetEnvProgress(100, M('RuntimeCacheCleaned'));
  end
  else
    AppendInstallValidation(M1('WheelsCleanupFailed', WheelhouseDir));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir, Payload: String;
  SetupProgressStart: Integer;
  PrereqsReady, PluginReady, UvrReady, SeedVcReady, DdspReady, VocalReady, InferenceReady: Boolean;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := ResolveInstallerDataDir(DataDirPage.Values[0]);
    ForceDirectories(DataDir);
    Payload := '{' + #13#10 +
      '  "data_dir": "' + JsonEscape(DataDir) + '"' + #13#10 +
      '}' + #13#10;
    SaveStringToFile(ExpandConstant('{app}\data_home.json'), Payload, False);
    ForceDirectories(ExpandConstant('{userappdata}\XB-SVCB'));
    SaveStringToFile(ExpandConstant('{userappdata}\XB-SVCB\data_home.json'), Payload, False);

    ValidateBundledRuntime();

    if BuildEnvSelected() or EnvConfigureSelected() then
    begin
      SetEnvProgress(0, M('RuntimePreparing'));
      WriteInstallerEnv();
      PrereqsReady := True;
      if EnvConfigureSelected() then
      begin
        if BuildEnvSelected() then
          SetupProgressStart := 35
        else
          SetupProgressStart := 100;
        PrereqsReady := RunSetupBatch('install_prereqs.bat', '', M('PrereqsConfiguring'), 0, SetupProgressStart);
      end
      else
        SetupProgressStart := 0;
      if BuildEnvSelected() and PrereqsReady and
         RunSetupBatch('setup_env.bat', GpuInstallArgs(), M('RuntimeBuilding'), SetupProgressStart, 100) then
      begin
        PluginReady := ValidatePluginRuntime();
        UvrReady := ValidateUvrRuntime();
        SeedVcReady := ValidateSeedVcRuntime();
        DdspReady := ValidateDdspRuntime();
        VocalReady := ValidateVocalRuntime();
        InferenceReady := ValidateAllInferenceRuntimes();
        if (not PluginReady) or (not UvrReady) or (not SeedVcReady) or (not DdspReady) or (not VocalReady) or
           (not InferenceReady) then
          SetEnvProgress(100, M('RuntimeValidationPartial'))
        else
          CleanupBundledWheelhouse();
      end;
    end;
  end;
end;
