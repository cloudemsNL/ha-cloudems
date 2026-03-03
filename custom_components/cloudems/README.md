# ⚡ CloudEMS — Slimme Energiebeheer voor Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?logo=home-assistant)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/cloudemsNL/ha-cloudems?include_prereleases&label=versie&logo=github)](https://github.com/cloudemsNL/ha-cloudems/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg?logo=home-assistant)](https://www.home-assistant.io)
[![Languages](https://img.shields.io/badge/talen-EN%20%7C%20NL%20%7C%20DE-lightgrey)](translations/)

> **"Stroom is geld. CloudEMS zorgt dat jij het beheert — niet het energiebedrijf."**

**CloudEMS** begon als een persoonlijk project: een Home Assistant-integratie die écht slim omgaat met energie. Geen dure slimme stekkers nodig, geen cloud-abonnement, geen ingewikkeld gedoe. Gewoon je verbruik begrijpen, je zonnepanelen optimaal benutten en je verbruik afstemmen op de goedkoopste uren van de dag.

Vandaag is CloudEMS uitgegroeid tot een volwaardige energiemanager die draait op elk Home Assistant-systeem — privacy-first, lokaal, en gratis te gebruiken.

> 🌐 [cloudems.eu](https://cloudems.eu) · 📖 [Documentatie](https://github.com/cloudemsNL/ha-cloudems) · 🐛 [Issues](https://github.com/cloudemsNL/ha-cloudems/issues)

---

## 🆕 Wat is er nieuw in v1.9.0?

### 🌱 CO2-intensiteit sensor (altijd actief, geen configuratie nodig)

CloudEMS toont nu de CO2-intensiteit van het elektriciteitsnet in gCO2eq/kWh.

| Bronnen | Beschikbaarheid |
|---------|----------------|
| Electricity Maps API | Gratis, geen sleutel |
| CO2 Signal API | Gratis token vereist |
| EEA 2023 statisch gemiddelde | Altijd, offline |

Gebruik het om automaties te maken als: *"Laad de EV alleen wanneer het net groen is (<200g)"*.

### 🔌 P1 direct naar NILM — hoogste kwaliteit invoer

Wanneer je een P1-lezer hebt geconfigureerd (SLIMMELEZER, HomeWizard, USB), worden de per-fase vermogens uit het DSMR-telegram nu **direct naar de NILM-detector gestuurd** — zonder vertraging via HA-sensoren. Dit is de beste mogelijke NILM-invoer.

**Prioriteitsvolgorde NILM-invoer (v1.9):**

| Prioriteit | Bron | Kwaliteit |
|-----------|------|----------|
| 1 | P1 direct (DSMR5 per-fase W) | ⭐⭐⭐⭐⭐ |
| 2 | P1 stroom × spanning (DSMR4) | ⭐⭐⭐⭐ |
| 3 | Per-fase HA vermogenssensor | ⭐⭐⭐⭐ |
| 4 | Totaal netverbruik ÷ fasen | ⭐⭐ |
| 5 | Totaal netverbruik op L1 | ⭐ |

### 🔋 Batterij EPEX-schema (automatische laadplanning)

CloudEMS plant automatisch wanneer je batterij moet laden en ontladen op basis van EPEX dag-aheadprijzen.

- **Laden**: 3 goedkoopste uren van de dag
- **Ontladen**: 3 duurste uren van de dag
- **Veiligheid**: stopt laden bij SoC > 90%, stopt ontladen bij SoC < 20%
- **Slim**: slaat gepland laden over als PV het al doet

Benodigde configuratie (optioneel):
```yaml
# configuration.yaml (of via UI opties)
battery_scheduler_enabled: true
battery_soc_entity: sensor.battery_state_of_charge
battery_charge_entity: number.battery_charge_power
battery_discharge_entity: number.battery_discharge_power
battery_capacity_kwh: 10.0
battery_max_charge_w: 3000
battery_max_discharge_w: 3000
```

### 📊 Energiekosten-voorspelling (zelf-lerend)

De sensor **`CloudEMS Energie · Kosten Verwachting`** voorspelt wat je vandaag en morgen kwijt bent aan stroom.

- **Zelf-lerend**: leert jouw verbruikspatroon per uur (exponentieel voortschrijdend gemiddelde)
- **Nauwkeurigheid neemt toe**: na 5+ dagen bruikbaar, na 14+ dagen betrouwbaar
- **Morgen-preview**: als EPEX-prijzen voor morgen bekend zijn (na ~13:00) geeft het ook een schatting voor morgen
- **ApexCharts-klaar**: `hourly_patterns` attribuut geeft verbruikscurve per uur voor grafieken

### 🖥️ Professioneel dashboard YAML (`cloudems-dashboard-v1.9.yaml`)

Compleet klaar dashboard met:
- Live EPEX prijsgrafiek vandaag + morgen (ApexCharts kolommen)
- Fase-stroom monitor (live lijndiagram)
- NILM apparatenlijst
- Kosten-widgets (vandaag actueel + verwachting + morgen)
- CO2-intensiteitskaart
- NILM diagnose pagina (events, baseline per fase, classificatierate)
- PID-tuning pagina met live state-grafieken

Vereist: `apexcharts-card` en `mushroom-cards` via HACS.

---

## 🆕 Wat is er nieuw in v1.9.0?

### 🧠 Zelf-lerende verbeteringen

**Adaptieve NILM-drempel**
Voorheen was de detectiedrempel hardcoded op 25W. Nu leert CloudEMS automatisch hoe "rustig" of "lawaaierig" jouw netsignaal is, en past de drempel aan. Een goede P1-meter kan zakken naar ~10W (detecteert waterkoker van 1200W én LED-lamp van 40W). Een goedkope klemstroomtransformator blijft hoger om valse meldingen te vermijden.

**EV laden via PID-regelaar**
De dynamische EV-lader gebruikt nu een echte PID-regelaar in plaats van drempel-logica. Setpoint = 0W netimport. Resultaat: gladde laadstroomregeling die automatisch meegaat met wisselende zonproductie en bewolking — geen harde sprongen meer.

**PID Auto-Tuner (Relay Feedback)**
Voor installaties met fase-begrenzing: CloudEMS kan zichzelf automatisch afregelen met de Åström-Hägglund relay-methode (Ziegler-Nichols). Dit bepaalt de ideale Kp/Ki/Kd voor jouw specifieke installatie. Start via de HA-service `cloudems.start_pid_autotune`.

### 🔌 NILM sensor-cascade

Voorheen werkte NILM alleen met per-fase vermogenssensoren. Nu is er een cascade:

| Prioriteit | Bron | Wanneer |
|-----------|------|---------|
| 1 | Per-fase vermogenssensor (W) | Beste: aparte sensor per L1/L2/L3 |
| 2 | Per-fase stroomsensor (A × U) | Goed: stroomsensor zonder aparte vermogenssensor |
| 3 | Totaal netverbruik ÷ 3 fasen | Fallback: verdeeld over fasen |
| 4 | Totaal netverbruik op L1 | Laatste: enkelfasige installaties |

De sensor **CloudEMS NILM · Sensor Input** toont precies welke modus actief is en geeft aanbevelingen voor verbetering.

### 🎛️ Instelbare PID-parameters

Nieuwe instelentiteiten (zichtbaar in HA onder **Instellingen → CloudEMS**):

| Entiteit | Beschrijving | Standaard |
|---------|-------------|---------|
| `CloudEMS Fase PID · Kp` | Proportionele versterking fase-begrenzing | 3.0 |
| `CloudEMS Fase PID · Ki` | Integratieve versterking fase-begrenzing | 0.4 |
| `CloudEMS Fase PID · Kd` | Differentiële versterking fase-begrenzing | 0.8 |
| `CloudEMS EV PID · Kp` | Proportionele versterking EV-lader | 0.05 |
| `CloudEMS EV PID · Ki` | Integratieve versterking EV-lader | 0.008 |
| `CloudEMS EV PID · Kd` | Differentiële versterking EV-lader | 0.02 |
| `CloudEMS Prijs · Goedkoop drempel` | Prijs waaronder "goedkoop" geldt (EUR/kWh) | 0.10 |
| `CloudEMS NILM · Gevoeligheid (W)` | Minimale vermogenssprong voor detectie | 25W (adaptief) |

Wijzigingen worden **direct live toegepast** — geen HA-herstart nodig.

### 📊 Nieuwe sensoren

| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS System · PID Diagnostics` | Live PID-toestand: fout, integraal, output per regelaar |
| `CloudEMS NILM · Sensor Input` | Welke sensoren NILM gebruikt + adaptieve drempel |

---

---

## 🆕 Wat is er nieuw in v1.9.0?

### 🐛 Kritieke bugfixes

| Bug | Impact | Opgelost |
|-----|--------|----------|
| `db.classify(event)` kreeg een PowerEvent-object i.p.v. `(float, float)` | **NILM werkte volledig niet** — nul detecties | ✅ |
| `asyncio.ensure_future` zonder running loop | Kon crashen bij snelle updates | ✅ |
| `_enrich_price_info` zocht `s.get("hour")` in slots zonder `hour`-key | `prev_hour_price` altijd `None` | ✅ |
| Lege velden in configuratiescherm gaven validatiefout | Kon sensoren niet leegmaken | ✅ v1.6 |

### ✨ Nieuwe functies

- **NILM Diagnose-sensor** (`CloudEMS NILM · Diagnostics`) — zie precies wat NILM meet: welke vermogenssprongen gedetecteerd worden, waarom iets wel of niet geclassificeerd wordt, en wat de baseline per fase is
- **Morgen-prijzen** — `CloudEMS Energy · EPEX Today` bevat nu ook `tomorrow_prices` (beschikbaar na ~13:00 CET)
- **Volledige dag-grafiek** — `today_prices` bevat altijd alle 24 uren, ook de al verstreken uren

---

## ☕ Steun de ontwikkeling

CloudEMS is volledig gratis en open source. Toch kost het ontwikkelen, testen en onderhouden van deze integratie honderden uren per jaar. Serverkosten, ENTSO-E data, API-testen, documentatie schrijven — het loopt op.

**Als CloudEMS jou maandelijks geld bespaart op je energierekening, overweeg dan een kleine bijdrage.**
Elke koffie helpt om nieuwe functies te bouwen, bugs sneller te fixen en de integratie levend te houden voor de hele community.

| | |
|---|---|
| ☕ **Doneer via Buy Me a Coffee** | [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m) |
| ☕ **Alternatief donatie-kanaal** | [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems) |

> Op de roadmap staan: NILM-verbeteringen, EV-planning, voorspellende stuurlogica, Belgisch capaciteitstarief en meer. Jouw steun bepaalt hoe snel die functies er komen.

---

## 📋 Inhoudsopgave

- [Wat doet CloudEMS?](#wat-doet-cloudems)
- [Ondersteunde landen](#ondersteunde-landen)
- [Vereisten](#vereisten)
- [Installatie](#installatie)
- [Configuratiewizard](#configuratiewizard)
- [Sensoren & entiteiten](#sensoren--entiteiten)
- [EPEX-prijzen (gratis, geen sleutel nodig voor NL/DE/AT)](#epex-prijzen)
- [NILM — Apparaatdetectie](#nilm--apparaatdetectie)
- [Dynamisch EV laden](#dynamisch-ev-laden)
- [Piekafschaving](#piekafschaving)
- [Fase-balancering](#fase-balancering)
- [Multi-omvormer beheer](#multi-omvormer-beheer)
- [P1 / DSMR koppeling](#p1--dsmr-koppeling)
- [Lovelace-dashboard](#lovelace-dashboard)
- [Problemen oplossen](#problemen-oplossen)
- [Veelgestelde vragen](#veelgestelde-vragen)
- [Bijdragen](#bijdragen)
- [Licentie](#licentie)

---

## ✨ Wat doet CloudEMS?

| Functie | Beschrijving |
|---------|-------------|
| 🧠 **NILM-detectie** | Herkent automatisch welke apparaten aan zijn — wasmachine, CV-ketel, EV-lader — puur op basis van je stroommeter. Geen slimme stekkers nodig. |
| ⚡ **Fase-beveiliging** | Bewaakt het stroomverbruik per fase en voorkomt dat je groep eruit vliegt. |
| ☀️ **Zonnestroom sturen** | Begrenst je omvormer automatisch bij negatieve EPEX-prijzen zodat je niet betaalt om te leveren. |
| 💰 **EPEX-prijzen (gratis)** | Live uurprijzen voor 10 Europese landen. **NL, DE en AT werken volledig gratis zonder API-sleutel.** |
| 🔋 **Slim EV laden** | Past de laadstroom van je auto automatisch aan op basis van zonne-overschot en stroomprijs. |
| 📊 **Piekafschaving** | Houdt je maandpiek onder controle (relevant voor het Belgisch capaciteitstarief). |
| ⚖️ **Fase-balancering** | Herverdeelt verbruik over L1/L2/L3 om asymmetrische belasting te voorkomen. |
| 🌤️ **PV-voorspelling** | Statistisch + weermodel (Open-Meteo) per omvormer. |
| 🤖 **Lokale & cloud-AI** | NILM via ingebouwde patronen, Ollama (lokaal LLM) of CloudEMS cloud-API. |
| 📡 **P1/DSMR direct** | Optionele directe TCP-verbinding met HomeWizard P1 of DSMR-reader. |
| 🔆 **Multi-omvormer** | Tot 9 omvormers onafhankelijk beheren met zelflerend azimut/helling. |
| 💶 **Kostenregistratie** | Dagelijkse/maandelijkse energiekosten op basis van live EPEX-prijs. |

---

## 🌍 Ondersteunde landen

| Land | Code | Gratis, geen sleutel | Databron |
|------|------|---------------------|----------|
| 🇳🇱 Nederland | `NL` | ✅ Ja | EnergyZero API |
| 🇩🇪 Duitsland | `DE` | ✅ Ja | Awattar DE API |
| 🇦🇹 Oostenrijk | `AT` | ✅ Ja | Awattar AT API |
| 🇧🇪 België | `BE` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇫🇷 Frankrijk | `FR` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇨🇭 Zwitserland | `CH` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇩🇰 Denemarken | `DK` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇳🇴 Noorwegen | `NO` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇸🇪 Zweden | `SE` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |
| 🇫🇮 Finland | `FI` | 🔑 ENTSO-E sleutel | ENTSO-E Transparency |

> **ENTSO-E sleutel nodig?** Registreer gratis op [transparency.entsoe.eu](https://transparency.entsoe.eu) → Account aanmaken → API Security Token genereren. Vul dit in bij de CloudEMS-wizard onder "AI & NILM → API-sleutel".

---

## 📦 Vereisten

- **Home Assistant** 2024.1 of nieuwer
- **HACS** (aanbevolen) of handmatige installatie
- Minimaal één vermogenssensor (W of kW) van een slimme meter, P1-koppeling of stroommeter

**Optioneel maar aanbevolen:**
- Stroomsensoren per fase (A) — voor fase-beveiliging en -balancering
- Omvormersvermogenssensor — voor NILM en EV-zonneladen
- EV-lader `number`-entiteit — voor dynamische stroomsturing

---

## 🚀 Installatie

### Via HACS (aanbevolen)

1. Open **HACS** in Home Assistant
2. Ga naar **Integraties** → klik het ⋮-menu → **Aangepaste opslagplaatsen**
3. Voeg toe: `https://github.com/cloudemsNL/ha-cloudems` — Categorie: **Integratie**
4. Zoek **CloudEMS** en klik **Downloaden**
5. **Herstart Home Assistant**
6. Ga naar **Instellingen → Integraties → Integratie toevoegen** → zoek **CloudEMS**

### Handmatige installatie

```bash
wget https://github.com/cloudemsNL/ha-cloudems/releases/latest/download/ha-cloudems.zip
unzip ha-cloudems.zip
cp -r custom_components/cloudems /config/custom_components/
```

Herstart Home Assistant en voeg de integratie toe via **Instellingen → Integraties**.

---

## 🧙 Configuratiewizard

De CloudEMS-wizard begeleidt je stap voor stap. **Niet-relevante velden worden automatisch verborgen** — je ziet alleen wat voor jouw situatie geldt.

| Stap | Titel | Beschrijving |
|------|-------|-------------|
| 1 | 🌍 Land | Kies je EPEX-land voor stroomprijsdata |
| 2 | ⚡ Netaansluiting | Kies je zekeringgrootte (bijv. 3×25 A) of voer eigen limieten in |
| 3 | 🔌 Netsensoren | Netto-vermogenssensor of aparte import/export-sensoren |
| 4 | 🔌 Fase-sensoren | Optionele stroom-, spannings- en vermogenssensoren per fase |
| 5 | 🌞 Zonne & EV | Omvormer, batterij, EV-lader, zonnebegrenzing |
| 6 | ☀️ Omvormers | Configureer 0–9 omvormers met zelflerend azimut/helling |
| 7 | 🚀 Functies | Dynamisch laden, kostenregistratie, piekafschaving, fase-balancering |
| 7b | 📊 Piekafschaving | Piekdrempel en afschakelbare lasten *(alleen als piekafschaving aan)* |
| 8 | 🤖 AI & NILM | AI-provider, API-sleutel, betrouwbaarheidsdrempel |
| 8b | 🤖 Ollama | Ollama host/poort/model *(alleen als Ollama geselecteerd)* |
| 9 | 📡 P1-meter | Directe P1-verbinding inschakelen *(optioneel)* |
| 9b | 📡 P1-instellingen | P1-gateway IP/poort *(alleen als P1 aan)* |

> ℹ️ **Automatische detectie:** CloudEMS scant je bestaande sensoren en doet suggesties op basis van eenheden (W, A, V) en namen. Je kunt altijd handmatig een andere sensor kiezen.

### Instellingen later wijzigen

Ga naar **Instellingen → Integraties → CloudEMS → Configureren** en kies de sectie:

- 🔌 **Netsensoren** — sensoren, fasenaantal, zekeringsgrootte
- ⚡ **Fase-sensoren** — stroom/spanning/vermogen per fase
- ☀️ **Zonne & EV** — omvormer/batterij/EV-entiteiten
- 🚀 **Functies** — functies aan/uitzetten, drempelwaarden
- 🤖 **AI & NILM** — AI-backend wisselen
- 📡 **P1 & Geavanceerd** — P1-instellingen

> ✅ **Bug opgelost in v1.9.0:** Lege velden in het configuratiescherm worden nu correct geaccepteerd — net als in de wizard.

---

## 📊 Sensoren & entiteiten

### Netsensoren
| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS Grid · Net Power` | Huidig net-import/export vermogen (W) |
| `CloudEMS Grid · Phase L1/L2/L3 Current` | Stroom per fase (A) |
| `CloudEMS Grid · Phase L1/L2/L3 Voltage` | Spanning per fase (V) |
| `CloudEMS Grid · Phase L1/L2/L3 Power` | Vermogen per fase (W) |
| `CloudEMS Grid · Phase Imbalance` | Maximale onbalans tussen fasen (A) |
| `CloudEMS Grid · Peak Shaving` | Huidige maandpiek (W) |
| `CloudEMS Grid · P1 Net Power` | Vermogen via directe P1-verbinding (W) |

### Energiesensoren
| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS Energy · Price` | Huidige EPEX-prijs (EUR/kWh) |
| `CloudEMS Energy · Price Current Hour` | Uurprijs (+ is goedkoop/duur/negatief) |
| `CloudEMS Energy · Price Next Hour` | Volgende uurprijs |
| `CloudEMS Energy · Price Previous Hour` | Vorige uurprijs |
| `CloudEMS Energy · EPEX Today` | **Alle uurprijzen van vandaag** (voor grafiek in dashboard) |
| `CloudEMS Energy · Cost` | Huidig energiegebruik in EUR/uur |
| `CloudEMS Energy · Insights` | AI-tips en aanbevelingen in leesbare tekst |
| `CloudEMS Energy · Cheapest 1h/2h/3h` | Binaire sensor: ben je nu in het goedkoopste uur/2h/3h? |

### Zonne-sensoren
| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS Solar · PV Forecast Today` | Verwachte zonnestroom vandaag (kWh) |
| `CloudEMS Solar · [Omvormer naam]` | Per omvormer: vermogen, piek, clipping, benutting |

### NILM-sensoren
| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS AI · Status` | Welke AI-backend actief is en hoeveel apparaten herkend zijn |
| `CloudEMS NILM · Diagnostics` | Diagnose: events/minuut, classificatierate, baseline per fase, event-log |
| `CloudEMS Batterij · EPEX Schema` | Huidige batterij-actie + volledig dagschema op basis van EPEX |
| `CloudEMS Net · CO2 Intensiteit` | Gram CO2/kWh van het elektriciteitsnet (live of statisch) |
| `CloudEMS Energie · Kosten Verwachting` | Verwachte totale dagkosten + morgen-voorspelling (zelf-lerend) |
| `CloudEMS NILM · Devices` | Aantal herkende apparaten |
| `CloudEMS NILM · Running Devices` | Aantal apparaten dat nu aan staat |
| `CloudEMS NILM · Running Devices Power` | Totaal vermogen van lopende apparaten (W) |
| `CloudEMS NILM · [Apparaatnaam]` | Per apparaat: vermogen, energie, betrouwbaarheid |

### Systeemsensoren
| Sensor | Beschrijving |
|--------|-------------|
| `CloudEMS System · Decision Log` | Recente automatiseringsbeslissingen (diagnostisch) |
| `CloudEMS Boiler · Status` | Boilerstatus (aan/uit) |

---

## 💰 EPEX-prijzen

CloudEMS haalt automatisch de uurprijzen op — **volledig gratis voor Nederland, Duitsland en Oostenrijk**, zonder registratie of API-sleutel.

### Prijzen zien op je dashboard

De sensor `CloudEMS Energy · EPEX Today` bevat alle uurprijzen van vandaag in het attribuut `today_prices`. Gebruik dit met een ApexCharts card:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: EPEX prijzen vandaag
series:
  - entity: sensor.cloudems_energy_epex_today
    attribute: today_prices
    data_generator: |
      return entity.attributes.today_prices.map(h => [h.hour * 3600000, h.price]);
yaxis:
  - decimals: 4
    title: EUR/kWh
```

### Goedkoopste uren gebruiken in automatiseringen

```yaml
# Voorbeeld: vaatwasser starten in het goedkoopste 3-uurs venster
automation:
  alias: Vaatwasser bij goedkope stroom
  trigger:
    - platform: state
      entity_id: binary_sensor.cloudems_energy_cheapest_3h
      to: "on"
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.vaatwasser
```

### Voor andere landen (BE, FR, etc.)

Haal gratis een ENTSO-E API-sleutel op via [transparency.entsoe.eu](https://transparency.entsoe.eu). Vul deze in bij **CloudEMS → Configureren → AI & NILM → API-sleutel**.

---

## 🧠 NILM — Apparaatdetectie

**Non-Intrusive Load Monitoring** herkent welke apparaten aan zijn op basis van je totale stroomverbruik — zonder slimme stekkers.

CloudEMS ondersteunt drie AI-backends:

| Backend | Nauwkeurigheid | Privacy | Vereisten |
|---------|---------------|---------|-----------|
| **Ingebouwd** | Goed | ✅ 100% lokaal | Geen |
| **Ollama** | Beter | ✅ 100% lokaal | Ollama lokaal draaien |
| **Cloud API** | Beste | Data naar CloudEMS cloud | CloudEMS-abonnement |

**Herkende apparaattypen:** Wasmachine, droger, vaatwasser, oven, magnetron, waterkoker, tv, computer, warmtepomp, boiler, EV-lader, omvormer, verlichting.

> ℹ️ NILM heeft een inwerkperiode van enkele uren tot dagen. De sensor `CloudEMS AI · Status` toont de huidige leerstand.
>
> **Sensor-prioriteit:** NILM gebruikt bij voorkeur per-fase vermogenssensoren. Zonder fase-sensoren valt het terug op het totale netverbruik. Zie `CloudEMS NILM · Sensor Input` voor de actieve modus en aanbevelingen. De sensor `CloudEMS AI · Status` toont de huidige leerstand. Hoe meer schakelingen gemeten worden, hoe nauwkeuriger de detectie.

---

## 🔋 Dynamisch EV laden

CloudEMS past de laadstroom van je EV-lader automatisch aan op basis van:

- **Zonne-overschot** — laad sneller als je PV meer produceert dan je huis verbruikt
- **EPEX-prijs** — meer laden in de goedkoopste uren, minder bij dure stroom
- **Faselimieten** — nooit meer dan je zekeringsgroep toelaat

Vereisten: een EV-lader met een `number`-entiteit voor de laadstroominstelling (bijv. Easee, go-e, OCPP, Alfen Eve, Zaptec).

---

## 📊 Piekafschaving

Relevant voor het **Belgisch capaciteitstarief** en iedereen die zijn maandpiek wil beheersen.

CloudEMS bewaakt je maandpiek (kW) en schakelt automatisch afschakelbare lasten uit (bijv. boiler, wasmachine, EV-lader) als het netverbruik je ingestelde drempel overschrijdt.

Configureer welke entiteiten uitgeschakeld mogen worden via **Instellingen → CloudEMS → Configureren → Functies**.

---

## ⚖️ Fase-balancering

Voor driefase-aansluitingen bewaakt CloudEMS de stroom op elke fase en kan verbruik herverdelen om onbalans binnen de ingestelde drempel te houden. Dit voorkomt asymmetrische belasting en mogelijke groepuitval.

Vereist: stroomsensoren per fase (A).

---

## ☀️ Multi-omvormer beheer

Beheer tot 9 PV-omvormers onafhankelijk. CloudEMS leert automatisch:

- **Piekstroom (Wp)** — geschat op basis van productiehistorie
- **Azimut & helling** — geleerd uit dagelijkse productiecurves
- **Fasekoppeling** — automatisch gedetecteerd

Bij zonnebegrenzing worden omvormers in prioriteitsvolgorde (configureerbaar) begrensd.

---

## 📡 P1 / DSMR koppeling

De meeste gebruikers halen P1-data via de [DSMR-integratie](https://www.home-assistant.io/integrations/dsmr/) of [HomeWizard](https://www.home-assistant.io/integrations/homewizard/). CloudEMS gebruikt deze bestaande sensoren automatisch.

Voor een directe TCP-verbinding (bijv. HomeWizard P1-dongle): schakel de P1-optie in de wizard in.

---

## 🎨 Lovelace-dashboard

Een kant-en-klaar Lovelace-dashboard (`cloudems-dashboard.yaml`) is meegeleverd. Installeer de kaart (`cloudems-card.js`) als [custom card](https://www.home-assistant.io/lovelace/custom-cards/).

Het dashboard toont:
- Live stroomstromen (import/export/zon)
- EPEX-prijsgrafiek voor vandaag
- Fase-meters met benutting
- NILM-apparatenlijst
- PV-voorspelling
- Piek- en kostenoverzicht

---

## 🔧 Problemen oplossen

### Veelvoorkomende fouten

**Sensoren tonen `unavailable`**
→ Controleer of de geconfigureerde entiteiten nog bestaan. Ga naar **Instellingen → CloudEMS → Configureren → Netsensoren**.

**Geen EPEX-prijzen (NL/DE/AT)**
→ Controleer je internetverbinding. NL gebruikt de gratis EnergyZero API, DE/AT de gratis Awattar API. Controleer de attribuut `data_source` van de prijssensor.

**Geen EPEX-prijzen (andere landen)**
→ Je hebt een gratis ENTSO-E sleutel nodig. Registreer op [transparency.entsoe.eu](https://transparency.entsoe.eu) en voer de sleutel in onder **AI & NILM → API-sleutel**.

**Automatische detectie kiest verkeerde sensor**
→ De wizard suggereert sensoren op basis van eenheden en namen. Je kunt altijd handmatig een andere sensor selecteren.

**Lege waarden niet geaccepteerd in configuratiescherm**
→ Opgelost in v1.9.0. Zorg dat je de nieuwste versie gebruikt.

### Debug-logging inschakelen

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.cloudems: debug
```

### Diagnostiek

CloudEMS ondersteunt de ingebouwde HA-diagnostiek. Ga naar **Instellingen → Integraties → CloudEMS → ⋮ → Diagnostiek downloaden**.

---

## ❓ Veelgestelde vragen

**Heeft CloudEMS internet nodig?**
Alleen voor EPEX-prijzen (gratis, geen login nodig voor NL/DE/AT) en optionele Cloud AI NILM. Al het energiebeheer draait lokaal.

**Werkt het met een eenfasige aansluiting?**
Ja. Kies `1×16A`, `1×25A` etc. in de wizard. Fase-specifieke functies worden automatisch verborgen.

**Kan ik het gebruiken zonder slimme meter?**
Ja, als je een vermogenssensor hebt (bijv. van een klemstroomtransformator, SolarEdge, Fronius, Huawei, Solis, etc.) kun je CloudEMS gebruiken. P1/DSMR is optioneel.

**Welke EV-laders worden ondersteund?**
Elke lader met een `number`-entiteit voor de laadstroom. Getest met: Easee, go-e, OCPP (generiek), Alfen Eve, Zaptec.

**Worden mijn gegevens naar de cloud gestuurd?**
Nee, standaard niet. EPEX-prijzen ophalen is de enige uitgaande verbinding. Cloud AI NILM is optioneel en vereist een abonnement.

---


## 🎛️ PID-regelaars afstellen

CloudEMS gebruikt drie PID-regelaars:

**1. Fase-begrenzer (multi-omvormer dimming)**
Past de omvormeruitgang aan om de fasestroom onder het ingestelde maximum te houden. Pas **Kp** aan voor snelheid, **Ki** voor het wegwerken van blijvende afwijking, **Kd** voor dempening bij plotselinge schakelingen.

**2. EV-laadstroom PID**
Regelt de laadstroom zodat het netto netverbruik op ±0W blijft (optimaal solar-overschot benutten). Hogere **Kp** = snellere reactie op bewolking, maar risico op oscillatie.

**3. Auto-tuner**
Wil je de parameters automatisch bepalen? Roep de HA-service `cloudems.start_pid_autotune` aan. CloudEMS voert een relay-experiment uit en berekent de ideale Kp/Ki/Kd via de Ziegler-Nichols methode. Resultaten zijn zichtbaar in `CloudEMS System · PID Diagnostics`.

> **Tip:** Begin met de standaardwaarden. Pas pas aan als je oscillatie ziet (te hoge Kp) of trage reactie (te lage Kp/Ki).

---
## 🤝 Bijdragen

Bijdragen zijn van harte welkom!

1. Fork de repository
2. Maak een feature branch: `git checkout -b feature/mijn-functie`
3. Commit je wijzigingen: `git commit -m 'Voeg mijn functie toe'`
4. Push en open een Pull Request

Open eerst een [issue](https://github.com/cloudemsNL/ha-cloudems/issues) voor grote wijzigingen.

---

## 💖 Doneer

CloudEMS is en blijft gratis. Als de integratie jou helpt energie te besparen, overweeg dan een kleine bijdrage. Dit helpt de ontwikkeling actief te houden en nieuwe functies sneller te bouwen.

→ ☕ [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m)
→ ☕ [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems)

---

## 📄 Licentie

MIT © 2025 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

*Trefwoorden: Home Assistant energiebeheer, NILM apparaatdetectie, EPEX dag-vooruit prijzen, dynamisch EV laden, piekafschaving, fase-balancering, zonnebegrenzing, slimme woning energie, HA custom integratie, HACS*
