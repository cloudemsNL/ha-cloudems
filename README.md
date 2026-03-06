<div align="center">

# ⚡ CloudEMS
### Smart Energy Management for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cloudemsNL/ha-cloudems.svg?style=for-the-badge)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg?style=for-the-badge)](https://www.home-assistant.io/)

**Fully local · Privacy-first · No subscription · No extra hardware**

[🌐 cloudems.eu](https://cloudems.eu) &nbsp;·&nbsp; [📖 Wiki](https://github.com/cloudemsNL/ha-cloudems/wiki) &nbsp;·&nbsp; [🐛 Report an issue](https://github.com/cloudemsNL/ha-cloudems/issues/new) &nbsp;·&nbsp; [☕ Buy Me a Coffee](https://buymeacoffee.com/cloudems)

</div>

---

> *"Power costs money. CloudEMS makes sure you control it — not the grid operator."*

CloudEMS is a comprehensive Home Assistant integration that turns your smart meter into an intelligent energy brain. It observes, learns, predicts and acts — automatically aligning every flexible load in your home to the cheapest electricity, maximising your solar self-consumption, protecting your circuits from overload, and keeping your home safe while you're away.

Everything runs **100% locally** on your Home Assistant instance. No cloud subscription required. No data leaves your home.

---

## 🚀 Installation

### Via HACS (recommended)

1. Open **HACS** → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/cloudemsNL/ha-cloudems` → category **Integration**
3. Search **CloudEMS** → **Download**
4. Restart Home Assistant
5. **Settings** → **Devices & Services** → **+ Add Integration** → search **CloudEMS**
6. Follow the setup wizard

> 💡 Choose **Advanced** wizard mode for full control over all sensors, inverters, batteries and P1.

### Manual installation

Download the [latest release](https://github.com/cloudemsNL/ha-cloudems/releases/latest), extract and copy `custom_components/cloudems/` into your HA `config/custom_components/` directory.

---

## 🧠 How CloudEMS works — the self-optimising loop

CloudEMS runs a **10-second update cycle** that continuously reads your smart meter, processes every sensor in the system, and makes real-time decisions. But the real power is in the learning:

```
Smart meter → CloudEMS reads → learns patterns → predicts → acts
     ↑                                                          ↓
     └──────────── feedback: was the prediction right? ←───────┘
```

Every module in CloudEMS is **self-learning**. There is nothing to manually tune. Over time the system becomes more accurate at predicting your consumption, your solar output, the behaviour of your appliances, and the patterns of your household — all from the grid signal alone.

---

## 📡 NILM — Appliance Detection Without Extra Hardware

**Non-Intrusive Load Monitoring** is the technique of identifying individual appliances from the aggregate grid power signal. CloudEMS includes a full NILM pipeline:

### How it detects devices

Every time your total power changes by more than a threshold, CloudEMS captures a **power event** — the signature of an appliance turning on or off. Each signature has a characteristic shape, magnitude, duration and timing. CloudEMS compares it against:

1. **Internal database** — thousands of pre-classified signatures (washing machines, ovens, heat pumps, EV chargers, etc.)
2. **Local AI** — a scikit-learn model trained on your own confirmed events, running entirely offline
3. **Ollama integration** — local Large Language Model for nuanced classification (optional, no data leaves your home)
4. **CloudEMS cloud AI** — highest accuracy option for difficult devices (optional, privacy-respecting)

### Smart Plug Anchoring

If you have **smart plugs** (Shelly, Tasmota, ESPHome, etc.), CloudEMS automatically discovers them and uses their readings as **anchors**. The anchored device's power is subtracted from the aggregate signal, giving the NILM a cleaner residual — improving detection accuracy from ~65% to ~85%+.

### Context-aware Bayesian classification

Detection scores are adjusted in real-time based on context:
- **Outdoor temperature** → heat pump and AC probability boosted when relevant
- **Time of day & weekday** → devices that rarely run at this hour get a penalty
- **Season** → winter vs summer device distribution
- **Phase balance** → 3-phase events (EV, heat pump) distinguished from 1-phase events

### Three-phase correlation

On 3-phase installations, CloudEMS analyses the **per-phase current deltas** from your DSMR5 meter to determine whether a new event is a 1-phase or 3-phase device — and which phase it's on. Smart plugs are also phase-attributed this way.

### User feedback loop

Every detected device can be confirmed, corrected or dismissed. Confirmed devices train the local AI model. The system gets smarter with every correction.

### What gets detected

| Device type | Notes |
|---|---|
| Washing machine, dryer, dishwasher | Cycle detection, program stage tracking |
| Oven, microwave, induction cooker | Power-level discrimination |
| Heat pump, boiler, electric heater | COP tracking, defrost detection |
| EV charger | Session learning, kWh per session |
| Refrigerator | Duty cycle monitoring, anomaly detection |
| Television, computer, entertainment | Standby detection |
| Solar inverter, home battery | Always excluded from NILM — tracked separately |

---

## 💰 Dynamic EPEX Prices & Cost Optimisation

CloudEMS fetches **day-ahead electricity prices** (EPEX Spot) and uses them to time every flexible load.

### Free price sources (no API key needed)

| Country | Source |
|---|---|
| 🇳🇱 Netherlands | EnergyZero |
| 🇩🇪 Germany | Awattar |
| 🇦🇹 Austria | Awattar |

### ENTSO-E (free API key required)

Belgium, France, Norway, Sweden, Denmark, Finland, and all other ENTSO-E areas.

### Self-learning cost forecaster

The cost forecaster tracks your **actual hourly consumption** day by day, weekday by weekday. After ~14 days it can predict:
- Remaining cost for today (actual so far + forecast remaining hours)
- Total cost for tomorrow (using tomorrow's EPEX prices + learned consumption)
- Monthly budget tracking with overspend alerts

The model continuously measures its own accuracy (MAPE) and self-corrects.

### Cheap-hours scheduling

CloudEMS identifies the cheapest 1, 2 or 3 consecutive hours of the day and exposes them as sensors. You can link any switch or automation to these windows. Four configurable slots let you schedule:
- Washing machine / dryer → turn on during cheapest 4 hours
- Dishwasher → cheapest 3 hours, but not before 06:00
- Extra boiler heat-up → cheapest single hour

CloudEMS only ever **turns devices on** — never off. Your programme runs to completion uninterrupted.

---

## ☀️ Solar Optimisation

### Self-learning PV forecast

CloudEMS builds a **statistical model** of your solar production by observing your actual inverter output, hour by hour, over weeks and months. Simultaneously it queries the free **Open-Meteo weather API** for irradiance forecasts and blends them with the statistical model.

The result: an accurate per-hour forecast for today and tomorrow, **without you needing to enter any panel specifications**.

### Automatic orientation & tilt detection

CloudEMS analyses the shape of your daily yield curves:
- The hour of peak production → derives **solar azimuth** (south = noon, east = morning peak)
- Morning-heavy vs afternoon-heavy yield → east/west bias
- Yield profile width → estimates **panel tilt**

After ~30 clear days the system becomes "confident" in its orientation estimate. You can also enter values manually — or leave it to learn.

### Multi-inverter management (up to 9 inverters)

Each inverter is tracked independently. CloudEMS learns which **grid phase** each inverter is on using the **Phase Prober** — a short, controlled dim-pulse that measures which phase current responds. This is done passively and automatically, without user intervention.

When a phase approaches its current limit, CloudEMS dims only the inverters on that phase, leaving others untouched. A **PID controller** (with anti-windup) ensures smooth transitions without oscillation.

### Clipping loss analysis

If your inverter regularly hits its power limit in summer, CloudEMS detects the plateau pattern and calculates:
- kWh lost per day/week/month to clipping
- Financial value of the loss at current EPEX prices
- Estimated payback period for a larger inverter

### PV health monitoring

By comparing recent peak production (7-day rolling average) against the all-time peak under comparable irradiance conditions, CloudEMS detects:
- **Soiling** — panels dirty, production down ~15%
- **Degradation** — year-on-year decline above the expected ~0.5%/year
- **Shadow** — structural shading at specific hours (identified per inverter, per hour slot)

---

## 🔋 Battery Management

### EPEX charge/discharge schedule

CloudEMS automatically builds an optimal battery schedule for each day:
- **Charge** during the N cheapest hours (configurable)
- **Discharge** during the N most expensive hours
- Respects current SoC, max charge/discharge power, and battery capacity
- Avoids scheduling charge during hours when solar will charge the battery anyway

### Seasonal strategy

In **summer**, solar often fully charges the battery by midday. Charging at night (even if cheap) wastes a cycle. CloudEMS detects this and shifts its strategy:
- Skip night charging if PV forecast covers > threshold
- Discharge window moves to the evening peak (17–22h)
- More discharge hours in summer (longer peak opportunity)

In **winter**, solar is negligible and pure EPEX scheduling is optimal. CloudEMS detects the season automatically from PV production patterns.

### Battery degradation tracking

CloudEMS tracks **State of Health (SoH)** over time:
- Full and partial charge cycle counting
- Deep discharge stress detection (below 10%)
- High SoC stress (continuous >95% charging)
- Temperature stress (if sensor available)
- Alerts at SoH < 90% (warning) and < 80% (critical)

Battery chemistry is configurable: LFP degrades more slowly than NMC/NCA and gets a different degradation curve.

---

## 🚗 EV Charging

### Dynamic current control

CloudEMS adjusts your EV charger's **charging current in real-time** using a PID controller:
- Solar surplus mode: charge at exactly the rate your panels are producing — no import, no waste
- Cheap-hours mode: charge at maximum configured current during cheap EPEX windows
- Phase protection mode: reduce current to prevent tripping your main fuse

The PID controller includes **auto-tuning** — it observes how the system responds to current changes and automatically optimises its own Kp/Ki/Kd parameters.

### EV session learner

After ~10 charging sessions CloudEMS learns your charging patterns:
- Typical plug-in hour per weekday
- Expected kWh per session
- Whether you're a commuter (Mon–Fri evening) or mixed pattern

This feeds into the **unified load planner** to pre-reserve the optimal cheap window for tomorrow's expected charge.

---

## ⚡ Phase Management

### Per-phase current monitoring

CloudEMS monitors import and export current on each phase (L1/L2/L3) every 10 seconds. When a phase approaches its limit, it throttles loads in priority order:
1. Dim solar inverter(s) on the overloaded phase
2. Reduce EV charging current
3. Shed configured sheddable loads

### Phase balancing

On 3-phase installations, CloudEMS tracks structural phase imbalance — one phase consistently heavier than others. It provides concrete advice: *"Move the washing machine from L1 to L3 — estimated 18% balance improvement."*

### Peak shaving

A configurable peak limit (in watts) triggers load shedding when import approaches the threshold. Useful for capacity tariff management. CloudEMS tracks your daily and monthly peak values and warns you before you exceed your tariff band.

### Grid congestion detection

If your import exceeds a configured threshold during high-price hours, CloudEMS declares a congestion event and automatically sheds non-critical loads, reducing EV charging to minimum current and delaying boiler cycles.

---

## 🏠 Presence Detection

CloudEMS determines whether anyone is home **purely from energy consumption patterns** — no GPS, no login events, no calendar, no PIR sensors.

It maintains two rolling signals:

1. **Standby deviation** — how far is current consumption from the learned night-time baseline? Near standby = likely empty.
2. **Weekly pattern deviation** — how far is current consumption from the same weekday/hour last week? Below pattern = likely away.

Both signals are blended into a single confidence score. States detected:

| State | Description |
|---|---|
| `home` | Normal consumption pattern |
| `away` | Power near standby for > 5 minutes |
| `sleeping` | Night-time pattern: low, smooth, constant |
| `vacation` | Away for > 8 consecutive hours |

This detection drives: lamp circulation security, heating pre-heat, EV charging priority, and energy saving automations.

---

## 💡 Lamp Circulation & Burglary Deterrence

When nobody is home, CloudEMS activates an intelligent lamp circulation system that makes the house appear occupied to the outside world.

### What makes it convincing

Most "burglary deterrence" timers are immediately recognisable — the same lamp turns on at the same time every day. CloudEMS does the opposite:

- **Random intervals** — each switch happens after a Gaussian-distributed random interval (2–8 minutes, weighted towards the middle). No two evenings are the same.
- **Variable lamp count** — 1, 2 or 3 lamps turn on simultaneously, weighted so 1 lamp is most common. Occasionally more, occasionally fewer — just like real people.
- **Behaviour mimicry** — CloudEMS learns which lamps you personally turn on at which hour of the week. During circulation it **weights those lamps higher**, so the pattern resembles your actual habits rather than random noise.
- **Neighbour correlation** — if nearby lights (neighbour automations) activate at the same time, CloudEMS shifts its own next switch moment by a random 15–45 seconds, so timings don't align suspiciously.

### Seasonal intelligence

The system starts and stops based on the actual position of the sun, not a fixed clock time. In June it starts later; in December it starts earlier — automatically, via the `sun.sun` entity. No reconfiguring required between seasons.

### PIR bypass

Lamps can be paired with a motion sensor (PIR). If the sensor detects motion, that lamp is excluded from the circulation for 5 minutes — preventing a lamp from being switched off while someone is in the room (useful for overnight stays where not everyone is away).

### Negative price bonus

During negative EPEX electricity prices, CloudEMS extends each circulation interval by 5 minutes — free electricity, maximum deterrence time.

### Passive phase detection

Every time the circulation switches a lamp, CloudEMS measures the per-phase current delta before and after. This passively determines **which grid phase each lamp is on**, adding to your overall phase map — with zero extra configuration.

### Test mode

A dashboard button starts the circulation immediately for 2 minutes regardless of presence state. This lets you verify all lamps are reachable and also triggers phase detection for newly added lamps.

---

## 🏊 Pool Controller

CloudEMS manages pool filtration and heating intelligently:

**Filtration:**
- Runs during PV surplus (free energy) whenever available
- Falls back to cheapest EPEX hours to meet minimum daily runtime
- Daily minimum adjusts with water temperature: more filtration when warm (bacterial growth risk)

**Heating:**
- Activates heat pump when water temperature drops below setpoint
- Prioritises PV surplus for heating
- COP-optimised timing: heats when outdoor temperature is highest (best heat pump efficiency)
- EPEX-price-aware: avoids expensive hours when not urgent

Supports: filter pump, heat pump, water temperature sensor, UV lamp, pool robot.

---

## 🏡 Home Intelligence & Learning

### Thermal house model

CloudEMS learns your home's **thermal loss coefficient** (W/°C) from heating power and outdoor temperature:
- Benchmarks your home against Dutch standards (1970s vs modern vs passive house)
- Powers the climate pre-heat advisor: pre-heat before expensive hours, reduce during peaks
- Predicts heating cost for the upcoming winter based on degree-day forecasts

### Home baseline & anomaly detection

168 weekly time slots (24h × 7 days) are individually tracked. CloudEMS learns your normal consumption per slot and alerts when something is significantly different:
- *"It's Tuesday 3 AM and you're using 900W more than normal"*
- Standby hunters: identifies devices that are always on across several nights

### Gas analysis

For homes with gas heating, CloudEMS correlates gas consumption with outdoor temperature (Heating Degree Days) to:
- Benchmark your boiler efficiency against Dutch norms
- Detect sudden consumption spikes (gas leak, burner problem)
- Forecast winter gas costs

### Day-type classification

CloudEMS automatically distinguishes between: office days (low daytime, evening peak), work-from-home days (high daytime), weekends (later peaks), and holidays (standby only). This improves all forecasts and scheduling decisions.

### Consumption categories

NILM devices are automatically grouped into categories with daily kWh breakdown:
🔥 Heating · 🚗 EV / Mobility · 🫧 White goods · 🍳 Kitchen · 📺 Entertainment · ❄️ Cooling · 🔌 Always-on · 🔧 Other

### Virtual room meters

CloudEMS clusters devices and smart plugs by room, using the HA Area Registry, keyword matching in entity names, and device-type heuristics:
- Real-time per-room consumption (W)
- Daily kWh per room
- Percentage of total home consumption

### Sensor sanity guard

Before any calculation, all sensor values are validated:
- Hard magnitude limits (> 55 kW grid, > 50 kW PV → impossible)
- kW/W unit confusion detection
- Spike vs own history (> 8× learned mean)
- Sign errors (exporting while sun=0 and battery=0)
- Per-phase limits

Corrupted readings are filtered before they can affect NILM, scheduling or cost calculations.

### Smart sensor hint engine

CloudEMS analyses your grid signal for patterns it recognises — even from sensors you haven't configured. If your grid power drops during midday consistently, it suggests you might have solar panels connected to a sensor not yet linked. If rapid step-changes appear, it suggests a battery may be present.

---

## 📊 Sensors & Entities

CloudEMS exposes 100+ sensors. Key examples:

| Domain | Sensor | Description |
|---|---|---|
| Grid | `grid_net_power` | Live net import/export (W) |
| Grid | `phase_l1_current` | Per-phase current (A) |
| Price | `energy_price_current_hour` | Current EPEX price (€/kWh) |
| Price | `cheapest_hour_today` | Start time of cheapest 1h block |
| Price | `energy_cost_today` | Actual cost so far today (€) |
| Price | `energy_cost_forecast_today` | Predicted total cost today (€) |
| NILM | `nilm_running_devices` | Count of detected active appliances |
| NILM | `nilm_device_*` | Per-device power, kWh, confidence |
| Solar | `solar_pv_forecast_today` | Predicted PV yield today (kWh) |
| Solar | `pv_health` | Panel health status |
| Solar | `clipping_loss_today` | Lost kWh to inverter clipping |
| Battery | `battery_epex_schedule` | Current charge/discharge action |
| Battery | `battery_soh` | State of Health (%) |
| EV | `ev_session_kwh` | Energy delivered in current session |
| Presence | `occupancy` | home / away / sleeping / vacation |
| Lamps | `lamp_circulation_status` | Circulation mode + active lamps |
| Pool | `pool_status` | Filter + heater state + water temp |
| House | `thermal_w_per_k` | Thermal loss coefficient (W/°C) |
| House | `anomaly_detected` | Unusual consumption for this time slot |
| Costs | `energy_budget_status` | Budget tracking (on track / overspend) |

---

## 🎨 Dashboard

The included `cloudems-dashboard.yaml` provides **11 fully-styled tabs** for a complete overview of your home's energy system. Import it via the HA Lovelace dashboard editor.

**Required frontend cards (all free, installable via HACS):**
- [mushroom-cards](https://github.com/piitaya/lovelace-mushroom)
- [apexcharts-card](https://github.com/RomRider/apexcharts-card)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)

**Tabs included:**

| Tab | Content |
|---|---|
| 🏠 Overview | Live grid, solar, battery, current cost |
| ⚡ Energy & Prices | EPEX price chart, cheap-hours countdown |
| 🔌 Phases & Current | Per-phase current, phase balance, peak |
| 🧠 NILM | Detected devices, AI confidence, feedback buttons |
| ☀️ Solar | PV forecast chart, inverter health, clipping |
| 🔋 Battery | EPEX schedule, SoH, charge history |
| 🚗 EV | Dynamic charging, session history |
| 🌡️ Climate | Pre-heat advice, thermal model, gas analysis |
| 💧 Pool | Filter/heater status, water temperature |
| 💡 Lamps | Circulation status, phase detection, test button |
| 📈 Costs | Daily/monthly forecast, budget tracker, categories |

---

## 🛠 Requirements

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1.0 or newer |
| Smart meter | P1 port or compatible integration (DSMR, HomeWizard, Shelly EM, etc.) |
| Python | 3.11+ (built into HA — nothing to install) |
| Ollama | Optional — for local LLM-based NILM classification |

---

## ☕ Support CloudEMS

CloudEMS is **completely free and open source**. It takes hundreds of hours per year to develop and maintain. If CloudEMS saves you money on your energy bill — and it will — please consider a small contribution to keep the project going.

<div align="center">

### 👉 [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems) ☕

*Even a coffee a month makes a real difference. Thank you.*

</div>

You can also support by:
- ⭐ Starring this repository
- 🐛 [Reporting bugs](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=bug_report.md) so we can fix them
- 💡 [Requesting features](https://github.com/cloudemsNL/ha-cloudems/issues/new?template=feature_request.md)
- 📣 Telling other HA users about CloudEMS

---

## 📄 License

MIT © 2026 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

<div align="center">
<sub>Keywords: Home Assistant energy management · NILM · EPEX prices · dynamic EV charging · peak shaving · phase balancing · solar curtailment · Ollama AI · lamp circulation · burglary deterrence · smart meter · P1 · DSMR</sub>
</div>
