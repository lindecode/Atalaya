# Construye la distribucion de Atalaya para Windows x64:
#   dist\Atalaya-<version>-portable.zip   carpeta lista para usar (Python incluido, datos junto al programa)
#   dist\Atalaya-Setup-<version>.exe      instalador por usuario (requiere Inno Setup 6; ver packaging\README.md)
#
# El paquete incluye el Python embebido oficial (verificado por SHA-256) y las dependencias de
# requirements.lock.txt ya instaladas: el equipo de destino no necesita Python ni Internet para instalar.
param(
    [switch]$SinInstalador,   # solo carpeta + ZIP portable (no necesita Inno Setup)
    [switch]$SinZip,
    [switch]$SinPrueba,       # omite la prueba de humo del paquete
    [string]$LlamaCppZip,     # ZIP oficial precompilado de llama.cpp (opcional)
    [string]$LlamaCppSha256,
    [string]$LlamaCppLicense,
    [string]$ModeloGguf,      # modelo con licencia redistribuible (opcional)
    [string]$ModeloSha256,
    [string]$ModeloLicense,
    [string]$EmbeddingGguf,   # modelo dedicado de embeddings (opcional)
    [string]$EmbeddingSha256,
    [string]$EmbeddingLicense
)
$ErrorActionPreference = 'Stop'
$Packaging = $PSScriptRoot
$Root = Split-Path -Parent $Packaging
$Build = Join-Path $Root 'build'
$Stage = Join-Path $Build 'Atalaya'
$Dist = Join-Path $Root 'dist'
$Cache = Join-Path $Packaging 'cache'
$versions = Get-Content (Join-Path $Packaging 'versions.json') -Raw | ConvertFrom-Json
$componentFiles = [ordered]@{}

