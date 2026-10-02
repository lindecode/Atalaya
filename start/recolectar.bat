@echo off
rem network-llm - Recolecta evidencia, analiza con reglas + LLM y genera el informe
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\recolectar.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
