# Instalador de Atalaya: entorno de Python, dependencias, Ollama y modelos, base de datos,
# indice RAG, accesos directos e inicio automatico. Se puede repetir: cada paso detecta lo ya hecho.
param(
    [switch]$Si,                 # aceptar todas las preguntas con su valor por defecto
    [switch]$SinAccesos,         # no crear accesos directos (escritorio / menu Inicio)
    [switch]$SinInicioAutomatico,
    [switch]$SinCiclo,           # no programar el analisis periodico (se puede activar despues en Ajustes)
    [switch]$SinModelos,         # no descargar modelos de Ollama
    [switch]$SinPermisos,        # no ofrecer la configuracion de permisos (requiere administrador)
    [switch]$SinRed,             # no instalar paquetes, Ollama ni descargar modelos
    [string]$Modelo = 'qwen3.5:4b'
)
. "$PSScriptRoot\comun.ps1"

$ChatModel = $Modelo
$EmbeddingModel = 'embeddinggemma:latest'

function Test-PythonRuntime([string]$exe) {
    & $exe -c "import struct,sys; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize('P') == 8 else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-Pip([string]$exe) {
    $ErrorActionPreference = 'Continue'   # en PowerShell 5.1, redirigir stderr con 'Stop' lo convierte en error
    & $exe -m pip --version *> $null
    return $LASTEXITCODE -eq 0
}

function Find-BasePython {
    # Python >= 3.11 (la herramienta usa tomllib). Se ignora el alias de la Microsoft Store.
    $ErrorActionPreference = 'Continue'   # en PowerShell 5.1, 2>$null con 'Stop' convierte stderr en error
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in '3.13', '3.12', '3.11') {
            $exe = & py "-$version" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        }
    }
    foreach ($command in Get-Command python -All -ErrorAction SilentlyContinue) {
        if ($command.Source -match 'WindowsApps') { continue }
        & $command.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $command.Source }
    }
    return $null
}

function Get-OllamaModels {
    $ErrorActionPreference = 'Continue'
    $exe = Find-Ollama
    if (-not $exe -or -not (Test-Port $OllamaPort)) { return @() }
    (& $exe list 2>$null | Select-Object -Skip 1) | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ }
}

Write-Host "Instalador de Atalaya" -ForegroundColor White
Write-Host "Carpeta: $Root"

# 1. Python -------------------------------------------------------------------------------------
Write-Paso "Entorno de Python"
$python = Find-VenvPython
if ($python) {
    if (-not (Test-PythonRuntime $python)) {
        throw "El entorno existente no usa Python 3.11+ de 64 bits. Renombre o elimine .venv y repita la instalacion."
    }
    Write-Ok "Entorno existente: $python"
} else {
    $base = Find-BasePython
    if (-not $base) {
        Write-Aviso "No se encontro Python 3.11 o superior."
        if (-not $SinRed -and (Get-Command winget -ErrorAction SilentlyContinue) -and (Confirm-Paso "Instalar Python 3.12 con winget?" $true $Si)) {
            winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
            $base = Find-BasePython
        }
        if (-not $base) { throw "Instale Python 3.11+ desde https://www.python.org y vuelva a ejecutar el instalador." }
    }
    Write-Ok "Python base: $base"
    & $base -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE) { throw "No se pudo crear el entorno virtual" }
    $python = Find-VenvPython
    if (-not $python -or -not (Test-PythonRuntime $python)) { throw "El entorno creado no es Python 3.11+ x64" }
    Write-Ok "Entorno creado: $python"
}

# 2. Dependencias -------------------------------------------------------------------------------
Write-Paso "Dependencias reproducibles (requirements.lock.txt)"
if (Test-BundledRuntime) {
    Write-Ok "Incluidas en el paquete (runtime\); no se descarga nada"
} else {
    if ($SinRed) { throw "SinRed requiere un runtime ya preparado; no se pueden descargar dependencias para .venv." }
    # Un .venv copiado de otra carpeta o a medio borrar conserva python.exe pero puede no traer pip:
    # se repone con ensurepip, que viene con Python y no usa la red
    if (-not (Test-Pip $python)) {
        Write-Aviso "El entorno no tiene pip (copiado de otra carpeta o incompleto); se repone con ensurepip"
        & $python -m ensurepip --upgrade --default-pip
        if ($LASTEXITCODE -or -not (Test-Pip $python)) {
            throw "No se pudo reponer pip. Elimine la carpeta .venv y vuelva a ejecutar el instalador."
        }
        Write-Ok "pip repuesto"
    }
    & $python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.lock.txt')
    if ($LASTEXITCODE) { throw "Fallo la instalacion de dependencias" }
    Write-Ok "Dependencias instaladas"
}

