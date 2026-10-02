# Configuracion UNICA como administrador para que el uso diario no necesite elevacion:
#   1. Anade al usuario al grupo "Lectores del registro de eventos" (S-1-5-32-573): puede leer los
#      registros Security (accesos, RDP, fuerza bruta) y Sysmon sin ser administrador.
#   2. Activa el log de paquetes bloqueados del firewall en %ProgramData%\network-llm\firewall,
#      una carpeta que el usuario puede leer (la ruta por defecto en System32 exige administrador).
# Antes de cambiar nada guarda el estado previo en %ProgramData%\network-llm\estado-previo.json;
# -Revertir restaura exactamente ese estado y borra %ProgramData%\network-llm.
# -MostrarEstado imprime el estado actual sin cambiar nada (no necesita administrador).
param([switch]$Elevado, [string]$UsuarioSid, [switch]$Revertir, [switch]$MostrarEstado)
. "$PSScriptRoot\comun.ps1"

$ReadersSid = 'S-1-5-32-573'
$DataDir = Join-Path $env:ProgramData 'network-llm'
$FirewallDir = Split-Path -Parent $FirewallLog
$StateFile = Join-Path $DataDir 'estado-previo.json'
# Valores de fabrica de Windows: se usan al revertir una configuracion hecha sin estado guardado
$WindowsDefaults = @{ LogBlocked = 'NotConfigured'; LogFileName = '%systemroot%\system32\LogFiles\Firewall\pfirewall.log'; LogMaxSizeKilobytes = 4096 }

function Get-ReadersMemberSids {
    # ADSI en lugar de Get-LocalGroupMember, que falla si el grupo contiene SIDs huerfanos
    $group = Get-LocalGroup -SID $ReadersSid
    $adsi = [ADSI]"WinNT://$env:COMPUTERNAME/$($group.Name),group"
    @($adsi.psbase.Invoke('Members')) | ForEach-Object {
        $bytes = $_.GetType().InvokeMember('objectSid', 'GetProperty', $null, $_, $null)
        (New-Object Security.Principal.SecurityIdentifier($bytes, 0)).Value
    }
}

function Get-CurrentState([string]$sid) {
    [ordered]@{
        version    = 1
        capturedAt = (Get-Date).ToUniversalTime().ToString('o')
        userSid    = $sid
        wasMember  = [bool](@(Get-ReadersMemberSids) -contains $sid)
        firewall   = @(Get-NetFirewallProfile -All | ForEach-Object {
            [ordered]@{ Name = [string]$_.Name; LogBlocked = [string]$_.LogBlocked
                        LogFileName = [string]$_.LogFileName; LogMaxSizeKilobytes = [int]$_.LogMaxSizeKilobytes }
        })
    }
}

function Get-DefaultFirewallState {
    @('Domain', 'Private', 'Public') | ForEach-Object { [pscustomobject](@{ Name = $_ } + $WindowsDefaults) }
}

function Test-LegacyConfiguration {
    # Configurado por una version que no guardaba el estado: el firewall ya escribe en nuestra carpeta
    -not (Test-Path $StateFile) -and [bool](Get-NetFirewallProfile -All | Where-Object { $_.LogFileName -eq $FirewallLog })
}

function Test-Configured {
    # True si queda algo aplicado por network-llm (sirve a desinstalar.ps1 para ofrecer revertir).
    # La pertenencia al grupo sola no cuenta: el usuario podia estar en el antes de instalar.
    (Test-Path $StateFile) -or [bool](Get-NetFirewallProfile -All | Where-Object { $_.LogFileName -eq $FirewallLog })
}

if ($MostrarEstado) {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $state = Get-CurrentState $sid
    $state['configuradoPorNetworkLlm'] = Test-Configured
    $state['estadoPrevioGuardado'] = if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { $null }
    $state | ConvertTo-Json -Depth 5
    exit 0
}

if (-not $Elevado) {
    # Parte sin elevar: identifica al usuario real (el SID) antes de pedir UAC, por si el administrador
    # que confirma es otra cuenta.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($Revertir) {
        Write-Host "Se restaurara el estado anterior a network-llm (grupo de lectores de eventos y log del firewall)"
        Write-Host "y se borrara $DataDir."
    } else {
        Write-Host "Se pedira permiso de administrador (UAC) UNA vez para:"
        Write-Host "  - Anadir su usuario al grupo 'Lectores del registro de eventos'"
        Write-Host "  - Registrar en $FirewallDir los paquetes que bloquea el firewall"
        Write-Host "El estado actual se guarda antes para poder revertirlo (configurar-permisos.bat revertir)."
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
        Write-Ok $(if ($Revertir) { "Estado anterior restaurado." } else { "Configuracion aplicada." })
        Write-Aviso "Cierre sesion y vuelva a entrar para que el cambio de grupo surta efecto."
    } else { Write-Fallo "Termino con errores (codigo $($process.ExitCode)); revise la ventana de administrador." }
    exit $process.ExitCode
}

