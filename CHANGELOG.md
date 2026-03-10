# Changelog

Alle noemenswaardige wijzigingen per versie.

## [4.5.4] — 2026-03-11

### 🐛 Bugfixes

**Issue #3: Dashboard mist entiteiten — entity_id mismatches (sensor.py)**
Root cause: HA genereert entity_ids automatisch van `_attr_name`, maar de namen kwamen niet overeen
met de entity_ids die het dashboard verwacht. Expliciete `self.entity_id` toegevoegd aan:
- `CloudEMSBatterySocSensor`: `sensor.cloudems_battery_soc` → `sensor.cloudems_battery_so_c`
- `CloudEMSPhaseCurrentSensor`: `sensor.cloudems_grid_phase_l1_current` → `sensor.cloudems_current_l1/l2/l3`
- `CloudEMSSelfConsumptionSensor`: `sensor.cloudems_pv_zelfconsumptiegraad` → `sensor.cloudems_self_consumption`
- `CloudEMSSolarSystemSensor`: `sensor.cloudems_solar_system_intelligence` → `sensor.cloudems_solar_system`
- `CloudEMSPriceCurrentSensor`: `sensor.cloudems_energy_price_current_hour` → `sensor.cloudems_price_current_hour`

**Issue #4: Foutieve vermogensberekening huisverbruik in dashboard (www/dashboard.html)**
Root cause: `homeW = solar + netW` hield geen rekening met batterijvermogen.
Bij ontladen (bijv. -3000W) toonde het dashboard 0W huis terwijl er wel 3kW verbruik was.
Fix: `homeW = max(0, solar + netW - batPwrW)` — dezelfde Kirchhoff-formule als `_calc_house_load()`.

