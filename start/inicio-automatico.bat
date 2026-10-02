@echo off
rem network-llm - Activa/desactiva el monitor al iniciar sesion (activar | desactivar | estado)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\inicio-automatico.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