# 3. Ollama y modelos ---------------------------------------------------------------------------
Write-Paso "Ollama (LLM local)"
if (-not (Find-Ollama)) {
    Write-Aviso "Ollama no esta instalado. Sin el, las reglas funcionan pero no hay explicaciones ni chat."
    if (-not $SinRed -and (Get-Command winget -ErrorAction SilentlyContinue) -and (Confirm-Paso "Instalar Ollama con winget?" $true $Si)) {
        winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
    }
}
if (Find-Ollama) {
    Write-Ok "Ollama: $(Find-Ollama)"
    if ((Start-OllamaIfNeeded) -and -not $SinModelos -and -not $SinRed) {
        $installed = @(Get-OllamaModels)
        foreach ($model in @($ChatModel, $EmbeddingModel)) {
            $present = $installed | Where-Object { $_ -eq $model -or "$($_):latest" -eq $model -or $_ -eq "$($model):latest" }
            if ($present) { Write-Ok "Modelo disponible: $model"; continue }
            $size = if ($model -eq $ChatModel) { '~3.4 GB' } else { '~0.6 GB' }
            if (Confirm-Paso "Descargar $model ($size)?" $true $Si) {
                & (Find-Ollama) pull $model
                if ($LASTEXITCODE) { Write-Aviso "No se pudo descargar $model" } else { Write-Ok "Descargado $model" }
            }
        }
    }
}

# 4. Base de datos e indice RAG -----------------------------------------------------------------
Write-Paso "Base de datos local"
if ((Invoke-Tool @('status')) -ne 0) { throw "No se pudo inicializar la base de datos" }
Write-Paso "Indice de documentacion para el chat (RAG)"
if ((Invoke-Tool @('rag', 'index')) -ne 0) { Write-Aviso "No se pudo indexar la documentacion; el chat seguira sin ella." }

# 5. Accesos directos ---------------------------------------------------------------------------
if (-not $SinAccesos) {
    Write-Paso "Accesos directos"
    if (Confirm-Paso "Crear acceso directo en el escritorio y carpeta en el menu Inicio?" $true $Si) {
        New-Shortcut (Get-DesktopShortcut) (Join-Path $StartDir 'iniciar.bat') 'Abrir el panel de Atalaya'
        $menu = Get-MenuFolder
        New-Item -ItemType Directory -Force -Path $menu | Out-Null
        New-Shortcut (Join-Path $menu 'Abrir panel.lnk') (Join-Path $StartDir 'iniciar.bat') 'Abrir el panel de Atalaya'
        New-Shortcut (Join-Path $menu 'Recolectar y analizar.lnk') (Join-Path $StartDir 'recolectar.bat') 'Recolectar evidencia, analizar e informar'
        New-Shortcut (Join-Path $menu 'Detener.lnk') (Join-Path $StartDir 'detener.bat') 'Detener panel y monitor'
        New-Shortcut (Join-Path $menu 'Diagnostico.lnk') (Join-Path $StartDir 'diagnostico.bat') 'Comprobar la instalacion'
        New-Shortcut (Join-Path $menu 'Configurar permisos.lnk') (Join-Path $StartDir 'configurar-permisos.bat') 'Configuracion unica como administrador'
        Write-Ok "Escritorio: Atalaya  |  Menu Inicio: carpeta Atalaya"
    }
}

# 6. Inicio automatico --------------------------------------------------------------------------
if (-not $SinInicioAutomatico) {
    Write-Paso "Inicio automatico"
    if (Confirm-Paso "Iniciar Atalaya en segundo plano (icono junto al reloj, con el monitor) al entrar en Windows?" $false $Si) {
        New-TrayStartupShortcut
        Write-Ok "Atalaya arrancara en la bandeja al iniciar sesion (desactivar: start\inicio-automatico.bat)"
    }
}

# 7. Analisis periodico (activado por defecto) --------------------------------------------------
if (-not $SinCiclo) {
    Write-Paso "Analisis periodico"
    if (Confirm-Paso "Analizar el equipo automaticamente cada 5 minutos (recomendado)?" $true $Si) {
        try {
            & (Join-Path $PSScriptRoot 'automatizacion.ps1') -Accion activar -Minutos 5
        } catch {
            Write-Aviso "No se pudo programar la tarea: $($_.Exception.Message). Activela despues en Ajustes."
        }
    } else {
        Write-Host "  Sin analisis periodico: Atalaya solo recolecta al pulsar Recolectar. Activelo en Ajustes."
    }
}

# 8. Permisos -----------------------------------------------------------------------------------
if (-not $SinPermisos) {
    Write-Paso "Permisos (opcional, una sola vez, pide administrador)"
    Write-Host "  Permite leer accesos/RDP (registro Security) y el log del firewall sin ejecutar como administrador."
    if (Confirm-Paso "Configurar permisos ahora?" $false $Si) {
        & (Join-Path $PSScriptRoot 'configurar-permisos.ps1')
    } else {
        Write-Host "  Puede hacerlo mas tarde con start\configurar-permisos.bat"
    }
}

Write-Paso "Instalacion completada"
Write-Host "  Abrir el panel:        start\iniciar.bat (o el acceso directo del escritorio)"
Write-Host "  Recolectar y analizar: start\recolectar.bat"
Write-Host "  Comprobar todo:        start\diagnostico.bat"
