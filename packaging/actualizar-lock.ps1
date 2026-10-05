# Regenera requirements.lock.txt: resuelve requirements.txt en un entorno limpio y fija todas las versiones
# (incluidas las dependencias indirectas). Ejecutar al cambiar requirements.txt y revisar el diff antes del commit.
#
# Por defecto respeta las versiones ya fijadas (el lock actual actua como restriccion): solo se resuelve lo
# nuevo y nada cambia de version sin querer. -Actualizar resuelve todo de cero (subida deliberada; probar despues).
param([string]$Python = 'py -3.13', [switch]$Actualizar)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lock = Join-Path $root 'requirements.lock.txt'
$venv = Join-Path ([IO.Path]::GetTempPath()) "atalaya-lock-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$constraints = $null
try {
    Invoke-Expression "$Python -m venv `"$venv`""
    $pip = Join-Path $venv 'Scripts\python.exe'
    $arguments = @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $root 'requirements.txt'))
    if (-not $Actualizar -and (Test-Path $lock)) {
        $constraints = Join-Path ([IO.Path]::GetTempPath()) "atalaya-constraints-$([guid]::NewGuid().ToString('N').Substring(0, 8)).txt"
        Copy-Item $lock $constraints
        $arguments += @('-c', $constraints)
    }
    & $pip @arguments
    if ($LASTEXITCODE) { throw "pip install fallo (si choca con una version fijada, use -Actualizar)" }
    $version = (& $pip -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    $frozen = & $pip -m pip freeze --disable-pip-version-check --exclude-editable | Sort-Object
    $header = @(
        "# Versiones exactas para el instalador y el ZIP portable (Windows x64, CPython $version).",
        "# Generado por packaging\actualizar-lock.ps1 a partir de requirements.txt; no editar a mano."
    )
    ($header + $frozen) | Set-Content -Path $lock -Encoding ascii
    Write-Host "requirements.lock.txt actualizado ($($frozen.Count) paquetes, CPython $version$(if (-not $Actualizar) { ', versiones existentes respetadas' }))"
} finally {
    if (Test-Path $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
    if ($constraints -and (Test-Path $constraints)) { Remove-Item $constraints }
}
