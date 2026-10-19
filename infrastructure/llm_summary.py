# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Section summaries from the local LLM, through whichever chat client the active provider builds."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=1500)
    highlights: list[str] = Field(max_length=5)
    risk: Literal["low", "medium", "high", "critical"]


from shared.i18n import t, DEFAULT_LANGUAGE

SYSTEM_PROMPT_ES = t("llm.summary_system_prompt", lang="es")
SYSTEM_PROMPT_EN = t("llm.summary_system_prompt", lang="en")
SYSTEM_PROMPT = SYSTEM_PROMPT_ES


def _escape_data_delimiters(raw_json: str) -> str:
    """Collected text cannot close the <datos> block early."""
    return re.sub(r"(?i)<(/?)datos>", r"\\u003c\1datos>", raw_json)


class ChatSectionSummarizer:
    def __init__(self, client, model: str):
        self.client, self.model = client, model

    def summarize(self, title: str, digest: dict, lang: str = DEFAULT_LANGUAGE) -> dict:
        data = _escape_data_delimiters(json.dumps(digest, ensure_ascii=False, default=str))[:16_000]
        sys_prompt = t("llm.summary_system_prompt", lang=lang, title=title, default=SYSTEM_PROMPT.format(title=title))
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": f"<datos>\n{data}\n</datos>"}],
            format=SectionSummary.model_json_schema(), think=False,
            options={"temperature": 0.2, "top_p": 0.8, "top_k": 20, "seed": 42},
        )
        return SectionSummary.model_validate_json(response.message.content).model_dump()
