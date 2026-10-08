from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from settings import data_home


_SECRET = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|api[_-]?key\s*[:=]\s*|password\s*[:=]\s*|token\s*[:=]\s*)([^\s,;\"']+)"
)


def logs_dir() -> Path:
    return data_home() / "logs"


def log_path(component: str = "app") -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", component.casefold()).strip("-") or "app"
    return logs_dir() / f"atalaya-{safe}.jsonl"


def redact(value: object) -> str:
    return _SECRET.sub(lambda match: match.group(1) + "[REDACTADO]", str(value))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "process": record.process,
            "thread": record.threadName,
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(component: str = "app", level: int = logging.INFO) -> Path:
    """Configure one rotating structured log per process; safe to call repeatedly."""
    path = log_path(component)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    marker = str(path.resolve()).casefold()
    if not any(getattr(handler, "_atalaya_path", None) == marker for handler in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        handler._atalaya_path = marker  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(min(root.level, level) if root.level else level)
    logging.getLogger(f"atalaya.{component}").info("Componente iniciado")
    _install_exception_hooks()
    return path


def _install_exception_hooks() -> None:
    if getattr(sys.excepthook, "_atalaya_hook", False):
        return
    previous = sys.excepthook

    def unhandled(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, KeyboardInterrupt):
            logging.getLogger("atalaya.unhandled").critical(
                "Excepción no controlada", exc_info=(exc_type, exc_value, exc_traceback)
            )
        previous(exc_type, exc_value, exc_traceback)

    unhandled._atalaya_hook = True  # type: ignore[attr-defined]
    sys.excepthook = unhandled

    if hasattr(threading, "excepthook"):
        previous_thread = threading.excepthook

        def thread_unhandled(args):
            if not issubclass(args.exc_type, KeyboardInterrupt):
                logging.getLogger("atalaya.unhandled").critical(
                    "Excepción no controlada en hilo %s", args.thread.name if args.thread else "?",
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
            previous_thread(args)

        threading.excepthook = thread_unhandled
