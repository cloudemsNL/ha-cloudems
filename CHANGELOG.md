## v5.5.466 (2026-04-09)

### Battery card & plan card bugfixes
- `cloudems-battery-card.js`: Countdown timer werkt nu correct — `document.querySelectorAll` doorzoekt geen shadow DOM. Opgelost via `window._zpCdHosts` (Set van shadow roots per kaartinstantie).
- `cloudems-battery-plan-card.js`: SOC `—` voor verleden uren opgelost — `soc_start ?? actual?.soc_pct ?? null` fallback hersteld (was weggevallen t.o.v. v428).
- `cloudems-battery-plan-card.js`: LADEN/LEVER toont nooit meer streepje — `charge_kwh ?? 0` altijd een getal. `fmtKwh(0)` → `0W`, `fmtKwh(0.5)` → `0.50kWh`.
- `cloudems-battery-plan-card.js`: SOC kolom toont alleen eindsoc% met optionele `van X%` subtitle als start ≠ eind — geen `27→27%` meer.



### Batterijplan tabel — correcte beslissingen via Zonneplan tariefgroep
- `coordinator.py`: Plan-generator gebruikt nu de werkelijke Zonneplan tariefgroep-forecast (low/normal/high per uur) voor acties, niet meer een simplistische 15ct drempel die alles als "laden" markeerde.
- Werkelijke SOC gelezen van batteries[], niet meer 50%% default.
- LOW=laden, HIGH=ontladen, NORMAL=hold — overeenkomstig hoe Zonneplan zelf beslist.

## v5.5.191 (2026-04-05)

### Batterijplan — echte fix voor Zonneplan zonder EPEX-scheduler
- `coordinator.py`: Plan-generatie verplaatst buiten alle `if battery_scheduler` guards. Bij Zonneplan is `_battery_scheduler = None` waardoor mijn vorige fallback nooit draaide. Nu wordt het plan vlak voor de return statement gegenereerd — altijd, ongeacht of de EPEX-scheduler actief is.
- Gebruikt `today_all_display` (all-in prijs) als eerste keuze zodat de weergave overeenkomt met wat de gebruiker betaalt.

## v5.5.190 (2026-04-05)

### Batterijplan — vandaag en morgen plan gefixed
- `coordinator.py`: morgen-plan las `tomorrow_prices` (bestaat niet) ipv `tomorrow_all` — beide plans waren daardoor altijd leeg
- `coordinator.py`: vandaag-plan fallback probeert nu ook `today_all_display` (verrijkte all-in prijzen) naast `today_all`
- `cloudems-battery-overview-card.js`: leegtekst verbeterd

## v5.5.189 (2026-04-05)

### Batterijplan Vandaag — Zonneplan fallback
- `coordinator.py`: Als EPEX-scheduler geen schedule bouwt (bijv. bij Zonneplan waarbij `today_all` leeg is), genereert de coordinator nu een vandaag-plan via `decide_action_v3` op basis van beschikbare uurprijzen — zelfde logica als het morgen-plan.
- `cloudems-battery-overview-card.js`: Als schedule leeg blijft, toont de kaart nu de `human_reason` tekst ("Goedkoop tarief, batterij vasthouden...") als informatieve fallback i.p.v. "Geen data".

## v5.5.188 (2026-04-05)

### Batterijplan diagnostiek & robustere sensor-lookup
- `cloudems-battery-overview-card.js`: sensor wordt nu op 3 manieren gezocht (entity_id, naam-gebaseerd, attribuut-scan) om entity registry conflicten te omzeilen
- `cloudems-battery-overview-card.js`: prijs-veld fallback `price_all_in ?? price_allin ?? price`
- `sensor.py`: expliciete entity_id voor CloudEMSBatteryScheduleSensor

## v5.5.187 (2026-04-05)

### Batterijplan "Geen data" opgelost
- `sensor.py` `CloudEMSBatteryScheduleSensor`: miste expliciete `entity_id = _eid(entry, "sensor.cloudems_battery_schedule")`. HA genereerde een willekeurige entity_id, waardoor de kaart de sensor nooit kon vinden.
- `cloudems-battery-overview-card.js`: slot prijs-veld heet `price_allin` (zonder underscore) in de scheduler output, maar de kaart zocht naar `price_all_in`. Fallback toegevoegd: `price_all_in ?? price_allin ?? price`.

## v5.5.186 (2026-04-05)

### Preventieve AttributeError fixes
- `coordinator.py`: `self._last_soc_pct` op regel 10294 vervangen door `getattr(self, "_last_soc_pct", None)` — dit was de meest frequente crash (5x in logs bij v5.5.180, 3x bij v5.5.176).
- `coordinator.py`: `self._last_solar_w` beschermd met `getattr(..., 0.0)` op twee plekken waar het gebruikt wordt vóór het geïnitialiseerd kan zijn op eerste cyclus.

## v5.5.185 (2026-04-05)

### Bugfixes uit logs
- `sensor.py` `_quarter_prices_for_sensor`: kwartierprijs toonde ruwe EPEX (bijv. €0.019) i.p.v. all-in prijs (€0.132). Fix: gebruik `today_all_display` uur→prijs lookup zodat 15M-weergave identiek is aan 1H-weergave. `price_excl_tax` bevat nu de ruwe EPEX voor de breakdown-popup.
- `sensor.py` NILM hybride status: sensor overschreed HA 16KB attribuutlimiet (database warning). Fix: trim ankers naar 40 stuks + alleen essentiële velden.

## v5.5.184 (2026-04-05)

### Groepenkast bugfixes

**Bug: Rail 2 verdwijnt na pagina-refresh**
- `__init__.py` `save_circuit_panel`: sloeg `rail_index` nooit op en zette `position = i` (vlak genummerd) i.p.v. de encoded `ri*1000+ni`. Na refresh viel alles terug op Rail 1. Fix: gebruik `nd["position"]` en sla `rail_index` op.
- `__init__.py` `add_circuit_node`: sla ook `rail_index` en `parent_main_id` op bij aanmaken.

**Bug: Aardlek niet zichtbaar in aansluitschema**
- `cloudems-groepenkast-card.js` `_buildHierarchy`: `_getParentRCD()` zocht alleen op dezelfde rail. Automaten op Rail 1, aardlekken op Rail 2 → geen koppeling → automaten direct achter hoofdschakelaar getekend. Fix: cross-rail fallback — als geen RCD op eigen rail gevonden, zoek de eerste RCD op een andere rail.

## v5.5.183 (2026-04-04)

### Bugfix — alle wrapper-kaarten leeg
- Alle 10 tab-wrapper kaarten opnieuw geschreven met `window.loadCardHelpers().createCardElement()` — de correcte HA-manier om child cards aan te maken. Vorige aanpak met `document.createElement()` crashte stil wanneer child cards `this._r()` aanriepen in hun `setConfig()` vóórdat `hass` gezet was.
- Robuuste error handling per child card zodat één falende card de wrapper niet crasht.

## v5.5.182 (2026-04-04)

### Bugfixes + layout
- `battery-overview-card`: `schedule_today` → `schedule` (correct sensor-attribuut)
- `sensor.py`: al gefixed in v5.5.177
- Dashboard layout: Overzicht 2|6 → 4|4 (dagrapport+rooms naar links)
- Dashboard layout: Klimaat 4|2 → 3|3 (climate-epex naar rechts)
- Dashboard layout: Beslissingen 4|1 → 2|3 (beslissingen-tabs naar rechts)
- Alle 10 tab-wrapper kaarten opnieuw gegenereerd met werkende event handlers

## v5.5.181 (2026-04-04)

### Bugfix — wrapper kaarten
- Alle 10 tab-wrapper kaarten opnieuw gegenereerd: `getElementById` werkte niet (ID bestond niet), `innerHTML` tab-bar update verwijderde event listeners bij elke hass-update. Shadow DOM wordt nu slechts één keer gebouwd, class/visibility worden apart bijgewerkt.
- `cloudems-solar-tabs-card`: verwijst nu alleen naar pv-forecast + zelfconsumptie (solar-card staat apart op de Solar tab).

## v5.5.180 (2026-04-04)

### Dashboard consolidatie — alle tabs
10 nieuwe tab-wrapper kaarten — elke wrapper bevat bestaande kaarten als child elements:
- `solar-tabs-card`: PV Forecast + Zelfconsumptie (Solar tab: 6→4 kaarten)
- `klimaat-tabs-card`: Airco + Klimaat (Klimaat tab: 7→6 kaarten)
- `nilm-visual-tabs-card`: Energie visual + NILM visual
- `apparaat-tabs-card`: Tijdlijn + Apparaten + Levensduur (NILM: 8→5 kaarten)
- `ai-tabs-card`: AI + Leerresultaten + Leerproces
- `toekomst-tabs-card`: Future Shadow + Blackout Guard
- `fase-tabs-card`: Fase Balans + Fase Historiek (Zelflerend: 9→5 kaarten)
- `diagnose-tabs-card`: Diagnose + P1 + Zekeringen (Diagnose: 5→3 kaarten)
- `lampen-tabs-card`: Lampen + Circadiaans + Automaat (Lampen: 5→3 kaarten)
- `beslissingen-tabs-card`: Beslissingen + Meldingen + Schakelaars (Beslissingen: 7→5 kaarten)

## v5.5.179 (2026-04-04)

### Dashboard consolidatie — Overzicht tab
- `cloudems-energy-view-card.js` — nieuw: flow + sankey gecombineerd met tabs (⚡ Stroom standaard, 〰 Sankey op klik)
- Dashboard: cloudems-flow-card en cloudems-sankey-card vervangen door cloudems-energy-view-card

## v5.5.178 (2026-04-04)

### Dashboard consolidatie
- `cloudems-battery-overview-card.js` — nieuw: week + uur-voor-uur plan gecombineerd (tabs: Week/Gisteren/Vandaag/Morgen)
- `cloudems-batterij-status-card.js` — nieuw: off-grid survival + energiekosten gecombineerd (tabs: Off-Grid/Kosten)
- Dashboard: batterij-arbitrage-card en batterij-levensduur-card verwijderd (data zit al in battery-card)
- Dashboard: offgrid + kosten-calculator + energie-potentieel vervangen door batterij-status-card
- Dashboard: week-card + battery-plan-card vervangen door battery-overview-card
- Dashboard: duplicate vacation-card verwijderd van Overzicht tab (blijft op Beslissingen)
- `sensor.py`: battery_power_w, solar_power_w, house_load_w toegevoegd aan sensor.cloudems_status

## v5.5.177 (2026-04-04)

### Bugfix — flow & sankey toonden verschillende accu-waarden
- `sensor.py`: `battery_power_w`, `solar_power_w` en `house_load_w` toegevoegd aan `sensor.cloudems_status` attributen. Beide kaarten lezen nu dezelfde coordinator-bron i.p.v. elk hun eigen fallback-keten.

## v5.5.176 (2026-04-04)

### Bugfix — kritiek: Ariston boiler permanent geblokkeerd
- `boiler_controller.py`: `_check_turn_on_no_response` preset mismatch check gebruikte `is_on` om `_want` te bepalen. In de turn-on context is `is_on` altijd `False`, waardoor `_want = preset_off` werd. Als de boiler al in `preset_off` stond (bijv. GREEN) werd geen mismatch gedetecteerd en liep de back-off teller onterecht op. Gevolg: boiler permanent geblokkeerd. Fix: `_want` altijd `preset_on` in deze context.

## v5.5.175 (2026-04-04)

### Bugfixes
- `cloudems-standards.js`: syntax error LU landnaam — apostrof in Luxemburg PAN-naam brak de JS string
- `switch.py`: rolluik automaat aan/uit triggerde geen coordinator refresh — `async_request_refresh` toegevoegd na `set_auto_enabled`
- `button.py`: rolluik cancel/pause knoppen triggeerden geen coordinator refresh — `async_request_refresh` toegevoegd na `cancel_override` en `set_auto_enabled`

## v5.5.174 (2026-04-04)

### Bugfixes
- `coordinator.py`: sluimerverbruik altijd 0 — `nilm_devices` (integer count) vervangen door `nilm_devices_enriched` (lijst) in `_build_standby_intelligence`
- `coordinator.py`: FCR/aFRR "Batterij SOC niet beschikbaar" — `data.get("battery_soc_pct")` (key bestond niet) vervangen door `self._last_soc_pct`

## v5.5.173 (2026-04-04)

### Bugfix
- `number.py`: ontbrekende `RestoreEntity` import toegevoegd. Zorgde voor `NameError` bij laden van `CloudEMSBlackoutReservePct` waardoor de volledige integratie niet startte.

## v5.5.106 (2026-04-01)

### AdaptiveHome Bridge — cloud-ready voorbereiding
- `adaptivehome_bridge.py` uitgebreid met:
  - Cloud-beslissing override mechanisme (`get_cloud_decision()`, `CloudDecision` dataclass)
  - Offline buffer voor cloud-uitval (max 50.000 metingen, FIFO)
  - `async_push_to_cloud()` met aiohttp + backfill bij reconnect
  - `configure_cloud()` voor URL/token/licentieniveau
  - `LicenseLevel` constanten (cloudems/ah_basic/bundle/enterprise)
  - `adaptivehome_decision` event listener voor cloud-beslissingen
  - Buffer-status in `get_status()` output
- `coordinator.py` bijgewerkt:
  - Cloud push aanroep toegevoegd in bridge-sectie
  - `configure_cloud()` aangeroepen bij setup vanuit config-keys
  - Config-keys: `adaptivehome_cloud_url`, `adaptivehome_license`

### Bugfixes sessie 2026-04-01
- JS kaarten: alle live vermogenswaarden nu consistent via `sensor.cloudems_status.attributes`
  (sankey, home-card, iso-card, self-healing-card)
- `en.json`: `neighbourhood_url` placeholder toegevoegd (HA validatie-warning opgelost)
- Coordinator ctx pipeline: alle 61 cross-method variabelen gedekt, geen NameErrors meer

# CloudEMS Changelog

## v5.5.78 (2026-03-31)
- Fix: Fase-conflict blijft herstarten bij west-omvormer (issue gemeld door Roedie84)

  Root cause: cross-validatie telde elke meting even zwaar mee, ook ruis-stemmen
  bij lage vermogens. Een west-omvormer produceert 's ochtends <100W — op dat moment
  is fasecorrelatie mathematisch onbetrouwbaar (signaal-ruis ratio te laag).
  Die ruis-stemmen wegstemden de correcte L3-stemmen van de middag.

  Fix: vermogensdrempel voor crossval-stemmen.
    CROSSVAL_MIN_POWER_PCT = 0.20 (20% van 7-daags piek)
    CROSSVAL_MIN_POWER_ABS = 300W (absoluut minimum)
  Stem alleen als omvormer echt produceert. West-omvormer ochtend = automatisch
  uitgesloten. Piek bekend na ~7 dagen normaal gebruik.

  Tevens toegevoegd:
    - user_confirmed_phase veld: als gebruiker ooit handmatig bevestigt,
      wordt crossval permanent overgeslagen
    - HA service cloudems.confirm_inverter_phase (label, phase)
    - services.yaml bijgewerkt