**Issue #8: Vals alarm stroomstoring bij NOM / zelfvoorzienend huis (coordinator.py)**
Root cause: detectie alleen op `solar < 10W AND grid < 5W` — bij batterij-ontlading
is dit exact de normale toestand (accu dekt alles, PV=0 's nachts).
Fix: extra checks toegevoegd:
  - `battery_discharge < 50W` — als accu ontlaadt is er geen storing
  - `house_load < 50W` — als huisverbruik berekend > 50W is er geen storing
  Alleen als ÁLle meetpunten nul zijn telt het als potentiële stroomstoring.

### ℹ️ Analyse overige gemelde issues

**Issue #1/2: Entiteiten werken niet / dubbel gezien**
Na de entity_id fixes (boven) zullen gebruikers die al een installatie hadden zowel de
oude (automatisch gegenereerde) als de nieuwe entiteit in HA zien. De oude kan handmatig
worden verwijderd via Instellingen → Entiteiten, of via de OrphanPruner. Bij een nieuwe
installatie treedt dit niet op.

**Issue #5: NILM afwijzen werkt niet** — opgelost in v4.5.3 (user_suppressed persistent)

**Issue #6: NILM apparaten soms fout gedetecteerd** — gedeeltelijk opgelost in v4.5.3
(betere infra-naam filtering). NILM-detectie verbetert naarmate het systeem meer data
verzamelt. Aanbeveling: gebruik 'Bevestigen' / 'Afwijzen' in de CloudEMS app.

**Issue #7: Aanwezigheidsdetector + accu**
De coordinator stuurt al `_calc_house_load(solar, grid, battery)` naar de absence detector,
dus de huisverbruiksberekening is correct. De 'sleeping' melding bij lage accu-verbruiker
komt van de nacht-standby detectie. Dit is beoogd gedrag.

**Issue #9: EPEX prijzen ipv leveranciersprijs** — opgelost in v4.5.1/4.5.2

**Issue #10: Dashboard** — verbeteringen in v4.5.1 en nu entity_id fixes in v4.5.4

## [4.5.3] — 2026-03-11

### 🐛 Bugfixes

**NILM afwijzen werkt nu permanent (nilm/detector.py + coordinator.py)**
- Root cause: `dismiss_device()` verwijderde het apparaat uit `_devices` met `.pop()`,
  maar de store sloeg `user_suppressed=True` nooit op → na herstart HA verscheen het apparaat terug
- Fix: `dismiss_device()` zet nu `user_suppressed=True` en laat het apparaat in `_devices` staan.
  `get_devices_for_ha()` filtert al op `user_suppressed`, dus het verdwijnt direct uit de UI.
  Bij de volgende `async_save()` wordt de flag gepersisteerd.
- `dismiss_nilm_device()` in coordinator triggert nu onmiddellijk `async_save()` via event loop task

**"Electricity Meter Energieproductie" en vergelijkbare systeemnamen in NILM (nilm/detector.py)**
- Uitgebreide naam-keyword filters (beide passes in `get_devices_for_ha()`):
  - Nieuwe termen: `energieproductie`, `energieverbruik`, `stroomlevering`, `netto verbruik`
  - Nieuw patroon: naam bevat "meter" + een energie-term → altijd infra
  - Nieuw patroon: naam begint met "electricity ", "dsmr ", "p1 ", "slimme "
  - Combo-namen: "electricity meter energieproductie", "meter energieverbruik"

**Prijs = 0.0 werd als False behandeld (sensor.py)**
- `ep.get("current_display") or ep.get("current")` → bij prijs exact 0.0 ct viel het terug naar base
- Fix: expliciete `is not None` check

**Daggrafiek toonde altijd basis EPEX ipv all-in (sensor.py)**
- `sensor.cloudems_energy_price` gaf altijd `today_all` (basis EPEX) terug als `today_prices`
- Fix: als `today_all_display` (all-in met tax/BTW/markup) beschikbaar is, wordt dat gebruikt
- `today_prices_base` attribuut toegevoegd voor debugging/vergelijking

### ✨ Verbeteringen

**Setup wizard: eerst land, dan leverancier (www/setup-wizard.html)**
- Stap 5 "Prijsbron" toont nu eerst een landkeuze (🇳🇱 NL / 🇧🇪 BE / 🇩🇪 DE / 🇫🇷 FR / 🇦🇹 AT / 🇳🇴 / 🇸🇪 / 🇩🇰)
- Nadat een land gekozen is, verschijnen alleen de leveranciers die in dat land beschikbaar zijn
- "← Land wijzigen" knop om terug te gaan naar landkeuze
- NL: EPEX (EnergyZero) · Frank Energie · Tibber · Octopus · Eneco · Vattenfall · Essent · ANWB · NieuweStroom
- DE/AT: EPEX (Awattar) · Tibber · Octopus
- BE: EPEX (ENTSO-E) · Tibber · Octopus
- NO/SE/DK: EPEX (Nordpool) · Tibber

**Prijssensor attributen uitgebreid (sensor.py)**
- `prices_from_provider`, `price_include_tax/btw`, `tax_per_kwh`, `vat_rate`, `supplier_markup_kwh`
  nu ook beschikbaar op `sensor.cloudems_energy_price` (was alleen op current_hour sensor)

## [4.5.2] — 2026-03-11

### ✨ Prijsleverancier koppeling — setup wizard & config flow

**Nieuwe stap in de setup wizard (www/setup-wizard.html)**
- Stap 5 "Prijsbron instellen" toegevoegd (was 5 stappen, nu 6)
- Keuze uit: EPEX dag-vooruit · Frank Energie · Tibber · Octopus Energy · Eneco/Vattenfall/Essent/ANWB/NieuweStroom
- Inline credentials-invoer per provider:
  - Tibber: API Token-veld met link naar developer.tibber.com
  - Octopus: API-sleutel-veld
  - Login-providers (Eneco etc.): e-mail + wachtwoordveld
  - Frank Energie + EPEX: geen credentials nodig
- Validatie: "Volgende"-knop geblokkeerd totdat credentials volledig zijn
- Opslaan via HA WebSocket service call (`cloudems.set_price_provider`)
- Graceful fallback als service nog niet beschikbaar: toont uitleg met verwijzing naar opties-flow

**Nieuwe en uitgebreide stappen in config flow (config_flow.py)**
- `async_step_price_provider`: leverancierskeuze na de prijzen-stap (setup flow)
- `async_step_price_provider_credentials`: credentials invullen indien vereist (setup flow)
- `_register_price_provider()`: schrijft provider naar `external_providers` met `_price_provider: true` markering
- `async_step_prices_opts`: leverancierskeuze bovenaan toegevoegd (opties flow)
- `async_step_price_provider_creds_opts`: credentials-stap in opties flow
- `_apply_price_provider_opts()`: schrijft/verwijst provider via config entry update

**Nieuwe constanten (const.py)**
- `CONF_PRICE_PROVIDER` / `DEFAULT_PRICE_PROVIDER`
- `PRICE_PROVIDER_CREDENTIALS`: welke credentials-velden elke provider vereist
- `PRICE_PROVIDER_LABELS`: weergavenamen voor UI

**strings.json / translations**
- Nieuwe stap-definities: `price_provider`, `price_provider_credentials`, `price_provider_creds_opts`
- `prices_opts` bijgewerkt met nieuw `price_provider` veld en beschrijvingsplaceholder

## [4.5.1] — 2026-03-11

### 🐛 Bugfixes — Energieprijzen & dashboard

**Leverancier als primaire prijsbron (coordinator.py)**
- Provider-prijzen (Tibber, Frank Energie, Octopus, etc.) worden nu vroeg in de update-cyclus opgehaald zodat ze beschikbaar zijn als `price_info` wordt samengesteld
- Als een energieleverancier-provider actief is worden zijn all-in prijzen direct als `price_info` gebruikt — geen EPEX + vaste markup meer stapelen bovenop echte leveranciersprijzen
- Nieuw veld `prices_from_provider: true` markeert de data als reeds all-in

**`_apply_price_components` — geen dubbele markup (coordinator.py)**
- Bij provider-prijzen (all-in) worden belasting, BTW en leveranciersmarge niet nogmaals opgeteld
- EPEX-flow ongewijzigd

**`sensor.cloudems_price_current_hour` — attributes (sensor.py)**
- `next_hour_eur_kwh` was altijd `None`: index-fout gecorrigeerd (index 0 = huidig uur, index 1 = volgend)
- Nieuwe attributen: `prices_from_provider`, `price_source`, `provider_key`

**ProviderManager — geen dubbele poll (coordinator.py)**
- Poll-resultaat gecached in `_provider_poll_cache` en hergebruikt aan het einde van de cyclus

### ✨ Dashboard verbeteringen (www/dashboard.html)

- **Prijs-card label** dynamisch: "EPEX prijs" bij EPEX, "Stroomprijs" bij provider
- **Prijs-bron badge** zichtbaar onder de gauge: toont bijv. "Tibber", "Frank Energie", "EPEX · EnergyZero"
- **Eenheid** in gauge center: "ct all-in" bij provider/belasting, "ct/kWh" bij kale EPEX
- **Negatieve prijzen** correct: minteken, cyaan kleur, bar vanuit rechts
- **Delta volgend uur** werkt nu correct (was altijd leeg door index-bug)
- **Goedkope-uren chart**: toont `price_display` (all-in) indien beschikbaar; header toont prijstype; negatieve prijzen correct
- **`nilmDevices`** entiteit toegevoegd aan E-config (veroorzaakte gemiste WebSocket-events)


### Nieuwe integraties (cloud-native, geen HACS afhankelijkheden)

#### ☀️ PV Omvormers
- **SolarEdge** — Monitoring Portal API v1
- **Enphase** — Enlighten API v4
- **SMA** — Sunny Portal / ennexOS API
- **Fronius** — Solar.web API (GEN24, Primo, Symo)
- **Huawei FusionSolar** — OpenAPI
- **GoodWe** — SEMS Portal
- **Growatt** — Growatt Server
- **Solis** — SolisCloud (HMAC-MD5 signing)
- **Deye / Sunsynk** — via SolarmanPV API

#### 🚗 Elektrische Auto's
- **Tesla** — Fleet API (+ owners.api fallback)
- **BMW / Mini** — ConnectedDrive API
- **Volkswagen / Audi / SEAT / Škoda** — WeConnect / Cariad API
- **Hyundai / Kia** — Bluelink / UVO Connect EU API
- **Renault** — My Renault / Gigya API
- **Nissan** — NissanConnect EV (Carwings API)
- **Polestar** — Polestar GraphQL API
- **Ford** — FordPass API
- **Mercedes-Benz** — me connect API
- **Volvo** — Connected Vehicle API v2
- **Rivian** — GraphQL API

#### 🫧 Huishoudapparaten
- **BSH HomeConnect** (Bosch, Siemens, Neff, Gaggenau) — officieel gedocumenteerde API
  - Wasmachine, droger, vaatwasser, oven, koelkast
  - Remote start, stop, programma selectie
- **Ariston NET remotethermo v3** — boilers & warmtepompen
  - CV temperatuur, DHW, vlam-status, modi instellen
- **Miele@home** — officiële Miele cloud API
- **Electrolux / AEG** — Electrolux Group API
- **Candy / Haier** — Simply-Fi / hOn API

#### ⚡ Energieleveranciers
- **Tibber** — officieel GraphQL API
- **Octopus Energy** — NL + UK API
- **Frank Energie** — realtime EPEX prijzen (geen auth nodig)
- **Eneco** — Mijn Eneco API
- **Vattenfall** — MyVattenfall API
- **Essent** — Mijn Essent API
- **ANWB Energie** — API
- **NieuweStroom** — API

### Architectuur
- Nieuw `providers/` package met `base.py`, `inverters.py`, `ev_vehicles.py`, `appliances.py`, `energy_suppliers.py`
- `ProviderManager` coördineert alle externe providers vanuit de coordinator
- `UPDATE_HINTS` dict per provider: altijd direct weten waar API-wijzigingen te vinden zijn
- OAuth2Mixin: herbruikbaar token beheer voor alle OAuth2 providers
- Cloud-variant ready: geen HA-entiteiten nodig, werkt ook in hosted variant

---


## [4.4.5] - 2026-03-10

### Nieuw — EMHASS-geïnspireerde modules

#### Vloer Thermische Buffer (`energy_manager/floor_thermal_buffer.py`)
Physics-informed model voor vloerverwarming als thermische batterij (gebaseerd op
Langer & Volling 2020, zoals geïmplementeerd in EMHASS):
- Modelleert vloertemperatuur via warmtebalans: `T_floor(t+dt) = T_floor(t) + dt/C × (P - UA × ΔT)`
- Leert `C_floor` (thermische capaciteit, Wh/°C) en `UA_floor` (warmteoverdracht, W/°C)
  automatisch als een vloertemperatuursensor beschikbaar is
- `plan_charge_windows()`: berekent optimale laad/afgifte-vensters op basis van
  24-uurs EPEX-prijsprofiel, COP-curve warmtepomp en comfortgrenzen (NEN-EN 1264: max 29°C)
- Werkt zonder vloertemperatuursensor via modelschatting
- Sensor: `cloudems_floor_buffer_status` met t_floor, laadvensters en geschatte besparing

#### ML Verbruiksforecaster (`energy_manager/consumption_ml_forecast.py`)
Lichtgewicht k-NN verbruiksvoorspelling met weers- en seizoensfeatures (geïnspireerd
op de scikit-learn/skforecast aanpak van EMHASS). Geen externe dependencies:
- Features: uur (circulair), weekdag (circulair), seizoen (circulair),
  buitentemperatuur, PV-opbrengst gisteren, weekend-vlag, Heating Degree Day
- Gewogen k-NN regressie (K=7) met euclidische afstand in feature-ruimte
- Fallback op patroongemiddelde als k-NN buren te ver weg zijn
- Bijhoudt MAPE over 7 dagen en feature-importantie via correlatie-analyse
- Sensor: `cloudems_ml_consumption_forecast` met 24-uurs voorspelling en modelstatus

## [4.4.4] - 2026-03-10

### Bugfix

- **Auto-deploy dashboard**: twee fouten opgelost die zichtbaar waren in de HA logs:
  - `'LovelaceData' object has no attribute 'get'` — `hass.data["lovelace"]` is een `LovelaceData`
    TypedDict, geen gewone dict. Fix: gebruik `dashboards_collection` key die HA zelf opslaat
    in `hass.data["lovelace"]["dashboards_collection"]` (zie `lovelace/async_setup`)
  - `Detected blocking call to read_text` — YAML-bestand werd gelezen op de event loop.
    Fix: lezen via `hass.async_add_executor_job()`

## [4.4.3] - 2026-03-10

### Bugfix

- **Auto-deploy dashboard**: volledige herschrijving van `_async_ensure_lovelace_dashboard()`.
  Vorige versie probeerde via de `DashboardsCollection` API te gaan, maar die is na `async_setup`
  van de lovelace component niet toegankelijk via `hass.data`. Nieuwe aanpak schrijft direct naar
  de HA `.storage/` bestanden (zelfde methode als backup/restore tools):
  - `.storage/lovelace_dashboards` → dashboard-registratie (metadata + slug)
  - `.storage/lovelace.cloudems-lovelace` → views en kaarten (yaml-inhoud)
  Daarna hot-registratie voor de huidige sessie via `LovelaceStorage` + `frontend.async_register_built_in_panel`
  zodat geen herstart nodig is.

## [4.4.2] - 2026-03-10

### Dashboard

- **Verbruiksverdeling**: "Verbruik per Categorie" en "Verbruiksverdeling (huidig)" samengevoegd tot één kaart met totaal vandaag, Nu/Vandaag/%-tabel en insight

## [4.4.1] - 2026-03-10

### Bugfixes

- **Auto-deploy dashboard**: 4 bugs opgelost in `_async_ensure_lovelace_dashboard()`:
  - `async_items()` geeft een lijst terug, geen dict — `.get()` en `.items()` werkten niet
  - `"mode": "storage"` veroorzaakte een Voluptuous schema-fout bij `async_create_item`
  - Dashboard-object werd op de verkeerde plek opgezocht na aanmaken
  - Race condition opgelost met `asyncio.sleep(0)` zodat de `CHANGE_ADDED`-listener kan uitvoeren
- **Dashboard duplicaat verwijderd**: `cloudems/cloudems-dashboard.yaml` (root) verwijderd — enige bron is nu `custom_components/cloudems/www/cloudems-dashboard.yaml`
- **Auto-copy dashboard YAML**: `cloudems-dashboard.yaml` wordt bij elke start automatisch gekopieerd naar `/config/` (alleen als de component-versie nieuwer is)

## [4.4.0] - 2026-03-10

### Negen structurele verbeteringen

#### 1. NILM Unsupervised Clustering (`nilm/unsupervised_cluster.py`) — nieuw module
Groepeert onbekende vermogensevents automatisch via incrementele DBSCAN-achtige
clustering zonder scikit-learn-afhankelijkheid. Als een cluster ≥ 5 events bereikt,
verschijnt automatisch een gebruikersvraag: "Onbekend apparaat ~1800 W gedetecteerd —
wat is dit?" Na bevestiging wordt het cluster omgezet naar een NILM-apparaat met
direct herkenning van toekomstige events. Type-suggestie op basis van vermogen + duur
(ketel, wasmachine, EV, warmtepomp, etc.). Persistente opslag via HA Store.
`NILMEventClusterer.add_unknown_event()` aangeroepen vanuit NILMDetector bij
niet-herkende events.

#### 2. Degradatiekosten-bewuste Batterijplanning (`energy_manager/battery_cycle_economics.py`) — nieuw module
`BatteryCycleEconomics` berekent voor elk laad/ontlaad-paar de netto winst ná aftrek
van slijtagekosten. Formule: `netto_spread = (discharge_prijs - charge_prijs / rt_eff) - cycle_cost`.
Chemie-specifieke factoren (LFP 0.0025, NMC 0.0045, NCA 0.0050, LTO 0.0010 €/kWh/cyclus).
SoC stress-boetes: diep ontladen (<15%) +30% slijtage, hoog laden (>92%) +20%.
Eigenverbruik (PV-gevulde batterij dekt directe last) wordt nooit geblokkeerd.
Integreer in `battery_scheduler._build_schedule()` via `eco.evaluate_slot_pair()`.

#### 3. Leverancier Switchadviseur (`energy_manager/supplier_switch_advisor.py`) — nieuw module
`build_switch_advice()` gebruikt de ContractComparison-data van supplier_compare.py
en genereert een concreet switchadvies: "switch_aanbevolen / evalueer / blijf /
onvoldoende_data". Berekent jaarlijkse besparing, terugverdientijd overstapkosten,
beste switchmoment op basis van contracteinddatum, en stapsgewijze administratie-tekst.
Minimale jaarlijkse besparing voor aanbeveling: €60. Maximale terugverdientijd: 3 maanden.
Sensor: `cloudems_switch_advies`.

#### 4. Coördinator opsplitsen — voorbereiding (`coordinator.py`)
De 6300+-regels coordinator is te groot voor veilig onderhoud. Architectuurvoorbereiding:
`CloudEMSConfig.from_dict()` (zie punt 8) vervangt alle verspreid `config.get()`-aanroepen.
`CloudEMSActionsTracker` (zie punt 10) centraliseert beslissingslogging. Volgende stap
(v4.5): opsplitsing in `EnergyCoordinator`, `NILMCoordinator`, `ClimateCoordinator`
als delegate-klassen. Backlog toegevoegd aan coordinator.py commentaar.

#### 5. Getypte Configuratie (`config_schema.py`) — nieuw bestand
Centrale `CloudEMSConfig` dataclass met sub-configuraties: `BatteryConfig`, `EVConfig`,
`PVConfig`, `GridConfig`, `PriceConfig`, `AIConfig`, `NotificationConfig`.
`CloudEMSConfig.from_dict(config)` vervangt verspreid `config.get("key", default)`.
`cfg.validate()` geeft duidelijke foutmeldingen bij ongeldige waarden.
Berekende properties: `ev.max_power_w`, `grid.phases`, `battery.enabled`.
België-autodetectie: `country == "BE"` → `belgium_capacity_enabled = True` automatisch.

#### 6. Unit Tests (`tests/test_cloudems.py`) — nieuwe testsuit
pytest-tests voor de vijf nieuwe en kritieke bestaande modules:
  • `TestBatteryCycleEconomics` — 8 parametrized tests incl. chemie, efficiency, SoC-stress
  • `TestNILMEventClusterer` — 8 tests incl. clustering, type-suggestie, bevestiging
  • `TestBelgianCapacityCalculator` — 6 tests incl. postcode-detectie, vrije band
  • `TestCloudEMSConfig` — 6 tests incl. validatie, auto-België, type-conversie
  • `TestSupplierSwitchAdviseur` — 4 tests incl. edge cases
  • `TestActionsTracker` — 5 tests incl. headline-generatie, serialisatie
Uitvoeren: `pytest tests/test_cloudems.py -v`

#### 7. "Wat heeft CloudEMS vandaag voor je gedaan?" (`energy_manager/actions_tracker.py`) — nieuw module
`CloudEMSActionsTracker` registreert elke CloudEMS-actie gedurende de dag:
boiler verschoven, EV op PV-surplus geladen, congestie-event afgevangen, etc.
Om middernacht reset de dagkaart automatisch; gisterenkaart blijft bewaard.
`DaySummaryCard.build_headline()` genereert leesbare samenvatting:
"€1.23 bespaard — boiler 2× verschoven, EV 8.4 kWh smart geladen, 1 congestie-event".
Sensor: `cloudems_dag_acties` met `headline`, `total_saving_eur`, `action_count`,
`recent_actions[]`. Zichtbaar als prominente kaart op de Overzicht-tab.
Integratie via `coordinator._actions_tracker.log_action(...)` bij elke beslissing.
`Actions`-constanten-klasse voorkomt typo's in action_type strings.

#### 8. Installatiescore Dashboard Presenter (`energy_manager/installation_score_presenter.py`) — nieuw module
`InstallationScorePresenter` maakt de score zichtbaar op de Overzicht-tab (niet alleen
Diagnose). "Quick wins" gesorteerd op impact/moeite-verhouding met directe actie-URL
per ontbrekend onderdeel. Score-trending over 7 dagen (richting: stijgend/stabiel/dalend).
`should_show_persistent_notification()` triggert HA-notificatie als score < 50.
Sensor `cloudems_setup_score` krijgt `next_step_label`, `next_step_url`, `quick_wins[]`
als attributen — bruikbaar voor dashboard-knoppen via custom:button-card.

#### 9. België Capaciteitstarief Module (`energy_manager/belgium_capacity.py`) — nieuw module
Specifieke implementatie voor Belgisch capaciteitstarief (actief 2023):
  • Grondslag: rolling gemiddelde van 12 hoogste maandpieken (niet alleen huidige maand)
  • DSO zone-detectie op basis van postcode: Fluvius Antwerpen/Gent/Limburg/Oost-VL/
    West-VL/Vlaams-Brabant, Ores (Wallonië), Sibelgas (Brussel)
  • Tarieven 2025 per DSO (37.90–48.20 €/kW/jaar)
  • Vrije band: eerste 2.5 kW altijd gratis
  • `estimate_cost_impact(extra_kw)` — berekent extra jaarkosten per kW piek-stijging
  • Automatisch geactiveerd als `country == "BE"` in config
  • Sensor: `cloudems_be_capacity_cost` met `rolling_12m_avg_kw`, `estimated_annual_cost`,
    `monthly_headroom_kw`, `dso`, `warning_level`

---

## [4.3.5] - 2026-03-09

### Acht intelligentie-verbeteringen + persistentie

#### 1. LoadPlanAccuracyTracker (`load_plan_accuracy.py`) — nieuw module
Vergelijkt elke ochtend het gisteren gegenereerde LoadPlanner-plan (estimated_savings_eur)
met de werkelijke EPEX-data en het verbruik uit price_hour_history. Leert correctiefactoren
voor PV-forecast-bias en prijsforecast-bias via trage EMA. Persistente opslag via Store.
Sensor: correctiefactoren, accuracy-percentage, 14-daags overzicht.

#### 2. CapacityPeakMonitor persistentie (`capacity_peak.py`)
De 12-maanden piekhistorie en huidige maandpiek worden nu opgeslagen via HA Store.
Na een herstart is de piekdrempel direct beschikbaar — geen gemiste maand-peak meer.
`async_setup()` en `async_maybe_save()` toegevoegd.

#### 3. SensorEMA persistentie (`sensor_ema.py`)
EMA-states (ema, interval_ema, alpha) worden bewaard bij herstart. De eerste minuten
na een herstart zijn nu ruis-vrij — de EMA werkt direct alsof hij nooit gestopt was.

#### 4. InstallationScore trending (`installation_score.py`)
Score-verloop over de laatste 7 dagen bijgehouden in Store. Als de score > 5 punten
daalt (bv. door een uitgevallen sensor) verschijnt `trend_alert` in de sensor-attributen
en een WARNING in de coordinator-log.

#### 5. Supplier_compare dynamische tarieven (`supplier_compare.py`)
Nieuwe functie `derive_actual_tariff()` berekent het consumption-weighted gemiddelde
import- en exporttarief uit price_hour_history. De vergelijking toont nu altijd de
werkelijke marktprijzen als metadata naast de referentiecontracten.

#### 6. SleepDetector ↔ AbsenceDetector koppeling (`absence_detector.py`)
`set_sleep_mode(is_sleeping, confidence)` toegevoegd aan AbsenceDetector. Wanneer
SleepDetector slaap detecteert, wordt het away_score richting 0.35 geblend (slaap ≠
afwezigheid). Bij confidence ≥ 0.6 overschrijft het de staat direct naar "sleeping".

#### 7. HeatPumpCOP → SmartClimate koppeling (`heat_pump_cop.py`, `smart_climate.py`)
`get_heating_rate_estimate(outdoor_temp_c)` toegevoegd aan HeatPumpCOPLearner: schaalt
de geleerde COP naar K/min (COP 3.0 → 0.20 K/min). `seed_from_cop_estimate(zone, rate)`
in PredictiveStartScheduler zaait zones zonder meetdata met deze COP-prior.

#### 8. LoadPlanner dag-type correctie (`day_classifier.py`)
DayTypeClassifier houdt nu per weekdag (Ma..Zo) een EMA bij van het uurlijkse
vermogensprofiel. `get_peak_hours(weekday, top_n=3)` geeft de typische piekuren
terug — maandag vs. vrijdag worden zo anders behandeld in de LoadPlanner.

### Bugfixes (overgedragen van v4.3.4-hotfix)
- `sensor.py` lijn 1385: `NameError: name 'time' is not defined` — import-alias
  `time as _time_mod` niet consistent gebruikt. Gecorrigeerd naar `_time_mod()`.
- `coordinator.py` lijn 2886: `'VirtualZone' object has no attribute 'area_id'` —
  ShutterController itereerde zones zonder `getattr`-guard. Gecorrigeerd.

## [4.3.4] - 2026-03-09

### Zeven nieuwe intelligentie-verbeteringen

#### EV-laaddrempel zelfkalibratie (`dynamic_ev_charger.py`)
`DynamicEVCharger` past de cheap_threshold automatisch aan op het **p35-percentiel
van de afgelopen 30 dagen EPEX-prijzen**. Bij dure wintermaanden schuift de drempel
mee omhoog, bij goedkope zomernachten omlaag — zonder handmatige aanpassing.
Geconfigureerde drempel blijft de fallback; kalibratie blijft binnen ±50%.
`feed_price_history()` aangeroepen vanuit coordinator na elke hourly update.

#### BDE 24-uurs gewichtenmatrix (`bde_feedback.py`)
`BDEFeedbackTracker` beheert naast globale gewichten nu ook een **24-uurs profiel
per beslissingstype**. Een "epex_cheap" beslissing om 03:00 heeft een andere
historische trefkans dan om 14:00. BDE-confidence wordt voor de actieve beslissing
geschaald met `get_weight_for_hour(source, hour)` vóór uitvoering. Persistente
opslag in dezelfde Store (backward compatible).

#### SalderingCalibrator (`saldering_context.py`)
Nieuwe klasse `SalderingCalibrator` leert het **werkelijke salderingspercentage**
vanuit dagelijks gemeten import/export data. Wettelijke waarden (36% in 2026) worden
gecorrigeerd als de energiemaatschappij in de praktijk afwijkt. Elke nacht om 03:00
wordt een dagmeting opgeslagen. `get_calibrated_context()` geeft een gecalibreerde
`SalderingContext` terug als drop-in vervanging.

#### GasPredictor stuksgewijze fit (`gas_predictor.py`)
Het gasmodel gebruikt nu een **stuksgewijze lineaire regressie** met drie
temperatuurzones (< 5°C, 5–12°C, > 12°C). Per zone een eigen helling en intercept,
zodat het niet-lineaire gedrag van vloerverwarming, warmtepompen en stookgrenzen
correct wordt gevangen. R² wordt gerapporteerd vanuit de geselecteerde zone.

#### NILMScheduleLearner ↔ BehaviourCoach koppeling
`NILMScheduleLearner.apply_coach_feedback()` ontvangt aanbevelingen van
`BehaviourCoach` en slaat het **aanbevolen verschuivingsuur + maandelijkse besparing**
op per apparaat in `DeviceSchedule`. Zichtbaar in sensor-attributen en klaar voor
dashboard-badges ("verschuif naar 03:00 → €4.20/mnd").
Coordinator roept `apply_coach_feedback()` automatisch aan na elke coach-analyse.

#### Notificatie-moeheids-detectie (`notification_engine.py`)
`NotificationEngine` telt via `ignored_count` hoe vaak een alert opnieuw verstuurd
wordt zonder dat het opgelost raakt. Na 5× negeren wordt de cooldown verdubbeld
(elk blok van 5 extra negeertijden verdubbelt opnieuw: 1×, 2×, 4×, 8×...).
Bij oplossing reset `ignored_count` naar 0. `get_fatigue_summary()` toont welke
alerts moeheid vertonen — nuttig voor drempel-optimalisatie.

#### ApplianceROI cumulatieve besparingstracking (`appliance_roi.py`)
`ApplianceROICalculator` heeft nu een HA Store (`cloudems_appliance_roi_v1`) en
accumuleeert dagelijks de werkelijke besparing per NILM-apparaat. Na een jaar:
`get_lifetime_summary()` geeft een overzicht zoals "EV-lader: €340 bespaard,
1.240 kWh". Zichtbaar in `to_sensor_dict()` via nieuw veld `total_saved_eur`.
## [4.3.3] - 2026-03-09

### Volledige zelflerend-audit — alles in één release

#### Persistentie — vier modules die leerden maar alles vergaten bij herstart

**`AbsenceDetector`** — weekpatroon (7×24 slots) en nacht-standby EMA worden nu
opgeslagen via HA Store (`cloudems_absence_detector_v1`). Na een herstart begint
aanwezigheidsdetectie meteen op het geleerde patroon in plaats van opnieuw te
leren. `async_setup()` wordt aangeroepen vanuit coordinator setup.

**`ShutterThermalLearner`** — geleerde raamoriëntaties per kamer (azimuth-buckets)
worden persistent opgeslagen (`cloudems_shutter_thermal_v1`). Het leren van een
oriëntatie kost een heel seizoen aan zonnedagen — dit verlies bij iedere herstart
is nu voorkomen. Constructor accepteert nu `hass` parameter.

**`SensorSanityGuard`** — het geleerde gemiddelde per sensor (gebruikt voor
spike-detectie) wordt opgeslagen (`cloudems_sensor_sanity_v1`). Na herstart wordt
de history voorgevuld met het geleerde gemiddelde zodat de eerste uren geen valse
spike-alarmen worden gegenereerd.

**`PredictiveStartScheduler`** (in SmartClimate) — geleerde opwarmsnelheden per
zone (K/min) worden opgeslagen (`cloudems_predictive_scheduler_v1`). Na herstart
klopt de voorverwarmingstijd meteen, zonder een dag te wachten op nieuwe metingen.

#### Cross-module leerloops — vier nieuwe koppelingen

**HomeBaseline standby → BatteryUncertaintyTracker** — de grid-delta schatting
voor stale batterijen gebruikt nu de geleerde standby-basislast van HomeBaseline
(`get_standby_w()`) in plaats van de hardcoded 500W default.

**AbsenceDetector "weg" → NILM gevoeligheid** — als aanwezigheid met ≥70%
zekerheid als "away" of "vacation" wordt geclassificeerd, verdubbelt de
`AdaptiveNILMThreshold` automatisch zijn drempel. Koelkast- en routerfluctuaties
worden dan niet als nieuwe apparaten geregistreerd. Bij thuiskomst keert de
drempel terug naar de geleerde waarde.

**NILM confirmed standby → HomeBaseline correctie** — elke nacht om 03:00 worden
bevestigde always-on apparaten (koelkast, router, alarm) vanuit NILM doorgegeven
aan `HomeBaselineLearner.adjust_standby()` zodat de standby-drempel klopt met de
werkelijke installatie.

**PVAccuracy bias → PVForecast kalibratie** — de dagelijkse en maandelijkse
afwijkingsfactor van PVAccuracyTracker (werkelijk vs voorspeld) wordt elke nacht
via EMA doorgegeven aan de `_calib_factor` van alle omvormerprofielen in
PVForecast. De volgende dag start de voorspelling al gecorrigeerd.

#### Seizoenskalibratie — BoilerController auto-setpoints

`BoilerController.auto_calibrate_season()` past zomer/wintersetpoints automatisch
aan op basis van de buitentemperatuur als de gebruiker geen expliciete setpoints
heeft geconfigureerd:
- Buiten ≥15°C → setpoint_summer = setpoint − 5°C (minder stilstandsverlies)
- Buiten ≤5°C  → setpoint_winter = setpoint + 3°C (extra thermische buffer)

Wordt elke nacht om 03:00 aangeroepen vanuit de nachtcyclus.

#### AdaptiveNILMThreshold uitbreiding

`set_away_mode(True/False)` — drempel ×2 bij afwezigheid, terugzetten bij
thuiskomst. Zichtbaar in `sensor.cloudems_nilm_diagnose` als `away_mode: true`.
## [4.3.2] - 2026-03-09

### NILM — Volledig autonome zelfverbetering (geen gebruikersfeedback nodig)

CloudEMS NILM leert nu automatisch elke dag, zonder enige gebruikersinteractie.

**Vier autonome leerbronnen voor FalsePositiveMemory:**

1. **Steady-state validatie** — als na 35s de baseline niet stijgt met het verwachte
   vermogen, was het apparaat een false positive. De power-signature wordt nu automatisch
   opgeslagen zodat hetzelfde vermogen de volgende keer geblokkeerd wordt (was: alleen
   verwijderd zonder te leren).

2. **Korte sessies (<8s)** — een apparaat dat binnen 8 seconden alweer uitgaat is bijna
   zeker een transitiefluctuatie (batterij-ramp, EPEX-schakelaar, netwissel). Wordt nu
   automatisch als false-positive geleerd.

3. **Nachtelijke confidence-vloer sweep (03:00)** — niet-bevestigde apparaten met
   `effective_confidence < 0.15` die al 3+ dagen niet meer gezien zijn, worden
   automatisch naar FP-geheugen geschreven en verwijderd.

4. **Duplicate watt-klasse detectie (03:00)** — als twee niet-bevestigde apparaten
   tegelijk dezelfde watt-klasse (±200W) op dezelfde fase hebben, wordt de minst
   geziene verwijderd en geleerd. Vangt de "Nexus maakt drie 3kW-ghosts" situatie op.

5. **Lange ghost-sessies (03:00)** — niet-cycling apparaten die al >6u "aan" staan
   zonder off-edge worden als stranded detection herkend, geleerd en opgeruimd.

**Elke nacht om 03:00** draait `auto_prune_ghosts()` automatisch. Na een week heeft
CloudEMS de typische false-positive-patronen van jouw installatie geleerd en blokkeert
ze nog voor classificatie.

### MacroLoadTracker verbetering
Suppression-teller per grootverbruiker — het systeem monitort nu hoeveel events per
apparaat worden onderdrukt, wat inzicht geeft in welke verbruiker de meeste ruis
produceert (zichtbaar in `sensor.cloudems_nilm_diagnose`).
## [4.3.1] - 2026-03-09

### NILM — Batterij-onzekerheid (Nexus / traag gemeten accu's)

**Nieuw: `BatteryUncertaintyTracker`** — dedicated bescherming voor thuisbatterijen
met vertraagde of ontbrekende metingen (Zonneplan Nexus: ~60–90s updatevertraging).

Vier beschermingslagen die vervangen de oude EMA-decay-naar-0 staleness-guard:

- **Stale-breedte masker** — als een battery-entity geen verse meting heeft, wordt het
  onzekerheidsvenster verbreed rondom de *laatste bekende waarde* (niet gedecayed naar 0).
  Events die binnen dat venster vallen worden onderdrukt.
- **Burst-update detectie** — als na een stale periode ineens een grote vermogenssprong
  binnenkomt (bijv. Nexus springt van 0 → 3200 W in één tick), worden alle NILM-apparaten
  die tijdens de stale periode aangemaakt zijn en qua vermogen overeenkomen achteraf verwijderd.
- **Grid-delta schatting** — als geen batterijmeting beschikbaar is maar grid + solar wél
  gemeten worden, schatten we het batterijvermogen als `P_solar - P_grid - P_baseline` zodat
  het masker ook zonder directe meting actief blijft.
- **Provider-profielen** — `nexus`/`zonneplan` krijgt 75s stale-drempel en 120s burst-masker;
  `cloud` 45s/60s; `local` 25s/30s. Wordt automatisch afgeleid uit `battery_type` in de config.

**Nieuw: `FalsePositiveMemory`** — persistent geheugen voor afgewezen power-signatures.
Wanneer de gebruiker een apparaat als "incorrect" markeert, slaat dit de power-signature
(vermogen + fase + tijdvak) op. Volgende events met hetzelfde vermogen worden automatisch
onderdrukt. Opgeslagen via HA Store (`cloudems_nilm_fp_memory_v1`), vervalt na 90 dagen.

**Nieuw: `MacroLoadTracker`** — ruis-onderdrukking voor grote verbruikers (EV-lader,
warmtepomp, boiler). Berekent de standaarddeviatie van het vermogensvenster per apparaat
en blokkeert NILM-events die kleiner zijn dan 3,5× die σ. Leert ook vaste schakelstappen
(bijv. boiler-thermostaat ±2500 W).

### Bugfix — staleness-guard
De oude `_BATTERY_EMA_HOLD = 0.85` decay was onjuist: een Nexus die 3 kW laadt en 60s
geen update geeft, laadt waarschijnlijk nog steeds ~3 kW. Na 6 cycli (60s) was de
gerapporteerde waarde 38% van de werkelijkheid — NILM dacht dat de batterij inactief was.
Vervangen door *hold-laatste-waarde* + groeiend onzekerheidsvenster.

### Diagnostics
`sensor.cloudems_nilm_diagnose` bevat nu ook:
- `fp_memory` — opgeslagen signatures, top-5 meest afgewezen
- `macro_load` — actieve grootverbruikers en hun σ/drempel
- `battery_uncertainty` — per batterij: effectief vermogen, stale-status, masker
## [4.3.0] - 2026-03-09

### Toegevoegd
- **Sub-apparaten in HA**: Elke device-groep verschijnt nu als genest kind-apparaat onder CloudEMS Energy Manager
  - CloudEMS NILM Bediening (bevestig/afwijs knoppen)
  - CloudEMS Rolluiken (rolluik actie-knoppen + schakelaar)
  - CloudEMS PV Dimmer (omvormer schakelaars + sliders)
  - CloudEMS Zonne-energie (omvormer profiel/clipping sensoren)
  - CloudEMS Zone Klimaat (per-zone klimaat + kostensensoren)
- **Centrale orphan pruner**: Alle verouderde dynamische entiteiten (NILM, rolluiken, omvormer, zones) worden automatisch opgeruimd via `orphan_pruner.py`
- **Persistente orphan grace-tellers**: `_absent` tellers worden bewaard in HA storage (`cloudems_orphan_pruner_v1`) — herstart van HA reset de tellers niet meer
- **Zone klimaat entiteiten**: Correct gegroepeerd onder parent apparaat, dynamisch geregistreerd via coordinator listener
- **Slimme Uitstel** geïntegreerd in Goedkope Uren Schakelaars flow
- **EPEX prijsstaven**: Kleur op basis van prijsklasse in dashboard
- **Rolluik dashboard**: Volledig dynamisch op basis van geconfigureerde rolluiken
- **Versie centraal**: `VERSION` wordt uitgelezen uit `manifest.json` — `const.py`, sensor attributen en dashboard footers volgen automatisch
- **Persistente orphan grace-tellers**: grace-tellers bewaard in HA storage, updates gebufferd tot store geladen is
- **Ghost device indicator**: NILM beheer tab toont apparaten die > 7 dagen niet gezien zijn
- **Systeem gezondheid visual**: Diagnose tab toont health score 0-10 als visuele balk met kleurcodering
- **EPEX morgen hint**: Als alle uren van vandaag voorbij zijn, toont het goedkoopste uur van morgen
- **Goedkope uren besparing**: Schakelaar tabel toont blokprijs vs daggemiddelde en geschatte besparing per kWh
- **Smoke tests**: `tests/test_smoke.py` controleert semver, manifest-const sync en hacs.json
- **Zonneplan override detail**: Override tabel toont modus + minuten actief, auto-sturing label toegevoegd

### Opgelost
- `CloudEMSZoneClimateCostSensor`: verkeerde `entity_id` gegenereerd (`sensor.cloudems_klimaatkosten_vandaag` → `sensor.cloudems_zone_klimaat_kosten_vandaag`)
- Orphan pruner verwijderde ten onrechte NILM switches (`nilm_active`, `hmm_active`, `bayes_active`)
- `room_overview` en `zone_climate_cost_today` werden ten onrechte als dynamisch beschouwd en gepruned
- Dashboard: deprecated `call-service` → `perform-action` (HA 2024.8+)
- Dashboard: `content: >` block scalars vervangen door `content: |` (HA card parser compatibiliteit)
- Dashboard: alle hardcoded versienummers vervangen door dynamische template
- Dashboard: `call-service` entiteitsrijen vervangen door markdown referentiekaart

### Gewijzigd
- `orphan_pruner.py` v1.1.0: volledige herschrijving met dirty-flag opslag, persistente tellers en correcte shutter support
- `const.py`: `VERSION` is nu een computed property gelezen uit `manifest.json`

## [4.1.0] - 2026-03-09

### Vergeten-aan detectie (Appliance Over-On Guard)
- 🚨 **Nieuw: `energy_manager/appliance_overon_guard.py`** — detecteert apparaten die significant
  langer aan staan dan normaal of een gevaarlijke maximale aan-tijd bereiken.
  - **Twee detectielagen:**
    1. *Geleerd maximum* — per apparaat: huidige aan-tijd > 2,5× gemiddelde sessieduur → WARNING
    2. *Hard maximum* — per apparaattype: absolute bovengrens ongeacht leergeschiedenis → CRITICAL
  - **30+ apparaattypen** in de hard-maximum tabel: friteuse (1 u), strijkijzer (30 min),
    stijltang (30 min), grill (1,5 u), airfryer (1 u), waterkoker (10 min), toaster (10 min),
    ruimteverwarmer (8 u), elektrisch deken (4 u), stroomgereedschap (2 u), enz.
  - Prioriteit-escalatie: WARNING bij geleerd max, CRITICAL bij hard max
  - Alert vanzelf opgelost zodra apparaat uitgeschakeld wordt
- 🔧 **`nilm/detector.py`** — `DetectedDevice.to_dict()` exporteert nu `on_since_ts`
  (timestamp van het moment dat het apparaat aanging), nodig voor de over-on guard.
- 🔔 **`notification_engine.py`** — roept `build_overon_alerts()` aan als extra alertlaag,
  samengesteld met de bestaande NILM alerts dict.

## [4.0.9] - 2026-03-08

### Geen externe afhankelijkheden meer (HA-integratie)
- ♻️ **`local_ai.py` herschreven** — pure Python k-NN classifier vervangt scikit-learn + numpy
  - Algoritme: gewogen k-Nearest Neighbors (k=5, Manhattan distance)
  - Normalisatie: min-max in pure Python
  - Opslag: JSON in plaats van pickle — leesbaar, portable, geen binary
  - Zelfde interface (`PowerEvent`, `classify()`, `add_training_sample()`)
  - Trainingsdata van bestaande installaties blijft gewoon werken (features ongewijzigd)
- 🔌 **`aiohttp.ClientSession()` overal vervangen** door `async_get_clientsession(hass)`
  - Bestanden: `coordinator.py`, `price_fetcher.py`, `thermal_model.py`,
    `nilm/detector.py`, `nilm/database.py`, `log_reporter.py`
  - HA beheert de HTTP-sessie — betere connection pooling, geen resource-leaks
- 📦 **`manifest.json` requirements leeg** — `numpy>=1.21.0` en `aiohttp>=3.8.0` verwijderd
  - Nieuwe installaties downloaden geen extra pakketten meer
  - Bestaande installaties werken ongewijzigd (numpy/aiohttp staan gewoon stil)
- 🏗️ **`entity_provider.py` + `ha_provider.py` toegevoegd** — abstractielaag voor cloud-compatibiliteit
  - `EntityProvider` abstracte basisklasse met `get_state()`, `get_all_of_domain()`, `call_service()`
  - `EntityState` dataclass vervangt HA's `State` object in de engine
  - `HAEntityProvider` wikkelt `hass.states` en `hass.services` — gedrag ongewijzigd
  - Provider registry met `@register_provider` decorator
  - Coordinator heeft `self._provider`, `_async_get_state()`, `_async_call_service()`
  - Gedocumenteerd in `docs/ARCHITECTURE_ENTITY_PROVIDER.md`
- 🐛 **`nilm_filter.py`** corrupt bestand (afgekapt) vervangen door stub

## [4.0.8] - 2026-03-08

### Nieuwe feature — CloudEMS als thermostaat
- 🌡️ **`climate.py` platform** — CloudEMS registreert nu zelf `climate.cloudems_<zone>` entities in HA
  - Één entity per HA Area (automatisch ontdekt via zone_climate_manager)
  - HVAC modes: `heat` / `auto` / `off`
  - Presets: `comfort` / `eco` / `boost` / `sleep` / `away` / `solar` / `eco_window`
  - Setpoint-wijziging → zone comfort-temperatuur + 4u override
  - Preset-keuze → VirtualZone override (automatisch verlopen na 4u)
  - `hvac_mode off` → away-preset met 24u override (vorstbeveiliging blijft actief)
  - Extra attributen: heat_demand, best_source, cost_today_eur, window_open, preheat_min
- 🔧 `ZoneClimateManager.async_update` geeft zones nu als dict (area_id → ZoneSnapshot) ipv lijst
- ⚙️ `climate_mgr_enabled` toggle in config flow stap 3

### Activeren
Zet `climate_mgr_enabled: true` in de CloudEMS opties (via Integraties → CloudEMS → Configureren).
CloudEMS ontdekt dan automatisch zones op basis van je HA Area-indeling.

## [4.0.7] - 2026-03-08

### Bestaande functies versterkt
- 🔋 **Budget → BDE koppeling** — bij budgetoverschrijding schakelt BDE automatisch naar 'conservative' modus (minder laden)
- 🔢 **Health Score numeriek** — `sensor.cloudems_systeemgezondheid` geeft nu 0-10 score (was tekst "ok/degraded")
- 🚗 **EV EPEX+PV gecombineerde planning** — dynamisch gewogen score: bewolkt = prijs domineert, zonnig = PV domineert; toont top-5 uren met score

### Nieuwe features
- 💰 **Energiecontract vergelijker** (`supplier_compare.py`) — berekent wat je bij vast/dal-piek/groen contract had betaald op basis van werkelijk verbruiksprofiel
- ⚡ **P1 spanning + storingen** — parser uitgebreid met `voltage_l1/2/3` (V), `power_failures`, `long_power_failures`, `voltage_sags_l1/2/3`; zichtbaar in dashboard
- 📊 **Dashboard**: Health Score 0-10 balk, Contract vergelijker tabel, P1 Netspanning & Storingen kaart

### Storage keys nieuw
Geen — supplier_compare is stateless (herberekend uit price_hour_history)

## [4.0.6] - 2026-03-08

### Technische schuld opgelost
- 🔒 **`_safe_state()` wrapper** — alle `hass.states.get()` aanroepen in coordinator vervangen door centrale wrapper met exception-handling; voorkomt crashes bij HA-herstart

### Nieuwe features
- ☀️ **Zelfconsumptie-ratio sensor** (`sensor.cloudems_zelfconsumptie`) — % PV direct gebruikt; zelfvoorzieningsgraad als extra attribuut
- ☀️ **Zelfvoorzieningsgraad sensor** (`sensor.cloudems_zelfvoorzieningsgraad`) — % huis-verbruik gedekt door eigen PV
- 💡 **NILM Apparaat-ROI** (`appliance_roi.py`) — kosten per apparaat (€/mnd, €/jaar), potentiële besparing bij tijdverschuiving, tips per apparaat; live in data dict
- 🔋 **Batterij-efficiëntie tracker** (`battery_efficiency.py`) — meet dagelijks round-trip efficiency, waarschuwing bij < 80%, persistent 90-dagen history
- 🌙 **OffPeak detector → BDE Laag 3b** — automatische dal-tarief detectie uit 30-dagen prijshistorie
- 🔁 **BDE Feedback loop** — zelflerend gewichtensysteem (0.5–1.5×) op basis van terugkijkende prijsevaluatie
- 🌡️ **Gas-voorspelling** (`gas_predictor.py`) — lineair regressiemodel (temp → m³), stookgrens, HDD, maandkosten
- 💰 **Tariefwijziging-detector** (`tariff_change_detector.py`) — vergelijkt werkelijke opslag met geconfigureerde; HA-notificatie bij wijziging
- 🕐 **NILM tijdpatroon** (`time_pattern_learner.py`) — 7×24 uurhistogram, anomalie-notificatie
- 🔍 **Watchdog silent hang detectie** — `report_update_started()` + `check_silent_hang()` detecteert hangende netwerk-aanroepen zonder exception

### Storage keys nieuw
`cloudems_battery_efficiency_v1`, `cloudems_bde_feedback_v1`, `cloudems_gas_predictor_v1`,
`cloudems_tariff_detector_v1`, `cloudems_nilm_time_patterns_v1`

## [4.0.5] - 2026-03-08

### Toegevoegd
- 🏆 **Dashboard "Installatiescore"** — cirkel met score/100, tabel per criterium, verbeter-tips; score bijgewerkt met BDE + ExportTracker criteria (max 102→100 genormaliseerd)
- 🕐 **TimePatternLearner** (`nilm/time_pattern_learner.py`) — 7×24 uurhistogram per NILM-apparaat, persistentie via HA Store, anomalie-detectie + persistent notification bij ongewoon gebruik
- 🌙 **OffPeakDetector** (`energy/off_peak_detector.py`) — automatische dal-tarief detectie op basis van 30-dagen prijshistorie; Laag 3b in BatteryDecisionEngine: laden tijdens gedetecteerde dal-uren
- 🔁 **BDE Feedback Loop** (`energy/bde_feedback.py`) — registreert elke beslissing, evalueert per uur of charge/discharge voordelig was vs. daggemiddelde, past confidence-gewichten aan (leertempo 5%, range 0.5–1.5)
- 🌤️ **Seizoensgecorrigeerde jaarschatting** in ExportDailyTracker — `get_season_factor()`, `get_monthly_avg()`, `extrapolate_annual_kwh()` voor nauwkeurigere export-projectie

### Technisch
- `DecisionContext`: nieuw veld `off_peak_active`
- `coordinator.py`: 6 nieuwe attributen (`_time_pattern_learner`, `_off_peak_detector`, `_bde_feedback`, stores), evaluatie bij uurwisseling, opslaan bij dagcyclus
- Storage keys: `cloudems_nilm_time_patterns_v1`, `cloudems_bde_feedback_v1`

## [4.0.4] - 2026-03-08

### Toegevoegd
- ⚡ **PowerLearner Laag C geïntegreerd** — `adjust_delta_for_concurrent_load()` wordt nu aangeroepen bij elk on-event; concurrent context wordt gelogd op DEBUG niveau
- 📊 **`concurrent_loads` in NILM diagnostics** — per fase: total_w, apparatenlijst, count
- 📈 **`concurrent_load` in coordinator data** — per fase L1/L2/L3 beschikbaar voor BDE en andere modules
- 🖥️ **Dashboard "⚡ Actieve Last per Fase (Laag C)"** — tabel L1/L2/L3, PowerLearner stats (boosts, off-matches, auto-confirm), top-5 geleerde profielen

### Opgelost
- 🐛 **`_nilm_detector` attribuut bestaat niet** — BDE pakte altijd 0W concurrent load door verkeerde attribuutnaam; gecorrigeerd naar `self._nilm`

## [4.0.3] - 2026-03-08

### Toegevoegd
- 🔋 **BatteryDecisionEngine v2** — Laag 1b peak shaving: batterij ontlaadt automatisch als grid-import > geconfigureerd limiet (capaciteitstarief bescherming)
- 🎯 **target_soc_pct** op elke beslissing (bijv. 80% bij LOW tariefgroep, 20% bij ontladen)
- ✅ **Actie-uitvoering** — als `confidence ≥ 0.75` stuurt coordinator automatisch modus naar Zonneplan bridge (`self_consumption` / `home_optimization`)
- 📊 **Dashboard "🧠 Batterij beslissing"** — volledig herbouwd met explain-lijst, uitvoeringstatus, doelwaarde SOC, peak shaving indicatie

### Gewijzigd
- `coordinator.py`: één `self._battery_decision_engine` instantie (was twee losse aanroepen), `pv_forecast_tomorrow_kwh` correct doorgegeven (was hardcoded 0.0), `peak_shaving` context meegegeven
- `DecisionContext`: nieuwe velden `peak_shaving_active`, `grid_import_w`, `grid_peak_limit_w`
- Output dict `battery_decision`: nieuwe velden `target_soc_pct`, `executed`

## [4.0.2] - 2026-03-08

### Toegevoegd
- 📊 **ExportDailyTracker** — persistente rolling 30-dagen buffer voor dagelijkse export-kWh (overleeft herstart via HA Store `cloudems_export_daily_history_v1`)
- 🔋 **Batterij-aanbeveling in ExportLimitMonitor** — berekent optimale batterijcapaciteit en ROI op basis van piekexport
- 📉 **Dashboard: "Salderingsafbouw & Teruglevering"** — toont echte dagdata, jaar-voor-jaar tabel 2026/2027/0% en batterijadvies met alert banner

### Gewijzigd
- `export_limit_monitor.py` volledig herschreven (v2.0): echte daggemiddelden ipv `export_w * 24 * 0.3`, geen dubbele instantiatie, juiste saldering % (2026: 36%, 2027: 0%)
- `coordinator.py`: `ExportDailyTracker` geladen bij `async_setup()`, dagelijkse recording bij DailySummary trigger (7:30), real-time update elke cyclus

### Technisch
- Nieuwe output velden in `export_limit` dict: `avg_daily_export_kwh`, `peak_daily_kwh`, `recommend_battery_kwh`, `battery_roi_years`, `days_of_data`
- Salderingspercentages gecorrigeerd: 2025=64%, 2026=36%, 2027=0% (was 2026=27%)

## [4.0.1] - 2026-03-08

### Toegevoegd
- 🚫 **NILM Exclude via HA-area** — verplaats een device in Home Assistant naar de kamer "CloudEMS Exclude" om het volledig uit te sluiten van NILM en device-tracking. Werkt automatisch, geen herstart nodig.

### Technisch
- `coordinator.py`: Laag 4 toegevoegd aan `_config_eids` uitbreiding — scant `area_registry` en `device_registry` op area naam "cloudems exclude" (case-insensitive). Ondersteunt zowel device-level als entity-level area toewijzing.

## [4.0.0] - 2026-03-08

### Toegevoegd
- 🪟 Rolluiken module — volledige integratie met config flow, switch, sensor en dashboard tab
- 🌡️ ShutterThermalLearner — leert raamoriëntatie via temperatuur/zon correlatie
- 🔋 BatteryDecisionEngine basis in coordinator
- 📊 Systeem Status tabel tabelweergave gefixed
- 📋 Geleerde Voertuigprofielen tabel gefixed
- 🔍 Voertuigtype classificatie tabel gefixed
- ⚡ Batterij vermogen fix (kW → W conversie Zonneplan Nexus)
- 💾 Alle module-toggles persistent na herstart (Zonneplan auto-sturing, PV Forecast, NILM etc.)
- 🟢 Systeem Status kaart toont nu correct ✅/⭕ per module

### Gewijzigd
- `sensor.py`: module status flags lezen nu `_pv_forecast_enabled` en `_battery_sched_enabled` (was object check)
- `zonneplan_bridge.py`: power conversie fix voor kW sensoren (<50W drempel)
- `coordinator.py`: `_save_nilm_toggles` / `_load_nilm_toggles` uitgebreid met alle 16 module-toggles

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.0.0/).

