# Activa o desactiva el arranque del monitor de archivos al iniciar sesion (acceso directo en la
# carpeta Inicio del usuario: no necesita administrador).
param([ValidateSet('activar', 'desactivar', 'estado', 'alternar')][string]$Accion = 'alternar')
. "$PSScriptRoot\comun.ps1"

$shortcut = Get-StartupShortcut
if ($Accion -eq 'alternar') {   # doble clic sin argumentos: preguntar lo contrario de lo actual
    if (Test-Path $shortcut) {
        Write-Host "  Atalaya arranca en la bandeja (con el monitor) al iniciar sesion."
        $Accion = if (Confirm-Paso "Desactivarlo?" $false) { 'desactivar' } else { 'estado' }
    } else {
        Write-Host "  Atalaya NO arranca al iniciar sesion."
        $Accion = if (Confirm-Paso "Activarlo?" $true) { 'activar' } else { 'estado' }
    }
}
switch ($Accion) {
    'activar' {
        New-TrayStartupShortcut
        Write-Ok "Al iniciar sesion, Atalaya arrancara en la bandeja (junto al reloj) con el monitor activo"
    }
    'desactivar' {
        $removed = $false
        foreach ($path in @($shortcut, (Get-LegacyStartupShortcut))) {
            if (Test-Path $path) { Remove-Item $path; $removed = $true }
        }
        if ($removed) { Write-Ok "Inicio automatico desactivado" } else { Write-Ok "No estaba activado" }
    }
    'estado' {
        if (Test-Path $shortcut) { Write-Ok "Activado ($shortcut)" } else { Write-Host "  Desactivado" }
        Write-Host "  Uso: inicio-automatico.bat activar | desactivar"
    }
}
