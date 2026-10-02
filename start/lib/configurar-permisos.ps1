# Configuracion UNICA como administrador para que el uso diario no necesite elevacion:
#   1. Anade al usuario al grupo "Lectores del registro de eventos" (S-1-5-32-573): puede leer los
#      registros Security (accesos, RDP, fuerza bruta) y Sysmon sin ser administrador.
#   2. Activa el log de paquetes bloqueados del firewall en %ProgramData%\network-llm\firewall,
#      una carpeta que el usuario puede leer (la ruta por defecto en System32 exige administrador).
# Con -Revertir deshace ambos cambios.
param([switch]$Elevado, [string]$UsuarioSid, [switch]$Revertir)
. "$PSScriptRoot\comun.ps1"

$ReadersSid = 'S-1-5-32-573'
$FirewallDir = Split-Path -Parent $FirewallLog
$DefaultFirewallLog = '%systemroot%\system32\LogFiles\Firewall\pfirewall.log'

if (-not $Elevado) {
    # Parte sin elevar: identifica al usuario real (el SID) antes de pedir UAC, por si el administrador
    # que confirma es otra cuenta.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($Revertir) {
        Write-Host "Se quitara al usuario del grupo de lectores de eventos y se desactivara el log del firewall."
    } else {
        Write-Host "Se pedira permiso de administrador (UAC) UNA vez para:"
        Write-Host "  - Anadir su usuario al grupo 'Lectores del registro de eventos'"
        Write-Host "  - Registrar en $FirewallDir los paquetes que bloquea el firewall"
        Write-Host "Despues network-llm no necesita ejecutarse como administrador."
    }
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Elevado', '-UsuarioSid', $sid)
    if ($Revertir) { $arguments += '-Revertir' }
    try {
        $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    } catch {
        Write-Fallo "Se cancelo la solicitud de administrador; no se cambio nada."
        exit 1
    }
    if ($process.ExitCode -eq 0) {
        Write-Ok "Configuracion aplicada."
        if (-not $Revertir) { Write-Aviso "Cierre sesion y vuelva a entrar para que el permiso de lectura de eventos surta efecto." }
    } else { Write-Fallo "La configuracion termino con errores (codigo $($process.ExitCode))." }
    exit $process.ExitCode
}

# Parte elevada ---------------------------------------------------------------------------------
$failed = $false
$readers = Get-LocalGroup -SID $ReadersSid
try {
    if ($Revertir) {
        Remove-LocalGroupMember -Group $readers -Member $UsuarioSid -ErrorAction Stop
        Write-Ok "Usuario quitado de '$($readers.Name)'"
    } else {
        Add-LocalGroupMember -Group $readers -Member $UsuarioSid -ErrorAction Stop
        Write-Ok "Usuario anadido a '$($readers.Name)'"
    }
} catch [Microsoft.PowerShell.Commands.MemberExistsException] {
    Write-Ok "El usuario ya pertenecia a '$($readers.Name)'"
} catch [Microsoft.PowerShell.Commands.MemberNotFoundException] {
    Write-Ok "El usuario no pertenecia a '$($readers.Name)'"
} catch {
    Write-Fallo "Grupo de lectores de eventos: $($_.Exception.Message)"; $failed = $true
}

try {
    if ($Revertir) {
        Set-NetFirewallProfile -All -LogBlocked False -LogFileName $DefaultFirewallLog
        Write-Ok "Log del firewall desactivado y devuelto a su ruta por defecto"
    } else {
        New-Item -ItemType Directory -Force -Path $FirewallDir | Out-Null
        # El servicio del firewall (MpsSvc) debe poder escribir; el usuario, solo leer
        & icacls $FirewallDir /grant 'NT SERVICE\mpssvc:(OI)(CI)M' /grant "*${UsuarioSid}:(OI)(CI)RX" | Out-Null
        if ($LASTEXITCODE) { throw "icacls termino con codigo $LASTEXITCODE" }
        Set-NetFirewallProfile -All -LogBlocked True -LogMaxSizeKilobytes 16384 -LogFileName $FirewallLog
        Write-Ok "Firewall registrando paquetes bloqueados en $FirewallLog"
    }
} catch {
    Write-Fallo "Firewall: $($_.Exception.Message)"; $failed = $true
}

Read-Host "`nPulse Enter para cerrar esta ventana de administrador"
if ($failed) { exit 1 } else { exit 0 }