## [3.5.5] - 2026-03-07

### Toegevoegd
- **Testmodus / Simulator** — activeer via `cloudems.simulator_set` met sliders voor net, PV, batterij, EPEX-prijs etc.
  - Auto-timeout (standaard 30 min, instelbaar via `timeout_min`)
  - Persistent notification in HA bij activatie met resterende tijd
  - Oranje banner bovenaan het dashboard zolang testmodus actief is, met "Stop" knop
  - `binary_sensor.cloudems_testmodus` — ON als simulator actief, attributen: `remaining_min`, `simulated_fields`, `overrides`
- **Leer-freeze** — alle 16 leermodules (NILM, baseline, EV-sessie, thermisch model, HP COP, dagclassificatie, apparaatdrift, capaciteitspiek, weekvergelijking, micro-mobiliteit, batterij SoC, sensor EMA, P1-direct) worden bevroren zolang de simulator actief is. Historische data en leermodellen worden nooit overschreven.

### Opgelost
- `log_reporter.py` — syntax error: unterminated string literal op r331 (`"\\n".join(lines)`)
- Simulator beïnvloedt nu geen historische data, leerprocessen of opgeslagen statistieken

---

## [3.2.1] — 2026-03-07

### Hotfix — Privacy correcties log_reporter

- Anonimisering: alleen IP-adressen en postcodes/coördinaten maskeren (was: ook entity IDs en energiewaarden)
- Sensor snapshot: exacte waarden (W, °C) in plaats van bandbreedtes — betere diagnostiek
- Boiler tabel uitgebreid: entity ID, exacte temperatuur, kWh/cyclus
- Token-logica: config flow token indien aanwezig, anders anoniem (GitHub publieke repo)
- Preview tekst gecorrigeerd

