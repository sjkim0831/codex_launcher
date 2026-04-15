@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0.."
set "INSTANCE_ID=%CARBONET_INSTANCE_ID%"
if "%INSTANCE_ID%"=="" set "INSTANCE_ID=default"

set "REAL_CODEX_BIN=%CARBONET_REAL_CODEX_BIN%"
if "%REAL_CODEX_BIN%"=="" set "REAL_CODEX_BIN=codex"

set "OUTPUT_FILE=%TEMP%\carbonet-codex-watch-%RANDOM%-%RANDOM%.log"

call %REAL_CODEX_BIN% %* > "%OUTPUT_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%OUTPUT_FILE%"

set "PYTHON_EXE=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYTHON_EXE=py -3"

%PYTHON_EXE% "%SCRIPT_DIR%\app\server.py" --app-root "%SCRIPT_DIR%" ingest-codex-output --instance "%INSTANCE_ID%" --exit-code %EXIT_CODE% --output-file "%OUTPUT_FILE%" >nul 2>nul
del /q "%OUTPUT_FILE%" >nul 2>nul

exit /b %EXIT_CODE%
