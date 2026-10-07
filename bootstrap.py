from __future__ import annotations

from dataclasses import replace

from application.collect import CollectService
from application.analyze import AnalyzeService
from application.reports import ReportService
from application.status import StatusService
from application.watch import WatchService
from application.chat import ChatService
from application.chat_history import RecordedChatService
from application.conversation_memory import ConversationMemoryService
from application.doctor import DoctorService
from application.models import ModelService
from application.rag import RagService
from application.reputation import FileReputationService
from application.automation import AutomationConfigService, CycleService
from application.tool_router import SecureToolRouter
from infrastructure.clock import SystemClock
from infrastructure.ollama.analyzer import OllamaAnalyzer
from infrastructure.ollama.client import build_chat_client, pull_model
from infrastructure.ollama.models import OllamaModelCatalog
from infrastructure.ollama.embeddings import OllamaEmbeddingProvider
from infrastructure.llm_provider import build_components, provider_name
from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.sqlite.chat_history import SQLiteChatHistory
from infrastructure.sqlite.chat_tools import SQLiteQueryTools
from infrastructure.sqlite.knowledge_store import SQLiteKnowledgeStore
from infrastructure.sqlite.reputation_store import SQLiteReputationStore
from infrastructure.reputation.virustotal import VirusTotalHashProvider
from infrastructure.windows.authenticode import PowerShellAuthenticodeAnalyzer
from infrastructure.windows.common import WindowsSystemInfo, pid_alive
from infrastructure.windows.connections import PsutilConnectionCollector
from infrastructure.windows.event_log import RDP_CHANNEL, SECURITY_CHANNEL, WindowsEventLogCollector
from infrastructure.windows.file_watcher import build_observer
from infrastructure.windows.files import RecentFileCollector
from infrastructure.windows.firewall import FirewallLogCollector
from infrastructure.windows.persistence import WindowsPersistenceCollector
from infrastructure.windows.processes import PsutilProcessCollector
from infrastructure.windows.notifier import WindowsNotifier
from infrastructure.windows.sysmon import SysmonCollector
from infrastructure.windows.ssh import SSHObservationCollector
from infrastructure.windows.webview2 import webview2_version
from settings import Settings


def build_repository(settings: Settings | None = None) -> SQLiteRepository:
    return SQLiteRepository(settings or Settings())


COLLECTOR_PROFILES = {
    "quick": {"psutil_connections", "psutil_processes", "security_events", "rdp_events", "windows_firewall", "sysmon_network",
              "sysmon_process_registry", "ssh_observability"},
    "standard": None,
    "deep": None,
}


def build_collect_service(settings: Settings | None = None, profile: str = "standard") -> CollectService:
    effective = settings or Settings()
    if profile == "deep": effective = replace(effective, scan_hours=max(effective.scan_hours, 24 * 7))
    repository = build_repository(effective)
    collectors = (
        PsutilConnectionCollector(),
        PsutilProcessCollector(),
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
        SSHObservationCollector(),
    )
    if profile not in COLLECTOR_PROFILES: raise ValueError(f"Perfil de recolección inválido: {profile}")
    allowed = COLLECTOR_PROFILES[profile]
    if allowed is not None: collectors = tuple(collector for collector in collectors if collector.name in allowed)
    return CollectService(repository, collectors, SystemClock(), WindowsSystemInfo())


def build_status_service(settings: Settings | None = None) -> StatusService:
    return StatusService(build_repository(settings))


def build_model_service(settings: Settings | None = None) -> ModelService:
    effective = settings or Settings()
    selected = provider_name(effective)
    if selected == "llama_cpp":
        from infrastructure.llama_cpp.provider import LlamaCppModelCatalog
        effective = replace(effective, ollama_model=effective.llama_cpp_model_path.stem)
        catalog = LlamaCppModelCatalog(effective)
    else:
        catalog = OllamaModelCatalog(effective)
    return ModelService(build_repository(effective), catalog, SystemClock(), effective)


def _with_model(settings: Settings | None, model: str | None, role: str = "chat") -> Settings:
    """Explicit --model wins, then the model chosen in the GUI/`models use`, then the default in settings.py."""
    effective = settings or Settings()
    return replace(effective, ollama_model=model or build_model_service(effective).current(role))


def build_analyze_service(settings: Settings | None = None, model: str | None = None) -> AnalyzeService:
    effective = _with_model(settings, model)
    effective, analyzer, _, _, _ = build_components(effective)
    return AnalyzeService(build_repository(effective), analyzer, SystemClock(),
                          WindowsSystemInfo(), effective)


def build_report_service(settings: Settings | None = None) -> ReportService:
    effective = settings or Settings()
    return ReportService(build_repository(effective), SystemClock(), effective)


def build_watch_service(settings: Settings | None = None) -> WatchService:
    effective = settings or Settings()
    return WatchService(build_repository(effective), SystemClock(), WindowsSystemInfo(), WindowsNotifier(), effective,
                        build_observer)


def build_chat_service(settings: Settings | None = None, model: str | None = None) -> ChatService:
    effective = _with_model(settings, model)
    effective, _, client, _, _ = build_components(effective)
    rag = build_rag_service(effective)
    return ChatService(effective, SecureToolRouter(SQLiteQueryTools(effective), rag), client)


def build_doctor_service(settings: Settings | None = None) -> DoctorService:
    effective = settings or Settings()
    puller = None if provider_name(effective) == "llama_cpp" else lambda name: pull_model(effective, name)
    return DoctorService(effective, build_model_service(effective), webview2_version=webview2_version,
                         model_puller=puller)


def build_chat_history(settings: Settings | None = None) -> SQLiteChatHistory:
    effective = settings or Settings()
    build_repository(effective).initialize()  # applies the chat_* migration on existing databases
    return SQLiteChatHistory(effective)


def build_recorded_chat_service(settings: Settings | None = None, model: str | None = None) -> RecordedChatService:
    effective = _with_model(settings, model, "analysis")
    effective, _, _, embedder_class, _ = build_components(effective)
    history = build_chat_history(effective)
    memory = ConversationMemoryService(history, embedder_class(effective))
    return RecordedChatService(build_chat_service(effective, effective.ollama_model), history,
                               SystemClock(), effective.ollama_model, memory)


def build_rag_service(settings: Settings | None = None, embedding_model: str | None = None,
                      lexical_only: bool = False) -> RagService:
    effective = settings or Settings()
    if lexical_only:
        return RagService(SQLiteKnowledgeStore(effective), SystemClock(), effective, None)
    effective, _, _, embedder_class, _ = build_components(effective)
    embedder = embedder_class(effective, embedding_model)
    return RagService(SQLiteKnowledgeStore(effective), SystemClock(), effective, embedder)


def build_reputation_service(settings: Settings | None = None) -> FileReputationService:
    effective = settings or Settings()
    provider = (VirusTotalHashProvider(effective.virustotal_api_key, effective.reputation_timeout_seconds)
                if effective.virustotal_api_key else None)
    return FileReputationService(SQLiteReputationStore(effective), SystemClock(), effective,
                                 PowerShellAuthenticodeAnalyzer(), provider)


def build_automation_config_service(settings: Settings | None = None) -> AutomationConfigService:
    effective = settings or Settings()
    return AutomationConfigService(build_repository(effective), SystemClock())


def build_cycle_service(settings: Settings | None = None) -> CycleService:
    effective = settings or Settings()
    repository = build_repository(effective)
    return CycleService(repository, SystemClock(), effective, AutomationConfigService(repository, SystemClock()),
                        lambda profile: build_collect_service(effective, profile),
                        lambda configured: build_analyze_service(configured), pid_alive)
