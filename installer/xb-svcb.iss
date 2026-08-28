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
;    - 可选“搭建运行环境”：检测前置依赖，联网创建 .venv / 下载依赖与模型（由 batch 调 install.py）
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

#define MyAppName "XB-SVCB AI 翻唱工具"
#define MyAppShort "XB-SVCB"
#define MyAppVersion "0.0.30"
#define MyAppPublisher "XB-SVCB"
#define MyAppExe "XB-SVCB.exe"

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
OutputBaseFilename=XB-SVCB-Setup
; 自带模型超过单个安装文件上限，显式输出 bootstrapper + 小于 2GB 的分卷数据文件。
; 发布时 XB-SVCB-Setup.exe 与所有 XB-SVCB-Setup-*.bin 必须放在同一目录。
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
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

#ifndef XB_VALIDATE_ONLY
[Files]
; 应用本体：PyInstaller 打包产物（XB-SVCB.exe + _internal，含前端与 worker 脚本）
Source: "..\dist\XB-SVCB\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 环境搭建脚本（纯 batch + Python，安装过程不涉及 PowerShell）
Source: "..\install\install.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\configure_user_env.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\detect_python.bat"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\setup_env.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_prereqs.bat"; DestDir: "{app}"; Flags: ignoreversion
; 应用图标（供 .bat 快捷方式引用；exe 已内嵌同一图标）
Source: "..\assets\icon\xb-svcb.ico"; DestDir: "{app}"; Flags: ignoreversion
; FFmpeg 随分卷离线携带。系统 PATH 已有 ffmpeg 时跳过释放；否则安装到应用 tools 目录。
Source: "..\assets\tools\ffmpeg\*"; DestDir: "{app}\tools\ffmpeg"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression skipifsourcedoesntexist; Check: not SystemFfmpegAvailable
; 三个歌声引擎源码随分卷携带。模型由 assets/models 统一提供，排除仓库元数据、缓存、
; 示例与重复权重，安装后 install.py 会检测到源码并跳过 Git/ZIP 获取。
Source: "..\.tmp\bundled-engines\so-vits-svc\*"; DestDir: "{app}\engines\so-vits-svc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\.tmp\bundled-engines\ddsp-svc\*"; DestDir: "{app}\engines\ddsp-svc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\.tmp\bundled-engines\seed-vc\*"; DestDir: "{app}\engines\seed-vc"; Flags: recursesubdirs createallsubdirs ignoreversion
; 自带底模与 UVR 模型（随安装包分发；安装时由 install.py 本地复制，免联网慢下载）
; 模型为已压缩的二进制权重，用 nocompression 跳过再压缩，显著加快编译与安装速度
; FCPE 用于检测到极高音时自动扩展 F0 覆盖；分卷仍由 DiskSliceSize 控制在 2 GB 内
Source: "..\assets\models\*"; DestDir: "{app}\assets\models"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
; Python 依赖 wheelhouse：安装/修复运行环境时按 Python 版本与 GPU 栈自动选择 whl 离线安装
Source: "..\assets\wheels\*"; DestDir: "{app}\assets\wheels"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\release-notes\release_notes_v030.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion
Source: "..\docs\api.md"; DestDir: "{app}\docs"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\搭建/修复运行环境"; Filename: "{app}\setup_env.bat"; WorkingDir: "{app}"; IconFilename: "{app}\xb-svcb.ico"
Name: "{group}\卸载 {#MyAppShort}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\xb-svcb.ico"

