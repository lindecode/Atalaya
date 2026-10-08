from __future__ import annotations

import logging
from typing import Iterable

from domain.models import CollectionRequest, CollectionResult
from ports.clock import Clock
from ports.collectors import Collector
from ports.repositories import CollectionRepository
from ports.system import SystemInfo


log = logging.getLogger("atalaya.collect")


class CollectService:
    def __init__(
        self,
        repository: CollectionRepository,
        collectors: Iterable[Collector],
        clock: Clock,
        system_info: SystemInfo,
    ):
        self.repository = repository
        self.collectors = tuple(collectors)
        self.clock = clock
        self.system_info = system_info

    def execute(self) -> dict[str, object]:
        self.repository.initialize()
        started_at = self.clock.now_iso()
        admin = self.system_info.is_admin()
        run_id = self.repository.start_run("collect", started_at, admin)
        details: dict[str, object] = {}
        total_inserted = 0
        overall_status = "ok"

        for collector in self.collectors:
            try:
                cursor = self.repository.get_cursor(collector.name)
                result = collector.collect(CollectionRequest(now=self.clock.now_iso(), cursor=cursor))
            except Exception as exc:
                log.exception("Recolector %s falló", collector.name)
                result = CollectionResult(
                    collector.name, "auth_events", (), "error",
                    (f"Error no controlado en {collector.name}: {type(exc).__name__}: {exc}",),
                )

            inserted = 0
            if result.status in {"ok", "partial"}:
                try:
                    inserted = self.repository.save_collection(run_id, result, self.clock.now_iso())
                    total_inserted += inserted
                except Exception as exc:
                    log.exception("No se pudo guardar el resultado de %s", collector.name)
                    result = CollectionResult(
                        result.collector, result.item_kind, result.items, "error",
                        result.warnings + (f"No se pudo persistir: {type(exc).__name__}: {exc}",),
                        result.next_cursor,
                    )
            if result.status != "ok":
                overall_status = "partial"
                log.warning("Recolector %s terminó con estado %s: %s", collector.name, result.status,
                            "; ".join(result.warnings)[:1000])
            details[collector.name] = {
                "status": result.status,
                "found": len(result.items),
                "inserted": inserted,
                "warnings": list(result.warnings),
            }

        finished_at = self.clock.now_iso()
        self.repository.finish_run(run_id, finished_at, overall_status, details)
        return {
            "run_id": run_id,
            "status": overall_status,
            "is_admin": admin,
            "inserted": total_inserted,
            "collectors": details,
        }
