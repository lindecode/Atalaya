# Pruebas y entrega

## Preparación

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Ciclo de validación

Ejecuta primero pruebas cercanas y después la suite completa:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\unit\test_modulo.py
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
& .\.venv\Scripts\python.exe -m compileall -q application domain infrastructure interfaces ports shared
git diff --check
```

Para RAG añade:

```powershell
& .\.venv\Scripts\python.exe main.py rag eval --lexical-only
```

Las pruebas que dependen de Ollama, permisos elevados, registros de Windows, GPU o red usan dobles deterministas y una validación manual separada. No conviertas una dependencia ausente en un falso éxito.

## Cobertura mínima

- Dominio: positivos, negativos, umbrales y deduplicación.
- SQLite: migración vacía y existente, transacción, concurrencia y retención.
- Recolector: dato válido, permiso denegado, fuente ausente y cursor incremental.
- GUI: importación, navegación, filtros, formatos y ancho del contenedor.
- LLM/RAG: salida inválida, inyección, herramienta desconocida, timeout, proveedor ausente, citas y fallback léxico.
- Subprocesos/red: host rechazado, argumentos, timeout y fallo del ejecutable.

## Antes del commit

1. Revisa `git status --short` y separa cambios ajenos.
2. Inspecciona `git diff --cached`.
3. Ejecuta `git diff --cached --check`.
4. Resume qué se probó y qué requiere validación manual.

No afirmes que una integración real funciona si sólo se verificó con mocks.
