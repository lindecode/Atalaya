# Reglas de desarrollo

## Principios

- Conserva el funcionamiento local y la degradación segura.
- Prefiere módulos pequeños, funciones inyectables y contratos reutilizables.
- Separa recolección, persistencia, análisis y presentación.
- No dupliques consultas, formato ni decisiones entre CLI y GUI.
- Mantén compatibilidad con Windows y rutas con espacios.
- Usa UTC e ISO 8601 al persistir; formatea fechas legibles sólo en interfaces.
- El fallo de un recolector produce estado `partial` y diagnóstico útil, sin perder evidencia válida de otros.

## Base de datos

- Crea migraciones incrementales en `infrastructure/sqlite/migrations.py`.
- No edites retrospectivamente una migración distribuida.
- Usa consultas parametrizadas, límites explícitos y transacciones breves.
- Prueba actualización desde versión anterior e inicialización vacía.
- La purga preserva alertas confirmadas e instantáneas de evidencia.

## Errores y bitácora

- Registra contexto técnico sin secretos ni datos personales innecesarios.
- Muestra una explicación accionable y conserva el detalle en la bitácora.
- No silencies excepciones generales sin registrar la causa y degradar estado.

## Git y entrega

- Revisa `git status` antes y después: puede haber cambios de otros agentes.
- No modifiques, restaures ni incluyas cambios ajenos.
- Cada commit representa una unidad verificable: `feat(rag): ...`, `fix(gui): ...` o `docs(agents): ...`.
- No hagas push, reescritura, reset destructivo ni merge sin solicitud explícita.
- Termina con código documentado, pruebas proporcionales, compilación válida y `git diff --check` limpio.
