# -*- coding: utf-8 -*-
"""CloudEMS switch platform."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu
from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, MANUFACTURER, ATTRIBUTION
from .coordinator import CloudEMSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    from .const import CONF_INVERTER_CONFIGS
    entities = [
        CloudEMSSmartEVSwitch(coordinator, entry),
        # v1.22: NILM-schakelaars — standaard UIT voor gecontroleerd testen
        CloudEMSNILMSwitch(coordinator, entry),
        CloudEMSHybridNILMSwitch(coordinator, entry),
        CloudEMSNILMHMMSwitch(coordinator, entry),
        # v1.23: Bayesian posterior classifier
        CloudEMSNILMBayesSwitch(coordinator, entry),
    ]
    # Altijd 9 dimmer-schakelaar slots — unavailable als slot niet geconfigureerd is
    _inv_cfg_src = {**entry.data, **entry.options}
    inv_cfgs = _inv_cfg_src.get(CONF_INVERTER_CONFIGS, [])
    for slot in range(1, 10):
        inv_cfg = inv_cfgs[slot - 1] if slot <= len(inv_cfgs) else None
        entities.append(CloudEMSInverterDimmerSwitch(coordinator, entry, slot, inv_cfg))
    async_add_entities(entities)



class CloudEMSSmartEVSwitch(CoordinatorEntity, SwitchEntity):
    """Schakelaar voor slim EV laden op zonne-overschot."""
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_smart_ev"
        self._attr_name = "CloudEMS Slim EV Laden"
        self.entity_id = "switch.cloudems_slim_ev_laden"
        self._smart_ev_enabled = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self._smart_ev_enabled

    async def async_turn_on(self, **kwargs):
        self._smart_ev_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._smart_ev_enabled = False
        self.async_write_ha_state()


# ── v1.22: NILM-schakelaars ───────────────────────────────────────────────────

class CloudEMSNILMSwitch(CoordinatorEntity, SwitchEntity):
    """
    Hoofdschakelaar NILM-motor.

    UIT (default): NILM verwerkt geen events, apparaten worden niet gedetecteerd.
                   Geen CPU-impact, geen false positives.
    AAN:           NILM detecteert actief apparaten via vermogenssignaturen.

    Gebruik: zet AAN om te starten met leren, UIT om het systeem te pauzeren
    of om te vergelijken hoe de energiedashboard eruit ziet zonder NILM.
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:home-analytics"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_active"
        self._attr_name = "CloudEMS NILM Actief"
        self.entity_id = "switch.cloudems_nilm_actief"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.nilm_active

    async def async_turn_on(self, **kwargs):
        try:
            await self.coordinator.set_nilm_active(True)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM aan zetten mislukt: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        try:
            await self.coordinator.set_nilm_active(False)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM uit zetten mislukt: %s", err)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "description": (
                "Hoofdschakelaar NILM-apparaatdetectie. "
                "UIT = geen detectie, AAN = actief leren."
            ),
        }


class CloudEMSHybridNILMSwitch(CoordinatorEntity, SwitchEntity):
    """
    Schakelaar HybridNILM-verrijkingslaag.

    UIT (default): Alleen basisdetectie via vermogenssignaturen (database).
    AAN:           Extra lagen actief — smart plug ankering, Bayesiaanse priors,
                   3-fase balansanalyse en DSMR5 fase-correlatie.

    Zet AAN als NILM-basis goed werkt en je de nauwkeurigheid verder wil
    verbeteren via smart plugs en contextinformatie.
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:layers-triple"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_hybrid_nilm_active"
        self._attr_name = "CloudEMS HybridNILM Actief"
        self.entity_id = "switch.cloudems_hybridnilm_actief"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.hybrid_nilm_active

    async def async_turn_on(self, **kwargs):
        try:
            await self.coordinator.set_hybrid_nilm_active(True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("CloudEMS HybridNILM aan zetten mislukt: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        try:
            await self.coordinator.set_hybrid_nilm_active(False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("CloudEMS HybridNILM uit zetten mislukt: %s", err)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        diag = {}
        if self.coordinator._hybrid:
            d = self.coordinator._hybrid.get_diagnostics()
            diag = {
                "anchors_total":   d.get("anchors_total", 0),
                "anchors_active":  d.get("anchors_active", 0),
                "temperature_c":   d.get("weather_temperature_c"),
                "season":          d.get("weather_season"),
            }
        return {
            "description": (
                "HybridNILM voegt smart plug ankering, Bayesiaanse contextpriors "
                "en 3-fase balansanalyse toe bovenop de basis NILM-detectie."
            ),
            **diag,
        }


class CloudEMSNILMHMMSwitch(CoordinatorEntity, SwitchEntity):
    """
    Schakelaar NILM HMM sessietracking.

    UIT (default): Losse NILM-events worden apart bijgehouden (klassiek gedrag).
    AAN:           Wasmachine, droger en vaatwasser worden als één sessie
                   bijgehouden (correcte kWh per was/droogbeurt, programmatype).

    Vereist dat NILM Actief ook AAN staat.
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_hmm_active"
        self.entity_id = "switch.cloudems_nilm_sessietracking_hmm"
        self._attr_name = "CloudEMS NILM Sessietracking (HMM)"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.nilm_hmm_active

    async def async_turn_on(self, **kwargs):
        try:
            await self.coordinator.set_nilm_hmm_active(True)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM HMM aan zetten mislukt: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        try:
            await self.coordinator.set_nilm_hmm_active(False)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM HMM uit zetten mislukt: %s", err)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {
            "description": (
                "HMM sessietracking groepeert sub-events van wasmachine, droger "
                "en vaatwasser tot één sessie met correcte kWh en programmatype."
            ),
        }
        if self.coordinator.nilm_hmm_active and self.coordinator._hmm:
            sessions = self.coordinator._hmm.get_active_sessions()
            attrs["active_sessions"] = len(sessions)
            if sessions:
                attrs["sessions"] = sessions
        return attrs


