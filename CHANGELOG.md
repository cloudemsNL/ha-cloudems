# CloudEMS Changelog

## v5.3.60 (2026-03-26)
- Fix (root cause): sensor.cloudems_self_consumption en andere sensoren ontbraken doordat ze in HA's entity_registry gekoppeld waren aan een oud config_entry_id. HA weigert herregistratie dan stil — sensor verschijnt nooit. sensor_diagnostics v1.3 detecteert en verwijdert deze orphaned entries automatisch, na een herstart registreert de sensor opnieuw correct
- Fix: self-healing card prijs 0ct — las price sensor state als 0 of NaN zonder te vallen op attributen. Nu: state → price_incl_tax attribuut → 0
- Fix: versie kaart lege velden, self-healing card solar, standby_intelligence DB-spam (zie v5.3.58/59)

## v5.3.59 (2026-03-26)
- Uitgebreid: card_output_watcher v2.0 — elke 5 minuten kaart-snapshot in HA logs met solar/grid/huis/accu/prijs/zelfconsumptie. Problemen zijn nu direct leesbaar in de logs zonder screenshots
- Uitgebreid: checks toegevoegd voor self-healing card solar, prijs, PV forecast, coordinator performance
- Fix: self-healing card 0W solar — las sensor.cloudems_solar_system (leeg bij herstart), nu sensor.cloudems_zon_vermogen
- Fix: sensor.cloudems_standby_intelligence publiceerde heel coordinator.data — DB-spam elke 30s
- Fix: versie kaart lege velden — sleutelnamen gecorrigeerd naar wd.watchdog.total_restarts, wd.performance.avg_ms
- Fix: performance subdict toegevoegd aan sensor.cloudems_watchdog attributes
- Fix: sensor_diagnostics module — nu alleen sensoren met expliciete entity_id

## v5.3.58 (2026-03-26)
- Fix: self-healing card toonde 0W solar — las sensor.cloudems_solar_system (leeg bij herstart), nu sensor.cloudems_zon_vermogen (zelfde bron als sankey kaart)
- Fix: self-healing card re-renderde niet bij solar update — signature miste solar sensor state
- Fix: sensor.cloudems_standby_intelligence publiceerde héél coordinator.data (~50KB) → DB-spam elke 30s. Nu alleen standby_intelligence subdict
- Fix: versie kaart toonde streepjes — sleutelnamen update_cycles/errors_total/restart_count/cycle_ms bestonden niet. Nu wd.watchdog.total_restarts, wd.watchdog.total_failures, wd.performance.avg_ms
- Fix: performance subdict toegevoegd aan sensor.cloudems_watchdog attributes zodat cyclustijd zichtbaar is
- Fix: sensor_diagnostics module had verkeerde entity_ids (pv_forecast_today, p1_power) — nu alleen sensoren met expliciete entity_id

## v5.3.57 (2026-03-26)
- Fix: sensor.cloudems_ai_status dubbel geregistreerd (CloudEMSAIStatusSensor + CloudEMSAISensor met zelfde entity_id/unique_id) — tweede verwijderd, eerste uitgebreid met k-NN attributen (n_trained, buffer_size, model_version, ready)
- Fix: CloudEMSStandbyIntelligenceSensor had dubbele __init__ — samengevoegd
- Nieuw: sensor_diagnostics.py — controleert bij elke opstarten welke kritieke sensoren ontbreken of disabled zijn, re-enablet automatisch door HA uitgeschakelde sensoren (niet user-disabled), logt conflicten

## v5.3.3 (2026-03-24)
- Feature: aanwezigheidsdetectie wizard-stap toegevoegd (async_step_presence)
- Auto-detectie van person.*, device_tracker.* en binary_sensor presence/occupancy/motion werkte al
- Nieuw: gebruiker kan extra Hue/Zigbee/PIR sensoren toevoegen via de wizard
- Extra sensoren worden als manual_overrides doorgegeven aan ZonePresenceManager
- Translations NL/EN/DE/FR toegevoegd voor de nieuwe stap

