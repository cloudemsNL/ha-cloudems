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

> ✅ **Bug opgelost in v1.6.0:** Lege velden in het configuratiescherm worden nu correct geaccepteerd — net als in de wizard.

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

> ℹ️ NILM heeft een inwerkperiode van enkele uren tot dagen. De sensor `CloudEMS AI · Status` toont de huidige leerstand. Hoe meer schakelingen gemeten worden, hoe nauwkeuriger de detectie.

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
→ Opgelost in v1.6.0. Zorg dat je de nieuwste versie gebruikt.

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
