@echo off
setlocal

set "TASK_NAME=CarbonetCodexAccountScan"
schtasks /Delete /F /TN "%TASK_NAME%"
exit /b %ERRORLEVEL%
