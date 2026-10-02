# Borra las caches regenerables de Python y pytest. No toca data\ (base de datos), reports\ ni .venv\.
. "$PSScriptRoot\comun.ps1"

$targets = @()
$targets += Get-ChildItem -Path $Root -Recurse -Directory -Force -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' -and $_.FullName -notmatch '\\\.git\\' }
$targets += Get-ChildItem -Path $Root -Directory -Force -Filter 'pytest-cache-files-*' -ErrorAction SilentlyContinue
foreach ($name in '.pytest_cache', 'tests\.pytest-tmp') {
    $path = Join-Path $Root $name
    if (Test-Path $path) { $targets += Get-Item -Force $path }
}

if (-not $targets) { Write-Ok "No hay caches que borrar"; exit 0 }
$failed = 0
foreach ($target in $targets) {
    try { Remove-Item -LiteralPath $target.FullName -Recurse -Force -ErrorAction Stop }
    catch { $failed++; Write-Aviso "No se pudo borrar $($target.FullName): $($_.Exception.Message)" }
}
Write-Ok "Borradas $($targets.Count - $failed) carpetas de cache"
if ($failed) { exit 1 }
