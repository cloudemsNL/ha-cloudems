In ontwikkeling, nog niet productie klaar.

# ⚡ CloudEMS — Slimme Energiebeheer voor Home Assistant

> **"Stroom is geld. CloudEMS zorgt dat jij het beheert — niet het energiebedrijf."**

**CloudEMS** is een krachtige Home Assistant-integratie die je energieverbruik intelligent beheert. Het begrijpt je verbruikspatronen, optimaliseert je zonnepanelen en stemt apparaten af op de goedkoopste uren van de dag. Geen dure slimme stekkers of cloud-abonnementen nodig: alles draait lokaal, privacy-first en volledig gratis.

> 🌐 [cloudems.eu](https://cloudems.eu) · 📖 [Documentatie](https://github.com/cloudemsNL/ha-cloudems) · 🐛 [Issues](https://github.com/cloudemsNL/ha-cloudems/issues)

---

## ✨ Kernfuncties

### 🧠 Intelligent NILM & AI (Apparaatdetectie)

CloudEMS maakt gebruik van **Non-Intrusive Load Monitoring** om individuele apparaten te herkennen aan hun "vingerafdruk" op de stroommeter.

* **Geavanceerde Detectie:** Herkent wasmachines, ovens, warmtepompen en meer zonder extra hardware.
* **Slimme Filtering:** Onderscheidt feilloos tussen het laden van een thuisbatterij en thermische lasten (zoals verwarming), waardoor dubbeltellingen worden voorkomen.
* **Ollama AI Diagnostics:** Volledige ondersteuning voor lokale LLM's (Ollama) voor classificatie, inclusief real-time health-checks, responstijden en een ring-buffer voor de laatste 20 analyses.
* **Nauwkeurigheid:** Ingebouwde mechanismen schalen categorieën automatisch naar je werkelijke netto-verbruik voor 100% kloppende dashboards.

### 💰 Dynamische EPEX-prijzen & Kosten

Bespaar op je energierekening door gebruik te maken van de energiemarkt.

* **Gratis prijsdata:** Directe integratie voor NL, DE en AT (geen API-sleutel nodig). Overige landen via ENTSO-E.
* **Kostenvoorspelling:** Een zelflerend model dat je dagelijkse en maandelijkse kosten voorspelt op basis van historische patronen.
* **Automatisering:** Ingebouwde sensoren voor de goedkoopste 1, 2 of 3 uur van de dag.

### 🔋 Slim EV & Batterijbeheer

Maximaliseer je onafhankelijkheid met geavanceerde sturing.

* **Dynamisch EV laden:** Gebruikt een PID-regelaar (met Auto-Tuning) om je laadstroom vloeiend aan te passen aan je zonne-overschot.
* **Batterij EPEX-schema:** Automatische laadplanning voor de 3 goedkoopste uren en ontladen tijdens de 3 duurste uren.
* **Fase-beveiliging:** Voorkomt het springen van hoofdzekeringen door verbruik per fase te monitoren en bij te sturen.

### 📊 Inzicht & Gebouwbeheer

* **Aanwezigheidsdetectie:** Bepaalt de status (Home/Away/Sleeping/Vacation) puur op basis van verbruikspatronen.
* **Verwarmingsadvies:** Geeft pre-heat en reduceer-advies op basis van prijs- en weersvoorspellingen.
* **Multi-omvormer:** Ondersteunt tot 9 omvormers met automatische detectie van azimut en hellingshoek.

---

## 🌍 Ondersteunde Landen (EPEX)

| Land | Code | Gratis | Bron |
| --- | --- | --- | --- |
| 🇳🇱 Nederland | `NL` | ✅ | EnergyZero |
| 🇩🇪 Duitsland | `DE` | ✅ | Awattar |
| 🇦🇹 Oostenrijk | `AT` | ✅ | Awattar |
| 🇧🇪/🇫🇷/🇳🇴/... | BE/FR.. | 🔑 | ENTSO-E (Gratis sleutel nodig) |

---

## 🚀 Installatie & Configuratie

### Via HACS (Aanbevolen)

1. Voeg `https://github.com/cloudemsNL/ha-cloudems` toe als **Custom Repository**.
2. Zoek naar **CloudEMS** en klik op downloaden.
3. Herstart Home Assistant.

### De Wizard

De configuratie is volledig modulair. De wizard toont alleen wat voor jou relevant is:

1. **Netaansluiting:** Configureer je sensoren (P1, DSMR, of direct via TCP).
2. **PV & EV:** Koppel je omvormers en laders voor dynamische sturing.
3. **AI & NILM:** Kies je provider (Lokaal, Ollama of Cloud).
4. **Kosten:** Voer je tarieven, belastingen en marges in.

---

## 🛠 Sensoren & Entiteiten (Overzicht)

| Categorie | Belangrijke Sensoren |
| --- | --- |
| **Grid** | `grid_net_power`, `phase_l1_current`, `peak_shaving_w` |
| **Energie** | `energy_price_current_hour`, `net_co2_intensiteit`, `energy_cost_today` |
| **AI** | `nilm_running_devices`, `ollama_diagnostics`, `sensor_sanity` |
| **Zon** | `solar_pv_forecast_today`, `omvormer_efficientiedrift` |
| **Status** | `occupancy`, `climate_preheat`, `battery_epex_schema` |

---

## 🎨 Lovelace Dashboard

CloudEMS wordt geleverd met een uitgebreid `cloudems-dashboard.yaml`. Dit dashboard biedt 10 tabbladen voor een volledig overzicht van je woning, inclusief ApexCharts integratie voor prijs- en verbruiksverloop.

---

## ☕ Steun de ontwikkeling

CloudEMS is open source en kost honderden uren per jaar aan onderhoud. Bespaar je maandelijks op je energierekening? Overweeg een kleine bijdrage:

* **Buy Me a Coffee:** [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems)

---

## 📄 Licentie

MIT © 2026 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

*Trefwoorden: Home Assistant energiebeheer, NILM, EPEX prijzen, dynamisch laden, piekafschaving, fase-balancering, zonnebegrenzing, Ollama AI*

---
