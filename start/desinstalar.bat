@echo off
rem Atalaya - Quita accesos directos, inicio automatico y, si se confirma, entorno y datos
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\desinstalar.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
