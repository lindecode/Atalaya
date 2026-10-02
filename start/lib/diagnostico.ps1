# Comprueba la instalacion y dice que falta. No modifica nada.
# Lo que necesita Python lo hace `main.py doctor`; aqui solo lo previo (hay Python?) y los servicios.
. "$PSScriptRoot\comun.ps1"
$ErrorActionPreference = 'Continue'

Write-Paso "Python"
$python = Find-VenvPython
if (-not $python) {
    Write-Fallo "Sin Python para Atalaya."
    Write-Host "  Use el instalador Atalaya-Setup.exe (ya lo incluye) o ejecute start\instalar.bat."
    Write-Host "  Requisitos completos: README\README.instalacion.md"
    exit 1
}
Write-Ok "$python $(if (Test-BundledRuntime) { '(incluido)' })"

Write-Paso "Servicios de Atalaya"
if (Test-Port $GuiPort) { Write-Ok "Panel en http://127.0.0.1:$GuiPort" } else { Write-Host "  Panel detenido" }
$watch = Get-GuiProcesses | Where-Object { $_.CommandLine -match 'main\.py"?\s+watch\b' }
if ($watch) { Write-Ok "Monitor de archivos en marcha" } else { Write-Host "  Monitor de archivos detenido" }
if (Test-Path (Get-StartupShortcut)) { Write-Ok "Monitor con inicio automatico" } else { Write-Host "  Monitor sin inicio automatico" }

Write-Paso "Requisitos, LLM y permisos"
Invoke-Tool @('doctor') | Out-Null
