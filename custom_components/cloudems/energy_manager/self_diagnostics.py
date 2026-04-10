"""
CloudEMS — SelfDiagnostics v1.0.0

Analyseert dagelijks de eigen sensor-output op structurele anomalieën.
Detecteert patronen die wijzen op bugs, misconfiguratie of sensor-problemen
VOORDAT de gebruiker er last van heeft.

Checks:
  1. Omvormer bevriesdetectie  — toont 's avonds nog vermogen?
  2. Fase-stroom plausibiliteit — waarden boven zekering?
  3. Kirchhoff-consistentie    — solar + grid ≈ huis + batterij?
  4. EMA-convergentie          — leert het model of blijft het steken?
  5. Boiler-temperatuur drift  — temperatuur reageert niet op sturing?
  6. Batterij SoC stagnatie    — SoC verandert niet terwijl actie verwacht?
  7. NILM-apparaat consistentie— learned_power_w consistent met gemeten?
"""
from __future__ import annotations

import logging
import datetime
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SEVERITY_INFO    = "info"
SEVERITY_WARN    = "warn"
SEVERITY_ERROR   = "error"


@dataclass
class DiagnosticIssue:
    code:        str
    severity:    str
    title:       str
    detail:      str
    suggestion:  str
    first_seen:  str = ""
    count:       int = 1

    def to_dict(self) -> dict:
        return {
            "code":       self.code,
            "severity":   self.severity,
            "title":      self.title,
            "detail":     self.detail,
            "suggestion": self.suggestion,
            "first_seen": self.first_seen,
            "count":      self.count,
        }


