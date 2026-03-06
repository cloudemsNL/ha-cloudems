<div align="center">

# ⚡ CloudEMS
### Smart Energy Management for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cloudemsNL/ha-cloudems.svg?style=for-the-badge)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg?style=for-the-badge)](https://www.home-assistant.io/)

**Fully local · Privacy-first · No subscription · No extra hardware**

[🌐 cloudems.eu](https://cloudems.eu) &nbsp;·&nbsp; [📖 Wiki](https://github.com/cloudemsNL/ha-cloudems/wiki) &nbsp;·&nbsp; [🐛 Report an issue](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml) &nbsp;·&nbsp; [☕ Buy Me a Coffee](https://buymeacoffee.com/smarthost9m)

</div>

---

CloudEMS is a comprehensive Home Assistant integration that turns your smart meter into an intelligent energy brain. It observes, learns, predicts and acts — automatically aligning every flexible load in your home to the cheapest electricity, maximising your solar self-consumption, protecting your circuits from overload, and keeping your home safe while you're away.

Everything runs **100% locally** on your Home Assistant instance. No cloud subscription required. No data leaves your home.

---

## Installation

### Via HACS (recommended)

1. Open **HACS** → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/cloudemsNL/ha-cloudems` → category **Integration**
3. Search **CloudEMS** → **Download**
4. Restart Home Assistant
5. **Settings** → **Devices & Services** → **+ Add Integration** → search **CloudEMS**
6. Follow the setup wizard

> Choose **Advanced** wizard mode for full control over all sensors, inverters, batteries and P1.

### Manual installation

Download the [latest release](https://github.com/cloudemsNL/ha-cloudems/releases/latest), extract and copy `custom_components/cloudems/` into your HA `config/custom_components/` directory.

---

## Requirements

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1.0 or newer |
| Smart meter | P1 port or compatible integration (DSMR, HomeWizard, Shelly EM, etc.) |
| Python | 3.11+ (built into HA — nothing to install) |
| Ollama | Optional — for local LLM-based NILM classification |

---

## How it works

CloudEMS runs a **10-second update cycle** that continuously reads your smart meter, processes every sensor in the system, and makes real-time decisions. The real power is in the learning:

```
Smart meter → CloudEMS reads → learns patterns → predicts → acts
     ↑                                                          ↓
     └──────────── feedback: was the prediction right? ←───────┘
```

Every module is **self-learning** and **zero-config**. There is nothing to manually tune.

---

## Features

### 🧠 NILM — Appliance detection without extra hardware

Non-Intrusive Load Monitoring identifies individual appliances from the aggregate grid power signal alone. Every power event is compared against an internal signature database, a local scikit-learn model trained on your own confirmed events, and optionally a local Ollama LLM.

**Adaptive thresholds** — the detection threshold automatically calibrates to your installation's noise floor using a rolling 80th-percentile estimator. Quiet P1 meters drop to ~10 W sensitivity; noisy clamp meters stay higher to avoid false triggers.

**False positive removal** — newly detected appliances are validated 20 seconds after the trigger. If the grid baseline hasn't risen as expected, unconfirmed devices are automatically removed. Confirmed (user-verified) devices are never auto-removed.

**Smart Plug Anchoring** — if you have Shelly, Tasmota or ESPHome smart plugs, CloudEMS automatically uses their readings as anchors, improving detection accuracy from ~65% to ~85%+.

**Bayesian classification** — detection scores are adjusted in real-time based on outdoor temperature, time of day, season, and wind direction. The Bayesian layer can only improve confidence, never lower it.

**HMM session tracking** — a Hidden Markov Model tracks multi-state appliances (e.g. washing machines with multiple power levels) to improve on/off boundary detection.

Detection covers: washing machines, dryers, dishwashers, ovens, heat pumps, boilers, EV chargers, refrigerators, TVs, computers and more. Devices are grouped into consumption categories with daily kWh breakdown.

### 💰 Dynamic EPEX prices & cost optimisation

CloudEMS fetches day-ahead electricity prices (EPEX Spot) for NL, DE, AT (no API key) and all ENTSO-E areas (free key required). It identifies the cheapest consecutive-hour windows and exposes them as sensors you can link to any switch or automation.

**Cheapest 4-hour block** — a dedicated sensor always showing the optimal 4-hour charging/heating window for today, with per-hour price breakdown, start/end times, and live countdown to the next block.

**Cheap-hours switch scheduler** — any switch or script can be linked to automatically activate during the cheapest N hours of the day.

**Virtual bill simulator** — continuously records your hourly consumption and EPEX price, then calculates what you would have paid on a fixed tariff, a day/night tariff, or your actual dynamic contract. After 2+ months it tells you exactly how much you're saving (or not).

**Cost forecaster** — predicts today's and tomorrow's total cost based on learned consumption patterns and upcoming EPEX prices, with monthly budget tracking.

**Saldering simulator** — models the phased abolition of net metering in the Netherlands, showing the financial impact over coming years for your specific solar/consumption profile.

### ☀️ Solar optimisation

**Self-learning PV forecast** — builds a statistical model of your solar production by observing your actual inverter output over weeks, blended with Open-Meteo irradiance forecasts. No panel specifications required.

**PV forecast accuracy tracking** — continuously measures MAPE over 14-day and 30-day windows to show how accurate the forecast model has become. Includes bias factor to detect systematic over/under-estimation.

**Solar ROI calculator** — estimates annual yield (kWh), financial value, and payback period based on your detected system size.

**Automatic orientation detection** — derives your panel azimuth and tilt from the shape of your daily yield curves after ~30 clear days.

**Multi-inverter support** — up to 9 inverters tracked independently. CloudEMS learns which grid phase each inverter is on and dims only overloaded phases.

**Clipping loss analysis** — detects when your inverter hits its power limit and calculates kWh lost per day and estimated payback for a larger inverter.

**PV health monitoring** — detects soiling, degradation, and structural shading by comparing recent peak production against an irradiance-adjusted all-time baseline.

### 🔋 Battery management

CloudEMS builds an optimal charge/discharge schedule for each day based on EPEX prices, current SoC, and battery capacity. In summer it detects when solar will fully charge the battery and skips unnecessary night charging.

**Battery degradation tracking** — counts full and partial charge cycles, detects deep discharge and high-SoC stress, and tracks State of Health (SoH) over time with alerts at 90% and 80% SoH.

### 🚗 EV charging

**Dynamic current control** — adjusts your EV charger in real-time using a self-tuning PID controller across three modes: solar surplus, cheap-hours, and phase protection.

**EV session learner** — after ~10 sessions CloudEMS learns your typical plug-in hour, expected kWh per session, and weekday patterns to pre-reserve optimal cheap windows.

### 🌡️ Heat pump intelligence

**COP learning** — tracks your heat pump's Coefficient of Performance grouped by outdoor temperature bucket, with defrost cycle exclusion.

**Degradation detection** — short-term (3–4 week comparison) and year-on-year COP tracking. A sustained drop of 8%+ triggers a maintenance advisory.

**Climate pre-heat scheduling** — calculates the optimal pre-heat moment based on the thermal house model, current EPEX price ratio, and configurable setpoint offset.

### ⚡ Phase management

Monitors import and export current per phase (L1/L2/L3) every 10 seconds with automatic load shedding in priority order when limits are approached.

**Phase balancing** — detects structural imbalance and provides concrete re-wiring advice. **Peak shaving** — configurable import limit for capacity tariff management. **Grid congestion** — automatic shedding during high-price hours.

### 🏠 Presence & absence detection

Determines occupancy purely from energy consumption patterns — no GPS, no login events. States: home, away, sleeping, vacation. Reports confidence percentage and standby power level.

Drives lamp circulation, climate pre-heat, EV charging priority, and energy saving automations automatically.

### 💡 Lamp circulation & burglary deterrence

When nobody is home, CloudEMS activates a lamp circulation system that makes the house appear occupied:

- **Random intervals** — Gaussian-distributed timing (2–8 min), no two evenings identical
- **Behaviour mimicry** — learns which lamps you personally use at which hour
- **Seasonal intelligence** — starts/stops based on actual sunset via `sun.sun`
- **PIR bypass** — lamps paired with motion sensors are excluded while motion is detected
- **Passive phase detection** — every switch event passively determines which grid phase that lamp is on
- **Negative price bonus** — extends intervals when EPEX price is negative

### 🏊 Pool controller

Manages filtration and heating intelligently: PV surplus mode, cheapest EPEX hours fallback, temperature-adjusted daily minimum runtime, and COP-optimised heat pump scheduling.

### 🚲 Micro-mobility tracker

Detects and tracks e-bike and scooter charging sessions (40–700 W) using non-overlapping power classification ranges. Builds a learning profile per vehicle with session history, average kWh, peak charge hour, and optimal charging time recommendations.

### 📊 Home intelligence

**Thermal house model** — learns your home's thermal loss coefficient (W/°C) from heating power and outdoor temperature. Powers climate pre-heat scheduling and winter heating cost forecasts.

**Home baseline & anomaly detection** — 168 weekly time slots tracked individually with adaptive thresholds. Includes standby hunters that flag always-on devices as potential energy wasters.

**Virtual room meters** — clusters devices and smart plugs by room using the HA Area Registry, exposing real-time per-room consumption.

**Gas analysis** — correlates gas consumption with Heating Degree Days to benchmark boiler efficiency and forecast winter gas costs.

**Day classifier** — classifies each day as workday, weekend, holiday, vacation, or anomalous based on consumption patterns, enabling smarter scheduling across all modules.

### 🛡️ Data quality & reliability

**Sensor sanity guard** — validates all sensor values before any calculation. Filters impossible readings, kW/W unit confusion, historical spikes, and sign errors. Reports critical and warning flags per sensor.

**EMA diagnostics** — tracks all sensors through an Exponential Moving Average filter. Detects frozen sensors, slow-responding sensors, and blocked spikes.

**Watchdog** — monitors the coordinator for repeated update failures. After 3 consecutive errors it automatically reloads the integration with exponential backoff (30 s → 60 s → max 1 hour). Full crash history is persisted across HA restarts and visible on the Diagnose dashboard tab with error messages, timestamps, and restart counter.

---

## Sensors & entities

CloudEMS exposes 100+ sensors. Key examples:

| Domain | Sensor | Description |
|---|---|---|
| Grid | `grid_net_power` | Live net import/export (W) |
| Grid | `phase_l1_current` | Per-phase current (A) |
| Grid | `p1_power` | P1 meter direct reading (W) |
| Price | `energy_price_current_hour` | Current EPEX price (€/kWh) |
| Price | `cheapest_4h_block` | Cheapest 4-hour window + countdown |
| Price | `energy_cost_today` | Actual cost so far today (€) |
| Price | `energy_cost_forecast_today` | Predicted total cost today (€) |
| Bill | `bill_simulator_saving_vs_fixed` | € saved vs fixed tariff this year |
| NILM | `nilm_running_devices` | Count of detected active appliances |
| Solar | `solar_pv_forecast_today` | Predicted PV yield today (kWh) |
| Solar | `pv_forecast_accuracy` | MAPE 14d/30d + bias factor |
| Solar | `pv_opbrengst_terugverdientijd` | Annual yield estimate + payback period |
| Solar | `pv_health` | Panel health status |
| Solar | `clipping_loss_today` | Lost kWh to inverter clipping |
| Battery | `battery_epex_schedule` | Current charge/discharge action |
| Battery | `battery_soh` | State of Health (%) |
| EV | `ev_session_kwh` | Energy delivered in current session |
| Heat pump | `heat_pump_cop_current` | Current measured COP |
| Heat pump | `heat_pump_cop_degradation` | Year-on-year COP health |
| Presence | `absence_detector` | home / away / sleeping / vacation + confidence |
| Climate | `climate_preheat` | Pre-heat mode, setpoint offset, price ratio |
| Lamps | `lamp_circulation_status` | Circulation mode + active lamps |
| Pool | `pool_status` | Filter + heater state + water temp |
| House | `thermal_w_per_k` | Thermal loss coefficient (W/°C) |
| House | `anomaly_detected` | Unusual consumption (adaptive threshold) |
| Costs | `energy_budget_status` | Budget tracking (on track / overspend) |
| Micro | `micro_mobility` | E-bike/scooter session tracking |
| Diag | `sensor_sanity` | Sensor health: critical/warning flags |
| Diag | `ema_diagnostics` | Frozen/slow sensors, blocked spikes |
| Diag | `watchdog` | Crash counter, restart history, last error |

---

## Dashboard

The included `cloudems-dashboard.yaml` provides **16 fully-styled tabs**. Import via the HA Lovelace dashboard editor.

**Required frontend cards (all free, installable via HACS):**
- [mushroom-cards](https://github.com/piitaya/lovelace-mushroom)
- [apexcharts-card](https://github.com/RomRider/apexcharts-card)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)

| Tab | Content |
|---|---|
| 🏠 Overzicht | Live grid, solar, battery, current cost, notifications |
| 🏡 Huis Intelligentie | Presence, day type, consumption categories, room meters, pre-heat |
| 💶 Prijzen & Kosten | EPEX chart, cheap-hours, bill simulator, saldering, forecasts |
| ☀️ Solar & PV | Inverter status, clipping, shadow detection, self-consumption, ROI |
| 💡 Lampen | Circulation control, phase detection, behaviour pattern table |
| 🧠 NILM Apparaten | Detected devices, top consumers, AI confidence, ROI |
| ⚙️ NILM Beheer | Live activity monitor, device list, models, cleanup, database |
| ⚡ Fasen | Per-phase current gauges, phase balance, peak shaving |
| 🔋 Batterij | EPEX schedule, SoC graph, State of Health |
| 🌡️ Warm Water | Boiler control log, heat pump COP health + degradation |
| 🚗 EV & Mobiliteit | Dynamic charging, session learner, flex score |
| 🚲 E-bike & Scooter | Micro-mobility sessions, vehicle profiles, usage graph |
| 🏊 Zwembad | Pool filtration + heating smart control |
| 🔔 Meldingen | All active alerts, per-system alert status |
| 🧬 Zelflerend | Learning progress, anomaly detail, standby hunters |
| 🔬 Diagnose | Watchdog crash monitor, sensor sanity, EMA diagnostics, system info |

---

## Support CloudEMS

CloudEMS is **completely free and open source**. If it saves you money on your energy bill — please consider a small contribution.

<div align="center">

### 👉 [buymeacoffee.com/cloudems](https://buymeacoffee.com/smarthost9m) ☕

</div>

You can also support by starring this repository, [reporting bugs](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml), [requesting features](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=feature_request.yml), or telling other HA users about CloudEMS.

---

## License

MIT © 2026 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

<div align="center">
<sub>Keywords: Home Assistant energy management · NILM · EPEX prices · dynamic EV charging · peak shaving · phase balancing · solar curtailment · Ollama AI · lamp circulation · burglary deterrence · smart meter · P1 · DSMR · bill simulator · heat pump COP · e-bike charging · watchdog · presence detection · saldering simulator · PV forecast accuracy · false positive removal</sub>
</div>
