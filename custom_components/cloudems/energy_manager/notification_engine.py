# -*- coding: utf-8 -*-
"""
CloudEMS Smart Notification Engine — v1.0.0

Centraliseert alle CloudEMS-alerts en stuurt ze slim door via
Home Assistant's notificatiesysteem.

Probleem dat dit oplost:
  CloudEMS genereert tientallen inzichten per update-cyclus.
  Zonder deduplicatie zou elke 10s dezelfde melding opnieuw verstuurd worden.
  Gebruikers zouden het systeem uitzetten.

Oplossing:
  • Elke alert krijgt een unieke key (bijv. "pv_soiling:inv_123")
  • Per key: max 1 notificatie per COOLDOWN-periode
  • Drie prioriteitsklassen:
      CRITICAL  → direct + herinnering na 6u als niet opgelost
      WARNING   → 1× per dag
      INFO      → gebundeld in avonddigest (20:00)
  • HA persistent_notification altijd (zichtbaar in Lovelace sidebar)
  • Optioneel: notify.mobile_app_* als die is geconfigureerd
  • Gebruiker kan alert-key "dempen" via HA service

Sensor output:
  • cloudems_actieve_meldingen  → aantal openstaande alerts
  • Attributen: lijst van alle actieve alerts met prioriteit + tekst

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.components.persistent_notification import async_create

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_notifications_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 300

# Cooldown per prioriteit (seconden)
COOLDOWN = {
    "critical": 6 * 3600,    #  6 uur
    "warning":  24 * 3600,   # 24 uur
    "info":     24 * 3600,   # 24 uur (digest)
}

# Digest-uur: INFO-meldingen worden gebundeld verstuurd
DIGEST_HOUR = 20

# Stilteperiode: warning/info meldingen worden gebufferd tot buiten dit venster.
# Critical meldingen doorbreken altijd de stilteperiode.
QUIET_HOURS_DEFAULT_START = 22   # 22:00
QUIET_HOURS_DEFAULT_END   =  7   #  7:00

# Categorie → emoji
CATEGORY_EMOJI = {
    "pv":        "☀️",
    "battery":   "🔋",
    "gas":       "🔥",
    "appliance": "⚙️",
    "grid":      "⚡",
    "budget":    "💶",
    "mobility":  "🚗",
    "system":    "🤖",
}


@dataclass
class Alert:
    key:       str        # unieke ID, bijv. "pv_soiling:inv_dak"
    priority:  str        # "critical" | "warning" | "info"
    category:  str        # "pv" | "battery" | "gas" | ...
    title:     str
    message:   str
    first_seen_ts: float  = field(default_factory=time.time)
    last_sent_ts:  float  = 0.0
    resolved:      bool   = False
    muted:         bool   = False
    send_count:    int    = 0

    def to_dict(self) -> dict:
        return {
            "key": self.key, "priority": self.priority,
            "category": self.category, "title": self.title,
            "message": self.message, "first_seen_ts": self.first_seen_ts,
            "last_sent_ts": self.last_sent_ts, "resolved": self.resolved,
            "muted": self.muted, "send_count": self.send_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class NotificationEngine:
    """
    Centraliseert en dedupliceert alle CloudEMS-notificaties.

    Gebruik vanuit coordinator (elke update-cyclus):
        engine.ingest(alerts_dict)   ← roep aan met all active alerts
        await engine.async_dispatch() ← stuurt nieuwe meldingen door
        data = engine.get_data()     ← voor sensor

    alerts_dict formaat:
        {
          "pv_soiling:dak": {
            "priority": "warning",
            "category": "pv",
            "title": "PV-panelen mogelijk vuil",
            "message": "Omvormer Dak produceert 18% minder dan normaal.",
            "active": True,    ← False = alert opgelost
          },
          ...
        }
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass    = hass
        self._config = config
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._alerts: dict[str, Alert] = {}
        self._muted:  set[str]         = set()
        self._dirty   = False
        self._last_save   = 0.0
        self._last_digest = 0.0

        # Optionele mobiele notificatie service
        self._notify_service = config.get("notification_service", "")
        # Stilteperiode — aanpasbaar via update_quiet_hours()
        self._quiet_start: int = config.get("quiet_hours_start", QUIET_HOURS_DEFAULT_START)
        self._quiet_end:   int = config.get("quiet_hours_end",   QUIET_HOURS_DEFAULT_END)
        self._quiet_enabled: bool = config.get("quiet_hours_enabled", True)

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for d in saved.get("alerts", []):
            try:
                a = Alert.from_dict(d)
                self._alerts[a.key] = a
            except Exception:
                pass
        self._muted = set(saved.get("muted", []))
        _LOGGER.info(
            "NotificationEngine: %d alerts hersteld, %d gedempt",
            len(self._alerts), len(self._muted),
        )

    # ── Hoofd-interface ───────────────────────────────────────────────────────

    def ingest(self, alerts_dict: dict[str, dict]) -> None:
        """
        Verwerk de huidige set actieve/inactieve alerts.
        Aanroepen elke coordinator-cyclus.
        """
        seen_keys = set()
        for key, spec in alerts_dict.items():
            seen_keys.add(key)
            active = spec.get("active", True)

            if key not in self._alerts:
                self._alerts[key] = Alert(
                    key      = key,
                    priority = spec.get("priority", "info"),
                    category = spec.get("category", "system"),
                    title    = spec.get("title", key),
                    message  = spec.get("message", ""),
                )
                self._dirty = True
            else:
                a = self._alerts[key]
                a.resolved = not active
                # Update bericht (kan veranderen bij dynamische data)
                if a.message != spec.get("message", ""):
                    a.message = spec.get("message", "")
                    self._dirty = True

        # Markeer verdwenen keys als opgelost
        for key in list(self._alerts.keys()):
            if key not in seen_keys:
                self._alerts[key].resolved = True

    def update_quiet_hours(
        self,
        start: int,
        end: int,
        enabled: bool = True,
    ) -> None:
        """Pas stilteperiode aan vanuit options flow of service call."""
        self._quiet_start   = start
        self._quiet_end     = end
        self._quiet_enabled = enabled

    def _is_quiet_time(self) -> bool:
        """True als het momenteel binnen de stilteperiode valt."""
        if not self._quiet_enabled:
            return False
        h = datetime.now(timezone.utc).hour
        if self._quiet_start > self._quiet_end:
            # Stilteperiode loopt over middernacht: bijv. 22:00–07:00
            return h >= self._quiet_start or h < self._quiet_end
        else:
            return self._quiet_start <= h < self._quiet_end

    async def async_dispatch(self) -> None:
        """Stuur nieuwe/herhaalde notificaties door. Aanroepen elke coordinator-cyclus."""
        now = time.time()
        dt  = datetime.now(timezone.utc)

        to_send_critical: list[Alert] = []
        to_send_warning:  list[Alert] = []
        to_send_info:     list[Alert] = []

        for a in self._alerts.values():
            if a.resolved or a.muted or a.key in self._muted:
                continue
            cooldown = COOLDOWN.get(a.priority, 86400)
            if now - a.last_sent_ts < cooldown:
                continue

            if a.priority == "critical":
                to_send_critical.append(a)
            elif a.priority == "warning":
                to_send_warning.append(a)
            else:
                to_send_info.append(a)

        # Critical: altijd direct sturen — doorbreekt stilteperiode
        for a in to_send_critical:
            await self._send(a)

        # Warning/info: gebufferd tijdens stilteperiode
        in_quiet = self._is_quiet_time()
        if in_quiet:
            _LOGGER.debug(
                "NotificationEngine: stilteperiode actief (%02d:00–%02d:00) — "
                "%d warning + %d info meldingen gebufferd",
                self._quiet_start, self._quiet_end,
                len(to_send_warning), len(to_send_info),
            )
        else:
            for a in to_send_warning:
                await self._send(a)

        # Info: digest bundelen op DIGEST_HOUR
        if to_send_info and dt.hour == DIGEST_HOUR and now - self._last_digest > 3600:
            await self._send_digest(to_send_info)
            self._last_digest = now

        if to_send_critical or to_send_warning or (to_send_info and dt.hour == DIGEST_HOUR):
            self._dirty = True

    async def _send(self, alert: Alert) -> None:
        emoji = CATEGORY_EMOJI.get(alert.category, "ℹ️")
        notification_id = f"cloudems_{alert.key.replace(':', '_')}"
        title   = f"{emoji} CloudEMS — {alert.title}"
        message = alert.message

        # Altijd persistent notification
        try:
            async_create(
                self.hass,
                message   = message,
                title     = title,
                notification_id = notification_id,
            )
        except Exception as err:
            _LOGGER.warning("NotificationEngine: persistent_notification fout: %s", err)

        # Optioneel mobiele push
        if self._notify_service:
            try:
                await self.hass.services.async_call(
                    "notify", self._notify_service,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception as err:
                _LOGGER.debug("NotificationEngine: mobiele notificatie mislukt: %s", err)

        alert.last_sent_ts  = time.time()
        alert.send_count   += 1
        _LOGGER.info("CloudEMS notificatie verstuurd [%s]: %s", alert.priority, alert.title)

    async def send_daily_learning_report(self, report: dict) -> None:
        """
        Stuur het dagelijkse leerrapport als persistent_notification.
        Aanroepen vanuit coordinator rond 20:00 of bij day-rollover.
        """
        lines = ["## ☀️ CloudEMS Dagelijks Leerrapport", ""]

        # PV oriëntatie
        for inv in report.get("orientation_progress", []):
            pct   = inv.get("pct", 0)
            label = inv.get("label", "?")
            have  = inv.get("samples", 0)
            need  = inv.get("needed", 1800)
            icon  = "✅" if inv.get("confident") else ("🟡" if pct >= 50 else "🔴")
            lines.append(f"- {icon} **{label}**: oriëntatie {pct}% ({have}/{need} zonneminuten)")

        # Fase leren
        for inv in report.get("phase_progress", []):
            label = inv.get("label", "?")
            phase = inv.get("phase")
            certain = inv.get("certain", False)
            if certain and phase:
                lines.append(f"- ✅ **{label}**: fase {phase} bevestigd")
            elif phase:
                conf = inv.get("confidence", 0)
                lines.append(f"- 🔍 **{label}**: fase ~{phase} ({conf:.0f}% betrouwbaar)")

        # Vandaag geleerde zonneminuten
        samples_today = report.get("samples_today", 0)
        if samples_today:
            lines.append(f"- ☀️ Vandaag **{samples_today}** nieuwe zonneminuten geleerd")

        # Thermisch model
        thermal = report.get("thermal_samples", 0)
        if thermal:
            lines.append(f"- 🏠 Thermisch model: {thermal} metingen bijgewerkt")

        lines.append("")
        lines.append("*CloudEMS leert elke dag automatisch — prognoses worden steeds nauwkeuriger.*")

        msg = "\n".join(lines)
        try:
            async_create(
                self._hass,
                message         = msg,
                title           = "☀️ CloudEMS Leerrapport",
                notification_id = "cloudems_learning_report",
            )
        except Exception as exc:
            _LOGGER.debug("LearningReport sturen mislukt: %s", exc)

    async def _send_digest(self, alerts: list[Alert]) -> None:
        if not alerts:
            return
        lines = [f"**Dagelijkse CloudEMS samenvatting** ({len(alerts)} meldingen)\n"]
        for a in alerts:
            emoji = CATEGORY_EMOJI.get(a.category, "ℹ️")
            lines.append(f"{emoji} **{a.title}**")
            lines.append(f"  {a.message}\n")
        message = "\n".join(lines)

        try:
            async_create(
                self.hass,
                message   = message,
                title     = "☀️ CloudEMS Dagdigest",
                notification_id = "cloudems_digest",
            )
        except Exception as err:
            _LOGGER.warning("NotificationEngine: digest fout: %s", err)

        for a in alerts:
            a.last_sent_ts  = time.time()
            a.send_count   += 1

    # ── Muting ────────────────────────────────────────────────────────────────

    def mute(self, key: str) -> None:
        """Demp een alert-key (blijft gedempt tot handmatig herstel)."""
        self._muted.add(key)
        if key in self._alerts:
            self._alerts[key].muted = True
        self._dirty = True
        _LOGGER.info("NotificationEngine: alert gedempt — %s", key)

    def unmute(self, key: str) -> None:
        self._muted.discard(key)
        if key in self._alerts:
            self._alerts[key].muted = False
        self._dirty = True

    # ── Sensor data ───────────────────────────────────────────────────────────

    def get_data(self) -> dict:
        active = [
            a for a in self._alerts.values()
            if not a.resolved and not a.muted and a.key not in self._muted
        ]
        critical = [a for a in active if a.priority == "critical"]
        warnings = [a for a in active if a.priority == "warning"]
        info_    = [a for a in active if a.priority == "info"]

        return {
            "active_count":    len(active),
            "critical_count":  len(critical),
            "warning_count":   len(warnings),
            "info_count":      len(info_),
            "muted_count":     len(self._muted),
            "active_alerts": [
                {
                    "key":      a.key,
                    "priority": a.priority,
                    "category": a.category,
                    "title":    a.title,
                    "message":  a.message,
                    "age_h":    round((time.time() - a.first_seen_ts) / 3600, 1),
                }
                for a in sorted(active, key=lambda x: (
                    {"critical": 0, "warning": 1, "info": 2}.get(x.priority, 3)
                ))
            ],
        }

    # ── Helpers: alert-builders voor coordinator ──────────────────────────────

    @staticmethod
    def build_alerts_from_coordinator_data(data: dict) -> dict[str, dict]:
        """
        Extraheert alle alerts uit coordinator-data en geeft een alerts_dict terug
        die direct aan ingest() meegegeven kan worden.
        """
        alerts: dict[str, dict] = {}

        # PV-paneelgezondheid
        pv_h = data.get("pv_health", {})
        for inv in pv_h.get("inverters", []):
            key = f"pv_health:{inv.get('inverter_id', 'unknown')}"
            if inv.get("alert_type") in ("soiling", "degradation"):
                alerts[key] = {
                    "priority": "warning",
                    "category": "pv",
                    "title":    f"PV {inv.get('alert_type', 'probleem')}: {inv.get('label', '')}",
                    "message":  inv.get("advice", "Controleer panelen."),
                    "active":   True,
                }

        # Apparaat-efficiëntiedrift
        drift = data.get("device_drift", {})
        for dev in drift.get("devices", []):
            level = dev.get("level", "ok")
            # Only process devices with a frozen baseline (enough history)
            if not dev.get("baseline_frozen", False):
                continue
            key = f"device_drift:{dev.get('device_id', 'unknown')}"
            if level in ("warning", "alert"):
                alerts[key] = {
                    "priority": "warning" if level == "warning" else "critical",
                    "category": "appliance",
                    "title":    f"Apparaat efficiëntiedrift: {dev.get('label', '')}",
                    "message":  (
                        f"{dev.get('label','')} verbruikt {dev.get('drift_pct',0):.0f}% "
                        f"{'meer' if dev.get('drift_pct',0) > 0 else 'minder'} dan normaal. "
                        "Controleer het apparaat op defecten."
                    ),
                    "active": True,
                }
            else:
                # Niveau terug naar "ok" → zet alert expliciet op inactief zodat
                # de melding meteen verdwijnt i.p.v. te wachten tot de key uit
                # seen_keys valt.
                alerts[key] = {
                    "priority": "info",
                    "category": "appliance",
                    "title":    f"Apparaat efficiëntiedrift: {dev.get('label', '')}",
                    "message":  "",
                    "active":   False,
                }

        # Gas anomalie
        gas = data.get("gas_analysis", {})
        if gas.get("anomaly"):
            alerts["gas_anomaly"] = {
                "priority": "warning",
                "category": "gas",
                "title":    "Ongewoon hoog gasverbruik",
                "message":  gas.get("anomaly_message", "Gasverbruik is significant hoger dan normaal."),
                "active":   True,
            }

        # Budget overschrijding
        budget = data.get("budget", {})
        if budget.get("overall_status") == "overschrijding":
            alerts["budget_overschrijding"] = {
                "priority": "warning",
                "category": "budget",
                "title":    "Energiebudget dreigt overschreden",
                "message":  budget.get("summary", "Budget nadert limiet."),
                "active":   True,
            }

        # Clipping verlies
        clipping = data.get("clipping_loss", {})
        if clipping.get("annual_loss_eur", 0) > 50:
            alerts["clipping_loss"] = {
                "priority": "info",
                "category": "pv",
                "title":    "Clipping verlies gedetecteerd",
                "message":  clipping.get("advice", ""),
                "active":   True,
            }

        # Batterij gezondheid
        batt = data.get("battery_state_of_health", {})
        if batt.get("alert_level") == "critical":
            alerts["battery_soh_critical"] = {
                "priority": "critical",
                "category": "battery",
                "title":    "Batterij kritiek: lage SoH",
                "message":  batt.get("alert_message", ""),
                "active":   True,
            }
        elif batt.get("alert_level") == "warn":
            alerts["battery_soh_warn"] = {
                "priority": "warning",
                "category": "battery",
                "title":    "Batterij gezondheid daalt",
                "message":  batt.get("alert_message", ""),
                "active":   True,
            }

        # Verbruiksanomalie
        baseline = data.get("home_baseline", {})
        if data.get("anomaly_detected"):
            alerts["consumption_anomaly"] = {
                "priority": "info",
                "category": "grid",
                "title":    "Ongewoon verbruikspatroon",
                "message":  (
                    f"Huidig verbruik {baseline.get('current_w',0):.0f}W — "
                    f"{baseline.get('deviation_w',0):.0f}W boven verwacht "
                    f"({baseline.get('expected_w',0):.0f}W)."
                ),
                "active":   True,
            }

        # Hoge energieprijs (per uur alert)
        price_info = data.get("energy_price", {})
        current_price = price_info.get("current")
        price_alert_thr = data.get("config_price_alert_high", 0.30)
        if current_price and current_price > price_alert_thr:
            alerts["price_alert_high"] = {
                "priority": "warning",
                "category": "price",
                "title":    f"Hoge energieprijs: {current_price:.4f} €/kWh",
                "message":  (
                    f"Huidige prijs {current_price:.4f} €/kWh overschrijdt de ingestelde drempel "
                    f"van {price_alert_thr:.2f} €/kWh. Overweeg zware lasten uit te schakelen."
                ),
                "active":   True,
            }
        elif "price_alert_high" in alerts:
            # Price has dropped below threshold — deactivate
            alerts["price_alert_high"]["active"] = False

        # PV terugverdientijd informatief bericht (1× inzicht)
        pv_pay = data.get("pv_payback", {})
        if pv_pay.get("payback_years") and pv_pay.get("investment_eur", 0) > 0:
            yrs = pv_pay["payback_years"]
            rev = pv_pay.get("annual_revenue_eur", 0)
            wp  = pv_pay.get("total_wp_est", 0)
            alerts["pv_payback_info"] = {
                "priority": "info",
                "category": "pv",
                "title":    f"PV terugverdientijd: {yrs} jaar",
                "message":  (
                    f"Geschatte jaaropbrengst €{rev:.0f} op basis van {wp:.0f} Wp geleerd vermogen. "
                    f"Investering van €{pv_pay['investment_eur']:.0f} terugverdiend in ~{yrs} jaar. "
                    f"10-jaar ROI: {pv_pay.get('roi_10y_pct', 0):.0f}%."
                ),
                "active": True,
            }

        # Fase-conflict alerts (cross-validatie solar_learner)
        for conflict in data.get("phase_conflict_alerts", []):
            key = f"phase_conflict:{conflict.get('inverter_id', 'unknown')}"
            alerts[key] = {
                "priority": "warning",
                "category": "pv",
                "title":    f"Fase-conflict: {conflict.get('label', '')}",
                "message":  (
                    f"Omvormer {conflict.get('label','')} is bevestigd op fase "
                    f"{conflict.get('detected_phase','?')}, maar {conflict.get('conflict_pct',0):.0f}% "
                    f"van recente metingen wijst naar een andere fase. "
                    f"CloudEMS herstart het leerproces automatisch. "
                    f"Controleer de bekabeling als dit herhaaldelijk voorkomt "
                    f"(herstart #{conflict.get('relearn_events', 0)})."
                ),
                "active": True,
            }

        # Nieuwe-panelen-detectie alerts
        for reset in data.get("new_panel_resets", []):
            key = f"new_panels:{reset.get('inverter_id', 'unknown')}"
            alerts[key] = {
                "priority": "info",
                "category": "pv",
                "title":    f"Nieuwe panelen gedetecteerd: {reset.get('label', '')}",
                "message":  (
                    f"Vermogen van {reset.get('label','')} overschreed herhaaldelijk "
                    f"het geleerde piekvermogen (reset #{reset.get('reset_count', 1)}). "
                    f"CloudEMS leert automatisch het nieuwe piekvermogen."
                ),
                "active": True,
            }

        # Stroomuitval
        if data.get("outage_detected"):
            alerts["power_outage"] = {
                "priority": "critical",
                "category": "system",
                "title":    "Mogelijke stroomstoring",
                "message":  data.get("outage_message", "Geen PV- of netverbruik gedetecteerd overdag."),
                "active":   True,
            }
        elif "power_outage" in alerts:
            alerts["power_outage"]["active"] = False

        # Warmtepomp COP degradatie
        hp_cop = data.get("heat_pump_cop", {})
        if hp_cop.get("degradation_detected"):
            alerts["hp_cop_degradation"] = {
                "priority": "warning",
                "category": "appliance",
                "title":    "Warmtepomp efficiëntie gedaald",
                "message":  hp_cop.get("degradation_advice", "COP is gedaald. Overweeg onderhoud."),
                "active":   True,
            }
        elif "hp_cop_degradation" in alerts:
            alerts["hp_cop_degradation"]["active"] = False

        # Isolatie-investering — geen resultaat
        gas = data.get("gas_analysis", {})
        iso_advice = gas.get("isolation_advice", "")
        if "⚠️ Isolatie" in iso_advice and "gestegen" in iso_advice:
            alerts["isolation_no_effect"] = {
                "priority": "warning",
                "category": "gas",
                "title":    "Isolatie: geen verbruiksdaling",
                "message":  iso_advice,
                "active":   True,
            }

        return alerts

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "alerts": [a.to_dict() for a in self._alerts.values()],
                "muted":  list(self._muted),
            })
            self._dirty     = False
            self._last_save = time.time()
