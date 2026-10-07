# Arquitectura de Atalaya

Monitor de seguridad **local** para un equipo Windows. Recolecta evidencia del sistema, la guarda en SQLite y detecta patrones con reglas deterministas. Después usa un LLM local (Ollama) para explicar y priorizar lo detectado. Nada sale del equipo.

Los diagramas usan [Mermaid](https://mermaid.js.org/), que GitHub y VS Code (con la extensión *Markdown Preview Mermaid Support*) renderizan directamente.

---

## 1. Contexto: qué toca la herramienta

Todo ocurre dentro del equipo. Las únicas conexiones de red son a `127.0.0.1`: Ollama en el puerto 11434 y la GUI en el 8501.

```mermaid
flowchart LR
    user(["Usuario"])

    subgraph PC["Equipo Windows (todo local)"]
        direction LR
        subgraph Fuentes["Fuentes del sistema (solo lectura)"]
            psutil["Conexiones y procesos<br/>(psutil)"]
            evtx["Visor de eventos<br/>Security · RDP · Sysmon"]
            fw["pfirewall.log"]
            fs["Archivos del usuario<br/>(escaneo + watchdog)"]
            pers["Run keys · Startup<br/>tareas · servicios"]
        end

        tool["Atalaya<br/>(Python)"]
        db[("SQLite<br/>data/atalaya.db")]
        ollama["Ollama<br/>127.0.0.1:11434"]
        reports["reports/*.md"]
        gui["GUI Streamlit<br/>127.0.0.1:8501"]
    end

    Fuentes -->|lee| tool
    tool <-->|lee/escribe| db
    tool <-->|chat · embeddings| ollama
    tool -->|escribe| reports
    user -->|navegador| gui
    user -->|terminal| tool
    gui --- tool
```

**Restricciones que impone el código:**
- `OLLAMA_HOST` solo acepta `localhost`, `127.0.0.1` o `::1`; cualquier otro valor aborta ([settings.py](../settings.py)).
- La GUI solo arranca si `.streamlit/config.toml` escucha en loopback, y la telemetría de Streamlit está desactivada.
- La herramienta no actúa sobre el sistema: no mata procesos, no borra archivos ni toca el firewall.

---

## 2. Capas (arquitectura hexagonal)

El dominio y los casos de uso no conocen Windows, SQLite ni Ollama. Hablan con ellos a través de **puertos** (`Protocol`) que implementan los **adaptadores** de `infrastructure/`. [bootstrap.py](../bootstrap.py) conecta cada servicio con sus adaptadores.

```mermaid
flowchart TB
    subgraph IF["interfaces/ — entrada"]
        cli["cli.py<br/>collect · analyze · report · watch<br/>chat · models · rag · baseline · alert"]
        guiapp["gui/<br/>app.py · common.py · page_views.py<br/>10 páginas"]
    end

    boot["bootstrap.py<br/>(composición: elige adaptadores)"]

    subgraph APP["application/ — casos de uso"]
        collect["CollectService"]
        analyze["AnalyzeService"]
        watch["WatchService"]
        report["ReportService"]
        chat["ChatService"]
        models["ModelService"]
        rag["RagService<br/>+ MarkdownChunker"]
        router["SecureToolRouter"]
        harness["SecureChatHarness"]
        evals["RagEvalHarness"]
    end

    subgraph DOM["domain/ — reglas puras"]
        dmodels["models.py<br/>NetworkConnection · AuthEvent<br/>FileEvent · AlertCandidate…"]
        rules["rules/catalog.py<br/>R01–R16"]
        rbase["rules/base.py<br/>ventanas · baseline_key"]
        know["knowledge.py<br/>KnowledgeChunk · TrustLevel"]
    end

    subgraph PORTS["ports/ — contratos"]
        pcol["Collector"]
        prepo["CollectionRepository<br/>AnalysisRepository"]
        pllm["StructuredAnalyzer<br/>ModelCatalog"]
        prag["KnowledgeStore<br/>EmbeddingProvider"]
        pother["Clock · SystemInfo<br/>Notifier · ToolExecutor"]
    end

    subgraph INFRA["infrastructure/ — adaptadores"]
        win["windows/<br/>connections · event_log · files<br/>file_watcher · firewall · persistence<br/>sysmon · notifier"]
        sql["sqlite/<br/>repositories · queries · chat_tools<br/>knowledge_store · migrations"]
        oll["ollama/<br/>analyzer · models · embeddings · client"]
    end

    cli --> boot
    guiapp --> boot
    boot --> APP
    APP --> DOM
    APP --> PORTS
    win -. implementa .-> pcol
    sql -. implementa .-> prepo
    sql -. implementa .-> prag
    oll -. implementa .-> pllm
    oll -. implementa .-> prag
```

**Regla de dependencia:** las flechas apuntan hacia dentro. `domain/` no importa nada del proyecto. `application/` importa `domain/` y `ports/`. `infrastructure/` implementa los puertos. Hay una excepción: `ChatService` crea por defecto su cliente de Ollama si no se le inyecta uno.

---

## 3. Flujo principal: recolectar → analizar → informar

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario (CLI o GUI)
    participant C as CollectService
    participant W as Recolectores Windows
    participant DB as SQLite
    participant A as AnalyzeService
    participant R as Reglas R01–R16
    participant L as OllamaAnalyzer
    participant O as Ollama (local)
    participant Rep as ReportService

    U->>C: collect
    loop cada recolector
        C->>DB: leer cursor incremental
        C->>W: collect(cursor)
        W-->>C: items · estado ok/partial/skipped · avisos
        C->>DB: INSERT OR IGNORE (dedup) + nuevo cursor
    end
    C->>DB: cerrar run (qué se saltó y por qué)

    U->>A: analyze [--model]
    A->>DB: evidencia de las últimas 24 h + baseline aprobada
    alt primeras 5 ejecuciones (aprendizaje)
        A->>DB: aprobar lo observado como normal
    end
    A->>R: evaluar reglas
    R-->>A: AlertCandidate[]
    A->>DB: guardar alertas (dedup por regla+entidad+ventana)
    A->>DB: hasta 40 alertas "new", más graves primero
    loop lotes de 8
        A->>L: analyze(lote)
        L->>O: chat · JSON schema · evidencia delimitada como datos
        O-->>L: JSON
        L-->>A: resultado validado + ids realmente enviados
    end
    A->>DB: llm_analyses · solo esos ids pasan a "analyzed"

    U->>Rep: report
    Rep->>DB: alertas + último análisis + recolectores omitidos
    Rep-->>U: reports/AAAAMMDD_HHMM.md
```

**Garantías del flujo:**
- **Detectan las reglas, no el LLM.** Si Ollama falla, el análisis termina con estado `partial` y las alertas siguen ahí. Las de lotes fallidos quedan como `new` para la siguiente ejecución.
- **El LLM no puede inventar ni minimizar.** Se descartan los `alert_id` que el modelo no recibió, y una alerta `critical` nunca baja de `high`.
- **Idempotencia.** Recolectar dos veces no duplica filas: los eventos de Windows se deduplican por `EventRecordID` y el resto con hashes `dedup_key`.

### Monitor en vivo (`watch`)

```mermaid
flowchart LR
    wd["watchdog<br/>(carpetas vigiladas)"] -->|eventos| q["cola en memoria"]
    q -->|cada 5 s, una transacción| db[("file_events")]
    db --> r89["R08 modificación masiva<br/>R09 ransomware"]
    r89 -->|high/critical| toast["aviso local<br/>(consola + sonido)"]
    r89 --> al[("alerts")]
```

R08 ignora `%TEMP%`. R09 usa la extensión de destino de los renombrados (`foto.jpg → foto.jpg.locked`).

---

## 4. Chat con herramientas y RAG

El chat combina dos tipos de fuente: **evidencia** del equipo (SQL, no confiable) y **conocimiento** (documentación del proyecto, confiable). Cada una pasa por una frontera distinta.

```mermaid
flowchart TB
    q["Pregunta del usuario"] --> san["SecureChatHarness<br/>sanea (NUL, espacios, 4000 car.)"]
    san --> llm["Ollama · modelo elegido<br/>SYSTEM_POLICY inmutable · think=False"]
    llm -->|tool_call| router{"SecureToolRouter<br/>(lista cerrada)"}

    router -->|get_alerts · get_auth_events<br/>get_connections · get_file_events<br/>get_persistence_new| sqlt["SQLiteQueryTools<br/>consultas fijas parametrizadas<br/>solo lectura · LIMIT 200<br/>sin raw_xml · campos ≤ 300 car."]
    router -->|search_knowledge| ragsvc["RagService"]
    router -->|cualquier otra| deny["ValueError → se devuelve<br/>el error al modelo"]

    sqlt --> ue["UNTRUSTED_EVIDENCE"]
    ragsvc --> tk["TRUSTED_KNOWLEDGE<br/>citas [K:id]"]
    ue --> llm
    tk --> llm

    llm -->|respuesta final| val["validate_answer<br/>rechaza citas [K:id] no recuperadas"]
    val --> out["Respuesta (texto plano en la GUI)"]
```

### Recuperación híbrida (RAG)

```mermaid
flowchart LR
    subgraph IDX["rag index (Markdown del proyecto)"]
        md["README/*.md · README*.md<br/>(solo .md dentro del proyecto, ≤ 2 MB,<br/>sin enlaces simbólicos)"]
        md --> chunk["MarkdownChunker<br/>por encabezados · 2800 car.<br/>solape 300"]
        chunk --> emb["OllamaEmbeddingProvider<br/>embeddinggemma (caché por hash)"]
        chunk --> fts[("knowledge_fts<br/>FTS5 · bm25")]
        emb --> kc[("knowledge_chunks<br/>embedding_json")]
    end

    subgraph SRCH["rag search"]
        query["consulta"] --> lex["léxica FTS5 × 0.40"]
        query --> vec["coseno embeddings × 0.25<br/>(si Ollama responde)"]
        query --> cov["cobertura de términos × 0.25<br/>+ prioridad de fuente"]
        lex --> rank["ranking top-k"]
        vec --> rank
        cov --> rank
        rank --> audit[("rag_audit<br/>hash de la consulta, ruta, ids")]
    end

    fts -.-> lex
    kc -.-> vec
```

- Si no hay embeddings, la búsqueda cae a **solo léxica** (`lexical_fallback`) y sigue funcionando.
- Cada chunk tiene un **nivel de confianza** (`trusted`, `derived`, `untrusted`, `llm_generated`). El chat solo recupera `trusted` y `derived`.
- `rag eval` comprueba la calidad de recuperación con [tests/fixtures/rag_eval.json](../tests/fixtures/rag_eval.json) y verifica que la evidencia SQL siga marcada como no confiable.

### Selección de modelo

```mermaid
flowchart LR
    pick["models use · selector de la GUI"] --> ms["ModelService"]
    ms -->|"lista + capacidades<br/>(/api/show)"| cat["OllamaModelCatalog"]
    ms -->|guarda| pref[("preferences<br/>ollama_model")]
    pref --> boot["bootstrap._with_model"]
    flag["--model (una vez)"] --> boot
    boot --> an["AnalyzeService / ChatService"]
```

Prioridad: `--model`, después la preferencia guardada y, por último, el valor de `settings.py` (`qwen3.5:4b`). Los modelos de embeddings no se pueden elegir, y los que no admiten `tools` se marcan como no aptos para el chat.

---

## 5. Modelo de datos (SQLite)

Base de datos: `data/atalaya.db`, en modo WAL para que `watch`, `analyze` y la GUI puedan leer y escribir a la vez. Las migraciones están versionadas con `PRAGMA user_version` en [migrations.py](../infrastructure/sqlite/migrations.py).

```mermaid
erDiagram
    runs ||--o{ connections : "run_id"
    runs ||--o{ llm_analyses : "run_id"
    alerts ||--o{ alert_evidence : "alert_id"
    alert_evidence }o--|| connections : "entity connection"
    alert_evidence }o--|| auth_events : "entity auth_event"
    alert_evidence }o--|| file_events : "entity file_event"
    alert_evidence }o--|| firewall_events : "entity firewall_event"
    alert_evidence }o--|| persistence_items : "entity persistence_item"
    knowledge_chunks ||--|| knowledge_fts : "chunk_id"

    runs {
        int id PK
        text kind
        text status
        text collectors
        text heartbeat_at
    }
    connections {
        int id PK
        text direction
        text raddr
        int rport
        text process_path
        text dedup_key UK
    }
    auth_events {
        int id PK
        text channel
        int event_id
        int record_id
        text source_ip
        int logon_type
    }
    file_events {
        int id PK
        text action
        text path
        text dest_path
        text extension
        text sha256
    }
    firewall_events {
        int id PK
        text action
        text src_ip
        int dst_port
        text dedup_key UK
    }
    persistence_items {
        int id PK
        text kind
        text location
        text name
        int active
    }
    sysmon_events {
        int id PK
        int event_id
        int record_id UK
        text data_json
    }
    baseline {
        int id PK
        text kind
        text value
        int approved
    }
    alerts {
        int id PK
        text rule_id
        text severity
        text status
        text evidence
        text dedup_key UK
    }
    alert_evidence {
        int alert_id FK
        text entity_type
        int entity_id
        text snapshot_json
    }
    llm_analyses {
        int id PK
        text model
        text alert_ids
        text result_json
        text error
    }
    cursors {
        text source PK
        text value_json
    }
    preferences {
        text key PK
        text value
    }
    knowledge_chunks {
        int id PK
        text source_uri
        text trust_level
        text content_hash
        text embedding_json
    }
    knowledge_fts {
        int chunk_id
        text content
    }
    rag_audit {
        int id PK
        text query_hash
        text route
        text retrieved_ids
    }
