; XB-SVCB online bootstrapper. It downloads one complete hardware-specific
; offline installer set from a public HTTPS directory and launches it.

#define MyAppName "XB-SVCB"
#define MyAppVersion "0.1.0"
#ifndef XB_ONLINE_BASE_URL
  #define XB_ONLINE_BASE_URL "https://invalid.example/xb-svcb/0.1.0"
#endif
#ifndef XB_ONLINE_MANIFEST_SHA256
  #define XB_ONLINE_MANIFEST_SHA256 "0000000000000000000000000000000000000000000000000000000000000000"
#endif

[Setup]
AppId={{8A5BDAA4-CC5F-45B0-A87F-AACB289713A2}
AppName={cm:OnlineAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoDescription=XB-SVCB Online Setup
VersionInfoProductName=XB-SVCB Online Setup
AppPublisher=XB-SVCB
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=XB-SVCB-Online-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
SetupIconFile=..\web\public\favicon.ico
DisableReadyPage=no
DisableFinishedPage=no

[Languages]
Name: "zhcn"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ja"; MessagesFile: "languages\Japanese.isl"

[CustomMessages]
zhcn.OnlineAppName=XB-SVCB 在线安装器
en.OnlineAppName=XB-SVCB Online Setup
ja.OnlineAppName=XB-SVCB オンラインセットアップ
zhcn.OnlineHardwareTitle=选择硬件版本
en.OnlineHardwareTitle=Choose a hardware build
ja.OnlineHardwareTitle=ハードウェア版の選択
zhcn.OnlineHardwareSubtitle=安装器将只下载此电脑需要的完整安装包
en.OnlineHardwareSubtitle=Setup downloads only the complete package needed by this computer
ja.OnlineHardwareSubtitle=このコンピューターに必要な完全パッケージのみをダウンロードします
zhcn.OnlineHardwarePrompt=请选择推理硬件。自动检测适用于大多数电脑；也可以手动覆盖检测结果。
en.OnlineHardwarePrompt=Choose the inference hardware. Auto detection is suitable for most computers, or you can override it manually.
ja.OnlineHardwarePrompt=推論ハードウェアを選択してください。通常は自動検出を使用し、必要に応じて手動で変更できます。
zhcn.OnlineAuto=自动检测（推荐）
en.OnlineAuto=Auto detect (recommended)
ja.OnlineAuto=自動検出 (推奨)
zhcn.OnlineCpu=CPU / 无兼容 GPU
en.OnlineCpu=CPU / no compatible GPU
ja.OnlineCpu=CPU / 対応 GPU なし
zhcn.OnlineCuda126=NVIDIA RTX 40 系及以下（CUDA 12.6）
en.OnlineCuda126=NVIDIA RTX 40 series or older (CUDA 12.6)
ja.OnlineCuda126=NVIDIA RTX 40 シリーズ以前 (CUDA 12.6)
zhcn.OnlineCuda128=NVIDIA RTX 50 系（CUDA 12.8）
en.OnlineCuda128=NVIDIA RTX 50 series (CUDA 12.8)
ja.OnlineCuda128=NVIDIA RTX 50 シリーズ (CUDA 12.8)
zhcn.OnlineRocm10=AMD Radeon（ROCm 10，推荐）
en.OnlineRocm10=AMD Radeon (ROCm 10, recommended)
ja.OnlineRocm10=AMD Radeon (ROCm 10、推奨)
zhcn.OnlineDirectML=AMD Radeon（DirectML 兼容模式）
en.OnlineDirectML=AMD Radeon (DirectML compatibility mode)
ja.OnlineDirectML=AMD Radeon (DirectML 互換モード)
zhcn.OnlineDownloadTitle=正在下载安装文件
en.OnlineDownloadTitle=Downloading installation files
ja.OnlineDownloadTitle=インストールファイルをダウンロードしています
zhcn.OnlineDownloadSubtitle=下载内容将通过 SHA-256 校验
en.OnlineDownloadSubtitle=Downloads are verified with SHA-256
ja.OnlineDownloadSubtitle=ダウンロード内容は SHA-256 で検証されます
zhcn.OnlineManifestInvalid=在线安装清单无效或已损坏：%1
en.OnlineManifestInvalid=The online installation manifest is invalid or damaged: %1
ja.OnlineManifestInvalid=オンラインインストールマニフェストが無効または破損しています: %1
zhcn.OnlineManifestVersion=在线安装清单版本为 %1，但此安装器需要 %2。请下载最新的在线安装器。
en.OnlineManifestVersion=The online manifest is for version %1, but this bootstrapper requires %2. Download the latest online bootstrapper.
ja.OnlineManifestVersion=オンラインマニフェストのバージョンは %1 ですが、このインストーラーには %2 が必要です。最新のオンラインインストーラーをダウンロードしてください。
zhcn.OnlineDownloadFailed=下载失败：%1%n%2
en.OnlineDownloadFailed=Download failed: %1%n%2
ja.OnlineDownloadFailed=ダウンロードに失敗しました: %1%n%2
zhcn.OnlineDownloadLocation=无法在在线安装器所在目录创建下载目录：%1%n请把在线安装器移动到具有写入权限的文件夹后重试。
en.OnlineDownloadLocation=Could not create the download directory next to the online installer: %1%nMove the online installer to a writable folder and try again.
ja.OnlineDownloadLocation=オンラインインストーラーの場所にダウンロードフォルダーを作成できません: %1%n書き込み可能なフォルダーにオンラインインストーラーを移動して再試行してください。
zhcn.OnlineSaveFailed=无法把已校验的下载文件保存到在线安装器所在目录：%1%n%2
en.OnlineSaveFailed=Could not save the verified download next to the online installer: %1%n%2
ja.OnlineSaveFailed=検証済みのダウンロードをオンラインインストーラーの場所に保存できません: %1%n%2
zhcn.OnlineLaunchFailed=无法启动已下载的安装器：%1
en.OnlineLaunchFailed=Could not start the downloaded installer: %1
ja.OnlineLaunchFailed=ダウンロードしたインストーラーを起動できませんでした: %1
zhcn.OnlineInstallerFailed=安装器未成功完成（退出代码 %1）。可以返回后重试。
en.OnlineInstallerFailed=Setup did not complete successfully (exit code %1). You can go back and try again.
ja.OnlineInstallerFailed=セットアップは正常に完了しませんでした (終了コード %1)。戻って再試行できます。
zhcn.OnlinePreparing=正在读取发布清单并准备下载…
en.OnlinePreparing=Reading the release manifest and preparing downloads...
ja.OnlinePreparing=リリースマニフェストを読み込み、ダウンロードを準備しています...

[Code]
const
  ManifestName = 'online-manifest.ini';
  MaxArtifactCount = 64;

var
  HardwarePage: TInputOptionWizardPage;
  DownloadPage: TDownloadWizardPage;
  SelectedStack: String;
  DownloadDirectory: String;
  DownloadedSetup: String;
  DownloadedArtifactCount: Integer;
  DownloadedArtifactNames: array[0..MaxArtifactCount - 1] of String;
  ArtifactsReady: Boolean;

function M(const Key: String): String;
begin
  Result := ExpandConstant('{cm:' + Key + '}');
end;

function M1(const Key, Arg1: String): String;
begin
  Result := FmtMessage(M(Key), [Arg1]);
end;

function M2(const Key, Arg1, Arg2: String): String;
begin
  Result := FmtMessage(M(Key), [Arg1, Arg2]);
end;

function ContainsText(const Text, Needle: String): Boolean;
begin
  Result := Pos(LowerCase(Needle), LowerCase(Text)) > 0;
end;

function CommandOutput(const CommandLine: String): String;
var
  ResultCode: Integer;
  TempFile: String;
  Text: AnsiString;
begin
  Result := '';
  TempFile := ExpandConstant('{tmp}\xb_svcb_online_detect.txt');
  DeleteFile(TempFile);
  if Exec(ExpandConstant('{cmd}'), '/d /c ' + CommandLine + ' > "' + TempFile + '" 2>nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    if LoadStringFromFile(TempFile, Text) then
      Result := String(Text);
  end;
  DeleteFile(TempFile);
end;

function DetectHardwareStack(): String;
var
  Caps, Names: String;
begin
  Result := 'cpu';
  Caps := CommandOutput('nvidia-smi --query-gpu=compute_cap --format=csv,noheader');
  Names := CommandOutput('nvidia-smi --query-gpu=name --format=csv,noheader');
  if (Caps <> '') or ContainsText(Names, 'NVIDIA') or ContainsText(Names, 'GeForce') then
  begin
    if ContainsText(Caps, '12.') or ContainsText(Names, 'RTX 50') or
       ContainsText(Names, 'RTX50') then
      Result := 'cu128'
    else
      Result := 'cu126';
    Exit;
  end;

  Names := CommandOutput(
    'powershell.exe -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name"');
  if ContainsText(Names, 'RTX 50') or ContainsText(Names, 'RTX50') then
    Result := 'cu128'
  else if ContainsText(Names, 'NVIDIA') or ContainsText(Names, 'GeForce') then
    Result := 'cu126'
  else if ContainsText(Names, 'AMD') or ContainsText(Names, 'Radeon') then
    Result := 'rocm10';
end;

function StackFromSelection(): String;
begin
  case HardwarePage.SelectedValueIndex of
    0: Result := DetectHardwareStack();
    1: Result := 'cpu';
    2: Result := 'cu126';
    3: Result := 'cu128';
    4: Result := 'rocm10';
    5: Result := 'directml';
  else
    Result := 'cpu';
  end;
end;

function IsHexHash(const Value: String): Boolean;
var
  I: Integer;
begin
  Result := Length(Value) = 64;
  if not Result then
    Exit;
  for I := 1 to Length(Value) do
  begin
    if Pos(Value[I], '0123456789abcdefABCDEF') = 0 then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function IsSafeBaseName(const Value: String): Boolean;
var
  I: Integer;
begin
  Result := (Value <> '') and (Value <> '.') and (Value <> '..') and
    (ExtractFileName(Value) = Value) and (Pos('..', Value) = 0);
  if not Result then
    Exit;
  for I := 1 to Length(Value) do
  begin
    if Pos(Value[I],
      '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._-') = 0 then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function BaseUrl(): String;
begin
  Result := '{#XB_ONLINE_BASE_URL}';
end;

function ArtifactUrl(const BaseName: String): String;
begin
  Result := BaseUrl() + '/' + BaseName;
end;

function PersistentDownloadDirectory(): String;
begin
  Result := AddBackslash(ExpandConstant('{src}')) +
    'XB-SVCB-Downloads\{#MyAppVersion}\' + SelectedStack;
end;

procedure InvalidManifest(const Detail: String);
begin
  SuppressibleMsgBox(M1('OnlineManifestInvalid', Detail), mbCriticalError, MB_OK, IDOK);
end;

function DownloadManifest(): Boolean;
var
  Error: String;
begin
  Result := False;
  DownloadPage.Clear;
  DownloadPage.Add(ArtifactUrl(ManifestName), ManifestName,
    '{#XB_ONLINE_MANIFEST_SHA256}');
  DownloadPage.Show;
  try
    try
      WizardForm.StatusLabel.Caption := M('OnlinePreparing');
      DownloadPage.Download;
      Result := True;
    except
      if not DownloadPage.AbortedByUser then
      begin
        Error := GetExceptionMessage;
        SuppressibleMsgBox(
          M2('OnlineDownloadFailed', DownloadPage.LastBaseNameOrUrl, Error),
          mbCriticalError, MB_OK, IDOK);
      end;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

function PrepareArtifactDownloads(): Boolean;
var
  ManifestPath, SectionName, VersionValue, CountValue: String;
  SetupName, FileName, HashValue, ExistingName: String;
  Count, Index, Previous: Integer;
begin
  Result := False;
  ManifestPath := ExpandConstant('{tmp}\') + ManifestName;
  VersionValue := GetIniString('release', 'version', '', ManifestPath);
  if VersionValue <> '{#MyAppVersion}' then
  begin
    SuppressibleMsgBox(
      M2('OnlineManifestVersion', VersionValue, '{#MyAppVersion}'),
      mbCriticalError, MB_OK, IDOK);
    Exit;
  end;

  SectionName := 'stack.' + SelectedStack;
  CountValue := GetIniString(SectionName, 'count', '', ManifestPath);
  Count := StrToIntDef(CountValue, 0);
  if (Count < 2) or (Count > MaxArtifactCount) then
  begin
    InvalidManifest(SectionName + '.count');
    Exit;
  end;

  SetupName := GetIniString(SectionName, 'setup', '', ManifestPath);
  if (not IsSafeBaseName(SetupName)) or
     (LowerCase(ExtractFileExt(SetupName)) <> '.exe') then
  begin
    InvalidManifest(SectionName + '.setup');
    Exit;
  end;

  DownloadDirectory := PersistentDownloadDirectory();
  if not ForceDirectories(DownloadDirectory) then
  begin
    SuppressibleMsgBox(
      M1('OnlineDownloadLocation', DownloadDirectory),
      mbCriticalError, MB_OK, IDOK);
    Exit;
  end;

  DownloadPage.Clear;
  DownloadedArtifactCount := Count;
  for Index := 0 to Count - 1 do
  begin
    FileName := GetIniString(SectionName, 'file' + IntToStr(Index), '', ManifestPath);
    HashValue := GetIniString(SectionName, 'sha256_' + IntToStr(Index), '', ManifestPath);
    if (not IsSafeBaseName(FileName)) or (not IsHexHash(HashValue)) then
    begin
      InvalidManifest(SectionName + '.file' + IntToStr(Index));
      Exit;
    end;
    for Previous := 0 to Index - 1 do
    begin
      ExistingName := GetIniString(
        SectionName, 'file' + IntToStr(Previous), '', ManifestPath);
      if CompareText(ExistingName, FileName) = 0 then
      begin
        InvalidManifest(SectionName + '.file' + IntToStr(Index));
        Exit;
      end;
    end;
    DownloadedArtifactNames[Index] := FileName;
    DownloadPage.Add(ArtifactUrl(FileName), FileName, HashValue);
  end;

  if CompareText(
       GetIniString(SectionName, 'file0', '', ManifestPath), SetupName) <> 0 then
  begin
    InvalidManifest(SectionName + '.setup');
    Exit;
  end;

  DownloadedSetup := AddBackslash(DownloadDirectory) + SetupName;
  Result := True;
end;

function DownloadArtifacts(): Boolean;
var
  Error, TempPath, DestinationPath: String;
  Index: Integer;
begin
  Result := False;
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      for Index := 0 to DownloadedArtifactCount - 1 do
      begin
        TempPath := AddBackslash(ExpandConstant('{tmp}')) +
          DownloadedArtifactNames[Index];
        DestinationPath := AddBackslash(DownloadDirectory) +
          DownloadedArtifactNames[Index];
        if (not FileExists(TempPath)) or
           (not CopyFile(TempPath, DestinationPath, False)) then
        begin
          SuppressibleMsgBox(
            M2('OnlineSaveFailed', DestinationPath, SysErrorMessage(DLLGetLastError)),
            mbCriticalError, MB_OK, IDOK);
          Exit;
        end;
        DeleteFile(TempPath);
      end;
      if not FileExists(DownloadedSetup) then
      begin
        InvalidManifest(DownloadedSetup);
        Exit;
      end;
      Result := True;
    except
      if not DownloadPage.AbortedByUser then
      begin
        Error := GetExceptionMessage;
        SuppressibleMsgBox(
          M2('OnlineDownloadFailed', DownloadPage.LastBaseNameOrUrl, Error),
          mbCriticalError, MB_OK, IDOK);
      end;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

function EnsureArtifacts(): Boolean;
begin
  Result := ArtifactsReady;
  if Result then
    Exit;
  SelectedStack := StackFromSelection();
  if not DownloadManifest() then
    Exit;
  if not PrepareArtifactDownloads() then
    Exit;
  Result := DownloadArtifacts();
  if Result then
    ArtifactsReady := True;
end;

function LaunchOfflineSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not Exec(DownloadedSetup, '/SP- /LANG=' + ActiveLanguage(),
    ExpandConstant('{tmp}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
  begin
    SuppressibleMsgBox(
      M1('OnlineLaunchFailed', SysErrorMessage(DLLGetLastError)),
      mbCriticalError, MB_OK, IDOK);
    Exit;
  end;
  if ResultCode <> 0 then
  begin
    SuppressibleMsgBox(
      M1('OnlineInstallerFailed', IntToStr(ResultCode)),
      mbError, MB_OK, IDOK);
    Exit;
  end;
  Result := True;
end;

procedure InitializeWizard;
begin
  HardwarePage := CreateInputOptionPage(
    wpWelcome, M('OnlineHardwareTitle'), M('OnlineHardwareSubtitle'),
    M('OnlineHardwarePrompt'), True, False);
  HardwarePage.Add(M('OnlineAuto'));
  HardwarePage.Add(M('OnlineCpu'));
  HardwarePage.Add(M('OnlineCuda126'));
  HardwarePage.Add(M('OnlineCuda128'));
  HardwarePage.Add(M('OnlineRocm10'));
  HardwarePage.Add(M('OnlineDirectML'));
  HardwarePage.SelectedValueIndex := 0;

  DownloadPage := CreateDownloadPage(
    M('OnlineDownloadTitle'), M('OnlineDownloadSubtitle'), nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = HardwarePage.ID then
  begin
    if SelectedStack <> StackFromSelection() then
    begin
      SelectedStack := '';
      DownloadedSetup := '';
      ArtifactsReady := False;
    end;
  end
  else if CurPageID = wpReady then
  begin
    Result := EnsureArtifacts();
    if Result then
      Result := LaunchOfflineSetup();
  end;
end;
