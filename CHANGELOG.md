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
