@echo off
rem Atalaya - Instala o repara Atalaya (Python, dependencias, Ollama, accesos directos)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\instalar.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
