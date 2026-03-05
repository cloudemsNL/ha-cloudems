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

## 🆕 Wat is er nieuw in v1.21.0?

### 🧠 CPU-adaptieve NILM-motor (NilmCpuGuard + NilmEnhancer)

CloudEMS bewaakt nu actief de CPU-belasting van de HA-host en schaalt de NILM-detectie automatisch terug als het systeem druk is. Zo draait NILM altijd zo goed als je hardware toelaat — zonder dat HA traag wordt.

| CPU-modus | Actief bij | Wat er draait |
|-----------|-----------|---------------|
| **FULL** | < 60% CPU | Scipy events + Seq2Point ONNX + Clustering + Bayesiaans + FSM + Kalman |
| **NORMAL** | 60–75% | Kalman + Bayesiaans + FSM + bewijs-accumulatie |
| **LITE** | 75–88% | Alleen Kalman + Bayesiaanse priors |
| **MINIMAL** | 88–95% | Alleen Kalman-basislijn |
| **PAUSE** | > 95% | Geen berekeningen, toestand behouden |

De sensor `sensor.cloudems_nilm_diagnostics` toont in welke modus de motor draait en hoeveel procent van de tijd elke modus actief was.

### 🤖 Seq2Point ONNX-modellen (ingebouwd)

CloudEMS v1.21.0 bevat voor het eerst **meegeleverde ONNX-modellen** voor 15 apparaattypes. Dit zijn compacte 2-laags neurale netwerken (MLP) die een venster van 599 stroopsamples omzetten naar een vermogensschatting per apparaat.

**Ingebouwde modellen:**
`wasmachine · droger · vaatwasser · warmtepomp · EV-lader · koelkast · magnetron · waterkoker · boiler · cv-boiler · oven · elektrische verwarming · computer · tv · verlichting`

Modellen worden geladen vanuit `nilm_models/` in de integratiemap. In `CpuMode.FULL` worden ze automatisch gebruikt als extra classificatielaag. Geen installatie, geen download, geen API-sleutel nodig.

### 🔍 Verbeterde NILM — minder vals-positieven

| Verbetering | Beschrijving |
|------------|-------------|
| **Minimum on_events: 2 → 3** | Apparaat moet 3× gezien zijn voor het zichtbaar wordt |
| **Pending-filter** | Onbevestigde detecties worden verborgen tot ze bewezen zijn (≥ 0.92 confidence) of door de gebruiker bevestigd |
| **Standaard drempel: 0.65 → 0.80** | Hogere standaard in de wizard = direct minder rommel |
| **best_conf na Ollama** | Bugfix: confidence werd niet herberekend na Ollama-classificatie, waardoor Cloud AI onnodig werd aangeroepen |

---

## 🆕 Wat is er nieuw in v1.20.0?

### 🏠 Virtuele stroommeter per kamer

CloudEMS groepeert NILM-apparaten en smart plugs automatisch per ruimte en berekent het realtime verbruik per kamer.

**Automatische kamertoewijzing (prioriteitsvolgorde):**
1. HA Area Registry — entiteit al toegewezen aan ruimte in HA
2. Keyword matching — entity_id/naam bevat "keuken", "slaapkamer", etc.
3. Apparaattype-heuristiek — koelkast → keuken, tv → woonkamer
4. Handmatige override via service `cloudems.assign_device_to_room`
5. Fallback: "Overig"

Sensor-output per kamer: huidig verbruik (W), apparaatlijst, kWh vandaag/maand, percentage van totaal.

### ⏰ Goedkope Uren Schakelaar Planner

Schakelt switches automatisch **aan** tijdens het goedkoopste N-uursblok van de dag. Alleen aanzetten, nooit uitzetten — veilig voor apparaten die niet mogen worden onderbroken.

**Configureerbaar per schakelaar:**
- Welke switch/input_boolean
- Goedkoopste 1, 2, 3 of 4 uur
- Vroegste en laatste starttijd (bijv. niet vóór 6:00, niet na 22:00)
- Actieve weekdagen

**Voorbeeld:** *"Zet mijn wasmachine aan zodra de goedkoopste 3 uur beginnen — ik heb hem al gevuld en klaargezet."*

### 🏷️ NILM-apparaatbeheer verbeterd

- `cloudems.rename_nilm_device` — hernoem een apparaat zonder detectiedata te verliezen
- `cloudems.hide_nilm_device` — verberg uit het dashboard zonder te verwijderen
- `cloudems.assign_device_to_room` — koppel aan een kamer
- `cloudems.decline_nilm_device` — weiger een detectie (nooit meer tonen)
- Alleen bevestigde apparaten worden doorgegeven aan de virtuele stroommeter

