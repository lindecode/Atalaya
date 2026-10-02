@echo off
rem Atalaya - Configuracion unica como administrador (configurar-permisos.bat revertir para deshacer)
setlocal
set "EXTRA="
if /i "%~1"=="revertir" set "EXTRA=-Revertir"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\configurar-permisos.ps1" %EXTRA%
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
