@echo off
rem network-llm - Instala o repara network-llm (Python, dependencias, Ollama, accesos directos)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\instalar.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
