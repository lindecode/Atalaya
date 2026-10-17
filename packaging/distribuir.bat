@echo off
rem Atalaya - Genera el instalador .exe y el paquete .msi listos para distribuir en dist\ (ver packaging\README.md)
rem Opciones: -ConZip  -SinMsi  -SinExe  -SinPrueba  -SinPreguntar
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0distribuir.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
