# Ciclo completo de una sola vez: recolectar evidencia, analizar (reglas + LLM) y generar el informe.
. "$PSScriptRoot\comun.ps1"

Write-Paso "Recolectando evidencia"
if ((Invoke-Tool @('collect')) -ne 0) { Write-Fallo "La recoleccion fallo"; exit 1 }

Write-Paso "Analizando"
if (-not (Start-OllamaIfNeeded)) { Write-Aviso "Se aplicaran solo las reglas, sin explicaciones del LLM." }
if ((Invoke-Tool @('analyze')) -ne 0) { Write-Fallo "El analisis fallo"; exit 1 }

Write-Paso "Generando informe"
if ((Invoke-Tool @('report')) -ne 0) { Write-Fallo "No se pudo generar el informe"; exit 1 }
Write-Ok "Listo. Revise las alertas en el panel (start\iniciar.bat) o en la carpeta reports\"
