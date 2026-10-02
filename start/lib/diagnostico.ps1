# Comprueba la instalacion y dice que falta para cada funcion. No modifica nada.
. "$PSScriptRoot\comun.ps1"
$ErrorActionPreference = 'Continue'

Write-Paso "Python"
$python = Find-VenvPython
if ($python) {
    Write-Ok "$python ($(& $python --version 2>&1))"
    & $python -c "import psutil, win32evtlog, watchdog, ollama, streamlit, pydantic" 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Ok "Dependencias completas" } else { Write-Fallo "Faltan dependencias: ejecute start\instalar.bat" }
} else {
    Write-Fallo "Sin entorno de Python: ejecute start\instalar.bat"
}

Write-Paso "Ollama"
$ollama = Find-Ollama
if (-not $ollama) { Write-Fallo "No instalado (las reglas funcionan; sin explicaciones ni chat)" }
elseif (Test-Port $OllamaPort) {
    Write-Ok "En marcha en 127.0.0.1:$OllamaPort"
    if ($python) { Invoke-Tool @('models') | Out-Null }
} else { Write-Aviso "Instalado pero detenido (iniciar.bat y recolectar.bat lo arrancan)" }

Write-Paso "Servicios de Atalaya"
if (Test-Port $GuiPort) { Write-Ok "Panel en http://127.0.0.1:$GuiPort" } else { Write-Host "  Panel detenido" }
$watch = Get-GuiProcesses | Where-Object { $_.CommandLine -match 'main\.py"?\s+watch\b' }
if ($watch) { Write-Ok "Monitor de archivos en marcha" } else { Write-Host "  Monitor de archivos detenido" }
if (Test-Path (Get-StartupShortcut)) { Write-Ok "Monitor con inicio automatico" } else { Write-Host "  Monitor sin inicio automatico" }

Write-Paso "Permisos para cada fuente"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$readers = $identity.Groups | Where-Object { $_.Value -eq 'S-1-5-32-573' }
if ($admin) { Write-Ok "Sesion de administrador: todas las fuentes disponibles" }
elseif ($readers) { Write-Ok "Accesos y RDP (Security): legibles via 'Lectores del registro de eventos'" }
else { Write-Aviso "Accesos y RDP (Security): sin permiso. Ejecute start\configurar-permisos.bat (y cierre sesion)" }
if (Test-Path $FirewallLog) { Write-Ok "Log del firewall: $FirewallLog" }
else { Write-Aviso "Log del firewall no configurado: start\configurar-permisos.bat" }
if (Get-WinEvent -ListLog 'Microsoft-Windows-Sysmon/Operational' -ErrorAction SilentlyContinue) { Write-Ok "Sysmon instalado" }
else { Write-Host "  Sysmon no instalado (opcional, ver README\README.md, fase 5)" }

if ($python) {
    Write-Paso "Base de datos"
    Invoke-Tool @('status') | Out-Null
}