## v5.5.77 (2026-03-31)
- Crash fix #46: _nexus_p90 UnboundLocalError
  Root cause: variabele alleen gedefinieerd in else-tak maar gebruikt buiten if/else.
  Als _ai_registry aanwezig was sloeg Python de else over → UnboundLocalError elke cyclus.
  Fix: _nexus_p90 = 90.0 altijd initialiseren vóór de if/else.

- Performance fix #46: score_trend_alert runaway log spam
  Root cause: get_trend_alert() had geen cooldown — bij parallelle coordinator
  instanties (coordinator crasht → herstart → overlap) logde hij tientallen keren
  per seconde hetzelfde alert. Dit verklaart avg_ms 1700-3000 en mode: CRITICAL.
  Fix: 24u cooldown in get_trend_alert() via _trend_alert_last_ts.

## v5.5.75 (2026-03-31)
- Fix: partner_slug toegevoegd aan data_consent config flow stap
- Fix: voltage_v van P1 (voltage_l1) doorgegeven aan lightning detector
- Nieuw: dagrapport-kaart toont gisteren vergelijking
  - DailySummaryGenerator.get_yesterday() snapshot bij dagelijkse notificatie
  - Watchdog sensor exposeert daily_summary_yesterday attribuut
  - Kaart: zelfconsumptie/opgewekt/kosten vandaag vs gisteren naast elkaar
- Fix: Kirchhoff-gecorrigeerde batterijwaarde geborgd in v5.5.74

## v5.5.75 (2026-03-31)
- Fix: spanning (voltage_v) nu doorgegeven vanuit P1 naar LightningDetector
- Fix: HA persistent_notification bij bliksemevent (⚡ CloudEMS — Blikseminslag gedetecteerd)
- Nieuw: ApiClient model (AdaptiveHome) — betalende data-API afnemers
  - Tiers: tier1 (€500/mnd) t/m tier4 (claim-verificatie)
  - Rate limiting per dag/maand, automatische reset
  - API key met dak_ prefix
