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

## 🆕 Wat is er nieuw in v1.15.4?

### 🐛 Bugfixes

| # | Probleem | Oplossing |
|---|----------|-----------| 
| 1 | **Nieuwe v1.15 sensoren toonden `unavailable`** — EMA-diagnostics, sanity guard, occupancy, climate preheat en PV-nauwkeurigheid werden door de coordinator berekend maar misten HA-sensor entiteiten | 5 nieuwe sensorklassen aangemaakt in `sensor.py`, alle 5 geregistreerd in `async_setup_entry()` |
| 2 | **NaN-waarden in grafieken** — `_val()` in de kaart herkende de letterlijke string `"NaN"` niet als ongeldige waarde, waardoor grafieken broken values toonden | `_val()` en `_fmt()` uitgebreid met string-NaN en `isFinite()`-check |
| 3 | **HTML-entity bug in dashboard** — `Ori&euml;ntatie` werd letterlijk getoond i.p.v. `Oriëntatie` | Gecorrigeerd in `cloudems-dashboard.yaml` |
| 4 | **DSMR5 export-sensoren ontbraken in wizard** — de initiële installatie-wizard had geen velden voor per-fase teruglevering, alleen de opties-flow had dit | DSMR5 L1/L2/L3 export-velden toegevoegd aan de `phase_sensors` stap van de wizard |
| 5 | **PV-sensor ontbrak in opties** — na installatie was er geen veld om de PV/omvormer-sensor aan te passen in de `☀️ PV & EV`-sectie | `CONF_SOLAR_SENSOR` toegevoegd aan `solar_ev_opts` |
| 6 | **`Oriëntatie` entity slug** — niet-ASCII `ë` genereerde `cloudems_apparaat_effici_ntiedrift` i.p.v. de verwachte slug | Naam aangepast naar ASCII `Efficientiedrift` |

> ⚠️ **Na installatie van v1.15.4:** herstart Home Assistant volledig. De entity registry maakt de nieuwe sensor-entiteiten aan (`sensor.cloudems_occupancy`, `sensor.cloudems_climate_preheat`, etc.). Dashboard-tabs die "Configuratiefout" toonden zullen daarna correct werken.

---

## 🆕 Wat is er nieuw in v1.13.0?

### 🐛 Bugfixes & verbeteringen

| # | Probleem | Oplossing |
|---|----------|-----------| 
| 1 | **Binary sensors verkeerd domein** — `binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom`, `binary_sensor.cloudems_verbruik_anomalie` en `binary_sensor.cloudems_energy_cheapest_1h/2h/3h` werden via het sensor-platform geregistreerd waardoor ze `sensor.*` entity_ids kregen en dashboard-kaarten "Entiteit niet gevonden" toonden | Verplaatst naar `binary_sensor.py` — entity_ids kloppen nu |
| 2 | **Sensor namen genereerden verkeerde entity_ids** — o.a. `sensor.cloudems_micro_mobiliteit_e_bike_scooter`, `sensor.cloudems_verbruik_categorieen`, `sensor.cloudems_gasstand_m3` kwamen niet overeen met het dashboard | Namen aangepast zodat de slugs exact overeenkomen |
| 3 | **Dubbele `CloudEMS Grid · Net Power` sensor** — `CloudEMSGridNetPowerSensor` conflicteerde met `CloudEMSPowerSensor` waardoor één de suffix `_2` kreeg | Dubbele verwijderd |
| 4 | **Unknown i.p.v. 0W bij geen import/export** — import- en exportvermogenssensoren toonden `unknown` wanneer er geen stroom liep | `available = True` override toegevoegd |
| 5 | **"Totaal (W)" klopte niet** — toonde NILM-geschatte som in plaats van gemeten afname | Vervangen door `sensor.cloudems_grid_import_power` |
| 6 | **Top 5 toonde #1/#2/... i.p.v. apparaatnamen** — `secondary_info: attribute` werkt niet in recente HA-versies | Vervangen door Jinja2 markdown-tabel |
| 7 | **Leervoortgang kaart toonde geen attribuutwaarden** | Omgezet naar `type: attribute` rijen |

