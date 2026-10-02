# Abre el panel: arranca Ollama si hace falta, lanza la GUI (si no esta ya en marcha) y abre el navegador.
. "$PSScriptRoot\comun.ps1"

$url = "http://127.0.0.1:$GuiPort"
$python = Get-Python

if (Test-Port $GuiPort) {
    Write-Ok "El panel ya esta en marcha"
} else {
    Write-Paso "Preparando network-llm"
    Start-OllamaIfNeeded | Out-Null
    # Ventana minimizada: cerrarla (o start\detener.bat) apaga el panel
    Start-Process -FilePath $python -ArgumentList 'main.py', 'gui' -WorkingDirectory $Root -WindowStyle Minimized
    if (-not (Wait-Port $GuiPort 60)) {
        Write-Fallo "El panel no respondio en 60 s. Revise la ventana minimizada 'python' o ejecute start\diagnostico.bat"
        exit 1
    }
    Write-Ok "Panel en $url"
}
Start-Process $url
