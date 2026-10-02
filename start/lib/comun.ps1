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

function Start-OllamaIfNeeded {
    if (Test-Port $OllamaPort) { return $true }
    $exe = Find-Ollama
    if (-not $exe) {
        Write-Aviso "Ollama no esta instalado: las alertas funcionan, pero sin explicaciones del LLM ni chat."
        return $false
    }
    # Preferir la app de bandeja (deja el icono para gestionarlo); si no, el servidor sin ventana
    $app = Join-Path (Split-Path -Parent $exe) 'ollama app.exe'
    if (Test-Path $app) { Start-Process -FilePath $app }
    else { Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden }
    if (Wait-Port $OllamaPort 30) { Write-Ok "Ollama iniciado"; return $true }
    Write-Aviso "Ollama no respondio en 30 s; se continua sin LLM."
    return $false
}

function Invoke-Tool([string[]]$arguments) {
    # Ejecuta main.py con el Python del entorno y devuelve su codigo de salida
    $python = Get-Python
    Push-Location $Root
    try { & $python 'main.py' @arguments | Out-Host; return $LASTEXITCODE } finally { Pop-Location }
}

function Get-GuiProcesses {
    # Procesos de esta herramienta: la GUI (main.py gui y el streamlit hijo) y el monitor (main.py watch)
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'interfaces[\\/]gui[\\/]app\.py' -or $_.CommandLine -match 'main\.py"?\s+(gui|watch)\b' }
}

function New-Shortcut([string]$path, [string]$target, [string]$description, [int]$windowStyle = 1) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $StartDir
    $shortcut.Description = $description
    $shortcut.WindowStyle = $windowStyle            # 1 normal, 7 minimizada
    $icon = Join-Path $Root 'assets\icon.ico'
    $shortcut.IconLocation = if (Test-Path $icon) { "$icon,0" } else { "$env:SystemRoot\System32\shell32.dll,47" }
    $shortcut.Save()
}

function Get-StartupShortcut { Join-Path ([Environment]::GetFolderPath('Startup')) 'Atalaya vigilar.lnk' }
function Get-MenuFolder { Join-Path ([Environment]::GetFolderPath('Programs')) 'Atalaya' }
function Get-DesktopShortcut { Join-Path ([Environment]::GetFolderPath('Desktop')) 'Atalaya.lnk' }

function Confirm-Paso([string]$pregunta, [bool]$porDefecto = $true, [bool]$siempreSi = $false) {
    if ($siempreSi) { return $porDefecto }
    $opciones = if ($porDefecto) { '[S/n]' } else { '[s/N]' }
    $respuesta = Read-Host "  $pregunta $opciones"
    if ([string]::IsNullOrWhiteSpace($respuesta)) { return $porDefecto }
    return $respuesta.Trim().ToLower().StartsWith('s')
}
