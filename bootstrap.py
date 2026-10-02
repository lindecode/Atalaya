from __future__ import annotations

from dataclasses import replace

from application.collect import CollectService
from application.analyze import AnalyzeService
from application.reports import ReportService
from application.status import StatusService
from application.watch import WatchService
from application.chat import ChatService
from application.models import ModelService
from infrastructure.clock import SystemClock
from infrastructure.ollama.analyzer import OllamaAnalyzer
from infrastructure.ollama.models import OllamaModelCatalog
from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.sqlite.chat_tools import SQLiteQueryTools
from infrastructure.windows.common import WindowsSystemInfo
from infrastructure.windows.connections import PsutilConnectionCollector
from infrastructure.windows.event_log import RDP_CHANNEL, SECURITY_CHANNEL, WindowsEventLogCollector
from infrastructure.windows.files import RecentFileCollector
from infrastructure.windows.firewall import FirewallLogCollector
from infrastructure.windows.persistence import WindowsPersistenceCollector
from infrastructure.windows.notifier import WindowsNotifier
from infrastructure.windows.sysmon import SysmonCollector
from settings import Settings


def build_repository(settings: Settings | None = None) -> SQLiteRepository:
    return SQLiteRepository(settings or Settings())


def build_collect_service(settings: Settings | None = None) -> CollectService:
    effective = settings or Settings()
    repository = build_repository(effective)
    collectors = (
        PsutilConnectionCollector(),
        WindowsEventLogCollector(
            "security_events", SECURITY_CHANNEL,
            (4624, 4625, 4648, 4672, 4698, 4720, 4732, 1102), requires_admin=True,
        ),
        WindowsEventLogCollector("rdp_events", RDP_CHANNEL, (1149,)),
        RecentFileCollector(effective),
        WindowsPersistenceCollector(effective),
        FirewallLogCollector(effective.firewall_log_path),
        SysmonCollector("sysmon_network", (3,), "connections"),
        SysmonCollector("sysmon_files", (11, 23), "file_events"),
        SysmonCollector("sysmon_process_registry", (1, 12, 13), "sysmon_events"),
    )
    return CollectService(repository, collectors, SystemClock(), WindowsSystemInfo())


def build_status_service(settings: Settings | None = None) -> StatusService:
    return StatusService(build_repository(settings))


def build_model_service(settings: Settings | None = None) -> ModelService:
    effective = settings or Settings()
    return ModelService(build_repository(effective), OllamaModelCatalog(effective), SystemClock(), effective)


def _with_model(settings: Settings | None, model: str | None) -> Settings:
    """Explicit --model wins, then the model chosen in the GUI/`models use`, then the default in settings.py."""
    effective = settings or Settings()
    return replace(effective, ollama_model=model or build_model_service(effective).current())


def build_analyze_service(settings: Settings | None = None, model: str | None = None) -> AnalyzeService:
    effective = _with_model(settings, model)
    return AnalyzeService(build_repository(effective), OllamaAnalyzer(effective), SystemClock(),
                          WindowsSystemInfo(), effective)


def build_report_service(settings: Settings | None = None) -> ReportService:
    effective = settings or Settings()
    return ReportService(build_repository(effective), SystemClock(), effective)


def build_watch_service(settings: Settings | None = None) -> WatchService:
    effective = settings or Settings()
    return WatchService(build_repository(effective), SystemClock(), WindowsSystemInfo(), WindowsNotifier(), effective)


def build_chat_service(settings: Settings | None = None, model: str | None = None) -> ChatService:
    effective = _with_model(settings, model)
    return ChatService(effective, SQLiteQueryTools(effective))
