# Reputación segura de ejecutables

La aplicación analiza archivos ejecutables sin ejecutarlos ni cargarlos a
Internet. El modo local calcula SHA-256 y valida Authenticode. El modo online
envía exclusivamente el hash SHA-256 a VirusTotal.

```powershell
$env:VIRUSTOTAL_API_KEY = "su-api-key"
& ..\.venv\Scripts\python.exe main.py reputation inspect "C:\ruta\programa.exe"
& ..\.venv\Scripts\python.exe main.py reputation inspect "C:\ruta\programa.exe" --online
& ..\.venv\Scripts\python.exe main.py reputation lookup <sha256>
& ..\.venv\Scripts\python.exe main.py reputation list
```

No existe una función de carga de muestras. Una firma válida o cero detecciones
no prueban que un archivo sea benigno; los resultados son evidencia para
revisión humana y no autorizan bloqueos, borrados ni ejecución automática.
