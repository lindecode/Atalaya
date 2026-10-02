@echo off
rem network-llm - Detiene el panel y el monitor de archivos
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\detener.ps1" %*
set "CODE=%ERRORLEVEL%"
timeout /t 4 >nul 2>nul
exit /b %CODE%
