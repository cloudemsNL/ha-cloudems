# ⚡ CloudEMS — Intelligent Energy Management

CloudEMS transforms your Home Assistant into a **self-learning energy brain** — fully local, no subscription, no extra hardware required.

## What it does

- **🧠 NILM** — detects appliances from your smart meter without extra hardware
- **💰 EPEX prices** — optimises every flexible load to the cheapest electricity hours
- **☀️ Solar** — self-learning PV forecast, clipping detection, per-inverter tracking
- **🔋 Battery** — optimal charge/discharge scheduling with degradation tracking
- **🔥 Gas** — TTF Day-Ahead pricing, all-in cost calculation
- **🚗 EV** — dynamic charging with solar surplus and price optimisation; hybrid EV fuel/electric advisor
- **❄️ Multisplit airco** — per-room power distribution across 11 brands
- **🪟 Shutters** — thermal learning, schedule learning, weather protection
- **🌍 CO₂ tracker** — real-time grid intensity, personal carbon footprint vs country average
- **📉 Net metering advisor** — personalised advice for the NL 2027 phase-out (and other countries)
- **⚡ Demand response** — automatic load shifting on EPEX spikes and national grid surplus
- **🌐 National grid monitor** — NED (NL), with DE/BE/GB stubs; surplus signal for smart charging
- **⛽ Fuel prices** — CBS (NL) and country fallbacks; generator break-even vs grid price
- **📊 Battery benchmark** — optional Mijnbatterij.nl reporting (NL); extensible for other platforms
- **🗺️ Grid congestion** — capaciteitskaart.netbeheernederland.nl (NL); auto-limits feed-in in congestion zones

## Supported hardware (auto-detected)

**Inverters:** Growatt, GoodWe, Fronius, SMA, Enphase Envoy, Huawei Solar, Alpha ESS  
**Batteries:** Zonneplan Nexus, Homevolt, Huawei Luna 2000, Alpha ESS  
**EV chargers:** EVCC (50+ brands), NRGkick, Wallbox  
**Grid meters:** P1/DSMR, Shelly EM, Shelly 3EM  
**Airco:** Daikin, LG, Mitsubishi, Toshiba, Samsung, Fujitsu and more  
**Sensors:** Netatmo, Ecowitt, Open-Meteo

## Countries supported

| Country | EPEX | Fuel prices | Net metering | CO₂ intensity | Grid congestion |
|---------|------|-------------|--------------|---------------|-----------------|
| 🇳🇱 NL | ✅ | ✅ CBS OData | ✅ WEK schedule | ✅ NED API | ✅ capaciteitskaart |
| 🇧🇪 BE | ✅ | ✅ fallback | ✅ no phase-out | ✅ estimate | 🔜 Elia |
| 🇩🇪 DE | ✅ | ✅ fallback | ➖ feed-in tariff | ✅ estimate | 🔜 BNetzA |
| 🇫🇷 FR | ✅ | ✅ fallback | ✅ no phase-out | ✅ estimate | — |
| 🇬🇧 GB | ✅ | ✅ fallback | ✅ SEG 50% | ✅ estimate | — |

## Setup

After installation, open the interactive setup wizard:
```
http://homeassistant.local:8123/local/cloudems/onboarding.html
```

The wizard auto-detects your hardware and guides you step by step.

---
[📖 Documentation](https://github.com/cloudemsNL/ha-cloudems/wiki) · [☕ Buy Me a Coffee](https://buymeacoffee.com/smarthost9m)