function Write-Paso([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

# Version unica: shared\about.py
$about = Get-Content (Join-Path $Root 'shared\about.py') -Raw
if ($about -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { throw "No se encontro APP_VERSION en shared\about.py" }
$Version = $Matches[1]
Write-Host "Atalaya $Version · Python $($versions.python.version)" -ForegroundColor White

# Python del equipo de compilacion: solo para resolver ruedas (pip); debe coincidir en version menor
$pyMinor = ($versions.python.version -split '\.')[0..1] -join '.'
$builderPython = (& py "-$pyMinor" -c "import sys; print(sys.executable)" 2>$null)
if (-not $builderPython) { throw "Se necesita Python $pyMinor en el equipo de compilacion (winget install Python.Python.$pyMinor)" }
$builderPython = $builderPython.Trim()

Write-Paso "Preparando build\Atalaya"
if (Test-Path $Build) { Remove-Item -LiteralPath $Build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage, $Dist, $Cache | Out-Null

# Solo archivos versionados: ni caches, ni datos, ni secretos locales. Fuera tests y el propio empaquetado.
Push-Location $Root
try {
    $files = git ls-files | Where-Object { $_ -notmatch '^(tests|packaging)/' -and $_ -notmatch '^\.git' }
    if ($LASTEXITCODE -or -not $files) { throw "git ls-files fallo: ejecute la compilacion desde el repositorio" }
    $dirty = git status --porcelain -- $files
    if ($dirty) { Write-Host "  [!] Hay cambios sin commit; se empaqueta el estado actual de los archivos" -ForegroundColor Yellow }
} finally { Pop-Location }
foreach ($file in $files) {
    $target = Join-Path $Stage $file
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root $file) -Destination $target
}
Write-Host "  $($files.Count) archivos de la aplicacion"

Write-Paso "Python embebido $($versions.python.version)"
$zip = Join-Path $Cache (Split-Path -Leaf $versions.python.url)
if (-not (Test-Path $zip)) {
    Invoke-WebRequest -UseBasicParsing $versions.python.url -OutFile $zip
}
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $versions.python.sha256) {
    Remove-Item $zip
    throw "SHA-256 del Python embebido no coincide (esperado $($versions.python.sha256), obtenido $hash)"
}
$Runtime = Join-Path $Stage 'runtime'
Expand-Archive -LiteralPath $zip -DestinationPath $Runtime
# ._pth: rutas de importacion del Python embebido (relativas a runtime\). Se anaden las dependencias,
# la carpeta de la aplicacion (..) y "import site" para que pywin32 registre sus rutas y DLL.
$pth = Get-ChildItem $Runtime -Filter 'python*._pth' | Select-Object -First 1
$zipName = (Get-ChildItem $Runtime -Filter 'python*.zip' | Select-Object -First 1).Name
Set-Content -Path $pth.FullName -Encoding ascii -Value @($zipName, '.', 'Lib\site-packages', '..', 'import site')
Write-Host "  SHA-256 verificado; $($pth.Name) configurado"

if ($LlamaCppZip -or $ModeloGguf) {
    if (-not ($LlamaCppZip -and $LlamaCppSha256 -and $LlamaCppLicense -and $ModeloGguf -and $ModeloSha256 -and $ModeloLicense)) {
        throw 'Para integrar llama.cpp indique ZIP, modelo, hashes y las dos licencias'
    }
    Write-Paso 'Runtime llama.cpp integrado'
    foreach ($item in @(@($LlamaCppZip, $LlamaCppSha256, 'llama.cpp'), @($ModeloGguf, $ModeloSha256, 'modelo GGUF'))) {
        if (-not (Test-Path -LiteralPath $item[0] -PathType Leaf)) { throw "No existe $($item[2]): $($item[0])" }
        $actual = (Get-FileHash -LiteralPath $item[0] -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $item[1].ToLower()) { throw "SHA-256 incorrecto para $($item[2])" }
    }
    foreach ($license in @($LlamaCppLicense, $ModeloLicense)) {
        if (-not (Test-Path -LiteralPath $license -PathType Leaf)) { throw "No existe la licencia: $license" }
    }
    $llamaTemp = Join-Path $Build 'llama-cpp-extract'
    Expand-Archive -LiteralPath $LlamaCppZip -DestinationPath $llamaTemp
    $server = Get-ChildItem $llamaTemp -Recurse -File -Filter 'llama-server.exe' | Select-Object -First 1
    if (-not $server) { throw 'El ZIP verificado no contiene llama-server.exe' }
    $llamaTarget = Join-Path $Runtime 'llama.cpp'
    New-Item -ItemType Directory -Force -Path $llamaTarget | Out-Null
    Copy-Item -Path (Join-Path $server.DirectoryName '*') -Destination $llamaTarget -Recurse -Force
    $serverTarget = Join-Path $llamaTarget 'llama-server.exe'
    $modelTarget = Join-Path $Stage 'models'
    New-Item -ItemType Directory -Force -Path $modelTarget | Out-Null
    Copy-Item -LiteralPath $ModeloGguf -Destination (Join-Path $modelTarget 'atalaya.gguf')
    $componentFiles['runtime/llama.cpp/llama-server.exe'] = (Get-FileHash -LiteralPath $serverTarget -Algorithm SHA256).Hash.ToLower()
    $componentFiles['models/atalaya.gguf'] = (Get-FileHash -LiteralPath (Join-Path $modelTarget 'atalaya.gguf') -Algorithm SHA256).Hash.ToLower()
    $licenseTarget = Join-Path $Stage 'THIRD_PARTY_LICENSES'
    New-Item -ItemType Directory -Force -Path $licenseTarget | Out-Null
    Copy-Item -LiteralPath $LlamaCppLicense -Destination (Join-Path $licenseTarget 'llama.cpp.txt')
    Copy-Item -LiteralPath $ModeloLicense -Destination (Join-Path $licenseTarget 'model.txt')
    if ($EmbeddingGguf -or $EmbeddingSha256 -or $EmbeddingLicense) {
        if (-not ($EmbeddingGguf -and $EmbeddingSha256 -and $EmbeddingLicense)) {
            throw 'El modelo de embeddings requiere archivo, SHA-256 y licencia'
        }
        if (-not (Test-Path -LiteralPath $EmbeddingGguf -PathType Leaf)) { throw "No existe: $EmbeddingGguf" }
        if (-not (Test-Path -LiteralPath $EmbeddingLicense -PathType Leaf)) { throw "No existe: $EmbeddingLicense" }
        $embeddingHash = (Get-FileHash -LiteralPath $EmbeddingGguf -Algorithm SHA256).Hash.ToLower()
        if ($embeddingHash -ne $EmbeddingSha256.ToLower()) { throw 'SHA-256 incorrecto para el modelo de embeddings' }
        Copy-Item -LiteralPath $EmbeddingGguf -Destination (Join-Path $modelTarget 'atalaya-embedding.gguf')
        $componentFiles['models/atalaya-embedding.gguf'] = (Get-FileHash -LiteralPath (Join-Path $modelTarget 'atalaya-embedding.gguf') -Algorithm SHA256).Hash.ToLower()
        Copy-Item -LiteralPath $EmbeddingLicense -Destination (Join-Path $licenseTarget 'embedding-model.txt')
    }
    Write-Host '  llama-server.exe y modelo verificados e incluidos'
}

if ($componentFiles.Count) {
    # El runtime vuelve a calcular estos hashes antes de ejecutar componentes incluidos.
    @{ schema = 1; files = $componentFiles } | ConvertTo-Json -Depth 3 |
        Set-Content -Path (Join-Path $Stage 'COMPONENTS.sha256.json') -Encoding utf8
    Write-Host '  Manifiesto de integridad de componentes generado'
}

Write-Paso "Dependencias (requirements.lock.txt)"
$sitePackages = Join-Path $Runtime 'Lib\site-packages'
# Almacen de ruedas: pip descarga las publicadas y construye las que solo existen como codigo fuente
# (p. ej. proxy_tools, de pywebview). El equipo de compilacion es Windows x64 con el mismo Python, asi que
# las ruedas construidas valen para el runtime. Se guardan en cache para las siguientes compilaciones.
$wheels = Join-Path $Cache "wheels-cp$($pyMinor -replace '\.', '')"
& $builderPython -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE) { throw "El Python de compilacion debe ser de 64 bits" }
& $builderPython -m pip wheel --disable-pip-version-check -q --no-deps -w $wheels -r (Join-Path $Root 'requirements.lock.txt')
if ($LASTEXITCODE) { throw "pip no pudo preparar las ruedas de requirements.lock.txt" }
& $builderPython -m pip install --disable-pip-version-check -q --no-deps --no-index --find-links $wheels `
    --only-binary=:all: --platform win_amd64 --python-version $pyMinor --implementation cp `
    --target $sitePackages -r (Join-Path $Root 'requirements.lock.txt')
if ($LASTEXITCODE) { throw "pip no pudo instalar las dependencias en el runtime" }
Get-ChildItem $sitePackages -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $sitePackages -Directory -Filter 'bin' | Remove-Item -Recurse -Force   # scripts .exe de pip, no se usan
# Fuera lo que no se ejecuta: suites de tests de las librerias y plantillas de desarrollo de Streamlit.
# Ademas de pesar, son las rutas mas profundas (limite de 260 caracteres de Windows).
$pruned = @(Get-ChildItem $sitePackages -Directory | ForEach-Object { Get-ChildItem $_.FullName -Directory -Filter 'tests' })
$pruned += @(Get-Item (Join-Path $sitePackages 'streamlit\.agents') -Force -ErrorAction SilentlyContinue)
$pruned | Where-Object { $_ } | Remove-Item -Recurse -Force
Write-Host "  $((Get-ChildItem $sitePackages -Directory).Count) paquetes instalados ($($pruned.Count) carpetas de tests/plantillas omitidas)"

if (-not $SinPrueba) {
    Write-Paso "Prueba de humo del paquete"
    $python = Join-Path $Runtime 'python.exe'
    $env:ATALAYA_HOME = Join-Path $Build 'smoke-home'
    $env:PYTHONUTF8 = '1'
    Push-Location $Stage
    try {
        & $python -c "import psutil, win32evtlog, watchdog, ollama, pydantic, streamlit, pandas, plotly, pystray, webview, clr; print('  importaciones ok')"
        if ($LASTEXITCODE) { throw "Faltan modulos en el paquete" }
        & $python main.py --version
        if ($LASTEXITCODE) { throw "main.py --version fallo" }
        & $python main.py status | Out-Null
        if ($LASTEXITCODE) { throw "main.py status fallo (base de datos)" }
        & $python main.py doctor | Out-Null   # ok aunque haya avisos; solo falla con problemas bloqueantes
        if ($LASTEXITCODE) { throw "main.py doctor detecto problemas bloqueantes en el paquete" }
        Write-Host "  version, base de datos y doctor ok"
    } finally {
        Pop-Location
        Remove-Item Env:ATALAYA_HOME
        Get-ChildItem $Stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
        if (Test-Path (Join-Path $Build 'smoke-home')) { Remove-Item (Join-Path $Build 'smoke-home') -Recurse -Force }
    }
}

$sizeMb = [math]::Round(((Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB)
Write-Host "  Carpeta lista: $Stage ($sizeMb MB)"
# Instalado en %LOCALAPPDATA%\Programs\Atalaya (~46 caracteres + el nombre de usuario): Windows corta en 260
$longest = (Get-ChildItem $Stage -Recurse -File | ForEach-Object { $_.FullName.Length - $Stage.Length - 1 } | Measure-Object -Maximum).Maximum
if ($longest -gt 170) { throw "Ruta relativa de $longest caracteres: con nombres de usuario largos superaria 260 en la instalacion" }
Write-Host "  Ruta relativa mas larga: $longest caracteres (limite propio 170)"

if (-not $SinZip) {
    Write-Paso "ZIP portable"
    $portable = Join-Path $Build 'portable'
    Copy-Item -LiteralPath $Stage -Destination (Join-Path $portable 'Atalaya') -Recurse
    # Con el archivo "portable" los datos quedan en Atalaya\userdata (ver settings.data_home)
    Set-Content -Path (Join-Path $portable 'Atalaya\portable') -Value 'Datos en userdata\ junto al programa.' -Encoding ascii
    $zipOut = Join-Path $Dist "Atalaya-$Version-portable.zip"
    if (Test-Path $zipOut) { Remove-Item $zipOut }
    Compress-Archive -Path (Join-Path $portable 'Atalaya') -DestinationPath $zipOut -CompressionLevel Optimal
    Remove-Item -LiteralPath $portable -Recurse -Force
    Write-Host "  $zipOut ($([math]::Round((Get-Item $zipOut).Length / 1MB)) MB)"
}

if (-not $SinInstalador) {
    Write-Paso "Instalador (Inno Setup)"
    $iscc = @((Get-Command iscc -ErrorAction SilentlyContinue).Source,
              "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) {
        Write-Host "  [!] Inno Setup 6 no esta instalado: no se genera el .exe." -ForegroundColor Yellow
        Write-Host "      Instalelo con: $($versions.innosetup.install)  y vuelva a ejecutar build.bat"
        exit 2
    }
    & $iscc /Q "/DAppVersion=$Version" "/DSourceDir=$Stage" "/DOutputDir=$Dist" (Join-Path $Packaging 'atalaya.iss')
    if ($LASTEXITCODE) { throw "Inno Setup fallo (codigo $LASTEXITCODE)" }
    $setup = Join-Path $Dist "Atalaya-Setup-$Version.exe"
    Write-Host "  $setup ($([math]::Round((Get-Item $setup).Length / 1MB)) MB)"
    Write-Host "  Sin firma digital: Windows SmartScreen mostrara 'editor desconocido' (ver packaging\README.md)"
}

$manifest = Get-ChildItem $Dist -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
$manifest | Set-Content -Path (Join-Path $Dist 'SHA256SUMS.txt') -Encoding ascii
Write-Host "`nListo. Salida en $Dist"
Write-Host "Hashes: $(Join-Path $Dist 'SHA256SUMS.txt')" -ForegroundColor Green
