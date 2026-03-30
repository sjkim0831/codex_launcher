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
  set "EXITCODE=1"
  goto :end
)

set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" (
  set "NO_PAUSE=1"
  shift
)

echo [INFO] Using %PY%
if "%NO_PAUSE%"=="1" (
  "%PY%" START_FREEAGENT.py %1 %2 %3 %4 %5 %6 %7 %8 %9
) else (
  "%PY%" START_FREEAGENT.py %*
)
set "EXITCODE=%ERRORLEVEL%"

:end
if not "%NO_PAUSE%"=="1" pause
exit /b %EXITCODE%
