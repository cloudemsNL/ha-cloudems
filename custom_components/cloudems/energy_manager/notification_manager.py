"""
CloudEMS — NotificationManager v1.0.0

Centrale notificatiemodule. Verstuurt berichten via:
  1. Geconfigureerde notify-service (bijv. notify.mobile_app_telefoon)
  2. Auto-discovered mobile_app services (alle mobile_app_* services)
  3. Fallback: persistent_notification in HA frontend

Gebruik:
    nm = NotificationManager(hass, config)
    await nm.send("Titel", "Bericht", category="boiler")

Config (cloudems yaml / opties):
    notify_services: ["notify.mobile_app_telefoon"]  # optioneel, auto-discover als leeg
    notify_categories:                                # welke categorieën wil je ontvangen
        boiler: true
        smart_delay: true
        solar: true
        energy_report: true
        legionella: true
        alert: true       # altijd aan, niet uit te zetten

Copyright © 2025 CloudEMS
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Categorieën die de gebruiker aan/uit kan zetten
NOTIFY_CATEGORIES = [
    "boiler",
    "smart_delay",
    "solar",
    "energy_report",
    "legionella",
]
# 'alert' is altijd aan (fouten, kritieke events)

# Anti-spam: minimale tijd tussen twee berichten van dezelfde categorie + titel (seconden)
SPAM_COOLDOWN_S = 3600  # 1 uur default

# v5.5.521: per-categorie cooldowns
# Informatieve meldingen maximaal 1x per dag, alerts direct maar niet herhalen
CATEGORY_COOLDOWNS: dict = {
    "alert":        3600,    # 1 uur — urgent maar niet elke cyclus
    "phase":        86400,   # 1x per dag — fase-onbalans is structureel
    "diagnostics":  86400,   # 1x per dag — zelf-diagnose
    "forecast":     86400,   # 1x per dag — PV forecast afwijking
    "sensor":       86400,   # 1x per dag — sensor fout
    "battery":      3600,    # 1 uur — accu-temperatuur etc.
    "boiler":       7200,    # 2 uur
    "ev":           3600,    # 1 uur
    "info":         86400,   # 1x per dag
    "tip":          604800,  # 1x per week — optimalisatie tips
    "weekly":       604800,  # 1x per week — wekelijkse rapport
}


class NotificationManager:
    """Centrale notificatiemanager voor CloudEMS."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._spam: dict[str, float] = {}  # key → last_sent_ts
        self._discovered_services: list[str] = []
        self._last_discover: float = 0.0
        # v5.5.522: persisteer spam-timestamps zodat herstart cooldown respecteert
        try:
            from homeassistant.helpers.storage import Store
            self._store = Store(hass, 1, "cloudems_notification_cooldowns_v1")
            hass.async_create_task(self._async_load())
        except Exception:
            self._store = None

    async def _async_load(self) -> None:
        """Laad opgeslagen cooldown-timestamps na (her)start."""
        try:
            saved = await self._store.async_load() if self._store else None
            if saved and isinstance(saved.get("spam"), dict):
                import time as _t
                now = _t.time()
                # Gooi verlopen entries weg (ouder dan langste cooldown = 1 week)
                self._spam = {
                    k: v for k, v in saved["spam"].items()
                    if now - v < 604800
                }
        except Exception:
            pass

    async def _async_save(self) -> None:
        """Sla huidige cooldown-timestamps op."""
        try:
            if self._store:
                await self._store.async_save({"spam": dict(self._spam)})
        except Exception:
            pass

    # ── Publieke API ────────────────────────────────────────────────────────

    async def send(
        self,
        title: str,
        message: str,
        category: str = "alert",
        notification_id: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Stuur een notificatie. Wordt genegeerd als categorie uitstaat of spam-cooldown actief."""
        if not self._category_enabled(category) and not force:
            return
        spam_key = f"{category}:{notification_id or title}"
        now = time.time()
        cooldown = CATEGORY_COOLDOWNS.get(category, SPAM_COOLDOWN_S)
        if not force and now - self._spam.get(spam_key, 0) < cooldown:
            _LOGGER.debug("NotificationManager: cooldown actief voor '%s' (nog %.0fs)",
                          spam_key, cooldown - (now - self._spam.get(spam_key, 0)))
            return
        self._spam[spam_key] = now
        # Persisteer zodat herstart de cooldown respecteert
        self._hass.async_create_task(self._async_save())

        services = await self._get_notify_services()

        sent = False
        for svc in services:
            try:
                domain, service_name = svc.split(".", 1)
                await self._hass.services.async_call(
                    domain, service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
                _LOGGER.info("NotificationManager: '%s' verstuurd via %s", title, svc)
                sent = True
            except Exception as exc:
                _LOGGER.warning("NotificationManager: fout bij %s: %s", svc, exc)

        # Altijd persistent_notification als fallback (of extra)
        nid = notification_id or f"cloudems_{category}_{abs(hash(title)) % 100000}"
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": title, "message": message, "notification_id": nid},
                blocking=False,
            )
            if not sent:
                _LOGGER.info("NotificationManager: '%s' via persistent_notification", title)
        except Exception:
            pass

    async def dismiss(self, notification_id: str) -> None:
        """Verwijder een persistent_notification."""
        try:
            await self._hass.services.async_call(
                "persistent_notification", "dismiss",
                {"notification_id": notification_id},
                blocking=False,
            )
        except Exception:
            pass

    # ── Interne hulpfuncties ────────────────────────────────────────────────

    def _category_enabled(self, category: str) -> bool:
        if category == "alert":
            return True
        cats = self._config.get("notify_categories", {})
        # Default: alle categorieën aan tenzij expliciet uitgeschakeld
        return bool(cats.get(category, True))

    async def _get_notify_services(self) -> list[str]:
        """Geeft geconfigureerde of auto-discovered notify-services terug."""
        # 1. Expliciet geconfigureerd
        configured = self._config.get("notify_services") or []
        if configured:
            return [s for s in configured if s]

        # 2. Auto-discover (cache 5 minuten)
        now = time.time()
        if now - self._last_discover > 300 or not self._discovered_services:
            self._discovered_services = await self._discover_mobile_services()
            self._last_discover = now

        return self._discovered_services

    async def _discover_mobile_services(self) -> list[str]:
        """Zoek automatisch alle mobile_app_* notify services op."""
        try:
            all_services = self._hass.services.async_services()
            notify_svcs  = all_services.get("notify", {})
            mobile = [
                f"notify.{svc}"
                for svc in notify_svcs
                if svc.startswith("mobile_app_")
            ]
            if mobile:
                _LOGGER.info(
                    "NotificationManager: %d mobile_app service(s) gevonden: %s",
                    len(mobile), ", ".join(mobile),
                )
            else:
                _LOGGER.debug(
                    "NotificationManager: geen mobile_app services gevonden — "
                    "alleen persistent_notification"
                )
            return mobile
        except Exception as exc:
            _LOGGER.warning("NotificationManager: discover fout: %s", exc)
            return []

    @staticmethod
    def config_schema_defaults() -> dict:
        """Standaard config-waarden voor gebruik in config_flow."""
        return {
            "notify_services":   [],
            "notify_categories": {cat: True for cat in NOTIFY_CATEGORIES},
        }
