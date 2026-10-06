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
$tray = Get-GuiProcesses | Where-Object { $_.CommandLine -match 'main\.py"?\s+tray\b' }
if ($tray) { Write-Ok "Atalaya en segundo plano (icono junto al reloj)" } else { Write-Host "  Atalaya no esta en la bandeja (start\iniciar.bat lo arranca)" }
if (Test-Path (Get-StartupShortcut)) { Write-Ok "Inicio automatico al entrar en Windows" } else { Write-Host "  Sin inicio automatico" }
$task = Get-ScheduledTask -TaskName 'Atalaya - ciclo automatico' -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName 'Atalaya - ciclo automatico'
    $action = @($task.Actions)[0]
    $valid = $action -and (Test-Path -LiteralPath $action.Execute) -and (Test-Path -LiteralPath $action.WorkingDirectory)
    if ($valid) { Write-Ok "Ciclo automatico: $($task.State); proxima: $($info.NextRunTime); ultimo codigo: $($info.LastTaskResult)" }
    else { Write-Fallo "La tarea automatica apunta a una instalacion que ya no existe; desactivela y vuelva a activarla" }
} else { Write-Host "  Ciclo automatico: desactivado" }

Write-Paso "Requisitos, LLM y permisos"
Invoke-Tool @('doctor') | Out-Null
