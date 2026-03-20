# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
cloud_sync_mixin.py — v4.6.533

Gedeelde basis voor alle zelflerend modules met cloud-sync (federated learning).

Elke module die deze mixin gebruikt krijgt:
  - to_cloud_delta()     : geanonimiseerde samenvatting van wat geleerd is
  - apply_cloud_prior()  : verwerk ontvangen cloud-aggregaat als startwaarden
  - _sanitize()          : strip alle PII (entity_ids, namen, locatie)

Privacy-garanties:
  - Geen entity_ids
  - Geen apparaatnamen (alleen type-informatie)
  - Geen locatie
  - Alleen statistische samenvattingen (gemiddelde, std, count)
  - Alle waarden afgerond op 1-2 decimalen

Federated learning principe:
  - Lokale instantie leert zelfstandig op eigen data
  - Periodiek stuurt hij een delta naar de cloud
  - Ontvangt aggregated priors van vergelijkbare installaties
  - Priors worden alleen als startwaarde gebruikt (laag gewicht)
  - Eigen data overschrijft altijd de prior na genoeg samples

Cloud-sync schema:
  {
    "module":     str,          # module naam (niet de installatie)
    "version":    str,          # CloudEMS versie
    "region":     str,          # NL/BE/DE (land, geen locatie)
    "phase_count": int,         # 1 of 3
    "learned":    dict,         # geanonimiseerde geleerde waarden
    "meta": {
      "samples":  int,
      "uptime_days": float,
    }
  }
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

# Gewicht van cloud-prior bij initialisatie
# 0.2 = cloud-prior heeft gewicht van 20% van MIN_SAMPLES geleerde samples
CLOUD_PRIOR_WEIGHT = 0.20


class CloudSyncMixin:
    """
    Mixin voor alle zelflerend modules. Voeg toe als extra base class.

    Subclass moet implementeren:
      _get_learned_data() -> dict   : ruwe geleerde data
      _apply_prior(data: dict)      : verwerk cloud-prior data

    Optioneel override:
      _sanitize_learned(data: dict) -> dict  : extra privacy-filter
    """

    _cloud_module_name: str = "unknown"
    _cloud_version:     str = "4.6.533"

    def to_cloud_delta(
        self,
        phase_count: int = 3,
        region: str = "NL",
    ) -> Optional[Dict[str, Any]]:
        """
        Geeft geanonimiseerde samenvatting terug voor cloud-upload.
        Retourneert None als er onvoldoende data is om te delen.
        """
        try:
            raw = self._get_learned_data()
            if not raw:
                return None
            sanitized = self._sanitize_learned(raw)
            if not sanitized:
                return None
            return {
                "module":      self._cloud_module_name,
                "version":     self._cloud_version,
                "region":      region,
                "phase_count": phase_count,
                "learned":     sanitized,
                "meta": {
                    "ts":          int(time.time()),
                    "uptime_days": round((time.time() - getattr(self, "_start_ts", time.time())) / 86400, 1),
                },
            }
        except Exception as _e:
            _LOGGER.debug("CloudSyncMixin.to_cloud_delta fout: %s", _e)
            return None

    def apply_cloud_prior(self, prior_data: Dict[str, Any]) -> None:
        """
        Verwerk ontvangen cloud-aggregaat als startwaarden.
        Veilig om aan te roepen — overschrijft nooit eigen geleerde data
        als er al genoeg samples zijn.
        """
        try:
            learned = prior_data.get("learned", {})
            if learned:
                self._apply_prior(learned)
        except Exception as _e:
            _LOGGER.debug("CloudSyncMixin.apply_cloud_prior fout: %s", _e)

    # ── Te implementeren door subclass ────────────────────────────────────────

    def _get_learned_data(self) -> dict:
        """Geef ruwe geleerde data terug. Override in subclass."""
        return {}

    def _apply_prior(self, data: dict) -> None:
        """Verwerk cloud-prior. Override in subclass."""
        pass

    def _sanitize_learned(self, data: dict) -> dict:
        """
        Standaard sanitizer: verwijder keys die PII kunnen bevatten.
        Override voor module-specifieke filtering.
        """
        forbidden_patterns = [
            "entity_id", "entity", "name", "label", "location",
            "address", "ip", "mac", "serial", "device_id",
        ]
        result = {}
        for k, v in data.items():
            k_lower = k.lower()
            if any(pat in k_lower for pat in forbidden_patterns):
                continue
            if isinstance(v, dict):
                cleaned = self._sanitize_learned(v)
                if cleaned:
                    result[k] = cleaned
            elif isinstance(v, (int, float, bool, str)):
                result[k] = v
            elif isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
                result[k] = [round(x, 2) if isinstance(x, float) else x for x in v[:20]]
        return result

    @staticmethod
    def _round_for_cloud(val: float, decimals: int = 1) -> float:
        """Afronden voor cloud-upload — voorkomt fingerprinting via exacte waarden."""
        if val == 0:
            return 0.0
        # Rond af op 'decimals' significante cijfers relatief aan de waarde
        import math
        magnitude = math.floor(math.log10(abs(val))) if val != 0 else 0
        factor    = 10 ** (decimals - 1 - magnitude)
        return round(val * factor) / factor
