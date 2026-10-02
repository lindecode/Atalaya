@echo off
rem network-llm - Borra caches de Python/pytest (no toca datos)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\limpiar-cache.ps1" %*
set "CODE=%ERRORLEVEL%"
timeout /t 4 >nul 2>nul
exit /b %CODE%
