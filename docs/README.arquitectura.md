# Arquitectura y módulos

Atalaya sigue una arquitectura hexagonal. Las dependencias deben apuntar hacia el dominio, no hacia adaptadores concretos.

## Responsabilidades

- `domain/`: entidades y reglas puras; no conoce Windows, SQLite, Streamlit u Ollama.
- `ports/`: contratos (`Protocol`) requeridos por los casos de uso.
- `application/`: casos de uso y coordinación; depende de `domain/` y `ports/`.
- `infrastructure/`: adaptadores Windows, SQLite, Ollama, llama.cpp, reputación, logging y procesos.
- `interfaces/`: CLI, escritorio, bandeja y GUI; no contiene reglas de detección ni SQL de negocio.
- `bootstrap.py`: raíz de composición e inyección de adaptadores.
- `settings.py` y `shared/`: configuración y utilidades transversales pequeñas.
- `tests/`: contrato verificable del comportamiento.

```text
interfaces -> bootstrap -> application -> domain
                              |
                              +-------> ports <- infrastructure
```

No importes `interfaces` desde `application` o `domain`. No abras SQLite desde una vista. No uses `subprocess`, HTTP o APIs de Windows desde el dominio.

## Cómo extender una fuente

1. Define o amplía el contrato en `ports/`.
2. Añade modelos puros en `domain/` sólo si son compartidos.
3. Implementa el adaptador en `infrastructure/`.
4. Coordínalo desde `application/`.
5. Regístralo en `bootstrap.py`.
6. Añade migración y repositorio si persiste datos.
7. Expón la información por CLI/GUI sin duplicar lógica.
8. Añade pruebas unitarias y de integración.

Para diagramas consulta `README/README.arqu.md`. Si cambia una frontera entre capas, actualiza ambos documentos.
