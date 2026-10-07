# Contribuir a Atalaya

Al enviar una contribución confirma que tiene derecho a hacerlo y acepta que se
publique bajo MPL-2.0. Conserve la separación entre dominio, aplicación, puertos,
infraestructura e interfaces.

Antes de proponer cambios:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

- No incluya bases, logs, rutas personales, conversaciones, tokens o certificados.
- Añada pruebas para reglas, migraciones, recolectores y consultas.
- No otorgue al LLM ejecución arbitraria, SQL libre ni acceso externo implícito.
- Mantenga las degradaciones seguras cuando falten permisos, Ollama o Sysmon.
- Explique cambios de privacidad, red, permisos o retención.

Las contribuciones no transfieren derechos sobre la marca Atalaya. Las funciones
comerciales separadas pueden mantenerse en otros repositorios y contratos.