> ⚠️ **Na installatie:** herstart Home Assistant volledig zodat de entity registry de nieuwe `binary_sensor.*` entity_ids aanmaakt.

---

## 🆕 Wat is er nieuw in v1.9.0?

### 🌿 CO2-intensiteit net (altijd actief, geen configuratie nodig)

CloudEMS toont nu de CO2-intensiteit van het elektriciteitsnet in gCO2eq/kWh.

| Bronnen | Beschikbaarheid |
|---------|----------------|
| Electricity Maps API | Gratis, geen sleutel |
| CO2 Signal API | Gratis token vereist |
| EEA 2023 statisch gemiddelde | Altijd, offline |

Gebruik het om automaties te maken als: *"Laad de EV alleen wanneer het net groen is (<200g)"*.

### 🔌 P1 direct naar NILM — hoogste kwaliteit invoer

Wanneer je een P1-lezer hebt geconfigureerd (SLIMMELEZER, HomeWizard, USB), worden de per-fase vermogens uit het DSMR-telegram nu **direct naar de NILM-detector gestuurd** — zonder vertraging via HA-sensoren.

**Prioriteitsvolgorde NILM-invoer:**

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

### 📊 Energiekosten-voorspelling (zelf-lerend)

De sensor **`CloudEMS Energie · Kosten Verwachting`** voorspelt wat je vandaag en morgen kwijt bent aan stroom.

- **Zelf-lerend**: leert jouw verbruikspatroon per uur
- **Morgen-preview**: als EPEX-prijzen voor morgen bekend zijn (na ~13:00)
- **ApexCharts-klaar**: `hourly_patterns` attribuut geeft verbruikscurve per uur

### 🧠 Zelf-lerende verbeteringen

**Adaptieve NILM-drempel** — leert automatisch hoe "rustig" of "lawaaierig" jouw netsignaal is en past de drempel aan.

**EV laden via PID-regelaar** — gladde laadstroomregeling die automatisch meegaat met wisselende zonproductie en bewolking.

**PID Auto-Tuner (Relay Feedback)** — start via `cloudems.start_pid_autotune`. Bepaalt de ideale Kp/Ki/Kd voor jouw installatie.

### 🎛️ Instelbare PID-parameters

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

---

## ☕ Steun de ontwikkeling

CloudEMS is volledig gratis en open source. Toch kost het ontwikkelen, testen en onderhouden van deze integratie honderden uren per jaar.

**Als CloudEMS jou maandelijks geld bespaart op je energierekening, overweeg dan een kleine bijdrage.**

| | |
|---|---|
| ☕ **Doneer via Buy Me a Coffee** | [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m) |
| ☕ **Alternatief donatie-kanaal** | [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems) |

---

## 📋 Inhoudsopgave

