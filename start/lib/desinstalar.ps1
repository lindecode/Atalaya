# Quita lo que crearon instalar.bat / el instalador. Los datos del usuario solo se borran si se confirma.
# -DesdeDesinstalador: lo llama el desinstalador de Windows (Inno Setup), que ya quita sus accesos
# directos y la carpeta del programa; aqui solo se detiene Atalaya, se revierten permisos y se pregunta por los datos.
param([switch]$DesdeDesinstalador, [switch]$Silencioso)
. "$PSScriptRoot\comun.ps1"
$Host.UI.RawUI.WindowTitle = 'Desinstalar Atalaya'

Write-Paso "Deteniendo Atalaya"
& (Join-Path $PSScriptRoot 'detener.ps1')

if (-not $DesdeDesinstalador) {
    Write-Paso "Accesos directos e inicio automatico"
    foreach ($path in @((Get-DesktopShortcut), (Get-StartupShortcut), (Get-LegacyStartupShortcut), (Get-MenuFolder))) {
        if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force; Write-Ok "Eliminado $path" }
    }
}

if ($Silencioso) {
    # Sin nadie delante: no se pide UAC ni se borra nada del usuario
    Write-Ok "Desinstalacion silenciosa: se conservan datos ($(Get-DataHome)) y permisos"
    exit 0
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
    } elseif ($DesdeDesinstalador) {
        Write-Aviso "Quedan aplicados. Para revertirlos despues necesitara reinstalar Atalaya (configurar-permisos.bat revertir)."
    } else {
        Write-Host "  Puede hacerlo despues con: configurar-permisos.bat revertir"
    }
} else {
    Write-Ok "No hay permisos configurados por Atalaya"
}

if (-not $DesdeDesinstalador) {
    $ownVenv = Join-Path $Root '.venv'
    if ((Test-Path $ownVenv) -and (Confirm-Paso "Borrar el entorno de Python de Atalaya ($ownVenv)?" $true)) {
        Remove-Item -LiteralPath $ownVenv -Recurse -Force
        Write-Ok "Entorno eliminado"
    }
}

Write-Paso "Datos"
$home_ = Get-DataHome
if (Test-Path $home_) {
    Write-Host "  $home_ contiene la base de datos (alertas, historial del chat) y los informes."
    if ((Read-Host "  Escriba BORRAR para eliminarlos (Enter para conservarlos)") -ceq 'BORRAR') {
        Remove-Item -LiteralPath $home_ -Recurse -Force
        Write-Ok "Eliminado $home_"
    } else { Write-Ok "Datos conservados en $home_ (una nueva instalacion los reutiliza)" }
} else { Write-Ok "No hay datos guardados" }

Write-Host "`n  Ollama y sus modelos no se tocan; se desinstalan desde Configuracion > Aplicaciones."
if ($DesdeDesinstalador) { Read-Host "`n  Pulse Enter para terminar la desinstalacion" | Out-Null }
