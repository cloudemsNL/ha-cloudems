"""
CloudEMS EnergySourceManager — v5.5.503
Generieke kWh-bronbeheerder: leest kWh direct van apparaat-sensoren
als primaire bron, gebruikt berekening als fallback.

Twee sensortypen:
- daily_reset: sensor reset elke dag naar 0 (bijv. omvormer energy_today)
- cumulative:  sensor telt oneindig op (bijv. P1 netmeter, lifetime accu-teller)
               → CloudEMS berekent dagdelta: waarde_nu − waarde_begin_dag

Overleeft herstarts: begin-van-dag waarde wordt gepersisteerd.
"""
from __future__ import annotations
import logging
import datetime
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Bekende eenheden → kWh conversiefactoren
_UNIT_TO_KWH = {
    "kwh": 1.0,
    "wh":  1.0 / 1000.0,
    "mwh": 1000.0,
    "kj":  1.0 / 3600.0,
    "j":   1.0 / 3_600_000.0,
}

# Patronen die wijzen op een cumulatieve sensor (geen dagelijkse reset)
_CUMULATIVE_PATTERNS = [
    "total", "lifetime", "cumulative", "all_time", "totaal", "cumulatief",
    "meter", "import_kwh", "export_kwh", "electricity_import", "electricity_export",
    "net_metering", "grid_import", "grid_export", "energy_meter",
]

# Patronen die wijzen op een dagelijkse reset sensor
_DAILY_PATTERNS = [
    "today", "daily", "day", "vandaag", "dagelijks",
    "energy_today", "daily_energy", "today_energy", "production_today",
    # Zonneplan Nexus: delivery_day / production_day zijn dagwaarden ondanks TOTAL_INCREASING
    "delivery_day", "production_day", "levering_vandaag", "productie_vandaag",
    "charged_today", "discharged_today", "geladen_vandaag", "ontladen_vandaag",
]


