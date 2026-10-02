from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from bootstrap import build_analyze_service, build_chat_service, build_collect_service, build_model_service, build_report_service, build_repository, build_status_service, build_watch_service
from infrastructure.clock import SystemClock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="network-llm", description="Monitor local de seguridad para Windows")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="Recolecta una instantánea local")
    commands.add_parser("status", help="Muestra el estado y tamaño de la base de datos")
    analyze = commands.add_parser("analyze", help="Ejecuta reglas y correlación local opcional")
    analyze.add_argument("--model", help="Modelo de Ollama solo para esta ejecución")
    commands.add_parser("report", help="Genera un informe Markdown")
    commands.add_parser("gui", help="Abre la interfaz local Streamlit")
    commands.add_parser("watch", help="Monitoriza archivos en vivo hasta Ctrl+C")
    chat = commands.add_parser("chat", help="Pregunta al analista local")
    chat.add_argument("question", nargs="?")
    chat.add_argument("--model", help="Modelo de Ollama solo para esta pregunta")
    models = commands.add_parser("models", help="Lista los LLM locales de Ollama o elige uno")
    models_actions = models.add_subparsers(dest="models_action")
    models_actions.add_parser("use", help="Guarda el modelo para analyze/chat/GUI").add_argument("name")
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
        _print_collect(build_collect_service().execute())
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
    if args.command == "models":
        service = build_model_service()
        if args.models_action == "use":
            try:
                model = service.select(args.name)
            except ValueError as exc:
                raise SystemExit(str(exc))
            print(f"Modelo seleccionado: {model['name']}" + ("" if model["tools"] else " (aviso: sin tool calling, el chat no funcionará)"))
            return 0
        current = service.current()
        try:
            models = service.available()
        except Exception as exc:
            raise SystemExit(f"Ollama no disponible: {exc}")
        for model in models:
            marker = "*" if model["name"] == current else " "
            uses = "analyze+chat" if model["tools"] else "analyze" if model["chat"] else "embeddings (no usable)"
            print(f"{marker} {model['name']:<28} {model['parameters'] or '?':>6}  {model['size_gb']:>5} GB  {uses}")
        if current not in {model["name"] for model in models}:
            print(f"Aviso: el modelo actual {current} no está instalado (ollama pull {current})")
        return 0
    if args.command == "report":
        print(build_report_service().execute())
        return 0
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
        result = build_chat_service(model=args.model).ask(question)
        print(result["answer"])
        for call in result["tool_calls"]:
            print(f"- {call['name']}: ids={call['ids']}")
        return 0
    if args.command == "backup":
        repository = build_repository(); repository.initialize()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = repository.settings.backup_dir / f"network_llm_{stamp}.db"
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