- Nieuw: Data API publieke endpoints (AdaptiveHome /api/v1/data/*)
  - GET /data/pv_cloud_proxy — PV-bewolking proxy per locatie
  - GET /data/weather — weerobservaties per locatie
  - GET /data/voltage — netspanningsanomalieën per straat
  - POST /data/verify_event — claim-verificatie (Tier 4)
  - GET /data/my_usage — API verbruik voor huidige client
- Nieuw: Admin dashboard "Data API Clients" view
  - MRR/ARR van data API
  - Client aanmaken met tier, datasets en contract
  - Inline API key generatie

## v5.5.74 (2026-03-31)
- Fix: Kirchhoff-gecorrigeerde batterijwaarde ging verloren in finale data dict
  Root cause: self._data wordt op regel ~9673 volledig opnieuw gebouwd.
  _collect_multi_battery_data() las de ruwe sensorwaarde (+445W stale) opnieuw,
  ongeacht de eerdere Kirchhoff-correctie op data["batteries"].
  Gevolg: display toonde +445W laden terwijl batterij -11kW aan het ontladen was.
  House (2.8kW) was WEL correct want die leest uit _bal.house_w.
  Fix: _kirchhoff_battery_w/_kirchhoff_battery_data opslaan als class attribuut.
  Nieuwe methode _collect_multi_battery_data_kirchhoff() past correctie toe
  in de finale self._data dict. Reset na één cyclus.

## v5.5.66 (2026-03-30)
- Nieuw: WeatherObservationCollector — microklimaat dataset (weather_observation.py)
  Verzamelt per 5 minuten alle beschikbare meteorologische data:
  - Direct: temperatuur, wind, neerslag, luchtdruk, vochtigheid via weather entity
  - PV-proxy: bewolking via forecast vs werkelijk (altijd aanwezig)
  - Rolluik-proxy: windstoot detectie via wind-beveiliging activatie
  - Thermisch: isolatiewaarde berekening uit binnen/buitentemperatuur delta
  - KNMI-kalibratie infrastructuur: correctie-offset via EMA
  - SensorMeta: kwaliteitsscore 0-100 per variabele, hoogte, oriëntatie
  - Cloud-ready schema: ObservationRecord klaar voor AdaptiveHome upload
  - sensor.cloudems_weather_observations: totaal records + statistieken

Commercieel fundament:
  - Elke installatie = microklimaat-meetstation met 10-seconden PV-proxy
  - KNMI-kalibratie maakt data vergelijkbaar met officiële stations
  - Upload schema klaar voor verkoop aan meteo/verzekeraars/netbeheerders
  - Variabelen aanwezig afhankelijk van gekoppelde HA-sensoren

## v5.5.65 (2026-03-30)
- Nieuw: Real-time wolkradar via Open-Meteo current= API
  - pv_forecast.py: haalt nu ook current=cloud_cover,wind_speed_10m,wind_direction_10m op
  - Elk uur bijgewerkt vanuit satelliet + grondradar (geen scraping, CC BY 4.0)
  - get_current_wind() geeft nu real-time waarden ipv hourly forecast
- Nieuw: PV dip risico berekening (assess_dip_risk)
  - cloud_pct >40% + wind >2m/s → stijgend risico (0.0-1.0 score)
  - Geeft geschatte minuten tot impact (5-30 min)
  - Volledig standalone — werkt zonder cloud-netwerk
- Nieuw: Boiler reageert op verwachte PV dip
  - Bij risico >50%: effectief surplus verlaagd (risico × 50%)
  - Bij 80% dip risico: boiler ziet 40% minder surplus → start geen nieuwe cyclus
  - Niet actief bij negatieve prijs (dan wel gewoon laden)
  - sensor.cloudems_pv_dip_events.attributes.dip_risk toont actuele status

## v5.5.64 (2026-03-30)
- Nieuw: PV Dip Detector — gedistribueerd wolkradar netwerk (laag 1 van 3)
  - Open-Meteo uitgebreid: wind_speed_10m + wind_direction_10m + cloud_cover per uur
  - pv_dip_detector.py: detecteert 20%+ onverwachte PV-dalingen
  - Privacy: GPS afgerond op 0.01° (~1km), installation_id als SHA-256 hash
  - PvDipEvent schema: cloud-ready voor AdaptiveHome upload
  - Haversine + kompasrichting berekening voor wolkreistijd
  - receive_cloud_event(): klaar voor events van andere installaties
  - Sensor: sensor.cloudems_pv_dip_events (state=aantal events)
  - Attributen: recent_events, active_prediction, upload_pending (voor cloud)

## v5.5.63 (2026-03-30)
- Nieuw: Batterij SoC prognose curve (vandaag groen + morgen blauw gestippeld)
  - Backend: soc_forecast_curve berekend per uur op basis van PV forecast - huisverbruik
  - Vandaag: vanaf huidig uur, morgen: volledige dag
  - Min/max SoC punten gemarkeerd, 20%/80% referentielijnen
  - Scheiding vandaag/morgen via verticale lijn
- Nieuw: Solar analyse tab verbeterd met SVG staafgrafiek (30 dagen)
  - Vandaag goud, eerdere dagen groen, datumlabels automatisch
  - Detailrijen onder de grafiek voor exacte waarden
- Nieuw: Boiler kWh display naast tankvisualisatie
  - Berekening: tankL × (T_water - T_koud) × 1.163 / 1000
  - Toont opgeslagen thermische energie in kWh
- Nieuw: Dagrapport kaart (cloudems-dagrapport-card)
  - Zelfconsumptie score groot weergegeven
  - KPI grid: opgewekt / kosten vandaag / kosten maand
  - Energiebalans bars: opgewekt / geïmporteerd / teruggeleverd / opbrengst
  - Top 5 verbruikers vandaag via NILM
  - Vergelijkingsrij met kleurcodering
  - Automatisch geregistreerd als lovelace resource

## v5.5.62 (2026-03-30)
- Nieuw: verwachte teruglevering per uur in pv-forecast-card
  - Backend: surplus_forecast_hourly berekend in coordinator
    PV forecast per uur − verwacht huisverbruik (HouseConsumptionLearner)
    + EPEX prijs per uur → verwachte opbrengst in €
  - Frontend: oranje balken naar beneden onder de PV grafiek
    Kleurintensiteit op basis van opbrengst per uur (meer € = dieper oranje)
    Totaal verwachte opbrengst rechtsboven surplus zone
  - Label "↓ verwacht surplus (excl. sturing)" — eerlijk: zonder boiler/EV correctie

## v5.5.61 (2026-03-30)
- Nieuw: pv-forecast-card toont gestapelde balken per omvormer
  - Omvormer 1: groen, omvormer 2: teal, samen = totaal forecast
  - Dunne scheidingslijn tussen omvormers voor leesbaarheid
  - Fallback naar enkelvoudige balk bij 1 omvormer

## v5.5.60 (2026-03-30)
- Fix: pv-forecast-card toonde dubbele balken bij 2 omvormers
  - Oorzaak: sensor.hourly bevat per omvormer een entry per uur
  - Bij 2 omvormers: uur 12 stond 2× in de array → 2 balken naast elkaar
  - Fix: aggregeer per uur (som forecast_w/low_w/high_w, gemiddelde confidence)
  - Resultaat: één balk per uur = totaal van alle omvormers

## v5.5.59 (2026-03-30)
- Fix: alle dagen toonden exact dezelfde forecast grafiek
  - Gisteren: had geen aparte forecast → nu arr24() (lege lijn), alleen werkelijk zichtbaar
  - Vandaag: fcHourly correct
  - Morgen: fcTomHourly correct (vandaag forecast als referentie)
- Fix: "Verwacht tot nu" label aangepast per dag
  - Gisteren: "Totaal verwacht → —" (geen forecast beschikbaar)
  - Vandaag: "Verwacht tot nu"
  - Morgen: "Totaal verwacht"

## v5.5.58 (2026-03-30)
- Fix: solar card inverter chips toonden verkeerde of lege waarden
  - Oriëntatie (kompas) was leeg: inv.learned_azimuth bestaat niet → inv.azimuth_compass
  - Piek vermogen was leeg: inv.peak_wp bestaat niet → inv.estimated_wp / peak_w
  - Fase was leeg: inv.detected_phase bestaat niet → inv.phase_display
  - Benutting % was handmatig berekend → nu inv.utilisation_pct (backend berekend)
  - Benut chip toont nu ook max vermogen: "0% benut · 10.21 kW max"

## v5.5.56 (2026-03-30)
- Fix: solar card crash "fcExpected.toFixed is not a function"
  - Root cause: fcA.hourly is [{hour, forecast_w, ...}] objecten, niet array van getallen
  - _toArr24() helper: converteert object-array correct naar 24-waarden getal-array
  - Detecteert automatisch beide formaten (object-stijl en getal-stijl)
  - forecast_w in Watt → kWh per uur voor grafiek
  - Getest met echte sensor data structuur

## v5.5.53 (2026-03-30)
- Fix: drempelwaarden voor display verwijderd/verlaagd
  - Boiler kWh sensor: current_power_w altijd gezet (ook bij 10W, 50W, 180W)
  - is_heating badge: drempel 50W → 5W
  - NILM power toewijzen: 50W → 1W
  - Apparaat actief check: 50W → 1W
  - Infra_pw dict (flow card): solar/grid/ev/hp/boiler drempel 50-200W → 1W
  - Flow card JS: pw > 10 → pw > 1 voor is_on check
  - Leer-drempels (nominaal vermogen) ongewijzigd (> 50W) — ruis niet leren

## v5.5.52 (2026-03-30)
- Fix: alle sensor outputs gebruiken nu display EMA (5s tau)
  - solar_power, grid_power (import/export), battery_power, house_power
  - Vloeiende UI zonder geflicker, altijd Kirchhoff=0 wat de gebruiker ziet
  - Beslissingen (boiler, EV, accu) blijven op 20s EMA
  - P1 grid blijft leidend voor beslissingen, display EMA alleen voor weergave
  - Getest: 6 scenario's, display altijd sluitend

## v5.5.51 (2026-03-30)
- Fix: display EMA gebruikte fout anker bij geschatte battery (Nexus vertraging)
  - house_trend als anker voor display bij battery_estimated=True
  - huis_display blijft stabiel bij grote grid sprong
- Getest: Kirchhoff=0 op raw, display én EMA in 11 scenario's
  - Nacht, dag, accu laden/ontladen, inductie, zelfvoorzienend, max export
  - Grid sprong met Nexus vertraging, magnetron piek
  - Alle drie lagen exact 0W imbalans

## v5.5.50 (2026-03-30)
- Nieuw: Twee EMA lagen voor alle sensoren
  - Display (~5s tau):   nauwelijks filter, geen geflicker in UI maar wel vloeiend
  - Beslissingen (~20s): pieken gesmoothed, stabiele sturing
  - alpha_display = dt/(5+dt) ≈ 0.67 bij 10s interval
  - alpha_decision = dt/(20+dt) ≈ 0.33 bij 10s interval
  - Magnetron piek: display toont max 333W, beslissing max 167W
  - Kirchhoff gewaarborgd op beide EMA niveaus
  - house_power sensor gebruikt display EMA → geen flikkerende getallen

## v5.5.49 (2026-03-30)
- Nieuw: Leerbare sprong-toedeling via JumpAttribution sigmoid
  - Kleine sprong (500W): ~21% accu, ~79% huis (waarschijnlijk koelkast/lamp)
  - Middel (3kW): ~41% accu — kan inductie OF accu zijn
  - Groot (7kW): ~83% accu — vrijwel zeker Nexus cloud-lag
  - Enorm (10kW): ~91% accu — zeker accu
  - house_alpha = base_alpha × (1 - battery_fraction) — proportioneel gereduceerd
  - Zelflerend: na ~45s arriveert echte Nexus waarde → threshold bijgesteld
  - Diagnostics: jump_attribution.threshold_w en n_learned zichtbaar

## v5.5.48 (2026-03-30)
- Fix: Kirchhoff imbalans door foute house_alpha boost bij grid/accu sprongen
  - Eerder: bij grote delta → house_alpha boosten zodat huis de sprong volgt
  - Bug: huis (thermische lasten) kan nooit 7kW+ springen in 10s — dat is altijd de accu
  - Bij boosten: house_trend = 8840W (sprong), battery = solar+grid-8840 = onmogelijk
  - Fix: bij grote grid sprong (>1kW) → house_alpha clippen naar max 0.05
  - Huis EMA blijft stabiel, accu krijgt de sprong via Kirchhoff
  - battery = solar + grid - house_ema → altijd Kirchhoff=0
  - Na ~45s arriveert echte Nexus waarde → systeem convergeert naar werkelijke waarden
  - Threshold stale battery: 10s → 30s (Nexus P90 latency ~45s)

## v5.5.47 (2026-03-30)
- Fix: Kirchhoff imbalans bij grote export + accu ontladen
  - Bug: bij export > solar + 500W werd batterij VERVANGEN door Kirchhoff-van-house_trend
  - Als house_trend verouderd (8840W, trend van eerder) → battery = 412-7470-8840 = -15898W (onmogelijk)
  - Circulaire fout: house_w = house_trend = 8840W, dashboard toont bat=9630W → 6268W mismatch
  - Fix: als batterijsensor vers is (< 30s) → sensor is leidend, house volgt via Kirchhoff
  - Resultaat: solar=412W, bat=9630W ontladen, grid=7470W export → huis=2572W (correct)
  - Threshold verhoogd: 10s → 30s voor Kirchhoff-override (Nexus P90 latency ~45s)

## v5.5.46 (2026-03-29)
- Nieuw: Solar card volledig herbouwd naar Solcast-stijl
  - Header: omvormers + piek + huidig vermogen
  - Top strip: Nu / Vandaag gemeten / Morgen verwacht
  - Tabs: Live, Analyse, Advies
  - Grafiek: SVG met 3 lijnen (verwacht/werkelijk/gisteren) + tijdlijn nu
  - Navigatie: gisteren ← vandaag → morgen
  - Stats: verwacht tot nu / werkelijk / afwijking %
  - Per omvormer: naam, vermogen, benutting bar, oriëntatie, fase
  - Analyse tab: rolling 14-daagse productie + nauwkeurigheid 14d/30d
  - Advies tab: automatische tips op basis van forecast en clipping
- Nieuw: Backend rolling 30-daagse uurdata opslag
  - Elke dag bij middernacht opgeslagen in _pv_daily_history
  - Persistent via storage (overleeft herstart)
  - Beschikbaar in accuracy sensor als daily_history attribuut

## v5.5.45 (2026-03-29)
- Nieuw: TRV/airco throttling — voorkomt te frequent sturen
  - TRV: max 1x per 5 minuten (batterij spaarzaam)
  - Airco: max 1x per 3 minuten (voorkomt piepen bij elke bevestiging)
  - Alleen sturen bij mode-wijziging OF significante temperatuurverandering (>0.4°C)
- Nieuw: CV-ketel wizard configuratie
  - Entity: switch.* / climate.* / OpenTherm
  - Stooklijn parameters: slope, min/max aanvoertemperatuur, zomer cutoff
  - Minimaal aantal zones dat warmte vraagt voor ketel aan
- Nieuw: OpenTherm stooklijn berekening
  - T_aanvoer = T_pivot + slope × (T_setpoint - T_buiten)
  - Beter dan VTherm vaste hoog/laag: berekent optimale aanvoertemperatuur
  - Max 55°C → condensatieketel altijd in condensatiemodus
  - Extra correctie op basis van gewogen warmtevraag per zone
  - Slope is leerbaar (toekomst)

## v5.5.44 (2026-03-29)
- Fix: has_gas_heating was nooit True — geen wizard knop beschikbaar
  - Alle gas-checks (v5.5.32-5.5.43) faalden omdat has_gas_heating altijd "" was
  - Fix: coordinator detecteert automatisch of gas geconfigureerd is
  - Als gas_sensor of gas_price_sensor aanwezig → has_gas_heating="yes" voor alle boilers
  - Gebruiker hoeft niets in te stellen — gas config = gas aanwezig

## v5.5.40 (2026-03-29)
- Fix: mismatch correctie werd geskipped als pending_preset gevuld was
  - Na elk turn_on commando: pending_preset = "boost" 
  - _do_mismatch_correction: if pending_preset → return (skip)
  - Maar als force_green verandert, klopt pending_preset ook niet meer
  - Fix: als pending_preset ≠ gewenste preset → reset pending → correctie gaat door
  - Gecombineerd met v5.5.39 all-in prijs fix: nu beide pijlen in dezelfde richting

## v5.5.39 (2026-03-29)
- Fix: gas-check gebruikte EPEX raw prijs ipv all-in prijs
  - EPEX raw = 7.1 ct/kWh, gas thermisch = 14.2 ct/kWh → 7.1 < 14.2 → GEEN force_green
  - All-in prijs = 21.7 ct/kWh → 21.7 > 14.2 → force_green=True (correct)
  - Oorzaak: price_info["current"] = EPEX raw, price_info["current_all_in"] = all-in incl. belasting
  - Fix: gebruik current_all_in in alle gas-checks in boiler_controller
  - Gesimuleerd: alle waarden uit echte log, alle edge cases OK

## v5.5.38 (2026-03-29)
- Refactor: gas-check en mismatch correctie in helper methoden
  - _apply_gas_check_and_mismatch() en _do_mismatch_correction()
  - Alle 3 paden gebruiken dezelfde helper: _evaluate_single, _group_sequential, _group_parallel
  - Toekomstige paden hoeven alleen de helper aan te roepen
  - Getest: alle 3 paden + edge cases gesimuleerd voor release

## v5.5.37 (2026-03-29)
- Fix: BOOST bleef actief in cascade/seq pad (definitieve fix)
  - Eerdere fixes zaten in _evaluate_single, niet in _group_sequential
  - Cascade boilers gaan via _group_sequential → mismatch correctie miste daar
  - Nu: gas-check + mismatch correctie ook in _group_sequential
  - Getest: alle paden gesimuleerd incl. edge cases

## v5.5.37 (2026-03-29)
- Fix: gas-check zat in _evaluate_single maar seq pad loopt via _group_sequential
  - _evaluate_single en _evaluate_group zijn twee aparte functies
  - Gas-check op verkeerde plek → nooit uitgevoerd bij cascade/seq boilers
  - Fix: gas-check toegevoegd in _group_sequential direct voor active=None block
  - Gesimuleerd en geverifieerd: 24.6ct > 14.2ct gas → force_green=True → GREEN

## v5.5.36 (2026-03-29)
- Fix: BOOST bleef actief bij hold_on ondanks gas goedkoper
  - _switch_smart gas-check werkt alleen bij nieuwe turn_on commando's
  - Bij hold_on komt geen nieuw commando → gas-check werd nooit uitgevoerd
  - force_green werd ook niet gezet via seq-pad → mismatch check zag geen verschil
  - Fix: gas-check zet force_green direct vóór de mismatch correctie
  - Elke cyclus: als gas goedkoper → force_green=True → mismatch BOOST≠GREEN → correctie

## v5.5.35 (2026-03-29)
- Refactor: centrale gas-check in _switch_smart (vervangt v5.5.32 + v5.5.34)
  - Gas-check zat op losse plekken (demand boost, seq levering) — elk nieuw pad zou
    opnieuw vergeten worden
  - Nu: één centrale blokkade in _switch_smart() — de enige plek die altijd
    doorlopen wordt bij elk BOOST commando, ongeacht welk pad het triggert
  - Alle toekomstige paden zijn automatisch gedekt
  - Losse gas-checks uit v5.5.32 en v5.5.34 verwijderd

## v5.5.34 (2026-03-29)
- Fix: BOOST via seq [levering [geleerd]] pad ondanks goedkoper gas
  - v5.5.32 gas-check zat alleen in demand boost pad, niet in seq/levering pad
  - Levering-learner stuurde turn_on zonder force_green → altijd BOOST
  - Nu: seq pad checkt ook gas prijs voor hybrid boilers met has_gas_heating=yes
  - Zelfde logica: stroom duurder dan gas → force_green=True → GREEN (WP)

## v5.5.33 (2026-03-29)
- CLAUDE_INSTRUCTIONS bijgewerkt: ontwikkelregels toegevoegd
  - Bij twijfel overleggen voor coderen
  - Logisch denken: gebruikerscontext meenemen (gas, cascade, multi-instantie)
  - Code controleren: statische analyse, scope fouten, baseline vergelijking
  - Web search bij twijfel over externe APIs of hardware gedrag
  - Releaseproces: nooit dubbele versienummers, CHANGELOG altijd bijwerken

## v5.5.32 (2026-03-29)
- Fix: demand boost werd actief terwijl gas goedkoper is
  - Gebruiker heeft gas + CV cascade → gas pakt het tekort op als WP te traag is
  - BOOST (weerstandselement) is nooit goedkoper dan gas in dit scenario
  - Demand boost geblokkeerd als: has_gas_heating=yes EN gas goedkoper dan BOOST
  - Alleen BOOST als stroom écht goedkoper dan gas (>10% marge)

## v5.5.31 (2026-03-29)
Schone release — werkmap gesynchroniseerd. Bevat alle fixes van deze sessie:
- BatterySocLearner: span-EMA capaciteitsmeting (Methode C)
- Capaciteit sanity check werkt ook direct na herstart
- Boiler: BOOST→GREEN modus-correctie elke cyclus na herstart
- Boiler: setpoint verlagen tijdens accu-ontlading + geen surplus
- Boiler: cmd→_desired_cmd fix (NameError bij iMemory brug)
- Dashboard sensors: 19 kritieke sensors met expliciete entity_id
- Sensor setup: _eid naam conflict opgelost (for _watch_eid in _WATCH)
- Button unique_ids: coordinator.config_entry.entry_id ipv DOMAIN
- Demo wizard: 🎮 Demo optie in installatie wizard
- Kirchhoff: house_alpha boost bij grote batterij/grid-verandering
- Ariston debounce: 600s → 30s, back-off reset bij iMemory brug

## v5.5.29 (2026-03-29)
- Fix: Ariston blijft in BOOST na herstart terwijl CloudEMS GREEN zou kiezen
  - hold_on actie controleerde niet of de huidige modus correct was
  - Bij hold_on + preset mismatch (bijv. BOOST terwijl GREEN gewenst) → stuur correctie
  - Treedt op na herstart: Ariston onthoudt modus, CloudEMS zag "al aan" → geen actie
  - Nu: binnen één cyclus gecorrigeerd van BOOST naar GREEN als prijs dit vraagt

## v5.5.28 (2026-03-29)
- Fix: demo dashboard toont 0W voor alles
  - Demo engine startte correct maar coordinator las lege sensor config (grid="", solar="")
  - Demo engine get_sensor_config() wordt nu geïnjecteerd in coordinator config bij start
  - Geldt voor zowel auto-start bij herstart als handmatig aanzetten via set_demo_mode()

## v5.5.27 (2026-03-29)
- Fix: pieksturing/flow kaart en andere dashboard sensors ontbraken na crashes
  - 94 sensors hadden geen expliciete entity_id → kwetsbaar voor registry drift
  - Alle 19 dashboard-kritieke sensors hebben nu expliciete entity_id via _eid()
  - Gerepareerd: grid_net_power, pv_forecast_today/tomorrow, grid_phase_imbalance,
    energy_balancer, meter_topology, solar_system_intelligence, grid_import_power,
    p1_power (+ eerder: status, boiler_status)
  - Registry fix kan alle sensors nu herstellen bij orphaned entries

## v5.5.26 (2026-03-29)
- Fix: flow kaart blijft "Energiestroom laden..."
  - sensor.cloudems_status had geen expliciete entity_id
  - Na crashes/herstarts kon HA de entity_id anders toewijzen
  - Alle kritieke sensoren (status, boiler_status) krijgen nu expliciete entity_id via _eid()
  - Registry fix kan ze nu ook herstellen bij orphaned entries

## v5.5.25 (2026-03-29)
- Fix: boiler schakelcommando "name 'cmd' is not defined"
  - cmd["preset"] → _desired_cmd["preset"] in _switch() iMemory brug check
  - Bug bestond al vóór onze wijzigingen (ook in v5.5.18), nu opgelost
- Verificatie: alle 289 Python bestanden syntax OK, geen nieuwe bugs geïntroduceerd
  vs v5.5.18 baseline

## v5.5.24 (2026-03-29)
- Fix: crash door naam conflict _eid in sensor.py
  - _eid is onze helper functie maar werd ook als loop variabele gebruikt
    in _post_add_check: "for _eid in _WATCH" overschreef de functie definitie
  - Loop variabele hernoemd naar _watch_eid
  - Dit veroorzaakte crashes bij normale (niet-demo) setup na v5.5.19

## v5.5.23 (2026-03-29)
- Fix: alle resterende entry.entry_id scope fouten in button.py
  - Statische analyse uitgevoerd op alle 6 entity files
  - Alle __init__ zonder entry param gebruiken nu coordinator.config_entry.entry_id
  - Geen hardcoded entity_ids meer, geen DOMAIN-based unique_ids meer
  - Volledig schoon — 0 problemen in statische analyse

## v5.5.22 (2026-03-29)
- Fix: NameError 'entry' is not defined in button.py
  - CloudEMSForceUpdateButton en CloudEMSBuyMeCoffeeButton hadden geen entry param
  - maar gebruikten wel f"{entry.entry_id}" → NameError bij setup
  - Fix: coordinator.config_entry.entry_id voor coordinator-only __init__ methods

## v5.5.21 (2026-03-29)
- Fix: crash echte instantie door button unique_id conflicten met demo instantie
  - cloudems_force_update/diagnostics/buy_me_coffee/nilm_cleanup/* gebruikten DOMAIN prefix
  - Allemaal omgezet naar entry.entry_id prefix zodat elke instantie unieke IDs heeft
  - Slider buttons (coordinator-only) lezen entry_id via coordinator.config_entry
  - entity_id via _eid() helper voor demo-awareness

## v5.5.20 (2026-03-29)
- Fix: demo dashboard toont zelfde data als echte instantie
  - Registry fix beperkt tot eigen config entry (nooit andere instantie aanraken)
  - Cleanup van verouderde demo entities met _2/_3 suffix bij setup
  - _post_add_check watchers via _eid() zodat demo de juiste entities monitort
  - Na installatie v5.5.20: demo entry verwijderen en opnieuw toevoegen voor clean slate

## v5.5.19 (2026-03-29)
- Nieuw: Multi-instantie + Demo volledig afgebouwd
  - Entity_id refactor: _eid(entry, entity_id) helper in sensor.py, switch.py, button.py,
    number.py, climate.py, virtual_boiler.py (117 entity_ids totaal)
  - Demo instantie: sensor.cloudems_demo_*, switch.cloudems_demo_* etc.
  - Normale instantie: ongewijzigd sensor.cloudems_*
  - cloudems-dashboard-demo.yaml aangemaakt (kopie normaal, alle entities vervangen)
  - Demo dashboard geregistreerd in _DASHBOARDS + sidebar "🎮 CloudEMS Demo"
  - Demo dashboard YAML gekopieerd naar /config/ bij setup
  - CLOUDEMS_SLUGS bijgewerkt voor live reload

## v5.5.18 (2026-03-29)
- Nieuw: Demo modus optie bij installatie wizard
  - Kies "🎮 Demo — virtuele installatie, geen echte sensoren nodig"
  - Tweede CloudEMS instantie als Demo zonder conflict met eerste
  - Titel "CloudEMS Demo" ipv "CloudEMS" zodat ze te onderscheiden zijn
  - Demo engine direct actief op 48× tijdversnelling (dag in 30 min)
  - HA-notificatie bij activatie met uitleg

## v5.5.17 (2026-03-29)
- Fix: Normaal knop toonde 75°C ipv 53°C (green_max)
  - Normaal = max_setpoint_green_c (53°C), niet huidige setpoint
- Fix: Nacht/Normaal/PV-boost/+/- knoppen gaan nu via cloudems boiler_send_now
  - Zet manual_override 2 uur → CloudEMS overschrijft niet direct terug
  - Fallback naar water_heater.set_temperature als service niet beschikbaar is

## v5.5.16 (2026-03-29)
- Fix: BOOST knop in virtuele thermostaat werkte niet
  - Bug 1: send_now zette geen manual_override_until → coordinator overschreef direct terug
  - Bug 2: comment zei "altijd GREEN" maar logica koos al BOOST boven 53°C — nu expliciet
  - Fix: manual_override_until = 2 uur na handmatige BOOST → CloudEMS respecteert dit
  - Fix: setpoint > green_max → BOOST via iMemory brug, setpoint <= green_max → GREEN
  - Debounce gereset zodat commando meteen verstuurd wordt

## v5.5.15 (2026-03-29)
- Fix: capaciteit sanity check werkt nu ook direct na herstart
  - Vóór fix: check vereiste max_discharge_w > 2000W maar na herstart is die 0
  - Nu: als geleerde cap < 2 kWh én config battery_capacity_kwh aanwezig → gebruik config direct
  - Batterij kaart toont nu meteen 10 kWh na herstart ipv 1.7 kWh

## v5.5.14 (2026-03-29)
- Fix: house_alpha boost ook bij grote grid-verandering
  - Scenario: grid stopt exporteren maar battery toont nog -9kW → house spikt naar 11kW
  - Fix: max(battery_delta, grid_delta) bepaalt de boost → beide triggers gedekt
  - 2kW verandering = +6% boost, 9kW = +27% boost, normale situaties ongewijzigd

## v5.5.13 (2026-03-29)
- Fix: Kirchhoff huis-EMA te traag bij grote batterijverandering (Zonneplan Nexus)
  - Nexus stuurt batterijdata traag → battery.alpha laag → house_alpha laag
  - Bij vermogenssprong > 2kW: house_alpha tijdelijk geboosted (max +27% bij 9kW sprong)
  - Kleine gerichte fix — normale situaties ongewijzigd

## v5.5.12 (2026-03-29)
- Nieuw: Batterij degradatie prognose op basis van gemeten capaciteit
  - BatterySocLearner span-EMA koppelt aan BatteryDegradationTracker
  - Maandelijkse capaciteits-snapshot bewaard (max 10 jaar / 120 maanden)
  - Lineaire regressie op capaciteitsgeschiedenis → verlies kWh/jaar
  - Prognose: over 5 jaar X kWh, over 10 jaar Y kWh, nog Z jaar tot 70% SoH
  - 70% SoH = fabrikant "versleten" grens — accu werkt daarna nog jaren gewoon
  - Batterij Levensduur kaart toont de prognose sectie zodra data beschikbaar is
  - Eerste meting na één span (15%) al zichtbaar, betrouwbaarheid groeit met tijd

## v5.5.11 (2026-03-29)
- Fix: BatterySocLearner capaciteit fout geleerd (1.7 kWh ipv 10 kWh)
  - Methode C toegevoegd: SoC-span EMA — elke span van X%→Y% + gemeten kWh = directe capaciteitsschatting
  - Gewogen EMA: grote spans (40%) wegen zwaarder dan kleine spans (15%)
  - 30%→70% + 3.8 kWh → capaciteit = 3.8/0.40 = 9.5 kWh, direct na eerste span correct
  - Hoogste prioriteit boven methode A (Wh/SoC) en B (cyclus-mediaan)
  - 0.0% afwijking getest op Zonneplan Nexus 10 kWh profiel

## v5.5.10 (2026-03-29)
- Fix: batterij capaciteit 1.6 kWh ipv 10 kWh in Energie Potentieel kaart
  - BatterySocLearner soms verkeerde capaciteit leren bij Zonneplan Nexus
  - Sanity check: als geleerde capaciteit <2 kWh maar max_discharge >2000W → verwerp
  - Fallback naar battery_capacity_kwh uit hoofdconfig (die staat wel correct op 10 kWh)
  - Energie Potentieel kaart toont nu correcte kWh berekeningen

## v5.5.9 (2026-03-29)
- Fix: Ariston back-off "3x geen respons op turn_on"
  - ARISTON_CMD_DEBOUNCE_S: 600s → 30s (10 minuten wachten was te lang voor boiler sturing)
  - iMemory brug reset back-off teller voor sturen (geen fout, bewuste actie)
  - Op v5.4.97 liep back-off op omdat debounce commando's te lang vasthield

## v5.5.9 (2026-03-29)
- Fix: zone_climate_manager crashte elke seconde op alle zones (1217 fouten in 21 min)
  cop_current is None als warmtepomp nog geen data heeft → float(None) → crash
  Fix: (_cop_raw.get("cop_current") or DEFAULT_COP) vangt ook None en 0 op

## v5.5.8 (2026-03-29)
- CLAUDE_INSTRUCTIONS bijgewerkt: sessie 2026-03-29 volledig gedocumenteerd
- Openstaande items bijgewerkt: HouseConsumptionLearner persistentie, Solar Clipping Forecast, Ghost Power Hunter UI

## v5.5.7 (2026-03-29)
- Nieuw: HouseConsumptionLearner — zelflerend huisverbruik per uurslot (7×24 EMA matrix)
  - Leert weekdag/weekend patroon automatisch via coordinator tick
  - Voorspelt: verwacht totaal vandaag, al verbruikt, nog nodig rest van dag
  - Survival: op basis van geleerd patroon (veel nauwkeuriger dan statisch getal)
    "bij grid uitval overleef je tot 12:50 op batterij + PV"
  - Off-grid kaart toont geleerd forecast sectie zodra model voldoende data heeft
  - sensor.cloudems_home_rest: remaining_kwh, consumed_kwh, total_kwh, survival attrs

## v5.5.6 (2026-03-29)
- Nieuw: cloudems-offgrid-card — Off-Grid Survival Calculator (4 scenario's, batterij + PV balk)
- Nieuw: cloudems-fuse-monitor-card — Groepenkast Bewaking (fase stroom, vrije capaciteit, actieve apparaten)
- Nieuw: cloudems-kosten-calculator-card — Kosten Calculator (tarief, dag/week/maand/jaar, PV besparing)
- Alle 3 nieuwe kaarten in dashboard: Batterij view + Diagnose view
- README volledig herschreven: Mermaid diagrammen, feature matrix, alle nieuwe modules, subtiele cloud roadmap hint

## v5.5.6 (2026-03-29)
- Nieuw: cloudems-offgrid-card — off-grid survival calculator (4 scenario's, batterij + PV)
- Nieuw: cloudems-fuse-monitor-card — live fase-stroom bewaking met ruimte per fase
- Nieuw: cloudems-kosten-calculator-card — vandaag/week/maand/jaar kosten + PV besparing
- Dashboard: alle 5 nieuwe kaarten toegevoegd aan relevante views
- README volledig herschreven: Mermaid architectuurdiagram, feature matrix,
  collapsible secties per module, 18/18 nieuwe features gedocumenteerd

## v5.5.5 (2026-03-29)
- Dashboard: alerts ticker + energie potentieel toegevoegd aan Overzicht view
- Dashboard: energie potentieel toegevoegd aan Warm Water view

## v5.5.4 (2026-03-29)
- Nieuw: cloudems-alerts-ticker-card — roterende meldingen ticker (kritiek→waarschuwing→info)
- Nieuw: cloudems-energie-potentieel-card — batterij + PV als universele rekenmachine
  koken, koffie, vaatwasser, lampen, airco, e-bike, douche, droger, magnetron...
  Aparte sectie per bron (batterij / verwachte PV vandaag)
- Nieuw: Boiler kaart 🚿 Douche tab
  Live sessie, duur/liters/kWh/€/CO₂/flow, fun facts, geschiedenis grafiek
- Beide nieuwe kaarten geregistreerd als Lovelace resource

## v5.5.3 (2026-03-29)
- Fix: Ariston iMemory-brug zet max_setpoint eerst op 75°C voor setpoint instellen
  - Stap 3: max_setpoint → 75°C (of hw_max als lager)
  - Stap 3b: sleep 2s + controleer of max_setpoint bevestigd is door Ariston cloud
  - Stap 4: set_temperature → gewenst setpoint
  - Stap 5: sleep 3s → BOOST
  - Zonder max_setpoint op 75 accepteert Ariston geen setpoints boven de huidige max

## v5.5.2 (2026-03-29)
- Fix: Ariston BOOST accepteert nooit directe temperatuurwijzigingen
  - iMemory-brug nu altijd actief bij BOOST (ook ≤53°C)
  - Volgorde: iMemory → setpoint → sleep 3s → BOOST (erft setpoint over)
  - Als boiler al in iMemory zit → stap 1 overgeslagen, direct setpoint + BOOST
  - Van 58→63°C: iMemory 63°C instellen, dan BOOST → correcte temperatuur

## v5.5.1 (2026-03-29)
- Fix: Ariston BOOST setpoint boven 53°C via iMemory-brug
  - Volgorde: iMemory activeren → setpoint instellen (geen cap) → wacht 3s → BOOST
  - BOOST erft iMemory setpoint automatisch over → boiler verwarmt naar gewenste 58-75°C
  - iMemory watchdog onderbroken zichzelf niet tijdens bewuste tussenstap
- Nieuw: AI stap 2 — BDE._learner = bde_feedback (tariefdrempels zelflerend)
- Nieuw: ShowerTracker — douche-sessie detectie via temperatuurdaling
  - Duur, liters, kosten (€), CO₂, flow L/min
  - Fun facts: militaire douche / prima / lang / erg lang
  - Beschikbaar via sensor.cloudems_boiler_status shower_status attribuut

## v5.5.0 (2026-03-29)
- Fix: "Fouten (ooit)" vervangen door "Fouten (gem. 7d)" — gaat naar 0 na 7 schone dagen
  - Intern blijft de volledige teller bewaard voor logging
  - 7-daags rollend venster: groen=0, oranje=1-5/dag, rood=>5/dag
  - Fouten (uptime) en Fouten (vandaag) blijven als aanvulling

## v5.4.99 (2026-03-29)
- Nieuw: errors_since_uptime en errors_today in versie-kaart
  - LoggingHandler in guardian.py telt CloudEMS ERROR logs — reset bij herstart
  - errors_today reset automatisch om middernacht
  - Versie-kaart toont nu drie rijen: Fouten (ooit) / Fouten (uptime) / Fouten (vandaag)
  - Direct zichtbaar of de huidige versie schoon draait

## v5.4.98 (2026-03-29)
- Fix: drift false positives bij koffiezetter en keukenaapparaten
  - kitchen type naar DRIFT_SKIP_TYPES (koffiezetter, waterkoker, magnetron)
  - baseline_max_w bijgehouden tijdens leren — melding alleen als BUITEN eerder gezien bereik
  - baseline_max_w bevroren na freeze — groeit niet meer mee met drift
  - Resultaat: koffiezetter die soms 1400W trekt terwijl baseline_max 1400W is = geen alert

## v5.4.97 (2026-03-29)
- Fix: zone_climate_manager crashte elke 30s op alle zones — data["heat_pump_cop"] is een dict maar werd direct naar float() gecast. Nu veilig cop_current eruit gelezen.

## v5.4.96 (2026-03-29)
- Fix: demo engine bug DEMO_GHOST_PV_W vs DEMO_GHOST_PV_DELAY_TICKS vergelijking
- Fix: ghost detector dt_s gebruikt nu UPDATE_INTERVAL_FAST als default
- Fix: alle JS kaart-versies gebumpt (67 kaarten) — waren nog op 5.3/5.4.25

## v5.4.95 (2026-03-29)
- Fix: omvormer correlatie per uur i.p.v. gemiddelde ratio
  West/Oost oriëntaties worden correct afgehandeld: ratio op 10:00 ≠ ratio op 15:00
  Growatt Oost piek 12:00 (96% van totaal), GoodWe West piek 15:00 (58% van totaal)
  Schatting GoodWe West op uur 14: 1928W vs echt 1810W (86% confidence)

## v5.4.94 (2026-03-29)
- Uitbreiding StaleSensorEstimator: multi-omvormer correlatie en export inference
  - Multi-omvormer: stale omvormer geschat via ratio t.o.v. werkende omvormer
    (GoodWe West stale + Growatt werkt → GoodWe = totaal × geleerde ratio)
  - Export inference: grid export > bekende productie → onverklaard vermogen berekend
    (export 5kW, solar 2kW → "minstens 3kW onverklaard, waarschijnlijk stale omvormer")
  - Confidence 88-100% bij voldoende correlatie-data

## v5.4.93 (2026-03-29)
- Nieuw: Stale Sensor Estimator — geconfigureerde sensor verliest communicatie → virtuele fallback
  - PV omvormer offline: schatting via geleerd per-uur profiel + weercorrectie
  - Batterij offline: Kirchhoff inference (solar + grid - house)
  - Boiler offline: thermisch afkoelmodel
  - Direct hersteld zodra sensor terugkomt — geen wachttijd
  - Alert: "Omvormer communicatie verloren — schatting actief (X min)"
  - Confidence daalt naarmate sensor langer offline is (max 1 uur)

## v5.4.92 (2026-03-29)
- Nieuw: Ghost Battery Detector — Reverse NILM detecteert onbekende batterijen en omvormers
  - Onbekende omvormer: onverklaard productievermogen dat zonnecurve volgt
  - Onbekende batterij: bidirectionele vermogensstappen gecorreleerd met solar/grid
  - Virtuele SoC bijhouden voor onbekende batterij (integratie via Kirchhoff)
  - Auto-correctie bij ≥68% confidence (min 50 observaties, 2+ dagen)
  - Deactivatie in 3 ticks zodra gebruiker apparaat configureert
  - Demo modus: vergeten 1.5kW omvormer verschijnt live en wordt gedetecteerd
  - CLAUDE_INSTRUCTIONS: Reverse NILM + Edge Device architectuurnotities toegevoegd
- Fix: Kirchhoff batterij triggert direct bij grote export (v5.4.91 doorgevoerd)
- Fix: last_change_ts ipv last_update_ts voor batterij leeftijd (v5.4.90 doorgevoerd)

## v5.4.91 (2026-03-29)
- Fix: batterij Kirchhoff triggert nu direct bij grote export (grid < -500W én export > solar + 500W)
  Export kan fysiek alleen van solar of batterij komen — geen 10s wachten nodig
  Bij laden blijft de 10s drempel behouden (huis kan pieken door oven/inductie)

## v5.4.90 (2026-03-29)
- Fix: Kirchhoff batterij-correctie gebruikte last_update_ts (sensor leeft) in plaats van last_change_ts (waarde veranderd). Nexus stuurt ook updates zonder waarde-wijziging waardoor Kirchhoff nooit triggerde.

## v5.4.89 (2026-03-29)
- Fix: NILM fase na herstart altijd exact hersteld zoals opgeslagen — nooit meer ? als de fase voor herstart bekend was
- Fix: phase_votes minimaal op 5 gezet voor bekende fases zodat relearn-logica niet snel overschrijft

## v5.4.88 (2026-03-29)
- Fix: NILM fase handmatig instelbaar via L1/L2/L3 knoppen in detail panel
  - Persistent: fase_votes krijgt +10 zodat fase ook na herstart bewaard blijft
  - Nieuwe HA service: cloudems.set_nilm_phase (device_name, phase)
  - Voor apparaten die nooit schakelen (Proxmox, NAS, router)

## v5.4.87 (2026-03-29)
- CLAUDE_INSTRUCTIONS: weekend TODO's toegevoegd (AI stap 2, alerts-ticker-card, house_trend logs)

## v5.4.86 (2026-03-29)
- Boiler refactor stap 1: 5 inline magic numbers geëxtraheerd naar benoemde constanten (DEMAND_BOOST_THRESHOLD_MIN/MAX_S, HP_HW_DEADBAND_DEFAULT_C, FALLBACK_SETPOINT_ON/OFF_C). Geen logica gewijzigd.

## v5.4.85 (2026-03-29)
- CLAUDE_INSTRUCTIONS bijgewerkt met product roadmap: demo/multi-instance, cloud migratie, businessmodel (abonnement + no cure no pay), saldering-deadline 2027

## v5.4.84 (2026-03-29)
- Nieuw: Demo modus — simuleer een volledige energie-installatie zonder echte hardware
  - Instelbare tijdversnelling: 1x / 10x / 48x (dag in 30 min) / 96x (dag in 15 min)
  - Virtuele PV-curve, batterij, boiler, EV lader met realistische profielen
  - AI learning gepauzeerd tijdens demo, echte geleerde data onaangetast
  - Kirchhoff gegarandeerd (som = 0) voor alle simulatie-uren
  - Activeren via: CloudEMS → Configureren → Systeem & Communicatie → Demo modus
  - Alle virtuele sensoren verdwijnen automatisch bij uitzetten

## v5.4.83 (2026-03-29)
- Fix: Configuratiefout in alle custom cards door preview:true verwijderd — HA probeerde een preview te renderen zonder hass context wat crashte

## v5.4.82 (2026-03-29)
- Fix: dubbele iconen in alle losse kaarten — hardcoded <span>emoji</span> verwijderd uit 15 kaarten (icoon zat al in c.title)
- Fix: NaN% SoH in batterij levensduur kaart — veilige isNaN check toegevoegd

## v5.4.81 (2026-03-29)
- Fix: Airco / Multisplit staat nu na Klimaatbeheer in het Verbruik & Comfort submenu

## v5.4.80 (2026-03-29)
- Fix: AI n_since_train werd niet opgeslagen bij elke batch — na herstart reset naar 0 waardoor 0/48 bleef staan ondanks groeiende buffer. Nu opgeslagen na elke batch.
- Fix: BDE set_ai_thresholds() had undefined 'learner' variabele — silent crash elke cyclus. _learner wordt nu correct geïnitialiseerd.

## v5.4.79 (2026-03-29)
- ISO kaart verplaatst van hoofddashboard naar dev dashboard (nog niet productieklaar)

## v5.4.78 (2026-03-28)
- Fix: KirchhoffDriftMonitor overschreef data["grid_power"] waardoor NET op 11kW sprong bij grote batterij-ontlading (house_trend liep achter). Grid is altijd P1 — mag nooit overschreven worden.

## v5.4.77 (2026-03-28)
- Fix: Architectuur tab type sections→panel zodat arch card de volledige schermbreedte gebruikt (geen zwarte zijbalken)

## v5.4.76 (2026-03-28)
- Fix: arch card groter — getCardSize 10→14, viewBox hoogte +40px, min-height SVG, alle fonts vergroot (headers 10→12, blok-titels 10→12, sub-tekst 8.5→10, freq 8→9)

## v5.4.75 (2026-03-28)
- Fix: sensor.cloudems_grid_net_power en sensor.cloudems_net_vermogen krijgen _force_update_priority=1 — altijd force_update ongeacht performance mode, zodat de flow card direct na elke P1 update (~1s) de nieuwe gridwaarde toont

## v5.4.74 (2026-03-28)
- Fix: flow card re-rendert nu elke ~100ms bij gewijzigde sensordata (was ~500ms) — minder vertraging na sensorupdate

## v5.4.73 (2026-03-28)
- Fix: spike-filter bewaart nu som=0 — bij negatieve of extreme house_w wordt battery bijgesteld (niet house_trend zonder correctie)

## v5.4.72 (2026-03-27)
- Tooltips uitgebreid: alle nodes tonen nu raw sensorwaarde, update-interval, leeftijd, sensor entity_id, stale-indicator en Kirchhoff-badge (berekend/gemeten)
- sensor.cloudems_energy_balancer: battery_raw_w, solar_raw_w, grid_raw_w, *_age_s, battery_estimated, sensor_* entity_ids toegevoegd

## v5.4.71 (2026-03-27)
- Fix: battery altijd via Kirchhoff berekend zodra meting ouder is dan 10s (was: 112s)
- Fix: data["batteries"] wordt bijgewerkt met gecorrigeerde waarde → som = 0 in flow card
- Nieuw: EMA alpha adapteert aan geleerd sensor-interval (P1 ~1s → alpha=1.0, Nexus ~45s → alpha=0.11)
- Nieuw: house_trend alpha = gemiddelde van grid + solar + battery alpha
- Nieuw: ESPHome 1kHz highres reader gekoppeld aan NILM via feed_highres_batch()

## v5.4.70 (2026-03-27)
- Fix: grid_power_w in coordinator altijd van geconfigureerde sensor (data["grid_power"]), niet meer overschreven door P1 ruwe net_power_w. Dit veroorzaakte onjuiste gridwaarden in de flow card en statuskaart.

## v5.4.7 (2026-03-26)
- Nieuw: Micro-Cycle Prevention — _apply_anti_cycling() nu volledig geïmplementeerd in BDE; blokkeert actiewissels <2 min en richting-flips <anti_cycling_min (veiligheids-acties altijd doorgelaten)
- Nieuw: Negative Price Dumping — BDE laag 2b: ontlaad batterij vóór negatief EPEX-uur zodat maximale laadruimte beschikbaar is bij betaald laden (lookahead 3 uur, drempel -0.5 ct/kWh)
- Nieuw: Open Window Heat-Kill — smart_climate detecteert raam open via temperatuurval >1.5°C in 5 min (geen sensor vereist); activeert ECO_WINDOW preset automatisch
- Nieuw: RL Feedback UI — 👍/👎 knoppen in decisions-learner-card; cloudems.submit_feedback service geregistreerd; feedback naar DecisionOutcomeLearner + AI registry ThresholdLearner
- Nieuw: Voltage Rise Prevention — export_limit_monitor.check_voltage_rise(): 248V licht verlagen, 251V sterk verlagen, 253V stoppen
- Nieuw: Pre-Cooling Strategy — climate_preheat.update_cooling(): pre-koelen bij goedkoop uur + warme dag, koeling beperken bij duur uur
- Uitgebreid: EnergyDispatchPlanner — 12-uurs dispatch-plan als BDE laag 3.4 (pSoC trajectory)
- Uitgebreid: ActuatorWatchdog — battery_scheduler, climate_epex, pool_controller, peak_shaving aangesloten
- Fix: Solar dimmer restore bij herstart — async_setup() roept altijd _restore() aan
- Fix: AI buffer stuck op 24 — ongeldige samples gefilterd bij laden én retrain; n_since_train zichtbaar in AI kaart
- Fix: DLC_VERSION decisions-learner-card gebumpt naar 5.4.7
- Uitgebreid: Self-healing card — nieuwe situaties neg_price_dump, micro_cycle, window_open, voltage_rise

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

## v5.5.467 (2026-04-09)

### Bugfixes battery cards en Zonneplan bridge

**cloudems-battery-overview-card.js** (Week/Gisteren/Vandaag/Morgen kaart):
- SOC verleden uren: toonde altijd `—`. Nu: werkelijke gemeten SOC uit `actual.soc_pct`.
- LADEN/LEVER: toonde `—` (kleur #374151, bijna onzichtbaar). Nu: `0W` in #475569 als waarde 0 is.
- kWh: verleden uren tonen nu energie in kWh (avg W / 1000) voor waarden ≥ 100W.

**cloudems-battery-card.js** (-6u/nu/+6u tabel):
- SOC: toonde `27%→27%` (zelfde waarde). Nu: alleen eindsoc%, `start→end` alleen als ze verschillen.

**zonneplan_bridge.py** (slider sturing):
- CHARGE-pad: `plan_deliver_w > 50` → `>= 0`. Bij laaduur (plan_deliver_w=0) viel slider terug op hardware max (~10000W). Nu schrijft hij 0W.
- DISCHARGE-pad: zelfde fix.
- HOLD-pad: slider werd niet geschreven als waarde 0W was (`and _deliver_target > 0` check). Nu schrijft hij altijd.

## v5.5.468 (2026-04-09)

### Fase-inbalans meldingen gedebounced (24 uur)

**data_quality_monitor.py** — `phase_badge_mismatch` check:
- De melding verscheen elke coordinator-cyclus (~10s) zodra een fase-badge mismatch gedetecteerd werd.
- Nu: melding wordt alleen getoond als de mismatch aaneengesloten 24 uur aanhoudt.
- Patroon: zelfde `_first_seen` debounce als de bestaande `self_cons_zero` check.
- Automatische reset: als de mismatch verdwijnt, reset de timer — bij terugkeer begint de 24 uur opnieuw.

Opmerking: de `phase_advisor` notificaties (HA pop-ups) waren al gelimiteerd op 1×/dag via `ADVISE_COOLDOWN_S = 86400`. Die zijn ongewijzigd.

## v5.5.469 (2026-04-09)

### Battery card en overview card fixes

**cloudems-battery-card.js**:
- SOC: toonde `19%→19%` (end→end volgorde bug). Nu: `_ps0+'%→'+_ps1+'%'` = `10%→19%`. Pijl alleen getoond als start ≠ eind.
- LADEN/LEVER: toonde `—` in kleur #374151 (onzichtbaar). Nu: `0W` in #475569 als waarde 0 of null is.

**cloudems-battery-overview-card.js**:
- SOC: toonde `16% v.14%` (achtersteevoren). Nu: `14%→16%` (start→eind, correct).
- kWh: threshold `>= 100W` verwijderd — alle verleden-uur waarden tonen nu consistent in `0.08 kWh` formaat. Spatie toegevoegd: `0.11 kWh` i.p.v. `0.11kWh`.

## v5.5.470 (2026-04-09)

### Verleden uren: 0W → 0 kWh, PV streepje gefixed

**cloudems-battery-card.js**, **cloudems-battery-overview-card.js**, **cloudems-battery-plan-card.js**:
- Nul-waarden in verleden uren tonen nu `0 kWh` i.p.v. `0W` (eenheid is energie, niet vermogen).
- PV kolom: `—` voor uren zonder zon → `0W` (toekomst) of `0 kWh` (verleden).
- `fmtE` en `fmtKwh` functions: nul geeft nu `0 kWh`.

## v5.5.471 (2026-04-09)

### SOC verleden uren toont nu ook start→eind%

**cloudems-battery-card.js**, **cloudems-battery-overview-card.js**, **cloudems-battery-plan-card.js**:
- SOC voor verleden uren toonde alleen het eindgetal. Nu: `start%→eind%` als de coordinator beide waarden kent (soc_start geketend van vorig uur, soc_end = gemeten).
- Logica uniform in alle drie kaarten: `_ps0 !== _ps1 → start→eind`, anders alleen eind.

## v5.5.472 (2026-04-09)

### PV streepje gefixed — Temporal Dead Zone bug

**cloudems-battery-card.js**:
- `_zero` werd op regel 353 gedeclareerd maar al gebruikt op regel 346 (vóór declaratie).
- In JavaScript veroorzaakt dit een "Cannot access before initialization" TDZ fout → PV toonde altijd `—`.
- Fix: `_zero` verplaatst vóór `pvDisp` zodat de volgorde klopt.
- Resultaat: PV toont nu `0W` (toekomst) of `0 kWh` (verleden) bij nul-waarden.

## v5.5.473 (2026-04-09)

### Simultaan laden+ontladen zichtbaar + countdown timer gefixed

**cloudems-battery-card.js**:
- netW filter verwijderd: LADEN en LEVER worden nu onafhankelijk getoond. Als het plan zegt "laad 300W EN lever 1100W", tonen beide kolommen hun waarde — niet één van de twee op basis van netto richting.
- Countdown timer: `<span class="zp-cd">wachten</span>` werd elke 10s gereset door set hass() innerHTML rebuild, waardoor "· Xs" nooit stabiel zichtbaar was. Fix: template gebruikt nu direct `window._zpCd` zodat elke render de huidige waarde toont.

## v5.5.474 (2026-04-09)

### Countdown timer altijd zichtbaar

**cloudems-battery-card.js**:
- Countdown was alleen zichtbaar bij |plan - slider| > 50W. Als sliders al kloppen → geen element → nooit zichtbaar.
- Nu altijd zichtbaar: bij mismatch oranje "wachten · Xs", bij match groen "✓ plan · Xs".
- `.zp-cd` span aanwezig in beide staten zodat de setInterval altijd iets kan updaten.

## v5.5.475 (2026-04-09)

### Morgen-plan: SOC headroom controle toegevoegd

**coordinator.py** — `schedule_tomorrow` plan builder:
- `_exp_dis = min(_deficit_t, _del_t)` miste SOC headroom check. Bij SOC=10% (minimum) werd toch 1244W discharge gepland terwijl de accu leeg is. SOC werd dan geclamped op 10% maar LEVER bleef hoog.
- Fix: `_headroom_t = max(0, (_sim_t - _min_t)/100 * _cap_t * 1000)` nu toegepast op zowel deficit-branch als high-branch.
- PV=0W morgen: data-beschikbaarheidsissue — omvormer stuurt morgen's forecast pas later op de dag. Geen codebug.

## v5.5.476 (2026-04-09)

### Morgen-plan: PV forecast en SOC headroom gefixed

**coordinator.py** — `schedule_tomorrow` plan builder:

PV forecast morgen — twee bugs:
1. Eerste loop zocht `day=='tomorrow'` in `pv_forecast_hourly` — maar die entries hebben geen `day` field. Nooit een treffer. Loop verwijderd.
2. Tweede loop gebruikte `=` i.p.v. `+=` — bij meerdere omvormers overschreef elke omvormer de vorige. Nu worden alle omvormers per uur gesommeerd.
3. Extra fallback: solar_learner.get_forecast_tomorrow() als pv_forecast_hourly_tomorrow leeg is.

SOC headroom in deficit-branch: `_exp_dis = min(_deficit_t, _del_t)` → nu `min(_deficit_t, _del_t, _headroom_t)`.

## v5.5.477 (2026-04-09)

### Slider label "Solar laden" → "Laden (max)"

**cloudems-battery-card.js**:
- "Solar laden" is misleidend — de slider bepaalt de maximale laadsnelheid ongeacht bron (zon of net bij goedkoop tarief). Hernoemd naar "Laden (max)".
- "Levering thuis" blijft ongewijzigd — dat is wél een correcte omschrijving.

## v5.5.478 (2026-04-09)

### Battery-card: verleden uren LADEN/LEVER/PV in kWh

**cloudems-battery-card.js**:
- LADEN en LEVER toonden verleden-uur waarden in W (`61W`, `106W`). Nu in kWh (`0.06 kWh`, `0.11 kWh`).
- PV verleden uren: zelfde fix.
- `fmtE` functie toegevoegd (zelfde als overview-card): `w > 0 → (w/1000).toFixed(2)+' kWh'`.
- Nul-waarden tonen `0 kWh` voor verleden, `0W` voor toekomst.

## v5.5.479 (2026-04-09)

### Battery-card: kWh ook als actual ontbreekt voor verleden uren

**cloudems-battery-card.js**:
- `chgDisp = isPast && actual ? actChg : chgW` — als `actual` null is (uur nog niet in _hourly_actual), viel het terug op `chgW` met W-eenheid.
- Fix: `isPast` alleen bepaalt de eenheid. `chgVal > 0 → isPast ? fmtE(chgVal) : chgVal+'W'`.
- Rij 18:00 met `LADEN=106W` toont nu `0.11 kWh`.

SOC enkelvoudige waarden zijn correct: als soc_start=soc_end (afgerond) was er geen SOC-verandering in dat uur (bijv. 106W laden in 9.3kWh accu = 1.1% → afgerond 1% verschil, soms 0%).

## v5.5.480 (2026-04-09)

### Slider EMA verwijderd — raw P1 voor huidig-uur plan

**coordinator.py**:
- `_slider_house_ema` met α=0.05 had een tijdconstante van ~3 minuten. Bij een sprong van 400W naar 1883W stuurde de slider 1027W terwijl het plan 1862W toonde.
- De EMA was bedoeld om thrashing te voorkomen, maar de CloudCommandQueue (15s debounce + rate limiting) doet dat al.
- Fix: huidig uur gebruikt nu direct de raw P1 house_load_w. Tabel en slider zijn nu consistent.

## v5.5.481 (2026-04-09)

### Verleden-uur kWh afgeleid van SOC × capaciteit

**cloudems-battery-card.js** + **cloudems-battery-overview-card.js**:
- `bat_w` sensor van de Nexus kan afwijken door Kirchhoff correcties → toonde 0 kWh terwijl SOC 87%→18% (=6.4 kWh discharge) zichtbaar was.
- Fix: voor verleden uren wordt LADEN en LEVER nu berekend als `SOC_delta / 100 × capaciteit_kWh`.
  - Discharge kWh = max(0, soc_start - soc_end) / 100 × cap
  - Charge kWh = max(0, soc_end - soc_start) / 100 × cap
- Fallback naar bat_w als SOC delta niet beschikbaar is.
- Capaciteit: `capKwh` uit `sensor.cloudems_battery_savings.attributes.capacity_kwh` (default 9.3 kWh).

## v5.5.482 (2026-04-09)

### Nieuwe NETTO kWh kolom — LADEN/LEVER terug naar W

**cloudems-battery-card.js**:
- LADEN en LEVER: altijd W (gemiddeld vermogen van dat uur, past én toekomst).
- Nieuwe NETTO kolom (tussen LEVER en PV): netto energie kWh met teken.
  - Verleden: `(soc_end - soc_start)/100 × capaciteit_kWh` (meest betrouwbaar). Positief=geladen, negatief=ontladen.
  - Toekomst: `power_w/1000` uit het plan (= charge_w - discharge_w).
- Kleur: groen (+kWh = netto geladen), oranje (−kWh = netto ontladen), grijs (≈0).

## v5.5.483 (2026-04-09)

### LADEN/LEVER verleden uren consistent met NETTO

**cloudems-battery-card.js**:
- Probleem: bat_w sensor toonde 0W maar SOC delta gaf 6.42 kWh discharge → LEVER=0W maar NETTO=-6.42 kWh (onmogelijk).
- Fix: LADEN en LEVER voor verleden uren worden nu afgeleid van NETTO (= SOC delta × cap):
  - NETTO < 0 (netto ontladen): LEVER = |netto_W| W, LADEN = 0W
  - NETTO > 0 (netto geladen): LADEN = netto_W W, LEVER = 0W
- Alle drie kolommen (LADEN, LEVER, NETTO) zijn nu intern consistent.
- Toekomst uren: ongewijzigd (charge_w / discharge_w uit plan).

## v5.5.484 (2026-04-09)

### LADEN/LEVER: echte gemiddelden uit coordinator accumulator

**coordinator.py**:
- `_hourly_acc` accumuleert nu apart: `chg` (alleen bat_w > 10W) en `dis` (alleen |bat_w| < -10W).
- Bij uur-overgang: `chg_w` = gemiddeld laadvermogen (alleen tijdens laden), `dis_w` = gemiddeld ontlaadvermogen (alleen tijdens ontladen).
- Beide waarden zitten nu in `_hourly_actual[h]` beschikbaar voor JS kaarten.

**cloudems-battery-card.js**:
- LADEN (verleden): `actual.chg_w` — werkelijk gemiddeld laadvermogen van dat uur.
- LEVER (verleden): `actual.dis_w` — werkelijk gemiddeld ontlaadvermogen van dat uur.
- NETTO: ongewijzigd (SOC delta × capaciteit).
- Alle drie zijn nu onafhankelijk en kunnen alle drie tegelijk een waarde hebben.

## v5.5.485 (2026-04-09)

### Alle drie kaarten consistent met chg_w/dis_w accumulator

**cloudems-battery-overview-card.js** + **cloudems-battery-plan-card.js**:
- Zelfde fix als 5.5.484 voor battery-card: LADEN en LEVER voor verleden uren gebruiken nu `actual.chg_w` en `actual.dis_w` uit de coordinator accumulator.
- Fallback naar `bat_w` voor uren vóór 5.5.484.

## v5.5.486 (2026-04-09)

### Configuratiefout gefixed + SOC altijd start→eind

**cloudems-battery-card.js**:
- Configuratiefout: NETTO kolom stond in de header maar `${nettoStr}` ontbrak in de rij-template. Header en rij waren niet gesynchroniseerd → crash bij renderen.
- SOC: `_ps0 !== _ps1` check verwijderd — altijd `start%→eind%` tonen ook als waarden gelijk zijn.

**cloudems-battery-overview-card.js** + **cloudems-battery-plan-card.js**:
- SOC: zelfde fix — altijd `start%→eind%` tonen.

## v5.5.487 (2026-04-09)

### NETTO: geen bat_w fallback, altijd kWh, — bij geen data

**cloudems-battery-card.js**:
- NETTO verleden: `actual.bat_w` fallback verwijderd — bat_w heeft sign-flip issues (Kirchhoff). Als geen SOC data → toont '—' i.p.v. een verkeerde waarde.
- NETTO toekomst/huidig: `s.power_w / 1000` altijd in kWh formaat ('+1.10 kWh' of '−1.10 kWh').
- Drempel verlaagd van 0.01 naar 0.005 kWh zodat kleine waarden zichtbaar zijn.

## v5.5.488 (2026-04-09)

### NETTO: altijd SOC delta × capaciteit

**cloudems-battery-card.js**:
- NETTO is voor elk uur hetzelfde: `(soc_end - soc_start) / 100 × capaciteit_kWh`.
- Verleden: soc_start/soc_end uit meting (_hourly_actual).
- Huidig en toekomst: soc_start/soc_end uit plan-simulatie.
- Geen bat_w, geen power_w meer — één betrouwbare formule voor alle uren.
- Groen = netto geladen, oranje = netto ontladen, grijs = geen data (—).

## v5.5.489 (2026-04-09)

### Uitlijning, HUIS, SOC gefixed

**cloudems-battery-card.js**:
- NETTO toonde '—' als soc_start/soc_end ontbrak → kolom onzichtbaar → PV leek in NETTO-positie → HUIS leek leeg. Fix: NETTO toont nu altijd '0 kWh' als geen data (grijs), nooit '—'.
- SOC: als soc_start null is maar actual.soc_pct beschikbaar → gebruik dat als fallback. Zo toont 18:00 altijd start→eind ook als soc_start niet in het plan staat.

## v5.5.491 (2026-04-09)

### SOC grenspunten — simpel en correct

**coordinator.py**:
- `soc_pct` in `_hourly_actual` was het gemiddelde van alle samples dat uur. Nu: **laatste sample** van het uur. Dat is het grenspunt: einde van dit uur = begin van het volgende.
- `soc_start` voor een uur = `soc_end` van het vorige uur (= grenspunt). Nooit een fallback naar het huidige uur's gemiddelde.
- Resultaat: nooit meer single SOC values — elke uur heeft altijd een begin én eindwaarde.
- NETTO = `(soc_end - soc_start) / 100 × capaciteit` is nu ook altijd correct.

## v5.5.498 (2026-04-10)

### kWh accumulatie: ruwe Nexus waarde ipv Kirchhoff-gecorrigeerd

**coordinator.py**:
- `battery_raw_w` wordt nu opgeslagen in `data` direct na spike-filter maar vóór Kirchhoff-correctie.

**sensor.py** — `CloudEMSBatteryPowerSensor._accumulate()`:
- Gebruikt nu `battery_raw_w` als beschikbaar i.p.v. de Kirchhoff-gecorrigeerde `batteries[].power_w`.
- Kirchhoff-correctie past de waarde aan voor energiebalans-berekeningen maar de Nexus interne Wh-teller (en Zonneplan app) meet de werkelijke accu-stroom — niet de balancer-schatting.
- Verwacht: `charge_kwh_today` en `discharge_kwh_today` komen nu overeen met Zonneplan statistieken.

GitHub issue #50 (Roodie84): zelfde probleem bevestigd.

## v5.5.499 (2026-04-10)

### kWh bronnen: accu-sensoren als primaire bron

**config_flow.py** — `battery_detail` stap:
- Twee nieuwe velden: `bat_charge_kwh_sensor` en `bat_discharge_kwh_sensor`.
- Auto-detect (stap 5 in auto_detect): zoekt bekende patronen zoals `charged_kwh`, `energy_charged`, `discharged_kwh` etc. in HA entity registry.
- Nexus-specifiek: Zonneplan integratie publiceert deze sensoren automatisch.

**sensor.py** — `CloudEMSBatteryPowerSensor`:
- Prioriteit kWh-accumulatie:
  1. Geconfigureerde accu-sensoren (`charge_kwh_sensor` / `discharge_kwh_sensor`) → direct lezen, geen berekening
  2. `battery_raw_w` (ruwe Nexus waarde, vóór Kirchhoff) → zelf accumuleren
  3. `total_w` (Kirchhoff-gecorrigeerd) → fallback als niets anders beschikbaar

GitHub issue #50 (Roodie84): fix voor systematische afwijking t.o.v. Zonneplan statistieken.

## v5.5.500 (2026-04-10)

### kWh sensoren ook in options flow

**config_flow.py** — `battery_detail_opts` stap (options flow):
- Zelfde `bat_charge_kwh_sensor` / `bat_discharge_kwh_sensor` velden toegevoegd als in de setup wizard.
- Bestaande waarden worden hersteld uit config (`existing.get(...)`).
- Samenvatting:
  - Setup wizard: `battery_detail` → kWh sensor velden + auto-detect
  - Options flow: `battery_detail_opts` → zelfde velden, bestaande waarden hersteld
  - Sensor: leest sensors direct (prio 1), raw_w (prio 2), Kirchhoff (prio 3)

## v5.5.500 (2026-04-10)

### kWh bronnen: 4-niveau prioriteit + Nexus entity map uitgebreid

**zonneplan_bridge.py**:
- Entity map uitgebreid met `charged_today` en `discharged_today` (bekende sensor-namen voor meerdere accu-merken).
- `get_info()` exposed `charged_today_kwh` en `discharged_today_kwh` zodat coordinator deze kan doorgeven.

**sensor.py** — 4-niveau kWh-bron prioriteit:
1. Geconfigureerde HA-sensoren (`bat_charge_kwh_sensor` / `bat_discharge_kwh_sensor`) → meest nauwkeurig
2. Bridge entity map (`charged_today` / `discharged_today`) → automatisch als Nexus/accu deze levert
3. `battery_raw_w` (ruwe sensor vóór Kirchhoff) → zelf accumuleren
4. `total_w` (Kirchhoff-gecorrigeerd) → laatste fallback

**config_flow.py**:
- `battery_detail` stap: twee nieuwe optionele velden voor kWh-sensoren.
- Auto-detect: zoekt automatisch bekende kWh-sensor patronen in entity registry.

## v5.5.501 (2026-04-10)

### PV kWh: energy_sensor als primaire bron (issue #49)

**coordinator.py**:
- PV kWh accumuleerde via `W × tijd` — zelfde probleem als bij de batterij (issue #50).
- Fix: elke cyclus wordt de `energy_sensor` van elke omvormer uitgelezen (kWh vandaag).
- Als de sensor beschikbaar is, wordt de uur-verdeling herschaald naar het werkelijke totaal.
- Ondersteunt Wh én kWh sensoren (automatische conversie op basis van `unit_of_measurement`).
- Werkt voor alle bekende omvormers: SolarEdge, Huawei, Growatt, GoodWe, SMA, Fronius etc.
- De `energy_sensor` was al configureerbaar in de wizard maar werd nooit gebruikt voor correctie.

GitHub issue #49 (Roodie84): PV forecast/werkelijk klopt niet.

## v5.5.502 (2026-04-10)

### EnergySourceManager — generieke kWh-bronbeheerder

**energy_manager/energy_source_manager.py** (nieuw):
- Generieke klasse die kWh-sensoren leest voor alle apparaattypen.
- Prioriteit: sensor (device-intern, overleeft herstart) → berekening (fallback).
- Auto-detect per categorie: pv, battery_charge, battery_discharge, grid_import, grid_export, device.
- Eenheidsconversie: kWh, Wh, MWh, kJ, J automatisch omgezet.
- `auto_detect_all()`: scant alle geconfigureerde apparaten en stelt sensoren voor.

**coordinator.py**:
- Initialiseert `_energy_source_mgr` dict bij setup voor alle geconfigureerde sensoren.

**config_flow.py** — `sensors` stap:
- Twee nieuwe velden: `grid_import_kwh_sensor` en `grid_export_kwh_sensor`.
- Auto-detect: `EnergySourceManager.auto_detect_all()` scant PV, batterij, grid en NILM.
- Sensors stap: gebruiker kan kWh-sensoren instellen voor grid import/export.

Architectuurprincipe: apparaat-interne kWh tellers overleven herstarts en zijn nauwkeuriger
dan W×t accumulatie. Berekening blijft altijd beschikbaar als fallback.

## v5.5.503 (2026-04-10)

### EnergySourceManager: dagelijks reset vs cumulatief

**energy_manager/energy_source_manager.py**:
- Twee sensortypen herkend:
  - `daily_reset`: sensor reset zelf elke dag naar 0 (omvormer energy_today, accu geladen_vandaag) → direct lezen
  - `cumulative`: sensor telt oneindig op (P1 netmeter, lifetime accu-teller) → delta = huidig − dag_start
- Type-detectie via: HA `state_class` (meest betrouwbaar), daarna entity_id patronen
- Negatieve delta (sensor reset of terugzetting) wordt opgevangen met automatische dag-start reset
- `restore_day_start()`: herstel na HA herstart vanuit persistente opslag
- `get_persist_state()`: geeft persisteerbare staat voor opslag

**coordinator.py**:
- `_store_esm_state`: nieuwe persistente opslag voor dag-startwaarden
- Bij setup: herstel dag-startwaarden van alle ESM instanties
- Elke 60s: sla dag-startwaarden op (zelfde cyclus als anchor_kwh)

## v5.5.504 (2026-04-10)

### HistoricalBootstrapper — betrouwbaar vanaf dag 1

**energy_manager/historical_bootstrapper.py** (nieuw):
- Laadt historische sensordata vanuit HA recorder statistics API.
- Voedt alle CloudEMS learners met historische data zodat het systeem direct accuraat is.
- Categorieën en terugkijkperiode:
  - PV productie: 365 dagen (seizoenspatroon voor zonne-forecast)
  - Huisverbruik: 90 dagen (weekpatroon voor HouseConsumptionLearner)
  - Grid import/export: 90 dagen
  - Batterij laden/ontladen: 30 dagen
  - NILM apparaten: 30 dagen
- Dagelijkse waarden voor cumulatieve sensoren: delta = max - min per uur-groep
- Veilig om meerdere keren aan te roepen via `_done` set

**coordinator.py**:
- `_run_historical_bootstrap()`: gestart 30s na setup (wacht op volledige initialisatie)
- Bootstrap voedt: PV forecast learner, HouseConsumptionLearner, NILM device learner
- Werkt voor alle geconfigureerde energy_sensor, charge_kwh_sensor, grid_*_kwh_sensor

## v5.5.505 (2026-04-10)

### Batterijgezondheid, kwaliteitsindicatoren, sensor fingerprinting, PV clipping

**energy_manager/battery_health.py** (nieuw):
- BatteryHealthTracker: round-trip efficiëntie, SoH, equivalente cycli
- Werkelijke capaciteit vs rated op basis van kWh metingen

**energy_manager/sensor_quality.py** (nieuw):
- SensorQualityMonitor: per categorie 'sensor'/'calculated'/'estimated'/'missing'
- Setup score 0-100% met issues en verbeterpunten

**energy_manager/sensor_fingerprint.py** (nieuw):
- SensorFingerprinter: herkent 15+ omvormermerken, 7+ batterijmerken, 4+ grid meters
- Stelt automatisch correcte kWh-sensoren voor per merk

**energy_manager/pv_clipping.py** (nieuw):
- PVClippingDetector: detecteert wanneer omvormer limiteert op AC-maximum
- Markeert clipping-uren voor betere forecast learning (niet trainen op geclipte data)

**coordinator.py**:
- Initialiseert alle vier managers bij setup
- BatteryHealthTracker per batterij config
- SensorFingerprinter voor wizard hints
- PVClippingDetector per omvormer met max_ac_power_w config

**cloudems-battery-card.js**:
- Data kwaliteitsbadge: ● sensor / ◐ berekend / ○ geschat / ✕ ontbreekt
- Setup score badge in header
- Round-trip efficiëntie: werkelijk gemeten i.p.v. berekend

## v5.5.506 (2026-04-10)

### kWh sensoren in alle wizard/flow stappen

**config_flow.py** — kWh sensor velden toegevoegd/hersteld per stap:

| Stap | Nieuw veld | Al aanwezig |
|------|-----------|-------------|
| `inverter_detail` (wizard) | `max_ac_power_w` (clipping) | `energy_sensor` ✓ |
| `inverter_detail_opts` (opties) | `energy_sensor`, `max_ac_power_w` | — |
| `battery_detail` (wizard) | `charge_kwh_sensor`, `discharge_kwh_sensor` | ✓ |
| `battery_detail_opts` (opties) | `charge_kwh_sensor`, `discharge_kwh_sensor` | ✓ |
| `sensors` (opties) | `grid_import_kwh_sensor`, `grid_export_kwh_sensor` | ✓ |
| `ev_charger_detail` (wizard) | `energy_sensor` | — |
| Boiler `bu_*` | — | `energy_sensor` ✓ |

Nexus: automatisch geconfigureerd via managed battery — geen handmatige actie nodig.

## v5.5.507 (2026-04-10)

### DSMR T1/T2 tarieven + nette labels voor alle kWh velden

**config_flow.py** — `sensors` stap:
- Grid kWh: 2 velden → 4 velden voor DSMR T1/T2 per tarief:
  - "Import kWh — Tarief 1 (laag/nacht)"
  - "Import kWh — Tarief 2 (hoog/dag)"
  - "Export kWh — Tarief 1 (laag/nacht)"
  - "Export kWh — Tarief 2 (hoog/dag)"
- Legacy `grid_import/export_kwh_sensor` velden blijven werken als fallback

**energy_manager/energy_source_manager.py**:
- T1/T2 DSMR auto-detect patronen toegevoegd (tarief_1, tariff1, delivered_tariff1, etc.)
- `sum_t1_t2()` helper: telt T1+T2 op voor totaal dagbedrag

**coordinator.py**:
- Grid ESM initialiseert nu 4 managers (import_t1, import_t2, export_t1, export_t2)
- Legacy single sensor fallback behouden

**translations** (7 talen):
- Alle nieuwe veldnamen hebben nu een nette label in NL, EN, DE en via fallback voor DA/FI/FR/IT/NB/PL/PT/SV

## v5.5.508 (2026-04-10)

### Log fixes: translation fout, entity spam, performance

**translations** (6 talen):
- `battery_type_opts.description` bevatte `{detected_hint}` placeholder maar die werd nooit meegegeven → formatjs MISSING_VALUE error bij elke render van de wizard. Placeholder verwijderd uit alle vertalingen.

**config_flow.py**:
- `detected_hint` alsnog toegevoegd aan `description_placeholders` van `battery_type_opts` voor beide flows (setup + opties).

**ha_provider.py**:
- Entity's die niet in de HA state machine staan (bijv. bij herstart) logden WARNING per service call → spam van 8+ berichten. Downgraded naar DEBUG want dit is normaal gedrag bij opstarten.
- Entities die echt niet bestaan (na grace period) blijven WARNING loggen.

## v5.5.509 (2026-04-10)

### kWh velden: (optioneel) labels + auto-detect werkt nu

**config_flow.py** — `sensors` stap:
- T1/T2 velden gebruiken nu `default=` i.p.v. `description=` → HA vult waarden in.
- Auto-detect via `EnergySourceManager.auto_detect_all()` wordt aangeroepen bij openen van de stap en vult gevonden sensoren direct in als default waarde.
- Fallback volgorde: opgeslagen config → auto-detect → legacy veld → leeg

**translations** (8 talen):
- Alle optionele kWh sensor velden krijgen "(optioneel)" label:
  - "Import kWh — Tarief 1 (laag/nacht) (optioneel)"
  - "Dagproductie sensor (kWh) (optioneel)"
  - "Batterij geladen kWh sensor (optioneel)"
  - etc.

## v5.5.510 (2026-04-10)

### Extra sensoren & Omgeving — nieuwe wizard stap

**config_flow.py** — nieuwe stap `extra_sensors_opts`:
- Bereikbaar via Instellingen → CloudEMS → "🌡️ Extra sensoren & Omgeving"
- Auto-detect via HA device_class: temperature, irradiance, wind_speed, precipitation, carbon_dioxide, frequency, water
- 10 optionele sensoren met netjes label + (optioneel):

| Sensor | Gebruikt voor |
|--------|--------------|
| Buitentemperatuur | Rolluiken, WKK stooklijn, thermisch model, PV temp correctie |
| PV paneel temperatuur | PV forecast temperatuurcorrectie (+15% nauwkeuriger) |
| Batterij temperatuur | Degradatiemodel, laadbeperking <5°C |
| Irradiantie / pyranometer | Directe stralingsmeting → beste PV forecast |
| Windsnelheid | FCR inkomsten schatting, ventilatie koeling, WKK |
| Neerslag | PV reinigingsadvies, paneel output correctie |
| CO₂ buiten/binnen | Ventilatie koppeling, luchtkwaliteit dashboard |
| Netfrequentie | FCR deelname nauwkeuriger |
| Watermeter | Totale energierekening, lekdetectie |

**coordinator.py**:
- `_read_extra_sensor()`: generieke helper voor optionele sensoren
- Alle 9 nieuwe sensorwaarden beschikbaar in `data` dict voor alle subsystemen

## v5.5.511 (2026-04-10)

### Windsnelheid: echte sensor + stormbescherming rolluiken

**config_flow.py** — rolluiken setup (`shutter_count` stap):
- Windsnelheid sensor (optioneel) — voor echte meting i.p.v. weersvoorspelling
- Stormdrempel (m/s, default 12 m/s = Beaufort 6) — rolluiken gaan automatisch omhoog

**coordinator.py**:
- Rolluiken, PV-dip detector en PV forecast gebruiken nu echte windsensor als geconfigureerd
- Prioriteit: echte sensor → weersvoorspelling (API)
- Stormbescherming: bij overschrijding drempel → rolluiken omhoog + WARNING in log

Opmerking: wind was al aanwezig als weersforecast (API) maar nooit als echte sensor.
De rolluiken hadden al rook + temperatuursensor maar het meest kritische (storm!) ontbrak.

## v5.5.512 (2026-04-10)

### EnvironmentalProcessor + MultidayPlanner

**energy_manager/environmental_processor.py** (nieuw):
- Irradiantie: real-time PV forecast correctie + soiling factor tracking
- Regen: paneel-reinigingsdetectie (>2mm → soiling factor omhoog)
- Batterijtemperatuur: laadbeperking LFP tabel (<0°C stop, 0-5°C 20%, 5-10°C 50%)
- PV paneel temperatuur: vermogenscorrectie (-0.35%/°C boven 25°C)
- CO₂: ventilatie aanbeveling bij >1000 ppm (🌬️), urgent bij >1500 ppm
- Water: nacht-lekdetectie (>5L per kwartier tussen 23:00-06:00)

**energy_manager/multiday_planner.py** (nieuw):
- Analyseert EPEX prijzen voor vandaag + morgen + overmorgen
- SOC-doelen per dag-einde: hoog als morgen duur, laag als morgen goedkoop
- Cross-day advies: "Morgen goedkoper → vandaag minder laden"
- Goedkoopste laaduren en duurste ontlaaduren per dag

**coordinator.py**:
- EnvironmentalProcessor.process_all() elke cyclus → resultaten in data["environmental"]
- Batterijlaadlimiet automatisch verlaagd bij extreme temperatuur

## v5.5.513 (2026-04-10)

### Nexus kWh sensoren: correcte detectie en auto-configuratie

**Root cause**: Zonneplan integratie gebruikt `state_class=TOTAL_INCREASING` voor
`delivery_day` en `production_day`, maar dit zijn dagwaarden die om middernacht resetten.
EnergySourceManager interpreteerde ze daardoor als cumulatief → verkeerde delta berekening.

**energy_manager/energy_source_manager.py**:
- Detectievolgorde omgedraaid: entity_id patronen eerst, state_class daarna
- `_DAILY_PATTERNS` uitgebreid met Zonneplan patronen: `delivery_day`, `production_day`,
  `levering_vandaag`, `productie_vandaag`
- Auto-detect battery patronen: `production_day` → charge, `delivery_day` → discharge
- Resultaat: sensoren worden nu als `daily_reset` behandeld → correcte directe lezing

**config_flow.py** — managed battery Zonneplan setup:
- Bij aanmaken Nexus batterij config: automatisch zoeken naar `production_day` en
  `delivery_day` in entity registry → direct invullen als kWh-sensoren
- Werkt voor alle installaties ongeacht `contract["label"]` naam

Na herstart of herinstallatie: kaart toont 4,58 kWh geladen / 5,45 kWh ontladen.

## v5.5.514 (2026-04-10)

### ZonneplanP1Bridge — volledige Zonneplan integratie als databron

**energy_manager/zonneplan_p1_bridge.py** (nieuw):
- Leest alle bruikbare data uit de Zonneplan HA integratie automatisch
- Fallback voor grid/P1: gebruikt Zonneplan P1 meter data als geen DSMR geconfigureerd
- Fallback voor PV: `sensor.zonneplan_last_measured_value` → solar_power
- Fallback voor prijs: `sensor.zonneplan_current_electricity_tariff`
- Aanvulling kWh dag totalen (worden altijd ingevuld naast andere bronnen)

**Beschikbare data via Zonneplan:**

| Zonneplan sensor | CloudEMS veld | Gebruik |
|-----------------|---------------|---------|
| `electricity_consumption` | `grid_power` (import W) | Fallback P1 |
| `electricity_production` | `grid_power` (export W) | Fallback P1 |
| `electricity_total_today` | `zp_grid_import_kwh_today` | kWh dag |
| `electricity_total_today_returned` | `zp_grid_export_kwh_today` | kWh dag |
| `last_measured_value` | `solar_power` | Fallback PV |
| `yield_today` | `zp_pv_kwh_today` | kWh dag |
| `power` (battery) | Batterij vermogen | Aanvulling |
| `state_of_charge` | Batterij SOC | Aanvulling |
| `production_day` | `zp_bat_charged_kwh_today` | kWh dag |
| `delivery_day` | `zp_bat_discharged_kwh_today` | kWh dag |
| `current_electricity_tariff` | `current_price_eur_kwh` | Fallback prijs |

**coordinator.py**:
- Detecteert Zonneplan integratie bij startup automatisch
- `fill_missing()` vult ontbrekende velden aan zonder bestaande data te overschrijven
- Werkt ook voor gebruikers die alleen Zonneplan P1 meter hebben (geen eigen DSMR)
- Ideale basis voor cloud variant: alle data via Zonneplan API

## v5.5.515 (2026-04-10)

### Label audit: alle optionele sensoren hebben nu (optioneel)

**translations** (8 talen — 64 + 8 = 72 labels gecorrigeerd):
- Systematische audit: alle optionele sensoren in alle stappen in alle talen
- Gecorrigeerde stappen: inverter_detail, inverter_detail_opts, battery_detail,
  battery_detail_opts, ev_charger_detail, sensors, extra_sensors_opts,
  shutter_count, shutter_count_opts, advanced_opts
- Velden: inv_energy_sensor, inv_max_ac_power, bat_charge/discharge_kwh_sensor,
  ev_energy_sensor, grid_import/export_kwh_t1/t2, alle omgevingssensoren

## v5.5.516 (2026-04-10)

### Lovelace storage corruptie fix

**Oorzaak**: HA meldt "Input is a zero-length, empty document" voor `lovelace.cloudems-lovelace`.
Dit ontstaat als CloudEMS het storage bestand schrijft maar er dan een crash/herstart tussendoor komt,
of als twee processen tegelijk schrijven.

**__init__.py** — `_async_ensure_lovelace_dashboard()`:
- **Atomic write**: schrijft naar `.tmp` bestand, valideert de JSON, dan pas `replace()` (atomair op Linux)
- **Lege YAML guard**: als dashboard YAML leeg of `None` is → skip met WARNING, overschrijf bestaand storage niet
- **JSON validatie**: vóór rename wordt de geschreven JSON teruggelezen en gevalideerd
- **Lege JSON guard**: als de te schrijven JSON leeg is → skip met WARNING

Gebruikers die de repair-melding zien: klik "Verzenden" om te bevestigen dat HA het lege bestand
hernoemd heeft. CloudEMS schrijft daarna een geldig dashboard bij de volgende herstart.

## v5.5.517 (2026-04-10)

### Dashboard herstel na HA repair

**__init__.py** — `_async_ensure_lovelace_dashboard()`:
- Detecteert nu of het bestaande storage bestand geen CloudEMS views bevat
  (bijv. na HA repair → reset naar lege "Nieuwe sectie" view)
- Bij detectie: WARNING in log + dashboard wordt hersteld vanuit YAML
- Hersteld dashboard triggert ook live reload zodat browser direct de juiste views toont

**Herstelprocedure na storage corruptie:**
1. Klik "Verzenden" op de HA repair melding
2. Installeer 5.5.517
3. Herstart HA — CloudEMS detecteert het lege dashboard en herstelt het automatisch

## v5.5.518 (2026-04-10)

### Nexus kWh: runtime auto-detect voor bestaande installaties

**Root cause**: bestaande installaties hebben `charge_kwh_sensor` en `discharge_kwh_sensor`
niet in hun `battery_configs` omdat die velden pas later toegevoegd zijn.
De config wordt opgeslagen in HA en is niet automatisch bijgewerkt.

**coordinator.py** — ESM setup:
- Als `charge_kwh_sensor` leeg is voor een Nexus batterij: zoekt automatisch naar
  `production_day` en `delivery_day` sensoren in de HA entity registry
- Schrijft gevonden sensoren terug naar de bat config in memory zodat sensor.py ze ook vindt
- Logt gevonden sensoren als INFO voor debugging

**sensor.py** — native_value:
- Als `charge_kwh_sensor` leeg is: kijkt ook in `coordinator._energy_source_mgr`
  voor bat_chg_0/bat_dis_0 managers die de coordinator al opgezet heeft
- Geen herstart of herconfiguratie nodig — werkt automatisch na installatie

## v5.5.519 (2026-04-10)

### Nexus kWh: fix voor managed battery zonder battery_configs

**Root cause**: de Nexus batterij wordt via de Zonneplan bridge beheerd.
`battery_configs` is leeg → de auto-detect loop van v5.5.518 runt nooit.

**sensor.py**:
- Prio 1: via ESM managers (coordinator heeft ze gevuld)
- Prio 2: directe scan van alle HA sensor states op `production_day` / `delivery_day`
- Werkt nu ook als `battery_configs` volledig leeg is
- Geen herconfiguratie of herstart vereist

## v5.5.519 (2026-04-10)

### ZonneplanP1Bridge: detectie herschreven

**Root cause**: bridge zocht op exacte entity_ids zoals `sensor.zonneplan_production_day`
maar de echte entity heet `sensor.thuisbatterij_productie_vandaag` — device naam als prefix.

**energy_manager/zonneplan_p1_bridge.py**:
- detect() herschreven met dezelfde aanpak als de al werkende ZonneplanMarginCalculator
- Filter op `"zonneplan" in entity_id` + `endswith(patroon)` — werkt voor elke device naam
- Patronen: `_production_day`, `_productie_vandaag`, `_delivery_day`, `_levering_vandaag`

**sensor.py**:
- Leest `zp_bat_charged_kwh_today` / `zp_bat_discharged_kwh_today` als Bron 2a
  (na geconfigureerde sensor, vóór W×t accumulatie)

## v5.5.520 (2026-04-10)

### Echte kWh meters voor P1, NILM sockets + auto-detect overal consistent

**coordinator.py** — P1/DSMR runtime auto-detect:
- Als grid_import/export kWh sensoren niet geconfigureerd zijn: auto-detect via
  `EnergySourceManager.auto_detect_all()` bij startup → zelfde patroonmatch als de rest

**nilm/detector.py** — DetectedDevice:
- Nieuw veld: `energy_sensor_id` — kWh sensor van het apparaat
- Opgenomen in `to_dict()` zodat de coordinator het kan lezen

**nilm/hybrid_nilm.py** — AnchoredDevice:
- Nieuw veld: `energy_sensor_id`
- Bij registratie van nieuw anker: auto-detect op basis van entity_id patronen
  (bijv. `sensor.wasmachine_energy`, `sensor.wasmachine_kwh`)

**coordinator.py** — NILM anchor kWh accumulatie:
- Prioriteit 1: `energy_sensor_id` — direct van apparaat sensor (exact, overleeft herstart)
- Prioriteit 2: W×t accumulatie (fallback als geen sensor geconfigureerd)

## v5.5.520 (2026-04-10)

### MeasurementTracker + P1/NILM/PV runtime fixes

**energy_manager/measurement_tracker.py** (nieuw):
- Vergelijkt sensor vs berekening per stroom (PV, grid, batterij, huis)
- Drie niveaus:
  - <5% afwijking: kalibratiefactor publiceren (kleine offset)
  - 5-20%: loggen, sensor wint, geen correctie (model is OK, maar niet precies)
  - >20%: structurele fout — berekeningsmodel klopt niet, sensor is primair,
    berekening gemarkeerd als onbetrouwbaar, diagnostiek publiceren
- Correctiefactoren zijn NOOIT voor structurele fouten
- Publiceert `data["measurement_quality"]` voor dashboard + cloud diagnostiek

**coordinator.py**:
- P1/DSMR kWh runtime auto-detect bij startup als niet geconfigureerd
- NILM smart plugs: `energy_sensor_id` als prio 1 boven W×t accumulatie
- PV: tracking toegevoegd (sensor vs W×t), logt structurele afwijkingen
- `measurement_quality` gepubliceerd elke cyclus

**nilm/detector.py**:
- `DetectedDevice.energy_sensor_id` veld toegevoegd

## v5.5.520 (2026-04-10)

### Runtime auto-detect voor alle energie-sensoren + passieve meting vs berekening

**coordinator.py** — runtime auto-detect (zelfde aanpak als ZonneplanMarginCalculator):
- PV `energy_sensor`: auto-detect via EnergySourceManager als niet geconfigureerd
- Grid import/export kWh: auto-detect als T1/T2 velden leeg zijn
- Batterij charge/discharge: auto-detect via `production_day`/`delivery_day` patronen
- NILM smart plugs: gebruiken nu `energy_sensor_id` als prio 1, W×t als fallback

**energy_manager/measurement_tracker.py** (nieuw):
- Passieve observatie: sensor kWh vs berekende kWh per stroom
- Logt WARNING bij >20% structurele afwijking (max 1x per uur)
- Publiceert naar `data["measurement_quality"]` — dashboard en toekomstige cloud
- **Bewust geen auto-correctie**: met 2 installaties onbetrouwbaar.
  Auto-correctie komt in cloud variant na statistische validatie.

**nilm/detector.py**:
- `DetectedDevice.energy_sensor_id` veld toegevoegd voor directe kWh meting

## v5.5.520 (2026-04-10)

### MeasurementTracker — lokaal leren van correctiefactoren

**energy_manager/measurement_tracker.py** (nieuw):
- Vergelijkt sensor (primair) vs W×t berekening (fallback) per stroom
- Leert lokaal via mediaan over rolling 30-dagenvenster
- Als sensor wegvalt: gecorrigeerde berekening als fallback
- Logt structurele afwijkingen > 20% als WARNING
- Publiceert factoren naar data["measurement_factors"]

**Stromen**: pv, grid_import, grid_export, bat_charge, bat_discharge

**coordinator.py**:
- PV: sensor primair → leert factor → gecorrigeerde W×t als fallback
- Dagovergang: commit meting aan tracker voor alle stromen
- `data["pv_kwh_source"]` = "sensor" | "corrected_calc" | "raw_calc"
- P1/DSMR en NILM runtime auto-detect toegevoegd

**Architectuur voor cloud**:
- Factoren worden lokaal geleerd en gepubliceerd
- Cloud kan later factoren terug sturen (zoals EPEX prijzen)
- Statistische validatie over veel installaties → cloud variant

## v5.5.521 (2026-04-10)

### Notificatie-spam fix + zelf-lerend systeem verbeteringen

**energy_manager/notification_manager.py**:
- Spam-key gebruikt nu `notification_id` ipv alleen `title` — zelfde melding = zelfde key
- Per-categorie cooldowns: phase/diagnostics/sensor/forecast = 1x per dag, tips = 1x per week
- `persistent_notification` valt ook onder cooldown (niet meer elke slow_tick aangemaakt)

**energy_manager/self_diagnostics.py**:
- `run_analysis()` draaide elke ~1.7 min → notificatie max 1x per 24u

**energy_manager/measurement_tracker.py**:
- `validate_sensor()`: detecteert fout geconfigureerde sensor (factor > 5x = Wh als kWh)

**coordinator.py**:
- Battery capaciteit auto-kalibratie: meet werkelijke capaciteit via charge_kwh / SOC-delta
- Logt afwijking > 15% t.o.v. geconfigureerde capaciteit
- NILM smart plug energy sensor auto-linking: zoekt kWh-sensor op hetzelfde HA-device
  (bijv. Shelly plug S heeft altijd energy sensor naast power sensor)
- Sensor sanity check bij dagovergang: suspect sensoren worden gelogd

## v5.5.522 (2026-04-10)

### Notificatie cooldowns overleven herstart

**energy_manager/notification_manager.py**:
- Spam-timestamps worden opgeslagen in `cloudems_notification_cooldowns_v1` (HA storage)
- Bij herstart: timestamps herladen — cooldown loopt gewoon door
- Verlopen entries (> 1 week) worden automatisch opgeruimd bij laden
- Na elke verzonden notificatie direct opslaan

## v5.5.523 (2026-04-10)

### Performance fix: nieuwe modules naar slow_tick

**Root cause performance CRITICAL**: EnvironmentalProcessor.process_all() draaide
elke 10s cyclus — onnodig voor omgevingssensoren die elke 1-5 min veranderen.

**coordinator.py**:
- EnvironmentalProcessor: elke 10s → alleen bij slow_tick (~100s)
- Verwachte impact: -20-30ms per cyclus, minder CRITICAL/MINIMAL modes

**Diagnose uit logs**:
- Regelmatig CRITICAL (>1000ms), soms 8-11 seconden piek
- full_logging=false bij CRITICAL → ZonneplanP1Bridge INFO logs onderdrukt
- Verklaart waarom bridge-detectie nooit in logs verscheen

## v5.5.524 (2026-04-10)

### ZonneplanP1Bridge: echte root cause battery kWh fix

**Root cause**: SOC en vermogen werken via de bestaande Zonneplan API bridge.
De battery kWh sensoren (`sensor.thuisbatterij_productie_vandaag`) bevatten
GEEN "zonneplan" in hun entity_id — de bridge filterde hier op en vond ze dus nooit.

**energy_manager/zonneplan_p1_bridge.py**:
- detect() gesplitst in twee groepen:
  - Groep 1: P1/electricity/PV → `"zonneplan" in entity_id` (werkte al)
  - Groep 2: battery → `entity_registry.platform == "zonneplan_one"` filter
    (vindt `sensor.thuisbatterij_*` correct ongeacht device naam)
- Extra INFO log bij succesvolle detectie batterij kWh sensoren

## v5.5.525 (2026-04-10)

### Nexus kWh: directe scan werkte niet door vertaling

**Root cause**: sensor.py Prio 2 directe scan zocht naar `"production_day"` maar
de Zonneplan integratie vertaalt de entity naar `sensor.thuisbatterij_productie_vandaag`
— "productie_vandaag" bevat nooit "production_day".

**sensor.py**:
- Directe scan uitgebreid met Nederlandse patronen:
  - geladen: `production_day`, `productie_vandaag`, `production_today`, `charged_kwh`
  - ontladen: `delivery_day`, `levering_vandaag`, `delivery_today`, `discharged_kwh`
- Dit is de eenvoudigste en meest robuuste fix — werkt ongeacht bridge of ESM

## v5.5.526 (2026-04-10)

### Multi-battery: kWh, SOC en capaciteit correct geaggregeerd

**sensor.py — CloudEMSBatteryPowerSensor (kWh)**:
- Sommeer alle geconfigureerde batterijen per bron:
  - Bron 1: geconfigureerde sensors per bat_cfg (bat_chg_0, bat_chg_1, ...)
  - Bron 2: pattern scan (NL + EN) sommeer alle matches

**sensor.py — Battery SOC sensor**:
- Single battery: batteries[0].soc_pct (was al correct)
- Multi-battery: capaciteitsgewogen gemiddelde
  - bat1=80% × 10kWh + bat2=40% × 5kWh → 66.7% (15kWh totaal)
- extra_state_attributes: capaciteit = som, vermogen = som

**Vermogen** was al correct gesommeerd via `sum(b.get("power_w"))`.

## v5.5.527 (2026-04-10)

### Multi-battery: volledige audit en fixes

**sensor.py**:
- SOC: simpel gemiddelde (SOC1+SOC2+...)/n — niet gewogen
- Capaciteit: sum() over alle batteries
- kWh: sum() per bron (geconfigureerd per bat_cfg, ESM, pattern scan)

**coordinator.py**:
- batt_soc voor schedule/flex: simpel gemiddelde uit data["batteries"]
- batt_capacity voor schedule/flex: sum() uit data["batteries"]
- Fallback naar legacy single-sensor als batteries[] leeg is

**Principe**: alles wat per-batterij is wordt gesommeerd (kWh, vermogen, capaciteit)
of gemiddeld (SOC). Grid/Net is altijd enkelvoudig.

## v5.5.527 (2026-04-10)

### Multi-battery audit + SOC fix

**sensor.py — SOC**:
- Simpel gemiddelde: (SOC1 + SOC2 + ... + SOCn) / n
- Geen capaciteitsweging — dat was fout

**Volledig audit multi-battery**:
- battery_raw_w: ✅ al gesommeerd in coordinator
- batt_soc voor beslissingen: ✅ al simpel gemiddelde
- batt_capacity voor beslissingen: ✅ al som
- round-trip efficiëntie: ✅ correct (discharge/charge × 100, gesommeerde waarden)
- coordinator batteries[0] aanroepen: ✅ allemaal bewaakt
- max_charge_w/max_discharge_w: per batterij via battery_configs (correct)
