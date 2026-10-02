# Activa o desactiva el arranque del monitor de archivos al iniciar sesion (acceso directo en la
# carpeta Inicio del usuario: no necesita administrador).
param([ValidateSet('activar', 'desactivar', 'estado', 'alternar')][string]$Accion = 'alternar')
. "$PSScriptRoot\comun.ps1"

$shortcut = Get-StartupShortcut
if ($Accion -eq 'alternar') {   # doble clic sin argumentos: preguntar lo contrario de lo actual
    if (Test-Path $shortcut) {
        Write-Host "  El monitor arranca al iniciar sesion."
        $Accion = if (Confirm-Paso "Desactivarlo?" $false) { 'desactivar' } else { 'estado' }
    } else {
        Write-Host "  El monitor NO arranca al iniciar sesion."
        $Accion = if (Confirm-Paso "Activarlo?" $true) { 'activar' } else { 'estado' }
    }
}
switch ($Accion) {
    'activar' {
        New-Shortcut $shortcut (Join-Path $StartDir 'vigilar.bat') 'Monitor de archivos de Atalaya' 7
        Write-Ok "El monitor arrancara minimizado al iniciar sesion"
    }
    'desactivar' {
        if (Test-Path $shortcut) { Remove-Item $shortcut; Write-Ok "Inicio automatico desactivado" }
        else { Write-Ok "No estaba activado" }
    }
    'estado' {
        if (Test-Path $shortcut) { Write-Ok "Activado ($shortcut)" } else { Write-Host "  Desactivado" }
        Write-Host "  Uso: inicio-automatico.bat activar | desactivar"
    }
}
