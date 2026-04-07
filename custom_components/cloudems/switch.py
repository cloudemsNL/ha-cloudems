# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS switch platform."""
from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, MANUFACTURER, ATTRIBUTION
from .sub_devices import sub_device_info, SUB_PV_DIMMER, SUB_SHUTTER, SUB_LAMP, SUB_BATTERY, SUB_GRID
from .coordinator import CloudEMSCoordinator


def _eid(entry, entity_id: str) -> str:
    """Demo-aware entity_id helper."""
    from .const import WIZARD_MODE_DEMO, CONF_WIZARD_MODE
    data = {**entry.data, **entry.options}
    if data.get(CONF_WIZARD_MODE) == WIZARD_MODE_DEMO:
        for prefix in ("sensor.", "switch.", "number.", "button.", "climate.", "water_heater."):
            if entity_id.startswith(prefix + "cloudems_"):
                return entity_id.replace(
                    prefix + "cloudems_",
                    prefix + "cloudems_demo_", 1)
    return entity_id


class CloudEMSBlackoutReserveSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Stroomonderbreking reserve schakelaar — default UIT.

    Als AAN: houdt altijd het ingestelde % SoC apart (via number entity).
    """
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:battery-lock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_blackout_reserve_active"
        self._attr_name = "CloudEMS Stroomonderbreking Reserve"
        self.entity_id = _eid(entry, "switch.cloudems_blackout_reserve_actief")
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self._sync_to_bridge()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self._sync_to_bridge()
        self.async_write_ha_state()

    def _sync_to_bridge(self) -> None:
        try:
            zp = getattr(self.coordinator, '_zonneplan_bridge', None)
            if not (zp and hasattr(zp, 'set_blackout_reserve')):
                return
            if self._is_on:
                pct_eid = _eid(self._entry, 'number.cloudems_blackout_reserve_pct')
                st = self.hass.states.get(pct_eid)
                pct = float(st.state) if (st and st.state not in ('unavailable','unknown')) else 20.0
                zp.set_blackout_reserve(pct)
            else:
                zp.set_blackout_reserve(0.0)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("Blackout sync fout: %s", exc)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in ('unavailable', 'unknown'):
            self._is_on = last.state == 'on'
            self._sync_to_bridge()


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
        # v2.6: slaapstand detector — standaard UIT
        CloudEMSSlaapstandSwitch(coordinator, entry),
        # v2.6 Module toggles — aangemaakt door CloudEMS, geen config.yaml nodig
        CloudEMSNILMModuleSwitch(coordinator, entry),
        CloudEMSPeakShavingSwitch(coordinator, entry),
        CloudEMSPhaseBalancingSwitch(coordinator, entry),
        CloudEMSCheapSwitchModule(coordinator, entry),
        CloudEMSNILMLoadShiftSwitch(coordinator, entry),  # v4.6.218
        CloudEMSBudgetSwitch(coordinator, entry),          # v4.6.239
        CloudEMSPVForecastSwitch(coordinator, entry),
        CloudEMSShadowDetectorSwitch(coordinator, entry),
        CloudEMSSolarLearnerSwitch(coordinator, entry),
        CloudEMSClimateMgrSwitch(coordinator, entry),
        CloudEMSBoilerSwitch(coordinator, entry),
        CloudEMSEVChargerSwitch(coordinator, entry),
        CloudEMSBatterySchedulerSwitch(coordinator, entry),
        CloudEMSZonneplanAutoForecastSwitch(coordinator, entry),
        CloudEMSERESwitch(coordinator, entry),
        CloudEMSWeeklyInsightsSwitch(coordinator, entry),
        CloudEMSNotificationsSwitch(coordinator, entry),
        CloudEMSLampCirculationSwitch(coordinator, entry),
        CloudEMSEBikeSwitch(coordinator, entry),
        CloudEMSZwembadSwitch(coordinator, entry),
        CloudEMSRolluikenSwitch(coordinator, entry),
        # v5.5.168: Stroomonderbreking reserve — default UIT
        CloudEMSBlackoutReserveSwitch(coordinator, entry),
    ]
    # Altijd 9 dimmer-schakelaar slots — unavailable als slot niet geconfigureerd is
    _inv_cfg_src = {**entry.data, **entry.options}
    inv_cfgs = _inv_cfg_src.get(CONF_INVERTER_CONFIGS, [])
    for slot in range(1, 10):
        inv_cfg = inv_cfgs[slot - 1] if slot <= len(inv_cfgs) else None
        entities.append(CloudEMSInverterDimmerSwitch(coordinator, entry, slot, inv_cfg))

    # Per-rolluik automaat schakelaar
    shutter_cfgs = entry.options.get("shutter_configs") or entry.data.get("shutter_configs", [])
    for sc in shutter_cfgs:
        cover_id = sc.get("entity_id", "") or sc.get("cover_entity_id", "")
        if cover_id:
            label = sc.get("label") or cover_id.split(".")[-1].replace("_", " ").title()
            entities.append(CloudEMSShutterAutoSwitch(coordinator, entry, cover_id, label))
            entities.append(CloudEMSShutterLearnSwitch(coordinator, entry, cover_id, label))

    async_add_entities(entities, update_before_add=False)



class CloudEMSSmartEVSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Schakelaar voor slim EV laden op zonne-overschot."""
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_smart_ev"
        self._attr_name = "CloudEMS Slim EV Laden"
        self.entity_id = _eid(entry, "switch.cloudems_slim_ev_laden")
        self._smart_ev_enabled = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._smart_ev_enabled = last.state == "on"

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
        self.entity_id = _eid(entry, "switch.cloudems_nilm_actief")
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
        self.entity_id = _eid(entry, "switch.cloudems_hybridnilm_actief")
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
        self.entity_id = _eid(entry, "switch.cloudems_nilm_sessietracking_hmm")
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
        self.entity_id = _eid(entry, "switch.cloudems_nilm_bayesian_classifier")
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
        self.entity_id = _eid(entry, f"switch.cloudems_zonnedimmer_{slot}")
        self._entry = entry
        # Verberg lege slots
        if not self._inv_eid:
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_PV_DIMMER)

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



