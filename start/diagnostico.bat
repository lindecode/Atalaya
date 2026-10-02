@echo off
rem Atalaya - Comprueba la instalacion y los permisos
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\diagnostico.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