# ── v1.23: Bayesian classifier schakelaar ─────────────────────────────────────

class CloudEMSNILMBayesSwitch(CoordinatorEntity, SwitchEntity):
    """
    Schakelaar Bayesian NILM posterior classifier.

    UIT (default): Confidence-scores komen puur uit database/AI-signatures.
    AAN:           Een Bayesiaanse posterior wordt berekend per apparaattype,
                   gebaseerd op tijdstip, seizoen en temperatuur als prior, en
                   de Gaussische vermogensmatch als likelihood.

    Veiligheidsregel: de Bayesian laag kan nooit een lagere confidence geven
    dan de originele — hij verbetert alleen, verslechtert nooit.
    Het systeem leert priors bij na confirmed events.
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:chart-bell-curve-cumulative"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_bayes_active"
        self.entity_id = "switch.cloudems_nilm_bayesian_classifier"
        self._attr_name = "CloudEMS NILM Bayesian Classifier"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.nilm_bayes_active

    async def async_turn_on(self, **kwargs):
        try:
            await self.coordinator.set_nilm_bayes_active(True)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM Bayes aan zetten mislukt: %s", err)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        try:
            await self.coordinator.set_nilm_bayes_active(False)
        except Exception as err:
            _LOGGER.error("CloudEMS NILM Bayes uit zetten mislukt: %s", err)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {
            "description": (
                "Bayesian posterior classifier verbetert confidence op basis van "
                "tijdstip, seizoen en temperatuur als prior. "
                "Kan nooit een match verslechteren, alleen verbeteren."
            ),
        }
        bayes = getattr(self.coordinator, "_bayes", None)
        if bayes:
            diag = bayes.get_diagnostics()
            attrs["calls_total"]    = diag.get("calls_total", 0)
            attrs["boost_rate_pct"] = diag.get("boost_rate_pct", 0)
            attrs["top_priors"]     = diag.get("top_priors_now", {})
        return attrs


# ═══════════════════════════════════════════════════════════════════════════════
# v1.24.0 — Per-inverter solar dimmer on/off switch
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInverterDimmerSwitch(CoordinatorEntity, SwitchEntity):
    """Zonnedimmer aan/uit schakelaar voor omvormer slot 1-9.

    Altijd aangemaakt voor alle 9 slots. Slots zonder geconfigureerde omvormer
    zijn unavailable en worden verborgen in HA. Entity_id is stabiel: 
    switch.cloudems_zonnedimmer_schakelaar_1 t/m _9.
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:solar-power-variant"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: "CloudEMSCoordinator",
        entry: "ConfigEntry",
        slot: int,
        inv_cfg: dict | None,
    ) -> None:
        super().__init__(coordinator)
        self._slot    = slot
        self._inv_cfg = inv_cfg
        self._inv_eid = inv_cfg.get("entity_id", "") if inv_cfg else ""
        self._label = inv_cfg.get("label", f"Omvormer {slot}") if inv_cfg else f"Omvormer {slot}"
        self._attr_unique_id = f"{entry.entry_id}_inv_dimmer_sw_{slot}"
        self._attr_name      = f"CloudEMS PV Dimmer {self._label}"
        self.entity_id       = f"switch.cloudems_zonnedimmer_{slot}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "CloudEMS",
            "manufacturer": MANUFACTURER,
        }

    @property
    def available(self) -> bool:
        return bool(self._inv_eid)

    @property
    def is_on(self) -> bool:
        if not self._inv_eid:
            return False
        mgr = self.coordinator._multi_inv_manager
        if mgr is None:
            return True
        return mgr._dimmer_enabled.get(self._inv_eid, True)

    async def async_turn_on(self, **kwargs):
        if self._inv_eid:
            mgr = self.coordinator._multi_inv_manager
            if mgr:
                mgr.set_dimmer_enabled(self._inv_eid, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        if self._inv_eid:
            mgr = self.coordinator._multi_inv_manager
            if mgr:
                mgr.set_dimmer_enabled(self._inv_eid, False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        base = {"slot": self._slot, "inverter_id": self._inv_eid or None, "label": self._label}
        if not self._inv_eid:
            return base
        mgr = self.coordinator._multi_inv_manager
        if mgr is None:
            return base
        return {**base, **mgr.get_dimmer_state(self._inv_eid)}