class EnergySourceManager:
    """
    Beheer kWh-bron per apparaat of categorie.

    Prioriteit:
    1. Geconfigureerde sensor (device internal counter — overleeft herstart)
    2. Berekening via W × tijd (fallback)

    Sensortype-detectie:
    - daily_reset: waarde lezen direct
    - cumulative: dagdelta = huidig − dag_start_waarde
    """

    AUTO_DETECT_PATTERNS = {
        "pv": [
            "energy_today", "daily_energy", "today_energy",
            "production_today", "energy_produced", "pv_energy_today",
            "solar_energy_today", "opbrengst_vandaag",
        ],
        "battery_charge": [
            "charged_kwh", "energy_charged", "charge_energy",
            "battery_charge_kwh", "charged_today", "geladen_vandaag",
            # Zonneplan Nexus: production_day = geladen (batterij produceert voor huis)
            "production_day", "productie_vandaag",
        ],
        "battery_discharge": [
            "discharged_kwh", "energy_discharged", "discharge_energy",
            "battery_discharge_kwh", "discharged_today", "ontladen_vandaag",
            # Zonneplan Nexus: delivery_day = ontladen (batterij levert aan huis)
            "delivery_day", "levering_vandaag",
        ],
        "grid_import": [
            "energy_import_today", "import_kwh_today", "electricity_import_today",
            "import_energy_today", "net_import_today", "verbruik_vandaag",
            "electricity_meter_energieverbruik",
        ],
        "grid_export": [
            "energy_export_today", "export_kwh_today", "electricity_export_today",
            "export_energy_today", "net_export_today", "teruglevering_vandaag",
            "electricity_meter_energieproductie",
        ],
        # DSMR P1: tarief 1 (laag/nacht) en tarief 2 (hoog/dag)
        "grid_import_t1": [
            "energieverbruik_tarief_1", "energy_import_tariff1", "import_t1",
            "electricity_delivered_tariff1", "verbruik_tarief_1", "tarief_1",
        ],
        "grid_import_t2": [
            "energieverbruik_tarief_2", "energy_import_tariff2", "import_t2",
            "electricity_delivered_tariff2", "verbruik_tarief_2", "tarief_2",
        ],
        "grid_export_t1": [
            "energieproductie_tarief_1", "energy_export_tariff1", "export_t1",
            "electricity_returned_tariff1", "productie_tarief_1",
        ],
        "grid_export_t2": [
            "energieproductie_tarief_2", "energy_export_tariff2", "export_t2",
            "electricity_returned_tariff2", "productie_tarief_2",
        ],
        "device": [
            "energy_today", "energy_kwh", "daily_energy", "power_consumption_today",
            "kwh_today", "energy_usage_today",
        ],
    }

    def __init__(self, hass, category: str, sensor_entity_id: Optional[str] = None,
                 label: str = "", sensor_type: str = "auto"):
        """
        Args:
            sensor_type: 'daily_reset', 'cumulative', of 'auto' (automatisch detecteren)
        """
        self.hass = hass
        self.category = category
        self.sensor_entity_id = sensor_entity_id
        self.label = label or category
        self._sensor_type = sensor_type  # 'daily_reset', 'cumulative', 'auto'
        self._detected_type: Optional[str] = None  # gecached na eerste detectie

        # Voor cumulatieve sensoren: bewaar dag-startwaarde
        self._day_start_value: Optional[float] = None  # kWh bij begin van de dag
        self._day_start_date: Optional[str] = None     # datum van dag-start

        self._last_read_ok: bool = False

    def _detect_sensor_type(self, entity_id: str, state_class: Optional[str]) -> str:
        """
        Detecteer automatisch of sensor dagelijks reset of cumulatief is.
        Gebruikt state_class, entity_id patronen en eenheden.
        """
        if self._sensor_type != "auto":
            return self._sensor_type

        if self._detected_type:
            return self._detected_type

        # Check eerst entity_id voor bekende dagelijkse reset patronen
        # Sommige integraties (Zonneplan) gebruiken TOTAL_INCREASING voor dagwaarden
        eid_lower_check = entity_id.lower()
        for pat in _DAILY_PATTERNS:
            if pat in eid_lower_check:
                self._detected_type = "daily_reset"
                _LOGGER.debug("EnergySourceManager[%s]: %s → dagelijks reset "
                              "(patroon '%s' overschrijft state_class)",
                              self.label, entity_id, pat)
                return "daily_reset"

        # HA state_class als tweede indicator
        if state_class == "total_increasing" or state_class == "total":
            self._detected_type = "cumulative"
            return "cumulative"
        if state_class == "measurement":
            # measurement kan beide zijn — check naam
            pass

        eid_lower = entity_id.lower()

        # Check cumulatieve patronen
        for pat in _CUMULATIVE_PATTERNS:
            if pat in eid_lower:
                self._detected_type = "cumulative"
                _LOGGER.debug("EnergySourceManager[%s]: %s → cumulatief (patroon: %s)",
                              self.label, entity_id, pat)
                return "cumulative"

        # Check dagelijkse patronen
        for pat in _DAILY_PATTERNS:
            if pat in eid_lower:
                self._detected_type = "daily_reset"
                _LOGGER.debug("EnergySourceManager[%s]: %s → dagelijks reset (patroon: %s)",
                              self.label, entity_id, pat)
                return "daily_reset"

        # Default: daily_reset (veiliger — cumulatief geeft 0 bij eerste dag)
        self._detected_type = "daily_reset"
        return "daily_reset"

    def _to_kwh(self, value: float, unit: str) -> float:
        """Converteer waarde naar kWh op basis van eenheid."""
        factor = _UNIT_TO_KWH.get(unit.lower().strip(), 1.0)
        return round(value * factor, 4)

    def _today_str(self) -> str:
        return datetime.date.today().isoformat()

    def read_kwh(self) -> Optional[float]:
        """
        Lees kWh van sensor voor vandaag.
        - daily_reset: direct lezen
        - cumulative: delta t.o.v. start van de dag
        Retourneert None als sensor niet beschikbaar.
        """
        if not self.sensor_entity_id:
            return None
        try:
            state = self.hass.states.get(self.sensor_entity_id)
            if state is None or state.state in ("unavailable", "unknown", "", None):
                self._last_read_ok = False
                return None

            raw = float(state.state)
            unit = (state.attributes.get("unit_of_measurement") or "kWh")
            state_class = state.attributes.get("state_class")
            kwh = self._to_kwh(raw, unit)

            sensor_type = self._detect_sensor_type(self.sensor_entity_id, state_class)
            today = self._today_str()

            if sensor_type == "daily_reset":
                # Direct lezen — sensor reset zelf elke dag
                self._last_read_ok = True
                return kwh

            else:  # cumulative
                # Dagdelta: huidig − dag_start_waarde
                if self._day_start_date != today:
                    # Nieuwe dag (of eerste keer) — reset dag-startwaarde
                    if self._day_start_date is not None and self._day_start_date < today:
                        # Echte dagovergang (niet eerste keer)
                        _LOGGER.debug(
                            "EnergySourceManager[%s]: nieuwe dag %s → dag_start = %.3f kWh",
                            self.label, today, kwh
                        )
                    self._day_start_value = kwh
                    self._day_start_date = today

                delta = kwh - (self._day_start_value or 0.0)
                # Sanity: delta mag niet negatief zijn (sensor reset of terugzetting)
                if delta < -0.1:
                    _LOGGER.warning(
                        "EnergySourceManager[%s]: negatieve delta %.3f kWh → dag_start gereset",
                        self.label, delta
                    )
                    self._day_start_value = kwh
                    delta = 0.0

                self._last_read_ok = True
                return round(max(0.0, delta), 4)

        except (ValueError, TypeError, AttributeError) as exc:
            _LOGGER.debug("EnergySourceManager[%s]: leesfout %s: %s",
                          self.label, self.sensor_entity_id, exc)
            self._last_read_ok = False
            return None

    def restore_day_start(self, day_start_value: float, date: str) -> None:
        """Herstel dag-startwaarde na herstart (vanuit persistente opslag)."""
        if date == self._today_str():
            self._day_start_value = day_start_value
            self._day_start_date = date
            _LOGGER.debug("EnergySourceManager[%s]: dag_start hersteld: %.3f kWh op %s",
                          self.label, day_start_value, date)

    def get_persist_state(self) -> dict:
        """Geef persisteerbare staat terug (voor opslaan bij afsluiten/herstart)."""
        return {
            "day_start_value": self._day_start_value,
            "day_start_date":  self._day_start_date,
            "sensor_type":     self._detected_type or self._sensor_type,
        }

    @property
    def has_sensor(self) -> bool:
        return bool(self.sensor_entity_id)

    @property
    def last_ok(self) -> bool:
        return self._last_read_ok

    @property
    def sensor_type_detected(self) -> str:
        return self._detected_type or self._sensor_type

    @staticmethod
    def auto_detect(hass, category: str, existing_sensor: Optional[str] = None,
                    hint_entity_id: Optional[str] = None) -> Optional[str]:
        """Zoek automatisch een geschikte kWh-sensor voor de gegeven categorie."""
        if existing_sensor:
            state = hass.states.get(existing_sensor)
            if state and state.state not in ("unavailable", "unknown"):
                return existing_sensor

        patterns = EnergySourceManager.AUTO_DETECT_PATTERNS.get(category, [])
        if not patterns:
            return None

        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(hass)

            hint_prefix = ""
            if hint_entity_id:
                parts = hint_entity_id.split(".")
                if len(parts) >= 2:
                    hint_prefix = parts[1].rsplit("_", 2)[0].lower()

            candidates = []
            for entry in ent_reg.entities.values():
                if entry.domain != "sensor":
                    continue
                eid = entry.entity_id.lower()
                for pat in patterns:
                    if pat in eid:
                        score = 2 if (hint_prefix and hint_prefix in eid) else 1
                        candidates.append((score, entry.entity_id))
                        break

            if candidates:
                candidates.sort(key=lambda x: -x[0])
                return candidates[0][1]

        except Exception as exc:
            _LOGGER.debug("EnergySourceManager.auto_detect[%s]: %s", category, exc)

        return None

    @staticmethod
    def auto_detect_all(hass, config: dict) -> dict:
        """Scan alle geconfigureerde apparaten en stel kWh-sensoren voor."""
        results = {}

        for i, inv in enumerate(config.get("inverter_configs", [])):
            if not inv.get("energy_sensor"):
                found = EnergySourceManager.auto_detect(hass, "pv",
                                                         hint_entity_id=inv.get("entity_id"))
                if found:
                    results[f"inverter_configs.{i}.energy_sensor"] = found

        for i, bat in enumerate(config.get("battery_configs", [])):
            if not bat.get("charge_kwh_sensor"):
                found = EnergySourceManager.auto_detect(hass, "battery_charge",
                                                         hint_entity_id=bat.get("power_sensor"))
                if found:
                    results[f"battery_configs.{i}.charge_kwh_sensor"] = found
            if not bat.get("discharge_kwh_sensor"):
                found = EnergySourceManager.auto_detect(hass, "battery_discharge",
                                                         hint_entity_id=bat.get("power_sensor"))
                if found:
                    results[f"battery_configs.{i}.discharge_kwh_sensor"] = found

        if not config.get("grid_import_kwh_sensor"):
            found = EnergySourceManager.auto_detect(hass, "grid_import",
                                                     hint_entity_id=config.get("import_power_sensor"))
            if found:
                results["grid_import_kwh_sensor"] = found

        if not config.get("grid_export_kwh_sensor"):
            found = EnergySourceManager.auto_detect(hass, "grid_export",
                                                     hint_entity_id=config.get("export_power_sensor"))
            if found:
                results["grid_export_kwh_sensor"] = found

        for i, dev in enumerate(config.get("nilm_device_configs", [])):
            if not dev.get("energy_sensor"):
                found = EnergySourceManager.auto_detect(hass, "device",
                                                         hint_entity_id=dev.get("entity_id"))
                if found:
                    results[f"nilm_device_configs.{i}.energy_sensor"] = found

        return results
