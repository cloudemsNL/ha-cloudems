!!!! BETA BETA BETA !!!!


!!!!!!Dasbhoard code zelf even WWW folder kopieeren, auto update werkt nog niet!!!!!!

<div align="center">

# ⚡ CloudEMS
### Intelligent Energy Management for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cloudemsNL/ha-cloudems.svg?style=for-the-badge)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-blue.svg?style=for-the-badge)](https://www.home-assistant.io/)

**Fully local · Privacy-first · No subscription · No extra hardware**

[🌐 cloudems.eu](https://cloudems.eu) &nbsp;·&nbsp; [📖 Wiki](https://github.com/cloudemsNL/ha-cloudems/wiki) &nbsp;·&nbsp; [🐛 Report an issue](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml) &nbsp;·&nbsp; [☕ Buy Me a Coffee](https://buymeacoffee.com/smarthost9m)

</div>

---

CloudEMS transforms your smart meter into an intelligent energy brain. It observes, learns, predicts and acts — automatically aligning every flexible load in your home to the cheapest electricity, maximising solar self-consumption, protecting circuits from overload, and keeping your home safe while you're away.

Everything runs **100% locally** on your Home Assistant instance. No cloud. No subscription. No data ever leaves your home.

---

## Contents

- [Installation](#installation)
- [Requirements](#requirements)
- [How it works](#how-it-works)
- [Features](#features)
- [Sensors & entities](#sensors--entities)
- [Dashboard](#dashboard)
- [Support CloudEMS](#support-cloudems)

---

## Installation

### Via HACS (recommended)

1. Open **HACS** → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/cloudemsNL/ha-cloudems` → category **Integration**
3. Search **CloudEMS** → **Download**
4. Restart Home Assistant
5. Go to **Settings** → **Devices & Services** → **+ Add Integration** → search **CloudEMS**
6. Follow the setup wizard

> 💡 Choose **Advanced** mode in the wizard for full control over inverters, batteries, boiler groups, P1 sensors and all optional modules.

### Manual installation

Download the [latest release](https://github.com/cloudemsNL/ha-cloudems/releases/latest), extract it, and copy `custom_components/cloudems/` into your `config/custom_components/` directory. Restart Home Assistant.

---

## Requirements

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1.0 or newer |
| Smart meter | P1 port or compatible integration (DSMR, HomeWizard, Shelly EM, etc.) |
| Python | 3.11+ (built into HA — nothing to install) |
| Ollama | Optional — for local LLM-assisted NILM classification |

---

## How it works

CloudEMS runs a **10-second update cycle** that reads your smart meter, processes every connected sensor, and makes real-time decisions. The real power is in the self-learning layer:

```
Smart meter → CloudEMS reads → learns patterns → predicts → acts
     ↑                                                          ↓
     └──────────── feedback: was the prediction right? ←───────┘
```

Every module is **self-learning** and **zero-config**. CloudEMS calibrates itself to your home over days and weeks — there is nothing to manually tune.

---

## Features

### 🧠 NILM — Appliance detection without extra hardware

Non-Intrusive Load Monitoring identifies individual appliances from the aggregate grid power signal alone. No extra hardware or smart plugs required.

Each power event is matched against an internal signature database, a local scikit-learn model trained on your confirmed events, and optionally a local Ollama LLM for edge cases.

**Adaptive thresholds** — detection sensitivity auto-calibrates to your installation's noise floor using a rolling 80th-percentile estimator. Quiet P1 meters reach ~10 W sensitivity; noisy clamp meters stay higher to avoid false triggers.

**False positive removal** — new detections are validated 20 seconds after the trigger. If the grid baseline hasn't moved as expected, unconfirmed events are discarded automatically. User-confirmed devices are never auto-removed.

**Smart Plug Anchoring** — Shelly, Tasmota or ESPHome plugs are automatically used as anchors, lifting detection accuracy from ~65% to ~85%+.

**Bayesian classification** — detection scores adjust in real-time based on outdoor temperature, time of day, season, and wind direction. The Bayesian layer can only improve confidence, never lower it.

**HMM session tracking** — a Hidden Markov Model tracks multi-state appliances (e.g. washing machines with multiple power levels) to sharpen on/off boundary detection.

Detected device categories include washing machines, dryers, dishwashers, ovens, heat pumps, boilers, EV chargers, refrigerators, TVs, computers and more — with daily kWh breakdowns per category.

---

### 💰 Dynamic EPEX prices & cost optimisation

CloudEMS fetches day-ahead electricity prices (EPEX Spot) for NL, DE, AT (no API key) and all ENTSO-E areas (free key). It identifies the cheapest consecutive-hour windows and exposes them as sensors you can attach to any switch or automation.

**Cheapest 4-hour block** — always shows the optimal charging/heating window for today, with per-hour breakdown, start/end times and a live countdown.

**Cheap-hours switch scheduler** — link any switch or script to automatically activate during the cheapest N hours of the day.

**Bill simulator** — records your hourly consumption and EPEX price continuously, then calculates what you would have paid on a fixed tariff, a day/night tariff, or your actual dynamic contract. After 2+ months it tells you exactly how much you're saving.

**Cost forecaster** — predicts today's and tomorrow's total cost based on learned consumption patterns and upcoming EPEX prices, with monthly budget tracking.

**Saldering simulator** — models the phased abolition of Dutch net metering (saldering), showing the financial impact year by year for your specific solar and consumption profile.

---

### ⚡ Grid congestion & capacity tariff management

Designed for the Dutch grid congestion reality of 2025–2026, with relevance for Belgium's already-active capacity tariff regime.

**Grid congestion detector** — monitors your import power against a configurable threshold. When import is high *and* the EPEX price is elevated, a congestion event is declared and CloudEMS automatically sheds flexible loads in priority order: EV charging is throttled to minimum, boiler loads are deferred, and solar export is reduced if the battery can absorb it. Events are counted per day and per month with peak import logging.

**Capacity tariff peak monitor** — tracks your 15-minute average power demand and compares it against the highest quarterly-peak recorded this month. When you are close to setting a new monthly peak, an alert fires with the minutes remaining in the current quarter-hour window — giving you time to shed loads before it counts. Relevant for Belgium's capaciteitstarief and anticipated Dutch DSO tariff reforms (Liander / Enexis 2025–2026).

**Flex score** — a real-time 0–100 flexibility score that combines grid price, solar surplus, battery state, phase load and congestion status into a single signal used to coordinate all load-shifting modules without conflict.

---

### ☀️ Solar & PV optimisation

**Self-learning PV forecast** — builds a statistical model of your solar production by observing actual inverter output over weeks, blended with Open-Meteo irradiance data. No panel specifications required.

**Forecast accuracy tracking** — continuously measures MAPE over 14-day and 30-day windows. A bias factor detects systematic over- or under-estimation and corrects the model over time.

**Solar ROI calculator** — estimates annual yield (kWh), financial value, and payback period based on your detected system size and current energy prices.

**Automatic orientation detection** — derives your panel azimuth and tilt from the shape of your daily yield curves after ~30 clear days.

**Multi-inverter support** — up to 9 inverters tracked independently. CloudEMS learns which grid phase each inverter feeds and dims only overloaded phases during congestion events.

**Clipping loss analysis** — detects when your inverter hits its rated power limit and quantifies the kWh lost per day, including an estimated payback period for upgrading to a larger inverter.

**Clipping forecast** — predicts tomorrow's expected clipping losses based on the weather forecast and learned inverter behaviour, so you can pre-emptively adjust loads or battery scheduling.

**PV health monitoring** — detects soiling, degradation, and structural shading by comparing recent peak production against an irradiance-adjusted all-time baseline.

---

### 🔋 Battery management

CloudEMS builds an optimal daily charge/discharge schedule based on EPEX prices, current SoC, and battery capacity. In summer it detects when solar will fully charge the battery and skips unnecessary overnight charging.

**Degradation tracking** — counts full and partial charge cycles, detects deep-discharge and high-SoC stress, and tracks State of Health (SoH) over time with alerts at 90% and 80% SoH thresholds.

---

### 🚗 EV charging

**Dynamic current control** — adjusts your EV charger in real-time using a self-tuning PID controller across three modes: solar surplus, cheap-hours, and phase protection.

**Session learner** — after ~10 sessions CloudEMS learns your typical plug-in time, expected kWh per session, and weekday patterns to pre-reserve the optimal cheap windows for the next charge.

**ERE certificate tracking** — tracks charged kWh against the Dutch RED3 / NEa Emissiereductie-eenheden (ERE) scheme. Calculates the renewable energy fraction based on whether charging occurred on solar surplus, green-rate hours, or grid average. Generates quarterly reports suitable for submission to an inboekdienstverlener (Laadloon, FincoEnergies, Voltico, etc.), with monthly breakdowns and JSON/CSV export. Estimated yield: €0.03–€0.10 per kWh charged, ~€120–€400/year for a typical home charger.

> ERE tracking requires a MID-certified charge point (Zaptec, Alfen, OCPP, Smappee, Ohme) and registration with an inboekdienstverlener before May 2026.

---

### 🌡️ Climate & heat pump intelligence

**COP learning** — tracks your heat pump's Coefficient of Performance grouped by outdoor temperature bucket, with defrost cycle exclusion for accurate baselines.

**Degradation detection** — short-term (3–4 week) and year-on-year COP comparison. A sustained drop of 8%+ triggers a maintenance advisory.

**Climate pre-heat scheduling** — calculates the optimal pre-heat moment based on the thermal house model, current EPEX price ratio, and a configurable setpoint offset.

**Zone climate cost tracking** — monitors per-zone heating costs today and over time, including wood stove efficiency advice where applicable.

**Smart climate manager** — coordinates zone setpoints, boiler demand signals and heat pump scheduling into a unified climate strategy, overrideable per zone from the dashboard.

---

### ♨️ Boiler & hot water

**Boiler cascade control (v3.1)** — manages one or more electric boiler groups (resistive or heat-pump-assisted) with configurable setpoints, comfort thresholds, minimum on/off times, and per-unit priorities. Groups are managed through the wizard — no YAML required.

**Self-learning delivery boiler detection** — the cascade automatically learns which boiler is used first for hot water demand (the "delivery" boiler) by tracking temperature deficits and energy consumption per cycle. The delivery boiler is always heated first to ensure hot water is available. Minimum 5 learning cycles needed; confidence reported on the dashboard.

**Hourly and day-of-week usage patterns** — a 7×24 matrix of hot water usage is built from flow sensor readings. The system uses this to pre-heat the delivery boiler before expected demand peaks — not just when cheap hours begin. Saturday morning patterns are treated differently from Monday morning.

**Optimal start timing** — instead of starting the boiler as soon as cheap electricity begins (which may be hours early), CloudEMS calculates the exact start time needed so the boiler reaches setpoint just before the predicted demand peak.

**Thermal loss compensation** — the system learns each boiler's cooling rate (°C/hour). This is used to predict when a boiler will fall below the comfort floor, enabling just-in-time re-heating. Dashboard shows "time until cold" per boiler.

**Flow-sensor demand response** — connecting a flow sensor (binary or volume) to each boiler group gives CloudEMS real-time hot water demand signals. When a tap opens, the delivery boiler gets immediate priority regardless of the current cascade schedule.

**Seasonal setpoints** — automatic summer/winter mode based on outdoor temperature trend (3-day hysteresis). Configurable per-season setpoints, or automatic ±5°C adjustment.

**Grid congestion integration** — during grid congestion, buffer boilers are paused while the delivery boiler remains on. This cuts peak load while maintaining hot water availability.

**Proportional dimmer control** — for boilers connected via a dimmer module (RBDimmer, DimmerLink, `number.*`, `light.*`), the power output follows PV surplus proportionally in 5% steps (30-second update rate). Full AAN/UIT control also supported.

**Post-saldering mode** — with Dutch net metering phasing out in 2027, this mode lowers the PV surplus trigger threshold to 40%, aggressively consuming every available solar watt instead of exporting it.

**Anomaly detection** — if daily hot water demand exceeds 2.5× the learned baseline, a persistent HA notification is created. Useful for detecting leaks or unusual household situations.

**P1 direct response** — when a P1 smart meter reader is configured, grid export data is pushed to the boiler controller on every telegram (~1 second). This means the boiler reacts to live grid conditions rather than waiting for the coordinator cycle (30 seconds).

**Week energy budget** — tracks kWh consumption per boiler per ISO week, visible on the dashboard.

**Delta-T setpoint optimisation** — when a boiler is well above its comfort floor, the setpoint is reduced proportionally (max −8°C) to avoid overheating and reduce thermal losses.

**Wash cycle detector** — when a washing machine or dishwasher is connected (via smart plug or NILM), CloudEMS detects the active wash phase (pre-wash, heating, wash, rinse, spin) from the power profile and estimates remaining programme time.

---

### ⚡ Phase management & capacity tariff

Monitors import and export current per phase (L1/L2/L3) every 10 seconds with automatic load shedding in priority order when limits are approached.

**Phase balancing** — detects structural phase imbalance and provides concrete re-wiring advice.

**Peak shaving** — configurable import limit with priority-based shedding.

**Congestion shedding** — automatic load reduction during high-price congestion events. Four warning levels: advisory (80%), soon (90%), warning (95%), critical (100%+). Actions are ranked by comfort impact.

**Capacity tariff peak monitor (v3.0)** — tracks the 15-minute average power demand and compares it against the monthly peak. Features:
- Automatic monthly reset (no manual intervention needed)
- End-of-quarter projection based on current power trajectory
- Ranked load-shedding actions with urgency levels (advisory / soon / now)
- 12-month peak history with indicative cost per month
- Headroom indicator: W available before setting a new monthly peak
- Relevant for Belgium (active), Netherlands (Liander/Enexis 2025+)

---

### 🏠 Presence & home intelligence

**Absence detection** — determines occupancy purely from energy consumption patterns. No GPS, no login events. States: home, away, sleeping, vacation — with confidence percentage and standby power level.

**Sleep detector** — detects when everyone is asleep based on motion sensor inactivity and lights-off signals. Switches off configurable standby loads automatically.

**Day classifier** — classifies each day as workday, weekend, holiday, vacation, or anomalous based on consumption patterns, used by scheduling modules across the entire system.

**Thermal house model** — learns your home's thermal loss coefficient (W/°C) from heating power and outdoor temperature. Powers pre-heat scheduling and winter heating cost forecasts.

**Consumption anomaly detection** — 168 weekly time slots tracked with adaptive thresholds. Standby hunters flag always-on devices as potential energy wasters.

**Virtual room meters** — clusters devices and smart plugs by HA Area, exposing real-time per-room consumption without extra hardware.

**Gas analysis** — correlates gas consumption with Heating Degree Days to benchmark boiler efficiency and forecast winter gas costs.

**Weekly energy insights** — an automatically generated weekly summary of consumption trends, savings, solar yield, peak costs and module recommendations, delivered as a HA notification and visible on the dashboard.

---

### 💡 Lamp circulation & burglary deterrence

When CloudEMS detects an empty home, it activates a lamp circulation system that makes the house appear occupied:

- **Random intervals** — Gaussian-distributed timing (2–8 min), no two evenings identical
- **Behaviour mimicry** — learns which lamps you personally use at which hour of the day
- **Seasonal intelligence** — starts and stops based on actual sunset via `sun.sun`
- **PIR bypass** — lamps paired with motion sensors are excluded while real motion is detected
- **Passive phase detection** — every switch event passively identifies which grid phase that lamp is on
- **Negative price bonus** — extends intervals when EPEX prices go negative

---

### 🏊 Pool controller

Manages filtration and heating intelligently: PV surplus mode, cheapest EPEX hours fallback, temperature-adjusted daily minimum runtime, and COP-optimised heat pump scheduling.

---

### 🚲 Micro-mobility tracker

Detects and tracks e-bike and scooter charging sessions (40–700 W) using non-overlapping power classification ranges. Builds a learning profile per vehicle with session history, average kWh, peak charge hour, and optimal charging time recommendations.

Supported integrations: Bosch eBike via [hass-bosch-ebike](https://github.com/...) (HACS), Specialized Turbo via Bluetooth (HACS), and any brand via losse sensors configured in CloudEMS options.

---

### 🛡️ Data quality & reliability

**Sensor sanity guard** — validates all sensor values before any calculation. Filters impossible readings, kW/W unit confusion, historical spikes, and sign errors.

**EMA diagnostics** — tracks all sensors through an Exponential Moving Average filter. Detects frozen sensors, slow-responding sensors, and blocked spikes before they corrupt calculations.

**Watchdog** — monitors the coordinator for repeated update failures. After 3 consecutive errors it reloads the integration with exponential backoff (30 s → 60 s → max 1 hour). Full crash history is persisted across HA restarts and visible on the Diagnose tab with error messages, timestamps, and restart counter.

---

## Sensors & entities

CloudEMS exposes 100+ sensors. Key examples:

| Domain | Sensor | Description |
|---|---|---|
| Grid | `grid_net_power` | Live net import/export (W) |
| Grid | `phase_l1_current` | Per-phase current (A) |
| Grid | `kwartier_piek` | 15-min average demand vs. monthly peak (W) |
| Grid | `grid_congestion` | Congestion active, utilisation %, event count |
| Price | `energy_price_current_hour` | Current EPEX price (€/kWh) |
| Price | `cheapest_4h_block` | Cheapest 4-hour window + countdown |
| Price | `energy_cost_today` | Actual cost so far today (€) |
| Price | `energy_cost_forecast_today` | Predicted total cost today (€) |
| Bill | `bill_simulator_saving_vs_fixed` | € saved vs fixed tariff this year |
| NILM | `nilm_running_devices` | Count of detected active appliances |
| Solar | `solar_pv_forecast_today` | Predicted PV yield today (kWh) |
| Solar | `pv_forecast_accuracy` | MAPE 14d/30d + bias factor |
| Solar | `clipping_loss_today` | Lost kWh to inverter clipping |
| Solar | `clipping_forecast_tomorrow` | Expected clipping losses tomorrow |
| Solar | `pv_health` | Panel health status |
| Solar | `pv_opbrengst_terugverdientijd` | Annual yield estimate + payback period |
| Battery | `battery_epex_schedule` | Current charge/discharge action |
| Battery | `battery_soh` | State of Health (%) |
| EV | `ev_session_kwh` | Energy delivered in current session |
| EV | `ere_certificaten` | ERE certificates earned + quarterly report |
| Heat pump | `heat_pump_cop_current` | Current measured COP |
| Heat pump | `heat_pump_cop_degradation` | Year-on-year COP health |
| Climate | `climate_preheat` | Pre-heat mode, setpoint offset, price ratio |
| Climate | `zone_klimaat_kosten_vandaag` | Per-zone heating costs today |
| Presence | `absence_detector` | home / away / sleeping / vacation + confidence |
| Lamps | `lamp_circulation_status` | Circulation mode + active lamps |
| Pool | `pool_status` | Filter + heater state + water temp |
| House | `thermal_w_per_k` | Thermal loss coefficient (W/°C) |
| House | `anomaly_detected` | Unusual consumption (adaptive threshold) |
| House | `energy_insights` | Weekly summary: savings, trends, recommendations |
| Micro | `micro_mobiliteit` | E-bike/scooter session tracking + vehicle profiles |
| Gas | `gasanalyse` | Gas efficiency vs HDD benchmark + winter forecast |
| Costs | `energy_budget_status` | Budget tracking (on track / overspend) |
| Diag | `sensor_sanity` | Sensor health: critical/warning flags |
| Diag | `ema_diagnostics` | Frozen/slow sensors, blocked spikes |
| Diag | `watchdog` | Crash counter, restart history, last error, version |

---

## Dashboard

The included `cloudems-dashboard.yaml` provides **19 fully-styled tabs**. Import it via the HA Lovelace dashboard editor (Raw configuration editor → paste).

**Required frontend cards** (all free, installable via HACS):
- [mushroom-cards](https://github.com/piitaya/lovelace-mushroom)
- [apexcharts-card](https://github.com/RomRider/apexcharts-card)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)

| # | Tab | Content |
|---|---|---|
| 1 | 🏠 Overzicht | Live grid, solar, battery, current cost, notifications |
| 2 | 💶 Prijzen & Kosten | EPEX chart, cheap-hours, bill simulator, saldering, forecasts |
| 3 | 🏡 Huis Intelligentie | Presence, day type, consumption categories, room meters, pre-heat |
| 4 | ⚡ Fasen | Per-phase current gauges, phase balance, peak shaving, congestion |
| 5 | ☀️ Solar & PV | Inverter status, clipping, clipping forecast, shadow detection, ROI |
| 6 | 🔋 Batterij | EPEX schedule, SoC graph, State of Health, degradation |
| 7 | 🧠 NILM Apparaten | Detected devices, top consumers, AI confidence |
| 8 | ⚙️ NILM Beheer | Live activity monitor, device list, models, cleanup |
| 9 | 🌡️ Warm Water | Boiler groups, cascade control, wash cycle status |
| 10 | 🌡️ Klimaat | Zone overview, pre-heat schedule, zone cost tracking |
| 11 | 🚗 EV & Mobiliteit | Dynamic charging, session learner, ERE certificates, flex score |
| 12 | 🚲 E-bike & Scooter | Micro-mobility sessions, vehicle profiles, usage graph |
| 13 | 🏊 Zwembad | Pool filtration + heating smart control |
| 14 | 💡 Lampen | Circulation control, phase detection, behaviour pattern |
| 15 | 🏆 ERE Certificaten | ERE earnings, quarterly report, MID meter status |
| 16 | 🧬 Zelflerend | Weekly insights, learning progress, anomaly detail, standby hunters |
| 17 | 🔔 Meldingen | All active alerts, per-system alert status |
| 18 | 🔬 Diagnose | Watchdog crash monitor, sensor sanity, EMA diagnostics, system info |
| 19 | ⚙️ Configuratie | Module toggles, boiler groups editor, NILM settings |

The dashboard reads the CloudEMS version dynamically from HA — updating the integration automatically updates the version shown in all tab titles.

---

## Support CloudEMS

CloudEMS is **completely free and open source**. If it saves you money on your energy bill — please consider a small contribution.

<div align="center">

### 👉 [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m) ☕

</div>

You can also support by starring this repository, [reporting bugs](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml), [requesting features](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=feature_request.yml), or telling other HA users about CloudEMS.

---

## License

MIT © 2026 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

<div align="center">
<sub>Keywords: Home Assistant energy management · NILM · EPEX spot prices · dynamic EV charging · peak shaving · phase balancing · grid congestion · netcongestie · capaciteitstarief · ERE certificaten · saldering simulator · solar curtailment · Ollama AI · lamp circulation · burglary deterrence · smart meter · P1 · DSMR · bill simulator · heat pump COP · wash cycle detector · sleep detector · e-bike charging · watchdog · presence detection · PV forecast accuracy · clipping loss · false positive removal · flex score · boiler cascade</sub>
</div>
