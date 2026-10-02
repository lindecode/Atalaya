# Quita lo que creo el instalador. Los datos (data\, reports\) solo se borran si se confirma expresamente.
. "$PSScriptRoot\comun.ps1"

Write-Paso "Deteniendo Atalaya"
& (Join-Path $PSScriptRoot 'detener.ps1')

Write-Paso "Accesos directos e inicio automatico"
foreach ($path in @((Get-DesktopShortcut), (Get-StartupShortcut), (Get-MenuFolder))) {
    if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force; Write-Ok "Eliminado $path" }
}

Write-Paso "Permisos de administrador"
$permisos = Join-Path $PSScriptRoot 'configurar-permisos.ps1'
try { $estado = & $permisos -MostrarEstado | Out-String | ConvertFrom-Json } catch { $estado = $null }
if (-not $estado) {
    Write-Aviso "No se pudo comprobar la configuracion de permisos; revisela con: configurar-permisos.bat revertir"
} elseif ($estado.configuradoPorAtalaya) {
    Write-Host "  configurar-permisos cambio el grupo 'Lectores del registro de eventos' y el log del firewall."
    if (Confirm-Paso "Restaurar el estado anterior? (pide administrador una vez)" $true) {
        & $permisos -Revertir
    } else {
        Write-Host "  Puede hacerlo despues con: configurar-permisos.bat revertir"
    }
} else {
    Write-Ok "No hay permisos configurados por Atalaya"
}

$ownVenv = Join-Path $Root '.venv'
if ((Test-Path $ownVenv) -and (Confirm-Paso "Borrar el entorno de Python de Atalaya ($ownVenv)?" $true)) {
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

Write-Host "  Ollama y sus modelos no se tocan; se desinstalan desde Configuracion > Aplicaciones."
