from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from bootstrap import build_analyze_service, build_chat_history, build_chat_service, build_collect_service, build_cycle_service, build_doctor_service, build_model_service, build_rag_service, build_recorded_chat_service, build_report_service, build_reputation_service, build_repository, build_status_service, build_watch_service
from infrastructure.clock import SystemClock
from shared.about import APP_NAME, APP_VERSION, COPYRIGHT, REPOSITORY_URL


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Monitor local de seguridad para Windows",
                                     epilog=f"{COPYRIGHT} {REPOSITORY_URL}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION} · {COPYRIGHT}")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Recolecta una instantánea local")
    collect.add_argument("--profile", choices=("quick", "standard", "deep"), default="standard")
    cycle = commands.add_parser("cycle", help="Recolecta y analiza sólo cuando hay novedades")
    cycle.add_argument("--profile", choices=("quick", "standard", "deep"))
    cycle.add_argument("--force-analysis", action="store_true")
    cycle.add_argument("--no-llm", action="store_true")
    commands.add_parser("status", help="Muestra el estado y tamaño de la base de datos")
    analyze = commands.add_parser("analyze", help="Ejecuta reglas y correlación local opcional")
    analyze.add_argument("--model", help="Modelo de Ollama solo para esta ejecución")
    commands.add_parser("report", help="Genera un informe Markdown")
    commands.add_parser("gui", help="Abre la interfaz local Streamlit")
    tray = commands.add_parser("tray", help="Atalaya en segundo plano: icono junto al reloj con el panel y el monitor")
    tray.add_argument("--no-browser", action="store_true", help="No abrir el navegador al arrancar")
    tray.add_argument("--monitor", action="store_true", help="Activar también el monitor de archivos")
    tray.add_argument("--navegador", action="store_true", help="Abrir el panel en el navegador en vez de en la ventana de Atalaya")
    commands.add_parser("watch", help="Monitoriza archivos en vivo hasta Ctrl+C")
    chat = commands.add_parser("chat", help="Pregunta al analista local")
    chat.add_argument("question", nargs="?")
    chat.add_argument("--model", help="Modelo de Ollama solo para esta pregunta")
    chat.add_argument("--session", type=int, help="Añade la pregunta a una conversación guardada (ver: historial list)")
    chat.add_argument("--no-history", action="store_true", help="No guardar esta pregunta en el historial")
    history = commands.add_parser("historial", help="Consulta las conversaciones guardadas del chat")
    history_actions = history.add_subparsers(dest="history_action", required=True)
    history_list = history_actions.add_parser("list", help="Lista conversaciones (más recientes primero)")
    history_list.add_argument("--search", help="Texto a buscar en títulos y mensajes")
    history_list.add_argument("--limit", type=int, default=30)
    history_actions.add_parser("show", help="Muestra una conversación").add_argument("id", type=int)
    history_export = history_actions.add_parser("export", help="Exporta una conversación a Markdown")
    history_export.add_argument("id", type=int)
    history_export.add_argument("--output", type=Path, help="Archivo de salida (por defecto, en pantalla)")
    history_actions.add_parser("delete", help="Borra una conversación").add_argument("id", type=int)
    models = commands.add_parser("models", help="Lista los LLM locales de Ollama o elige uno")
    models_actions = models.add_subparsers(dest="models_action")
    models_use = models_actions.add_parser("use", help="Guarda el modelo para un rol")
    models_use.add_argument("name")
    models_use.add_argument("--role", choices=("chat", "analysis", "summary"), default="chat")
    models_actions.add_parser("pull", help="Descarga un modelo con el Ollama local").add_argument("name")
    models_actions.add_parser("recommend", help="Recomienda modelos instalados por función")
    commands.add_parser("doctor", help="Comprueba requisitos (Python, Ollama, modelos, permisos) y cómo resolverlos")
    rag = commands.add_parser("rag", help="Indexa y consulta conocimiento local seguro")
    rag_actions = rag.add_subparsers(dest="rag_action", required=True)
    rag_index = rag_actions.add_parser("index", help="Trocea e indexa Markdown confiable")
    rag_index.add_argument("paths", nargs="*", type=Path)
    rag_index.add_argument("--embedding-model")
    rag_index.add_argument("--lexical-only", action="store_true")
    rag_search = rag_actions.add_parser("search", help="Prueba la recuperación híbrida")
    rag_search.add_argument("query")
    rag_search.add_argument("--top-k", type=int, default=6)
    rag_search.add_argument("--embedding-model")
    rag_search.add_argument("--lexical-only", action="store_true")
    rag_actions.add_parser("status", help="Muestra fuentes, chunks y cobertura de embeddings")
    rag_eval = rag_actions.add_parser("eval", help="Ejecuta el harness local de recuperación y seguridad")
    rag_eval.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag_eval.json")
    rag_eval.add_argument("--lexical-only", action="store_true")
    reputation = commands.add_parser("reputation", help="Analiza ejecutables sin cargarlos a Internet")
    reputation_actions = reputation.add_subparsers(dest="reputation_action", required=True)
    reputation_inspect = reputation_actions.add_parser("inspect", help="Hash, firma Authenticode y reputación opcional")
    reputation_inspect.add_argument("path", type=Path)
    reputation_inspect.add_argument("--online", action="store_true", help="Consulta sólo SHA-256 en VirusTotal")
    reputation_lookup = reputation_actions.add_parser("lookup", help="Consulta un SHA-256 en VirusTotal")
    reputation_lookup.add_argument("sha256")
    reputation_actions.add_parser("list", help="Lista resultados guardados")
    commands.add_parser("backup", help="Crea una copia consistente de SQLite")
    purge = commands.add_parser("purge", help="Aplica la retención local")
    purge.add_argument("--days", type=int, default=30)
    alert = commands.add_parser("alert", help="Cambia el estado de una alerta").add_subparsers(dest="alert_action", required=True)
    for action in ("confirm", "dismiss"):
        sub = alert.add_parser(action)
        sub.add_argument("id", type=int)
        sub.add_argument("--note")
    alert.add_parser("approve", help="Aprueba como normal la entidad de la alerta (R03, R04, R05, R10)").add_argument("id", type=int)
    baseline = commands.add_parser("baseline", help="Administra la baseline").add_subparsers(dest="baseline_action", required=True)
    approve = baseline.add_parser("approve")
    approve.add_argument("kind")
    approve.add_argument("value")
    baseline.add_parser("learn", help="Aprueba todo lo observado hasta ahora y descarta las alertas que cubre")
    return parser


