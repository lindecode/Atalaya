@echo off
rem Atalaya - Monitor de archivos en vivo (Ctrl+C para detener)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\vigilar.ps1" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