## v5.3.3 (2026-03-24)
- Feature: bewegingssensoren aanwezigheidsdetectie (issue #43)
  - Auto-detectie van binary_sensor motion/occupancy/presence via ZonePresenceDetector (was al aanwezig)
  - CONF_PRESENCE_ENTITIES en CONF_PRESENCE_CALENDAR constants toegevoegd
  - Onboarding hint: als bewegingssensoren aanwezig maar niet geconfigureerd → melding in dashboard
  - Config flow stap presence was al aanwezig en volledig werkend

## v5.3.2 (2026-03-24)
- Fix: HAEntityFallbackReader las geen per-fase data (L1/L2/L3 altijd 0W in P1 kaart)
- Toegevoegd: per-fase import/export vermogen en stroom in _PATTERNS en keyword_map pass 3
- Toegevoegd: per-fase velden worden nu ingevuld in P1Telegram via HAEntityFallbackReader

## v5.3.1 (2026-03-24)
- Fix: HAEntityFallbackReader dubbele x1000 conversie — unit=kW deed x1000 en scale=1000 deed nogmaals x1000, resultaat 1000x te hoog
- Fix: unit=W sensoren worden nu correct doorgelaten zonder extra conversie

## v5.3.0 (2026-03-24)
- Fix: flow card toonde corrupte grid-waarde (>50 kW) als sensor.cloudems_grid_net_power stale data had
- Fallback: als grid > 50kW, bereken grid uit fase-data van sensor.cloudems_status (altijd actief en correct)

## v5.2.9 (2026-03-24)
- Revert: CloudEMSGridNetPowerSensor registratie ongedaan gemaakt — veroorzaakte dubbele entiteit en las corrupte P1 data

## v5.2.8 (2026-03-24)
- Fix: CloudEMSGridNetPowerSensor weer geregistreerd in sensor.py — was verwijderd in v4.6.x maar de flow card en dashboard verwijzen ernaar
- Revert: sensor.cloudems_power terug naar sensor.cloudems_grid_net_power in YAML en JS
- Revert: kW-conversie fix niet nodig want sensor levert W direct

## v5.2.7 (2026-03-24)
- Fix: flow card toonde x1000 te hoge waarden voor sensor.cloudems_* sensoren — HA converteert device_class:power sensoren automatisch van W naar kW in de state, _getVal deed daarna nogmaals x1000. CloudEMS-eigen sensoren worden nu niet meer dubbel geconverteerd.

## v5.2.6 (2026-03-24)
- Fix: flow card en dashboard YAML verwezen naar sensor.cloudems_grid_net_power — deze sensor is al lange tijd niet geregistreerd (verwijderd in v4.6.x). Vervangen door sensor.cloudems_power (CloudEMSPowerSensor, de actieve grid power sensor)

## v5.2.5 (2026-03-24)
- Fix: cloudems-overview-card verwijderd uit Overzicht-tab dashboard YAML — kaart is vervangen en hoort er niet thuis

## v5.2.4b (2026-03-24)
- Fix: cloudems-overview-card werd niet geregistreerd als custom element → Configuratiefout in rechterkolom
- CloudemsOverviewCard staat in de bundel maar was uitgecommentarieerd in de CARDS-registratie

## v5.2.4 (2026-03-24)
- Revert: _getVal kW-conversie teruggezet naar origineel (v4.6.617 gedrag) — fix was onnodig en onjuist
- Fix: laatste onguarded customElements.define in cloudems-cards.js (cloudems-graph-card-editor) voorzien van guard
- Fix: SUB_CLIMATE NameError in sensor.py → vervangen door SUB_ZONE_CLIMATE

## v5.2.3 (2026-03-24)
- Fix: flow card toonde belachelijk hoog grid vermogen (bijv. 322 kW) — HA converteert sensor.cloudems_ eenheden automatisch naar kW via energy dashboard instellingen, _getVal deed daarna nogmaals × 1000. CloudEMS-eigen sensoren worden nu niet meer dubbel geconverteerd.

## v5.2.2 (2026-03-24)
- Fix: getCardSize() toegevoegd aan cloudems-rooms-card (ontbrak) en cloudems-home-card (ontbrak)
- HA roept getCardSize() aan voor sectie-layout berekening — ontbrekende methode veroorzaakt hui-grid-section crash en verdwijnende rechterkolom

## v5.2.1 (2026-03-24)
- Cleanup: cloudems-cards.backup-pre-phase.js definitief verwijderd uit de codebase en LOVELACE_CARDS_BACKUP_URL constante verwijderd uit __init__.py

## v5.2.0 (2026-03-24)
- Fix: cloudems-cards.backup-pre-phase.js toegevoegd aan always-remove stale lijst in __init__.py
- Root cause van oude 1-fase kaart zelfs in private window: backup bestand was nog geregistreerd als Lovelace resource en bevat onguarded cloudems-flow-card v3.0 definitie die de nieuwe kaart overschreef

## v5.1.9 (2026-03-24)
- Fix: if(!customElements.get()) guard toegevoegd aan ALLE 56 losse JS-kaartbestanden
- Root cause van Configuratiefout + verdwijnende kolom: dubbele customElements.define gooit DOMException bij herlaad of dubbele resource-registratie

## v5.1.8 (2026-03-24)
- Fix: cloudems-flow-card.js stub wordt nu altijd verwijderd uit HA Lovelace resource-storage bij herstart, ongeacht versienummer

## v5.1.7 (2026-03-24)
- Fix: cloudems-flow-card.js stub volledig leeggemaakt (geen code meer) — browser-cache van de stub kon de oude 1-fase kaart nog laden

## v5.1.6 (2026-03-24)
- Fix: cloudems-flow-card.js stub werd niet opgeruimd uit Lovelace resource-registratie na verwijdering uit _ALL_JS_RESOURCES — oude kaart bleef laden
- Fix: "cloudems-flow-card.js" toegevoegd aan stale cleanup keywords zodat de oude resource-registratie bij HA-herstart verwijderd wordt

## v5.1.5 (2026-03-24)
- Fix: cloudems-flow-card.js stub verwijderd uit Lovelace resource-registratie — veroorzaakte race condition (soms 1-fase, soms 3-fase kaart afhankelijk van laadvolgorde)
- Root cause: in v4.6.x bestond de stub niet, flow card werd uitsluitend via cloudems-cards.js geladen

## v5.1.4 (2026-03-24)
- Fix: flow card teruggezet in cloudems-cards.js bundel (extractie als standalone veroorzaakte 1/3-fase wisselprobleem)
- Fix: debounce in flow card hass setter correct geïmplementeerd via last_updated van status sensor en primaire sensorwaarden
- Fix: cloudems-flow-card.js terug als stub

## v5.1.3 (2026-03-24)
- Fix: cloudems-flow-card losgekoppeld uit cloudems-cards.js bundel naar eigen standalone bestand
- Fix: foutieve debounce in flow card hass setter teruggedraaid (veroorzaakte single-phase weergave)
- Fix: CloudemsFlowCard niet meer geregistreerd in de bundel (dubbele registratie opgelost)

## v5.1.2 (2026-03-24)
- Fix: cloudems-flow-card renderde bij elke hass state update → debounce toegevoegd op relevante sensoren
- Fix: hui-grid-section layout crash (rechterkolom verdwijnt) veroorzaakt door onnodige DOM-vervanging in flow card
- Fix: trage bolletjesanimatie flow card — _renderFull werd te frequent getriggerd

## v5.1.1 (2026-03-24)
- Fix: YAMLException "non-printable characters" bij laden dashboard — 22 Unicode variation selectors (U+FE0F) verwijderd uit cloudems-dashboard.yaml, 1 uit cloudems-dashboard-dev.yaml

## v5.1.0 (2026-03-24)
- Fix: rechterkolom Overzicht-tab viel weg / werd niet weergegeven op mobiel
  - `cloudems-mini-price-card` verplaatst van ongeldig `cards:` blok op view-niveau naar sectie 1
  - `cards:` key op view-niveau verwijderd (niet geldig in `type: sections` views)
- Fix: "Configuratiefout" op Overzicht-tab door conflicterende JS-registraties
  - `cloudems-cards.backup-pre-phase.js` verwijderd uit `_ALL_JS_RESOURCES` (laadde altijd mee en conflicteerde met `cloudems-cards.js`)
  - `cloudems-graph-card-editor`, `cloudems-flow-card`, `cloudems-flow-card-editor` voorzien van `if (!customElements.get(...))` guard in `cloudems-cards.js`
- Fix: `_ALL_JS_RESOURCES` opgeschoond — duplicaten verwijderd (10+ bestanden waren 2-3× geregistreerd)

## v5.0.28 (2026-03-23)
- Fix: `translations/de.json` stap `onboarding_redirect` ontbrak

## v5.0.27 (2026-03-23)
- Fix: `cloudems-klimaat-card.js`, `cloudems-lamp-card.js` en `cloudems-lamp-auto-card.js` niet geregistreerd in `__init__.py`

## v5.0.26 (2026-03-23)
- Bump JS card versies na wijzigingen (p1-card v1.1.0, zelfconsumptie-card v1.1, diagnose-card v1.1.0)

## v5.0.25 (2026-03-23)
- Fix: Zelfconsumptie kaart toonde "Nog geen data" bij ratio 0% (bijv. bewolkt, ochtend)

## v5.0.24 (2026-03-23)
- Fix: Diagnose kaart fase details (L1/L2/L3 stroom, spanning, vermogen) toonden 0.0
- Fix: "Net & Fasen sensor: Niet gevonden" verdwenen — kaart kijkt nu naar juiste sensor
- Fix: Piekschavinglimiet correct uitgelezen

## v5.0.23 (2026-03-23)
- Fix: Alle 107 config flow stappen hebben nu volledige labels in nl/en/de/fr (0 ontbrekend)
- Toegevoegd: labels voor multisplit, EV, e-bike, klimaat, boiler, rolluiken, zwembad, etc.

## v5.0.22 (2026-03-23)
- Fix: P1 melding toont nu "P1 data actief via DSMR/HomeWizard integratie" i.p.v. foutmelding
- Fix: `p1_data["source"]` veld toegevoegd zodat kaart juiste bron toont
- Fix: `P1Reader` krijgt nu `hass` mee zodat HAEntityFallbackReader werkt

## v5.0.21 (2026-03-23)
- Fix: `CONF_MULTISPLIT_GROUPS` en `MULTISPLIT_BRANDS` ontbraken in `const.py` → "Unknown error" bij Airco/Multisplit opgelost

## v5.0.19 (2026-03-23)
- Herstel: 19 ontbrekende `energy_manager` bestanden terug (fronius, evcc, saldering, demand_response, hybrid_ev_advisor, ned_national_grid, co2_footprint, wallbox_provider, nrgkick, etc.)
- Herstel: `nilm_group_tracker.py`
- Fix: multisplit dropdown 0-99 i.p.v. bolletjeslijst

## v5.0.18 (2026-03-23)
- Herstel: `multisplit_manager.py` en alle multisplit flow stappen terug uit v5.0.6
- Fix: `CONF_MULTISPLIT_GROUPS` / `MULTISPLIT_BRANDS` in `const.py`

## v5.0.17 (2026-03-23)
- Fix: EV flow — menu → `ev_opts` (dropdown 0-99) → per laadpaal detail
- Fix: E-bike flow — menu → `ebike_count` (dropdown) → per voertuig detail
- Fix: `back_to_menu` labels correct in alle stappen

## v5.0.16 (2026-03-23)
- Fix: EV laadpaal label en translations

## v5.0.15 (2026-03-23)
- Feature: Multi-EV laadpaal configuratie (meerdere laadpalen via wizard)

## v5.0.9 (2026-03-23)
- Fix: `CapacityPeakMonitor.get_status()` ontbrak → coordinator crash bij `learning_frozen=True`
- Fix: `BatteryBenchmarkReporter.get_status()` ontbrak → `AttributeError`
- Fix: `FuelPriceFetcher._diesel_eur_l` property/setter conflict → `AttributeError`

## v5.3.4 (2026-03-25)
- Prio 2 stap 1 AI: OutcomeTracker parallel aan DecisionOutcomeLearner geactiveerd
  - OutcomeTracker geïnstantieerd in coordinator
  - _record_decision_dual() helper — stuurt alle 6 record_decision aanroepen naar beide systemen
  - OutcomeTracker.tick() in elke coordinator cyclus
  - OutcomeTracker stats gepubliceerd in coordinator data
- Prio 3 Tooltips:
  - battery-card: BDE drempels (laad/ontlaad/saldering) toegevoegd aan BDE beslissing tooltip
  - BDE: _last_charge_thr, _last_discharge_thr, _last_nm_pct opgeslagen na elke evaluate()
  - diagnose-card: DSMR-type, geleerde vertraging, betrouwbaarheid, lag-compensatie nu met tooltip
  - nilm-card: elke apparaatrij heeft nu tooltip met betrouwbaarheid, detectiemethode, fase, kamer

## v5.3.5 (2026-03-25)
- Fix: flow card las sensor.cloudems_p1_data (bestaat niet) i.p.v. sensor.cloudems_p1_power → fase-vermogens en bolletjesrichting nu correct
- Fix: HAEntityFallbackReader gaf current_l1/l2/l3 = 0.0 door als stroom-entiteit 0 levert maar fase-vermogen wel beschikbaar is → nu berekend als I = P/U (230V), of None als beide 0 zijn zodat fusie-model ze negeert

## v5.3.6 (2026-03-25)
- Fix KRITIEK: UnboundLocalError _selfcons_pct — coordinator crashte elke cyclus omdat _selfcons_pct op regel 6125 gebruikt werd maar pas op regel 8634 gedefinieerd wordt. Fix: locals().get("_selfcons_pct", 0.0) als fallback.

## v5.3.7 (2026-03-25)
- Fix: bolletjesrichting flow card — fase-richting (import/export) toegevoegd aan sig hash zodat een flip grid→hub / hub→grid direct een full render triggert ipv te wachten op de 30-tick debounce

## v5.3.8 (2026-03-25)
- Fix: flow card las power_l1_w/l2_w/l3_w maar coordinator slaat dit op als power_l1_import_w/l2_import_w/l3_import_w — alle fase-richtingen waren altijd null → vielen terug op limiter waarden → bolletjes gingen altijd van hub naar buiten

## v5.3.9 (2026-03-25)
- Fix KRITIEK: _selfcons_pct UnboundLocalError — de locals().get() fix in v5.3.6 werkte niet omdat Python de variabele als lokaal markeert in de hele functie. Echte fix: _selfcons_pct = 0.0 initialiseren aan het begin van _async_update_data.

## v5.3.10 (2026-03-25)
- Fix: flow card grid-node toonde waarde van stale sensor.cloudems_grid_net_power (0W/1W) — nu sensor.cloudems_p1_power.net_power_w gebruikt als die beschikbaar is

## v5.3.11 (2026-03-25)
- Fix: CloudEMSGridNetPowerSensor opnieuw geregistreerd in sensor.py — leest p1_data.net_power_w met fallback naar grid_power. Alle kaarten lezen nu sensor.cloudems_grid_net_power zonder per-kaart fallbacks.
- Cleanup: flow card p1 net_power_w fallback-hack verwijderd

## v5.3.12 (2026-03-25)
- Fix: bolletjesrichting flow card gebruikt nu limiter power_w (sensor.cloudems_status.attributes.phases) — zelfde bron als piekschaving kaart. Eerder werden P1 per-fase waarden gebruikt die konden afwijken van de limiter.

## v5.3.13 (2026-03-25)
- Architectuur: kaart-niveau logica verplaatst naar backend
  - sensor.cloudems_grid_net_power publiceert nu power_l1_net_w/l2/l3, current_l1/l2/l3, alle p1 fase-data
  - Sanity check (>50kW corrupt) verplaatst van flow card naar sensor.py native_value
  - flow card: _signedA, dubbele sensor-fallbacks en _p1a verwijderd
  - home card: _signedA() functie en dubbele sensor-namen vervangen door backend attributen
  - p1 card: l1net berekening vervangen door backend power_l1_net_w attribuut

## v5.3.14 (2026-03-25)
- Fix: sensor.cloudems_grid_net_power_2 dubbele entity — CloudEMSGridNetPowerSensor niet meer geregistreerd, CloudEMSPowerSensor (unique_id _power, entity_id cloudems_grid_net_power) krijgt nu alle benodigde attributen (power_l1_net_w etc.) en P1 prioriteit in native_value
- Fix: 51A corrupt stroom — limiter negeert stroomwaarden > 3× max_ampere
- Fix: HAEntityFallbackReader negeert stroomwaarden > 100A
- Fix: fase-balans-card gebruikt nu sensor.cloudems_status.phases (backend)

## v5.3.15 (2026-03-25)
- Fix: sensor.cloudems_grid_net_power bestond niet meer na verwijdering CloudEMSGridNetPowerSensor
- Alle kaarten, dashboard YAML en HTML lezen nu sensor.cloudems_power (CloudEMSPowerSensor, unique_id _power, de actieve sensor)

## v5.3.16 (2026-03-25)
- Fix: flow card valt terug op sensor.cloudems_power als geconfigureerde grid-entity niet bestaat in HA (migratie van sensor.cloudems_grid_net_power naar sensor.cloudems_power)

## v5.3.17 (2026-03-25)
- Revert v5.3.16 fallback-truc — niet nodig: dashboard YAML wordt bij elke herstart overschreven via _do_storage_work, sensor.cloudems_power staat al in de YAML

## v5.3.18 (2026-03-25)
- Fix: CloudEMSPowerSensor native_value teruggebracht naar origineel — leest power_w uit coordinator data. P1 net_power_w logica veroorzaakte 0W weergave in flow card.

## v5.3.19 (2026-03-25)
- Fix: eenmalige migratie in _do_storage_work — vervangt sensor.cloudems_grid_net_power door sensor.cloudems_power in alle opgeslagen Lovelace configs bij elke herstart
- Versie-bump: alle JS kaarten gebumpt naar 5.3.19

## v5.3.20 (2026-03-25)
- CLAUDE_INSTRUCTIONS bijgewerkt met volledige bump-verplichting
- Backup versie voor Joan

## v5.3.21 (2026-03-25)
- Fix: flow card gebruikt nu sensor.cloudems_grid_import_power en sensor.cloudems_grid_export_power voor grid waarde — zelfde sensoren als overview kaart, bestaan altijd in elke installatie

## v5.3.22 (2026-03-25)
- Revert: alles terug naar sensor.cloudems_grid_net_power — die sensor bestaat en werkt in alle installaties. De migratie naar sensor.cloudems_power was fout.

## v5.3.23 (2026-03-25)
- Fix dashboard: dubbele kaarten verwijderd uit alle tabs
  - Solar: pv-forecast-card dubbel
  - Batterij: batterij-levensduur-card dubbel, batterij-arbitrage-card dubbel
  - EV: ev-trip-card dubbel
  - Klimaat: climate-epex-card dubbel
  - Lampen: lamp-auto-card dubbel
  - NILM: nilm-visual-card dubbel, apparaat-tijdlijn-card dubbel
  - Zelflerend: fase-balans-card dubbel
  - Prijzen: prijsverloop-card (legacy) en mini-price-card verwijderd (3 prijskaarten → 1)

## v5.3.24 (2026-03-25)
- Fix: sensor.cloudems_status publiceert nu grid_power_w, import_power_w, export_power_w
- Fix: flow card leest grid_power_w van sensor.cloudems_status — werkt in elke installatie ongeacht entity_id van andere sensoren

## v5.3.25 (2026-03-25)
- Nieuw: tests/test_integration.py — herbruikbare test suite voor kritieke integratiepunten
- Fix: sanity check stroom — 51A bij 770W wordt nu correct als corrupt herkend (was: grens 100A te hoog)
  Nieuwe logica: als stroom > 5x verwacht (P/U) dan corrupt → reset naar 0 → berekend als I=P/U
- Tests: 22/22 geslaagd

## v5.3.26 (2026-03-25)
- Fix: zelfconsumptie altijd 0% — battery_power stond niet in data dict, dus batterij-ontlading werd niet afgetrokken van export. Fix: _last_battery_w gebruiken.
- Tests: 23/23 geslaagd

## v5.3.27 (2026-03-25)
- Test suite uitgebreid: OutcomeTracker, DecisionOutcomeLearner bias, AI samples, energiebalans
- Tests: 32/32 geslaagd

## v5.3.27 (2026-03-25)
- Uitgebreide test suite: 40 tests voor P1, stroom sanity, status sensor, fase richting, zelfconsumptie, BDE, OutcomeTracker, Limiter, PowerCalculator, SelfConsumptionTracker, BatteryDecisionEngine, aanwezigheid, Kirchhoff
- Alle 40 tests geslaagd

## v5.3.28 (2026-03-25)
- Nieuw: tests/test_real_modules.py — draait echte modules zonder HA (26 tests, 0 mislukt)
- Nieuw: tests/mock_homeassistant.py — HA mock voor tests
- Fix: 37 JS kaarten hadden geen versienummer — versieconstant toegevoegd aan alle kaarten
- Fix: cloudems-p1-card.js lazen nog import-export berekening — nu via sensor.cloudems_status.phases

## v5.3.28 (2026-03-25)
- Fix: p1-card import-export berekening verwijderd — leest nu sensor.cloudems_status.phases[L1].power_w
- Nieuw: tests/test_real_modules.py — 26 echte module tests zonder HA installatie
- Nieuw: tests/mock_ha.py — volledige MockHA omgeving voor end-to-end tests
- Totaal: 66 tests, 0 mislukt

## v5.3.29 (2026-03-25)
- Fix: bolletjes richting omgekeerd bij import — _gridL1w/L2w/L3w lazen sensor.cloudems_grid_net_power.power_l1_net_w (was 0, niet null) → verkeerde richting. Terug naar sensor.cloudems_status.phases[L1].power_w — altijd correct.

## v5.3.30 (2026-03-25)
- Fix: fase-bolletjes richting — gebruikt nu current_a (zelfde bron als piekschaving): positief=import=grid→hub, negatief=export=hub→grid

## v5.3.31 (2026-03-25)
- Fix: lokale AI 0 samples — _record_decision_dual riep zichzelf recursief aan (oneindige lus) → nooit samples doorgestuurd. Nu roept het _decision_learner.record() correct aan.
- Fix: zelfconsumptie data verloren na herstart — _today_date was leeg bij korte sessies waardoor save een lege datum opslaat. Nu altijd geïnitialiseerd bij async_setup.

## v5.3.31 (2026-03-25)
- Fix: NILM ankers altijd alle 5 zichtbaar (?, L1, L2, L3, Σ) op vaste gelijkmatige posities
- Fix: NILM devices verdeeld onder hun eigen anker zonder overlap
- Fix: bolletjes op THUIS→anker lijnen voor actieve apparaten

## v5.3.32 (2026-03-25)
- Fix: cloudems-gas-card en cloudems-config-card kapot door versie-bump die VERSION const binnen class plaatste ipv ervoor
- Alle JS kaarten syntax-gecontroleerd: 0 fouten

## v5.3.33 (2026-03-25)
- Verwijderd: cloudems-prijsverloop-card.js — legacy kaart vervangen door cloudems-price-card
- Registratie en bestand volledig verwijderd zodat de oude kaart niet meer verschijnt

## v5.3.34 (2026-03-25)
- Hersteld: cloudems-prijsverloop-card terug — was per ongeluk verwijderd
- Prijzen tab gebruikt nu weer cloudems-prijsverloop-card

## v5.3.35 (2026-03-25)
- Verwijderd: cloudems-price-card.js — cloudems-prijsverloop-card is de correcte prijskaart

## v5.3.36 (2026-03-25)
- Dashboard: cloudems-energy-visual-card toegevoegd aan NILM tab
- Dashboard: cloudems-energy-visual-card en cloudems-overview-card toegevoegd aan Configuratie tab (was onderhoud)
- Dashboard: cloudems-beheer-card verwijderd uit Configuratie tab (toonde al "vervangen" melding)

## v5.3.37 (2026-03-25)
- Dashboard: mini-price-card als eerste kaart op alle tabs (behalve Prijzen & Kosten)
- Dashboard: version-card als laatste kaart op alle 17 tabs

## v5.3.38 (2026-03-25)
- Dashboard: alle 17 tabs op max_columns: 2 — consistente 2-koloms layout overal

## v5.3.38 (2026-03-26)
- Fix AI: n_since_train en buffer worden nu opgeslagen en hersteld na herstart
- Fix AI: RETRAIN_INTERVAL verlaagd van 144 naar 48 — eerste training na ~8 minuten
- Fix AI: battery_soc/solar_power/battery_power sleutels met _w fallback in _build_features
- Fix AI: buffer periodiek opgeslagen (elke 60 samples) zodat data niet verloren gaat bij crash

## v5.3.39 (2026-03-26)
- Fix: dubbele shutdown logs — coordinator._shutdown_done guard voorkomt 2x uitvoering
- CLAUDE_INSTRUCTIONS: dashboard kaart volgorde (mini-price eerst, version laatst) vastgelegd

## v5.3.39 (2026-03-26)
- Fix: flow card verdwijnt niet meer na errors — animatieloop herstart zichzelf na 5s ipv permanent te stoppen

## v5.3.40 (2026-03-26)
- AI refactor stap 2: DOL.record() verwijderd uit _record_decision_dual
- OutcomeTracker is nu de enige recorder voor beslissingen
- DOL blijft actief voor apply_bias_to_threshold() (BDE + ShutterController)

## v5.3.41 (2026-03-26)
- Dashboard: alle 17 tabs nu 2 kolommen (links=hoofd, rechts=ondersteunend)
- Dashboard: mini-price eerste, version-card laatste op alle tabs gecontroleerd

## v5.3.42 (2026-03-26)
- Nieuw: Wasmachine Finish-at Predictor
  - Bij klaar-notificatie: EPEX droger-advies (nu vs goedkoopste uur komende 6 uur)
  - Slijtage-detector: aanloopstroom gemonitord per cyclus, waarschuwing bij >20% afwijking
  - Beide features alleen voor wasmachine (ApparaatType.WASMACHINE)

## v5.3.43 (2026-03-26)
- Nieuw: Virtual Cold Storage (VirtualColdStorageManager)
  - Vrieskist als thermische batterij via slimme stekker
  - Super-cool bij PV-surplus of negatieve prijs → koel naar min_temp_c
  - Off-peak uitschakel-venster bij hoge prijs → laat opwarmen tot max_temp_c
  - Leert opwarm/afkoelsnelheid van de specifieke vriezer (EMA model)
  - Temperatuursensor optioneel voor feedback-loop
  - Configuratie via virtual_cold_storage[] in CloudEMS opties

## v5.3.44 (2026-03-26)
- Nieuw: Future Shadow Card (cloudems-future-shadow-card)
  - Toont werkelijke kosten vs schaduw (zonder CloudEMS) per dag
  - Geleerd voordeel, recente uitkomsten, DOL insights
- Nieuw: Ghost 2.0 TV Simulator (GhostTVSimulator in lamp_circulation.py)
  - Simuleert TV-flikkering via RGB lamp bij Away-mode
  - Scene-wisselingen elke 3-8s, kleurwisselingen elke 20-120s
  - Nachtpauze 02:00-06:00, stopt bij thuiskomst
  - Configuratie via lamp_circulation.tv_simulator in CloudEMS opties

## v5.3.44 (2026-03-26)
- Nieuw: Future Shadow Card (cloudems-future-shadow-card)
  - Toont werkelijk verbruik/kosten vs "zonder CloudEMS" schaduw
  - Leest DOL total_value_eur + cost_today_eur voor dagvergelijking
  - Toegevoegd aan Zelflerend tab rechterkolom
- Nieuw: Ghost 2.0 TV Simulator volledig geïmplementeerd
  - GhostTVSimulator klasse in lamp_circulation.py
  - RGB lamp simuleert TV-flikkering (scene changes 3-8s, kanaalwisselingen 20-120s)
  - Nachtpauze 02:00-06:00, stopt automatisch als huis niet meer Away
  - Configuratie via lamp_cfg.tv_simulator.entity_id in CloudEMS opties
  - Status nu ook gepubliceerd naar coordinator data (ghost_tv_sim)

## v5.3.45 (2026-03-26)
- Nieuw: Ghost 2.0 Audio Deterrence (GhostAudioDeterrence)
  - Speelt huiselijke geluiden (hond, vaatwasser, stemmen) bij bewegingsdetectie in Away mode
  - Cooldown 5 min, nachtpauze 23:00-06:00 configureerbaar
  - Configuratie via lamp_cfg.audio_deterrence in CloudEMS opties
  - Triggers worden gelogd als decision_audio events

## v5.3.46 (2026-03-26)
- Nieuw: Elektrische Vingerafdruk (ElectricalFingerprintMonitor)
  - Monitort inschakel-curves voor koelkast, vriezer, warmtepomp, airco via NILM
  - Detecteert: motorwikkeling degradatie, koelmiddelverlies, wikkeling kortsluiting, mechanische weerstand
  - Baseline opgebouwd uit eerste 10 cycli, daarna EMA-bijwerking
  - Waarschuwing bij >25% afwijking, kritiek bij >40%
  - Cooldown 24u per apparaat, opgeslagen in HA Store
  - Triggers gelogd als electrical_fingerprint decision events

## v5.3.47 (2026-03-26)
- Nieuw: Contextual Occupancy (ContextualOccupancyLearner)
  - Leert gedragssequenties via NILM: slaap/opstaan/vertrek/thuiskomst
  - Detecteert intenties op basis van apparaat-activatievolgorde
  - Anomalie-detectie: gevaarlijke apparaten 's nachts (oven, strijkijzer)
  - Leert eigen varianten na 3+ herhalingen
  - Notificatie bij ongewone activiteit: "Oven aan om 02:00 — wil je uitschakelen?"

## v5.3.48 (2026-03-26)
- Nieuw: Self-Healing Dashboard Card (cloudems-self-healing-card)
  - Eerste kaart op de Overzicht tab — altijd zichtbaar
  - 7 contextuele situaties: negatieve prijs, PV-surplus, piekschaving, dure stroom,
    batterij laden/ontladen, Away mode, normaal
  - Toont: situatie-icon, titel, sub-tekst, badge, 4 real-time metrics
  - Actieve CloudEMS-acties als pills onderaan
  - Achtergrond en kleur passen zich dynamisch aan de situatie aan

## v5.3.49 (2026-03-26)
- Self-Healing Card v2.0.0 — alle CloudEMS modules geïntegreerd:
  - Nieuw: maintenance_warning (ElectricalFingerprint afwijking)
  - Nieuw: super_cool (Virtual Cold Storage actief)
  - Nieuw: boiler_boost situatie
  - Nieuw: wash_cycle (wasmachine actief + resterende tijd + droger-advies pill)
  - Nieuw: sleeping situatie (nachtmodus)
  - Away: Ghost TV-simulatie pill toegevoegd
  - Normal: Contextual Occupancy intent als sub-tekst
  - Normal: NILM apparaten-count als metric sub
  - Normal: DOL totaal geleerd voordeel als pill
  - Metrics: surplus sub-tekst, batterij richting, EPEX prijs per kWh

## v5.3.50 (2026-03-26)
- Bugfix: CloudEMS startte niet op — AttributeError '_elec_fingerprint' niet gevonden
  ElectricalFingerprintMonitor en ContextualOccupancyLearner werden te vroeg
  via async_setup() aangeroepen, vóór hun initialisatie in de setup-flow.
  async_setup() aanroepen verplaatst naar direct na de instantiatie van beide modules.

## v5.3.51 (2026-03-26)
- Fix: Self-Healing Card toonde 0 ct/kWh — prijs nu correct gelezen uit sensor.cloudems_price_current_hour
- Fix: 'dure stroom' drempel verlaagd van 30 naar 25 ct/kWh (23.7 ct was al hoog maar werd niet getoond)
- Fix: prijssensor toegevoegd aan change-detectie signaal

## v5.3.52 (2026-03-26)
- Fix: Self-Healing Card "Huis" toont nu totaal huisverbruik (incl. boiler, airco, EV)
  Leest sensor.cloudems_huisverbruik (Kirchhoff-gefilterd), fallback: solar+grid-batterij

## v5.3.53 (2026-03-26)
- Self-Healing Card v3.0 — volledig redesign
  - Donker palet met één kleuraccent per situatie (streep + dot + tag)
  - Geen emoji's als structuurelement — typografie doet het werk
  - Compacte labels, geen helptext
  - Metrics met tabular-nums, subtiele sub-labels
  - Pills als kleine status-chips, niet als grote knoppen

## v5.3.53 (2026-03-26)
- Stijl: Self-Healing Card teksten herschreven — korter, feitelijker, minder AI-achtig
- CLAUDE_INSTRUCTIONS: stijlregel toegevoegd voor professionele maar menselijke UI/teksten

## v5.3.54 (2026-03-26)
- Fix: Self-Healing Card PV leest nu sensor.cloudems_solar_system (was altijd 0W)
- Fix: Self-Healing Card prijs leest sensor.cloudems_price_current_hour direct
- Fix: VirtualColdStorage thermisch model nu persistent via HA Store (overleeft herstart)
- Info: zelfconsumptie 0% na herstart lost zichzelf op — storage was leeg door crashes gisteren

## v5.3.55 (2026-03-26)
- Bugfix: Zelfconsumptie was altijd 0% — realtime fallback berekening was 0.0 door
  volgorde-probleem in coordinator tick (_selfcons_pct pas later berekend)
  Fix: inline realtime berekening (solar - export) / solar × 100
- Fix: TV-simulator config veld had geen label/beschrijving in alle talen
  Vertaling toegevoegd voor nl/en/de/fr
- Info: TV-simulator = 1 RGB lamp kiezen via "TV-simulator lamp (RGB)" dropdown

## v5.3.56 (2026-03-26)
- Bugfix: cloudems-overview-card bestond niet meer als JS element — verwijderd uit dashboard
- Bugfix: Flow card toonde leeg scherm als sensor.cloudems_status nog niet geladen was
  Nu zichtbaar "Energiestroom laden..." in plaats van onzichtbaar
- Fix: self-healing card batterij sensor fallback toegevoegd (cloudems_batterij_epex_schema → cloudems_battery_schedule)
- Fix: self-healing card SoC en battW fallback op cloudems_battery_soc/power
- Fix: PV forecast kaart toont gemeten kWh als forecast nog niet beschikbaar is
- Fix: PV forecast lege grafiek toont "Forecast bouwt op na 3+ zonnedagen"
- Fix: Zelfconsumptie realtime berekening — geen opbouw meer nodig na herstart
- Test: alle 61 dashboard cards gecontroleerd op JS definitie
