from __future__ import annotations

import argparse
import sys
from typing import Sequence

from bootstrap import build_collect_service, build_status_service


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="network-llm", description="Monitor local de seguridad para Windows")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="Recolecta una instantánea local")
    commands.add_parser("status", help="Muestra el estado y tamaño de la base de datos")
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
    raise AssertionError(args.command)
