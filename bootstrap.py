from __future__ import annotations

from application.collect import CollectService
from application.analyze import AnalyzeService
from application.reports import ReportService
from application.status import StatusService
from application.watch import WatchService
from infrastructure.clock import SystemClock
from infrastructure.ollama.analyzer import OllamaAnalyzer
from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.windows.common import WindowsSystemInfo
from infrastructure.windows.connections import PsutilConnectionCollector
from infrastructure.windows.event_log import RDP_CHANNEL, SECURITY_CHANNEL, WindowsEventLogCollector
from infrastructure.windows.files import RecentFileCollector
from infrastructure.windows.firewall import FirewallLogCollector
from infrastructure.windows.persistence import WindowsPersistenceCollector
from infrastructure.windows.notifier import WindowsNotifier
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
    )
    return CollectService(repository, collectors, SystemClock(), WindowsSystemInfo())


def build_status_service(settings: Settings | None = None) -> StatusService:
    return StatusService(build_repository(settings))


def build_analyze_service(settings: Settings | None = None) -> AnalyzeService:
    effective = settings or Settings()
    return AnalyzeService(build_repository(effective), OllamaAnalyzer(effective), SystemClock(),
                          WindowsSystemInfo(), effective)


def build_report_service(settings: Settings | None = None) -> ReportService:
    effective = settings or Settings()
    return ReportService(build_repository(effective), SystemClock(), effective)


def build_watch_service(settings: Settings | None = None) -> WatchService:
    effective = settings or Settings()
    return WatchService(build_repository(effective), SystemClock(), WindowsSystemInfo(), WindowsNotifier(), effective)
