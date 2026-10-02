@echo off
rem network-llm - Abre el panel (arranca Ollama y la GUI si hace falta)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\iniciar.ps1" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
