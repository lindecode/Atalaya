@echo off
rem Atalaya - Administra el ciclo periodico (activar [minutos] | desactivar | estado)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\automatizacion.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
