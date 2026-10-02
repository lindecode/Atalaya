# Detiene el panel (GUI) y el monitor de archivos. Ollama se deja en marcha: puede usarlo otra aplicacion.
. "$PSScriptRoot\comun.ps1"

$processes = @(Get-GuiProcesses)
if (-not $processes) { Write-Ok "No hay nada de Atalaya en marcha"; exit 0 }
foreach ($process in $processes) {
    $kind = if ($process.CommandLine -match 'watch') { 'monitor' } else { 'panel' }
    try {
        Stop-Process -Id $process.ProcessId -Force
        Write-Ok "Detenido $kind (PID $($process.ProcessId))"
    } catch {
        Write-Aviso "PID $($process.ProcessId) ya habia terminado"
    }
}
