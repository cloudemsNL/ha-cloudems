# ⚡ CloudEMS — Smart Energy Management for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?logo=home-assistant)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/cloudemsNL/ha-cloudems?include_prereleases&label=version&logo=github)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg?logo=home-assistant)](https://www.home-assistant.io)
[![Languages](https://img.shields.io/badge/languages-EN%20%7C%20NL%20%7C%20DE-lightgrey)](translations/)

**CloudEMS** is a professional, privacy-first Home Assistant integration for smart energy management. It brings real-time NILM device detection, per-phase current limiting, dynamic EV charging, EPEX electricity prices, solar curtailment, peak shaving, and PV forecasting — all running locally on your Home Assistant instance.

> 🌐 [cloudems.eu](https://cloudems.eu) · 📖 [Documentation](https://github.com/cloudemsNL/ha-cloudems) · 🐛 [Issues](https://github.com/cloudemsNL/ha-cloudems/issues)

---

## 📋 Table of Contents

- [Features](#features)
- [Supported Countries](#supported-countries)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration Wizard](#configuration-wizard)
- [Sensors & Entities](#sensors--entities)
- [NILM — Device Detection](#nilm--device-detection)
- [Dynamic EV Charging](#dynamic-ev-charging)
- [Peak Shaving](#peak-shaving)
- [Phase Balancing](#phase-balancing)
- [EPEX Prices](#epex-prices)
- [Multi-Inverter Management](#multi-inverter-management)
- [P1 / DSMR Integration](#p1--dsmr-integration)
- [Lovelace Dashboard](#lovelace-dashboard)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **NILM** | Non-Intrusive Load Monitoring — detect washing machines, EV chargers, boilers and more from grid data, no smart plugs needed |
| ⚡ **Phase limiting** | Prevent main fuse trips by monitoring and limiting current per phase in real time |
| ☀️ **Solar curtailment** | Automatically reduce inverter output during negative EPEX prices |
| 💰 **EPEX day-ahead prices** | Live electricity prices for 10 European countries with cheapest-hour binary sensors |
| 🔋 **Dynamic EV charging** | Automatically adjust EV charger current based on solar surplus and EPEX price |
| 📊 **Peak shaving** | Shed controllable loads to stay under your monthly peak demand limit (Belgian capacity tariff and beyond) |
| ⚖️ **Phase balancing** | Redistribute loads across L1/L2/L3 to prevent imbalance |
| 🌤️ **PV forecast** | Statistical + Open-Meteo weather-based forecast per inverter |
| 🤖 **Local & Cloud AI** | NILM classification via built-in patterns, Ollama local LLM, or CloudEMS cloud API |
| 📡 **P1/DSMR direct** | Optional direct TCP connection to HomeWizard P1 or DSMR-reader |
| 🔆 **Multi-inverter** | Manage up to 9 inverters independently with self-learning azimuth/tilt |
| 💶 **Cost tracking** | Daily/monthly/yearly energy cost based on live EPEX prices |

---

## 🌍 Supported Countries

CloudEMS supports EPEX day-ahead electricity prices for:

| Country | Code | Notes |
|---------|------|-------|
| 🇳🇱 Netherlands | `NL` | EPEX SPOT, includes peak/off-peak |
| 🇧🇪 Belgium | `BE` | Includes capacity tariff support |
| 🇩🇪 Germany | `DE` | EPEX SPOT Germany/Austria |
| 🇫🇷 France | `FR` | RTE day-ahead |
| 🇦🇹 Austria | `AT` | APG |
| 🇨🇭 Switzerland | `CH` | Swissgrid |
| 🇩🇰 Denmark | `DK` | Energinet |
| 🇳🇴 Norway | `NO` | Statnett |
| 🇸🇪 Sweden | `SE` | Svenska kraftnät |
| 🇫🇮 Finland | `FI` | Fingrid |

---

## 📦 Requirements

- **Home Assistant** 2024.1 or newer
- **HACS** (recommended) or manual installation
- At least one power sensor (W or kW) from a smart meter, P1 integration, or clamp meter

**Optional but recommended:**
- Per-phase current sensors (A) — for phase limiting and balancing
- Solar inverter power sensor — for NILM and EV solar charging
- EV charger `number` entity — for dynamic current control

---

## 🚀 Installation

### Via HACS (recommended)

1. Open **HACS** in Home Assistant
2. Go to **Integrations** → click the ⋮ menu → **Custom repositories**
3. Add URL: `https://github.com/cloudemsNL/ha-cloudems` — Category: **Integration**
4. Find **CloudEMS** and click **Download**
5. **Restart Home Assistant**
6. Go to **Settings → Integrations → Add integration** → search for **CloudEMS**

### Manual Installation

```bash
# Download and copy to your config directory
wget https://github.com/cloudemsNL/ha-cloudems/releases/latest/download/ha-cloudems.zip
unzip ha-cloudems.zip
cp -r custom_components/cloudems /config/custom_components/
```

Then restart Home Assistant and add the integration via **Settings → Integrations**.

---

## 🧙 Configuration Wizard

The CloudEMS setup wizard guides you through all steps. **Fields that are not relevant to your setup are hidden automatically** — you only see what you need.

### Step-by-step overview

| Step | Title | Description |
|------|-------|-------------|
| 1 | 🌍 Country | Select your EPEX country for electricity price data |
| 2 | ⚡ Grid connection | Choose your fuse size (e.g. 3×25 A) or enter custom limits |
| 3 | 🔌 Grid sensors | Net power sensor or separate import/export sensors |
| 4 | 🔌 Phase sensors | Optional per-phase current, voltage and power sensors |
| 5 | 🌞 Solar & EV | Solar inverter, battery, EV charger, solar curtailment |
| 6 | ☀️ Inverters | Configure 0–9 inverters with self-learning orientation |
| 7 | 🚀 Features | Enable dynamic loading, cost tracking, peak shaving, phase balancing |
| 7b | 📊 Peak shaving | Peak limit and sheddable loads *(only if peak shaving enabled)* |
| 8 | 🤖 AI & NILM | Cloud API key or Ollama toggle |
| 8b | 🤖 Ollama | Ollama host/port/model *(only if Ollama enabled)* |
| 9 | 📡 P1 meter | Enable direct P1 connection *(optional)* |
| 9b | 📡 P1 settings | P1 gateway IP/port *(only if P1 enabled)* |

> ℹ️ **Auto-detection:** CloudEMS scans your existing sensors and pre-fills suggestions based on keyword matching. This works for power (W/kW), current (A) and voltage (V) sensors.

### Changing settings later

Go to **Settings → Integrations → CloudEMS → Configure** and select the section you want to edit:

- 🔌 **Sensors & Grid** — change sensor entities, phase count, fuse sizes
- ☀️ **Solar & EV** — update inverter/battery/EV entities
- 🚀 **Features** — toggle features, update thresholds
- 🤖 **AI & NILM** — switch AI backend
- 📡 **P1 & Advanced** — P1 connection settings

---

## 📊 Sensors & Entities

CloudEMS creates sensors grouped by category for easy navigation in Home Assistant:

### Grid sensors
| Sensor | Description |
|--------|-------------|
| `CloudEMS Grid · Net Power` | Current grid import/export power (W) |
| `CloudEMS Grid · Phase L1/L2/L3 Current` | Per-phase current (A) |
| `CloudEMS Grid · Phase L1/L2/L3 Voltage` | Per-phase voltage (V) |
| `CloudEMS Grid · Phase L1/L2/L3 Power` | Per-phase power (W) |
| `CloudEMS Grid · Phase Imbalance` | Max imbalance between phases (A) |
| `CloudEMS Grid · Peak Shaving` | Current peak demand (W) |
| `CloudEMS Grid · P1 Net Power` | Power from direct P1 connection (W) |

### Energy sensors
| Sensor | Description |
|--------|-------------|
| `CloudEMS Energy · Price` | Current EPEX electricity price (EUR/kWh) |
| `CloudEMS Energy · Cost` | Real-time energy cost (EUR/h) |
| `CloudEMS Energy · Insights` | AI-generated energy insights and recommendations |
| `CloudEMS Energy · Cheapest 1h/2h/3h` | Binary sensor — is this one of the N cheapest hours today? |

### Solar sensors
| Sensor | Description |
|--------|-------------|
| `CloudEMS Solar · PV Forecast Today` | Expected solar production today (kWh) |
| `CloudEMS Solar · [Inverter Name]` | Per-inverter power, peak, clipping, utilisation |

### NILM sensors
| Sensor | Description |
|--------|-------------|
| `CloudEMS NILM · Devices` | Number of detected appliances |
| `CloudEMS NILM · [Device Name]` | Per-device power, energy, confidence |

### System sensors
| Sensor | Description |
|--------|-------------|
| `CloudEMS System · Decision Log` | Recent automation decisions (diagnostic) |
| `CloudEMS Boiler · Status` | Boiler on/off tracking |

### Switches
| Switch | Description |
|--------|-------------|
| `CloudEMS Solar Dimmer` | Enable/disable solar curtailment |
| `CloudEMS Smart EV Charging` | Enable/disable solar surplus EV charging |

---

## 🧠 NILM — Device Detection

**Non-Intrusive Load Monitoring** detects which appliances are active from your whole-home power signal — no smart plugs required.

CloudEMS supports three AI backends:

| Backend | Accuracy | Privacy | Requirements |
|---------|----------|---------|--------------|
| **Built-in** | Good | ✅ 100% local | None |
| **Ollama** | Better | ✅ 100% local | Ollama running locally |
| **Cloud API** | Best | Data sent to CloudEMS cloud | CloudEMS subscription |

Detected devices get their own sensor with:
- Current power (W)
- On/off state and confidence
- Daily / weekly / monthly / yearly energy (kWh)
- Phase assignment (L1/L2/L3)

**Detected device types:** Washing machine, dryer, dishwasher, oven, microwave, kettle, TV, computer, heat pump, boiler, EV charger, solar inverter, lights.

---

## 🔋 Dynamic EV Charging

CloudEMS dynamically adjusts your EV charger current based on:

- **Solar surplus** — charge faster when PV produces more than your house consumes
- **EPEX prices** — increase charging during the cheapest hours, reduce during expensive hours
- **Phase limits** — never exceed your grid connection fuse size

Requirements: an EV charger with a `number` entity for the current setpoint (e.g. Easee, OCPP, go-e, Alfen, Zaptec).

---

## 📊 Peak Shaving

Relevant for **Belgian capacity tariff** and anyone wanting to control peak demand.

CloudEMS tracks your monthly peak (kW) and automatically switches off sheddable loads (e.g. boiler, washing machine, EV charger) when grid demand exceeds your configured limit.

Configure which entities can be shed via **Settings → CloudEMS → Configure → Features**.

---

## ⚖️ Phase Balancing

For 3-phase installations, CloudEMS monitors the current on each phase and can redistribute loads to keep imbalance within the configured threshold. This prevents asymmetric loading and potential fuse trips.

Requires per-phase current sensors (A).

---

## 💰 EPEX Prices

CloudEMS fetches day-ahead EPEX prices automatically (no API key needed). The **Cheapest Nh binary sensors** turn `on` during the N cheapest hours of the day — use them in automations:

```yaml
# Example: start dishwasher during cheapest 3 hours
automation:
  trigger:
    - platform: state
      entity_id: binary_sensor.cloudems_energy_cheapest_3h
      to: "on"
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.dishwasher
```

---

## ☀️ Multi-Inverter Management

Manage up to 9 PV inverters independently. CloudEMS self-learns each inverter's:

- **Peak power (Wp)** — estimated from production history
- **Azimuth & tilt** — learned from daily production curves
- **Phase assignment** — automatically detected

During solar curtailment, inverters are dimmed in priority order (configurable).

---

## 📡 P1 / DSMR Integration

Most users get P1 data via the [DSMR integration](https://www.home-assistant.io/integrations/dsmr/) or [HomeWizard](https://www.home-assistant.io/integrations/homewizard/). CloudEMS uses these existing sensors automatically.

For direct TCP connection (e.g. HomeWizard P1 dongle), enable the P1 option in the wizard.

---

## 🎨 Lovelace Dashboard

A ready-to-use Lovelace dashboard card (`cloudems-card.js`) is included. Install it as a [custom card](https://www.home-assistant.io/lovelace/custom-cards/).

The included `cloudems-dashboard.yaml` provides a complete overview dashboard with:
- Live power flow
- EPEX price chart
- Per-phase gauges
- NILM device list
- Solar forecast

---

## 🔧 Troubleshooting

### Common errors

**`ImportError: cannot import name 'ATTRIBUTION'`**
→ You are running v1.4.0 or v1.4.1 with an older `const.py`. Update to v1.4.2+.

**Sensors show `unavailable`**
→ Check that your configured sensor entities still exist. Go to **Settings → CloudEMS → Configure → Sensors & Grid** and verify or update the entity selections.

**Auto-detection picks wrong sensors**
→ The wizard auto-suggests sensors based on keyword matching. You can always override suggestions by clearing the field and selecting the correct sensor manually.

**EPEX prices not updating**
→ Prices update at 13:00 CET daily. Check the `CloudEMS Energy · Price` sensor's attributes for `last_updated`. Ensure your HA has internet access.

### Enable debug logging

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.cloudems: debug
```

### Diagnostics

CloudEMS supports the built-in HA diagnostics. Go to **Settings → Integrations → CloudEMS → three-dot menu → Download diagnostics** to generate a redacted report useful for bug reports.

---

## ❓ FAQ

**Does CloudEMS need internet access?**
Only for EPEX price fetching and optional Cloud AI NILM. All energy management runs locally.

**Does it work with single-phase connections?**
Yes. Select `1×16A`, `1×25A`, etc. in the setup wizard. Phase-specific features are automatically hidden.

**Can I use it without a smart meter?**
Yes, if you have any power sensor (e.g. from a clamp meter, SolarEdge, Fronius, Huawei, Solis, etc.) you can use CloudEMS. P1/DSMR is optional.

**Which EV chargers are supported?**
Any charger that exposes a `number` entity for the charging current setpoint. Tested with: Easee, go-e, OCPP (generic), Alfen Eve, Zaptec.

**Is my data sent to the cloud?**
No by default. EPEX price fetching is the only outbound request. Cloud AI NILM is opt-in and requires a subscription.

---

## 🤝 Contributing

Contributions are very welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push and open a Pull Request

Please open an [issue](https://github.com/cloudemsNL/ha-cloudems/issues) first for large changes.

---

## 📄 License

MIT © 2025 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

*Keywords: Home Assistant energy management, NILM appliance detection, EPEX day-ahead prices, dynamic EV charging, peak shaving, phase balancing, solar curtailment, smart home energy, HA custom integration, HACS*