- [Wat doet CloudEMS?](#wat-doet-cloudems)
- [Ondersteunde landen](#ondersteunde-landen)
- [Vereisten](#vereisten)
- [Installatie](#installatie)
- [Configuratiewizard](#configuratiewizard)
- [Sensoren & entiteiten](#sensoren--entiteiten)
- [EPEX-prijzen](#epex-prijzen)
- [NILM — Apparaatdetectie](#nilm--apparaatdetectie)
- [Dynamisch EV laden](#dynamisch-ev-laden)
- [Piekafschaving](#piekafschaving)
- [Fase-balancering](#fase-balancering)
- [Multi-omvormer beheer](#multi-omvormer-beheer)
- [P1 / DSMR koppeling](#p1--dsmr-koppeling)
- [DSMR5 bidirectionele meter](#dsmr5-bidirectionele-meter)
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
| 🏠 **Aanwezigheidsdetectie** | Herkent automatisch home/away/sleeping/vacation op basis van verbruikspatronen. |
| 🌡️ **Verwarmingsadvies** | Slim pre-heat en reduceer-advies op basis van prijzen en thermisch model. |
| 🛡️ **Sensor-bewaking** | EMA smoothing voor trage cloud-sensoren, sanity checks, kW/W verwarring detectie. |

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
| 4 | ⚡ Fase-sensoren | Optionele stroom-, spannings- en vermogenssensoren per fase + DSMR5 export |
| 5 | 🌞 Zonne & EV | Omvormer, batterij, EV-lader, zonnebegrenzing |
| 6 | ☀️ Omvormers | Configureer 0–9 omvormers met zelflerend azimut/helling |
| 7 | 🚀 Functies | Dynamisch laden, kostenregistratie, piekafschaving, fase-balancering |
| 7b | 📊 Piekafschaving | Piekdrempel en afschakelbare lasten *(alleen als piekafschaving aan)* |
| 8 | 💶 Prijzen | BTW, energiebelasting, contracttype, leveranciersmarge |
| 9 | 🤖 AI & NILM | AI-provider, API-sleutel, betrouwbaarheidsdrempel |
| 9b | 🤖 Ollama | Ollama host/poort/model *(alleen als Ollama geselecteerd)* |
| 10 | 📡 P1-meter | Directe P1-verbinding inschakelen *(optioneel, Advanced mode)* |

> ℹ️ **Automatische detectie:** CloudEMS scant je bestaande sensoren en doet suggesties op basis van eenheden (W, A, V) en namen. Je kunt altijd handmatig een andere sensor kiezen.

### Instellingen later wijzigen

Ga naar **Instellingen → Integraties → CloudEMS → Configureren** en kies de sectie:

| Sectie | Inhoud |
|--------|--------|
| 🔌 Grid Sensors | Netsensor, fasenaantal, zekeringsgrootte |
| ⚡ Fase-sensoren | Stroom/spanning/vermogen per fase + DSMR5 teruglevering |
| ☀️ PV & EV Laden | PV sensor, batterij, laadpaal, zonnebegrenzing |
| 🔥 Gas & Warmte | Gasmeter, gasprijs, boiler, warmtepomp |
| 🔆 PV Omvormers | Meerdere omvormers configureren/bijwerken |
| 🔋 Batterijen | Meerdere batterijen beheren |
| 💶 Prijzen | Contracttype (dynamisch/vast), BTW, belasting |
| 🚀 Features | Piekafschaving, balancering, congestie |
| 🤖 AI & NILM | Provider, Ollama host, betrouwbaarheidsdrempel |
| 📡 P1 & Advanced | P1 TCP, extra opties |

---

## 📊 Sensoren & entiteiten

### Netsensoren
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_grid_net_power` | Huidig net-import/export vermogen (W) |
| `sensor.cloudems_grid_import_power` | Afname van het net (W) |
| `sensor.cloudems_grid_export_power` | Teruglevering aan het net (W) |
| `sensor.cloudems_phase_l1_current` | Stroom L1 (A) |
| `sensor.cloudems_phase_imbalance` | Maximale onbalans tussen fasen (A) |
| `sensor.cloudems_grid_peak_shaving` | Huidige maandpiek (W) |
| `sensor.cloudems_grid_congestion_utilisation` | Netbenutting (%) |

### Energiesensoren
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_energy_price_current_hour` | Huidige EPEX-prijs (EUR/kWh) |
| `sensor.cloudems_energy_epex_today` | Alle uurprijzen vandaag + morgen (voor grafiek) |
| `sensor.cloudems_energy_cost` | Huidig energiegebruik in EUR/uur |
| `sensor.cloudems_net_co2_intensiteit` | CO₂-intensiteit net (gCO₂eq/kWh) |
| `binary_sensor.cloudems_energy_cheapest_1h` | Ben je nu in het goedkoopste uur? |
| `binary_sensor.cloudems_energy_cheapest_3h` | Ben je nu in de goedkoopste 3 uur? |

### Intelligentie-sensoren (nieuw in v1.15)
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_occupancy` | Aanwezigheid: home / away / sleeping / vacation |
| `sensor.cloudems_climate_preheat` | Verwarmingsadvies: pre_heat / reduce / normal |
| `sensor.cloudems_pv_forecast_accuracy` | PV prognose MAPE 14 dagen (%) |
| `sensor.cloudems_ema_diagnostics` | Geblokkeerde sensor-spikes + trage sensoren |
| `sensor.cloudems_sensor_sanity` | Actieve sensorconfiguratieproblemen |

### Zonne-sensoren
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_solar_pv_forecast_today` | Verwachte zonnestroom vandaag (kWh) |
| `sensor.cloudems_solar_[omvormer]` | Per omvormer: vermogen, piek, clipping, benutting |

### NILM-sensoren
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_nilm_running_devices` | Nu herkende actieve apparaten |
| `sensor.cloudems_nilm_running_devices_power` | Totaal vermogen lopende apparaten (W) |
| `sensor.cloudems_nilm_diagnostics` | Events/min, classificatierate, baseline per fase |
| `sensor.cloudems_ai_status` | Welke AI-backend actief is |

### Systeemsensoren
| Sensor | Beschrijving |
|--------|-------------|
| `sensor.cloudems_battery_epex_schema` | Batterij actie + volledig dagschema |
| `sensor.cloudems_system_decision_log` | Recente automatiseringsbeslissingen |
| `sensor.cloudems_energie_kosten_verwachting` | Verwachte dagkosten + morgen-voorspelling |

---

## 💰 EPEX-prijzen

CloudEMS haalt automatisch de uurprijzen op — **volledig gratis voor Nederland, Duitsland en Oostenrijk**, zonder registratie of API-sleutel.

### Prijzen zien op je dashboard

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

---

## 🧠 NILM — Apparaatdetectie

**Non-Intrusive Load Monitoring** herkent welke apparaten aan zijn op basis van je totale stroomverbruik — zonder slimme stekkers.

| Backend | Nauwkeurigheid | Privacy | Vereisten |
|---------|---------------|---------|-----------| 
| **Ingebouwd** | Goed | ✅ 100% lokaal | Geen |
| **Ollama** | Beter | ✅ 100% lokaal | Ollama lokaal draaien |
| **Cloud API** | Beste | Data naar CloudEMS cloud | CloudEMS-abonnement |

**Herkende apparaattypen:** Wasmachine, droger, vaatwasser, oven, magnetron, waterkoker, tv, computer, warmtepomp, boiler, EV-lader, omvormer, verlichting.

> ℹ️ NILM heeft een inwerkperiode van enkele uren tot dagen. De sensor `sensor.cloudems_ai_status` toont de huidige leerstand.

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

Configureer welke entiteiten uitgeschakeld mogen worden via **Instellingen → CloudEMS → Configureren → Features**.

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

Voor een directe TCP-verbinding (bijv. HomeWizard P1-dongle): schakel de P1-optie in via **Advanced mode → P1 & Geavanceerd**.

---

## ⚡ DSMR5 bidirectionele meter

Als je slimme meter per fase afzonderlijk import en export meet (DSMR5), kun je de teruglevering-sensoren configureren onder **⚡ Fase-sensoren** — zowel in de installatie-wizard als in de opties.

```
DSMR5 Teruglevering L1 → sensor.slimmemeter_power_l1_export
DSMR5 Teruglevering L2 → sensor.slimmemeter_power_l2_export
DSMR5 Teruglevering L3 → sensor.slimmemeter_power_l3_export
```

CloudEMS berekent dan netto fase-vermogen als: `import_W − export_W`

---

## 🎨 Lovelace-dashboard

Een kant-en-klaar Lovelace-dashboard (`cloudems-dashboard.yaml`) is meegeleverd. Importeer via **Instellingen → Dashboards → ⋮ → RAW configuratie bewerken**.

Het dashboard bevat 10 tabbladen: Overzicht · Kringen · Prijzen · Huis · Mobiliteit · Gebouw · Sturing · Meldingen · Diagnose · Inzichten

Vereist: `apexcharts-card` en `mushroom-cards` via HACS.

---

## 🎛️ PID-regelaars afstellen

CloudEMS gebruikt drie PID-regelaars:

**1. Fase-begrenzer** — past de omvormeruitgang aan om de fasestroom onder het maximum te houden.

**2. EV-laadstroom PID** — regelt de laadstroom zodat het netto netverbruik op ±0W blijft.

**3. Auto-tuner** — roep de HA-service `cloudems.start_pid_autotune` aan. CloudEMS voert een relay-experiment uit en berekent de ideale Kp/Ki/Kd via de Ziegler-Nichols methode.

> **Tip:** Begin met de standaardwaarden. Pas pas aan als je oscillatie ziet (te hoge Kp) of trage reactie (te lage Kp/Ki).

---

## 🔧 Problemen oplossen

**Sensoren tonen `unavailable`**
→ Controleer of de geconfigureerde entiteiten nog bestaan. Ga naar **Instellingen → CloudEMS → Configureren → Grid Sensors**.

**Geen EPEX-prijzen (NL/DE/AT)**
→ Controleer je internetverbinding. Controleer de attribuut `data_source` van de prijssensor.

**Geen EPEX-prijzen (andere landen)**
→ Je hebt een gratis ENTSO-E sleutel nodig. Registreer op [transparency.entsoe.eu](https://transparency.entsoe.eu) en voer de sleutel in onder **AI & NILM → API-sleutel**.

**Dashboard toont "Configuratiefout"**
→ Herstart Home Assistant volledig na een update. Nieuwe sensor-entiteiten worden pas aangemaakt na een volledige herstart.

### Debug-logging inschakelen

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.cloudems: debug
```

### Diagnostiek

Ga naar **Instellingen → Integraties → CloudEMS → ⋮ → Diagnostiek downloaden**.

---

## ❓ Veelgestelde vragen

**Heeft CloudEMS internet nodig?**
Alleen voor EPEX-prijzen (gratis, geen login nodig voor NL/DE/AT) en optionele Cloud AI NILM. Al het energiebeheer draait lokaal.

**Werkt het met een eenfasige aansluiting?**
Ja. Kies `1×16A`, `1×25A` etc. in de wizard. Fase-specifieke functies worden automatisch verborgen.

**Kan ik het gebruiken zonder slimme meter?**
Ja, als je een vermogenssensor hebt (bijv. van een klemstroomtransformator, SolarEdge, Fronius, Huawei, Solis, etc.).

**Welke EV-laders worden ondersteund?**
Elke lader met een `number`-entiteit voor de laadstroom. Getest met: Easee, go-e, OCPP (generiek), Alfen Eve, Zaptec.

**Worden mijn gegevens naar de cloud gestuurd?**
Nee, standaard niet. EPEX-prijzen ophalen is de enige uitgaande verbinding. Cloud AI NILM is optioneel en vereist een abonnement.

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

CloudEMS is en blijft gratis. Als de integratie jou helpt energie te besparen, overweeg dan een kleine bijdrage.

→ ☕ [buymeacoffee.com/smarthost9m](https://buymeacoffee.com/smarthost9m)
→ ☕ [buymeacoffee.com/cloudems](https://buymeacoffee.com/cloudems)

---

## 📄 Licentie

MIT © 2025 CloudEMS · [cloudems.eu](https://cloudems.eu)

---

*Trefwoorden: Home Assistant energiebeheer, NILM apparaatdetectie, EPEX dag-vooruit prijzen, dynamisch EV laden, piekafschaving, fase-balancering, zonnebegrenzing, slimme woning energie, HA custom integratie, HACS*
