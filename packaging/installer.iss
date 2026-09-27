#ifndef StageDir
  #error StageDir must be supplied by build.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build.ps1
#endif
#ifndef ArtifactDir
  #error ArtifactDir must be supplied by build.ps1
#endif

[Setup]
AppId={{C2DAE9CC-6E39-4C50-BB76-54D3A915D64A}
AppName=小红书选品工作台
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\XhsXuanpin
DefaultGroupName=小红书选品工作台
OutputDir={#ArtifactDir}
OutputBaseFilename=XhsXuanpin-Setup-win-x64
ArchitecturesAllowed=x64compatible
SetupArchitecture=x64
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
SetupIconFile={#SourceDir}\src\XhsXuanpin.App\Assets\logo.ico
UninstallDisplayIcon={app}\XhsXuanpin.App.exe
AppMutex=Local\XhsXuanpin.App,Local\XhsXuanpin.Watchdog
CloseApplications=no

[Files]
Source: "{#StageDir}\setup\install-deps.ps1"; Flags: dontcopy
Source: "{#StageDir}\backend\requirements.txt"; Flags: dontcopy
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\小红书选品工作台"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\launch-watchdog.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\XhsXuanpin.App.exe"
Name: "{autodesktop}\小红书选品工作台"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\launch-watchdog.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\XhsXuanpin.App.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked

[Code]
var
  DependencyLabels: array[1..5] of TNewStaticText;
  CurrentDependencyIndex: Integer;
  CurrentDependencyTitle: String;

procedure InitializeWizard;
var
  I: Integer;
begin
  for I := 1 to 5 do
  begin
    DependencyLabels[I] := TNewStaticText.Create(WizardForm);
    DependencyLabels[I].Parent := WizardForm.InstallingPage;
    DependencyLabels[I].Left := ScaleX(16);
    DependencyLabels[I].Top := ScaleY(110 + (I - 1) * 25);
    DependencyLabels[I].Width := WizardForm.InstallingPage.Width - ScaleX(32);
    DependencyLabels[I].Height := ScaleY(22);
  end;
  DependencyLabels[1].Caption := '○ WebView2 运行环境：0%';
  DependencyLabels[2].Caption := '○ Python 3.12：0%';
  DependencyLabels[3].Caption := '○ Google Chrome：0%';
  DependencyLabels[4].Caption := '○ MuMu 模拟器：0%';
  DependencyLabels[5].Caption := '○ 工作台 Python 依赖：0%';
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
    DependencyLabels[CurrentDependencyIndex].Caption := '… ' + CurrentDependencyTitle +
      '：下载 ' + IntToStr((Progress * 100) div ProgressMax) + '%'
  else
    DependencyLabels[CurrentDependencyIndex].Caption := '… ' + CurrentDependencyTitle +
      '：已下载 ' + IntToStr(Progress div 1048576) + ' MB';
  WizardForm.Repaint;
  Result := True;
end;

function RunDependency(const Step: String; CheckOnly: Boolean; const InstallerPath: String): Boolean;
var
  ResultCode: Integer;
  Params: String;
begin
  Params := '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\install-deps.ps1') + '" -Step ' + Step +
    ' -RequirementsPath "' + ExpandConstant('{tmp}\requirements.txt') + '"';
  if CheckOnly then Params := Params + ' -CheckOnly';
  if InstallerPath <> '' then Params := Params + ' -InstallerPath "' + InstallerPath + '"';
  if Step = 'MuMuStartup' then Params := Params + ' -StartupReportPath "' +
    ExpandConstant('{tmp}\mumu-startup-status.txt') + '"';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure InstallDependency(Index: Integer; const Step, Title, Url, FileName: String);
var
  InstallerPath: String;
begin
  CurrentDependencyIndex := Index;
  CurrentDependencyTitle := Title;
  DependencyLabels[Index].Caption := '… ' + Title + '：正在检查';
  WizardForm.StatusLabel.Caption := '运行依赖：已完成 ' + IntToStr(Index - 1) + '/5，正在处理 ' + Title;
  WizardForm.Repaint;
  if (Step <> 'PythonPackages') and RunDependency(Step, True, '') then
  begin
    DependencyLabels[Index].Caption := '✓ ' + Title + '：100%（已安装）';
    WizardForm.ProgressGauge.Position := Index * 20;
    WizardForm.Repaint;
    exit;
  end;
  InstallerPath := '';
  if Url <> '' then
  begin
    try
      DownloadTemporaryFile(Url, FileName, '', @OnDownloadProgress);
    except
      DependencyLabels[Index].Caption := '× ' + Title + '：下载失败';
      WizardForm.Repaint;
      RaiseException(Title + ' 下载失败：' + GetExceptionMessage);
    end;
    InstallerPath := ExpandConstant('{tmp}\' + FileName);
  end;
  if Step = 'MuMu' then
  begin
    if WizardSilent then
      RaiseException('MuMu 需要在厂商安装窗口确认，请交互运行安装器。');
    MsgBox('接下来将打开 MuMu 官方安装窗口。请完成安装，工作台检测到模拟器后会继续。',
      mbInformation, MB_OK);
  end;
  DependencyLabels[Index].Caption := '… ' + Title + '：安装中';
  WizardForm.Repaint;
  if not RunDependency(Step, False, InstallerPath) then
  begin
    DependencyLabels[Index].Caption := '× ' + Title + '：失败';
    WizardForm.Repaint;
    RaiseException(Title + ' 安装失败。详情见 ' +
      ExpandConstant('{localappdata}\XhsXuanpin\data\logs\setup.log'));
  end;
  DependencyLabels[Index].Caption := '✓ ' + Title + '：100%';
  WizardForm.ProgressGauge.Position := Index * 20;
  WizardForm.Repaint;
end;

procedure InstallDependencyWithRetry(Index: Integer; const Step, Title, Url, FileName: String);
var
  ErrorText: String;
begin
  while True do
  begin
    try
      InstallDependency(Index, Step, Title, Url, FileName);
      exit;
    except
      ErrorText := GetExceptionMessage;
      Log(Title + '：' + ErrorText);
      if WizardSilent or (MsgBox(ErrorText + #13#10#13#10 +
        '重试当前步骤？已完成的依赖不会重新安装。', mbError, MB_RETRYCANCEL) <> IDRETRY) then
        RaiseException(ErrorText);
    end;
  end;
end;

procedure ConfigureMuMuStartup;
var
  ReportPath: String;
  Remaining: String;
  Entries: TArrayOfString;
  I: Integer;
begin
  ReportPath := ExpandConstant('{tmp}\mumu-startup-status.txt');
  if not WizardSilent then
    MsgBox('工作台文件已安装。接下来将尝试关闭 MuMu 的开机自启项。' + #13#10 +
      '若 Windows 请求管理员权限，请确认这是为了把 MuMu 服务改为手动启动。', mbInformation, MB_OK);
  while True do
  begin
    DeleteFile(ReportPath);
    if RunDependency('MuMuStartup', False, '') then
    begin
      DependencyLabels[4].Caption := '✓ MuMu 已安装；开机自启已关闭';
      Log('MuMu 开机自启配置完成');
      exit;
    end;
    Remaining := '';
    if LoadStringsFromFile(ReportPath, Entries) then
    begin
      for I := 0 to GetArrayLength(Entries) - 1 do
        Remaining := Remaining + Entries[I] + #13#10;
      Remaining := Trim(Remaining);
    end
    else
      Remaining := '状态无法读取，请查看 setup.log';
    if Trim(Remaining) = 'None' then
      Remaining := '未发现剩余自启项，但配置校验失败；请查看 setup.log';
    Log('MuMu 开机自启配置未完成：' + Remaining);
    DependencyLabels[4].Caption := '⚠ MuMu 已安装；部分开机自启未关闭';
    if WizardSilent then exit;
    if MsgBox('工作台已经安装完成，以下 MuMu 自启项仍需处理：' + #13#10 + Remaining + #13#10 + #13#10 +
      '重试请点“重试”；点“取消”将跳过配置并完成安装。',
      mbError, MB_RETRYCANCEL) <> IDRETRY then exit;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ConfigureMuMuStartup;
    exit;
  end;
  if CurStep <> ssInstall then exit;
  try
    ExtractTemporaryFile('install-deps.ps1');
    ExtractTemporaryFile('requirements.txt');
    WizardForm.ProgressGauge.Max := 100;
    WizardForm.ProgressGauge.Position := 0;
    InstallDependencyWithRetry(1, 'WebView2', 'WebView2 运行环境',
      'https://go.microsoft.com/fwlink/p/?LinkId=2124703', 'WebView2Setup.exe');
    InstallDependencyWithRetry(2, 'Python', 'Python 3.12',
      'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe', 'Python-3.12.10-amd64.exe');
    InstallDependencyWithRetry(3, 'Chrome', 'Google Chrome',
      'https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi', 'GoogleChromeEnterprise64.msi');
    InstallDependencyWithRetry(4, 'MuMu', 'MuMu 模拟器',
      'https://mumu.nie.netease.com/api/dl/win?channel=gw-win', 'MuMuSetup.exe');
    InstallDependencyWithRetry(5, 'PythonPackages', '工作台 Python 依赖', '', '');
  except
    Log('依赖安装未完成：' + GetExceptionMessage);
    if not WizardSilent then
      MsgBox('依赖安装未完成：' + GetExceptionMessage + #13#10 +
        '工作台尚未安装。检查问题后可重新运行安装器，已完成的依赖会自动复用。',
        mbError, MB_OK);
    Abort;
  end;
end;
