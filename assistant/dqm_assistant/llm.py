"""The service's own LLM calls (steps 3, 4 and 6): Fermilab's LiteLLM gateway, OpenAI-compatible.

Key from LITELLM_API_KEY or ~/.litellm_key. Never written anywhere by this code.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

DEFAULT_URL = os.environ.get("DQM_ASSISTANT_LLM_URL", "https://litellm.fnal.gov/v1")
DEFAULT_MODEL = os.environ.get("DQM_ASSISTANT_LLM_MODEL", "azure/claude-opus-5-5")


def _key() -> Optional[str]:
    k = os.environ.get("LITELLM_API_KEY")
    if k:
        return k
    p = Path.home() / ".litellm_key"
    return p.read_text().strip() if p.exists() else None


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_URL):
        from openai import OpenAI
        key = _key()
        if not key:
            raise RuntimeError("no LiteLLM key (LITELLM_API_KEY or ~/.litellm_key)")
        self.client = OpenAI(base_url=base_url, api_key=key)
        self.model = model

    def json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        text = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", text, re.S)          # tolerate prose or ``` fences around it
        if not m:
            raise ValueError(f"model did not return JSON: {text[:200]}")
        return json.loads(m.group(0))


def maybe_llm(enabled: bool = True) -> Optional[LLM]:
    if not enabled:
        return None
    try:
        return LLM()
    except Exception:
        return None
