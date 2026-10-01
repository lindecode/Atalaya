from __future__ import annotations

import streamlit as st

from infrastructure.sqlite.queries import SQLiteQueryRepository, since_hours
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def context():
    settings = Settings()
    repository = SQLiteRepository(settings)
    repository.initialize()
    query = SQLiteQueryRepository(settings)
    options = {"1 hora": 1, "24 horas": 24, "7 días": 168, "30 días": 720}
    label = st.sidebar.selectbox("Ventana temporal", list(options), index=1)
    st.sidebar.caption("Servidor local: 127.0.0.1")
    return settings, repository, query, since_hours(options[label])

