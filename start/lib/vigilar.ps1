# Monitor de archivos en vivo (R08 ransomware / modificacion masiva). Se detiene con Ctrl+C o start\detener.bat.
. "$PSScriptRoot\comun.ps1"

$running = Get-GuiProcesses | Where-Object { $_.CommandLine -match 'main\.py"?\s+watch\b' }
if ($running) { Write-Ok "El monitor ya esta en marcha (PID $(@($running)[0].ProcessId))"; exit 0 }

$Host.UI.RawUI.WindowTitle = 'network-llm - monitor de archivos'
Write-Paso "Monitor de archivos en marcha (Ctrl+C para detener)"
$python = Get-Python
Push-Location $Root
try { & $python 'main.py' 'watch' } finally { Pop-Location }
