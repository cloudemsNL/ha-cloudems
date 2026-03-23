<div align="center">

# ⚡ CloudEMS
### Intelligent Energy Management for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cloudemsNL/ha-cloudems.svg?style=for-the-badge)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg?style=for-the-badge)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-blue.svg?style=for-the-badge)](https://www.home-assistant.io/)

**Fully local · Privacy-first · No subscription · No extra hardware**

[🌐 cloudems.eu](https://cloudems.eu) &nbsp;·&nbsp; [📖 Wiki](https://github.com/cloudemsNL/ha-cloudems/wiki) &nbsp;·&nbsp; [🐛 Report an issue](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml) &nbsp;·&nbsp; [☕ Buy Me a Coffee](https://buymeacoffee.com/smarthost9m)

</div>

---

> [!NOTE]
> **v4.6.440 — Release Candidate** — CloudEMS has reached RC quality. Core functionality (NILM, price optimisation, battery, boiler, EV, shutters) is stable and in daily use. The generator/ATS module is new and in active testing.
>
> **Dashboard:** The CloudEMS dashboard is created automatically on first install. On some setups a **double restart** of Home Assistant is required before the dashboard appears in the sidebar. This is a known Lovelace API limitation.

---

> [!TIP]
> ## 🚀 Setup wizard
>
> Na installatie open je de **interactieve setup wizard** om je sensoren en apparaten te koppelen:
>
> ```
> http://homeassistant.local:8123/local/cloudems/onboarding.html
> ```
>
> De wizard helpt je stap voor stap met:
> - Je slimme meter (P1) koppelen
> - Fase-sensoren instellen
> - Zonnepanelen / omvormer koppelen
> - EV-lader koppelen
> - Piekschaving instellen
> - NILM apparaten opgeven (voor sneller leren)
>
> Alles wordt live vanuit jouw HA-installatie opgehaald — geen handmatig typen.

CloudEMS transforms your smart meter into an intelligent energy brain. It observes, learns, predicts and acts — automatically aligning every flexible load in your home to the cheapest electricity, maximising solar self-consumption, protecting circuits from overload, and keeping your home safe while you're away.

Everything runs **100% locally** on your Home Assistant instance. No cloud. No subscription. No data ever leaves your home.

---

## Contents

- [Installation](#installation)
- [Requirements](#requirements)
- [How it works](#how-it-works)
- [Features](#features)
- [Dashboard](#dashboard)
- [Configuration wizard](#configuration-wizard)
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

Each power event is matched against an internal signature database, a local classifier trained on your confirmed events, and optionally a local Ollama LLM for edge cases.

**Adaptive thresholds** — detection sensitivity auto-calibrates to your installation's noise floor using a rolling 80th-percentile estimator. Quiet P1 meters reach ~10 W sensitivity.

**False positive removal** — new detections are validated 20 seconds after the trigger and discarded if the grid baseline hasn't moved as expected.

**Smart Plug Anchoring** — Shelly, Tasmota or ESPHome plugs are automatically used as anchors, lifting detection accuracy from ~65% to ~85%+.

**Bayesian classification** — detection scores adjust in real-time based on outdoor temperature, time of day, season, and wind direction.

**7×24 weekly time profile** — each device builds a full 7-day × 24-hour usage matrix. CloudEMS detects when a device runs at an unusual time (e.g. dishwasher at 03:00) and sends an alert. Always-on devices (router, standby, hub) are automatically excluded based on their measured on-ratio — no manual configuration needed.

**HMM session tracking** — a Hidden Markov Model tracks multi-state appliances to sharpen on/off boundary detection.

---

### 💰 Dynamic EPEX prices & cost optimisation

CloudEMS fetches day-ahead electricity prices (EPEX Spot) for NL, DE, AT (no API key) and all ENTSO-E areas (free key).

**Smart negative price alerts** — alerts only fire when the **all-in price including energy tax and VAT** is negative, not just the raw EPEX base. This prevents false alerts when EPEX dips just below zero but the effective consumer price is still positive.

**Cheapest N-hour block** — always shows the optimal charging/heating window for today with countdown.

**Cheap-hours switch scheduler** — link any switch or script to automatically activate during the cheapest N hours.

**Bill simulator** — records hourly consumption and EPEX price, calculates what you would have paid on a fixed, day/night or dynamic tariff.

**Cost forecaster** — predicts today's and tomorrow's total cost based on learned consumption patterns and upcoming EPEX prices.

**Energy budget** — configurable monthly budget in €, kWh and m³ gas. Critical alerts fire only when the **euro budget** is at risk, not just kWh, to prevent false alarms when high solar export offsets consumption.

**Saldering simulator** — models the phased abolition of Dutch net metering (saldering), showing the financial impact year by year for your specific profile.

---

### ⚡ Grid congestion & capacity tariff management

**Grid congestion detector** — monitors import power against a configurable threshold with automatic priority-based load shedding (EV first, then boiler, then export reduction).

**Capacity tariff peak monitor** — tracks 15-minute average power demand vs monthly peak with end-of-quarter projection and ranked shedding actions. Relevant for Belgium's capaciteitstarief and Dutch DSO tariff reforms (Liander / Enexis 2025+).

**Flex score** — a real-time 0–100 flexibility score combining grid price, solar surplus, battery state, phase load and congestion status.

---

### ☀️ Solar & PV optimisation

**Self-learning PV forecast** — builds a statistical model of your solar production by observing actual inverter output over weeks, blended with Open-Meteo irradiance data. No panel specifications required.

**Forecast accuracy tracking** — continuously measures MAPE over 14-day and 30-day windows with automatic bias correction.

**Solar ROI calculator** — estimates annual yield (kWh), financial value and payback period based on detected system size and current energy prices.

**Automatic orientation detection** — derives panel azimuth and tilt from the shape of daily yield curves after ~30 clear days.

**Multi-inverter support** — up to 9 inverters tracked independently with per-phase assignment.

**Clipping loss analysis & forecast** — detects when your inverter hits its power limit, quantifies the lost kWh per day, and predicts tomorrow's losses.

**PV health monitoring** — detects soiling, degradation and structural shading by comparing recent peak production against an irradiance-adjusted all-time baseline.

**P1 offline detection** — when the P1/DSMR smart meter goes offline, the energy flow card shows a clear red warning banner instead of silently displaying 0W everywhere. All modules remain paused until data resumes.

---

### 🔋 Battery management

Optimal daily charge/discharge schedule based on EPEX prices, current SoC and battery capacity. In summer it detects when solar will fully charge the battery and skips unnecessary overnight charging.

**Degradation tracking** — cycle counting, SoH tracking, deep-discharge and high-SoC stress alerts at 90% and 80% SoH thresholds.

**Daily reset persistence** — battery charged/discharged today counters survive HA restarts and P1 outages. A self-healing date guard in both `BatteryEfficiencyTracker` and `BatterySavingsTracker` resets counters at midnight regardless of whether the coordinator was active at that moment.

**Victron Energy** — full Cerbo GX / Venus OS integration. Detects SOC and power from VE.Bus entities. ESS mode control for charge/discharge.

**Huawei Luna 2000** — EPEX-driven control via Time of Use and Maximize Self Consumption modes. Max charge/discharge power configurable per session.

**SMA Sunny Boy Storage** — SOC and power monitoring. Direct control via SMA Modbus (optional).

---

### 🚗 EV charging

**Dynamic current control** — self-tuning PID controller across solar surplus, cheap-hours, and phase protection modes.

**Session learner** — learns plug-in time, expected kWh and weekday patterns to pre-reserve optimal cheap windows for the next charge.

**ERE certificate tracking** — tracks charged kWh against the Dutch RED3/NEa Emissiereductie-eenheden scheme with quarterly reports suitable for submission to an inboekdienstverlener. Estimated yield: €0.03–€0.10 per kWh charged.

**Vehicle-to-Home (V2H)** — uses your EV as a home battery during expensive EPEX hours. Requires a bidirectional charger (Wallbox Quasar 2). Configurable minimum SOC, price threshold and max discharge power.

**EV Trip Planner** — reads your HA calendar and charges exactly enough for your next trip at the cheapest EPEX window. Learns average km per trip type (work, appointment, trip) over time. No more unnecessary full charges.

---

### ⚡ Generator & ATS/MTS backup power

Full generator and transfer switch integration — works with both automatic ATS and manual MTS setups. Configured entirely through the wizard; no YAML required.

**Automatic ATS** — CloudEMS reads a binary_sensor or sensor entity and reacts automatically when the generator takes over. The NET node in the energy flow card is dimmed and replaced by the generator node.

**Manual MTS** — CloudEMS confirms grid loss after 15 seconds and sends both a persistent HA notification and a TTS voice alert: *"Zet de MTS schakelaar om en start de generator."* A 5-minute cooldown prevents repeated alerts.

**Auto-start** — optionally links a switch, button or script to automatically start the generator. Verifies it actually started within 30 seconds and sends an escalation alert if it didn't.

**Load limiting** — when running on generator, CloudEMS automatically:
- Pauses EV charging when generator headroom drops below 1 kW
- Reduces boiler setpoint to legionella-safe minimum (45°C) when headroom drops below 2 kW
- Blocks all solar export (no grid feed-in when disconnected from the grid)

**Generator node in energy flow** — dedicated orange node showing live power, capacity utilisation percentage and fuel type. Fully interactive: click the node for a popup with all generator details.

**Generator fuel cost sensor** — tracks estimated fuel cost (€) based on measured power consumption and configured cost per kWh.

**Configuration:** power sensor, ATS/MTS status entity, auto-start switch, max power (W), fuel type, cost per kWh, TTS entity.

---

### 🌡️ Climate & heat pump intelligence

**COP learning** — tracks heat pump efficiency grouped by outdoor temperature with defrost cycle exclusion.

**Degradation detection** — short-term (3–4 week) and year-on-year COP comparison with maintenance advisories.

**Climate pre-heat scheduling** — calculates optimal pre-heat moment based on the thermal house model, current EPEX price ratio and configurable setpoint offset.

**Climate EPEX compensation** — pre-heats or pre-cools based on upcoming EPEX prices using EMA-learned setpoint patterns per hour of the day.

**Zone climate cost tracking** — monitors per-zone heating costs today and over time.

---

### ♨️ Boiler & hot water

**Boiler cascade control** — manages one or more electric boiler groups (resistive, heat pump, or hybrid) with configurable setpoints, comfort thresholds, minimum on/off times and per-unit priorities. Fully wizard-driven.

**Safe ramp-up after restart** — the hybrid/heat pump boiler setpoint ramps up gradually from the green base temperature in configurable steps (e.g. 53°C → 58°C → 63°C). After a restart, if the water temperature is far below the saved ramp setpoint, the ramp resets to green base — preventing uncontrolled heating when connection is lost.

**Price-aware legionella scheduling** — instead of running legionella prevention at a fixed time, CloudEMS selects the cheapest available hour (preferably night) based on EPEX prices. If tomorrow has significantly cheaper prices and there's still time, it defers to tomorrow. The safety deadline is always respected.

**Demand-boost threshold** — configurable via slider in the boiler card Leren tab (30–180 min). Shows learned threshold and accuracy statistics (correct/incorrect boost decisions).

**Tank volume configuration** — configurable in the wizard (0 = learn automatically from heating cycles). Also configurable: ramp maximum temperature.

**Self-learning delivery boiler detection**, hourly usage patterns, thermal loss compensation, flow-sensor demand response, proportional dimmer control, anomaly detection and wash cycle detector all remain fully functional.

---

### 🪟 Roller shutters

**New shutter card v3.0** — completely redesigned:

- **Compact overview** — all shutters in one list with position bar, ▲ ▼ per-shutter buttons and ☀ sun indicator
- **"All up / All down"** — single action for all shutters simultaneously
- **Detail dropdown** — select any shutter to see position slider, automation toggle, open/close times, setpoint, sun status and active override timer (shown only when override is active)
- **Collapsible learning section** — click to reveal progress bars and detected orientation per shutter
- **Direct HA service calls** — all buttons call real HA cover services

---

### 💡 Energy demand & savings advice

**Energy demand module** — calculates current energy needs per subsystem (boiler, battery, EV, climate, pool, gas) with device-level forecasts from NILM history.

**Savings advice engine** — generates up to 6 concrete tips with estimated € amounts based on current prices, surplus and learned patterns.

**Demand card** — tabbed card with system needs, device forecasts and advice. Available in the **💡 Advies** dashboard tab.

---

### 🏠 Presence & home intelligence

**Absence detection** — determines occupancy purely from energy consumption. States: home, away, sleeping, vacation.

**Sleep detector**, **day classifier**, **thermal house model**, **consumption anomaly detection**, **virtual room meters**, **gas analysis** and **weekly energy insights** — all stable and unchanged.

---

### 📊 eGauge smart meter

Full integration with eGauge sub-metering devices (new in HA 2026.1). Auto-detects all eGauge entities on setup. Provides grid power, per-phase (L1/L2/L3) and optional solar power as an alternative to P1/DSMR.

---

### ⚡ Phase outlet auto-detection

Automatically determines which electrical phase (L1/L2/L3) each smart plug or NILM device is connected to — no manual configuration required. Correlates device power-on events with phase current changes. Confidence score per device; locked after 3+ observations. Results feed into NILM and peak shaving.

---

### 🌡️ LG ThinQ, Mitsubishi MelCloud & Toshiba AC

Brand-specific EPEX climate control for LG, Mitsubishi and Toshiba airco systems. Auto-detects brand and power sensors per indoor unit. Real-time power consumption integrated with NILM.

---

### 🛡️ Data quality & reliability

**Sensor sanity guard** — validates all values before calculations. Filters impossible readings, kW/W unit confusion, historical spikes and sign errors.

**EMA diagnostics** — detects frozen sensors, slow-responding sensors and blocked spikes.

**Watchdog** — monitors the coordinator for repeated update failures. After 3 consecutive errors it reloads the integration with exponential backoff (30 s → 60 s → max 1 hour). Full crash history visible on the Diagnose tab.

---

## Dashboard

The included dashboard provides **22 fully-styled tabs** built entirely from custom JavaScript cards — no external frontend dependencies required beyond Home Assistant itself.

**Energy flow card highlights:**
- Animated power flow with proportional line widths and moving dots
- Interactive node popups with metrics and sparklines
- **Hover to enlarge** — nodes scale 1.08× on mouseover with full-name tooltip
- Generator node with capacity bar (when configured)
- P1 offline warning banner
- Sun/moon node with live cloud cover shading

| Tab | Content |
|---|---|
| 🏠 Overzicht | Live energy flow, status, notifications |
| 💡 Advies | Energy demand per subsystem, savings tips |
| 💶 Prijzen & Kosten | EPEX chart, cheap-hours, bill simulator, forecasts |
| 🏡 Huis | Presence, day type, consumption categories, room meters |
| ⚡ Fasen | Per-phase currents, phase balance, peak shaving |
| ☀️ Solar & PV | Inverter status, clipping, forecast, ROI |
| 🔋 Batterij | EPEX schedule, SoC, State of Health |
| 🧠 NILM Apparaten | Detected devices, schedule profiles, time heatmap |
| ⚙️ NILM Beheer | Live activity, device list, models, cleanup |
| 🌡️ Warm Water | Boiler groups, ramp status, demand-boost config |
| ❄️ Klimaat | Zone overview, pre-heat, zone cost tracking |
| ❄️ Klimaat EPEX | Price-based pre-heat/cool scheduling |
| 🚗 EV & Mobiliteit | Dynamic charging, session learner, ERE certificates |
| 🚲 E-bike & Scooter | Micro-mobility sessions, vehicle profiles |
| 🏊 Zwembad | Pool filtration + heating smart control |
| 💡 Lampen | Circulation control, behaviour pattern |
| 🏆 ERE Certificaten | ERE earnings, quarterly report |
| 🪟 Rolluiken | Shutter card v3.0 with dropdown detail |
| 🧬 Zelflerend | Weekly insights, learning progress, anomaly detail |
| 🔔 Meldingen | All active alerts |
| 🔬 Diagnose | Watchdog, sensor sanity, EMA diagnostics |
| ⚙️ Configuratie | Module toggles, boiler groups, NILM settings |

---

## Configuration wizard

The setup wizard guides you through all modules in grouped categories. Every step has a **← Back** button to return to the main menu without losing progress.

Available in 🇳🇱 Dutch · 🇬🇧 English · 🇩🇪 German · 🇫🇷 French.

| Category | Included sections |
|---|---|
| ⚡ Energie & Grid | Grid sensors, phase sensors, prices, budget, P1 advanced, **generator/ATS** |
| ☀️ Opwekking | PV inverters, clipping, EV, batteries |
| 🏠 Verbruik | Boiler controller, climate, shutters, pool, lamps |
| 🤖 Automatisering | NILM, AI, load shifting, cheap-hours switches |
| 🔧 Systeem | Mail reports |

---

## Support CloudEMS

CloudEMS is **completely free**. If it saves you money on your energy bill — please consider a small contribution.

<div align="center">

### 👉 [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m) ☕

</div>

You can also support by starring this repository, [reporting bugs](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.yml), [requesting features](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=feature_request.yml), or telling other HA users about CloudEMS.

---

## License

© 2026 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

<div align="center">
<sub>Keywords: Home Assistant energy management · NILM · EPEX spot prices · dynamic EV charging · peak shaving · phase balancing · grid congestion · netcongestie · capaciteitstarief · ERE certificaten · saldering simulator · solar curtailment · Ollama AI · lamp circulation · burglary deterrence · smart meter · P1 · DSMR · bill simulator · heat pump COP · wash cycle detector · sleep detector · e-bike charging · watchdog · presence detection · PV forecast accuracy · clipping loss · flex score · boiler cascade · generator ATS MTS backup power · rolluiken automatisering · legionella planning · demand boost · shutter card · energy budget</sub>
</div>
