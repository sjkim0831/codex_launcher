@echo off
setlocal

cd /d "%~dp0"

set "WSL_SCRIPT=/mnt/c/Users/jwchoo/Downloads/freeagent_ultra_codexlike/freeagent_ultra/run_freeagent_wsl.sh"
set "WSL_WORKSPACE=/opt/projects/carbonet"

if not "%~1"=="" set "WSL_WORKSPACE=%~1"

echo [INFO] Launching FreeAgent in WSL...
wsl -e bash -lc "export FREEAGENT_WORKSPACE='%WSL_WORKSPACE%'; bash '%WSL_SCRIPT%'"

exit /b %ERRORLEVEL%

