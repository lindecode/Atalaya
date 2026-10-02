# Regenera requirements.lock.txt: resuelve requirements.txt en un entorno limpio y fija todas las versiones
# (incluidas las dependencias indirectas). Ejecutar al cambiar requirements.txt y revisar el diff antes del commit.
param([string]$Python = 'py -3.13')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path ([IO.Path]::GetTempPath()) "atalaya-lock-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
try {
    Invoke-Expression "$Python -m venv `"$venv`""
    $pip = Join-Path $venv 'Scripts\python.exe'
    & $pip -m pip install --disable-pip-version-check -q -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE) { throw "pip install fallo" }
    $version = (& $pip -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    $frozen = & $pip -m pip freeze --disable-pip-version-check --exclude-editable | Sort-Object
    $header = @(
        "# Versiones exactas para el instalador y el ZIP portable (Windows x64, CPython $version).",
        "# Generado por packaging\actualizar-lock.ps1 a partir de requirements.txt; no editar a mano."
    )
    ($header + $frozen) | Set-Content -Path (Join-Path $root 'requirements.lock.txt') -Encoding ascii
    Write-Host "requirements.lock.txt actualizado ($($frozen.Count) paquetes, CPython $version)"
} finally {
    if (Test-Path $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
}