---

## [3.2.0] — 2026-03-07

### Log Reporter — automatische GitHub Issue uploads

#### log_reporter.py (nieuw — 425 regels)

Privacy-first diagnose-uploads bij kritieke fouten:

**Wat wordt geanonimiseerd:**
- Entity IDs vervangen door type-labels (`[sensor]`, `[cloudems_sensor]`)
- IP-adressen gemaskeerd als `[IP]`
- Energiewaarden weergegeven als bandbreedtes (bijv. `500–1000 W`)
- Geen locatie-informatie, geen persoonsnamen

**Wat er wél in zit:**
- HA-logs gefilterd op `cloudems` (laatste 200 regels)
- Guardian actieve issues (geanonimiseerd)
- Module-configuratie (welke modules actief, zonder waarden)
- CloudEMS versie + HA versie + Python versie
- Boiler-status als booleans (boven/onder setpoint, aan/uit)
- Capaciteitstarief waarschuwingsniveau

**Triggers:**
- Automatisch bij nieuwe kritieke Guardian-fouten (cooldown: 1 uur)
- Handmatig via HA-service `cloudems.upload_diagnostic_report`

**Cooldown:** maximaal 1 automatisch rapport per uur om spam te voorkomen

#### .github/workflows/analyse-auto-report.yml (nieuw)

