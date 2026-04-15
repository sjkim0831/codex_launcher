@echo off
setlocal

set "TASK_NAME=CarbonetCodexAccountScan"
set "INSTANCE_ID=%~1"
if "%INSTANCE_ID%"=="" set "INSTANCE_ID=default"
set "INTERVAL_MIN=%CARBONET_ACCOUNT_SCAN_INTERVAL_MIN%"
if "%INTERVAL_MIN%"=="" set "INTERVAL_MIN=15"

set "SCRIPT_DIR=%~dp0"
set "SCAN_CMD=%SCRIPT_DIR%account-scan.cmd %INSTANCE_ID%"

schtasks /Create /F /SC MINUTE /MO %INTERVAL_MIN% /TN "%TASK_NAME%" /TR "\"%SCAN_CMD%\"" >nul
if errorlevel 1 (
  echo Failed to create scheduled task %TASK_NAME%
  exit /b 1
)

echo Created scheduled task %TASK_NAME% with interval %INTERVAL_MIN% minutes.
schtasks /Query /TN "%TASK_NAME%"
exit /b 0
