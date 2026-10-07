from dataclasses import replace
from datetime import datetime, timezone

from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def test_live_queries_return_bounded_current_state_and_timeline(tmp_path):
    database = tmp_path / "atalaya.db"
    settings = replace(Settings(), database_path=database, reports_dir=tmp_path / "reports")
    SQLiteRepository(settings).initialize()
    now = datetime.now(timezone.utc).isoformat()
    with connect(database) as db:
        run = db.execute(
            "INSERT INTO runs(kind,started_at,is_admin,status) VALUES ('collect',?,0,'ok')", (now,)
        ).lastrowid
        db.execute(
            """INSERT INTO process_snapshots
            (run_id,ts,process_key,pid,create_time,name,rss_bytes,vms_bytes,memory_percent,cpu_seconds,thread_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run, now, "1:1", 1, 1.0, "demo.exe", 100, 200, 1.0, 2.0, 3),
        )
        db.execute(
            """INSERT INTO connections
            (run_id,ts,source,proto,direction,laddr,lport,raddr,rport,state,pid,process_name,dedup_key)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run, now, "psutil", "tcp", "outbound", "127.0.0.1", 50000,
             "203.0.113.5", 443, "ESTABLISHED", 1, "demo.exe", "live-connection"),
        )
        db.execute(
            "INSERT INTO alerts(ts,rule_id,severity,title,evidence,dedup_key) VALUES (?,?,?,?,?,?)",
            (now, "R03", "high", "Destino nuevo", "{}", "live-alert"),
        )

    query = SQLiteQueryRepository(settings)
    status = query.live_status()
    events = query.live_events("2000-01-01T00:00:00+00:00", limit=2)
    freshness = {row["fuente"]: row["ultima_observacion"] for row in query.live_freshness()}

    assert status["processes"] == 1 and status["memory_bytes"] == 100
    assert status["connections"] == 1 and status["alerts"] == {"high": 1}
    assert len(events) == 2 and {row["tipo"] for row in events} <= {"alerta", "conexión"}
    assert freshness["Procesos"] == now and freshness["Conexiones"] == now
