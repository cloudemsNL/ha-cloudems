# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""Hoofd NILM Analyzer - combineert database, lokale AI en cloud AI."""
from __future__ import annotations
import logging
from typing import Any

from .database import NILMDatabase
from .local_ai import LocalAIClassifier
from .cloud_ai import CloudAIClassifier

_LOGGER = logging.getLogger(__name__)


class NILMAnalyzer:
    """
    CloudEMS NILM Analyzer.

    Volgorde van analyse:
    1. Interne database (snelste, offline)
    2. Lokale AI (scikit-learn, geen internet nodig)
    3. Cloud AI (nauwkeurigste, internet vereist, abonnement)
    """

    def __init__(
        self,
        cloud_ai=None,
        confidence_threshold: float = 0.75,
        enable_local_ai: bool = True,
        enable_cloud_ai: bool = True,
    ) -> None:
        self._database = NILMDatabase()
        self._local_ai = LocalAIClassifier(model_path="")
        self._cloud_ai = cloud_ai
        self._confidence_threshold = confidence_threshold
        self._enable_local_ai = enable_local_ai
        self._enable_cloud_ai = enable_cloud_ai

        _LOGGER.info(
            "CloudEMS NILM gestart: %d apparaten in database",
            self._database.device_count
        )

    async def process_power_reading(self, power_watt: float, power_factor: float = 0.95):
        if self._enable_local_ai:
            events = self._local_ai.update_power(power_watt, power_factor)
            if self._enable_cloud_ai and self._cloud_ai and events:
                for event in events:
                    low_conf = [d for d in self._local_ai.get_learned_devices()
                                if d.probability < self._confidence_threshold and not d.confirmed]
                    if low_conf:
                        await self._enhance_with_cloud(event)
        return self.get_active_devices()

    async def _enhance_with_cloud(self, event) -> None:
        if not self._cloud_ai or not self._cloud_ai.is_available:
            return
        result = await self._cloud_ai.classify_event(
            power_delta=event.power_delta, rise_time=event.rise_time,
            power_factor=event.power_factor, power_before=event.power_before,
            power_after=event.power_after,
        )
        if result and result.get("confidence", 0) > self._confidence_threshold:
            _LOGGER.info("CloudEMS Cloud AI: %s (%.0f%%)", result.get("device_name"), result.get("confidence", 0) * 100)

    def get_active_devices(self):
        return self._local_ai.get_learned_devices()

    def get_confirmed_devices(self):
        return [d for d in self.get_active_devices() if d.confirmed]

    def get_pending_devices(self):
        return [d for d in self.get_active_devices()
                if not d.confirmed and d.probability >= self._confidence_threshold]

    def confirm_device(self, unique_id: str, name=None) -> bool:
        return self._local_ai.confirm_device(unique_id, name)

    def reset(self) -> None:
        self._local_ai.reset()

    def get_full_stats(self) -> dict:
        return {
            "database": {"device_count": self._database.device_count},
            "local_ai": self._local_ai.get_stats(),
            "cloud_ai": self._cloud_ai.get_stats() if self._cloud_ai else {"available": False},
            "confidence_threshold": self._confidence_threshold,
        }
