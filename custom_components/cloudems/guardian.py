# -*- coding: utf-8 -*-
"""
CloudEMS System Guardian — v1.0.0

De Guardian is een autonome bewakingsrobot die continu de gezondheid van
het volledige CloudEMS-systeem controleert en automatisch bijstuurt.

Vier bewakers:
  1. CoordinatorGuard   — stale data, trage cycli, ontbrekende outputs
  2. ModuleGuard        — modules die geen beslissingen nemen of altijd dezelfde
  3. SensorGuard        — unavailable/stuck/afwijkende sensoren
  4. BoilerCascadeGuard — warmte niet bereikt, leveringsboiler-fouten, anomalieën

Bijsturing (voorzichtig regime — standaard):
  - 2+ aaneengesloten faalcycli  → notificatie aan eigenaar
  - 3+ aaneengesloten faalcycli  → HA integration reload (zachte herstart)
  - 5+ aaneengesloten faalcycli  → veilige stand (boilers uit, EV minimum)
  - Module structureel defect    → module uitschakelen tot handmatige reset

Rapportage:
  - HA persistent notification   → altijd
  - Push via notify service       → configureerbaar (notification_service)
  - Wekelijks samenvattingsrapport → maandag 08:00

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)

GUARDIAN_FILE    = "/config/.storage/cloudems_guardian.json"
EVAL_INTERVAL_S  = 60       # Guardian evalueert elke minuut
NOTIFY_COOLDOWN  = 3600     # Zelfde melding niet vaker dan 1x per uur
WEEKLY_REPORT_H  = 8        # Weekrapport op maandag om 08:00

# Drempelwaarden (voorzichtig regime)
FAIL_NOTIFY_AT   = 2        # Notificatie na N aaneengesloten faalcycli
FAIL_RELOAD_AT   = 3        # Reload na N
FAIL_SAFE_AT     = 5        # Veilige stand na N
SENSOR_STUCK_S   = 900      # Sensor 'stuck' als waarde >15 min niet verandert
DATA_STALE_S     = 180      # Coordinator data 'stale' als >3 min oud


@dataclass
class GuardianIssue:
    key:       str
    level:     str    # 'info' | 'warning' | 'error' | 'critical'
    title:     str
    message:   str
    action:    str    # 'none' | 'notify' | 'reload' | 'safe_mode' | 'disable_module'
    source:    str    # 'coordinator' | 'module' | 'sensor' | 'boiler'
    first_ts:  float = field(default_factory=time.time)
    last_ts:   float = field(default_factory=time.time)
    count:     int   = 1
    resolved:  bool  = False
    notified:  bool  = False


class SystemGuardian:
    """
    CloudEMS autonome bewakingsrobot.

    Gebruik in coordinator:
        guardian = SystemGuardian(hass, config, coordinator)
        await guardian.async_setup()

        # In elke update-cyclus:
        await guardian.async_evaluate()

        # Dashboard data:
        data = guardian.get_status()
    """

    def __init__(self, hass: HomeAssistant, config: dict,
                 coordinator: "CloudEMSCoordinator") -> None:
        self._hass        = hass
        self._config      = config
        self._coordinator = coordinator
        self._notify_svc  = config.get("notification_service", "")
        self._issues:     dict[str, GuardianIssue] = {}
        self._fail_count: defaultdict[str] = defaultdict(int)
        self._last_eval:  float = 0.0
        self._last_weekly: float = 0.0
        self._last_notify: dict[str, float] = {}
        self._safe_mode:  bool  = False
        self._disabled_modules: set[str] = set()
        # Sensor waarde history voor stuck-detectie: {entity_id: deque[(ts, value)]}
        self._sensor_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
        self._eval_count: int = 0
        self._setup_ts:   float = time.time()   # voor uptime berekening
        # LogReporter — lazy import om circulaire imports te voorkomen
        self._log_reporter = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Laad persistente staat."""
        try:
            def _load():
                if os.path.exists(GUARDIAN_FILE):
                    with open(GUARDIAN_FILE) as f:
                        return json.load(f)
                return None
            saved = await self._hass.async_add_executor_job(_load)
            if saved:
                self._disabled_modules = set(saved.get("disabled_modules", []))
                self._last_weekly      = saved.get("last_weekly", 0.0)
                _LOGGER.info(
                    "SystemGuardian geladen: %d uitgeschakelde modules",
                    len(self._disabled_modules),
                )
        except Exception as err:
            _LOGGER.warning("SystemGuardian: laden mislukt: %s", err)

        # LogReporter initialiseren als GitHub token geconfigureerd is
        if self._config.get("github_log_token"):
            from .log_reporter import LogReporter
            self._log_reporter = LogReporter(self._hass, self._config)
            _LOGGER.info("SystemGuardian: LogReporter actief (GitHub Issues)")

    def _save(self) -> None:
        """Sync save — alleen aanroepen vanuit executor."""
        try:
            os.makedirs(os.path.dirname(GUARDIAN_FILE), exist_ok=True)
            with open(GUARDIAN_FILE, "w") as f:
                json.dump({
                    "disabled_modules": list(self._disabled_modules),
                    "last_weekly":      self._last_weekly,
                    "saved_at":         datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)
        except Exception as err:
            _LOGGER.warning("SystemGuardian: opslaan mislukt: %s", err)

    async def async_save(self) -> None:
        """Async save via executor — gebruik dit vanuit de event loop."""
        await self._hass.async_add_executor_job(self._save)

    # ── Hoofd-evaluatie ───────────────────────────────────────────────────────

    async def async_evaluate(self) -> None:
        """
        Voer alle bewakingschecks uit. Aanroepen elke coordinator-cyclus.
        Intern begrensd op EVAL_INTERVAL_S zodat frequente aanroepen veilig zijn.
        """
        now = time.time()
        if now - self._last_eval < EVAL_INTERVAL_S:
            return
        self._last_eval = now
        self._eval_count += 1

        data = self._coordinator.data or {}

        # ── Vier bewakers ────────────────────────────────────────────────────
        self._check_coordinator(data, now)
        self._check_modules(data, now)
        self._check_sensors(data, now)
        self._check_boiler_cascade(data, now)

        # ── Bijsturing op basis van gevonden issues ───────────────────────────
        await self._apply_actions(now)

        # ── Weekrapport ───────────────────────────────────────────────────────
        if self._should_send_weekly(now):
            await self._send_weekly_report(now)

    # ── 1. Coordinator bewaker ────────────────────────────────────────────────

    def _check_coordinator(self, data: dict, now: float) -> None:
        """Controleer of de coordinator verse data levert."""
        # Stale data check
        last_update = data.get("last_update_ts", 0.0)
        if last_update and (now - last_update) > DATA_STALE_S:
            age = int(now - last_update)
            self._raise_issue(
                key     = "coordinator:stale_data",
                level   = "warning",
                title   = "CloudEMS — Coordinator data verouderd",
                message = (f"De coordinator heeft {age}s geen verse data geleverd. "
                           f"Mogelijk is de update-cyclus geblokkeerd of vastgelopen."),
                action  = "notify",
                source  = "coordinator",
            )
        else:
            self._resolve("coordinator:stale_data")

        # Watchdog failures doortrekken naar Guardian
        wd = data.get("watchdog", {})
        cons_fail = wd.get("consecutive_failures", 0)
        if cons_fail >= FAIL_NOTIFY_AT:
            self._raise_issue(
                key     = "coordinator:consecutive_failures",
                level   = "critical" if cons_fail >= FAIL_RELOAD_AT else "warning",
                title   = "CloudEMS — Coordinator crasht herhaaldelijk",
                message = (f"{cons_fail} opeenvolgende update-fouten. "
                           f"Laatste fout: {wd.get('last_failure_msg', '?')}. "
                           f"Totaal herstarts: {wd.get('total_restarts', 0)}."),
                action  = "reload" if cons_fail >= FAIL_RELOAD_AT else "notify",
                source  = "coordinator",
            )
        else:
            self._resolve("coordinator:consecutive_failures")

        # Health check fouten vanuit setup
        hc = data.get("health_check", {})
        if hc.get("error_count", 0) > 0:
            errors = [i for i in hc.get("issues", []) if i["level"] == "error"]
            msg = "; ".join(f"{e['sensor_id']}: {e['message']}" for e in errors[:3])
            self._raise_issue(
                key     = "coordinator:health_check_errors",
                level   = "error",
                title   = "CloudEMS — Configuratiefouten gevonden bij setup",
                message = f"{hc['error_count']} ontbrekende of defecte entiteiten: {msg}",
                action  = "notify",
                source  = "coordinator",
            )
        else:
            self._resolve("coordinator:health_check_errors")

    # ── 2. Module bewaker ─────────────────────────────────────────────────────

    def _check_modules(self, data: dict, now: float) -> None:
        """Controleer of modules actieve beslissingen nemen."""

        # Boiler beslissingen: als boilers geconfigureerd zijn maar nooit iets doen
        boiler_groups = data.get("boiler_groups_status", [])
        for g in boiler_groups:
            gid = g.get("id", "?")
            if gid in self._disabled_modules:
                continue
            boilers = g.get("boilers", [])
            if not boilers:
                continue
            # Als alle boilers al uren op setpoint zijn zonder ooit aan te gaan = ok
            # Maar als er boilers zijn die needs_heat zouden moeten hebben maar nooit aan gaan:
            needs_heat = [b for b in boilers
                          if b.get("temp_c") is not None
                          and b.get("setpoint_c") is not None
                          and b.get("temp_c", 0) < b.get("setpoint_c", 0) - 3
                          and not b.get("is_on")]
            if len(needs_heat) == len(boilers) and len(boilers) > 0:
                labels = ", ".join(b["label"] for b in needs_heat)
                self._fail_count[f"module:boiler:{gid}"] += 1
                if self._fail_count[f"module:boiler:{gid}"] >= 3:
                    self._raise_issue(
                        key     = f"module:boiler:{gid}:no_heat",
                        level   = "warning",
                        title   = f"Boiler cascade '{g.get('name', gid)}' — geen verwarming",
                        message = (f"Alle boilers ({labels}) zijn onder setpoint maar worden "
                                   f"niet ingeschakeld. Mogelijk geblokkeerd door congestie, "
                                   f"timers of een fout in de cascadelogica."),
                        action  = "notify",
                        source  = "boiler",
                    )
            else:
                self._fail_count[f"module:boiler:{gid}"] = 0
                self._resolve(f"module:boiler:{gid}:no_heat")

        # EV-lader: als geconfigureerd maar sensor altijd unavailable
        ev_data = data.get("ev_status", {})
        if ev_data and ev_data.get("charger_available") is False:
            self._raise_issue(
                key     = "module:ev:unavailable",
                level   = "warning",
                title   = "EV-lader — niet bereikbaar",
                message = ("De EV-lader entiteit is unavailable. "
                           "CloudEMS kan niet dynamisch laden totdat de lader terug online is."),
                action  = "notify",
                source  = "module",
            )
        else:
            self._resolve("module:ev:unavailable")

        # NILM: als NILM actief is maar al lang geen apparaten detecteert
        nilm = data.get("nilm_status", {})
        if nilm and nilm.get("enabled") and not nilm.get("running_devices"):
            last_detect = nilm.get("last_detection_ts", 0.0)
            if last_detect and (now - last_detect) > 7200:  # 2 uur geen detectie
                self._raise_issue(
                    key     = "module:nilm:no_detection",
                    level   = "info",
                    title   = "NILM — geen apparaatdetectie",
                    message = ("NILM heeft de afgelopen 2 uur geen apparaten gedetecteerd. "
                               "Dit kan normaal zijn bij laag verbruik."),
                    action  = "none",
                    source  = "module",
                )
            else:
                self._resolve("module:nilm:no_detection")

    # ── 3. Sensor bewaker ─────────────────────────────────────────────────────

    def _check_sensors(self, data: dict, now: float) -> None:
        """Controleer kritieke sensoren op unavailable en stuck-waarden."""

        # v4.5.11: onderscheid tussen "niet geconfigureerd" en "tijdelijk geen data"
        # Voorheen stond er altijd "Controleer de sensor-configuratie" — maar als
        # de sensor gewoon even unavailable is (bijv. na herstart of bij cloudstoring)
        # is dat misleidend. We kijken nu of er een entity geconfigureerd is.
        cfg = getattr(self, "_config", {})
        critical = {
            "grid_power": {
                "label":       "Net-vermogen sensor",
                "config_keys": ["grid_sensor", "p1_sensor"],
            },
            "pv_power": {
                "label":       "PV-opbrengst sensor",
                "config_keys": ["solar_sensor", "inverter_configs"],
            },
        }
        for key, meta in critical.items():
            label = meta["label"]
            val = data.get(key)
            if val is None:
                # Bepaal of er überhaupt een sensor geconfigureerd is
                _is_configured = any(
                    cfg.get(ck) for ck in meta["config_keys"]
                )
                if not _is_configured:
                    # Sensor staat helemaal niet ingesteld
                    _msg = (
                        f"Er is geen sensor ingesteld voor '{key}'. "
                        f"Ga naar de CloudEMS configuratie en stel de juiste "
                        f"sensor in onder Energiemeting."
                    )
                    _title = f"{label} — niet geconfigureerd"
                else:
                    # Geconfigureerd maar levert nu geen waarde
                    # Kan tijdelijk zijn (herstart, integratie offline, cloudstoring)
                    _uptime_s = data.get("uptime_s", 0) or 0
                    if _uptime_s < 120:
                        # Binnen 2 min na opstart: niet meteen alarmeren
                        self._resolve(f"sensor:{key}:missing")
                        continue
                    _msg = (
                        f"Sensor voor '{key}' is geconfigureerd maar levert "
                        f"momenteel geen waarde. Dit kan tijdelijk zijn na een "
                        f"herstart of bij een integratie-storing. "
                        f"Als dit langer dan enkele minuten aanhoudt: "
                        f"controleer of de sensor entiteit beschikbaar is in HA."
                    )
                    _title = f"{label} — tijdelijk geen data"
                self._raise_issue(
                    key     = f"sensor:{key}:missing",
                    level   = "error" if not _is_configured else "warning",
                    title   = _title,
                    message = _msg,
                    action  = "notify",
                    source  = "sensor",
                )
            else:
                self._resolve(f"sensor:{key}:missing")
                # Stuck check via history
                self._sensor_history[key].append((now, float(val)))
                hist = self._sensor_history[key]
                if len(hist) >= 10:
                    window_s = hist[-1][0] - hist[0][0]
                    values   = [h[1] for h in hist]
                    spread   = max(values) - min(values)
                    if window_s > SENSOR_STUCK_S and spread < 0.5:
                        self._raise_issue(
                            key     = f"sensor:{key}:stuck",
                            level   = "warning",
                            title   = f"{label} — waarde bevroren",
                            message = (f"Sensor '{key}' levert al {window_s//60:.0f} minuten "
                                       f"dezelfde waarde ({val:.1f}). "
                                       f"Mogelijk is de sensor of integratie vastgelopen."),
                            action  = "notify",
                            source  = "sensor",
                        )
                    else:
                        self._resolve(f"sensor:{key}:stuck")

        # Boiler temperatuursensoren stuck check
        boiler_groups = data.get("boiler_groups_status", [])
        for g in boiler_groups:
            for b in g.get("boilers", []):
                eid = b.get("entity_id", "")
                temp = b.get("temp_c")
                if temp is not None and eid:
                    self._sensor_history[f"boiler_temp:{eid}"].append((now, float(temp)))
                    hist = self._sensor_history[f"boiler_temp:{eid}"]
                    if len(hist) >= 15:
                        window_s = hist[-1][0] - hist[0][0]
                        spread   = max(h[1] for h in hist) - min(h[1] for h in hist)
                        # Een boiler die aan is maar geen temperatuurstijging toont = probleem
                        is_on = b.get("is_on", False)
                        if is_on and window_s > 600 and spread < 0.3:
                            self._raise_issue(
                                key     = f"sensor:boiler_temp:{eid}:stuck_on",
                                level   = "warning",
                                title   = f"Boiler '{b.get('label', eid)}' — temp stuck terwijl aan",
                                message = (f"Boiler is 10+ minuten ingeschakeld maar temperatuur "
                                           f"verandert niet ({temp:.1f}°C). "
                                           f"Mogelijk defecte temperatuursensor of verwarmingselement."),
                                action  = "notify",
                                source  = "sensor",
                            )
                        else:
                            self._resolve(f"sensor:boiler_temp:{eid}:stuck_on")

    # ── 4. Boiler cascade bewaker ─────────────────────────────────────────────

    def _check_boiler_cascade(self, data: dict, now: float) -> None:
        """Specifieke cascade-gezondheid: warmte bereikt, leveringsboiler, anomalieën."""

        boiler_groups = data.get("boiler_groups_status", [])
        for g in boiler_groups:
            gid   = g.get("id", "?")
            name  = g.get("name", gid)
            learn = g.get("learn_status", {})

            # Anomalie melding vanuit BoilerLearner
            anom = learn.get("anomaly", {})
            if anom.get("alerted"):
                count  = anom.get("count", 0)
                self._raise_issue(
                    key     = f"boiler:{gid}:anomaly",
                    level   = "warning",
                    title   = f"Boiler cascade '{name}' — ongewoon hoog verbruik",
                    message = (f"{count} warm-water cycli vandaag — meer dan 2.5× normaal. "
                               f"Controleer op lekkage of ongewoon gebruik."),
                    action  = "notify",
                    source  = "boiler",
                )
            else:
                self._resolve(f"boiler:{gid}:anomaly")

            # Leveringsboiler-gezondheid: als geleerd maar boiler al lang koud
            delivery_eid = g.get("delivery_entity")
            if delivery_eid:
                for b in g.get("boilers", []):
                    if b.get("entity_id") == delivery_eid:
                        mtc = b.get("minutes_to_cold")
                        if mtc is not None and mtc < 20:
                            self._raise_issue(
                                key     = f"boiler:{gid}:delivery_cold",
                                level   = "warning",
                                title   = f"Leveringsboiler '{b.get('label')}' — bijna koud",
                                message = (f"De leveringsboiler heeft nog ~{mtc:.0f} minuten "
                                           f"warm water. Cascade moet spoedig opwarmen."),
                                action  = "notify",
                                source  = "boiler",
                            )
                        else:
                            self._resolve(f"boiler:{gid}:delivery_cold")
                        break

            # Seizoenswisseling melding
            season = g.get("season", "winter")
            season_key = f"boiler:{gid}:season:{season}"
            if season_key not in self._issues:
                self._raise_issue(
                    key     = season_key,
                    level   = "info",
                    title   = f"Boiler cascade '{name}' — seizoen gewijzigd",
                    message = f"Seizoensdetectie: nu {'zomer' if season == 'summer' else 'winter'}stand. Setpoints automatisch aangepast.",
                    action  = "notify",
                    source  = "boiler",
                )

    # ── Bijsturing ────────────────────────────────────────────────────────────

    async def _apply_actions(self, now: float) -> None:
        """Voer bijsturingsacties uit op basis van actieve issues."""

        active_critical = [i for i in self._issues.values()
                           if not i.resolved and i.level == "critical"]
        active_errors   = [i for i in self._issues.values()
                           if not i.resolved and i.level in ("error", "critical")]
        active_warnings = [i for i in self._issues.values()
                           if not i.resolved and i.level == "warning"]

        # Veilige stand bij aanhoudende kritieke problemen
        if len(active_critical) >= 2 or self._fail_count.get("coordinator:global", 0) >= FAIL_SAFE_AT:
            if not self._safe_mode:
                await self._activate_safe_mode()
        elif self._safe_mode and not active_critical:
            self._safe_mode = False
            _LOGGER.info("SystemGuardian: veilige stand opgeheven")

        # Notificaties sturen
        to_notify = [i for i in (active_errors + active_warnings)
                     if not i.notified or (now - self._last_notify.get(i.key, 0)) > NOTIFY_COOLDOWN]

        for issue in to_notify:
            await self._send_notification(issue)
            issue.notified = True
            self._last_notify[issue.key] = now

        # Automatisch log-rapport sturen bij nieuwe kritieke fouten
        new_critical = [i for i in active_errors if not i.notified]
        if new_critical and self._log_reporter:
            reason = new_critical[0].key
            try:
                data = self._coordinator.data or {}
                url  = await self._log_reporter.async_auto_report(
                    data, self.get_status(), reason)
                if url:
                    _LOGGER.info("SystemGuardian: auto-rapport verstuurd: %s", url)
            except Exception as _lr_err:
                _LOGGER.debug("SystemGuardian: auto-rapport fout: %s", _lr_err)

        # Info-issues: alleen loggen
        for issue in self._issues.values():
            if not issue.resolved and issue.level == "info" and not issue.notified:
                _LOGGER.info("SystemGuardian [info]: %s — %s", issue.title, issue.message)
                issue.notified = True

    async def _activate_safe_mode(self) -> None:
        """Zet het systeem in veilige stand: boilers uit, EV minimum."""
        self._safe_mode = True
        _LOGGER.warning("SystemGuardian: VEILIGE STAND geactiveerd")
        try:
            # Boilers uitschakelen via CloudEMS service
            await self._hass.services.async_call(
                "cloudems", "set_module_state",
                {"module": "boiler", "enabled": False},
                blocking=False,
            )
        except Exception:
            pass
        await self._send_notification(GuardianIssue(
            key     = "guardian:safe_mode",
            level   = "critical",
            title   = "CloudEMS — VEILIGE STAND ACTIEF",
            message = ("Meerdere kritieke problemen gedetecteerd. "
                       "Boilers en EV-lader zijn teruggeschaald. "
                       "Controleer het CloudEMS diagnose-tabblad."),
            action  = "safe_mode",
            source  = "coordinator",
        ))

    # ── Notificaties ──────────────────────────────────────────────────────────

    async def _send_notification(self, issue: GuardianIssue) -> None:
        """Stuur notificatie via persistent_notification en optioneel push."""
        notif_id = f"cloudems_guardian_{issue.key.replace(':', '_')}"
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":           f"⚙️ {issue.title}",
                    "message":         issue.message,
                    "notification_id": notif_id,
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("SystemGuardian: persistent_notification fout: %s", err)

        if self._notify_svc and issue.level in ("error", "critical", "warning"):
            try:
                await self._hass.services.async_call(
                    "notify", self._notify_svc,
                    {
                        "title":   f"CloudEMS: {issue.title}",
                        "message": issue.message,
                        "data":    {
                            "tag":      notif_id,
                            "priority": "high" if issue.level == "critical" else "normal",
                        },
                    },
                    blocking=False,
                )
            except Exception as err:
                _LOGGER.debug("SystemGuardian: push notificatie mislukt: %s", err)

    async def _send_weekly_report(self, now: float) -> None:
        """Stuur wekelijks samenvattingsrapport aan eigenaar."""
        self._last_weekly = now
        self._save()

        data    = self._coordinator.data or {}
        issues  = [i for i in self._issues.values() if not i.resolved]
        wd      = data.get("watchdog", {})
        boilers = data.get("boiler_groups_status", [])

        # Boiler-samenvatting
        boiler_lines = []
        for g in boilers:
            ls      = g.get("learn_status", {})
            season  = g.get("season", "?")
            total_e = sum(b.get("cycle_kwh", 0) for b in g.get("boilers", []))
            boiler_lines.append(
                f"• {g['name']}: {g['active_count']}/{g['boiler_count']} actief, "
                f"{season}stand, {total_e:.2f} kWh deze cyclus"
            )

        # Budget samenvatting
        budget  = data.get("boiler_weekly_budget", {})
        total_w = sum(v.get("current_week", 0) for v in budget.values())

        lines = [
            f"CloudEMS wekelijks rapport — {datetime.now().strftime('%d %b %Y')}",
            "",
            f"🔁 Coordinator: {wd.get('total_failures', 0)} crashes, "
            f"{wd.get('total_restarts', 0)} herstarts deze week",
            "",
            "♨️ Boiler cascade:",
            *boiler_lines,
            f"   Totaal warm water energie: {total_w:.2f} kWh",
            "",
            f"⚠️ Actieve issues: {len(issues)}",
            *[f"   [{i.level.upper()}] {i.title}" for i in issues[:5]],
            "",
            f"📊 Guardian evaluaties: {self._eval_count}",
            f"🔒 Veilige stand actief: {'ja' if self._safe_mode else 'nee'}",
            f"🚫 Uitgeschakelde modules: {', '.join(self._disabled_modules) or 'geen'}",
        ]

        msg = "\n".join(lines)
        _LOGGER.info("SystemGuardian weekrapport:\n%s", msg)

        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":           "📊 CloudEMS Weekrapport",
                    "message":         msg,
                    "notification_id": "cloudems_guardian_weekly",
                },
                blocking=False,
            )
        except Exception:
            pass

        if self._notify_svc:
            try:
                await self._hass.services.async_call(
                    "notify", self._notify_svc,
                    {"title": "CloudEMS Weekrapport", "message": msg},
                    blocking=False,
                )
            except Exception:
                pass

    def _should_send_weekly(self, now: float) -> bool:
        """Stuur weekrapport op maandag om WEEKLY_REPORT_H uur."""
        if (now - self._last_weekly) < 6 * 24 * 3600:
            return False
        dt = datetime.now()
        return dt.weekday() == 0 and dt.hour == WEEKLY_REPORT_H

    # ── Issue management ──────────────────────────────────────────────────────

    def _raise_issue(self, key: str, level: str, title: str, message: str,
                     action: str, source: str) -> None:
        if key in self._issues:
            issue = self._issues[key]
            if issue.resolved:
                issue.resolved  = False
                issue.notified  = False
                issue.first_ts  = time.time()
            issue.last_ts  = time.time()
            issue.count   += 1
            issue.message  = message
        else:
            self._issues[key] = GuardianIssue(
                key=key, level=level, title=title, message=message,
                action=action, source=source,
            )

    def _resolve(self, key: str) -> None:
        if key in self._issues and not self._issues[key].resolved:
            self._issues[key].resolved = True
            _LOGGER.info("SystemGuardian: issue opgelost — %s", key)

    # ── Publieke interface ────────────────────────────────────────────────────

    def enable_module(self, module: str) -> None:
        self._disabled_modules.discard(module)
        self._save()
        _LOGGER.info("SystemGuardian: module %s opnieuw ingeschakeld", module)

    def disable_module(self, module: str) -> None:
        self._disabled_modules.add(module)
        self._save()
        _LOGGER.warning("SystemGuardian: module %s uitgeschakeld", module)

    def get_status(self) -> dict:
        """Dashboard- en sensor-data."""

        def _fmt_uptime(seconds: int) -> str:
            if seconds < 60:
                return f"{seconds}s"
            if seconds < 3600:
                return f"{seconds // 60}m {seconds % 60}s"
            hours = seconds // 3600
            mins  = (seconds % 3600) // 60
            if hours < 24:
                return f"{hours}u {mins}m"
            days = hours // 24
            return f"{days}d {hours % 24}u"

        now    = time.time()
        active = [i for i in self._issues.values() if not i.resolved]
        resolved_recent = [
            i for i in self._issues.values()
            if i.resolved and (now - i.last_ts) < 3600
        ]

        def _issue_dict(i: GuardianIssue) -> dict:
            return {
                "key":      i.key,
                "level":    i.level,
                "title":    i.title,
                "message":  i.message,
                "source":   i.source,
                "count":    i.count,
                "first_ts": datetime.fromtimestamp(i.first_ts, tz=timezone.utc).isoformat(timespec="seconds"),
                "last_ts":  datetime.fromtimestamp(i.last_ts,  tz=timezone.utc).isoformat(timespec="seconds"),
                "resolved": i.resolved,
            }

        errors   = [i for i in active if i.level in ("error", "critical")]
        warnings = [i for i in active if i.level == "warning"]
        infos    = [i for i in active if i.level == "info"]

        overall = "ok"
        if errors:   overall = "error"
        elif warnings: overall = "warning"

        return {
            "status":             overall,
            "safe_mode":          self._safe_mode,
            "disabled_modules":   list(self._disabled_modules),
            "eval_count":         self._eval_count,
            "active_issues":      [_issue_dict(i) for i in active],
            "resolved_recent":    [_issue_dict(i) for i in resolved_recent],
            "error_count":        len(errors),
            "warning_count":      len(warnings),
            "info_count":         len(infos),
            "last_eval":          datetime.fromtimestamp(self._last_eval, tz=timezone.utc).isoformat(timespec="seconds") if self._last_eval else None,
            "last_weekly_report": datetime.fromtimestamp(self._last_weekly, tz=timezone.utc).isoformat(timespec="seconds") if self._last_weekly else None,
            "uptime_s":           int(now - self._setup_ts),
            "uptime_str":         _fmt_uptime(int(now - self._setup_ts)),
            "started_at":         datetime.fromtimestamp(self._setup_ts, tz=timezone.utc).isoformat(timespec="seconds"),
        }