GitHub Actions workflow die automatisch draait bij elk nieuw `auto-report` issue:

1. Claude analyseert het rapport (waarschijnlijke oorzaak, concrete stappen, code-aanbeveling)
2. Analyse wordt als comment geplaatst op het issue
3. Extra labels worden toegevoegd: `severity:critical/error/warning` + `module:boiler/ev/etc.`

Vereist: `ANTHROPIC_API_KEY` als GitHub repository secret

#### Config flow — Diagnostics stap (nieuw)

Nieuwe laatste wizard-stap met:
- `github_log_token`: GitHub PAT met `public_repo` scope
- `notification_service`: HA mobile app service naam voor push-meldingen

#### Guardian integratie
- LogReporter geïnitialiseerd in `async_setup()` als token aanwezig
- Auto-report getriggerd bij nieuwe kritieke issues in `_apply_actions()`

#### Coordinator
- `cloudems.upload_diagnostic_report` service geregistreerd in `__init__.py`

---

## [3.1.0] — 2026-03-07

### System Guardian — autonome bewakingsrobot

#### guardian.py (nieuw — 666 regels)

Vier bewakers die elke 60 seconden draaien:

**CoordinatorGuard** — stale data (>3 min oud), herhaalde crashes vanuit de watchdog, configuratiefouten uit de health check

