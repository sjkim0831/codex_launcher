@echo off
setlocal

set "SCRIPT_DIR=%~dp0.."
set "INSTANCE_ID=%~1"
if "%INSTANCE_ID%"=="" set "INSTANCE_ID=default"

set "PYTHON_EXE=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYTHON_EXE=py -3"

%PYTHON_EXE% "%SCRIPT_DIR%\app\server.py" --app-root "%SCRIPT_DIR%" scan-accounts --instance "%INSTANCE_ID%"
exit /b %ERRORLEVEL%