# ══════════════════════════════════════════════════════════════════════════════
# v2.6 — Module Toggle Switches (aangemaakt door CloudEMS, geen config.yaml nodig)
# ══════════════════════════════════════════════════════════════════════════════

def _device_info_switch(entry):
    from .const import DOMAIN
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "CloudEMS",
        "manufacturer": "CloudEMS",
        "suggested_area": "CloudEMS",
    }


class _CloudEMSModuleSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Basis voor module-toggle switches. Lees/schrijf een bool-attr op de coordinator.

    Gebruikt RestoreEntity zodat de schakelaarstaat na herstart hersteld wordt
    — onafhankelijk van hoe de coordinator de attr initialiseerde.
    """

    _attr_icon = "mdi:toggle-switch-outline"
    _coordinator_attr: str = ""      # e.g. "_nilm_active"
    _default_state: bool   = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._coordinator_attr.lstrip('_')}_module_toggle"

    @property
    def device_info(self):
        return _device_info_switch(self._entry)

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator, self._coordinator_attr, self._default_state))

    async def async_added_to_hass(self) -> None:
        """Herstel schakelaarstaat na herstart via RestoreEntity."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            val = last.state == "on"
            setattr(self.coordinator, self._coordinator_attr, val)
            _LOGGER.debug(
                "CloudEMS module toggle %s hersteld: %s",
                self._coordinator_attr, "AAN" if val else "UIT",
            )

    async def async_turn_on(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, True)
        self.async_write_ha_state()
        if hasattr(self.coordinator, "_save_nilm_toggles"):
            await self.coordinator._save_nilm_toggles()

    async def async_turn_off(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, False)
        self.async_write_ha_state()
        if hasattr(self.coordinator, "_save_nilm_toggles"):
            await self.coordinator._save_nilm_toggles()


class CloudEMSSlaapstandSwitch(_CloudEMSModuleSwitch):
    """Schakelaar voor de slaapstand detector (v3.9) — persistentie via RestoreEntity."""
    _attr_name  = "CloudEMS Slaapstand Actief"
    _attr_icon  = "mdi:sleep"
    _coordinator_attr = "_sleep_detector_enabled"
    _default_state    = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_sleep_detector_enabled"
        self.entity_id = _eid(entry, "switch.cloudems_slaapstand_actief")

    @property
    def is_on(self) -> bool:
        det = getattr(self.coordinator, "_sleep_detector", None)
        if det is not None:
            return det.enabled
        return getattr(self.coordinator, self._coordinator_attr, False)

    async def async_turn_on(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, True)
        det = getattr(self.coordinator, "_sleep_detector", None)
        if det is not None:
            det.set_enabled(True)
        await self.coordinator._save_nilm_toggles()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, False)
        det = getattr(self.coordinator, "_sleep_detector", None)
        if det is not None:
            det.set_enabled(False)
        await self.coordinator._save_nilm_toggles()
        self.async_write_ha_state()


class CloudEMSNILMModuleSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS NILM Apparaatdetectie"
    _attr_icon = "mdi:blur-radial"
    _coordinator_attr = "_nilm_active"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_nilm")


class CloudEMSPeakShavingSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Piekbeperking"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _coordinator_attr = "_peak_shaving_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_piekbeperking")


class CloudEMSPhaseBalancingSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Faseverdeling"
    _attr_icon = "mdi:sine-wave"
    _coordinator_attr = "_phase_balancing_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_faseverdeling")