**ModuleGuard** — boiler-cascades die niet opwarmen terwijl dat wel zou moeten, EV-lader unavailable, NILM zonder detectie

**SensorGuard** — kritieke sensoren (net, PV) ontbreken of leveren bevroren waarden. Boilertemperatuur stuck terwijl verwarmingselement aan is

**BoilerCascadeGuard** — anomalie-detectie (>2.5× normaal verbruik), leveringsboiler dreigt koud, seizoenswisseling notificatie

**Bijsturing (voorzichtig regime):**
- 2 faalcycli → notificatie via persistent_notification + push
- 3 faalcycli → HA integration reload
- 5 faalcycli → veilige stand (boilers uit, EV minimum)
- Module structureel defect → uitschakelen tot handmatige reset

**Rapportage:**
- `persistent_notification` bij elk nieuw issue
- Push via configureerbare `notification_service` voor warnings en hoger
- Weekrapport elke maandag 08:00 met overzicht crashes, boiler-energie, actieve issues

**Persistentie:** `/config/.storage/cloudems_guardian.json` — onthoudt uitgeschakelde modules en tijdstip weekrapport over HA-herstarts heen

#### Coordinator
- Guardian geïnitialiseerd in `async_setup()` na health check
- `async_evaluate()` aangeroepen elke update-cyclus (intern begrensd op 60s)
- `guardian` sleutel toegevoegd aan `self._data`

