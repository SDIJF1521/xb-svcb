; ============================================================
;  XB-SVCB · AI 翻唱工具  安装脚本（Inno Setup 6+）
;
;  编译方式（开发者侧）：
;    1) 先构建前端：在 web/ 执行 npm ci && npm run build
;    2) 再用 PyInstaller 打出应用 exe：pyinstaller installer/xb-svcb-app.spec（产物 dist/XB-SVCB/）
;       （以上两步可用 installer/build.ps1 一键完成）
;    3) 安装 Inno Setup（含 ISCC.exe）：https://jrsoftware.org/isinfo.php
;    4) 用 ISCC 编译本脚本，产物在 dist/XB-SVCB-Setup.exe
;
;  安装器在用户机上的行为：
;    - 释放打包好的应用本体 XB-SVCB.exe（前端与 worker 已内置，无需 Python 也能起界面）
;    - 可选“搭建运行环境”：联网创建 .venv / 下载依赖与模型（由 setup_env.bat 调 install.py，全程无 PowerShell）
;    - 创建开始菜单与桌面快捷方式（指向 XB-SVCB.exe）
;
;  用户机前置：仅「搭建运行环境」这一步需要 Python 3.10+ 与 ffmpeg（在 PATH）。Git 可选（缺失时自动下载 ZIP）。
;  应用界面本身由 exe 自带，无需 Node / Python。
; ============================================================

#define MyAppName "XB-SVCB AI 翻唱工具"
#define MyAppShort "XB-SVCB"
#define MyAppVersion "0.0.6"
#define MyAppPublisher "XB-SVCB"
#define MyAppExe "XB-SVCB.exe"

[Setup]
AppId={{B9C2F4E7-1A3D-4E6B-9C8A-2F5D7E1B3A40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
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
OutputBaseFilename=XB-SVCB-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 安装器与卸载项图标
SetupIconFile=..\assets\icon\xb-svcb.ico
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
; 默认使用随 Inno 自带的 Default.isl，保证任何机器都能编译。
; 如需简体中文向导：把 ChineseSimplified.isl 放入 Inno 的 Languages 目录后，
; 取消下一行注释（该翻译为非官方语言包，需自行下载）。
; Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkablealone
Name: "buildenv"; Description: "安装后立即搭建运行环境（创建 AI 子环境、复制自带模型；仅 Python 依赖需联网，耗时较长）"; GroupDescription: "运行环境:"

[Files]
; 应用本体：PyInstaller 打包产物（XB-SVCB.exe + _internal，含前端与 worker 脚本）
Source: "..\dist\XB-SVCB\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 环境搭建脚本（纯 batch + Python，安装过程不涉及 PowerShell）
Source: "..\install\*"; DestDir: "{app}\install"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "\__pycache__\*"
Source: "..\setup_env.bat"; DestDir: "{app}"; Flags: ignoreversion
; 应用图标（供 .bat 快捷方式引用；exe 已内嵌同一图标）
Source: "..\assets\icon\xb-svcb.ico"; DestDir: "{app}"; Flags: ignoreversion
; 自带底模与 UVR 模型（随安装包分发；安装时由 install.py 本地复制，免联网慢下载）
; 模型为已压缩的二进制权重，用 nocompression 跳过再压缩，显著加快编译与安装速度
; 排除可选的 fcpe.pt（默认 F0 用 rmvpe），让安装器体积压到 GitHub Release 单文件 2GiB 上限内
Source: "..\assets\models\*"; DestDir: "{app}\assets\models"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression; Excludes: "fcpe.pt"
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\搭建/修复运行环境"; Filename: "{app}\setup_env.bat"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\卸载 {#MyAppShort}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\xb-svcb.ico"

[Run]
; 安装结束后按勾选搭建环境（前端已预构建，跳过 web 步骤）。由 setup_env.bat 调 install.py，控制台保留便于查看日志。
Filename: "{app}\setup_env.bat"; \
  WorkingDir: "{app}"; Flags: shellexec skipifsilent; Tasks: buildenv; \
  StatusMsg: "正在搭建运行环境（创建子环境、复制自带模型、联网装 Python 依赖）…"
; 提供安装完成后直接启动选项（默认不勾）
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 {#MyAppShort}"; \
  WorkingDir: "{app}"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; 卸载时清理安装目录内生成的环境与下载物（用户数据在 ~/.xb-svcb，保留）
Type: filesandordirs; Name: "{app}\.venv-uvr"
Type: filesandordirs; Name: "{app}\.venv-svc"
Type: filesandordirs; Name: "{app}\.venv-hub"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\models"

[Code]
function CmdAvailable(const Exe: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/c where ' + Exe + ' >nul 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  Missing: String;
begin
  Missing := '';
  if not CmdAvailable('python') and not CmdAvailable('py') then
    Missing := Missing + '  • Python 3.10+  (https://www.python.org/downloads/)' + #13#10;
  if not CmdAvailable('ffmpeg') then
    Missing := Missing + '  • ffmpeg  (https://www.gyan.dev/ffmpeg/builds/)' + #13#10;
  { Git 为可选：缺失时安装器会自动改用下载 ZIP 获取 so-vits-svc，无需安装 Git }

  if Missing <> '' then
    MsgBox('检测到以下运行环境未安装（不影响复制文件，但“搭建运行环境”步骤会失败）：'
      + #13#10#13#10 + Missing + #13#10
      + '建议先安装并加入 PATH，再勾选安装结束时的“搭建运行环境”。'
      + #13#10 + '也可稍后从开始菜单的“搭建/修复运行环境”重试。',
      mbInformation, MB_OK);

  Result := True;
end;
