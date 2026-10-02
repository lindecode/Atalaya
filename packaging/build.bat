@echo off
rem Atalaya - Compila el ZIP portable y el instalador .exe (ver packaging\README.md)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