---

## 🆕 Wat is er nieuw in v1.18.0 – v1.18.1?

### 💾 Leerdata-backup (crash-veilig)

CloudEMS schrijft nu een **tweede kopie** van alle geleerde data naar `/config/cloudems_backup/`. Dit staat buiten de HA Store — bij een harde crash of Store-corruptie valt CloudEMS automatisch terug op de backup, zodat maanden aan geleerde oriëntatie, thermisch model, PV-profiel en fase-data niet verloren gaan.

### ⚡ Stroomuitval-detectie

CloudEMS detecteert automatisch wanneer de stroom uitvalt: als PV-opbrengst én netspanning allebei 0 zijn overdag (3 opeenvolgende meetpunten). Een notificatie wordt verzonden via het HA-meldingssysteem.

### 🚗 EV Zonnepiek-planning

De EV-lader wordt nu gestart op het verwachte PV-piekuur van de volgende dag, zelfs als er 's ochtends nog weinig zon is. CloudEMS plant op basis van de geleerde productiecurve per omvormer.

### 🔋 Slijtage-bewust laden

De batterij-scheduler houdt nu rekening met de **State of Health (SoH)** van de batterij. Bij een verouderde batterij (SoH < 90%) worden laadcycli geoptimaliseerd om verdere slijtage te beperken. SoH wordt geschat op basis van kalendertijd + gecumuleerde laadcycli per chemie (LFP / NMC / LTO).

### 📋 Dagelijks leerrapport

Elke dag om 20:00 genereert CloudEMS een intern leerrapport dat samenvat hoeveel elke zelflerende module heeft bijgeleerd (PV-profiel, thermisch model, verbruikspatronen). Zichtbaar in `sensor.cloudems_system_decision_log`.

---

## 🆕 Wat is er nieuw in v1.17.0?

### 🔗 HybridNILM — Smart plug integratie

CloudEMS ontdekt automatisch **slimme stekkers** (Shelly, Tasmota, ESPHome) in je HA-installatie en gebruikt ze als **anker-apparaten** voor NILM:

- Smart plugs krijgen **100% confidence** — hun verbruik is exact bekend
- Hun vermogen wordt **afgetrokken van het restsignaal** waardoor NILM andere apparaten schoner herkent
- Geen configuratie nodig — auto-discovery via eenheden en entiteitnamen

### 🌡️ Contextuele priors (Bayesiaans)

NILM-classificatie houdt nu rekening met de omgeving:

| Context | Effect |
|---------|--------|
| Temperatuur | Warmtepomp meer kans bij kou (< 5°C), airco meer kans bij warmte (> 25°C) |
| Tijdstip | Magnetron hogere kans tijdens lunchuur en avondeten |
| Seizoen | Verwarming hogere kans in winter, koeling in zomer |
| Vermogen | Penalty als event te klein is voor het apparaattype |

### 📐 DSMR5 fase-correlatie voor stopcontacten

Smart plugs krijgen automatisch een fase toegewezen door het vermogensverloop te correleren met DSMR5 per-fase snapshots:
- Bevestigd na 3 opeenvolgende matches (configureerbaar)
- Hervalidatie elke 24 uur (voor verplaatste stekkers)
- Relatieve fout ≤ 35% voor een geldige match

### 🔄 Duplicate penalty

Als een apparaattype al bevestigd is op een bepaalde fase, krijgt een tweede detectie van hetzelfde type op dezelfde fase een **penalty** — dit voorkomt dat CloudEMS twee wasmachines "ziet" in een huishouden met één.

---

## 🆕 Wat is er nieuw in v1.16.0?

### 🔋 Batterij edge-filter

NILM negeert vermogensevents die worden veroorzaakt door de batterij. Als een event een ratio van 0.6–1.4× het huidige batterijvermogen heeft, wordt het niet geclassificeerd. Dit voorkomt tientallen vals-positieven per dag bij systemen met een thuisbatterij.

### ☀️ Structurele schaduwdetector

CloudEMS vergelijkt per uur de werkelijke PV-opbrengst met de verwachte opbrengst en detecteert structurele schaduw op je panelen:

- **Oost-obstakel**: schaduw vroeg in de ochtend (07–10u)
- **West-obstakel**: schaduw laat in de middag (15–18u)
- **Middag-obstakel**: schaduw rondom zonnemiddag (11–14u) — vermoedelijk schoorsteen of vervuiling

Output: beschaduwde uren per omvormer, ernst, geschat dagelijks kWh-verlies, mensleesbaar advies.

### 🔮 Clipping-voorspelling voor morgen