def _print_collect(result: dict[str, object]) -> None:
    print(f"Run {result['run_id']}: {result['status']} (administrador: {'sí' if result['is_admin'] else 'no'})")
    for name, detail in result["collectors"].items():
        print(f"- {name}: {detail['status']}; encontrados={detail['found']}; nuevos={detail['inserted']}")
        for warning in detail["warnings"]:
            print(f"  aviso: {warning}")
    print(f"Total de filas nuevas: {result['inserted']}")


def _print_status(result: dict[str, object]) -> None:
    print(f"Base de datos: {result['database']}")
    print(f"Tamaño: {result['database_bytes']} bytes")
    print("Filas:")
    for table, count in result["tables"].items():
        print(f"- {table}: {count}")
    if result["last_run"]:
        last = result["last_run"]
        print(f"Última ejecución: #{last['id']} {last['kind']} {last['status']} iniciada {last['started_at']}")
    else:
        print("Última ejecución: ninguna")


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    if args.command == "collect":
        _print_collect(build_collect_service(profile=args.profile).execute())
        return 0
    if args.command == "cycle":
        try:
            result = build_cycle_service().execute(args.profile, args.force_analysis,
                                                   False if args.no_llm else None)
        except (ValueError, RuntimeError) as exc:
            raise SystemExit(f"No se pudo ejecutar el ciclo: {exc}")
        print(f"Perfil={result['profile']}")
        _print_collect(result["collected"])
        if result["analysis_skipped"]: print("Análisis omitido: no hubo evidencia nueva o está desactivado.")
        elif result["analyzed"]:
            analysis = result["analyzed"]
            print(f"Análisis #{analysis['run_id']}: alertas nuevas={analysis['new_alerts']}; LLM={analysis['llm_alerts']}")
        return 0
    if args.command == "status":
        _print_status(build_status_service().execute())
        return 0
    if args.command == "analyze":
        result = build_analyze_service(model=args.model).execute()
        print(f"Run {result['run_id']}: {result['status']}; alertas nuevas={result['new_alerts']}; "
              f"analizadas por {result['llm_model']}={result['llm_alerts']}")
        if result["learning"]:
            print("Baseline en aprendizaje: lo observado en esta ejecución se aprueba como normal.")
        if result["llm_error"]:
            print(f"Aviso: LLM no disponible: {result['llm_error']}")
        return 0
    if args.command == "doctor":
        icons = {"ok": "[ok]", "warn": "[!] ", "fail": "[x] ", "info": "[i] "}
        checks = build_doctor_service().run()
        group = None
        for check in checks:
            if check.group != group:
                group = check.group
                print(f"\n== {group}")
            print(f"  {icons[check.status]} {check.title}: {check.detail}")
            if check.fix:
                print(f"         -> {check.fix}")
        failed = [check for check in checks if check.status == "fail"]
        print("\nTodo listo." if not failed and not any(c.status == "warn" for c in checks)
              else f"\n{len(failed)} problema(s) bloqueante(s)." if failed else "\nFunciona; revise los avisos [!].")
        return 1 if failed else 0
    if args.command == "models":
        service = build_model_service()
        if args.models_action == "pull":
            doctor = build_doctor_service()
            last = ""
            try:
                for status, completed, total in doctor.pull_model(args.name):
                    line = f"{status} {completed * 100 // total}%" if total else status
                    if line != last:
                        print(f"\r{line:<60}", end="", flush=True)
                        last = line
            except Exception as exc:
                raise SystemExit(f"\nNo se pudo descargar {args.name}: {exc}")
            print(f"\nDescargado {args.name}")
            return 0
        if args.models_action == "use":
            try:
                model = service.select(args.name, args.role)
            except ValueError as exc:
                raise SystemExit(str(exc))
            print(f"Modelo seleccionado para {args.role}: {model['name']}" +
                  ("" if model["tools"] or args.role != "chat" else " (aviso: sin tool calling)"))
            return 0
        if args.models_action == "recommend":
            for role, model in service.recommendations().items():
                print(f"{role:<10} {model['name'] if model else 'sin modelo compatible'}")
            return 0
        current = service.current()
        try:
            models = service.available()
        except Exception as exc:
            raise SystemExit(f"Ollama no disponible: {exc}")
        for model in models:
            marker = "*" if model["name"] == current else " "
            uses = "analyze+chat" if model["tools"] else "analyze" if model["chat"] else "embeddings"
            print(f"{marker} {model['name']:<28} {model['parameters'] or '?':>6}  {model['size_gb']:>5} GB  {uses}")
        if current not in {model["name"] for model in models}:
            print(f"Aviso: el modelo actual {current} no está instalado (ollama pull {current})")
        return 0
    if args.command == "rag":
        service = build_rag_service(embedding_model=getattr(args, "embedding_model", None),
                                    lexical_only=getattr(args, "lexical_only", False))
        if args.rag_action == "index":
            try:
                result = service.index(args.paths or None)
            except (ValueError, OSError) as exc:
                raise SystemExit(f"No se pudo indexar: {exc}")
            print(f"Fuentes={result['sources']} chunks={result['chunks']} embeddings={result['embedded']}")
            if result["removed_sources"]:
                print(f"Retiradas del índice (ya no existen): {', '.join(result['removed_sources'])}")
            if result["embedding_error"]:
                print(f"Aviso: embeddings no disponibles; FTS5 quedó operativo: {result['embedding_error']}")
            return 0
        if args.rag_action == "search":
            for item in service.search(args.query, args.top_k):
                print(f"[K:{item.id}] score={item.score:.3f} {item.source_uri} > {item.section}")
                print(item.content[:500].replace("\n", " "))
            return 0
        if args.rag_action == "eval":
            from application.evals import RagEvalHarness
            result = RagEvalHarness(service).run(args.fixtures)
            for case in result["cases"]:
                print(f"{'PASS' if case['passed'] else 'FAIL'} {case['name']} ids={case.get('ids', [])}")
            print(f"Score: {result['passed']}/{result['total']} ({result['score']:.0%})")
            return 0 if result["passed"] == result["total"] else 1
        print(service.status())
        return 0
    if args.command == "reputation":
        service = build_reputation_service()
        try:
            if args.reputation_action == "inspect":
                result = service.inspect(args.path, args.online)
                print(f"{result.verdict} confidence={result.confidence:.0%} sha256={result.sha256}")
                signature = result.local.get("signature", {})
                print(f"Firma={signature.get('status', 'no comprobada')} publisher={signature.get('subject') or '-'}")
                if result.external: print(f"VirusTotal={result.external.get('stats', {})}")
                for reason in result.reasons: print(f"- {reason}")
            elif args.reputation_action == "lookup":
                result = service.lookup(args.sha256)
                print(f"{result.verdict} confidence={result.confidence:.0%} sha256={result.sha256}")
                print(f"VirusTotal={result.external.get('stats', {}) if result.external else 'sin resultado'}")
            else:
                for row in service.latest():
                    print(f"{row['checked_at']} {row['verdict']:<12} {row['confidence']:.0%} {row['sha256']} {row['path'] or '-'}")
        except (ValueError, OSError, RuntimeError) as exc:
            raise SystemExit(f"No se pudo obtener reputación: {exc}")
        return 0
    if args.command == "report":
        print(build_report_service().execute())
        return 0
    if args.command == "tray":
        from interfaces.tray import run_tray
        return run_tray(open_browser=not args.no_browser, monitor=args.monitor, force_browser=args.navegador)
    if args.command == "gui":
        project = Path(__file__).resolve().parents[1]
        config = tomllib.loads((project / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        address = config.get("server", {}).get("address")
        if address not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit("La GUI solo puede escuchar en loopback")
        try:
            return subprocess.call([sys.executable, "-m", "streamlit", "run", "interfaces/gui/app.py"], cwd=project)
        except KeyboardInterrupt:
            return 0
    if args.command == "watch":
        result = build_watch_service().execute()
        print(f"Watch #{result['run_id']}: eventos={result['events']}; alertas={result['alerts']}")
        return 0
    if args.command == "chat":
        question = args.question or input("Pregunta: ")
        if args.no_history:
            result = build_chat_service(model=args.model).ask(question)
        else:
            try:
                result = build_recorded_chat_service(model=args.model).ask(question, args.session)
            except (KeyError, ValueError) as exc:
                raise SystemExit(str(exc))
        print(result["answer"])
        for call in result["tool_calls"]:
            print(f"- {call['name']}: ids={call['ids']}")
        if "session_id" in result:
            print(f"(guardado en la conversación #{result['session_id']}; continuar con --session {result['session_id']})")
        return 0
    if args.command == "historial":
        store = build_chat_history()
        if args.history_action == "list":
            sessions = store.list_sessions(args.search, args.limit)
            if not sessions:
                print("No hay conversaciones guardadas" + (f" que contengan «{args.search}»" if args.search else ""))
            for session in sessions:
                print(f"#{session['id']:<5} {session['updated_at'][:16].replace('T', ' ')}  "
                      f"{session['messages']:>3} msj  {session['title']}")
            return 0
        if args.history_action == "delete":
            if not store.delete_session(args.id):
                raise SystemExit(f"Conversación inexistente: {args.id}")
            print(f"Conversación #{args.id} borrada")
            return 0
        try:
            markdown = store.export_markdown(args.id)
        except KeyError as exc:
            raise SystemExit(str(exc))
        if args.history_action == "export" and args.output:
            args.output.write_text(markdown, encoding="utf-8")
            print(args.output)
        else:
            print(markdown)
        return 0
    if args.command == "backup":
        repository = build_repository(); repository.initialize()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = repository.settings.backup_dir / f"atalaya_{stamp}.db"
        print(repository.backup(destination))
        return 0
    if args.command == "purge":
        if args.days < 1: raise SystemExit("--days debe ser positivo")
        repository = build_repository(); repository.initialize()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        print(repository.purge(cutoff))
        return 0
    if args.command == "alert":
        repository = build_repository()
        repository.initialize()
        if args.alert_action == "approve":
            try:
                kind, value = repository.approve_alert(args.id, SystemClock().now_iso())
            except (KeyError, ValueError) as exc:
                raise SystemExit(str(exc))
            print(f"Baseline aprobada: {kind}={value}")
            return 0
        status = "confirmed" if args.alert_action == "confirm" else "dismissed"
        repository.update_alert_status(args.id, status, args.note, SystemClock().now_iso())
        print(f"Alerta {args.id}: {status}")
        return 0
    if args.command == "baseline":
        repository = build_repository()
        repository.initialize()
        if args.baseline_action == "learn":
            now = SystemClock().now_iso()
            counts = repository.approve_all_observed(now)
            dismissed = repository.dismiss_baselined("Baseline aprendida", now)
            print(f"Baseline aprobada: {counts}; alertas descartadas: {dismissed}")
            return 0
        repository.approve_baseline(args.kind, args.value, SystemClock().now_iso())
        print(f"Baseline aprobada: {args.kind}={args.value}")
        return 0
    raise AssertionError(args.command)
