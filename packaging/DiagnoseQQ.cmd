@echo off
setlocal
set "SHIXU_DIAG_ROOT="
if exist "%~dp0python\python.exe" set "SHIXU_DIAG_ROOT=%~dp0"
if not defined SHIXU_DIAG_ROOT for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{9A26F6DF-9213-4D37-8AB1-0C826146AC18}_is1" /v InstallLocation 2^>nul') do set "SHIXU_DIAG_ROOT=%%B"
if not exist "%SHIXU_DIAG_ROOT%\python\python.exe" (
  echo Shixu installation not found. Place this folder inside the installed app folder.
  pause
  exit /b 1
)
set "SHIXU_DIAG_SCRIPT=%~dp0diagnose_qq.py"
if not exist "%SHIXU_DIAG_SCRIPT%" if exist "%~dp0scripts\diagnose_qq.py" set "SHIXU_DIAG_SCRIPT=%~dp0scripts\diagnose_qq.py"
"%SHIXU_DIAG_ROOT%\python\python.exe" -B -X utf8 "%SHIXU_DIAG_SCRIPT%" --root "%SHIXU_DIAG_ROOT%\." --output "%~dp0qq-diagnostic.json"
if errorlevel 1 (
  echo Diagnosis failed. No login or collection settings were changed.
  pause
  exit /b 1
)
echo Report: qq-diagnostic.json in this folder.
pause