[Run]
; 提供安装完成后直接启动选项（默认不勾）
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 {#MyAppShort}"; \
  WorkingDir: "{app}"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; 卸载时清理安装目录内生成的环境与下载物（用户数据在 .xb_svcb，保留）
Type: filesandordirs; Name: "{app}\.venv-uvr"
Type: filesandordirs; Name: "{app}\.venv-plugins"
Type: filesandordirs; Name: "{app}\.venv-svc"
Type: filesandordirs; Name: "{app}\.venv-rvc"
Type: filesandordirs; Name: "{app}\.venv-seedvc"
Type: filesandordirs; Name: "{app}\.venv-ddsp"
Type: filesandordirs; Name: "{app}\.venv-hub"
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
    '-c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function CommandOutput(const CommandLine: String): String; forward;

function PythonPathCommandAvailable(const CommandName: String): Boolean;
var
  Output, Line, LowerLine: String;
  NewLinePos: Integer;
begin
  Result := False;
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
      Result := True;
      Exit;
    end;
  end;
end;

function PythonAvailable(const CustomDir: String): Boolean;
begin
  Result := False;
  if (CustomDir <> '') and PythonFileAvailable(PathJoin(CustomDir, 'python.exe')) then
  begin
    Result := True;
    Exit;
  end;
  if PythonFileAvailable(ExpandConstant('{localappdata}\Programs\Python\Python310\python.exe')) then
  begin
    Result := True;
    Exit;
  end;
  if CmdAvailable('py') and CommandSucceeds(
      'py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"') then
  begin
    Result := True;
    Exit;
  end;
  Result := PythonPathCommandAvailable('python');
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
    Result := 'cu121'
  else if ContainsText(Names, 'AMD') or ContainsText(Names, 'Radeon') then
    Result := 'directml';
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
    if Caps <> '' then
    begin
      if HasComputeMajorAtLeast(Caps, 12) then
        Result := 'cu128'
      else if HasComputeMajorAtLeast(Caps, 5) then
        Result := 'cu121';
    end;

    if Result = 'cpu' then
    begin
      Names := CommandOutput(CmdPath(Smi) + ' --query-gpu=name --format=csv,noheader');
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

function CudaToolkitVersionForStack(const Stack: String): String;
begin
  { 这里必须只返回固定的推荐版本，不能从系统 nvcc 输出推导版本。 }
  if Stack = 'cu128' then
    Result := CudaToolkitBlackwellVersion
  else if Stack = 'cu121' then
    Result := CudaToolkitPreBlackwellVersion
  else
    Result := '';
end;

function CudaToolkitDownloadUrlForStack(const Stack: String): String;
begin
  { 下载链接同样固定，不能跟随系统已安装的 CUDA 版本变化。 }
  if Stack = 'cu128' then
    Result := CudaToolkitBlackwellUrl
  else if Stack = 'cu121' then
    Result := CudaToolkitPreBlackwellUrl
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
  Result := ContainsText(Output, 'release ' + Version);
end;

function CudaToolkitAvailable(const Version, ToolkitDir: String): Boolean;
begin
  Result :=
    CudaNvccMatchesVersion(CudaNvccPath(Version), Version) or
    ((ToolkitDir <> '') and CudaNvccMatchesVersion(ToolkitDir + '\bin\nvcc.exe', Version)) or
    (CmdAvailable('nvcc') and ContainsText(CommandOutput('nvcc --version 2>&1'), 'release ' + Version));
end;

function GpuStackLabel(const Stack: String): String;
begin
  if Stack = 'cu128' then
    Result := 'NVIDIA 50 系 / Blackwell，固定使用 CUDA 12.8（cu128 torch）'
  else if Stack = 'cu121' then
    Result := 'NVIDIA 50 系以下兼容显卡，固定使用 CUDA 12.6（PyMSS 使用 cu126）'
  else if Stack = 'directml' then
    Result := 'AMD Radeon，使用 DirectML 与 torch-directml'
  else
    Result := 'CPU 或未检测到兼容 GPU，安装 CPU 版 torch';
end;

function NvidiaGpuDetected(): Boolean;
var
  Stack: String;
begin
  Stack := DetectedGpuStackName();
  Result := (Stack = 'cu121') or (Stack = 'cu128');
end;

function DetectedCudaVersion(): String;
begin
  Result := CudaToolkitVersionForStack(DetectedGpuStackName());
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
    Result := '已检测到'
  else
    Result := '未检测到';
end;

function EnvironmentCheckSummary(): String;
var
  DetectedStack: String;
begin
  DetectedStack := DetectedGpuStackName();
  Result :=
    '安装器会先检查运行环境，再进入安装路径选择。当前检测结果：' + #13#10 +
    '  Python 3.10+：' + StatusText(PythonAvailable('')) + #13#10 +
    '  Git：' + StatusText(CmdAvailable('git')) + #13#10 +
    '  ffmpeg / ffprobe：' + StatusText(SystemFfmpegAvailable()) + '（未检测到时使用安装包内置版本）' + #13#10 +
    '  uv：' + StatusText(CmdAvailable('uv')) + '（Python 可用后自动安装）' + #13#10;
  if (DetectedStack = 'cu121') or (DetectedStack = 'cu128') then
    Result := Result + '  CUDA Toolkit ' + DetectedCudaVersion() + '：' +
      StatusText(CudaToolkitAvailable(DetectedCudaVersion(), '')) + #13#10;
  Result := Result +
    '  VB-CABLE：' + StatusText(VbCableAvailable()) + '（系统音频变声可选，未安装时请手动安装）' + #13#10 +
    '  JUCE VST3 Host：随安装包内置，安装后检查' + #13#10 +
    '  GPU 推理栈：' + GpuStackLabel(DetectedStack) + #13#10 +
    '前置依赖采用用户辅助模式：安装器不会自动下载或安装系统组件；uv 会在检测到 Python 后通过 pip 自动安装。下一页可打开对应下载页面，完成后返回并重新检测。';
end;

procedure OpenDownloadUrl(const URL: String);
var
  ErrorCode: Integer;
begin
  if not ShellExec('open', URL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox('无法打开下载页面：' + URL + #13#10 +
      '请复制链接到浏览器中打开。', mbError, MB_OK);
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
  MsgBox('uv 会在检测到 Python 3.10+ 后自动安装到当前用户目录，无需手动下载。',
    mbInformation, MB_OK);
end;

procedure CppDownloadClick(Sender: TObject);
begin
  OpenDownloadUrl('https://visualstudio.microsoft.com/visual-cpp-build-tools/');
end;

procedure CudaDownloadClick(Sender: TObject);
var
  Url: String;
begin
  Url := CudaToolkitDownloadUrlForStack(DetectedGpuStackName());
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
  if GpuStackName() = 'directml' then
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
  IsNvidia, IsDirectml, PythonReady: Boolean;
  DetectedStack, CudaVersion, GitPath: String;
  UserProfilePath, UvStandalonePath, UvPythonScriptsPath, UvUserScriptsPath: String;
begin
  GitPath := ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe');
  UserProfilePath := GetEnv('USERPROFILE');
  if UserProfilePath <> '' then
    UvStandalonePath := PathJoin(UserProfilePath, '.local\bin\uv.exe')
  else
    UvStandalonePath := '';
  UvPythonScriptsPath := ExpandConstant('{localappdata}\Programs\Python\Python310\Scripts\uv.exe');
  UvUserScriptsPath := ExpandConstant('{userappdata}\Python\Python310\Scripts\uv.exe');
  PythonReady := PythonAvailable(PrereqPathPage.Values[0]);
  PythonStatusLabel.Caption := 'Python 3.10+：' +
    StatusText(PythonReady);
  GitStatusLabel.Caption := 'Git：' +
    StatusText(CommandOrFileAvailable('git', GitPath,
      ExpandConstant('{autopf}\Git\cmd\git.exe'), ''));
  if CommandOrFileAvailable('uv', UvStandalonePath, UvPythonScriptsPath, UvUserScriptsPath) or
     FileExists(PrereqPathPage.Values[0] + '\Scripts\uv.exe') then
    UvStatusLabel.Caption := 'uv：已检测到'
  else if PythonReady then
    UvStatusLabel.Caption := 'uv：Python 可用，安装时自动安装'
  else
    UvStatusLabel.Caption := 'uv：等待 Python 安装完成后自动安装';
  CppStatusLabel.Caption := 'Microsoft C++ Build Tools：' +
    StatusText(CmdAvailable('cl') or
      FileExists(ExpandConstant('{pf32}\Microsoft Visual Studio\Installer\vswhere.exe')));
  VbCableStatusLabel.Caption := 'VB-CABLE：' + StatusText(VbCableAvailable()) +
    '（系统音频变声需要；普通歌曲翻唱不需要）';

  DetectedStack := DetectedGpuStackName();
  IsNvidia := (DetectedStack = 'cu121') or (DetectedStack = 'cu128');
  IsDirectml := DetectedStack = 'directml';
  CudaStatusLabel.Visible := IsNvidia;
  CudaDownloadButton.Visible := IsNvidia;
  DriverStatusLabel.Visible := IsNvidia or IsDirectml;
  DriverDownloadButton.Visible := IsNvidia or IsDirectml;
  if IsNvidia then
  begin
    CudaVersion := DetectedCudaVersion();
    CudaDownloadButton.Caption := '下载 CUDA ' + CudaVersion;
    if CudaToolkitAvailable(CudaVersion, CudaPathPage.Values[0]) then
      CudaStatusLabel.Caption := 'CUDA Toolkit ' + CudaVersion + '：已检测到'
    else
      CudaStatusLabel.Caption := 'CUDA Toolkit ' + CudaVersion + '：未检测到';
  end
  else
  begin
    CudaStatusLabel.Caption := '';
    CudaDownloadButton.Caption := '打开 CUDA 下载';
  end;
  if IsDirectml then
    DriverStatusLabel.Caption := 'AMD Radeon 驱动：请确认已安装'
  else if IsNvidia then
    DriverStatusLabel.Caption := 'NVIDIA 显卡驱动：请确认已安装'
  else
    DriverStatusLabel.Caption := '';
end;

procedure RefreshPrereqClick(Sender: TObject);
begin
  RefreshPrereqDownloadStatus;
end;

function RequiredPrereqMissing(): Boolean;
begin
  Result := not PythonAvailable(PrereqPathPage.Values[0]) or
    not CommandOrFileAvailable('git', ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe'),
      ExpandConstant('{autopf}\Git\cmd\git.exe'), '') or
    not (CmdAvailable('cl') or
      FileExists(ExpandConstant('{pf32}\Microsoft Visual Studio\Installer\vswhere.exe')));
  if DetectedGpuStackName() = 'cu128' then
    Result := Result or (not CudaToolkitAvailable(CudaToolkitBlackwellVersion, CudaPathPage.Values[0]))
  else if DetectedGpuStackName() = 'cu121' then
    Result := Result or (not CudaToolkitAvailable(CudaToolkitPreBlackwellVersion, CudaPathPage.Values[0]));
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
      Detail := '正在执行安装步骤...';

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
    DetailsInfoLabel.Caption := '完整日志文件：' + LastInstallLog;
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

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  PrereqPage := CreateInputOptionPage(
    wpWelcome,
    '环境检查与前置依赖',
    '先检查运行环境，再选择安装路径',
    EnvironmentCheckSummary(),
    False,
    False
  );
  PrereqPage.Add('安装后立即搭建运行环境（创建 AI 子环境、复制自带模型；仅 Python 依赖需联网，耗时较长）');
  PrereqPage.Add('配置 PATH / CUDA_PATH / VSINSTALLDIR 等用户环境变量（不安装软件）');
  PrereqPage.Add('在安装器窗口显示详细安装信息（可选；完整日志仍会写入安装目录）');
  PrereqPage.Values[0] := True;
  PrereqPage.Values[1] := True;
  PrereqPage.Values[2] := False;

  GpuStackPage := CreateInputOptionPage(
    wpSelectDir,
    'GPU 推理栈',
    '选择本机要使用的推理依赖栈',
    '安装器会复核实际显卡：NVIDIA 使用匹配的 CUDA 栈，AMD Radeon 使用 DirectML；没有兼容 GPU 时安装 CPU 版。',
    True,
    False
  );
  GpuStackPage.Add('自动检测（推荐）');
  GpuStackPage.Add('CPU 模式');
  GpuStackPage.Add('NVIDIA 50 系以下：CUDA 12.6（PyMSS cu126）');
  GpuStackPage.Add('NVIDIA 50 系 Blackwell：CUDA 12.8（cu128）');
  GpuStackPage.Add('AMD Radeon：DirectML');
  GpuStackPage.Values[0] := True;

  PrereqDownloadPage := CreateCustomPage(
    GpuStackPage.ID,
    '下载前置依赖',
    '系统依赖由用户安装，uv 在 Python 可用后自动安装'
  );

  PrereqDownloadIntro := TNewStaticText.Create(PrereqDownloadPage);
  PrereqDownloadIntro.AutoSize := False;
  PrereqDownloadIntro.WordWrap := True;
  PrereqDownloadIntro.Left := 0;
  PrereqDownloadIntro.Top := 0;
  PrereqDownloadIntro.Width := PrereqDownloadPage.SurfaceWidth;
  PrereqDownloadIntro.Height := ScaleY(48);
  PrereqDownloadIntro.Caption :=
    '安装器不会自动运行 winget、弹出系统安装程序或修改系统软件。点击右侧按钮打开下载页面，'
    + '完成安装后点击“重新检测”，再继续下一步。uv 会在 Python 可用后自动安装。';
  PrereqDownloadIntro.Parent := PrereqDownloadPage.Surface;

  CreateDownloadRow('Python 3.10+：', '打开 Python 下载', 56, PythonStatusLabel, PythonDownloadButton);
  PythonDownloadButton.OnClick := @PythonDownloadClick;
  CreateDownloadRow('Git：', '打开 Git 下载', 88, GitStatusLabel, GitDownloadButton);
  GitDownloadButton.OnClick := @GitDownloadClick;
  CreateDownloadRow('uv：', '自动安装', 120, UvStatusLabel, UvDownloadButton);
  UvDownloadButton.OnClick := @UvDownloadClick;
  UvDownloadButton.Enabled := False;
  CreateDownloadRow('Microsoft C++ Build Tools：', '打开 C++ 下载', 152, CppStatusLabel, CppDownloadButton);
  CppDownloadButton.OnClick := @CppDownloadClick;
  CreateDownloadRow('CUDA Toolkit：', '打开 CUDA 下载', 184, CudaStatusLabel, CudaDownloadButton);
  CudaDownloadButton.OnClick := @CudaDownloadClick;
  CreateDownloadRow('显卡驱动：', '打开驱动下载', 216, DriverStatusLabel, DriverDownloadButton);
  DriverDownloadButton.OnClick := @DriverDownloadClick;
  CreateDownloadRow('VB-CABLE 虚拟音频线：', '打开 VB-CABLE 下载', 248, VbCableStatusLabel, VbCableDownloadButton);
  VbCableDownloadButton.OnClick := @VbCableDownloadClick;

  RefreshPrereqButton := TNewButton.Create(PrereqDownloadPage);
  RefreshPrereqButton.Width := ScaleX(150);
  RefreshPrereqButton.Height := ScaleY(28);
  RefreshPrereqButton.Left := PrereqDownloadPage.SurfaceWidth - RefreshPrereqButton.Width;
  RefreshPrereqButton.Top := ScaleY(286);
  RefreshPrereqButton.Caption := '重新检测';
  RefreshPrereqButton.OnClick := @RefreshPrereqClick;
  RefreshPrereqButton.Parent := PrereqDownloadPage.Surface;

  PrereqPathPage := CreateInputDirPage(
    PrereqDownloadPage.ID,
    '前置依赖安装/查找路径',
    '选择依赖安装位置或已有路径',
    '如果刚安装的依赖尚未加入 PATH，可在这里填写其安装目录；安装器不会在这些位置自动安装。',
    False,
    ''
  );
  PrereqPathPage.Add('Python 3.10 目录：');
  PrereqPathPage.Add('Git 目录：');
  PrereqPathPage.Add('FFmpeg 目录（分卷内置，系统已安装则跳过）：');
  PrereqPathPage.Add('C++ Build Tools 目录：');

  CudaPathPage := CreateInputDirPage(
    PrereqPathPage.ID,
    'NVIDIA CUDA Toolkit',
    '选择 CUDA Toolkit 安装位置或已有目录',
    '此页面只对 NVIDIA 显卡显示：50 系固定推荐 CUDA 12.8，50 系以下固定推荐 CUDA 12.6；'
    + 'PyTorch wheel 已包含推理运行库，Toolkit 用于配套工具链。',
    False,
    ''
  );
  CudaPathPage.Add('CUDA Toolkit 目录：');

  DataDirPage := CreateInputDirPage(
    CudaPathPage.ID,
    '选择用户数据存储位置',
    '模型、作品、下载素材、编辑工程与主题媒体保存在哪里？',
    '建议选择空间充足的磁盘。该目录后续也可以在软件首页迁移。',
    False,
    ''
  );
  DataDirPage.Add('用户数据目录：');

  DetailsPage := CreateCustomPage(
    wpInstalling,
    '详细安装信息',
    '运行环境搭建输出'
  );

  DetailsInfoLabel := TNewStaticText.Create(DetailsPage);
  DetailsInfoLabel.AutoSize := False;
  DetailsInfoLabel.WordWrap := True;
  DetailsInfoLabel.Width := DetailsPage.SurfaceWidth;
  DetailsInfoLabel.Height := ScaleY(32);
  DetailsInfoLabel.Caption := '安装详情会显示在这里；完整日志也会保存到安装目录。';
  DetailsInfoLabel.Parent := DetailsPage.Surface;

  DetailsMemo := TNewMemo.Create(DetailsPage);
  DetailsMemo.Top := DetailsInfoLabel.Top + DetailsInfoLabel.Height + ScaleY(8);
  DetailsMemo.Width := DetailsPage.SurfaceWidth;
  DetailsMemo.Height := DetailsPage.SurfaceHeight - DetailsMemo.Top;
  DetailsMemo.ScrollBars := ssVertical;
  DetailsMemo.ReadOnly := True;
  DetailsMemo.Text := '尚未开始搭建运行环境。';
  DetailsMemo.Parent := DetailsPage.Surface;
end;

function RequestedGpuStackName(): String;
begin
  Result := 'auto';
  if GpuStackPage.Values[1] then
    Result := 'cpu'
  else if GpuStackPage.Values[2] then
    Result := 'cu121'
  else if GpuStackPage.Values[3] then
    Result := 'cu128'
  else if GpuStackPage.Values[4] then
    Result := 'directml';
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
    Result := '--gpu --cu128'
  else if Requested = 'cu121' then
    Result := '--gpu --no-cu128'
  else if Requested = 'directml' then
    Result := '--directml'
  else
  begin
    Stack := GpuStackName();
    if Stack = 'cu128' then
      Result := '--gpu --cu128'
    else if Stack = 'cu121' then
      Result := '--gpu --no-cu128'
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
      PrereqPathPage.Values[0] := ExpandConstant('{localappdata}\Programs\Python\Python310');
    if PrereqPathPage.Values[1] = '' then
      PrereqPathPage.Values[1] := ExpandConstant('{localappdata}\Programs\Git');
    if PrereqPathPage.Values[2] = '' then
      PrereqPathPage.Values[2] := ExpandConstant('{app}\tools\ffmpeg');
    if PrereqPathPage.Values[3] = '' then
      PrereqPathPage.Values[3] := ExpandConstant('{pf32}\Microsoft Visual Studio\2022\BuildTools');
  end;
  if CurPageID = PrereqDownloadPage.ID then
    RefreshPrereqDownloadStatus;
  if CurPageID = CudaPathPage.ID then
  begin
    if (CudaPathPage.Values[0] = '') or
       ContainsText(CudaPathPage.Values[0], '\NVIDIA GPU Computing Toolkit\CUDA\v12.') then
    begin
      if DetectedGpuStackName() = 'cu128' then
        CudaPathPage.Values[0] := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v' + CudaToolkitBlackwellVersion)
      else
        CudaPathPage.Values[0] := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v' + CudaToolkitPreBlackwellVersion);
    end;
  end;
  if CurPageID = wpFinished then
  begin
    if LastInstallLog <> '' then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
        '运行环境安装详情已写入：' + LastInstallLog + #13#10 +
        '安装过程不会打开 PowerShell 或命令行窗口；如需排查失败，请查看该日志。';
    if LastInstallSummary <> '' then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
        '最后日志摘要：' + #13#10 + LastInstallSummary;
  end;
  if CurPageID = DetailsPage.ID then
    RefreshDetailsMemo();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = GpuStackPage.ID then
    Result := not BuildEnvSelected();
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
  if CurPageID = DataDirPage.ID then
  begin
    DataDir := ResolveInstallerDataDir(DataDirPage.Values[0]);
    if not ForceDirectories(DataDir) then
    begin
      MsgBox('无法创建用户数据目录：' + DataDir + #13#10 +
        '请换一个有写入权限、空间充足的位置。',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    DataDirPage.Values[0] := DataDir;
  end;
  if CurPageID = PrereqDownloadPage.ID then
  begin
    RefreshPrereqDownloadStatus;
    if RequiredPrereqMissing() then
      if MsgBox('仍有一个或多个前置依赖未检测到。你可以先在下一页填写已有安装路径，'
        + '也可以返回下载并安装缺失项。要继续吗？', mbConfirmation, MB_YESNO) <> IDYES then
        Result := False;
  end;
end;

procedure WriteInstallerEnv();
var
  Payload, Stack: String;
begin
  Stack := GpuStackName();
  Payload := '@echo off' + #13#10 +
    'set "XB_FROM_INSTALLER=1"' + #13#10 +
    'set "XB_ENV_CONFIGURE=' + BoolFlag(EnvConfigureSelected()) + '"' + #13#10 +
    'set "XB_GPU_STACK_REQUESTED=' + BatchEscape(RequestedGpuStackName()) + '"' + #13#10 +
    'set "XB_GPU_STACK=' + BatchEscape(Stack) + '"' + #13#10 +
    'set "XB_PYTHON_DIR=' + BatchEscape(PrereqPathPage.Values[0]) + '"' + #13#10 +
    'set "XB_GIT_DIR=' + BatchEscape(PrereqPathPage.Values[1]) + '"' + #13#10 +
    'set "XB_FFMPEG_DIR=' + BatchEscape(PrereqPathPage.Values[2]) + '"' + #13#10 +
    'set "XB_CUDA_DIR=' + BatchEscape(CudaPathPage.Values[0]) + '"' + #13#10 +
    'set "XB_VSBT_DIR=' + BatchEscape(PrereqPathPage.Values[3]) + '"' + #13#10 +
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
  ResultCode: Integer;
  CmdLine, LogDir, LogPath, StepName: String;
  LogText: AnsiString;
begin
  BeginEnvProgress(Status, ProgressStart, ProgressEnd);
  StepName := BatchName;
  StringChangeEx(StepName, '.bat', '', True);
  LogDir := ExpandConstant('{app}\install_logs');
  ForceDirectories(LogDir);
  LogPath := LogDir + '\' + StepName + '.log';
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
  AppendInstallDetail('步骤：' + BatchName);
  AppendInstallDetail('开始时间：' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':'));
  AppendInstallDetail('参数：' + Args);
  AppendInstallDetail('日志文件：' + LogPath);
  AppendInstallDetail('------------------------------------------------------------');
  WizardForm.FilenameLabel.Caption := '安装详情日志：' + LogPath;
  CmdLine := '/c call "' + ExpandConstant('{app}\') + BatchName + '"';
  if Args <> '' then
    CmdLine := CmdLine + ' ' + Args;
  try
    Result := ExecAndLogOutput(ExpandConstant('{cmd}'), CmdLine, ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode, @InstallOutputLog);
  except
    AppendInstallDetail('[installer] ' + GetExceptionMessage);
    ResultCode := -1;
    Result := False;
  end;
  CurrentLogPath := '';
  if LoadStringFromFile(LogPath, LogText) then
    LastInstallSummary := TailText(LogText, 1600);
  if (not Result) or (ResultCode <> 0) then
  begin
    MsgBox(BatchName + ' 执行失败，退出码：' + IntToStr(ResultCode) + #13#10 +
      '安装文件已经复制完成。你可以稍后从开始菜单运行“搭建/修复运行环境”重试。' + #13#10#13#10 +
      '详细日志：' + LogPath,
      mbError, MB_OK);
    Result := False;
  end;
  if Result then
    FinishEnvProgress(Status + '完成');
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
  AppendInstallValidation('应用本体与内置组件校验');

  if not FileExists(PathJoin(AppDir, '{#MyAppExe}')) then
    Missing := AddMissingRuntimeFile(Missing, '应用本体', PathJoin(AppDir, '{#MyAppExe}'));
  if not FileExists(PathJoin(InternalDir, 'web\dist\index.html')) then
    Missing := AddMissingRuntimeFile(Missing, '前端入口', PathJoin(InternalDir, 'web\dist\index.html'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\plugin_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python 插件 worker', PathJoin(InternalDir, 'infrastructure\plugin_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'plugin_sdk_python\xb_svcb_plugin\__init__.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python 插件 SDK', PathJoin(InternalDir, 'plugin_sdk_python\xb_svcb_plugin\__init__.py'));
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
    Missing := AddMissingRuntimeFile(Missing, 'AI 歌声增强 worker', PathJoin(InternalDir, 'infrastructure\vocal_enhancement_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\formant_pitch_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, '高音保护 worker', PathJoin(InternalDir, 'infrastructure\formant_pitch_worker.py'));
  if not FileExists(PathJoin(InternalDir, 'infrastructure\vocal_tuning_worker.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'AI 对齐/自然修音 worker', PathJoin(InternalDir, 'infrastructure\vocal_tuning_worker.py'));
  if not FileExists(PathJoin(AppDir, 'install\configure_user_env.py')) then
    Missing := AddMissingRuntimeFile(Missing, '用户环境配置工具', PathJoin(AppDir, 'install\configure_user_env.py'));
  if not FileExists(PathJoin(AppDir, 'install\detect_python.bat')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python 运行时检测工具', PathJoin(AppDir, 'install\detect_python.bat'));
  if not SystemFfmpegAvailable() then
    Missing := AddMissingRuntimeFile(Missing, 'FFmpeg/ffprobe 分卷载荷', PathJoin(AppDir, 'tools\ffmpeg\bin'));
  if not FileExists(PathJoin(AppDir, 'engines\so-vits-svc\inference\infer_tool.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'So-VITS-SVC 分卷源码', PathJoin(AppDir, 'engines\so-vits-svc\inference\infer_tool.py'));
  if not FileExists(PathJoin(AppDir, 'engines\seed-vc\inference.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC 分卷源码', PathJoin(AppDir, 'engines\seed-vc\inference.py'));
  if not FileExists(PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py')) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC 分卷源码', PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py'));
  if not FileExists(PathJoin(AppDir, 'assets\models\pretrain\rmvpe.pt')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC RMVPE', PathJoin(AppDir, 'assets\models\pretrain\rmvpe.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\pretrain\fcpe.pt')) then
    Missing := AddMissingRuntimeFile(Missing, '高音域 FCPE', PathJoin(AppDir, 'assets\models\pretrain\fcpe.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\campplus_cn_common.bin')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC CampPlus', PathJoin(AppDir, 'assets\models\seedvc\campplus_cn_common.bin'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\whisper-small\model.safetensors')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC Whisper Small', PathJoin(AppDir, 'assets\models\seedvc\whisper-small\model.safetensors'));
  if not FileExists(PathJoin(AppDir, 'assets\models\seedvc\bigvgan_v2_44khz_128band_512x\bigvgan_generator.pt')) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC BigVGAN', PathJoin(AppDir, 'assets\models\seedvc\bigvgan_v2_44khz_128band_512x\bigvgan_generator.pt'));
  if not FileExists(PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\checkpoints\model_120.ckpt.best')) then
    Missing := AddMissingRuntimeFile(Missing, 'DeepFilterNet 权重', PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\checkpoints\model_120.ckpt.best'));
  if not FileExists(PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\config.ini')) then
    Missing := AddMissingRuntimeFile(Missing, 'DeepFilterNet 配置', PathJoin(AppDir, 'assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\config.ini'));
  if not FileExists(PathJoin(AppDir, 'assets\wheels\wheelhouse.json')) then
    Missing := AddMissingRuntimeFile(Missing, 'Python whl 离线依赖清单', PathJoin(AppDir, 'assets\wheels\wheelhouse.json'));
  if not FileExists(PathJoin(AppDir, 'engines\juce-vst3-host\xb-juce-vst3-host.exe')) then
    Missing := AddMissingRuntimeFile(Missing, 'JUCE VST3 Host', PathJoin(AppDir, 'engines\juce-vst3-host\xb-juce-vst3-host.exe'));

  Result := Missing = '';
  if Result then
    AppendInstallValidation('[ok] 应用本体、前端、AI workers、FFmpeg、SVC/DDSP/SeedVC 分卷源码、离线模型、Python whl 与 JUCE Host 完整。')
  else
  begin
    AppendInstallValidation('[fail] 发布包缺少必要组件：');
    AppendInstallValidation(Missing);
    MsgBox('安装包缺少必要组件，部分功能将不可用：' + #13#10 + Missing + #13#10#13#10 +
      '请重新下载安装器的完整分卷文件。', mbError, MB_OK);
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
  AppendInstallValidation('Python 插件运行环境最终校验');

  if not FileExists(PluginPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-plugins Python', PluginPython);
  if FileExists(PluginPython) and not PythonFileAvailable(PluginPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-plugins Python 不可运行', PluginPython);
  if not FileExists(PluginWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'Python 插件 worker', PluginWorker);
  if not FileExists(PluginSdk) then
    Missing := AddMissingRuntimeFile(Missing, 'Python 插件 SDK', PluginSdk);

  Result := Missing = '';
  if Result then
    AppendInstallValidation('[ok] Python 与混合插件运行环境可被软件识别。')
  else
  begin
    AppendInstallValidation('[fail] Python 插件运行环境不完整：');
    AppendInstallValidation(Missing);
    AppendInstallValidation('建议：在安装目录执行 setup_env.bat --only plugins。');
    MsgBox('Python 插件运行环境最终校验失败。' + #13#10 + Missing + #13#10#13#10 +
      '可稍后在安装目录执行：setup_env.bat --only plugins', mbError, MB_OK);
  end;
end;

function ValidateUvrRuntime(): Boolean;
var
  AppDir, UvrPython, UvrWorker, UvrModel, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  UvrPython := PathJoin(AppDir, '.venv-uvr\Scripts\python.exe');
  UvrWorker := PathJoin(AppDir, '_internal\infrastructure\uvr_worker.py');
  UvrModel := PathJoin(AppDir, 'models\uvr\5_HP-Karaoke-UVR.pth');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation('UVR 运行环境最终校验');
  AppendInstallValidation('安装目录：' + AppDir);

  if not FileExists(UvrPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-uvr Python', UvrPython);
  if FileExists(UvrPython) and not PythonFileAvailable(UvrPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-uvr Python 不可运行', UvrPython);
  if not FileExists(UvrWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR worker', UvrWorker);
  if not FileExists(UvrModel) then
    Missing := AddMissingRuntimeFile(Missing, 'UVR 分离模型', UvrModel);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation('[ok] UVR 运行环境可被软件识别。');
    Exit;
  end;

  AppendInstallValidation('[fail] UVR 运行环境不完整，软件会显示“降级模式 / UVR 未安装”。');
  AppendInstallValidation('缺失项：');
  AppendInstallValidation(Missing);
  AppendInstallValidation('建议：从开始菜单运行“搭建/修复运行环境”，或在安装目录执行 setup_env.bat --only uvr models。');

  MsgBox('UVR 运行环境最终校验失败。' + #13#10 +
    '安装器命令已执行完成，但软件仍无法识别完整 UVR 环境。' + #13#10#13#10 +
    '缺失项：' + #13#10 + Missing + #13#10#13#10 +
    '请稍后从开始菜单运行“搭建/修复运行环境”，或在安装目录执行：' + #13#10 +
    'setup_env.bat --only uvr models' + #13#10#13#10 +
    '详细日志：' + LastInstallLog,
    mbError, MB_OK);
end;

function ValidateSeedVcRuntime(): Boolean;
var
  AppDir, SeedPython, SeedWorker, SeedInference, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  SeedPython := PathJoin(AppDir, '.venv-seedvc\Scripts\python.exe');
  SeedWorker := PathJoin(AppDir, '_internal\infrastructure\seedvc_worker.py');
  SeedInference := PathJoin(AppDir, 'engines\seed-vc\inference.py');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation('SeedVC 运行环境最终校验');

  if not FileExists(SeedPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-seedvc Python', SeedPython);
  if FileExists(SeedPython) and not PythonFileAvailable(SeedPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-seedvc Python 不可运行', SeedPython);
  if not FileExists(SeedWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'SeedVC worker', SeedWorker);
  if not FileExists(SeedInference) then
    Missing := AddMissingRuntimeFile(Missing, 'Seed-VC inference.py', SeedInference);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation('[ok] SeedVC 运行环境可被软件识别。');
    Exit;
  end;

  AppendInstallValidation('[fail] SeedVC 运行环境不完整，软件会显示“降级模式”。');
  AppendInstallValidation('缺失项：');
  AppendInstallValidation(Missing);
  AppendInstallValidation('建议：从开始菜单运行“搭建/修复运行环境”，或执行 setup_env.bat --only seedvc。');

  MsgBox('SeedVC 运行环境最终校验失败。' + #13#10 +
    '缺失项：' + #13#10 + Missing + #13#10#13#10 +
    '可稍后在安装目录执行：setup_env.bat --only seedvc' + #13#10#13#10 +
    '详细日志：' + LastInstallLog,
    mbError, MB_OK);
end;

function ValidateDdspRuntime(): Boolean;
var
  AppDir, DdspPython, DdspWorker, DdspInference, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  DdspPython := PathJoin(AppDir, '.venv-ddsp\Scripts\python.exe');
  DdspWorker := PathJoin(AppDir, '_internal\infrastructure\ddsp_worker.py');
  DdspInference := PathJoin(AppDir, 'engines\ddsp-svc\main_reflow.py');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation('DDSP-SVC 运行环境最终校验');

  if not FileExists(DdspPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-ddsp Python', DdspPython);
  if FileExists(DdspPython) and not PythonFileAvailable(DdspPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-ddsp Python 不可运行', DdspPython);
  if not FileExists(DdspWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC worker', DdspWorker);
  if not FileExists(DdspInference) then
    Missing := AddMissingRuntimeFile(Missing, 'DDSP-SVC main_reflow.py', DdspInference);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation('[ok] DDSP-SVC 运行环境可被软件识别。');
    Exit;
  end;

  AppendInstallValidation('[fail] DDSP-SVC 运行环境不完整，软件会显示“降级模式”。');
  AppendInstallValidation('缺失项：');
  AppendInstallValidation(Missing);
  AppendInstallValidation('建议：从开始菜单运行“搭建/修复运行环境”，或执行 setup_env.bat --only ddsp。');
end;

function ValidateVocalRuntime(): Boolean;
var
  AppDir, VocalPython, VocalWorker, TuningWorker, FormantWorker, VocalReady, Missing: String;
begin
  AppDir := ExpandConstant('{app}');
  VocalPython := PathJoin(AppDir, '.venv-vocal\Scripts\python.exe');
  VocalWorker := PathJoin(AppDir, '_internal\infrastructure\vocal_enhancement_worker.py');
  TuningWorker := PathJoin(AppDir, '_internal\infrastructure\vocal_tuning_worker.py');
  FormantWorker := PathJoin(AppDir, '_internal\infrastructure\formant_pitch_worker.py');
  VocalReady := PathJoin(AppDir, 'models\vocal-enhancement\runtime.ready');
  Missing := '';

  AppendInstallValidation('');
  AppendInstallValidation('------------------------------------------------------------');
  AppendInstallValidation('AI 歌声增强运行环境最终校验');

  if not FileExists(VocalPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-vocal Python', VocalPython);
  if FileExists(VocalPython) and not PythonFileAvailable(VocalPython) then
    Missing := AddMissingRuntimeFile(Missing, '.venv-vocal Python 不可运行', VocalPython);
  if not FileExists(VocalWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'AI 歌声增强 worker', VocalWorker);
  if not FileExists(TuningWorker) then
    Missing := AddMissingRuntimeFile(Missing, 'AI 对齐/自然修音 worker', TuningWorker);
  if not FileExists(FormantWorker) then
    Missing := AddMissingRuntimeFile(Missing, '高音保护 worker', FormantWorker);
  if not FileExists(VocalReady) then
    Missing := AddMissingRuntimeFile(Missing, 'runtime.ready 标记', VocalReady);

  Result := Missing = '';
  if Result then
  begin
    AppendInstallValidation('[ok] AI 歌声增强运行环境可被软件识别。');
    Exit;
  end;

  AppendInstallValidation('[fail] AI 歌声增强运行环境不完整，软件会显示“降级模式”。');
  AppendInstallValidation('缺失项：');
  AppendInstallValidation(Missing);
  AppendInstallValidation('建议：从开始菜单运行“搭建/修复运行环境”，或执行 setup_env.bat --only vocal。');
end;

function ValidateTorchRuntime(const PythonPath, RuntimeLabel: String): Boolean;
var
  ResultCode: Integer;
  CheckCode: String;
begin
  Result := False;
  if not FileExists(PythonPath) then
  begin
    AppendInstallValidation('[fail] ' + RuntimeLabel + ' 缺少 Python：' + PythonPath);
    Exit;
  end;

  if GpuStackName() = 'directml' then
    CheckCode := 'import torch,torch_directml; assert hasattr(torch,''__version__''); assert torch_directml.is_available()'
  else if (GpuStackName() = 'cu121') or (GpuStackName() = 'cu128') then
    CheckCode := 'import torch; assert hasattr(torch,''__version__''); assert torch.cuda.is_available()'
  else
    CheckCode := 'import torch; assert hasattr(torch,''__version__'')';

  Result := Exec(PythonPath, '-c "' + CheckCode + '"', ExpandConstant('{app}'),
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if Result then
    AppendInstallValidation('[ok] ' + RuntimeLabel + ' Torch 可导入且设备栈匹配。')
  else
    AppendInstallValidation('[fail] ' + RuntimeLabel + ' Torch 损坏、未完成或与所选 GPU 栈不匹配。');
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
  AppendInstallValidation('六个 AI 隔离环境真实 Torch 校验');

  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-uvr\Scripts\python.exe'), 'UVR');
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-svc\Scripts\python.exe'), 'So-VITS-SVC');
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-rvc\Scripts\python.exe'), 'RVC');
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-seedvc\Scripts\python.exe'), 'SeedVC');
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-ddsp\Scripts\python.exe'), 'DDSP-SVC');
  Result := Result and CurrentReady;
  CurrentReady := ValidateTorchRuntime(PathJoin(AppDir, '.venv-vocal\Scripts\python.exe'), 'AI 歌声增强');
  Result := Result and CurrentReady;

  if not Result then
    MsgBox('一个或多个 AI 环境没有完整安装，软件会显示降级模式。' + #13#10 +
      '请不要直接启动软件；先从开始菜单运行“搭建/修复运行环境”，' + #13#10 +
      '或在安装目录重新执行 setup_env.bat。' + #13#10#13#10 +
      '详细日志：' + LastInstallLog, mbError, MB_OK);
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
      SetEnvProgress(0, '准备搭建运行环境…');
      WriteInstallerEnv();
      PrereqsReady := True;
      if EnvConfigureSelected() then
      begin
        if BuildEnvSelected() then
          SetupProgressStart := 35
        else
          SetupProgressStart := 100;
        PrereqsReady := RunSetupBatch('install_prereqs.bat', '', '正在检测前置依赖并配置环境变量…', 0, SetupProgressStart);
      end
      else
        SetupProgressStart := 0;
      if BuildEnvSelected() and PrereqsReady and
         RunSetupBatch('setup_env.bat', GpuInstallArgs(), '正在搭建运行环境（创建子环境、复制模型、安装 Python 依赖）…', SetupProgressStart, 100) then
      begin
        PluginReady := ValidatePluginRuntime();
        UvrReady := ValidateUvrRuntime();
        SeedVcReady := ValidateSeedVcRuntime();
        DdspReady := ValidateDdspRuntime();
        VocalReady := ValidateVocalRuntime();
        InferenceReady := ValidateAllInferenceRuntimes();
        if (not PluginReady) or (not UvrReady) or (not SeedVcReady) or (not DdspReady) or (not VocalReady) or
           (not InferenceReady) then
          SetEnvProgress(100, '部分运行环境校验失败，请查看安装详情日志');
      end;
    end;
  end;
end;
