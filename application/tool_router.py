from __future__ import annotations


class SecureToolRouter:
    """Closed router: SQL evidence stays exact; RAG only searches approved knowledge."""

    SQL_TOOLS = {"get_alerts", "get_auth_events", "get_connections", "get_file_events", "get_file_reputation", "get_persistence_new", "get_ssh_observations"}

    def __init__(self, sql_tools, rag_service):
        self.sql_tools, self.rag_service = sql_tools, rag_service

    def call(self, name, args):
        if name in self.SQL_TOOLS:
            return self.sql_tools.call(name, args)
        if name == "search_knowledge":
            unexpected = set(args) - {"query", "top_k"}
            if unexpected: raise ValueError(f"Argumentos no permitidos: {sorted(unexpected)}")
            query = args.get("query")
            if not isinstance(query, str) or not query.strip(): raise ValueError("query es obligatorio")
            top_k = int(args.get("top_k", 6))
            return self.rag_service.as_tool_rows(query, top_k)
        raise ValueError(f"Herramienta no permitida: {name}")