# Parte elevada ---------------------------------------------------------------------------------
$failed = $false
$readers = Get-LocalGroup -SID $ReadersSid

function Set-Membership([string]$sid, [bool]$member) {
    $current = @(Get-ReadersMemberSids) -contains $sid
    if ($current -eq $member) { Write-Ok "Grupo '$($readers.Name)': sin cambios"; return }
    if ($member) { Add-LocalGroupMember -Group $readers -Member $sid -ErrorAction Stop; Write-Ok "Usuario anadido a '$($readers.Name)'" }
    else { Remove-LocalGroupMember -Group $readers -Member $sid -ErrorAction Stop; Write-Ok "Usuario quitado de '$($readers.Name)'" }
}

if ($Revertir) {
    if (Test-Path $StateFile) {
        $previous = Get-Content $StateFile -Raw | ConvertFrom-Json
        $sid = $previous.userSid
        $wasMember = [bool]$previous.wasMember
        $profiles = @($previous.firewall)
        Write-Ok "Estado previo guardado el $($previous.capturedAt)"
    } else {
        # Configurado con una version anterior que no guardaba el estado: volver a los valores de Windows
        Write-Aviso "No hay estado previo guardado: se restauran los valores por defecto de Windows."
        $sid = $UsuarioSid
        $wasMember = $false
        $profiles = Get-DefaultFirewallState
    }
    try { Set-Membership $sid $wasMember } catch { Write-Fallo "Grupo de lectores de eventos: $($_.Exception.Message)"; $failed = $true }
    foreach ($fwProfile in $profiles) {
        try {
            Set-NetFirewallProfile -Name $fwProfile.Name -LogBlocked $fwProfile.LogBlocked -LogFileName $fwProfile.LogFileName `
                -LogMaxSizeKilobytes $fwProfile.LogMaxSizeKilobytes -ErrorAction Stop
            Write-Ok "Firewall $($fwProfile.Name): LogBlocked=$($fwProfile.LogBlocked), $($fwProfile.LogFileName)"
        } catch { Write-Fallo "Firewall $($fwProfile.Name): $($_.Exception.Message)"; $failed = $true }
    }
    if (-not $failed) {
        # El servicio del firewall puede tardar en soltar el log anterior
        foreach ($attempt in 1..5) {
            try { if (Test-Path $DataDir) { Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction Stop }; break }
            catch { Start-Sleep -Seconds 2 }
        }
        if (Test-Path $DataDir) { Write-Aviso "No se pudo borrar $DataDir (en uso); borrelo manualmente." }
        else { Write-Ok "Eliminado $DataDir" }
    } else {
        Write-Aviso "Se conserva $StateFile para poder reintentar."
    }
} else {
    try {
        New-Item -ItemType Directory -Force -Path $FirewallDir | Out-Null
        if (Test-Path $StateFile) {
            Write-Ok "Estado previo ya guardado; se conserva el original"
        } else {
            $state = Get-CurrentState $UsuarioSid
            if (Test-LegacyConfiguration) {
                # Lo actual ya es configuracion de network-llm: el estado previo real eran los valores de Windows
                $state.wasMember = $false
                $state.firewall = @(Get-DefaultFirewallState)
                $state['legacy'] = $true
                Write-Aviso "Configuracion anterior sin estado guardado: se registran los valores por defecto de Windows"
            }
            $state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding UTF8
            Write-Ok "Estado previo guardado en $StateFile"
        }
    } catch {
        Write-Fallo "No se pudo guardar el estado previo; no se cambia nada: $($_.Exception.Message)"
        Read-Host "`nPulse Enter para cerrar esta ventana de administrador"
        exit 1
    }
    try { Set-Membership $UsuarioSid $true } catch { Write-Fallo "Grupo de lectores de eventos: $($_.Exception.Message)"; $failed = $true }
    try {
        # El servicio del firewall (MpsSvc) debe poder escribir; el usuario, solo leer
        & icacls $FirewallDir /grant 'NT SERVICE\mpssvc:(OI)(CI)M' /grant "*${UsuarioSid}:(OI)(CI)RX" | Out-Null
        if ($LASTEXITCODE) { throw "icacls termino con codigo $LASTEXITCODE" }
        Set-NetFirewallProfile -All -LogBlocked True -LogMaxSizeKilobytes 16384 -LogFileName $FirewallLog -ErrorAction Stop
        Write-Ok "Firewall registrando paquetes bloqueados en $FirewallLog"
    } catch {
        Write-Fallo "Firewall: $($_.Exception.Message)"; $failed = $true
    }
}

Read-Host "`nPulse Enter para cerrar esta ventana de administrador"
if ($failed) { exit 1 } else { exit 0 }
