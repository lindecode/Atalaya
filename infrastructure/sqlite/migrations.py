MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE runs (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      is_admin INTEGER NOT NULL,
      collectors TEXT,
      status TEXT,
      heartbeat_at TEXT
    );
    CREATE TABLE connections (
      id INTEGER PRIMARY KEY,
      run_id INTEGER REFERENCES runs(id),
      ts TEXT NOT NULL,
      source TEXT NOT NULL,
      proto TEXT,
      direction TEXT,
      laddr TEXT, lport INTEGER,
      raddr TEXT, rport INTEGER,
      state TEXT,
      pid INTEGER,
      process_name TEXT,
      process_path TEXT,
      process_user TEXT,
      signed INTEGER,
      dedup_key TEXT UNIQUE
    );
    CREATE TABLE auth_events (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      channel TEXT NOT NULL,
      event_id INTEGER NOT NULL,
      record_id INTEGER NOT NULL,
      logon_type INTEGER,
      target_user TEXT,
      source_ip TEXT,
      source_host TEXT,
      process_name TEXT,
      status_code TEXT,
      raw_xml TEXT,
      UNIQUE(channel, record_id)
    );
    CREATE TABLE file_events (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      source TEXT NOT NULL,
      action TEXT NOT NULL,
      path TEXT NOT NULL,
      dest_path TEXT,
      extension TEXT,
      size INTEGER,
      sha256 TEXT,
      process_name TEXT,
      dedup_key TEXT UNIQUE
    );
    CREATE TABLE firewall_events (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      action TEXT,
      proto TEXT,
      src_ip TEXT, src_port INTEGER,
      dst_ip TEXT, dst_port INTEGER,
      direction TEXT,
      dedup_key TEXT UNIQUE
    );
    CREATE TABLE persistence_items (
      id INTEGER PRIMARY KEY,
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      kind TEXT NOT NULL,
      location TEXT NOT NULL,
      name TEXT NOT NULL DEFAULT '',
      command TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      last_missing_at TEXT,
      UNIQUE(kind, location, name)
    );
    CREATE TABLE baseline (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      value TEXT NOT NULL,
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      times_seen INTEGER NOT NULL DEFAULT 1,
      approved INTEGER NOT NULL DEFAULT 0,
      UNIQUE(kind, value)
    );
    CREATE TABLE alerts (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      rule_id TEXT NOT NULL,
      severity TEXT NOT NULL,
      title TEXT NOT NULL,
      evidence TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'new',
      status_note TEXT,
      status_at TEXT,
      dedup_key TEXT UNIQUE
    );
    CREATE TABLE llm_analyses (
      id INTEGER PRIMARY KEY,
      run_id INTEGER REFERENCES runs(id),
      ts TEXT NOT NULL,
      model TEXT NOT NULL,
      alert_ids TEXT NOT NULL,
      prompt_chars INTEGER,
      result_json TEXT,
      error TEXT,
      duration_ms INTEGER
    );
    CREATE TABLE cursors (
      source TEXT PRIMARY KEY,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE alert_evidence (
      alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
      entity_type TEXT NOT NULL,
      entity_id INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL,
      PRIMARY KEY (alert_id, entity_type, entity_id)
    );
    CREATE INDEX idx_conn_ts ON connections(ts);
    CREATE INDEX idx_auth_ts ON auth_events(ts, event_id);
    CREATE INDEX idx_auth_ip ON auth_events(source_ip);
    CREATE INDEX idx_file_ts ON file_events(ts);
    CREATE INDEX idx_fw_src ON firewall_events(src_ip, ts);
    CREATE INDEX idx_alert_st ON alerts(status, severity);
    CREATE INDEX idx_evidence_entity ON alert_evidence(entity_type, entity_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conn_remote_ts ON connections(raddr, ts);
    CREATE INDEX IF NOT EXISTS idx_conn_process_ts ON connections(process_name, ts);
    CREATE INDEX IF NOT EXISTS idx_file_action_ts ON file_events(action, ts);
    CREATE INDEX IF NOT EXISTS idx_persistence_first_seen ON persistence_items(first_seen);
    CREATE INDEX IF NOT EXISTS idx_alert_rule_ts ON alerts(rule_id, ts);
    CREATE INDEX IF NOT EXISTS idx_runs_kind_started ON runs(kind, started_at);
    """,
    """
    CREATE TABLE sysmon_events (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      event_id INTEGER NOT NULL,
      record_id INTEGER NOT NULL UNIQUE,
      process_name TEXT,
      data_json TEXT NOT NULL
    );
    CREATE INDEX idx_sysmon_event_ts ON sysmon_events(event_id, ts);
    """,
    """
    CREATE TABLE preferences (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE knowledge_chunks (
      id INTEGER PRIMARY KEY,
      chunk_key TEXT NOT NULL UNIQUE,
      source_uri TEXT NOT NULL,
      title TEXT NOT NULL,
      section TEXT NOT NULL,
      content TEXT NOT NULL,
      trust_level TEXT NOT NULL CHECK(trust_level IN ('trusted','derived','untrusted','llm_generated')),
      content_hash TEXT NOT NULL,
      embedding_model TEXT,
      embedding_json TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_knowledge_source ON knowledge_chunks(source_uri);
    CREATE INDEX idx_knowledge_trust ON knowledge_chunks(trust_level);
    CREATE VIRTUAL TABLE knowledge_fts USING fts5(
      chunk_id UNINDEXED,
      title,
      section,
      content,
      tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TABLE rag_audit (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      query_hash TEXT NOT NULL,
      route TEXT NOT NULL,
      retrieved_ids TEXT NOT NULL,
      embedding_model TEXT,
      duration_ms INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE file_reputation (
      id INTEGER PRIMARY KEY,
      sha256 TEXT NOT NULL,
      path TEXT,
      checked_at TEXT NOT NULL,
      local_json TEXT NOT NULL,
      provider TEXT NOT NULL,
      external_json TEXT,
      verdict TEXT NOT NULL CHECK(verdict IN ('trusted','likely_safe','unknown','suspicious','malicious')),
      confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
      reasons_json TEXT NOT NULL,
      UNIQUE(sha256, provider)
    );
    CREATE INDEX idx_file_reputation_checked ON file_reputation(checked_at);
    CREATE INDEX idx_file_reputation_verdict ON file_reputation(verdict);
    """,
    """
    CREATE TABLE chat_sessions (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE chat_messages (
      id INTEGER PRIMARY KEY,
      session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
      ts TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('user','assistant','error')),
      content TEXT NOT NULL,
      model TEXT,
      tool_calls_json TEXT,
      duration_ms INTEGER
    );
    CREATE INDEX idx_chat_messages_session ON chat_messages(session_id, id);
    CREATE INDEX idx_chat_sessions_updated ON chat_sessions(updated_at);
    """,
    """
    CREATE TABLE ssh_observations (
      id INTEGER PRIMARY KEY,
      run_id INTEGER REFERENCES runs(id),
      ts TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('session','service')),
      direction TEXT,
      local_address TEXT,
      local_port INTEGER,
      remote_address TEXT,
      remote_port INTEGER,
      state TEXT,
      pid INTEGER,
      process_name TEXT,
      process_path TEXT,
      process_user TEXT,
      command_summary TEXT,
      tunnel_types TEXT,
      agent_forwarding INTEGER,
      service_status TEXT,
      service_start_type TEXT,
      dedup_key TEXT NOT NULL UNIQUE
    );
    CREATE INDEX idx_ssh_ts ON ssh_observations(ts);
    CREATE INDEX idx_ssh_remote ON ssh_observations(remote_address, ts);
    """,
    """
    CREATE TABLE conversation_chunks (
      id INTEGER PRIMARY KEY,
      session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
      first_message_id INTEGER NOT NULL,
      last_message_id INTEGER NOT NULL,
      content TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      embedding_model TEXT,
      embedding_json TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(session_id, first_message_id, last_message_id)
    );
    CREATE INDEX idx_conversation_chunks_session ON conversation_chunks(session_id, last_message_id);
    CREATE VIRTUAL TABLE conversation_chunks_fts USING fts5(
      chunk_id UNINDEXED, content, tokenize='unicode61 remove_diacritics 2'
    );
    """,
    """
    CREATE TABLE analysis_cache (
      cache_key TEXT PRIMARY KEY,
      model TEXT NOT NULL,
      result_json TEXT NOT NULL,
      prompt_chars INTEGER NOT NULL,
      alert_ids_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX idx_analysis_cache_model ON analysis_cache(model, created_at);
    """,
    """
    CREATE TABLE process_snapshots (
      id INTEGER PRIMARY KEY,
      run_id INTEGER NOT NULL REFERENCES runs(id),
      ts TEXT NOT NULL,
      process_key TEXT NOT NULL,
      pid INTEGER NOT NULL,
      create_time REAL NOT NULL,
      name TEXT,
      path TEXT,
      process_user TEXT,
      status TEXT,
      parent_pid INTEGER,
      parent_name TEXT,
      command_summary TEXT,
      rss_bytes INTEGER NOT NULL,
      private_bytes INTEGER,
      vms_bytes INTEGER NOT NULL,
      memory_percent REAL NOT NULL,
      cpu_seconds REAL NOT NULL,
      thread_count INTEGER NOT NULL,
      read_bytes INTEGER,
      write_bytes INTEGER,
      UNIQUE(run_id, process_key)
    );
    CREATE TABLE process_lifecycle (
      process_key TEXT PRIMARY KEY,
      pid INTEGER NOT NULL,
      create_time REAL NOT NULL,
      name TEXT,
      path TEXT,
      process_user TEXT,
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      ended_at TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      missed_snapshots INTEGER NOT NULL DEFAULT 0,
      peak_rss_bytes INTEGER NOT NULL DEFAULT 0,
      peak_private_bytes INTEGER
    );
    CREATE INDEX idx_process_snapshot_ts ON process_snapshots(ts);
    CREATE INDEX idx_process_snapshot_key_ts ON process_snapshots(process_key, ts);
    CREATE INDEX idx_process_snapshot_memory ON process_snapshots(private_bytes, rss_bytes);
    CREATE INDEX idx_process_lifecycle_active ON process_lifecycle(active, last_seen);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fw_ts ON firewall_events(ts);
    CREATE INDEX IF NOT EXISTS idx_alert_ts ON alerts(ts);
    """,
)
