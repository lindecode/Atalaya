# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from shared.i18n import SUPPORTED_LANGUAGES, get_catalog, t


def test_i18n_supported_languages():
    assert "es" in SUPPORTED_LANGUAGES
    assert "en" in SUPPORTED_LANGUAGES


def test_i18n_lookup_and_formatting():
    # Spanish default lookup with formatting
    msg_es = t("common.rows_matching", matches=3, total=10)
    assert msg_es == "3 de 10 fila(s) coinciden con la búsqueda."

    # English lookup with formatting
    msg_en = t("common.rows_matching", lang="en", matches=3, total=10)
    assert msg_en == "3 of 10 row(s) match the search."


def test_i18n_charts_and_network():
    assert t("charts.direction.inbound", lang="es") == "Entrante"
    assert t("charts.direction.inbound", lang="en") == "Inbound"
    assert t("charts.scope.public", lang="es") == "Internet"
    assert t("charts.scope.public", lang="en") == "Internet"
    assert t("charts.scope.loopback", lang="es") == "Este equipo"
    assert t("charts.scope.loopback", lang="en") == "This device"


def test_i18n_table_enums():
    verdicts_es = t("tables.verdicts", lang="es")
    verdicts_en = t("tables.verdicts", lang="en")
    assert verdicts_es["malicious"] == "Malicioso"
    assert verdicts_en["malicious"] == "Malicious"

    headers_es = t("tables.headers", lang="es")
    headers_en = t("tables.headers", lang="en")
    assert headers_es["process_name"] == "Proceso"
    assert headers_en["process_name"] == "Process"


def test_i18n_rules():
    rule_es = t("rules.R01", lang="es")
    rule_en = t("rules.R01", lang="en")
    assert "4625" in rule_es["detects"]
    assert "4625" in rule_en["detects"]
    assert "bloquee" in rule_es["check"]
    assert "block" in rule_en["check"].lower()


def test_i18n_llm_prompts():
    summary_prompt_es = t("llm.summary_system_prompt", lang="es")
    summary_prompt_en = t("llm.summary_system_prompt", lang="en")
    assert "respondes en español" in summary_prompt_es
    assert "respond in English" in summary_prompt_en

    policy_es = t("llm.chat_system_policy", lang="es")
    policy_en = t("llm.chat_system_policy", lang="en")
    assert "UNTRUSTED_EVIDENCE" in policy_es
    assert "UNTRUSTED_EVIDENCE" in policy_en
    assert "solo lectura" in policy_es
    assert "read-only" in policy_en


def test_i18n_fallback_for_missing_key():
    assert t("non_existent_key", lang="en") == "non_existent_key"
    assert t("non_existent_key", default="Custom Fallback") == "Custom Fallback"


def test_i18n_navigation_and_pages():
    assert t("nav.sections.home", lang="es") == "Inicio"
    assert t("nav.sections.home", lang="en") == "Home"
    assert t("nav.sections.investigate", lang="es") == "Investigar"
    assert t("nav.sections.investigate", lang="en") == "Investigate"
    assert t("nav.sections.system", lang="es") == "Sistema"
    assert t("nav.sections.system", lang="en") == "System"

    assert t("nav.pages.overview", lang="es") == "Panel"
    assert t("nav.pages.overview", lang="en") == "Overview"
    assert t("nav.pages.settings", lang="es") == "Ajustes"
    assert t("nav.pages.settings", lang="en") == "Settings"

    # Pages title & subtitle
    overview_title_es = t("pages.overview.title", lang="es")
    overview_title_en = t("pages.overview.title", lang="en")
    assert "Panel de seguridad" in overview_title_es
    assert "Security Dashboard" in overview_title_en

    # Tabs
    assert t("tabs.features", lang="es") == "Funciones"
    assert t("tabs.features", lang="en") == "Features"
    assert t("tabs.flow_map", lang="es") == "Mapa de flujo"
    assert t("tabs.flow_map", lang="en") == "Flow Map"


def test_hero_mapping_completeness():
    from interfaces.gui.components import PAGE_HERO_MAP

    pages_es = t("pages", lang="es")
    pages_en = t("pages", lang="en")

    for key, pkey in PAGE_HERO_MAP.items():
        assert pkey in pages_es, f"{pkey} missing in ES pages"
        assert pkey in pages_en, f"{pkey} missing in EN pages"
        assert "title" in pages_es[pkey]
        assert "subtitle" in pages_es[pkey]
        assert "title" in pages_en[pkey]
        assert "subtitle" in pages_en[pkey]


def test_all_literal_keys_in_code_exist_in_catalogs():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[2]
    key_pattern = re.compile(r'\bt\(\s*["\']([a-zA-Z0-9_\.]+)["\']')
    ignored_keys = {"non_existent_key"}

    missing = []
    for py_file in root.rglob("*.py"):
        if ".venv" in py_file.parts or "build" in py_file.parts or "tools_" in py_file.name:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for match in key_pattern.finditer(content):
            key = match.group(1)
            if key in ignored_keys:
                continue
            for lang in ("es", "en"):
                val = t(key, lang=lang)
                if val == key:
                    missing.append((str(py_file.relative_to(root)), key, lang))

    assert not missing, f"Missing translation keys in catalogs: {missing}"



