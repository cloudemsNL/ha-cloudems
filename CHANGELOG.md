# Changelog

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.0.0/).

---

## [2.4.0] — 2026-03-06

### Bugfix — Dashboard "Entiteit niet gevonden" reparaties

- **`sensor.cloudems_energy_cost`**: sensor heette `CloudEMS Kosten Vandaag` (→ `kosten_vandaag`), dashboard verwachtte `energy_cost`. Naam gecorrigeerd naar `CloudEMS Energy Cost` + expliciete `entity_id` override.
- **`sensor.cloudems_flexibel_vermogen`**: sensor heette `CloudEMS Flex Score` (→ `flex_score`), dashboard verwachtte `flexibel_vermogen`. Naam gecorrigeerd + entity_id override.
- **`sensor.cloudems_warmtepomp_cop`**: sensor ontbrak volledig in de entity-registratie. Nieuwe `CloudEMSWarmtepompCOPSensor` klasse toegevoegd met COP-waarden, degradatiedetectie en alle dashboard-attributen (`cop_report`, `degradation_detected`, `degradation_pct`, `degradation_advice`, `cop_at_7c`).
- **`coordinator.py`**: `hp_cop_data` aangevuld met `degradation_detected`, `degradation_pct` en `degradation_advice` uit `COPReport`.

---

## [2.4.1] — 2026-03-06

### Bugfix
- `sensor.cloudems_battery_soc`: entity_id mismatch opgelost — sensor heette "Battery · State of Charge" → genereerde `sensor.cloudems_battery_state_of_charge`, dashboard verwachtte `sensor.cloudems_battery_soc`. Hernoemd naar "Battery · SoC".
- `sensor.cloudems_p1_power`: entity_id mismatch opgelost — sensor heette "Grid · P1 Net Power" → genereerde `sensor.cloudems_grid_p1_net_power`, dashboard verwachtte `sensor.cloudems_p1_power`. Hernoemd naar "CloudEMS P1 Power".
- `sensor.cloudems_nilm_diagnostics`, `sensor.cloudems_nilm_sensor_input`, `sensor.cloudems_nilm_devices`, `sensor.cloudems_nilm_running_devices`, `sensor.cloudems_nilm_running_devices_power`, `sensor.cloudems_ai_status`, `sensor.cloudems_nilm_hybride_status`: expliciete `entity_id` override toegevoegd om te garanderen dat de entiteit-ID overeenkomt met het dashboard, ongeacht eerder in het HA entity registry opgeslagen waarden.

---



### Bugfix
- `MicroMobilityTracker`: attribuut `_last_seen` ontbrak in `__init__` → `AttributeError` opgelost

---

## [2.2.0] — 2026-03-06

### Toegevoegd
- **Watchdog** (`watchdog.py`): bewaakt de coordinator op herhaalde crashes
  - Na 3 opeenvolgende `UpdateFailed` errors → automatische reload van de config entry
  - Exponential backoff: 30s → 60s → ... max 1 uur tussen herstarts
  - Crashgeschiedenis persistent opgeslagen in HA storage
  - `sensor.cloudems_watchdog` met status `ok` / `warning` / `critical`
  - Watchdog-kaart op het Diagnose tabblad: teller, foutmelding, crashhistorie

---

## [2.1.9] — 2026-03-06

### Bugfix
- `CloudEMSNILMDeviceSensor`: `extra_state_attributes` miste `@property` decorator → `TypeError: 'method' object is not iterable` bij toevoegen van NILM-entiteiten opgelost
- `_source_type`: ongeldige `@property` + `@staticmethod` combinatie verwijderd

---

## [2.1.8] — 2026-03-06

### Gewijzigd — NILM detectie minder streng, false positives worden actief verwijderd
- `NILM_MIN_CONFIDENCE`: 0.80 → **0.55** — meer apparaten zichtbaar (ook twijfelgevallen)
- `NILM_HIGH_CONFIDENCE`: 0.92 → **0.80** — eerder tonen zonder extra AI-bevestiging
- `STEADY_STATE_DELAY_S`: 35s → **20s** — snellere false positive detectie
- `STEADY_STATE_MIN_RATIO`: 0.50 → **0.40** — soepelere steady-state validatie
- Onbevestigde false positives worden nu **actief verwijderd** (was: confidence halveren)
- Bevestigde apparaten bij validatie-fail: confidence × 0.65 (was: × 0.50), blijven staan

---

## [2.1.7] — 2026-03-05

### Toegevoegd
- 9 nieuwe dashboardkaarten voor sensoren die nog geen dashboard-representatie hadden:
  - 🏠 Aanwezigheidsdetector (`sensor.cloudems_absence_detector`)
  - 🌡️ Slim Voorverwarmen (`sensor.cloudems_climate_preheat`)
  - ⏰ Goedkoopste 4-uurs Blok (`sensor.cloudems_cheapest_4h_block`)
  - 🛡️ Sensor Kwaliteitscheck (`sensor.cloudems_sensor_sanity`)
  - 🎯 PV Voorspelling Nauwkeurigheid (`sensor.cloudems_pv_forecast_accuracy`)
  - 💰 PV Opbrengst & Terugverdientijd (`sensor.cloudems_pv_opbrengst_terugverdientijd`)
  - 📊 EMA Sensor Diagnostiek (`sensor.cloudems_ema_diagnostics`)
  - 🗄️ NILM Database Status (`sensor.cloudems_nilm_db`)
  - 📡 P1 Direct Netmeting (`sensor.cloudems_p1_power`)
- NILM Live Activiteit monitor op NILM Beheer tabblad
- Dashboard footers gestandaardiseerd: één gecombineerde footer per tab, altijd als laatste kaart

### Bugfix
- Micro-mobiliteit voertuigprofielen tabel: ruwe dict-dump vervangen door opgemaakte markdown tabel
- Flexibel Vermogen Score: Jinja whitespace bugfix in tabel-rendering (`{%- for %}`)

---

## [2.1.6] — eerder

### Toegevoegd
- Multi-omvormer ondersteuning uitgebreid
- Solar power sommering voor modules zonder CONF_SOLAR_SENSOR
- Diverse NILM en energiebeheer verbeteringen
