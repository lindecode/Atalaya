# Funciones compartidas por los lanzadores de start\. Se carga con: . "$PSScriptRoot\comun.ps1"
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # start\lib -> start -> Atalaya
$StartDir = Join-Path $Root 'start'
$GuiPort = 8501
$OllamaPort = 11434
$FirewallLog = Join-Path $env:ProgramData 'Atalaya\firewall\pfirewall.log'

# La herramienta solo acepta Ollama en loopback; si el usuario tiene OLLAMA_HOST=0.0.0.0 (para exponerlo
# en la red) la herramienta se negaría a arrancar y un "ollama serve" lanzado desde aquí quedaría expuesto.
$env:OLLAMA_HOST = "http://127.0.0.1:$OllamaPort"
# La ruta del log del firewall (actual o anterior al cambio de nombre) la resuelve settings.py
$env:PYTHONUTF8 = '1'

function Write-Paso([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Write-Ok([string]$texto) { Write-Host "  [ok] $texto" -ForegroundColor Green }
function Write-Aviso([string]$texto) { Write-Host "  [!]  $texto" -ForegroundColor Yellow }
function Write-Fallo([string]$texto) { Write-Host "  [x]  $texto" -ForegroundColor Red }

function Find-VenvPython {
    # runtime\: Python incluido por el instalador o el ZIP portable. .venv\: instalacion desde el codigo fuente.
    foreach ($candidate in @((Join-Path $Root 'runtime\python.exe'), (Join-Path $Root '.venv\Scripts\python.exe'))) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Test-BundledRuntime { Test-Path (Join-Path $Root 'runtime\python.exe') }

function Get-PythonW {
    # pythonw.exe: el mismo interprete sin ventana de consola (para la bandeja)
    $python = Get-Python
    $windowless = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (Test-Path $windowless) { return $windowless }
    return $python
}

function Get-DataHome {
    # Igual que settings.data_home(): ATALAYA_HOME, modo portable (archivo "portable"), o %LOCALAPPDATA%\Atalaya
    if ($env:ATALAYA_HOME) { return $env:ATALAYA_HOME }
    if (Test-Path (Join-Path $Root 'portable')) { return (Join-Path $Root 'userdata') }
    return (Join-Path $env:LOCALAPPDATA 'Atalaya')
}

function Get-Python {
    $python = Find-VenvPython
    if (-not $python) { throw "No hay entorno de Python. Ejecute primero start\instalar.bat (ver README\README.instalacion.md)" }
    return $python
}

function Find-Ollama {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $default = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $default) { return $default }
    return $null
}

function Test-Port([int]$port, [int]$timeoutMs = 400) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        return ($async.AsyncWaitHandle.WaitOne($timeoutMs) -and $client.Connected)
    } catch { return $false } finally { $client.Close() }
}

function Wait-Port([int]$port, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-Ollama([int]$timeoutSec = 2) {
    try {
        $response = Invoke-RestMethod -UseBasicParsing -Uri "http://127.0.0.1:$OllamaPort/api/version" `
            -TimeoutSec $timeoutSec -ErrorAction Stop
        return ($response.version -is [string] -and $response.version.Length -gt 0)
    } catch { return $false }
}

function Wait-Ollama([int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Ollama) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-AtalayaGuiPort {
    $state = Join-Path (Get-DataHome) 'gui-instance.json'
    if (-not (Test-Path $state)) { return $null }
    try {
        $instance = Get-Content -LiteralPath $state -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($instance.app -ne 'Atalaya' -or $instance.version -ne 1 -or -not $instance.token) { return $null }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($instance.pid)" -ErrorAction Stop
        if (-not $process -or $process.CommandLine -notmatch 'main\.py[" ]+gui' `
            -or $process.CommandLine -notlike "*$($instance.token)*") { return $null }
        if (-not (Test-Port ([int]$instance.port))) { return $null }
        return [int]$instance.port
    } catch { return $null }
}

function Start-OllamaIfNeeded {
    if (Test-Ollama) { return $true }
    $exe = Find-Ollama
    if (-not $exe) {
        Write-Aviso "Ollama no esta instalado: las alertas funcionan, pero sin explicaciones del LLM ni chat."
        return $false
    }
    # Preferir la app de bandeja (deja el icono para gestionarlo); si no, el servidor sin ventana
    $app = Join-Path (Split-Path -Parent $exe) 'ollama app.exe'
    if (Test-Path $app) { Start-Process -FilePath $app }
    else { Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden }
    if (Wait-Ollama 30) { Write-Ok "Ollama iniciado"; return $true }
    Write-Aviso "El puerto $OllamaPort no responde como Ollama; se continua sin LLM."
    return $false
}

function Invoke-Tool([string[]]$arguments) {
    # Ejecuta main.py con el Python del entorno y devuelve su codigo de salida
    $python = Get-Python
    Push-Location $Root
    try { & $python 'main.py' @arguments | Out-Host; return $LASTEXITCODE } finally { Pop-Location }
}

function Get-GuiProcesses {
    # Procesos de esta herramienta: la bandeja (main.py tray), la GUI (main.py gui y el streamlit hijo)
    # y el monitor (main.py watch)
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'interfaces[\\/]gui[\\/]app\.py' -or $_.CommandLine -match 'main\.py"?\s+(gui|watch|tray)\b' }
}

function New-Shortcut([string]$path, [string]$target, [string]$description, [int]$windowStyle = 1,
                      [string]$arguments = '', [string]$workingDirectory = $StartDir) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $workingDirectory
    $shortcut.Description = $description
    $shortcut.WindowStyle = $windowStyle            # 1 normal, 7 minimizada
    $icon = Join-Path $Root 'assets\icon.ico'
    $shortcut.IconLocation = if (Test-Path $icon) { "$icon,0" } else { "$env:SystemRoot\System32\shell32.dll,47" }
    $shortcut.Save()
}

function Get-StartupShortcut { Join-Path ([Environment]::GetFolderPath('Startup')) 'Atalaya.lnk' }
function Get-LegacyStartupShortcut { Join-Path ([Environment]::GetFolderPath('Startup')) 'Atalaya vigilar.lnk' }

function New-TrayStartupShortcut {
    # Al iniciar sesion: Atalaya en la bandeja, con el monitor activo y sin abrir el navegador
    $legacy = Get-LegacyStartupShortcut
    if (Test-Path $legacy) { Remove-Item -LiteralPath $legacy }
    New-Shortcut (Get-StartupShortcut) (Get-PythonW) 'Atalaya en segundo plano' 1 'main.py tray --no-browser --monitor' $Root
}
function Get-MenuFolder { Join-Path ([Environment]::GetFolderPath('Programs')) 'Atalaya' }
function Get-DesktopShortcut { Join-Path ([Environment]::GetFolderPath('Desktop')) 'Atalaya.lnk' }

function Confirm-Paso([string]$pregunta, [bool]$porDefecto = $true, [bool]$siempreSi = $false) {
    if ($siempreSi) { return $porDefecto }
    $opciones = if ($porDefecto) { '[S/n]' } else { '[s/N]' }
    $respuesta = Read-Host "  $pregunta $opciones"
    if ([string]::IsNullOrWhiteSpace($respuesta)) { return $porDefecto }
    return $respuesta.Trim().ToLower().StartsWith('s')
}