Naast realtime clipping-detectie berekent CloudEMS nu ook de **verwachte clipping voor morgen** op basis van de weersvoorspelling en het geleerde PV-profiel. Zichtbaar als attribuut op de omvormer-sensor.

### 🤖 Ollama health-check

De Ollama-backend (lokale LLM voor NILM) wordt nu elke 60 seconden gecontroleerd. Als Ollama niet bereikbaar is, schakelt CloudEMS automatisch terug naar patroonherkenning zonder foutmeldingen te spammen. Status zichtbaar via `sensor.cloudems_ai_status`.

---


---

## 📜 Oudere versies

### 🔖 v1.15.4 — Bugfixes & intelligentie-sensoren


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

### 🔖 v1.13.0 — Binary sensors & entity correcties


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

### 🔖 v1.9.0 — CO2, P1 direct, batterij EPEX, kosten-voorspelling


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
- [Kamerverbruik](#kamerverbruik--virtuele-stroommeter)
- [Goedkope uren planner](#goedkope-uren-planner)
- [Schaduwdetectie](#schaduwdetectie)
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
| 🧠 **Seq2Point ONNX** | 15 ingebouwde neurale netwerk-modellen voor apparaatdetectie — geen download nodig. |
| 🏠 **Kamerverbruik** | Automatische verbruiksmeting per kamer op basis van NILM + smart plugs + HA areas. |
| ⏰ **Goedkope uren planner** | Schakelt apparaten automatisch aan tijdens het goedkoopste N-uursblok van de dag. |
| ☀️ **Schaduwdetectie** | Detecteert structurele schaduw op PV-panelen per uur met richtingsadvies. |
| ⚡ **Stroomuitval-detectie** | Meldt automatisch een stroomuitval via HA-notificaties. |
| 💾 **Leerdata-backup** | Crash-veilige tweede kopie van alle geleerde data naast de HA Store. |
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

**Smart plug versterking (v1.17):** CloudEMS ontdekt automatisch slimme stekkers en gebruikt ze als anker. Hun exacte vermogen wordt afgetrokken zodat NILM de rest schoner herkent. Geen configuratie nodig.

**ONNX modellen (v1.21):** 15 ingebouwde Seq2Point-modellen verbeteren de detectie in `CpuMode.FULL` met een extra neurale netwerk-laag. De modellen staan in `nilm_models/` en worden automatisch geladen.

**Minder vals-positieven:** apparaten verschijnen pas na 3 bevestigde detecties met ≥ 80% betrouwbaarheid. Onbevestigde detecties worden intern bijgehouden maar verborgen tot ze bewezen zijn.

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

## 🏠 Kamerverbruik — Virtuele stroommeter

CloudEMS berekent automatisch het verbruik per kamer door NILM-apparaten en smart plugs te clusteren op basis van de HA Area Registry en naam-heuristieken.

**Sensor:** `sensor.cloudems_room_meter` — staat toont de kamer met het hoogste verbruik, attributen tonen alle kamers.

**Kamer handmatig instellen:**
```yaml
service: cloudems.assign_device_to_room
data:
  device_id: "abc123"  # ID uit sensor.cloudems_nilm_running_devices
  room_name: "Keuken"
```

---

## ⏰ Goedkope uren planner

Configureer via **Instellingen → CloudEMS → Configureren → Features**:

```yaml
cheap_switches:
  - entity_id: switch.wasmachine
    window_hours: 3        # goedkoopste 3-uursblok
    earliest_hour: 7       # niet voor 07:00
    latest_hour: 22        # niet na 22:00
    days: [0,1,2,3,4]     # alleen werkdagen
    active: true
```

De planner zet het apparaat AAN zodra het goedkoopste blok begint. Het apparaat nooit automatisch uitschakelen — de gebruiker doet dat zelf.

---

## ☀️ Schaduwdetectie

CloudEMS vergelijkt elke 10 seconden de werkelijke PV-opbrengst met het geleerde profiel. Na minimaal 7 dagen data rapporteert de sensor structurele schaduw per omvormer.

**Output-attribuut `shadow_data` op de omvormer-sensor:**

| Veld | Beschrijving |
|------|-------------|
| `any_shadow` | `true` als structurele schaduw gedetecteerd |
| `direction` | `oost` / `west` / `midden` / `onduidelijk` |
| `shadowed_hours` | Lijst van getroffen uren met ernst-ratio |
| `daily_loss_kwh` | Geschat dagelijks verlies door schaduw |
| `advice` | Mensleesbaar advies |

> ℹ️ De detector heeft minimaal 7 dagen productiedata nodig. In de eerste week staat `any_shadow: false` met de melding "onvoldoende data".

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
