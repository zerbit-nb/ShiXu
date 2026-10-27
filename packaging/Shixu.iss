#ifndef Payload
  #error Pass /DPayload=absolute-stage-path
#endif
#ifndef Output
  #error Pass /DOutput=absolute-output-path
#endif

[Setup]
AppId={{9A26F6DF-9213-4D37-8AB1-0C826146AC18}
AppName=拾序
AppVersion=1.1.0
AppVerName=拾序 1.1.0
AppPublisher=Shixu Project
DefaultDirName={localappdata}\Programs\Shixu
DefaultGroupName=拾序
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir={#Output}
OutputBaseFilename=Shixu-1.1.0-win-x64-Setup
SetupIconFile={#Payload}\assets\brand\windows\shixu.ico
UninstallDisplayIcon={app}\assets\brand\windows\shixu.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
InfoBeforeFile={#SourcePath}FIRST-RUN.txt
VersionInfoVersion=1.1.0.0
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
FinishedLabel=拾序已安装。请点击 Finish 关闭安装器，再从桌面或开始菜单打开拾序。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#Payload}\package_guard.py"; DestName: "upgrade_guard.py"; Flags: dontcopy
Source: "{#Payload}\scripts\stop_napcat.ps1"; DestName: "upgrade_probe.ps1"; Flags: dontcopy
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\拾序"; Filename: "{app}\python\pythonw.exe"; Parameters: "-B -X utf8 ""{app}\scripts\desktop_window.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\brand\windows\shixu.ico"
Name: "{autodesktop}\拾序"; Filename: "{app}\python\pythonw.exe"; Parameters: "-B -X utf8 ""{app}\scripts\desktop_window.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\brand\windows\shixu.ico"; Tasks: desktopicon

[Code]
var
  GuardCode: Integer;
  GuardExtracted: Boolean;

function ApplicationStopped(): Boolean;
var
  ExitCode: Integer;
  GuardPath, ProbePath: String;
begin
  Result := True;
  GuardCode := 0;
  if FileExists(ExpandConstant('{app}\python\python.exe')) then
  begin
    if IsUninstaller then
    begin
      GuardPath := ExpandConstant('{app}\package_guard.py');
      ProbePath := ExpandConstant('{app}\scripts\stop_napcat.ps1');
    end
    else
    begin
      if not GuardExtracted then
      begin
        ExtractTemporaryFile('upgrade_guard.py');
        ExtractTemporaryFile('upgrade_probe.ps1');
        GuardExtracted := True;
      end;
      GuardPath := ExpandConstant('{tmp}\upgrade_guard.py');
      ProbePath := ExpandConstant('{tmp}\upgrade_probe.ps1');
    end;
    Result := Exec(ExpandConstant('{app}\python\python.exe'),
      '-B -X utf8 "' + GuardPath + '" --root "' + ExpandConstant('{app}') + '" --probe "' + ProbePath + '"',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode);
    if Result then
      Log('Application guard exit code: ' + IntToStr(ExitCode))
    else
      Log('Application guard launch error: ' + IntToStr(ExitCode));
    if Result then GuardCode := ExitCode else GuardCode := 20;
    Result := Result and (ExitCode = 0);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not ApplicationStopped() then
  begin
    if GuardCode = 10 then
      Result := '检测到拾序或其 NapCat 后台仍在运行。请从托盘选择“退出 拾序”并等待完成后重试；旧版请先在应用内退出 NapCat。安装器不会强制停止进程。'
    else
      Result := '无法完成后台退出检查（检查码 ' + IntToStr(GuardCode) + '），未确认有程序正在运行。请保留安装日志供排查，不要删除数据或强制结束 QQ。';
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := ApplicationStopped();
  if not Result then
    MsgBox('无法安全卸载（检查码 ' + IntToStr(GuardCode) + '）。运行中请从托盘选择“退出 拾序”并等待完成；旧版请先退出 NapCat。检查失败请保留日志，勿删除用户数据。', mbError, MB_OK);
end;
