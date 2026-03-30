@echo off
setlocal

cd /d "%~dp0"

set "PY="
if exist ".venv313\Scripts\python.exe" set "PY=.venv313\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not defined PY (
  echo [ERROR] Python virtual environment not found.
  echo Expected one of:
  echo   .venv313\Scripts\python.exe
  echo   .venv\Scripts\python.exe
  exit /b 1
)

"%PY%" freeagent_console.py %*
exit /b %ERRORLEVEL%
