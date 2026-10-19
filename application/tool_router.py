# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations


class SecureToolRouter:
    """Closed router: SQL evidence stays exact; RAG only searches approved knowledge."""

    SQL_TOOLS = {"get_overview", "get_alerts", "get_auth_events", "get_connections", "get_processes", "get_file_events", "get_file_reputation", "get_persistence_new", "get_ssh_observations"}

    def __init__(self, sql_tools, rag_service, dev_servers=None, containers=None):
        """`dev_servers(args)` / `containers(args)` answer from live sockets and Docker (not SQL); None disables them."""
        self.sql_tools, self.rag_service = sql_tools, rag_service
        self.dev_servers, self.containers = dev_servers, containers

    def call(self, name, args):
        if name in self.SQL_TOOLS:
            return self.sql_tools.call(name, args)
        if name == "get_dev_servers" and self.dev_servers is not None:
            return self.dev_servers(dict(args or {}))
        if name == "get_containers" and self.containers is not None:
            return self.containers(dict(args or {}))
        if name == "search_knowledge":
            unexpected = set(args) - {"query", "top_k"}
            if unexpected: raise ValueError(f"Argumentos no permitidos: {sorted(unexpected)}")
            query = args.get("query")
            if not isinstance(query, str) or not query.strip(): raise ValueError("query es obligatorio")
            top_k = int(args.get("top_k", 6))
            return self.rag_service.as_tool_rows(query, top_k)
        raise ValueError(f"Herramienta no permitida: {name}")