class CloudEMSCheapSwitchModule(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Goedkope Uren Schakelaars"
    _attr_icon = "mdi:clock-check-outline"
    _coordinator_attr = "_cheap_switch_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_goedkope_uren")


class CloudEMSBudgetSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Energiebudget"
    _attr_icon = "mdi:cash-check"
    _coordinator_attr = "_budget_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_budget")


class CloudEMSNILMLoadShiftSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS NILM Lastverschuiving"
    _attr_icon = "mdi:swap-horizontal-bold"
    _coordinator_attr = "_nilm_load_shifting_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_nilm_load_shift")


class CloudEMSPVForecastSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS PV-prognose & Azimuth"
    _attr_icon = "mdi:solar-power"
    _coordinator_attr = "_pv_forecast_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_pv_forecast")


class CloudEMSShadowDetectorSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Schaduwdetectie"
    _attr_icon = "mdi:weather-sunset"
    _coordinator_attr = "_shadow_detector_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_schaduw")


class CloudEMSSolarLearnerSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS SolarLearner Fase-detectie"
    _attr_icon = "mdi:lightning-bolt-circle"
    _coordinator_attr = "_solar_learner_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_solar_learner")


class CloudEMSClimateMgrSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Slim Klimaatbeheer"
    _attr_icon = "mdi:home-thermometer-outline"
    _coordinator_attr = "_climate_mgr_override"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_klimaat")

    @property
    def is_on(self) -> bool:
        # Climate uses config flag + optional override
        override = getattr(self.coordinator, "_climate_mgr_override", None)
        if override is not None:
            return bool(override)
        return bool(self.coordinator._config.get("climate_mgr_enabled", False))


class CloudEMSBoilerSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Boiler Sturing"
    _attr_icon = "mdi:fire"
    _coordinator_attr = "_boiler_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_ketel")


class CloudEMSEVChargerSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS EV-lader Sturing"
    _attr_icon = "mdi:ev-station"
    _coordinator_attr = "_ev_charger_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_ev_lader")


class CloudEMSBatterySchedulerSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Thuisbatterij Scheduler"
    _attr_icon = "mdi:battery-charging"
    _coordinator_attr = "_battery_sched_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_batterij")



    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)
class CloudEMSZonneplanAutoForecastSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Schakelaar voor Zonneplan/Nexus vendor-specifieke batterijsturing.

    AAN = CloudEMS stuurt de Nexus-batterij automatisch via PV-forecast + EPEX.
    UIT = Nexus werkt op de eigen Zonneplan Powerplay-logica (geen CloudEMS bemoeienis).
    Alleen zichtbaar/actief als de Zonneplan integratie gedetecteerd is.
    """
    _attr_name = "CloudEMS Zonneplan Nexus Auto-sturing"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_zonneplan_auto_forecast"
        self.entity_id = _eid(entry, "switch.cloudems_zonneplan_auto_sturing")

    @property
    def device_info(self):
        return _device_info_switch(self._entry)

    @property
    def available(self) -> bool:
        """Alleen beschikbaar als Zonneplan integratie actief is."""
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        return zb is not None and zb.is_available

    @property
    def is_on(self) -> bool:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        if zb and hasattr(zb, "_auto_forecast_enabled"):
            return bool(zb._auto_forecast_enabled)
        return bool(getattr(self.coordinator, "_zonneplan_auto_forecast", False))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            val = last.state == "on"
            self._apply(val)

    def _apply(self, val: bool) -> None:
        setattr(self.coordinator, "_zonneplan_auto_forecast", val)
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        if zb and hasattr(zb, "_auto_forecast_enabled"):
            zb._auto_forecast_enabled = val

    async def async_turn_on(self, **kwargs):
        self._apply(True)
        self.async_write_ha_state()
        if hasattr(self.coordinator, "_save_nilm_toggles"):
            await self.coordinator._save_nilm_toggles()

    async def async_turn_off(self, **kwargs):
        self._apply(False)
        self.async_write_ha_state()
        if hasattr(self.coordinator, "_save_nilm_toggles"):
            await self.coordinator._save_nilm_toggles()

    @property
    def extra_state_attributes(self) -> dict:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        if not zb:
            return {"description": "Zonneplan integratie niet gevonden."}
        return {
            "description": (
                "AAN: CloudEMS stuurt Zonneplan Nexus via PV-forecast + EPEX-tarieven. "
                "UIT: Nexus volgt eigen Zonneplan Powerplay-logica."
            ),
            "available": zb.is_available,
            "active_mode": getattr(zb, "_last_mode", None),
        }


class CloudEMSERESwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS ERE Certificaten"
    _attr_icon = "mdi:certificate-outline"
    _coordinator_attr = "_ere_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_ere")


class CloudEMSWeeklyInsightsSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Wekelijkse Inzichten"
    _attr_icon = "mdi:chart-line"
    _coordinator_attr = "_weekly_insights_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_inzichten")


class CloudEMSNotificationsSwitch(_CloudEMSModuleSwitch):
    _attr_name = "CloudEMS Notificaties"
    _attr_icon = "mdi:bell-outline"
    _coordinator_attr = "_notifications_enabled"
    _default_state = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_notificaties")


class CloudEMSLampCirculationSwitch(_CloudEMSModuleSwitch):
    """Module toggle voor Lampcirculatie & Beveiliging."""
    _attr_name = "CloudEMS Lampcirculatie"
    _attr_icon = "mdi:lightbulb-group-outline"
    _coordinator_attr = "_lamp_circulation_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_lampcirculatie")

    async def async_turn_off(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, False)
        # Propageer direct naar LampCirculationController
        lc = getattr(self.coordinator, "_lamp_circulation", None)
        if lc and hasattr(lc, "set_enabled"):
            lc.set_enabled(False)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        setattr(self.coordinator, self._coordinator_attr, True)
        lc = getattr(self.coordinator, "_lamp_circulation", None)
        if lc and hasattr(lc, "set_enabled"):
            lc.set_enabled(True)
        self.async_write_ha_state()



    @property
    def device_info(self): return sub_device_info(self._entry, SUB_LAMP)
class CloudEMSEBikeSwitch(_CloudEMSModuleSwitch):
    """Module toggle voor E-bike & Scooter tracking."""
    _attr_name = "CloudEMS E-bike Module"
    _attr_icon = "mdi:bicycle-electric"
    _coordinator_attr = "_ebike_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_ebike")


class CloudEMSZwembadSwitch(_CloudEMSModuleSwitch):
    """Module toggle voor Zwembad Controller."""
    _attr_name = "CloudEMS Zwembad Module"
    _attr_icon = "mdi:pool"
    _coordinator_attr = "_pool_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_zwembad")


class CloudEMSRolluikenSwitch(_CloudEMSModuleSwitch):
    """Module toggle voor Rolluiken Controller."""
    _attr_name = "CloudEMS Rolluiken Module"

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_SHUTTER)

    _attr_icon = "mdi:blinds"
    _coordinator_attr = "_shutter_enabled"
    _default_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = _eid(entry, "switch.cloudems_module_rolluiken")


class CloudEMSShutterAutoSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Per-rolluik automaat schakelaar. Aan = CloudEMS stuurt dit rolluik, Uit = CloudEMS laat het met rust."""

    _attr_icon = "mdi:robot"

    def __init__(self, coordinator, entry, cover_entity_id: str, label: str):
        super().__init__(coordinator)
        self._entry = entry
        self._cover_id = cover_entity_id
        safe = cover_entity_id.split(".")[-1].replace("-", "_")
        self._attr_unique_id = f"{entry.entry_id}_shutter_{safe}_auto"
        self._attr_name = f"CloudEMS Automaat {label}"
        self.entity_id = _eid(entry, f"switch.cloudems_shutter_{safe}_auto")

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_SHUTTER)

    @property
    def is_on(self) -> bool:
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return True
        return sc.get_auto_enabled(self._cover_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            sc = getattr(self.coordinator, "_shutter_ctrl", None)
            if sc:
                sc.set_auto_enabled(self._cover_id, last.state == "on")

    async def async_turn_on(self, **kwargs):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc:
            sc.set_auto_enabled(self._cover_id, True)
            self.hass.async_create_task(self.coordinator.async_request_refresh())
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc:
            sc.set_auto_enabled(self._cover_id, False)
            self.hass.async_create_task(self.coordinator.async_request_refresh())
        self.async_write_ha_state()


class CloudEMSShutterLearnSwitch(CoordinatorEntity, SwitchEntity):
    """Per-rolluik schakelaar voor tijdschema-leren (v4.6.157).
    Aan = CloudEMS leert open/sluit tijden van gebruikspatroon.
    Uit = vaste tijden uit configuratie.
    """

    _attr_icon = "mdi:school"

    def __init__(self, coordinator, entry, cover_entity_id: str, label: str):
        super().__init__(coordinator)
        self._entry = entry
        self._cover_id = cover_entity_id
        safe = cover_entity_id.split(".")[-1].replace("-", "_")
        self._attr_unique_id = f"{entry.entry_id}_shutter_{safe}_learning"
        self._attr_name = f"CloudEMS Tijdleren {label}"
        self.entity_id = _eid(entry, f"switch.cloudems_shutter_{safe}_learning")

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_SHUTTER)

    @property
    def is_on(self) -> bool:
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return True
        return sc.get_schedule_learning(self._cover_id)

    async def async_turn_on(self, **kwargs):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc:
            sc.set_schedule_learning(self._cover_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc:
            sc.set_schedule_learning(self._cover_id, False)
        self.async_write_ha_state()
