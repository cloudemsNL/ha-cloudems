"""
CloudEMS — influxdb_writer.py
Schrijft CloudEMS data naar InfluxDB v2 voor Grafana dashboards.

Geen extra dependencies — gebruikt HA's eigen aiohttp session.
Configuratie via CloudEMS opties (optioneel):
  influxdb_url:    "http://192.168.1.x:8086"
  influxdb_token:  "my-token"
  influxdb_org:    "home"
  influxdb_bucket: "cloudems"

Schrijft:
  - Elke coordinator cycle: realtime vermogen, SoC, prijzen
  - Elke beslissing: ZP action, battery, boiler, EV
  - Elke EV sessie afsluiting: sessie-statistieken
  - Audit log failures

Line Protocol formaat (InfluxDB v2):
  measurement,tag=val field=val timestamp
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

_WRITE_INTERVAL_S = 30   # schrijf elke 30s realtime data
_BATCH_MAX = 200         # max regels per batch


class InfluxDBWriter:
    """Schrijft CloudEMS meetwaarden naar InfluxDB v2 via HTTP."""

    def __init__(self, hass, config: dict):
        self._hass = hass
        self._url    = (config.get("influxdb_url") or "").rstrip("/")
        self._token  = config.get("influxdb_token") or ""
        self._org    = config.get("influxdb_org") or "home"
        self._bucket = config.get("influxdb_bucket") or "cloudems"
        self._enabled = bool(self._url and self._token)
        self._queue: list[str] = []
        self._last_write = 0.0
        self._errors = 0
        self._writes = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Line Protocol helpers ─────────────────────────────────────────────────

    def _lp(self, measurement: str, fields: dict, tags: dict | None = None, ts: float | None = None) -> str:
        """Bouw een InfluxDB line protocol regel."""
        tag_str = ""
        if tags:
            tag_str = "," + ",".join(f"{k}={str(v).replace(' ','_')}" for k, v in sorted(tags.items()))

        def _fmt(v):
            if isinstance(v, bool): return "true" if v else "false"
            if isinstance(v, int):  return f"{v}i"
            if isinstance(v, float): return f"{v:.6g}"
            return f'"{str(v)}"'

        field_str = ",".join(f"{k}={_fmt(v)}" for k, v in fields.items() if v is not None)
        if not field_str:
            return ""
        ns_ts = int((ts or time.time()) * 1_000_000_000)
        return f"{measurement}{tag_str} {field_str} {ns_ts}"

    def _enqueue(self, line: str) -> None:
        if line:
            self._queue.append(line)
        if len(self._queue) > _BATCH_MAX * 2:
            self._queue = self._queue[-_BATCH_MAX:]

    # ── Public write methods ─────────────────────────────────────────────────

    def write_realtime(self, data: dict) -> None:
        """Schrijf realtime vermogensdata naar queue."""
        if not self._enabled:
            return
        ts = time.time()
        self._enqueue(self._lp("cloudems_power", {
            "solar_w":    float(data.get("solar_power", 0) or 0),
            "grid_w":     float(data.get("grid_power",  0) or 0),
            "battery_w":  float(data.get("battery_power", 0) or 0),
            "house_w":    float(data.get("house_power",  0) or 0),
        }, ts=ts))

        # Prijs
        ep = data.get("energy_price", {}) or {}
        if ep.get("current"):
            self._enqueue(self._lp("cloudems_price", {
                "epex_eur_kwh":   float(ep.get("current", 0) or 0),
                "all_in_eur_kwh": float(ep.get("current_all_in", 0) or 0),
            }, tags={"tariff": str(ep.get("tariff_group", "unknown"))}, ts=ts))

        # Batterij SoC
        bats = data.get("batteries") or []
        for i, bat in enumerate(bats):
            soc = bat.get("soc_pct")
            if soc is not None:
                self._enqueue(self._lp("cloudems_battery",
                    {"soc_pct": float(soc), "power_w": float(bat.get("power_w", 0) or 0)},
                    tags={"battery": str(bat.get("label", f"bat{i}"))}, ts=ts))

        # EV sessie
        ev = data.get("ev_session", {}) or {}
        if ev.get("session_active"):
            self._enqueue(self._lp("cloudems_ev_session", {
                "current_a":      float(ev.get("session_current_a", 0) or 0),
                "kwh_so_far":     float(ev.get("session_kwh_so_far", 0) or 0),
                "cost_so_far":    float(ev.get("session_cost_so_far", 0) or 0),
                "solar_pct":      float(ev.get("session_solar_pct", 0) or 0),
            }, ts=ts))

    def write_decision(self, category: str, action: str, context: dict) -> None:
        """Schrijf een beslissing naar InfluxDB."""
        if not self._enabled:
            return
        fields = {
            "solar_w":   float(context.get("solar_w", 0) or 0),
            "grid_w":    float(context.get("grid_w",  0) or 0),
            "battery_w": float(context.get("battery_w", 0) or 0),
            "soc_pct":   float(context.get("soc_pct", 0) or 0) if context.get("soc_pct") else None,
            "price_ct":  round(float(context.get("price_eur_kwh", 0) or 0) * 100, 2),
        }
        self._enqueue(self._lp("cloudems_decision", fields,
            tags={"category": category, "action": action}))

    def write_ev_session_complete(self, session: dict) -> None:
        """Schrijf afgesloten EV sessie naar InfluxDB."""
        if not self._enabled:
            return
        ts = float(session.get("end_ts", time.time()))
        self._enqueue(self._lp("cloudems_ev_session_complete", {
            "kwh":           float(session.get("kwh", 0)),
            "cost_eur":      float(session.get("cost_eur", 0)),
            "solar_kwh":     float(session.get("solar_kwh", 0)),
            "solar_pct":     float(session.get("solar_pct", 0)),
            "co2_g":         float(session.get("co2_g", 0)),
            "duration_h":    float(session.get("duration_h", 0)),
            "price_per_kwh": float(session.get("price_per_kwh", 0)),
        }, tags={"weekday": str(session.get("weekday", 0))}, ts=ts))

    def write_audit_failure(self, module: str, entity_id: str, action: str, attempts: int) -> None:
        """Schrijf een command failure naar InfluxDB."""
        if not self._enabled:
            return
        self._enqueue(self._lp("cloudems_command_failure", {
            "attempts": attempts,
        }, tags={"module": module[:40], "entity": entity_id[:60], "action": action[:40]}))

    # ── Flush queue ──────────────────────────────────────────────────────────

    async def async_flush(self, force: bool = False) -> None:
        """Schrijf queue naar InfluxDB als interval verstreken is."""
        if not self._enabled or not self._queue:
            return
        if not force and (time.time() - self._last_write) < _WRITE_INTERVAL_S:
            return

        batch = self._queue[:_BATCH_MAX]
        self._queue = self._queue[_BATCH_MAX:]
        payload = "\n".join(batch)

        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self._hass)
            url = f"{self._url}/api/v2/write?org={self._org}&bucket={self._bucket}&precision=ns"
            async with session.post(
                url,
                data=payload.encode(),
                headers={
                    "Authorization": f"Token {self._token}",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                timeout=5,
            ) as resp:
                if resp.status in (200, 204):
                    self._writes += 1
                    self._last_write = time.time()
                    _LOGGER.debug("CloudEMS InfluxDB: %d regels geschreven", len(batch))
                else:
                    self._errors += 1
                    body = await resp.text()
                    _LOGGER.warning("CloudEMS InfluxDB fout %d: %s", resp.status, body[:200])
        except asyncio.TimeoutError:
            self._errors += 1
            _LOGGER.warning("CloudEMS InfluxDB: timeout")
        except Exception as exc:
            self._errors += 1
            _LOGGER.warning("CloudEMS InfluxDB: %s", exc)

    def get_status(self) -> dict:
        return {
            "enabled":    self._enabled,
            "url":        self._url if self._enabled else "",
            "bucket":     self._bucket,
            "writes":     self._writes,
            "errors":     self._errors,
            "queue_size": len(self._queue),
        }
