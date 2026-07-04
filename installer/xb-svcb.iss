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
;    - 可选“搭建运行环境”：检测/安装前置依赖，联网创建 .venv / 下载依赖与模型（由 batch 调 install.py）
;    - 创建开始菜单与桌面快捷方式（指向 XB-SVCB.exe）
;
;  用户机前置：安装器可通过 winget 自动安装缺失的 Python/Git/ffmpeg/uv/C++ Build Tools/CUDA Toolkit；
;  已安装则跳过。CUDA 栈可自动检测，也可手动指定 40 系及以下 cu121 / 50 系 cu128。
;  应用界面本身由 exe 自带，无需 Node / Python。
; ============================================================

#define MyAppName "XB-SVCB AI 翻唱工具"
#define MyAppShort "XB-SVCB"
#define MyAppVersion "0.0.14"
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

[Files]
; 应用本体：PyInstaller 打包产物（XB-SVCB.exe + _internal，含前端与 worker 脚本）
Source: "..\dist\XB-SVCB\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 环境搭建脚本（纯 batch + Python，安装过程不涉及 PowerShell）
Source: "..\install\*"; DestDir: "{app}\install"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "\__pycache__\*"
Source: "..\setup_env.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_prereqs.bat"; DestDir: "{app}"; Flags: ignoreversion
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
; 提供安装完成后直接启动选项（默认不勾）
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 {#MyAppShort}"; \
  WorkingDir: "{app}"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; 卸载时清理安装目录内生成的环境与下载物（用户数据在 .xb_xvcb，保留）
Type: filesandordirs; Name: "{app}\.venv-uvr"
Type: filesandordirs; Name: "{app}\.venv-svc"
Type: filesandordirs; Name: "{app}\.venv-rvc"
Type: filesandordirs; Name: "{app}\.venv-hub"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\models"

[Code]
var
  DataDirPage: TInputDirWizardPage;
  PrereqPage: TInputOptionWizardPage;
  GpuStackPage: TInputOptionWizardPage;
  PrereqPathPage: TInputDirWizardPage;
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

function BatchEscape(const S: String): String;
begin
  Result := S;
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

function ContainsText(const S, Needle: String): Boolean;
begin
  Result := Pos(Uppercase(Needle), Uppercase(S)) > 0;
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
      Token := Token + Text[I]
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

function DetectedGpuStackName(): String;
var
  Caps, Names: String;
begin
  Result := 'cpu';
  if not CmdAvailable('nvidia-smi') then
    Exit;

  Caps := CommandOutput('nvidia-smi --query-gpu=compute_cap --format=csv,noheader');
  if Caps <> '' then
  begin
    if HasComputeMajorAtLeast(Caps, 12) then
      Result := 'cu128'
    else if HasComputeMajorAtLeast(Caps, 5) then
      Result := 'cu121';
    Exit;
  end;

  Names := CommandOutput('nvidia-smi --query-gpu=name --format=csv,noheader');
  if ContainsText(Names, 'RTX 50') or ContainsText(Names, 'RTX50') then
    Result := 'cu128'
  else if Names <> '' then
    Result := 'cu121';
end;

function GpuStackLabel(const Stack: String): String;
begin
  if Stack = 'cu128' then
    Result := 'NVIDIA 50 系 / Blackwell，使用 CUDA 12.8 与 cu128 torch'
  else if Stack = 'cu121' then
    Result := 'NVIDIA 40 系及以下兼容显卡，使用 CUDA 12.1 与 cu121/cu118 torch'
  else
    Result := 'CPU 或未检测到兼容 NVIDIA 显卡，跳过 CUDA 并安装 CPU 版 torch';
end;

function ShowInstallDetails(): Boolean;
begin
  Result := PrereqPage.Values[0] and PrereqPage.Values[3];
end;

function BuildEnvSelected(): Boolean;
begin
  Result := PrereqPage.Values[0];
end;

function EnvAutoInstallSelected(): Boolean;
begin
  Result := PrereqPage.Values[1];
end;

function EnvConfigureSelected(): Boolean;
begin
  Result := PrereqPage.Values[2];
end;

function StatusText(Ok: Boolean): String;
begin
  if Ok then
    Result := '已检测到'
  else
    Result := '未检测到';
end;

function EnvironmentCheckSummary(): String;
begin
  Result :=
    '安装器会先检查运行环境，再进入安装路径选择。当前检测结果：' + #13#10 +
    '  Python 3.10+：' + StatusText(CmdAvailable('python') or CmdAvailable('py')) + #13#10 +
    '  Git：' + StatusText(CmdAvailable('git')) + #13#10 +
    '  ffmpeg：' + StatusText(CmdAvailable('ffmpeg')) + #13#10 +
    '  uv：' + StatusText(CmdAvailable('uv')) + #13#10 +
    '  CUDA Toolkit：' + StatusText(CmdAvailable('nvcc')) + #13#10 +
    '  GPU 推理栈：' + GpuStackLabel(DetectedGpuStackName()) + #13#10 +
    '  winget：' + StatusText(CmdAvailable('winget')) + #13#10 +
    '已安装的依赖会自动跳过；自动模式会让 CUDA / torch 与显卡匹配，不兼容或纯 CPU 机器会跳过 CUDA。';
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
  PrereqPage.Add('自动安装缺失的前置依赖（需要联网；优先使用 winget；可能弹出 UAC）');
  PrereqPage.Add('自动配置 PATH / CUDA_PATH / VSINSTALLDIR 等用户环境变量');
  PrereqPage.Add('在安装器窗口显示详细安装信息（可选；完整日志仍会写入安装目录）');
  PrereqPage.Values[0] := True;
  PrereqPage.Values[1] := True;
  PrereqPage.Values[2] := True;
  PrereqPage.Values[3] := False;

  GpuStackPage := CreateInputOptionPage(
    wpSelectDir,
    'GPU 与 CUDA 栈',
    '选择本机要使用的推理依赖栈',
    '安装器会复核实际显卡：RTX 50 系使用 cu128 + torch 2.7，40 系及以下使用 cu121/cu118；CPU 或不兼容显卡会跳过 CUDA 并安装 CPU 版 torch。',
    True,
    False
  );
  GpuStackPage.Add('自动检测（推荐）');
  GpuStackPage.Add('CPU 模式');
  GpuStackPage.Add('NVIDIA 40 系及以下：cu121 / cu118');
  GpuStackPage.Add('NVIDIA 50 系 Blackwell：cu128');
  GpuStackPage.Values[0] := True;

  PrereqPathPage := CreateInputDirPage(
    GpuStackPage.ID,
    '前置依赖安装/查找路径',
    '选择依赖安装位置或已有路径',
    '自动安装时会尽量使用这些位置；如果你已经装好了，也可以指向已有目录。留空则只按 PATH / 默认位置检测。',
    False,
    ''
  );
  PrereqPathPage.Add('Python 3.10 目录：');
  PrereqPathPage.Add('Git 目录：');
  PrereqPathPage.Add('ffmpeg 目录：');
  PrereqPathPage.Add('CUDA Toolkit 目录：');
  PrereqPathPage.Add('C++ Build Tools 目录：');

  DataDirPage := CreateInputDirPage(
    PrereqPathPage.ID,
    '选择用户数据存储位置',
    '模型、作品、下载素材与编辑工程保存在哪里？',
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
    Result := 'cu128';
end;

function GpuStackName(): String;
var
  Requested, Detected: String;
begin
  Requested := RequestedGpuStackName();
  if Requested = 'cpu' then
  begin
    Result := 'cpu';
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
  Stack: String;
begin
  Stack := GpuStackName();
  if Stack = 'cpu' then
    Result := '--cpu'
  else if Stack = 'cu128' then
    Result := '--gpu --cu128'
  else
    Result := '--gpu --no-cu128';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = DataDirPage.ID then
  begin
    if DataDirPage.Values[0] = '' then
      DataDirPage.Values[0] := ExpandConstant('{app}\.xb_xvcb');
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
    begin
      if GpuStackName() = 'cu128' then
        PrereqPathPage.Values[3] := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v12.8')
      else
        PrereqPathPage.Values[3] := ExpandConstant('{autopf}\NVIDIA GPU Computing Toolkit\CUDA\v12.1');
    end;
    if PrereqPathPage.Values[4] = '' then
      PrereqPathPage.Values[4] := ExpandConstant('{pf32}\Microsoft Visual Studio\2022\BuildTools');
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
  if (PageID = GpuStackPage.ID) or (PageID = PrereqPathPage.ID) then
    Result := not BuildEnvSelected();
  if PageID = DetailsPage.ID then
    Result := not ShowInstallDetails();
end;

procedure WriteInstallerEnv();
var
  Payload, Stack: String;
begin
  Stack := GpuStackName();
  Payload := '@echo off' + #13#10 +
    'set "XB_FROM_INSTALLER=1"' + #13#10 +
    'set "XB_PREREQ_AUTO=' + BoolFlag(EnvAutoInstallSelected()) + '"' + #13#10 +
    'set "XB_ENV_CONFIGURE=' + BoolFlag(EnvConfigureSelected()) + '"' + #13#10 +
    'set "XB_GPU_STACK_REQUESTED=' + BatchEscape(RequestedGpuStackName()) + '"' + #13#10 +
    'set "XB_GPU_STACK=' + BatchEscape(Stack) + '"' + #13#10 +
    'set "XB_PYTHON_DIR=' + BatchEscape(PrereqPathPage.Values[0]) + '"' + #13#10 +
    'set "XB_GIT_DIR=' + BatchEscape(PrereqPathPage.Values[1]) + '"' + #13#10 +
    'set "XB_FFMPEG_DIR=' + BatchEscape(PrereqPathPage.Values[2]) + '"' + #13#10 +
    'set "XB_CUDA_DIR=' + BatchEscape(PrereqPathPage.Values[3]) + '"' + #13#10 +
    'set "XB_VSBT_DIR=' + BatchEscape(PrereqPathPage.Values[4]) + '"' + #13#10;
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

procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir, Payload: String;
  SetupProgressStart: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := DataDirPage.Values[0];
    if DataDir = '' then
      DataDir := ExpandConstant('{app}\.xb_xvcb');
    ForceDirectories(DataDir);
    Payload := '{' + #13#10 +
      '  "data_dir": "' + JsonEscape(DataDir) + '"' + #13#10 +
      '}' + #13#10;
    SaveStringToFile(ExpandConstant('{app}\data_home.json'), Payload, False);

    if BuildEnvSelected() then
    begin
      SetEnvProgress(0, '准备搭建运行环境…');
      WriteInstallerEnv();
      if EnvAutoInstallSelected() or EnvConfigureSelected() then
      begin
        RunSetupBatch('install_prereqs.bat', '', '正在检测/安装前置依赖并配置环境变量…', 0, 35);
        SetupProgressStart := 35;
      end
      else
        SetupProgressStart := 0;
      RunSetupBatch('setup_env.bat', GpuInstallArgs(), '正在搭建运行环境（创建子环境、复制模型、安装 Python 依赖）…', SetupProgressStart, 100);
    end;
  end;
end;
