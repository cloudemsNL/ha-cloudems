
## v1.15.3-final — Complete implementation (2025-03-04)

### Added (this session)
- **HeatPumpCOPLearner** (`energy_manager/heat_pump_cop.py`)
  - Learns COP curve grouped per 2°C outdoor temperature bucket
  - 3 methods: direct (thermal sensor), thermal model (W/K × ΔT), formula fallback
  - Defrost cycle detection & exclusion from curve learning
  - Produces: cop_current, cop_at_7c/2c/−5c, defrost_today, curve dict
  - Inspired by HeatPumpAutoDetect in CloudEMS v7 TuyaWizard

- **PV Forecast: global_tilted_irradiance** (`pv_forecast.py`)
  - Open-Meteo API now uses `global_tilted_irradiance` with learned panel tilt/azimuth
  - Cascade fallback: global_tilted → direct_radiation → shortwave_radiation
  - Open-Meteo `azimuth` param converted from HA convention (0=N) to OM (0=S)

- **Thermal Model: Open-Meteo outdoor temp fallback** (`thermal_model.py`)
  - `async_fetch_outdoor_temp()`: fetches current_temperature_2m from Open-Meteo
  - 15-minute cache; used when no outdoor temp sensor is configured in HA
  - Returns cached (stale) value on network failure

- **Contract type: dynamisch / vast tarief** (`config_flow.py`, `coordinator.py`)
  - New `contract_type` setting: `dynamic` (EPEX) or `fixed`
  - Fixed mode: synthetic flat 24h price_info at user-entered tariff
  - Both import (consumption) and export (feed-in) tariffs separately configurable

- **DSMR5 per-phase export sensors** (`config_flow.py`, `coordinator.py`)
  - `power_sensor_l1/l2/l3_export`: optional per-phase backfeed sensors
  - Netto_fase = import_fase − export_fase before NILM ingestion

- **Config flow restructured**
  - Step 4 renamed: "Solar & EV" → "EV Charger"
  - New options section: "🔥 Gas & Warmte" (gas sensors, boiler, HP COP, HP sensors)
  - Contract type moved to "💶 Prijzen & Belasting" section

- **Zonneplan added to NL supplier list** (markup 1.69 ct/kWh)

- **Dashboard: Warmtepomp COP card** (Inzichten tab)
  - COP now, COP bij 7°C, defrost cycli, methode label
  - Green/orange/red colour coding (≥3.0 / ≥2.0 / <2.0)

### Sources
| Concept | Bronbestand |
|---------|-------------|
| COP bucket learning | CloudEMS v7 `backend/ml/auto_detect.py` HeatPumpAutoDetect |
| COP formula fallback | CloudEMS v7 `backend/ml/auto_detect.py` L194 |
| global_tilted_irradiance | Smart Boiler v2.2.54 YAML L24712 |
| Open-Meteo outdoor temp | Smart Boiler v2.2.54 YAML L31528 |
| PresenceDetector energy scoring | CloudEMS v7 `services/smarthome_intelligence.py` |
| ClimateOptimizer pre-heat | CloudEMS v7 `services/smarthome_intelligence.py` |
