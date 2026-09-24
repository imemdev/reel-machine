@echo off
rem Start Reel Machine on Windows (double-click or run from Command Prompt).
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" goto missing
if not exist "frontend\node_modules" goto missing
".venv\Scripts\python.exe" scripts\run_local.py
exit /b %ERRORLEVEL%
:missing
echo Missing project dependencies. Follow the Windows steps in README.md first. 1>&2
exit /b 1
