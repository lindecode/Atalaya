# Abre Atalaya: arranca la bandeja (icono junto al reloj, sin ventana) que a su vez arranca Ollama si hace
# falta, el panel y el navegador. Si Atalaya ya esta en la bandeja, solo abre el panel.
. "$PSScriptRoot\comun.ps1"

Start-Process -FilePath (Get-PythonW) -ArgumentList 'main.py', 'tray' -WorkingDirectory $Root
Write-Ok "Atalaya arranca en segundo plano: busque su icono junto al reloj (area de notificacion)."