```

- **`alert_evidence`** guarda una copia de cada fila que disparó la alerta (`snapshot_json`). Así la alerta conserva su evidencia aunque `purge` borre los datos originales.
- **`baseline`** guarda lo que se considera normal (`listen_port`, `logon_source`, `persistence`, `process_net`, `process_net_path`, `remote_port`, `remote_ip`). Las reglas R03, R04, R05, R06, R07 y R10 solo consultan las entradas con `approved=1`.
- **Ciclo de vida de una alerta:** `new` → `analyzed` (la vio el LLM) → `confirmed` o `dismissed` (lo decide el usuario). `purge` nunca borra las `confirmed`.

---

## 6. Fronteras de confianza

| Frontera | Riesgo | Control |
|---|---|---|
| Datos recolectados → LLM | Un nombre de archivo, comando o usuario con instrucciones (inyección de prompt) | Se pasan dentro de `<datos>` / `UNTRUSTED_EVIDENCE`, recortados a 300 caracteres, y una política de sistema indica que son datos y nunca instrucciones |
| LLM → base de datos | El modelo inventa alertas o baja una crítica | Esquema Pydantic con `extra="forbid"`, filtrado de ids y suelo `high` para las críticas |
| LLM → herramientas | El modelo pide SQL arbitrario o una herramienta inexistente | Router con lista cerrada y consultas fijas parametrizadas de solo lectura |
| LLM → navegador | Markdown inyectado (`![](http://…)`) que saca datos fuera | El texto del LLM y los informes se muestran como texto plano (`st.text` / `st.code`) |
| Datos recolectados → navegador | XSS con nombres como `<img onerror=…>` | `st.dataframe` y `st.code` escapan el contenido; está prohibido `unsafe_allow_html` |
| Documentos → RAG | Indexar archivos fuera del proyecto o enlaces simbólicos | Solo `.md` dentro de `project_dir`, sin enlaces simbólicos y de 2 MB como máximo |
| Red | Exfiltración a la nube | Ollama y la GUI solo en loopback; no hay ninguna API externa |

---

## 7. Mapa de archivos

| Ruta | Responsabilidad |
|---|---|
| [main.py](../main.py) | Punto de entrada; delega en `interfaces/cli.py` |
| [bootstrap.py](../bootstrap.py) | Composición: construye cada servicio con sus adaptadores y el modelo elegido |
| [settings.py](../settings.py) | Configuración: rutas, umbrales de reglas, modelo, RAG y validación de loopback |
| `domain/` | Modelos inmutables y reglas R01–R16 como funciones puras |
| `application/` | Casos de uso: collect, analyze, watch, report, chat, models, rag y evals |
| `ports/` | Contratos (`Protocol`) entre los casos de uso y la infraestructura |
| `infrastructure/windows/` | Lectura del sistema: psutil, Visor de eventos, firewall, archivos, persistencia y Sysmon |
| `infrastructure/windows/processes.py` | Snapshots de RAM y ciclo de vida; identidad estable por PID y hora de creación |
| `infrastructure/sqlite/` | Persistencia, consultas de solo lectura, herramientas del chat y almacén de conocimiento |
| `infrastructure/ollama/` | Análisis estructurado, catálogo de modelos, embeddings y llamada con fallback de `think` |
| `interfaces/gui/` | Panel Streamlit local |
| `tests/` | Pruebas unitarias e integración, más fixtures de evaluación del RAG |
| `data/`, `reports/` | Datos y salidas locales, excluidos de git |