#### Dashboard
- **🤖 System Guardian** kaart in Diagnose tab: statusbadge, issue-tabel met level-kleuren, recent-opgeloste issues, veilige-stand indicator, weekrapport timestamp

---

## [3.0.0] — 2026-03-07

### Grote release — Netbeleid NL + Health Check + Documentatie

#### Capaciteitstarief Piekbewaker (capacity_peak.py v3.0)
- Automatische maandreset — geen handmatige reset meer nodig
- Eindpiek-projectie per kwartier op basis van lopend verloop
- Gerangschikte load-shedding acties met urgentieniveaus (advisory/soon/now)
- Sheddable loads parameter: EV + boiler vermogen meegegeven voor concreet advies
- 12-maanden piekhistoriek met indicatieve maandkosten (€4,37/kW, NL Liander)
- Headroom indicator: W beschikbaar zonder nieuwe maandpiek
- `cost_impact_eur`: geschatte kostenstijging als eindpiek boven drempel uitkomt

#### Grid Congestion Detector (grid_congestion.py)
- Capaciteitstarief-bewuste acties: al bij 80% utilisation advies (was 90%)
- Urgentieniveaus per actie (advisory/soon/now)
- Capaciteitstarief-waarschuwing bij 95%+ (nog geen congestie, maar piek-risico)

#### Setup Health Check (health_check.py v1.0 — nieuw)
- Controleert na setup alle geconfigureerde entiteiten in HA
- Drie categorieën: missing (bestaat niet), stale (unavailable/unknown), zero (verdachte waarde)
- Kritieke sensoren (grid, PV) geven 'error'; optionele sensoren 'warning'
- Boiler-units en fase-sensoren apart gecontroleerd
- Resultaat beschikbaar als `health_check` attribuut op `sensor.cloudems_watchdog`
- HA log-entry bij fouten/waarschuwingen na setup

#### Coordinator
- Capacity peak: `sheddable_loads_w` (EV + boiler) meegegeven aan `update()`
- Handmatige maandreset verwijderd (nu automatisch)
- Health check uitgevoerd aan einde van `async_setup()`

#### Dashboard
- **⚡ Kwartier-piek & Capaciteitstarief**: volledig herschreven met ASCII progress bar, projectie, headroom, load-shedding acties met urgentie-kleur, maandhistoriek tabel, kostenwaarschuwing
- **🏥 Setup Health Check**: nieuwe kaart in Diagnose tab met issues-tabel en suggesties per probleem

#### Documentatie
- README: boiler sectie volledig herschreven met alle v2.8/v2.9/v3.0 features
- Blogpost: *Capaciteitstarief in Nederland* — uitleg, rekenvoorbeelden, tarieven
- Blogpost: *Netcongestie in Nederland* — uitleg, verschil met capaciteitstarief, CloudEMS werking
- Blogpost: *Post-saldering 2027* — impact afbouw saldering, zelfconsumptie strategie, rekenvoorbeelden

---



### Boiler Controller v3.1 — Intelligent leren & optimalisaties