class SelfDiagnostics:
    """
    Dagelijkse zelfreflectie — analyseert CloudEMS output op anomalieën.
    Aanroepen via coordinator daily_rollover of elke 6 uur.
    """

    def __init__(self, hass: "HomeAssistant", notify_mgr=None) -> None:
        self._hass        = hass
        self._notify_mgr  = notify_mgr
        self._history:    dict[str, list] = {}   # code → [timestamps]
        self._last_run:         Optional[float] = None
        self._last_notif_sent:  float = 0.0  # max 1x per dag notificeren
        self._issues:     list[DiagnosticIssue] = []
        self._opportunistic_misses: dict = {}   # v5.5.347: gemiste ontlaad-kansen tracker
        self._boiler_drift: dict = {}           # v5.5.347: boiler temp-drift tracker
        self._inv_evening_samples: dict[str, list] = {}  # eid → [w] na 20:00
        self._kirchhoff_samples:   list[float] = []
        self._phase_samples:       dict[str, list] = {}  # phase → [a]

    # ── Data verzamelen (elke coordinator-cyclus aanroepen) ──────────────────

    def tick(self, data: dict, config: dict) -> None:
        """Verzamel samples voor analyse. Lichtgewicht — geen I/O."""
        import time
        now = datetime.datetime.now()
        hour = now.hour

        # 1. Omvormer 's avonds
        if hour >= 21 or hour < 5:
            invs = data.get("inverter_data") or []
            if not invs:
                # probeer via solar_system
                ss = (self._hass.states.get("sensor.cloudems_solar_system") or
                      self._hass.states.get("sensor.cloudems_solar_system_intelligence"))
                invs = (ss.attributes.get("inverters") or []) if ss else []
            for inv in invs:
                eid = inv.get("inverter_id") or inv.get("entity_id") or inv.get("id") or ""
                w   = float(inv.get("current_w") or 0)
                if eid and w > 5:  # >5W 's avonds = bevroren waarde
                    buf = self._inv_evening_samples.setdefault(eid, [])
                    buf.append(w)
                    if len(buf) > 120: buf.pop(0)

        # 2. Kirchhoff samples
        solar  = float(data.get("solar_power") or 0)
        grid   = float(data.get("grid_power_w") or data.get("grid_power") or 0)
        house  = float(data.get("house_power")  or data.get("home_power")  or 0)
        batt   = float(data.get("battery_power") or 0)
        if solar > 0 or abs(grid) > 10 or house > 10:
            imbalance = abs(solar + grid - house - batt)
            self._kirchhoff_samples.append(imbalance)
            if len(self._kirchhoff_samples) > 1440: self._kirchhoff_samples.pop(0)

        # 3. Fase-stroom samples
        self._check_opportunistic_discharge(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), data, config
        )
        self._check_boiler_temp_drift(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        phases = data.get("phase_currents") or {}
        max_a  = float(config.get("max_current_a") or 25)
        for ph, a in phases.items():
            buf = self._phase_samples.setdefault(ph, [])
            if abs(a) > max_a * 1.4:
                buf.append(abs(a))
                if len(buf) > 200: buf.pop(0)

    # ── Analyse (dagelijks aanroepen) ────────────────────────────────────────

    async def run_analysis(self, data: dict, config: dict) -> list[DiagnosticIssue]:
        """Voer volledige analyse uit. Returnt lijst van issues."""
        self._issues = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        self._check_inverter_evening(now_str)
        self._check_kirchhoff(now_str, config)
        self._check_phase_spikes(now_str, config)
        self._check_solar_forecast_accuracy(now_str)
        self._check_boiler_response(now_str, data)
        self._check_battery_stagnation(now_str, data)
        self._check_nilm_consistency(now_str)
        # v5.5.347: checks gebaseerd op log-analyse
        if self._opportunistic_misses.get("hold_high_grid"):
            misses = self._opportunistic_misses["hold_high_grid"]
            if len(misses) >= 50:  # structureel patroon
                avg_grid = sum(misses) / len(misses)
                self._add(
                    "OPPORTUNISTIC_DISCHARGE_MISSED", SEVERITY_WARN,
                    "Batterij ontlaadt niet bij hoog grid-import",
                    f"{len(misses)} keer grid>{4000}W + SoC>70% maar hold. "
                    f"Gem. gemist grid: {avg_grid:.0f}W.",
                    "CloudEMS v5.5.346 bevat opportunistic discharge fix. "
                    "Update naar nieuwste versie.",
                    now_str,
                )
            self._opportunistic_misses.clear()

        # Reset dagelijkse buffers
        self._inv_evening_samples.clear()
        self._kirchhoff_samples.clear()
        self._phase_samples.clear()
        self._last_run = datetime.datetime.now().timestamp()

        if self._issues:
            _LOGGER.warning(
                "CloudEMS SelfDiagnostics: %d issue(s) gevonden: %s",
                len(self._issues),
                ", ".join(i.code for i in self._issues)
            )
            # v5.5.521: max 1x per 24u notificaties sturen
            import time as _t_sd
            if _t_sd.time() - self._last_notif_sent >= 86400:
                self._last_notif_sent = _t_sd.time()
                await self._send_notifications()
            else:
                _LOGGER.debug("SelfDiagnostics: cooldown actief — notificatie overgeslagen")
        else:
            _LOGGER.info("CloudEMS SelfDiagnostics: alles OK")

        return self._issues

    def _add(self, code: str, severity: str, title: str, detail: str,
             suggestion: str, now_str: str) -> None:
        hist = self._history.setdefault(code, [])
        hist.append(now_str)
        if len(hist) > 30: hist.pop(0)
        self._issues.append(DiagnosticIssue(
            code=code, severity=severity, title=title,
            detail=detail, suggestion=suggestion,
            first_seen=hist[0], count=len(hist),
        ))

    def _check_inverter_evening(self, now_str: str) -> None:
        """Omvormer toont >5W na 21:00 — bevroren waarde."""
        for eid, samples in self._inv_evening_samples.items():
            if len(samples) < 3: continue
            avg = statistics.mean(samples)
            if avg > 10:
                short = eid.split(".")[-1].replace("_", " ")
                self._add(
                    f"INV_EVENING_{eid}", SEVERITY_WARN,
                    f"Omvormer '{short}' toont 's avonds vermogen",
                    f"Gemiddeld {avg:.0f}W na 21:00 over {len(samples)} metingen. "
                    f"Echte productie is onwaarschijnlijk.",
                    "Controleer of de HA sensor de laatste dagwaarde behoudt ipv 0W. "
                    "Mogelijk heeft de omvormer een 'freeze' bug in de integratie.",
                    now_str,
                )

    def _check_kirchhoff(self, now_str: str, config: dict) -> None:
        """Kirchhoff-onbalans structureel > 200W."""
        if len(self._kirchhoff_samples) < 100: return
        avg_imbalance = statistics.mean(self._kirchhoff_samples)
        p95 = sorted(self._kirchhoff_samples)[int(len(self._kirchhoff_samples) * 0.95)]
        if avg_imbalance > 200:
            self._add(
                "KIRCHHOFF_IMBALANCE", SEVERITY_WARN,
                "Structurele energiebalans-afwijking",
                f"Gemiddelde Kirchhoff-onbalans: {avg_imbalance:.0f}W "
                f"(P95: {p95:.0f}W). Zon + Net ≠ Huis + Batterij.",
                "Controleer of alle vermogenssensoren dezelfde eenheid gebruiken (W vs kW). "
                "Mogelijk ontbreekt een verbruiker (EV, warmtepomp) in de balans.",
                now_str,
            )

    def _check_phase_spikes(self, now_str: str, config: dict) -> None:
        """Fase-stroom boven 1.4× zekering meer dan 3 keer per dag."""
        max_a = float(config.get("max_current_a") or 25)
        for ph, samples in self._phase_samples.items():
            if len(samples) >= 3:
                self._add(
                    f"PHASE_SPIKE_{ph}", SEVERITY_WARN,
                    f"Fase {ph}: herhaalde stroom-spikes",
                    f"{len(samples)}× boven {max_a * 1.4:.0f}A gedetecteerd "
                    f"(max zekering {max_a:.0f}A). Hoogste: {max(samples):.1f}A.",
                    "Controleer de fase-sensor kalibratie of de fusie-gewichten in "
                    "sensor.cloudems_solar_system_intelligence diagnostics.",
                    now_str,
                )

    def _check_solar_forecast_accuracy(self, now_str: str) -> None:
        """Forecast accuraatheid structureel laag."""
        try:
            acc_st = (self._hass.states.get("sensor.cloudems_solar_pv_forecast_accuracy") or
                      self._hass.states.get("sensor.cloudems_pv_forecast_accuracy"))
            if not acc_st or acc_st.state in ("unavailable", "unknown"): return
            acc = float(acc_st.state)
            if acc < 40:
                self._add(
                    "FORECAST_LOW_ACCURACY", SEVERITY_WARN,
                    "PV-voorspelling structureel onnauwkeurig",
                    f"Forecast accuraatheid: {acc:.0f}% (normaal >60%).",
                    "Controleer of de KNMI/weer-integratie correct werkt en of "
                    "de paneel-oriëntatie is geconfigureerd.",
                    now_str,
                )
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics forecast check fout: %s", e)

    def _check_boiler_response(self, now_str: str, data: dict) -> None:
        """Boiler reageert niet op sturing."""
        try:
            boiler_st = self._hass.states.get("sensor.cloudems_boiler_status")
            if not boiler_st: return
            boilers = boiler_st.attributes.get("boilers") or []
            for b in boilers:
                temp   = float(b.get("temp_c") or 0)
                sp     = float(b.get("active_setpoint_c") or b.get("setpoint_c") or 60)
                is_on  = b.get("is_on", False)
                label  = b.get("label") or "Boiler"
                # Al meer dan 2u aan maar temp stijgt niet naar setpoint
                if is_on and temp < sp - 15:
                    self._add(
                        f"BOILER_NO_RESPONSE_{label}", SEVERITY_WARN,
                        f"{label} reageert niet op sturing",
                        f"Boiler staat aan maar temperatuur ({temp:.0f}°C) is "
                        f"ver onder setpoint ({sp:.0f}°C).",
                        "Controleer of de schakelentiteit correct werkt en of "
                        "de temperatuursensor actuele waarden geeft.",
                        now_str,
                    )
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics boiler check fout: %s", e)

    def _check_battery_stagnation(self, now_str: str, data: dict) -> None:
        """Batterij SoC beweegt niet terwijl actie verwacht."""
        try:
            bat_st = self._hass.states.get("sensor.cloudems_batterij_epex_schema")
            if not bat_st: return
            soc     = float(bat_st.attributes.get("soc_pct") or -1)
            action  = str(bat_st.attributes.get("action") or "")
            power_w = float(bat_st.attributes.get("power_w") or 0)
            if soc < 0: return
            # Actie is laden/ontladen maar vermogen is 0
            if action in ("charge", "discharge") and abs(power_w) < 10:
                self._add(
                    "BATTERY_STAGNATION", SEVERITY_WARN,
                    "Batterij reageert niet op laad/ontlaad opdracht",
                    f"Actie '{action}' maar vermogen is {power_w:.0f}W.",
                    "Controleer de Zonneplan/batterij-integratie en of de "
                    "besturingsentiteit beschikbaar is.",
                    now_str,
                )
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics batterij check fout: %s", e)

    def _check_nilm_consistency(self, now_str: str) -> None:
        """NILM learned_power_w wijkt >3× af van huidige meting."""
        try:
            nilm_st = self._hass.states.get("sensor.cloudems_nilm_running_devices")
            if not nilm_st: return
            devices = nilm_st.attributes.get("devices") or []
            for d in devices:
                cur  = float(d.get("power_w") or 0)
                lrn  = float(d.get("learned_power_w") or 0)
                name = d.get("user_name") or d.get("name") or "?"
                if lrn > 50 and cur > 0 and (cur > lrn * 3 or cur < lrn * 0.2):
                    self._add(
                        f"NILM_DRIFT_{name}", SEVERITY_INFO,
                        f"NILM: '{name}' wijkt sterk af van geleerd profiel",
                        f"Huidig: {cur:.0f}W, geleerd: {lrn:.0f}W "
                        f"(factor {cur/lrn:.1f}×).",
                        "Apparaat verbruikt structureel meer/minder dan geleerd. "
                        "Mogelijk defect of ander gebruik dan normaal.",
                        now_str,
                    )
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics NILM check fout: %s", e)

    async def _send_notifications(self) -> None:
        """Stuur samenvatting via NotificationManager."""
        if not self._notify_mgr: return
        errors  = [i for i in self._issues if i.severity == SEVERITY_ERROR]
        warns   = [i for i in self._issues if i.severity == SEVERITY_WARN]
        infos   = [i for i in self._issues if i.severity == SEVERITY_INFO]

        if not errors and not warns: return  # alleen info → niet sturen

        icon  = "🔴" if errors else "🟡"
        lines = []
        for i in (errors + warns)[:5]:  # max 5 in push
            lines.append(f"• {i.title}: {i.detail[:80]}")
        msg = "\n".join(lines)
        if len(self._issues) > 5:
            msg += f"\n… en {len(self._issues)-5} andere bevindingen."

        await self._notify_mgr.send(
            f"{icon} CloudEMS zelfreflectie — {len(errors+warns)} aandachtspunt(en)",
            msg,
            category="alert",
            notification_id="cloudems_self_diagnostics",
            force=True,
        )


    def _check_opportunistic_discharge(self, now_str: str, data: dict, config: dict) -> None:
        """Batterij hold terwijl grid hoog en SoC vol — uit log-analyse (5.5.346).
        Detecteert gemiste ontlaad-kansen. Als dit structureel is, wijst het op
        een sub-optimale ZP drempel-configuratie."""
        try:
            grid_w = float(data.get("grid_power_w") or data.get("grid_power") or 0)
            min_soc = float(config.get("battery_min_soc_pct", 10) or 10)
            bat_st  = self._hass.states.get("sensor.cloudems_batterij_epex_schema")
            if not bat_st: return
            soc    = float(bat_st.attributes.get("soc_pct") or 0)
            action = str(bat_st.attributes.get("action") or "")
            if grid_w > 4000 and soc > 70 and action == "hold":
                buf = self._opportunistic_misses.setdefault("hold_high_grid", [])
                buf.append(grid_w)
                if len(buf) > 500: buf.pop(0)
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics opportunistic check fout: %s", e)

    def _check_boiler_temp_drift(self, now_str: str) -> None:
        """Boiler temp_c drijft structureel af van setpoint — geleerd uit boiler logs.
        Als temp >15°C onder setpoint terwijl boiler al lange tijd aan is: defect of
        misconfiguratie."""
        try:
            boiler_st = self._hass.states.get("sensor.cloudems_boiler_status")
            if not boiler_st: return
            boilers = boiler_st.attributes.get("boilers") or []
            for b in boilers:
                temp   = float(b.get("temp_c") or b.get("current_temp_c") or 0)
                sp     = float(b.get("active_setpoint_c") or b.get("setpoint_c") or 60)
                is_on  = b.get("is_on", False)
                label  = b.get("label") or "Boiler"
                gap    = sp - temp
                # Al aan maar >20°C onder setpoint na 10+ minuten
                buf = self._boiler_drift.setdefault(label, [])
                if is_on and gap > 20:
                    buf.append(gap)
                else:
                    if len(buf) < 3:
                        buf.clear()
                if len(buf) >= 12:  # 12 samples × ~10s = 2 minuten aanhoudend
                    avg_gap = sum(buf[-12:]) / 12
                    if avg_gap > 20:
                        self._add(
                            f"BOILER_DRIFT_{label}", SEVERITY_WARN,
                            f"{label} verwarmt niet effectief",
                            f"Boiler staat aan maar temperatuur is gem. {avg_gap:.0f}°C "
                            f"onder setpoint ({sp:.0f}°C) over de laatste 2 minuten.",
                            "Controleer of het verwarmingselement werkt en of de "
                            "temp-sensor correct is gekalibreerd.",
                            now_str,
                        )
                    buf.clear()
        except Exception as e:
            _LOGGER.debug("SelfDiagnostics boiler drift check fout: %s", e)

    def to_dict(self, capacity_kwh: float = 0) -> dict:
        """Status voor sensor attribuut."""
        return {
            "last_run":    datetime.datetime.fromtimestamp(self._last_run).isoformat()
                           if self._last_run else None,
            "issue_count": len(self._issues),
            "issues":      [i.to_dict() for i in self._issues],
            "status":      ("error" if any(i.severity == SEVERITY_ERROR for i in self._issues)
                            else "warn" if any(i.severity == SEVERITY_WARN for i in self._issues)
                            else "ok"),
        }
