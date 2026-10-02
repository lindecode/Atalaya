# Quita lo que creo el instalador. Los datos (data\, reports\) solo se borran si se confirma expresamente.
. "$PSScriptRoot\comun.ps1"

Write-Paso "Deteniendo network-llm"
& (Join-Path $PSScriptRoot 'detener.ps1')

Write-Paso "Accesos directos e inicio automatico"
foreach ($path in @((Get-DesktopShortcut), (Get-StartupShortcut), (Get-MenuFolder))) {
    if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force; Write-Ok "Eliminado $path" }
}

$ownVenv = Join-Path $Root '.venv'
if ((Test-Path $ownVenv) -and (Confirm-Paso "Borrar el entorno de Python de network-llm ($ownVenv)?" $true)) {
    Remove-Item -LiteralPath $ownVenv -Recurse -Force
    Write-Ok "Entorno eliminado"
}
# El ..\.venv del repositorio del curso no se toca: lo usan otras demos

Write-Paso "Datos"
Write-Host "  data\ contiene la base de datos con su historial de alertas; reports\ los informes."
if ((Read-Host "  Escriba BORRAR para eliminarlos (Enter para conservarlos)") -ceq 'BORRAR') {
    foreach ($name in 'data', 'reports') {
        $path = Join-Path $Root $name
        if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force; Write-Ok "Eliminado $path" }
    }
} else { Write-Ok "Datos conservados" }

Write-Host "`n  Los permisos (grupo de lectores y log del firewall) se revierten con: configurar-permisos.bat revertir"
Write-Host "  Ollama y sus modelos no se tocan; se desinstalan desde Configuracion > Aplicaciones."
