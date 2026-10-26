@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Read README.md for setup instructions.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\desktop.py
if errorlevel 1 pause
