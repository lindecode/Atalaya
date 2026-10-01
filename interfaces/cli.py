from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from bootstrap import build_analyze_service, build_chat_service, build_collect_service, build_report_service, build_repository, build_status_service, build_watch_service
from infrastructure.clock import SystemClock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="network-llm", description="Monitor local de seguridad para Windows")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="Recolecta una instantánea local")
    commands.add_parser("status", help="Muestra el estado y tamaño de la base de datos")
    commands.add_parser("analyze", help="Ejecuta reglas y correlación local opcional")
    commands.add_parser("report", help="Genera un informe Markdown")
    commands.add_parser("gui", help="Abre la interfaz local Streamlit")
    commands.add_parser("watch", help="Monitoriza archivos en vivo hasta Ctrl+C")
    chat = commands.add_parser("chat", help="Pregunta al analista local")
    chat.add_argument("question", nargs="?")
    commands.add_parser("backup", help="Crea una copia consistente de SQLite")
    purge = commands.add_parser("purge", help="Aplica la retención local")
    purge.add_argument("--days", type=int, default=30)
    alert = commands.add_parser("alert", help="Cambia el estado de una alerta").add_subparsers(dest="alert_action", required=True)
    for action in ("confirm", "dismiss"):
        sub = alert.add_parser(action)
        sub.add_argument("id", type=int)
        sub.add_argument("--note")
    baseline = commands.add_parser("baseline", help="Administra la baseline").add_subparsers(dest="baseline_action", required=True)
    approve = baseline.add_parser("approve")
    approve.add_argument("kind")
    approve.add_argument("value")
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
        result = build_analyze_service().execute()
        print(f"Run {result['run_id']}: {result['status']}; alertas nuevas={result['new_alerts']}; enviadas al LLM={result['llm_alerts']}")
        if result["llm_error"]:
            print(f"Aviso: LLM no disponible: {result['llm_error']}")
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
        result = build_chat_service().ask(question)
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
        status = "confirmed" if args.alert_action == "confirm" else "dismissed"
        repository.update_alert_status(args.id, status, args.note, SystemClock().now_iso())
        print(f"Alerta {args.id}: {status}")
        return 0
    if args.command == "baseline":
        repository = build_repository()
        repository.initialize()
        repository.approve_baseline(args.kind, args.value, SystemClock().now_iso())
        print(f"Baseline aprobada: {args.kind}={args.value}")
        return 0
    raise AssertionError(args.command)