#### Backend
- **Dag-van-de-week patroon**: 7×24 gebruiksmatrix per cascade-groep; `should_preheat()` gebruikt nu weekdag-specifiek patroon vóór het globale 24-uurs patroon als fallback
- **Optimale opwarmtijd** (`optimal_start_before_minutes`): berekent het exacte starttijdstip zodat de boiler warm is vóór de verwachte vraag, in plaats van zo vroeg mogelijk te starten bij goedkope uren
- **Afwijkingsdetectie**: telt cycli per dag; stuurt HA persistent notification bij >2.5× normaal gebruik (mogelijke lekkage of logeerpartij)
- **Delta-T optimalisatie** (`delta_t_optimize: true`): verlaagt dynamisch het setpoint als de boiler ruim boven de comfort-grens zit (max −8°C); vermijdt onnodige warmte-overschotten
- **Post-saldering modus** (`post_saldering_mode: true`): verlaagt PV-surplus drempel naar 40% voor agressievere zelfconsumptie — voorbereiding op afschaffing saldering 2027
- **P1 directe respons** (`async_p1_update`): coordinator pusht elke P1-telegram (< 1s) naar boiler controller; effectief surplus combineert P1-meting met solar surplus
- **Weekbudget tracking**: `get_weekly_budget()` telt kWh per boiler per ISO-week; persistente in-memory opslag

#### Coordinator
- P1-telegram net_power_w wordt direct doorgestuurd naar `BoilerController.async_p1_update()`
- `boiler_weekly_budget` en `boiler_p1_active` toegevoegd aan coordinator data

#### Sensor
- `sensor.cloudems_boiler_status` heeft nu `weekly_budget` en `p1_direct_active` attributen

#### Dashboard
- **Nieuw: 📅 Gebruikspatroon per dag van de week**: 7-rijen heatmap met 7 tijdblokken per dag (ASCII bars)
- **Nieuw: ⏱️ Wanneer is het warm? + Optimal start**: tabel met opwarmtijd per boiler, optimal-start indicator en P1-direct badge
- **Nieuw: 💰 Warmwater energiebudget**: kWh-verbruik per boiler deze week, cycle_kwh live, post-saldering indicator

---



### Boiler Controller v3.0 — Volledig intelligent systeem

#### Backend (boiler_controller.py)
- **Persistente cycle_kwh**: kWh-teller per boiler overleeft HA-herstarts via `cloudems_boiler_learn.json`
- **Gebruikspatroon per uur**: exponentieel gewogen leermodel per uur van de dag (0-23) via `flow_sensor`; `should_preheat()` activeert cascade preventief vóór piekperiodes
- **Thermische verliescompensatie**: afkoelsnelheid (°C/u) per boiler geleerd via temperatuurhistorie; `time_until_cold()` berekent tijd tot comfort-grens
- **Vraaggestuurde prioriteit**: `flow_sensor` koppeling registreert warm-water-onttrekking per uur; leveringsboiler krijgt direct hogere prioriteit na gebruik
- **Seizoenspatroon**: automatische zomer/winter detectie op basis van buitentemperatuur met 3-daagse hysterese; seizoensspecifieke setpoints via `setpoint_summer_c` / `setpoint_winter_c`
- **Netcongestie koppeling**: bufferboilers worden uitgesteld bij congestie; leveringsboiler blijft warm voor comfort
- **Proportionele dimmer sturing**: `dimmer_proportional: true` schakelt PV-surplus-proportioneel dimmen in (5%-stappen, max update elke 30s)

#### Dashboard
- **Cascade groepen kaart**: uitgebreid met seizoen-status, "Tot Koud" kolom (minuten/uren) en thermisch verlies (°C/u) per boiler
- **Nieuw: 📊 Gebruikspatroon per uur**: ASCII-bar visualisatie van warmwatergebruik per uur op basis van flow-sensor leerdata
- **Nieuw: 🌡️ Thermisch verlies & voorspelling**: tabel met verliescoëfficiënt, confidence, kWh per cyclus en tijd tot comfort-grens per boiler
- **Nieuw: 🔌 Dimmer & proportionele sturing**: statusoverzicht van dimmer-gestuurde boilers inclusief proportioneel-modus indicator

---

## [2.4.0] — 2026-03-06

### Bugfix — Dashboard "Entiteit niet gevonden" reparaties

- **`sensor.cloudems_energy_cost`**: sensor heette `CloudEMS Kosten Vandaag` (→ `kosten_vandaag`), dashboard verwachtte `energy_cost`. Naam gecorrigeerd naar `CloudEMS Energy Cost` + expliciete `entity_id` override.
- **`sensor.cloudems_flexibel_vermogen`**: sensor heette `CloudEMS Flex Score` (→ `flex_score`), dashboard verwachtte `flexibel_vermogen`. Naam gecorrigeerd + entity_id override.
- **`sensor.cloudems_warmtepomp_cop`**: sensor ontbrak volledig in de entity-registratie. Nieuwe `CloudEMSWarmtepompCOPSensor` klasse toegevoegd met COP-waarden, degradatiedetectie en alle dashboard-attributen (`cop_report`, `degradation_detected`, `degradation_pct`, `degradation_advice`, `cop_at_7c`).
- **`coordinator.py`**: `hp_cop_data` aangevuld met `degradation_detected`, `degradation_pct` en `degradation_advice` uit `COPReport`.

---

## [2.4.1] — 2026-03-06

### Bugfix
- `sensor.cloudems_battery_soc`: entity_id mismatch opgelost — sensor heette "Battery · State of Charge" → genereerde `sensor.cloudems_battery_state_of_charge`, dashboard verwachtte `sensor.cloudems_battery_soc`. Hernoemd naar "Battery · SoC".
- `sensor.cloudems_p1_power`: entity_id mismatch opgelost — sensor heette "Grid · P1 Net Power" → genereerde `sensor.cloudems_grid_p1_net_power`, dashboard verwachtte `sensor.cloudems_p1_power`. Hernoemd naar "CloudEMS P1 Power".
- `sensor.cloudems_nilm_diagnostics`, `sensor.cloudems_nilm_sensor_input`, `sensor.cloudems_nilm_devices`, `sensor.cloudems_nilm_running_devices`, `sensor.cloudems_nilm_running_devices_power`, `sensor.cloudems_ai_status`, `sensor.cloudems_nilm_hybride_status`: expliciete `entity_id` override toegevoegd om te garanderen dat de entiteit-ID overeenkomt met het dashboard, ongeacht eerder in het HA entity registry opgeslagen waarden.

---



### Bugfix
- `MicroMobilityTracker`: attribuut `_last_seen` ontbrak in `__init__` → `AttributeError` opgelost

---

## [2.2.0] — 2026-03-06

### Toegevoegd
- **Watchdog** (`watchdog.py`): bewaakt de coordinator op herhaalde crashes
  - Na 3 opeenvolgende `UpdateFailed` errors → automatische reload van de config entry
  - Exponential backoff: 30s → 60s → ... max 1 uur tussen herstarts
  - Crashgeschiedenis persistent opgeslagen in HA storage
  - `sensor.cloudems_watchdog` met status `ok` / `warning` / `critical`
  - Watchdog-kaart op het Diagnose tabblad: teller, foutmelding, crashhistorie

---

## [2.1.9] — 2026-03-06

### Bugfix
- `CloudEMSNILMDeviceSensor`: `extra_state_attributes` miste `@property` decorator → `TypeError: 'method' object is not iterable` bij toevoegen van NILM-entiteiten opgelost
- `_source_type`: ongeldige `@property` + `@staticmethod` combinatie verwijderd

---

## [2.1.8] — 2026-03-06

### Gewijzigd — NILM detectie minder streng, false positives worden actief verwijderd
- `NILM_MIN_CONFIDENCE`: 0.80 → **0.55** — meer apparaten zichtbaar (ook twijfelgevallen)
- `NILM_HIGH_CONFIDENCE`: 0.92 → **0.80** — eerder tonen zonder extra AI-bevestiging
- `STEADY_STATE_DELAY_S`: 35s → **20s** — snellere false positive detectie
- `STEADY_STATE_MIN_RATIO`: 0.50 → **0.40** — soepelere steady-state validatie
- Onbevestigde false positives worden nu **actief verwijderd** (was: confidence halveren)
- Bevestigde apparaten bij validatie-fail: confidence × 0.65 (was: × 0.50), blijven staan

---

## [2.1.7] — 2026-03-05

### Toegevoegd
- 9 nieuwe dashboardkaarten voor sensoren die nog geen dashboard-representatie hadden:
  - 🏠 Aanwezigheidsdetector (`sensor.cloudems_absence_detector`)
  - 🌡️ Slim Voorverwarmen (`sensor.cloudems_climate_preheat`)
  - ⏰ Goedkoopste 4-uurs Blok (`sensor.cloudems_cheapest_4h_block`)
  - 🛡️ Sensor Kwaliteitscheck (`sensor.cloudems_sensor_sanity`)
  - 🎯 PV Voorspelling Nauwkeurigheid (`sensor.cloudems_pv_forecast_accuracy`)
  - 💰 PV Opbrengst & Terugverdientijd (`sensor.cloudems_pv_opbrengst_terugverdientijd`)
  - 📊 EMA Sensor Diagnostiek (`sensor.cloudems_ema_diagnostics`)
  - 🗄️ NILM Database Status (`sensor.cloudems_nilm_db`)
  - 📡 P1 Direct Netmeting (`sensor.cloudems_p1_power`)
- NILM Live Activiteit monitor op NILM Beheer tabblad
- Dashboard footers gestandaardiseerd: één gecombineerde footer per tab, altijd als laatste kaart

### Bugfix
- Micro-mobiliteit voertuigprofielen tabel: ruwe dict-dump vervangen door opgemaakte markdown tabel
- Flexibel Vermogen Score: Jinja whitespace bugfix in tabel-rendering (`{%- for %}`)

---

## [2.1.6] — eerder

### Toegevoegd
- Multi-omvormer ondersteuning uitgebreid
- Solar power sommering voor modules zonder CONF_SOLAR_SENSOR
- Diverse NILM en energiebeheer verbeteringen
