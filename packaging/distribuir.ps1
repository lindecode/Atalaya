# Genera los instalables de Atalaya listos para distribuir, en dist\:
#   Atalaya-Setup-<version>.exe   instalador con asistente (Inno Setup), para usuarios
#   Atalaya-<version>.msi         paquete MSI (WiX), para despliegues con Intune/GPO/msiexec
#   SHA256SUMS.txt                hashes de todo lo generado
# Reutiliza packaging\build.ps1 (Python embebido verificado + dependencias + prueba de humo) y despues
# empaqueta la misma carpeta build\Atalaya como MSI. Ver packaging\README.md.
param(
    [switch]$ConZip,        # genera tambien el ZIP portable
    [switch]$SinMsi,
    [switch]$SinExe,
    [switch]$SinPrueba,     # omite la prueba de humo (iteraciones rapidas)
    [switch]$SinPreguntar   # instala WiX sin confirmar si falta (para CI)
)
$ErrorActionPreference = 'Stop'
$Packaging = $PSScriptRoot
$Root = Split-Path -Parent $Packaging
$Stage = Join-Path $Root 'build\Atalaya'
$Dist = Join-Path $Root 'dist'
# WiX 5: licencia MS-RL. La 6 anade una cuota de mantenimiento para uso comercial (OSMF)
$WixVersion = '5.0.2'

function Write-Paso([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

function Get-Wix {
    $wix = (Get-Command wix -ErrorAction SilentlyContinue).Source
    if (-not $wix) {
        $candidate = Join-Path $env:USERPROFILE '.dotnet\tools\wix.exe'
        if (Test-Path $candidate) { $wix = $candidate }
    }
    return $wix
}

function Install-Wix {
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
        throw "Para el MSI hace falta el SDK de .NET 6 o superior (winget install Microsoft.DotNet.SDK.8) y luego WiX"
    }
    if (-not $SinPreguntar) {
        $answer = Read-Host "WiX Toolset $WixVersion no esta instalado. Instalarlo ahora con dotnet tool (solo para su usuario)? [S/n]"
        if ($answer -and $answer -notmatch '^[sSyY]') { throw "Sin WiX no se puede generar el MSI (use -SinMsi para omitirlo)" }
    }
    & dotnet tool install --global wix --version $WixVersion
    if ($LASTEXITCODE) { throw "No se pudo instalar WiX (dotnet tool install --global wix --version $WixVersion)" }
}

# Version unica: shared\about.py
$about = Get-Content (Join-Path $Root 'shared\about.py') -Raw
if ($about -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { throw "No se encontro APP_VERSION en shared\about.py" }
$Version = $Matches[1]
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "El MSI necesita una version numerica x.y.z (APP_VERSION=$Version)" }

# Antes de compilar nada: si falta WiX, mejor saberlo ahora que tras varios minutos de build
if (-not $SinMsi) {
    $wix = Get-Wix
    if (-not $wix) { Install-Wix; $wix = Get-Wix }
    if (-not $wix) { throw "WiX instalado pero no encontrado; abra una consola nueva o agregue %USERPROFILE%\.dotnet\tools al PATH" }
    $extensions = & $wix extension list --global 2>$null | Out-String
    if ($extensions -notmatch 'WixToolset\.Util\.wixext') {
        & $wix extension add --global "WixToolset.Util.wixext/$WixVersion"
        if ($LASTEXITCODE) { throw "No se pudo agregar la extension WixToolset.Util.wixext" }
    }
}

Write-Paso "Carpeta del programa y .exe (packaging\build.ps1)"
$buildArgs = @{}
if (-not $ConZip) { $buildArgs['SinZip'] = $true }
if ($SinExe) { $buildArgs['SinInstalador'] = $true }
if ($SinPrueba) { $buildArgs['SinPrueba'] = $true }
& (Join-Path $Packaging 'build.ps1') @buildArgs
if ($LASTEXITCODE -eq 2) { throw "Falta Inno Setup para el .exe (winget install --id JRSoftware.InnoSetup -e) o use -SinExe" }
if ($LASTEXITCODE) { throw "build.ps1 termino con codigo $LASTEXITCODE" }

if (-not $SinMsi) {
    Write-Paso "Instalador MSI (WiX $WixVersion)"
    $msi = Join-Path $Dist "Atalaya-$Version.msi"
    if (Test-Path $msi) { Remove-Item -LiteralPath $msi }
    # Python deja __pycache__ al probar el paquete; no debe viajar en el MSI
    Get-ChildItem $Stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    # El antivirus puede retener un momento las miles de DLL/.pyd recien creadas: WiX ve "ruta no encontrada"
    # al comprimir el cabinet. Se reintenta en vez de fallar la distribucion entera.
    foreach ($attempt in 1..3) {
        & $wix build (Join-Path $Packaging 'atalaya.wxs') -arch x64 -ext WixToolset.Util.wixext `
            -d "AppVersion=$Version" -d "SourceDir=$Stage" -culture es-ES -o $msi
        if (-not $LASTEXITCODE) { break }
        if ($attempt -eq 3) { throw "WiX fallo (codigo $LASTEXITCODE)" }
        Write-Host "  [!] WiX fallo (intento $attempt de 3); reintento en 20 s" -ForegroundColor Yellow
        Start-Sleep -Seconds 20
    }
    Remove-Item -LiteralPath ([IO.Path]::ChangeExtension($msi, '.wixpdb')) -ErrorAction SilentlyContinue
    Write-Host "  $msi ($([math]::Round((Get-Item $msi).Length / 1MB)) MB)"
}

# build.ps1 ya escribio SHA256SUMS.txt; se rehace para incluir el MSI
$manifest = Get-ChildItem $Dist -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
$manifest | Set-Content -Path (Join-Path $Dist 'SHA256SUMS.txt') -Encoding ascii

Write-Paso "Listo para distribuir"
Get-ChildItem $Dist -File | Where-Object { $_.Name -match "$([regex]::Escape($Version))|SHA256SUMS" } | ForEach-Object {
    Write-Host ("  {0,-34} {1,6} MB" -f $_.Name, [math]::Round($_.Length / 1MB))
}
Write-Host "`n  Sin firma digital, SmartScreen mostrara 'editor desconocido' (ver packaging\README.md, Firma digital)."
