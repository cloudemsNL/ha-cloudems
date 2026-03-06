# -*- coding: utf-8 -*-
"""Multi-provider AI NILM classifier for CloudEMS — v1.5.0.

Priority order (as configured):
  1. Built-in pattern matching (always available)
  2. Ollama local LLM (if configured)
  3. CloudEMS / OpenAI / Anthropic cloud (as fallback)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import asyncio
import json
from typing import List, Dict, Optional
import aiohttp

from ..const import (
    CLOUD_API_BASE, CLOUD_NILM_ENDPOINT,
    AI_PROVIDER_NONE, AI_PROVIDER_CLOUDEMS, AI_PROVIDER_OPENAI,
    AI_PROVIDER_ANTHROPIC, AI_PROVIDER_OLLAMA,
)

_LOGGER = logging.getLogger(__name__)

OPENAI_URL    = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VER = "2023-06-01"


def _nilm_prompt(delta_power: float, rise_time: float, context: dict) -> str:
    return (
        f"You are a NILM (Non-Intrusive Load Monitoring) expert. "
        f"A power change of {delta_power:.0f}W was detected (rise time {rise_time:.1f}s). "
        f"Context: {json.dumps(context)}. "
        f"Identify the most likely household appliance. "
        f"Respond ONLY with JSON: "
        f'[{{"device_type":"<type>","name":"<friendly name>","confidence":<0-1>}}]'
    )


class CloudAIClassifier:
    """Classifies power events via configured AI provider."""

    def __init__(self, api_key: Optional[str], session: aiohttp.ClientSession,
                 provider: str = AI_PROVIDER_CLOUDEMS):
        self._api_key  = api_key
        self._session  = session
        self._provider = provider
        self._available    = provider != AI_PROVIDER_NONE and bool(api_key or provider == AI_PROVIDER_OLLAMA)
        self._last_error: Optional[str] = None
        self._call_count   = 0
        # Ollama settings (set externally if provider == ollama)
        self.ollama_host  = "localhost"
        self.ollama_port  = 11434
        self.ollama_model = "llama3"

    # ── Public interface ──────────────────────────────────────────────────────

    async def classify(self, delta_power: float, rise_time: float, context: Dict) -> List[Dict]:
        """Classify event. Returns [] when provider is none or call fails."""
        if self._provider == AI_PROVIDER_NONE:
            return []
        try:
            if self._provider == AI_PROVIDER_CLOUDEMS:
                return await self._call_cloudems(delta_power, rise_time, context)
            elif self._provider == AI_PROVIDER_OPENAI:
                return await self._call_openai(delta_power, rise_time, context)
            elif self._provider == AI_PROVIDER_ANTHROPIC:
                return await self._call_anthropic(delta_power, rise_time, context)
            elif self._provider == AI_PROVIDER_OLLAMA:
                return await self._call_ollama(delta_power, rise_time, context)
        except asyncio.TimeoutError:
            _LOGGER.debug("AI provider %s timeout, using local fallback", self._provider)
        except Exception as exc:
            self._last_error = str(exc)
            _LOGGER.debug("AI provider %s error: %s", self._provider, exc)
        return []

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def provider(self) -> str:
        return self._provider

    # ── CloudEMS ──────────────────────────────────────────────────────────────

    async def _call_cloudems(self, delta_power, rise_time, context) -> List[Dict]:
        if not self._api_key:
            return []
        url     = f"{CLOUD_API_BASE}{CLOUD_NILM_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {"delta_power": delta_power, "rise_time": rise_time, "context": context, "source": "ha_cloudems"}
        async with self._session.post(url, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                self._call_count += 1
                return [{**m, "source": "cloudems_cloud"} for m in data.get("matches", [])]
            elif resp.status == 402:
                _LOGGER.warning("CloudEMS API: subscription required — cloudems.eu/premium")
                self._available = False
        return []

    # ── OpenAI ────────────────────────────────────────────────────────────────

    async def _call_openai(self, delta_power, rise_time, context) -> List[Dict]:
        if not self._api_key:
            return []
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": _nilm_prompt(delta_power, rise_time, context)}],
            "max_tokens": 200, "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        async with self._session.post(OPENAI_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data   = await resp.json()
                text   = data["choices"][0]["message"]["content"].strip()
                result = json.loads(text)
                self._call_count += 1
                return [{**m, "source": "openai"} for m in result] if isinstance(result, list) else []
        return []

    # ── Anthropic ─────────────────────────────────────────────────────────────

    async def _call_anthropic(self, delta_power, rise_time, context) -> List[Dict]:
        if not self._api_key:
            return []
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": _nilm_prompt(delta_power, rise_time, context)}],
        }
        headers = {
            "x-api-key": self._api_key, "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VER,
        }
        async with self._session.post(ANTHROPIC_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data   = await resp.json()
                text   = data["content"][0]["text"].strip()
                result = json.loads(text)
                self._call_count += 1
                return [{**m, "source": "anthropic"} for m in result] if isinstance(result, list) else []
        return []

    # ── Ollama ────────────────────────────────────────────────────────────────

    async def _call_ollama(self, delta_power, rise_time, context) -> List[Dict]:
        url     = f"http://{self.ollama_host}:{self.ollama_port}/api/generate"
        payload = {
            "model":  self.ollama_model,
            "prompt": _nilm_prompt(delta_power, rise_time, context),
            "stream": False,
        }
        async with self._session.post(url, json=payload,
                                      timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data   = await resp.json()
                text   = data.get("response", "").strip()
                # Extract JSON array from response
                start  = text.find("[")
                end    = text.rfind("]") + 1
                if start >= 0 and end > start:
                    result = json.loads(text[start:end])
                    self._call_count += 1
                    return [{**m, "source": "ollama"} for m in result] if isinstance(result, list) else []
        return []
