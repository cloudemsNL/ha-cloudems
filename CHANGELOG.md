## [4.6.284] - 2026-03-16
### Fix — Boiler vermogen grafiek heeft nooit gewerkt
- **Rootcause:** De history API werd aangeroepen met `minimal_response=true` en twee entity IDs gecombineerd. Met minimal_response gebruiken entries het formaat `{s, lc}` in plaats van `{state, last_changed, entity_id}`. Daardoor was `series[0]?.entity_id` altijd leeg → temp en power konden niet onderscheiden worden → beide grafieken bleven leeg.
- **Fix:** Temp en power worden nu in twee aparte API-calls opgehaald (parallel via `Promise.all`). Parser herkent beide formaten (`s/lc` én `state/last_changed`).

### Feature — Virtuele thermostaat in boiler card
- De 'Virtuele thermostaten' kaart is verwerkt in de cloudems-boiler-card. Toont: huidig setpoint met −/+ knoppen (stap 1°C), snelknoppen Nacht (45°C) / Normaal / PV-boost (hardware max), actieve modus en huidige temperatuur.

## [4.6.283] - 2026-03-16

### Fix
- **Boiler tab: 'Boilers — Live status' kaart verwijderd** — De simpele markdown tabel met Temperatuur/Setpoint/Vermogen/COP was overbodig geworden nu de cloudems-boiler-card dezelfde info beter toont.

### Feature — Topology → NILM exclusie
- **`auto_exclude_by_entity_ids()`** — Topology-bekende infra-sensoren (grid, battery, solar, SoC uit config) worden doorgegeven aan NILM. Smart plug apparaten waarvan `source_entity_id` matcht worden automatisch uitgesloten van de energiebalans.

### Feature — Forecast zelfconsumptie
- **`forecast_self_consumption(pv_forecast_hourly)`** toegevoegd aan `SelfConsumptionTracker`. Combineert het geleerde uurverbruiksprofiel met de PV-forecast voor morgen → voorspelt hoeveel procent zelfverbruikt wordt. Basis voor sensor-attribuut en dashboard weergave.

### Feature — NILM correlatie + balans detectie (v4.6.282 afgerond)
- Alle drie detectielagen actief: naam, balans-overschrijding, vermogenscorrelatie.

## [4.6.282] - 2026-03-16

### Feature — Automatische infra-detectie via balans en vermogenscorrelatie
- **Balans-overschrijding:** Als NILM-som consistent > huis-vermogen + 25% marge over ≥60 seconden, zoekt CloudEMS de smart plug wiens vermogen de overrun verklaart en markeert die als `exclude_from_balance=auto_balance`. Nooit bevestigde apparaten.
- **Vermogenscorrelatie:** Elke 10 minuten berekent CloudEMS de Pearson-correlatie (vereenvoudigd) tussen elk actief smart plug apparaat en `battery_power_w` + `solar_power_w`. Correlatie > 0.85 over ≥10 metingen = infrastructuur → automatisch uitgesloten. Zo worden Zendure Accu 1/2 herkend ook als de naam-detectie ze mist.
- Reden `auto_balance` zichtbaar in detail panel.

## [4.6.281] - 2026-03-16

### Fix
- **Flow kaart: batterij en boiler node niet uitgelijnd** — battX en bolX stonden op verschillende X-posities (COL_R-38 vs COL_R+0). Beide nu op COL_R-20 zodat ze verticaal uitgelijnd zijn.
- **Flow kaart: sparkline nauwelijks zichtbaar** — stroke-width 0.9 + opacity 0.28 was te fijn. Nu: stroke-width 1.4 + opacity 0.70 voor de lijn, plus een gevuld gebied eronder (opacity 0.12) zodat de trend direct leesbaar is.

## [4.6.284] - 2026-03-16
### Fix — Boiler vermogen grafiek heeft nooit gewerkt
- **Rootcause:** De history API werd aangeroepen met `minimal_response=true` en twee entity IDs gecombineerd. Met minimal_response gebruiken entries het formaat `{s, lc}` in plaats van `{state, last_changed, entity_id}`. Daardoor was `series[0]?.entity_id` altijd leeg → temp en power konden niet onderscheiden worden → beide grafieken bleven leeg.
- **Fix:** Temp en power worden nu in twee aparte API-calls opgehaald (parallel via `Promise.all`). Parser herkent beide formaten (`s/lc` én `state/last_changed`).

### Feature — Virtuele thermostaat in boiler card
- De 'Virtuele thermostaten' kaart is verwerkt in de cloudems-boiler-card. Toont: huidig setpoint met −/+ knoppen (stap 1°C), snelknoppen Nacht (45°C) / Normaal / PV-boost (hardware max), actieve modus en huidige temperatuur.

## [4.6.283] - 2026-03-16

### Fix
- **Boiler tab: 'Boilers — Live status' kaart verwijderd** — De simpele markdown tabel met Temperatuur/Setpoint/Vermogen/COP was overbodig geworden nu de cloudems-boiler-card dezelfde info beter toont.

### Feature — Topology → NILM exclusie
- **`auto_exclude_by_entity_ids()`** — Topology-bekende infra-sensoren (grid, battery, solar, SoC uit config) worden doorgegeven aan NILM. Smart plug apparaten waarvan `source_entity_id` matcht worden automatisch uitgesloten van de energiebalans.

### Feature — Forecast zelfconsumptie
- **`forecast_self_consumption(pv_forecast_hourly)`** toegevoegd aan `SelfConsumptionTracker`. Combineert het geleerde uurverbruiksprofiel met de PV-forecast voor morgen → voorspelt hoeveel procent zelfverbruikt wordt. Basis voor sensor-attribuut en dashboard weergave.

### Feature — NILM correlatie + balans detectie (v4.6.282 afgerond)
- Alle drie detectielagen actief: naam, balans-overschrijding, vermogenscorrelatie.

## [4.6.282] - 2026-03-16

### Feature — Automatische infra-detectie via balans en vermogenscorrelatie
- **Balans-overschrijding:** Als NILM-som consistent > huis-vermogen + 25% marge over ≥60 seconden, zoekt CloudEMS de smart plug wiens vermogen de overrun verklaart en markeert die als `exclude_from_balance=auto_balance`. Nooit bevestigde apparaten.
- **Vermogenscorrelatie:** Elke 10 minuten berekent CloudEMS de Pearson-correlatie (vereenvoudigd) tussen elk actief smart plug apparaat en `battery_power_w` + `solar_power_w`. Correlatie > 0.85 over ≥10 metingen = infrastructuur → automatisch uitgesloten. Zo worden Zendure Accu 1/2 herkend ook als de naam-detectie ze mist.
- Reden `auto_balance` zichtbaar in detail panel.

## [4.6.281] - 2026-03-16

### Fix — Batterijen en SolarFlow nooit als NILM apparaat tonen (issue #29)
- **Rootcause:** Accu 1/2, SolarFlow, Zendure Manager verschenen als NILM apparaten onder de Thuis node. Dit is fundamenteel onjuist: batterijen zijn direct aan de hub gekoppeld (worden apart gepland) en SolarFlow/Zendure zijn PV+batterij infrastructuur, geen verbruiksapparaten.
- **Fix `_isDedicatedNode()`** — uitgebreid met: batterij-namen (accu, battery, batterij, powerwall, pylontech, BYD, ...), PV-infra namen (solarflow, omvormer, growatt, goodwe, zendure manager, ...) en apparaten met `exclude_from_balance=True`. Deze verschijnen nooit meer onder Thuis in de flow.

### Feature — EPEX prijsdetail bij klik op Netwerk node
- Klik op de Netwerk node in de flow → volledig EPEX barchart met uurprijzen vandaag, huidige prijs, min/gem/max, en toggle **incl. / excl. belasting**.

### Feature — Mini prijswidget (cloudems-mini-price-card)
- Nieuwe standalone kaart: compact EPEX prijsoverzicht met barchart + incl/excl toggle. Staat bovenaan alle 19 dashboard tabs. Altijd weten wat stroom kost.

### Feature — NILM auto-merge dubbele apparaatnamen
- Apparaten met dezelfde naam maar op verschillende fases (bijv. twee keer 'Vaatwasser') worden automatisch samengevoegd elke 10 minuten. Winner = bevestigd > meeste on_events. Smart plugs worden nooit samengevoegd (elk is een echt fysiek apparaat).

## [4.6.280] - 2026-03-16


### Fix
- **Flow kaart: NILM apparaat klik toonde Huisverbruik** — Klikken op een NILM device node (Vaatwasser, SolarFlow, etc.) in de flow opende altijd het Huisverbruik detail panel. Nu opent het een volledig device-specifiek panel met: vermogen, fase, type, kamer, betrouwbaarheids­balk, bevestigd/lerend status, en de volledige actie-set (Bevestigen / Afwijzen / Negeren / Uitsluiten van balans / Opnemen in balans). Automatisch uitgesloten apparaten tonen de reden.

## [4.6.279] - 2026-03-16

### Fix — Dubbele entiteiten (issue #29)
- **Automatische dubbeltelling-detectie** — CloudEMS scant elke 10 minuten alle HA entiteiten op bekende batterij/omvormer integraties (Zendure, SolarFlow, Victron, Growatt, GoodWe, SolarEdge, Enphase, Huawei, Sungrow, Fronius, Foxess, EcoFlow, Anker SOLIX, Pylontech — 15+ merken). Smart plug NILM apparaten die al worden beheerd door zo'n integratie worden automatisch gemarkeerd als `exclude_from_balance=True`. Dubbeltelling is daarmee onmogelijk — geen handmatige actie nodig.
- **NilmDevice.exclude_from_balance** — Nieuw veld op elk NILM apparaat. Wordt opgeslagen en hersteld bij herstart. Reden (`auto_integration` of `user`) wordt bijgehouden.
- **Klikbaar detail overal** — NILM apparaat detail panel toont nu altijd een ⊗/✓ knop om de balans-uitsluiting handmatig aan/uit te zetten. Apparaten uitgesloten door auto-detectie tonen een badge met de reden.
- **Visuele feedback** — Uitgesloten apparaten tonen ⊗ badge in de NILM rij en worden gedimmed weergegeven.
- **Service `cloudems.set_balance_exclude`** — Handmatige override: `{device_name, exclude, reason}`.

## [4.6.278] - 2026-03-16

### Feature — Solar card v2.1: alle secties compleet
- **Benutting & Clipping-drempel** — Per omvormer benutting-balk met clipping-drempel markering. Toont clipping advies en verlies per jaar als relevant.
- **PV samenvatting** — PV nu, vandaag, morgen, zelfconsumptie %, piekuur vandaag.
- **Zelfconsumptie detail** — PV productie, zelf verbruikt, teruggeleverd, beste zonuur, besparing per maand.
- **Structurele Schaduwdetectie** — Samenvatting, geschat verlies per dag, per-omvormer details.
- Alle sensor ID fallbacks (oude + nieuwe naam) voor forecast, accuracy en shadow sensoren.

## [4.6.284] - 2026-03-16
### Fix — Boiler vermogen grafiek heeft nooit gewerkt
- **Rootcause:** De history API werd aangeroepen met `minimal_response=true` en twee entity IDs gecombineerd. Met minimal_response gebruiken entries het formaat `{s, lc}` in plaats van `{state, last_changed, entity_id}`. Daardoor was `series[0]?.entity_id` altijd leeg → temp en power konden niet onderscheiden worden → beide grafieken bleven leeg.
- **Fix:** Temp en power worden nu in twee aparte API-calls opgehaald (parallel via `Promise.all`). Parser herkent beide formaten (`s/lc` én `state/last_changed`).

### Feature — Virtuele thermostaat in boiler card
- De 'Virtuele thermostaten' kaart is verwerkt in de cloudems-boiler-card. Toont: huidig setpoint met −/+ knoppen (stap 1°C), snelknoppen Nacht (45°C) / Normaal / PV-boost (hardware max), actieve modus en huidige temperatuur.

## [4.6.283] - 2026-03-16

### Fix
- **Boiler tab: 'Boilers — Live status' kaart verwijderd** — De simpele markdown tabel met Temperatuur/Setpoint/Vermogen/COP was overbodig geworden nu de cloudems-boiler-card dezelfde info beter toont.

### Feature — Topology → NILM exclusie
- **`auto_exclude_by_entity_ids()`** — Topology-bekende infra-sensoren (grid, battery, solar, SoC uit config) worden doorgegeven aan NILM. Smart plug apparaten waarvan `source_entity_id` matcht worden automatisch uitgesloten van de energiebalans.

### Feature — Forecast zelfconsumptie
- **`forecast_self_consumption(pv_forecast_hourly)`** toegevoegd aan `SelfConsumptionTracker`. Combineert het geleerde uurverbruiksprofiel met de PV-forecast voor morgen → voorspelt hoeveel procent zelfverbruikt wordt. Basis voor sensor-attribuut en dashboard weergave.

### Feature — NILM correlatie + balans detectie (v4.6.282 afgerond)
- Alle drie detectielagen actief: naam, balans-overschrijding, vermogenscorrelatie.

## [4.6.282] - 2026-03-16

### Feature — Automatische infra-detectie via balans en vermogenscorrelatie
- **Balans-overschrijding:** Als NILM-som consistent > huis-vermogen + 25% marge over ≥60 seconden, zoekt CloudEMS de smart plug wiens vermogen de overrun verklaart en markeert die als `exclude_from_balance=auto_balance`. Nooit bevestigde apparaten.
- **Vermogenscorrelatie:** Elke 10 minuten berekent CloudEMS de Pearson-correlatie (vereenvoudigd) tussen elk actief smart plug apparaat en `battery_power_w` + `solar_power_w`. Correlatie > 0.85 over ≥10 metingen = infrastructuur → automatisch uitgesloten. Zo worden Zendure Accu 1/2 herkend ook als de naam-detectie ze mist.
- Reden `auto_balance` zichtbaar in detail panel.

## [4.6.281] - 2026-03-16

### Fix
- **Flow kaart: batterij en boiler node niet uitgelijnd** — battX en bolX stonden op verschillende X-posities (COL_R-38 vs COL_R+0). Beide nu op COL_R-20 zodat ze verticaal uitgelijnd zijn.
- **Flow kaart: sparkline nauwelijks zichtbaar** — stroke-width 0.9 + opacity 0.28 was te fijn. Nu: stroke-width 1.4 + opacity 0.70 voor de lijn, plus een gevuld gebied eronder (opacity 0.12) zodat de trend direct leesbaar is.

## [4.6.284] - 2026-03-16
### Fix — Boiler vermogen grafiek heeft nooit gewerkt
- **Rootcause:** De history API werd aangeroepen met `minimal_response=true` en twee entity IDs gecombineerd. Met minimal_response gebruiken entries het formaat `{s, lc}` in plaats van `{state, last_changed, entity_id}`. Daardoor was `series[0]?.entity_id` altijd leeg → temp en power konden niet onderscheiden worden → beide grafieken bleven leeg.
- **Fix:** Temp en power worden nu in twee aparte API-calls opgehaald (parallel via `Promise.all`). Parser herkent beide formaten (`s/lc` én `state/last_changed`).

### Feature — Virtuele thermostaat in boiler card
- De 'Virtuele thermostaten' kaart is verwerkt in de cloudems-boiler-card. Toont: huidig setpoint met −/+ knoppen (stap 1°C), snelknoppen Nacht (45°C) / Normaal / PV-boost (hardware max), actieve modus en huidige temperatuur.

## [4.6.283] - 2026-03-16

### Fix
- **Boiler tab: 'Boilers — Live status' kaart verwijderd** — De simpele markdown tabel met Temperatuur/Setpoint/Vermogen/COP was overbodig geworden nu de cloudems-boiler-card dezelfde info beter toont.

### Feature — Topology → NILM exclusie
- **`auto_exclude_by_entity_ids()`** — Topology-bekende infra-sensoren (grid, battery, solar, SoC uit config) worden doorgegeven aan NILM. Smart plug apparaten waarvan `source_entity_id` matcht worden automatisch uitgesloten van de energiebalans.

### Feature — Forecast zelfconsumptie
- **`forecast_self_consumption(pv_forecast_hourly)`** toegevoegd aan `SelfConsumptionTracker`. Combineert het geleerde uurverbruiksprofiel met de PV-forecast voor morgen → voorspelt hoeveel procent zelfverbruikt wordt. Basis voor sensor-attribuut en dashboard weergave.

### Feature — NILM correlatie + balans detectie (v4.6.282 afgerond)
- Alle drie detectielagen actief: naam, balans-overschrijding, vermogenscorrelatie.

## [4.6.282] - 2026-03-16

### Feature — Automatische infra-detectie via balans en vermogenscorrelatie
- **Balans-overschrijding:** Als NILM-som consistent > huis-vermogen + 25% marge over ≥60 seconden, zoekt CloudEMS de smart plug wiens vermogen de overrun verklaart en markeert die als `exclude_from_balance=auto_balance`. Nooit bevestigde apparaten.
- **Vermogenscorrelatie:** Elke 10 minuten berekent CloudEMS de Pearson-correlatie (vereenvoudigd) tussen elk actief smart plug apparaat en `battery_power_w` + `solar_power_w`. Correlatie > 0.85 over ≥10 metingen = infrastructuur → automatisch uitgesloten. Zo worden Zendure Accu 1/2 herkend ook als de naam-detectie ze mist.
- Reden `auto_balance` zichtbaar in detail panel.

## [4.6.281] - 2026-03-16

### Fix — Batterijen en SolarFlow nooit als NILM apparaat tonen (issue #29)
- **Rootcause:** Accu 1/2, SolarFlow, Zendure Manager verschenen als NILM apparaten onder de Thuis node. Dit is fundamenteel onjuist: batterijen zijn direct aan de hub gekoppeld (worden apart gepland) en SolarFlow/Zendure zijn PV+batterij infrastructuur, geen verbruiksapparaten.
- **Fix `_isDedicatedNode()`** — uitgebreid met: batterij-namen (accu, battery, batterij, powerwall, pylontech, BYD, ...), PV-infra namen (solarflow, omvormer, growatt, goodwe, zendure manager, ...) en apparaten met `exclude_from_balance=True`. Deze verschijnen nooit meer onder Thuis in de flow.

### Feature — EPEX prijsdetail bij klik op Netwerk node
- Klik op de Netwerk node in de flow → volledig EPEX barchart met uurprijzen vandaag, huidige prijs, min/gem/max, en toggle **incl. / excl. belasting**.

### Feature — Mini prijswidget (cloudems-mini-price-card)
- Nieuwe standalone kaart: compact EPEX prijsoverzicht met barchart + incl/excl toggle. Staat bovenaan alle 19 dashboard tabs. Altijd weten wat stroom kost.

### Feature — NILM auto-merge dubbele apparaatnamen
- Apparaten met dezelfde naam maar op verschillende fases (bijv. twee keer 'Vaatwasser') worden automatisch samengevoegd elke 10 minuten. Winner = bevestigd > meeste on_events. Smart plugs worden nooit samengevoegd (elk is een echt fysiek apparaat).

## [4.6.280] - 2026-03-16


### Fix
- **Flow kaart: NILM apparaat klik toonde Huisverbruik** — Klikken op een NILM device node (Vaatwasser, SolarFlow, etc.) in de flow opende altijd het Huisverbruik detail panel. Nu opent het een volledig device-specifiek panel met: vermogen, fase, type, kamer, betrouwbaarheids­balk, bevestigd/lerend status, en de volledige actie-set (Bevestigen / Afwijzen / Negeren / Uitsluiten van balans / Opnemen in balans). Automatisch uitgesloten apparaten tonen de reden.

## [4.6.279] - 2026-03-16

### Fix — Dubbele entiteiten (issue #29)
- **Automatische dubbeltelling-detectie** — CloudEMS scant elke 10 minuten alle HA entiteiten op bekende batterij/omvormer integraties (Zendure, SolarFlow, Victron, Growatt, GoodWe, SolarEdge, Enphase, Huawei, Sungrow, Fronius, Foxess, EcoFlow, Anker SOLIX, Pylontech — 15+ merken). Smart plug NILM apparaten die al worden beheerd door zo'n integratie worden automatisch gemarkeerd als `exclude_from_balance=True`. Dubbeltelling is daarmee onmogelijk — geen handmatige actie nodig.
- **NilmDevice.exclude_from_balance** — Nieuw veld op elk NILM apparaat. Wordt opgeslagen en hersteld bij herstart. Reden (`auto_integration` of `user`) wordt bijgehouden.
- **Klikbaar detail overal** — NILM apparaat detail panel toont nu altijd een ⊗/✓ knop om de balans-uitsluiting handmatig aan/uit te zetten. Apparaten uitgesloten door auto-detectie tonen een badge met de reden.
- **Visuele feedback** — Uitgesloten apparaten tonen ⊗ badge in de NILM rij en worden gedimmed weergegeven.
- **Service `cloudems.set_balance_exclude`** — Handmatige override: `{device_name, exclude, reason}`.

## [4.6.278] - 2026-03-16

### Fix
- **Solar JS kaart: missende secties** — Benutting & Clipping-drempel, PV Samenvatting, Zelfconsumptie en Schaduwdetectie waren aanwezig in de code maar werden niet gerenderd door een variabelenaamconflict na een eerdere refactor. Opgelost.
- **Gas kaart: periodes tonen streepjes** — Dag/week/maand/jaar verbruik toonde `—` zodra m³=0, ook als de gas module actief is en de sensor werkt. Nu toont de kaart `0.00 m³` als de gasmeter een geldig getal rapporteert. Startup timer toegevoegd zodat data altijd verschijnt na laden.

## [4.6.277] - 2026-03-16


### Fix
- **Solar JS kaart toont 0 kWh forecast** — Zelfde rootcause als de solar system sensor: HA entity registry bewaart de oude entity ID `sensor.cloudems_solar_pv_forecast_today` terwijl de huidige code `sensor.cloudems_pv_forecast_today` genereert. JS kaart probeert nu eerst de oude naam, dan fallback naar de nieuwe. Zelfde fix voor tomorrow en accuracy sensor. Ook flow kaart detail panel gefixed.

## [4.6.276] - 2026-03-16

### Feature — AdaptiveHome koppeling (infrastructuur)
- **adaptivehome_bridge.py** — Nieuwe koppellaag tussen CloudEMS en AdaptiveHome. Onzichtbaar voor bestaande gebruikers — geen UI-wijzigingen.
- **Events CloudEMS → AdaptiveHome** (HA event bus): `cloudems_state_update` (10s), `cloudems_nilm_update` (30s), `cloudems_price_update` (5min), `cloudems_presence_update` (30s).
- **Events AdaptiveHome → CloudEMS**: `adaptivehome_occupancy`, `adaptivehome_mode`, `adaptivehome_scene`.
- **Services**: `cloudems.ah_get_status` (status opvragen via event-respons), `cloudems.ah_set_mode` (huismodus zetten: home/away/sleep/vacation).
- Bridge setup/shutdown volledig geïntegreerd in coordinator lifecycle — geen crash als AH niet aanwezig is.
- Placeholder voor toekomstige hosted variant (`async_push_to_hosted`).

## [4.6.275] - 2026-03-16

### Fix
- **Flow kaart: startup re-render** — Na setConfig wordt na 3s een forced re-render getriggerd zodat PV-data altijd snel zichtbaar is, ook als sensoren al waarden hadden vóór de kaart laadde.

### Feature
- **Solar tab: cloudems-solar-card naar productie** — Nieuwe JS kaart bovenaan de solar tab geplaatst (module-uit waarschuwing + cloudems-solar-card). Bestaande markdown kaarten blijven staan (DTAP).

## [4.6.274] - 2026-03-16

### Fix
- **Solar en batterij kaart: trage eerste weergave** — De dirty-check vergelijkt `last_changed` van sensoren. Bij opstarten is de sensor al beschikbaar maar verandert `last_changed` niet → kaart wacht op de volgende echte update. Fix: twee timeouts (3s en 8s) forceren een re-render na setConfig zodat data altijd snel zichtbaar is. Solar kaart kijkt ook naar inverter vermogenswaarden als extra trigger.

## [4.6.273] - 2026-03-16

### Fix — Ariston Lydos Hybrid schakelt BOOST bij dure stroom terwijl GREEN voldoende is
- **Oorzaak:** `_above_green_max` werd berekend als `current_temp >= max_setpoint_green_c - 1.0`. Bij een Ariston Lydos Hybrid met `max_setpoint_green_c=53°C` en actuele temp=52°C geeft dit `52 >= 52` = True → BOOST verplicht, ook al kan GREEN het setpoint (53°C) wél bereiken. De -1.0 marge triggert BOOST 1 graad te vroeg.
- **Fix:** BOOST verplicht alleen als het **actieve setpoint** boven `max_setpoint_green_c` uitkomt (`active_setpoint_c > max_setpoint_green_c`). Geldt voor zowel `heat_pump` als `hybrid` boiler types.
- **Effect:** Bij setpoint=53°C en green_max=53°C blijft de boiler in GREEN (warmtepomp, COP≈3.6) totdat het setpoint daadwerkelijk hoger gezet wordt.

## [4.6.272] - 2026-03-16

### Fix — Issue #28 feedback: boiler niet overslaan was niet duidelijk
- **Boiler stap nu echt optioneel** — Als `Warm water cascade activeren` uitstaat en gebruiker klikt Volgende, gaat de wizard direct door naar de volgende stap. Voorheen activeerde de stap altijd de boiler-wizard ongeacht de schakelaar (comment `# Altijd activeren — enabled-toggle verwijderd uit wizard (Fix 22)`).
- **Betere beschrijving boiler stap** — Duidelijk aangegeven: geen boiler → schakelaar UIT → Volgende → stap wordt overgeslagen. In alle 4 talen (NL/EN/DE/FR) bijgewerkt.

## [4.6.271] - 2026-03-16

### Fix — Issue #28: PV toevoegen geeft TypeError crash
- **Oorzaak:** `float(cfg.get(f'max_current_{phase.lower()}', DEFAULT_MAX_CURRENT))` crasht als de config-key bestaat maar expliciet `None` als waarde heeft. In dat geval geeft `.get(key, default)` de default NIET terug — alleen als de key ontbreekt. Resultaat: `float(None)` → `TypeError: float() argument must be a string or a real number, not 'NoneType'` → integratie start niet op.
- **Fix:** Vervangen door `cfg.get(key) or DEFAULT_MAX_CURRENT` zodat ook `None`-waarden correct terugvallen op de default.

### Fix — Issue #27: Batterij module bevriest, alleen update na herlaad
- **Oorzaak (rootcause):** `decide_action_v3()` in ZonneplanProvider leest `self._last_state` voor SoC, actieve mode en tariefgroep. Maar `_last_state` wordt alleen bijgewerkt door `read_state()`. De coordinator roept `provider.read_state()` alleen aan als `battery_soc_entity` geen waarde teruggeeft (fallback-pad). Als de soc_entity wél geconfigureerd is → `read_state()` wordt overgeslagen → `_last_state.active_mode` wordt stale → de idempotentie-check in `_send_control_mode()` (`current == mode_val and _last_sent_mode == mode_val`) blokkeert elke verdere sturing → batterij "bevriest" totdat de integratie herlaadt.
- **Fix:** `_zp_provider.read_state()` wordt nu altijd aangeroepen aan het begin van elke coordinator-cyclus, ongeacht of `battery_soc_entity` geconfigureerd is.
- **Extra logging:** Bij mode-wijziging via state refresh wordt dit gelogd als INFO. `decide_action_v3()` logt nu op DEBUG niveau: SoC bron, tariefgroep, actieve mode en last_sent_mode.

### Feature — Startup banner
- Zichtbaar in HA logs bij elke start: versienummer, URL. Helpt HACS-gebruikers bij diagnostiek via GitHub issues.

## [4.6.270] - 2026-03-16

### Fix
- **Alle JS solar kaarten werken nu** — Rootcause gevonden: de werkende markdown tab leest uit `sensor.cloudems_solar_system_intelligence` (oude entity_id bewaard door HA entity registry), terwijl de JS kaarten uit `sensor.cloudems_solar_system` lazen die leeg bleef. Alle JS kaarten lezen nu eerst `sensor.cloudems_solar_system_intelligence`, dan fallback naar `sensor.cloudems_solar_system`.
- **Solar-card dirty-check** — Was ook afhankelijk van `sensor.cloudems_status.attributes.inverter_data` (bestaat niet per CLAUDE_INSTRUCTIONS). Vervangen door `sol.attributes.inverters`.

## [4.6.269] - 2026-03-16

### Fix
- **NILM device detail opent niet bij klik** — `nid` bevatte spaties (bijv. `nilm_Ariston Boiler`) wat een ongeldig HTML id geeft. `querySelector('#nr-nilm_Ariston Boiler')` faalt op spaties. Fix: spaties en speciale tekens vervangen door `_` in het id. Bevestigen/Afwijzen/Negeren knoppen werken nu.

## [4.6.268] - 2026-03-16

### Fix
- **Solar tab hersteld** — Tab was per ongeluk vervangen door de nieuwe JS kaart zonder goedkeuring. Exact teruggezet naar de 4.6.236 inhoud (18 kaarten).
- **Infinity kW opgelost** — `Math.max(...[])` geeft Infinity als er geen omvormers zijn. Nu een veilige lege-array check.

## [4.6.267] - 2026-03-16

### Fix
- **Solar detail toont nu alle info** — Detail data wordt nu LIVE gebouwd vanuit hass bij elke klik (`_buildNodeDetail`) i.p.v. uit verouderde `_nodeData`. Toont: productie nu, vandaag kWh, morgen forecast, piek 7d, zekerheid%, en ALLE omvormers met individueel vermogen + piek.
- **Beide omvormers zichtbaar** — `_buildNodeDetail` leest `sensor.cloudems_solar_system.attributes.inverters` direct, niet de gefilterde `_getInverters()` output. Alle geconfigureerde omvormers verschijnen altijd.
- Zelfde live-aanpak voor batterij, boiler, grid, ev, home — altijd actuele data.

## [4.6.266] - 2026-03-16

### Fix
- **NILM devices verschijnen weer automatisch onder Thuis** — Twee bugs tegelijk: (1) `subBox` en `nilmBox` functies waren weggevallen tijdens refactor waardoor ze undefined waren. (2) `_getFlowLayer2` las uit `sensor.cloudems_nilm_top_N_device` die `unknown` teruggeeft als apparaat niet actief is — vervangen door directe read uit `sensor.cloudems_nilm_running_devices.attributes.device_list` (zelfde bron als detail panel). Top 5 op vermogen, klikbaar met detail.

## [4.6.265] - 2026-03-16

### Fix
- **Solar detail panel uitgebreid** — Toont nu: productie nu, vandaag kWh, morgen forecast, piek 7d, zekerheid%, en per omvormer vermogen + piek. Zoals in de mockup.

## [4.6.264] - 2026-03-16

### Fix
- **NILM devices niet zichtbaar onder Thuis** — `L2_XS` (de x-posities van de NILM nodes) werd gedefinieerd NADAT de pipes en arrows al werden getekend, waardoor `L2_XS[i]` `undefined` was. Definitie verplaatst naar vóór de pipes-sectie. NILM apparaten worden nu weer automatisch getoond onderaan de energiestroom kaart zonder te klikken.

## [4.6.263] - 2026-03-16

### Feature
- **Batterij tab productie-klaar** — Oude markdown/entities kaarten volledig verwijderd. Tab toont nu: module-uit waarschuwing (conditional) + nieuwe cloudems-battery-card v3.

## [4.6.262] - 2026-03-16

### Fix
- **Detail panel verdwijnt** — `_renderFull` schreef elke 30 ticks de volledige `shadowRoot.innerHTML` opnieuw, waardoor het detail panel direct werd vernietigd na openen. Fix: geen `_renderFull` zolang een detail panel open staat (`_activeNid` gezet).
- **Zon animatie hersteld** — Originele zon met glow, stralen, bewolkings-overlay en sparkline teruggeplaatst. Tekst staat nu correct onder de zon (y+27/y+38), niet erin.

## [4.6.261] - 2026-03-16

### Fix
- **Piekschaving badges** — Fase-badges: 'EXP' → 'EXPORT', 'OK' → 'IMPORT'. Onbalans-badge: 'HOOG' → 'ALERT', 'WARN' blijft, 'OK' blijft. Thresholds ongewijzigd: >5A = ALERT (rood), >3A = WARN (oranje), ≤3A = OK (groen).

## [4.6.260] - 2026-03-16

### Feature
- **Flow kaart volledig herschreven** — Altijd één node per type (zon/batterij/boiler), ongeacht hoeveel omvormers/accu's/boilers er zijn. Alle nodes zijn klikbaar: klikken toont een detail panel. Multi-node SOM-pill constructie verwijderd. Klikken op Zon toont per-omvormer vermogen, Batterij toont per-accu SoC+vermogen, Boiler toont per-boiler temp+setpoint. Klikken op Thuis toont NILM apparaten-lijst — NILM apparaten zijn zelf ook klikbaar voor details (fase, type, betrouwbaarheid, kamer, on-events).
- **Battery card v3.0** — Volledig nieuwe kaart: volledige cirkel arc met SoC exact in het midden + kWh + capaciteit, 24u vermogensgrafiek met 6u/24u wissel (laden groen / ontladen amber / nul-lijn), Providers-tabel met live interval-countdown en retry-pips, Zonneplan sturing uitklapbaar, Forecast 8u dots, slijtagekosten. Sliders Pad A en Entiteiten verwijderd.
- **Dashboard** — Batterij tab vernieuwd: alleen de nieuwe cloudems-battery-card (v3.0), oude markdown/entities kaarten verwijderd.

## [4.6.259] - 2026-03-16

### Feature
- **Flow kaart: NILM nodes klikbaar** — Elk NILM/subnode apparaat onderaan de energiestroom kaart is nu klikbaar. Klikken toont een detail-panel met: vermogen, fase (L1/L2/L3 met kleur), type, bron, on-events, kamer en betrouwbaarheidsbalk. Klik opnieuw of op ✕ om te sluiten. Data wordt live opgehaald uit `sensor.cloudems_nilm_devices` en `sensor.cloudems_nilm_running_devices`.

## [4.6.258] - 2026-03-16

### Fix
- **Solar/Batterij/NILM tabs: exact hersteld naar 4.6.236** — Nieuwe custom kaarten verwijderd uit de hoofdtabs. Tabs zijn nu weer identiek aan de laatste werkende versie (18/16/16 kaarten).
- **NILM Beheer tab hersteld** — Tab was verdwenen, teruggeplaatst na NILM tab.
- **Dev dashboard** — Alle nieuwe JS kaarten (solar, battery, boiler, shutter, nilm, pv-forecast, beheer) staan nu uitsluitend in `cloudems-dashboard-dev.yaml` voor testing.
- **Solar card crash** — `solS?.attributes` fix bij unavailable sensor.
- **cloudems-cards.js duplicate define** — `cloudems-nilm-card-editor` guard toegevoegd.

## [4.6.257] - 2026-03-16
### Fix
- **Solar/Batterij/NILM tabs: volledige oude inhoud hersteld** — Tabs waren vervangen door alleen de nieuwe custom kaart waardoor vrijwel alle informatie verdween. Oude tab-inhoud (18 solar cards, 16 battery cards, 16 NILM cards) teruggezet; nieuwe custom kaart staat bovenaan de tab als preview.
- **NILM Beheer tab hersteld** — Tab `cloudems-nilm-beheer` was verdwenen uit de navigatie. Teruggeplaatst na NILM tab.
- **Solar card crash** — `TypeError: Cannot read properties of undefined (reading 'attributes')` op lijn 102: `solS.attributes` → `solS?.attributes` wanneer sensor nog unavailable is bij opstarten.
- **cloudems-cards.js duplicate define** — `cloudems-nilm-card-editor` werd twee keer geregistreerd waardoor `customElements.define` een fout gooide op lijn 3034. Tweede registratie beveiligd met `!customElements.get(...)` guard.

## [4.6.256] - 2026-03-16
### Fix
- **Fase-balk gradient verwijderd** — De piekschaving fase-balken (L1/L2/L3) toonden altijd een groen→oranje→rood gradient ongeacht de werkelijke belasting. Nu een solide kleur op basis van belastingspercentage: `hsl(120 - ratio×120)` zodat 2A/25A groen is, 12A/25A geel-oranje, 24A/25A rood. Balk-label en badge-kleur volgen mee.
- **Solar card "Laden..." bij opstarten** — `sensor.cloudems_status` exporteerde geen `inverter_data` attribuut. De solar card gebruikt dit als fallback tijdens opstarten voordat `sensor.cloudems_solar_system` beschikbaar is. Nu toegevoegd aan `extra_state_attributes` van `CloudEMSStatusSensor`.
- **Battery card crash** — `TypeError: Cannot read properties of undefined (reading 'attributes')` op lijn 131 wanneer `sensor.cloudems_battery_so_c` undefined is maar `zpSoc` via EPEX schema wél beschikbaar is. Fix: `socS?.attributes||{}` i.p.v. `socS.attributes||{}`.
- **Overview card duplicate constructor** — `cloudems-control-card` probeerde `CloudemsControlCard` als constructor voor de tweede keer te registreren naast `cloudems-beheer-card`, wat een `CustomElementRegistry` fout veroorzaakte. Fix: thin alias class.
- **NILM card clicks werken niet** — `set hass()` deed altijd `_render()` zonder dirty-check, waardoor HA state-updates elke seconden de innerHTML vervingen en alle event listeners verdwenen vóór de gebruiker kon klikken. Fix: dirty-check op `last_changed` van de 4 NILM sensoren.

## [4.6.255] - 2026-03-16
### Fix
- **Home card crash** — `querySelectorAll is not defined` in `cloudems-home-card.js` (_bind(): ontbrekende `sr.` prefix op lijn ~999. Veroorzaakte een ReferenceError bij elke render waardoor de hele home tab een foutmelding toonde.
- **Dashboard resource cache** — Alle JS-resource URLs in `cloudems-dashboard.yaml` bijgewerkt naar `?v=4.6.255` (waren gemengd 4.6.196/4.6.227/4.6.233/4.6.241/4.6.248). Browser serveerde oude gecachte versies van battery-, solar- en home-card, waardoor tabs zwart of bevroren bleven na de upgrade naar 4.6.254.

## [4.6.140] - 2026-03-14
### Debug
- **Boiler vermogen WARNING log** — Elke coordinator-cyclus logt een WARNING in `cloudems_high.log`: `CloudEMS boiler [Boiler 1]: sensor_state=XXW → status.current_power_w=YYW`. Geen DEBUG-mode nodig. Hiermee is exact zichtbaar of `_read_sensors()` de waarde ophaalt maar `get_status()` hem niet doorgeeft, of omgekeerd.

## [4.6.139] - 2026-03-14
### Debug
- **Boiler config in startup log** — `coordinator_startup` logt nu voor elke boiler: `label`, `entity_id`, `energy_sensor`, `temp_sensor`, `control_mode`. Zichtbaar in `cloudems_high.log` direct na herstart — geen DEBUG niveau nodig.

## [4.6.138] - 2026-03-14
### Fixed
- **Inverter `control_entity` gewist bij bewerken** — zelfde patroon als boiler `energy_sensor`: optionele entity-selector stuurde lege string als gebruiker het veld niet aanraakte. Fix: behoud bestaande waarde als user_input leeg is.
- **Batterij `charge_entity` en `discharge_entity` gewist bij bewerken** — zelfde fix toegepast. Ook `power_sensor` en `soc_sensor` vallen nu terug op bestaande waarde.

## [4.6.137] - 2026-03-14
### Fixed
- **Boiler energy_sensor gewist bij unit bewerken** — `boiler_unit_edit` in de options flow overschreef `energy_sensor` (en `temp_sensor`) met een lege string als de gebruiker de entity-selector niet aanraakte. Dit is de directe oorzaak van "Vermogen: 0W" na het doorlopen van boiler-opties. Nu behouden deze velden hun waarde tenzij de gebruiker expliciet een andere sensor kiest.

## [4.6.136] - 2026-03-14
### Fixed
- **Config-opties wissen fase-sensoren** — `_save()` in options flow overschreef bestaande sensor-config met lege strings als een veld leeg was in de huidige stap. Nu worden lege waarden gefilterd zodat bestaande configuratie behouden blijft.
- **Zonneplan offline-melding** — is_online hysterese: pas na 3 opeenvolgende cycli zonder data wordt "offline" getoond. Voorkomt valse melding bij tijdelijk unavailable entity.

## [4.6.135] - 2026-03-14
### Debug
- **Fase stroom debug** — `_process_power_data()` logt nu per fase: welke stroomsensor entiteit, ruwe waarde, en wat `resolve_phase` oplevert. Filter op `custom_components.cloudems` op DEBUG niveau.

## [4.6.134] - 2026-03-14
### Debug
- **Boiler vermogen debug logging** — `_read_sensors()` logt nu op DEBUG niveau voor elke boiler: welke `energy_sensor` geconfigureerd is, de ruwe sensor state, en de uiteindelijke `current_power_w`. Parse-fouten worden nu als WARNING gelogd i.p.v. stil geslikt. Filter in HA Logboek op `cloudems.energy_manager.boiler_controller` op niveau DEBUG.

## [4.6.133] - 2026-03-14
### Fixed
- **Fase stroom 0A na 4.6.132** — `P1Telegram.to_dict()` riep `round(self.current_l1, 2)` aan terwijl het veld nu `Optional[float] = None` is (gewijzigd in 4.6.131). `round(None, 2)` gooit een `TypeError`, de hele P1 data verwerking faalde stil elke cyclus → `p1_data` leeg → `raw_a = None` → `current_a = 0`. Fix: None-guard toegevoegd.

## [4.6.132] - 2026-03-14
### Fixed
- **Alle real-time meetwaarden opgelost in één keer** — systematische audit van alle 138 CoordinatorEntity sensoren. 30 sensoren met `device_class` POWER/CURRENT/VOLTAGE/TEMPERATURE/BATTERY en `state_class=MEASUREMENT` kregen `_attr_force_update = True`. HA's state deduplicatie onderdrukte anders WebSocket updates als de waarde stabiel bleef, waardoor dashboards 0 bleven tonen. Inclusief: fase-sensoren (L1/L2/L3), grid import/export, huisverbruik, boiler temp/vermogen, PV omvormers, NILM apparaten, batterij SOC, EV vermogen, pool temp en alle overige vermogenssensoren.

## [4.6.131] - 2026-03-14
### Fixed
- **Fase stroom/spanning/vermogen sensoren tonen 0 na verloop van tijd** — alle 6 fase-sensoren (L1/L2/L3 stroom, spanning, vermogen, import, export, balans) kregen `_attr_force_update = True`. HA's state deduplicatie onderdrukte updates als de waarde stabiel bleef → dashboard toonde 0 terwijl er wel stroom liep.
- **P1 reader current default** — `current_l1/l2/l3` default was `0.0` (onbekend vs geen stroom niet te onderscheiden). Nu `None`. In coordinator: check is nu `is not None` ipv `if p1_a and p1_a > 0` — echte 0A waarden werden hierdoor weggegooid.
- **Zonneplan offline melding** (uit 4.6.130) — gecachede `_last_state` gebruikt ipv live `read_state()`.

## [4.6.130] - 2026-03-14
### Fixed
- **Zonneplan offline melding** — `get_setup_warnings()` gebruikte gecachede `_last_state` ipv `read_state()` opnieuw aanroepen. Voorkomt valse offline-melding bij tijdelijk unavailable SOC entity.

## [4.6.129] - 2026-03-14
### Fixed
- **Fase/grid sensoren 0W na update** — de `_handle_coordinator_update` override op BoilerStatus en BatterySchedule sensoren riep elke 10s `async_write_ha_state()` aan buiten de normale HA-cyclus. BatteryScheduleSensor heeft enorme attributen (volledige Zonneplan info) — dit floodde de HA state machine en recorder elke 10s → HA-vertraging → P1 telegrams misten → fase-sensoren 0W. Fix: overrides verwijderd. Beide sensoren gebruiken nu `coordinator._coordinator_tick` als `_seq` attribuut — HA detecteert de attribuutwijziging automatisch en stuurt een WebSocket event, zonder forced state writes.
- **NILM 6000+ entiteiten** (#22) — hard cap 200 dynamische NILM-sensoren + one-time cleanup bij startup
- **Boiler vermogen auto-detect pakte Ariston fase-sensoren** — skip nu sensoren met fase/l1/l2/l3/current/energy in de entity_id, kiest sensor met hoogste vermogen als totaal
- **asyncio.ensure_future → hass.async_create_task** in boiler temp persistentie
- **Zonneplan offline/modus** — is_online checkt nu SOC OR vermogen OR modus; active_mode filtert unavailable/unknown
- **JS kaarten** — decisions-card en prijsverloop-card toegevoegd aan `_do_storage_work()` resources

## [4.6.129] - 2026-03-14
### Fixed
- **Boiler vermogen auto-detect verkeerde sensor** — `_power_keywords` matching kon Ariston per-fase energiesensoren (`Energieverbruik Fase L3`, `L1 Current Average`) oppakken. Nu wordt `device_class == power` gebruikt — enkel echte vermogenssensoren worden gevonden
- **asyncio.ensure_future → hass.async_create_task** — `ensure_future()` buiten HA event loop context kan `RuntimeWarning` geven en fase/coordinator updates verstoren. Vervangen door `hass.async_create_task()` (correct HA patroon)
- **Batterij kaart update niet automatisch** (#25) — `_seq` counter + `_handle_coordinator_update` override toegevoegd aan `CloudEMSBatteryScheduleSensor`, identiek aan de boiler fix
- **NILM 6000+ entiteiten** (#22) — Hard cap van 200 dynamische NILM-sensoren in `_nilm_updated()`. One-time startup cleanup verwijdert bestaande orphaned NILM-entiteiten boven de cap
- **Bevat alle fixes uit v4.6.127 en v4.6.128**

## [4.6.128] - 2026-03-14
### Fixed
- **Boiler vermogen altijd 0W** — als geen `energy_sensor` geconfigureerd is, detecteert de controller nu automatisch een vermogenssensor op hetzelfde HA-device (bijv. `sensor.ariston_*_electric_power`). Sensor wordt gecacht na eerste detectie. Fallback naar schakelaarstatus blijft als geen sensor gevonden wordt.
- Bevat ook alle fixes uit v4.6.127 (JS kaarten, boiler auto-update, Zonneplan offline/modus)

## [4.6.127] - 2026-03-14
### Fixed
- **JS kaarten niet geladen** — `cloudems-decisions-card.js` en `cloudems-prijsverloop-card.js` stonden niet in `_do_storage_work()` resources-lijst in `__init__.py`; HA Storage-mode negeert de `resources:` sectie in de YAML
- **Boiler kaart update niet automatisch** — `_seq` counter toegevoegd aan `extra_state_attributes` zodat HA altijd een attribuut-wijziging ziet en een WebSocket event naar de frontend stuurt, ook als temp en vermogen stabiel zijn
- **Zonneplan "geconfigureerd maar offline"** — `is_online` checkte alleen of SOC beschikbaar was; nu checkt het SOC OF vermogen OF modus — als één van de drie beschikbaar is, is de integratie online
- **Zonneplan "Modus: Unavailable"** — fallback in `sensor.py` las de raw `.state` van de HA select entity zonder te filteren op `unavailable`/`unknown`; nu correct gefilterd

## v4.6.126
- Fix: boiler temperatuur overleeft herstart niet — laatste bekende temp wordt nu opgeslagen in .storage/cloudems_boiler_last_temp_v1 en bij herstart direct hersteld, zodat ook bij Ariston 429 altijd de juiste waarde getoond wordt.

## v4.6.125
- Fix: cloudems-decisions-card.js en cloudems-prijsverloop-card.js stonden NIET in _ALL_JS_RESOURCES in __init__.py — daardoor werden ze nooit gekopieerd naar /local/cloudems/ en gaf HA "Configuratiefout". Beide bestanden nu correct geregistreerd.
- Fix: boiler_status sensor state was altijd "0/1 aan" (nooit veranderend) → HA stuurde geen WebSocket update naar browser. Temperatuur toegevoegd aan state ("0/1 aan · 45.0°C") zodat elke temp-wijziging een browser update triggert.

## v4.6.124
- Fix: ts timestamp verwijderd uit boiler_status attributen — veroorzaakte elke 10s een recorder write wat performance problemen geeft.
- Diagnose: boiler niet-updaten wordt veroorzaakt door watchdog die na 3 coordinator failures de integratie herlaadt. Upload cloudems_high.log na installatie voor exacte foutmelding.

## v4.6.123
- Fix: boiler_status sensor ververst niet automatisch — CoordinatorEntity roept async_write_ha_state() standaard alleen aan als coordinator succesvol was, maar HA kan updates onderdrukken als state onveranderd lijkt. Override van _handle_coordinator_update() toegevoegd die altijd direct async_write_ha_state() aanroept, zodat alle kaarten elke coordinator cyclus (~10s) updaten.

## v4.6.122
- Fix: cloudems-prijsverloop-card toonde "Configuratiefout" — customElements.define verwees nog naar oude klassenaam CloudemsPriceCard i.p.v. CloudemsPrijsverloopCard.
- Fix: Boiler toont streepje na herstart — boiler_controller leest nu bij eerste cyclus de waarde van sensor.cloudems_boiler_{slug}_temp (recorder) als fallback, zodat de laatste bekende temperatuur direct beschikbaar is zonder te wachten op Ariston.

## v4.6.121
- Fix: Boiler status sensor (en alle kaarten die erop lezen) update niet automatisch — HA onderdrukt state-writes als waarde onveranderd is. Opgelost met `_attr_force_update = True` op CloudEMSBoilerStatusSensor: HA schrijft nu altijd naar de state machine, ook als temp en vermogen gelijk zijn.

## v4.6.120
- Fix: card_mod hersteld op Beslissingen tab (CloudEMS heeft eigen cloudems-card-mod.js).
- Fix: Boiler JS card update nooit automatisch — sensor.cloudems_boiler_status krijgt nu een `ts` timestamp in de attributen die elke coordinator cyclus wijzigt. HA detecteert daardoor altijd een state change en de JS card rendert opnieuw.

## v4.6.119
- Fix: Beslissingen tab "Configuratiefout" — card_mod op view-niveau niet ondersteund zonder lovelace-card-mod. Verwijderd.
- Fix: Boiler JS card update nooit automatisch — change detection uitgebreid met last_changed timestamp én water_heater setpoint states, zodat elke coordinator cyclus een re-render triggert.
- Fix: Boiler temp toont streepje na herstart — valt nu terug op sensor.cloudems_boiler_{slug}_temp (recorder sensor) als Ariston temp_c null geeft.

## v4.6.118
- Fix: cloudems-price-card bestond al in cloudems-cards.js (de grote ENERGIEPRIJS kaart). Nieuwe prijsverloop kaart hernoemd naar cloudems-prijsverloop-card om conflict te vermijden.
- Fix: Oude cloudems-price-card verwijderd uit cloudems-cards.js.
- Dashboard gebruikt nu: type: custom:cloudems-prijsverloop-card

## v4.6.117
- Fix: Beslissingen tab toonde "Configuratiefout" door verkeerde inspringing (4 spaties i.p.v. 2). Gecorrigeerd.

## v4.6.116
- Nieuw: `cloudems-price-card.js` — volledige JS card vervangt 3 oude kaarten (💶 Uurprijzen, 📊 Prijsverloop, 🕐 Goedkoopste uren).
- Features: 4 blok-strips per rij, laden-animatie, gouden gloed goedkoopste uur, PV werkelijk/verwacht (3px balk), planning-iconen (accu/EV/boiler/pool/surplus), Vandaag/Morgen tab, prijs in ct/kWh.
- Modules-aware: planning-iconen alleen zichtbaar als betreffende module ingeschakeld is.

## v4.6.115
- UX: "Goedkoopste Warmtebron" (gas vs elektriciteit vergelijking) verplaatst naar de boiler JS card. Toont gas/elektrisch prijs per kWh warmte met aanbeveling, direct onder de setpoint/vermogen rijen.

## v4.6.114
- Fix: "Error adding entity" voor alle nieuwe sensoren — `main_device_info()` bestond niet. Toegevoegd als alias voor `_device_info()`. Conflicterende `sub_device_info()` definitie verwijderd (was al geïmporteerd uit `sub_devices.py`).

## v4.6.113
- Fix: `NameError: DecisionsHistory is not defined` — lazy import ontbrak in coordinator. Zelfde fix voor `init_storage_backend`.
- Fix: `SyntaxError: from __future__ imports must occur at the beginning of the file` — sensor.py en 4 nieuwe modules (decisions_history, storage_backend, telemetry, utils) hadden `from __future__ import annotations` niet als eerste regel.

## v4.6.112
- Nieuw: `docs/ARCHITECTURE.md` — volledige technische documentatie (515 regels): bestandsstructuur, kern-architectuur, coordinator data dict, sensor register, energy manager modules, JS cards, configuratie opties, beslissingsflow, persistente opslag, telemetrie, refactor backlog, bekende issues, en ontwikkelworkflow.

## v4.6.111
- Nieuw: `docs/TELEMETRY_BEHEERDER.md` — volledige handleiding voor Firebase setup, security rules, API key ophalen, CloudEMS configuratie, data lezen als beheerder, GDPR toelichting en kostenraming.

## v4.6.110
- Wijziging: telemetry backend gewijzigd van Google Drive naar Firebase Firestore REST API. Geen SDK of OAuth nodig — alleen een Firebase project_id en API key in CloudEMS instellingen.
- Werkt voor alle gebruikers ongeacht Google account — elke installatie schrijft naar hetzelfde Firebase project via zijn eigen UUID.
- Firestore structuur: `cloudems_telemetry/<installation_id>/hours/<YYYYMMDDTHH00>`
- Configuratie: `telemetry_enabled: true`, `telemetry_firebase_project: <id>`, `telemetry_firebase_key: <key>`

## v4.6.109
- Nieuw: `telemetry.py` — opt-in anonieme diagnostiek naar Google Drive. Elk uur één entry met: versie, uptime, beslissingstypes (geen entity_id/label), foutcodes, boilercycli, coordinator cyclus prestatie (avg/max/p95 ms). GDPR-veilig: geen persoonlijke data, geen energiewaarden, geen locatie.
- Nieuw: `sensor.cloudems_telemetry` — toont telemetrie status en anonieme installatie-ID (eerste 8 chars).
- Bestanden in Drive: `cloudems_telemetry/<installation_id>.json`, rolling 7 dagen.
- Opt-in via CloudEMS instellingen (`telemetry_enabled`). Standaard UIT.

## v4.6.108
- Refactor plan gedocumenteerd in CLAUDE_INSTRUCTIONS.md: `_async_update_data` (4325 regels) wordt over 10 releases opgesplitst in `_gather_sensor_data()`, `_fetch_prices()`, `_evaluate_ev()`, `_evaluate_battery_data()`, `_evaluate_solar()`, `_evaluate_boiler()`, `_evaluate_shutters()`, `_evaluate_prices_costs()`, `_evaluate_intelligence()`, `_build_data_dict()`. Eén stap per release, elke stap apart testbaar. Status wordt bijgehouden in CLAUDE_INSTRUCTIONS.md.

## v4.6.107
- Fix: `sensor.cloudems_goedkoopste_laadmoment` gebruikte niet-bestaande `price_forecast` key — leest nu correct uit `_last_price_info.next_hours`.
- Fix: `CloudEMSAnomalieGridSensor` was duplicaat van bestaande `CloudEMSHomeBaselineSensor` — verwijderd. Notificatie (>15 min anomalie) toegevoegd aan bestaande sensor.
- Fix: `sensor.cloudems_seizoensvergelijking` gebruikte `solar_learner._inverters` — heet `._profiles`. Crashte anders.
- Fix: `decisions_history.py` schrijft nu via `StorageBackend` (met directe JSON fallback) — klaar voor cloud-migratie.
- Nieuw: `utils.py` — centrale `slugify()`, `slugify_entity_id()`, `format_duration()`, `clamp()`. Vervangt 19 losse slug-implementaties.
- Fix: 16 bare `except Exception: pass` in coordinator nu gelogd op DEBUG niveau.
- Fix: Efficiency v1 sensor-registratie verwijderd (v2 met rolling average blijft).
- Fix: f-string syntax error in anomalie notificatie tekst.
- Fix: Beslissingen tab achtergrondstijl in lijn met rest dashboard.

## v4.6.106
- Nieuw: `sensor.cloudems_seizoensvergelijking` — huidige maand vs vorige maand, PV piek, verbruiksprofiel en seizoenstip.
- Nieuw: `sensor.cloudems_boiler_planning` — voorspelt over hoeveel minuten de boiler de volgende keer opwarmt op basis van geleerd thermisch verlies (°C/uur) en hysterese.
- Nieuw: `sensor.cloudems_anomalie_grid` — detecteert aanhoudend afwijkend netverbruik (>15 min boven geleerd patroon) en stuurt HA notificatie met afwijking in Watt.
- Nieuw: `sensor.cloudems_boiler_efficiency_avg` — rolling average efficiëntie over laatste 10 verwarmingscycli met trend analyse (verbeterend/stabiel/verslechterend) en onderhoudswaarschuwing.

## v4.6.105
- Nieuw: Beslissingen tab in dashboard (na Overzicht) met cloudems-decisions-card.
- Fix: Boiler setpoint sensor leest nu van virtual thermostat entity (override waarde) i.p.v. coordinator setpoint.
- Fix: History throttle boiler JS card: 30s bij eerste load, 5 minuten daarna.
- Nieuw: `storage_backend.py` — abstractie-laag voor persistente opslag (LocalFileBackend nu, CloudBackend later bij migratie).
- Nieuw: `suggested_display_precision` op alle nieuwe energie/vermogen sensoren.
- Nieuw: `sensor.cloudems_boiler_efficiency` — efficiëntiescore (0-100%) met interpretatie (Uitstekend/Goed/Matig/Slecht).
- Nieuw: `sensor.cloudems_goedkoopste_laadmoment` — toont goedkoopste moment in 8u, stuurt HA notificatie als besparing >30%.

## v4.6.104
- Nieuw: `decisions_history.py` — ring buffer voor alle CloudEMS beslissingen (24u), schrijft naar `cloudems_decisions_history.json` en overleeft herstart.
- Nieuw: `sensor.cloudems_decisions_history` — exposeert laatste 60 beslissingen als attribuut voor JS card.
- Nieuw: `cloudems-decisions-card.js` — tijdlijn kaart met filter per categorie (batterij, boiler, EV, rolluiken), klikken toont volledige tekst + energie-context.
- Nieuw recorder-sensoren (overleven herstart, beschikbaar voor cloud-migratie):
  - `sensor.cloudems_batterij_soc` — batterij SOC (%)
  - `sensor.cloudems_net_vermogen` — netlevering/afname (W)
  - `sensor.cloudems_zon_vermogen` — totaal PV vermogen (W)
  - `sensor.cloudems_boiler_setpoint` — actueel boiler setpoint (°C)
  - `sensor.cloudems_slider_leveren` — Zonneplan 'leveren aan huis' slider (W)
  - `sensor.cloudems_slider_zonladen` — Zonneplan 'zonneladen' slider (W)

## v4.6.103
- Fix: CloudEMSBoilerTempSensor en CloudEMSBoilerPowerSensor gebruikten entity_id-slug ("ariston") als entity_id maar de rest van het systeem (virtual_boiler, JS card, history fetch) verwacht label-slug ("boiler_1"). Sensoren heten nu correct `sensor.cloudems_boiler_boiler_1_temp` en `sensor.cloudems_boiler_boiler_1_power`. Let op: bestaande recorder-data voor de old entity_id gaat verloren (die was toch leeg).

## v4.6.102
- Fix: Temperatuurverloop en vermogengrafiek toonden "Wacht op recorder" omdat de history fetch entity_id-slug gebruikte ("ariston") maar de recorder-sensoren label-slug hebben ("boiler_1"). Nu wordt label-slug gebruikt met entity_id-slug als fallback.

## v4.6.101
- Fix: JS boiler card temperatuur en vermogen werden alleen bijgewerkt bij plugin-reload. De `set hass` trigger vergeleek alleen `state` en `last_updated` van de boiler_status sensor, maar temp_c en power_w zitten in de attributen. Nu worden ook `temp_c`, `current_power_w`, `is_on` en `active_setpoint_c` per boiler meegenomen in de change-detectie → automatische update elke coordinator-cyclus (~10s).

## v4.6.100
- Fix: Markdown Live status kaart gebruikte `regex_replace` filter (bestaat niet in HA Jinja2) voor slug-berekening. Vervangen door `replace(' ', '_')` — werkt correct voor labels als "Boiler 1" → "boiler_1". Nu ook `override_setpoint_c` als eerste bron (override heeft voorrang boven vboiler temperature).

## v4.6.99
- Fix: `current_temperature` van boiler entity (bijv. Ariston) werd overgeslagen bij state "unavailable". Cloud-integraties bewaren attributes ook na een 429/timeout — nu worden de attributes altijd uitgelezen, met saniteitcheck (5–95°C). De `_last_known_temp_c` cache vult zich daardoor ook na een herstart zodra de eerste 429-response binnenkomt die nog attributes heeft.
- Fix: Markdown Live status kaart toonde setpoint uit `boiler_status` (53°C GREEN cap) i.p.v. de actuele virtual thermostat override waarde. Nu gelijk aan JS card.

## v4.6.98
- Fix: CLAUDE_INSTRUCTIONS.md en virtual_boiler.py (root) hersteld — zip moet altijd compleet blijven.

## v4.6.98
- Fix: CLAUDE_INSTRUCTIONS.md en virtual_boiler.py (root) toegevoegd — ontbraken onterecht sinds 4.6.89.

## v4.6.97
- Fix: tariffs.json ontbrak in zip (was aanwezig in 4.6.88). Hersteld.
- CLAUDE_INSTRUCTIONS.md en losse virtual_boiler.py in root niet hersteld — waren geen onderdeel van de installatie.

## v4.6.96
- Fix: JS boiler card toonde vermogen alleen bij is_heating=true. Nu altijd zichtbaar (ook bij 0 W). Kleur en balk dimmen bij 0W.

## v4.6.95
- Fix: `current_temperature` van de boiler entity (bijv. `water_heater.ariston`) werd gelezen ook als de entity state "unavailable" was — Ariston levert dan geen attributen mee, waardoor `current_temp_c = None`. Nu wordt de entity state eerst gecontroleerd op "unavailable"/"unknown" (zelfde check als bij de optionele temp_sensor). De geconfigureerde temperatuursensor is daarmee echt optioneel.

## v4.6.94
- Fix: `current_temp_c` bleef `None` wanneer `water_heater.ariston` tijdelijk unavailable was tijdens een cloud write-operatie (bijv. bij BOOST/manual setpoint wijziging). Nieuw: `_last_known_temp_c` cache in `BoilerState` — na de eerste succesvolle lezing wordt de temperatuur nooit meer `None`, ook niet bij korte Ariston cloud onderbrekingen.

## v4.6.93
- Fix: JS boiler card setpoint gebruikte entity_id-slug (bijv. "ariston") maar virtual_boiler gebruikt label-slug (bijv. "boiler_1") — mismatch waardoor vboilerSt altijd null was en setpoint altijd 53°C toonde.
- Dashboard: "🚿 Boilers — Live status" markdown kaart tijdelijk terug gezet voor betrouwbare temperatuur/vermogen weergave.

## v4.6.92
- Fix: JS boiler card toonde setpoint uit `boiler_status` (bijv. 53°C GREEN-max) in plaats van de actuele override waarde. Nu wordt `target_temperature` van `water_heater.cloudems_boiler_<slug>` gelezen — de virtual thermostat entity heeft altijd het echte setpoint (ook bij manual/boost override).
- Fix: `maxSp` was `max_setpoint_boost_c || setpoint` — bij manual override met hoog setpoint kon de bar overschieten. Nu `Math.max(setpoint, setpoint_c)` als basis.

## v4.6.91
- Fix: `BoilerPowerSensor.native_value` retourneerde `0` als boiler niet gevonden of vermogen `None` — nu `None` zodat recorder geen onjuist 0W wegschrijft.
- Fix: `BuitenTempSensor` fallback-loop zocht `outdoor_temp_c` in `boiler_groups_status` maar dat veld bestaat niet in die dict — fallback verwijderd.
- Fix: JS boiler card `_fetchHistory` werd elke ~10s getriggerd bij elke sensor state-update → recorder API bombardement. Nu 5-minuten throttle. `_historyPower` geïnitialiseerd in constructor.
- Audit: gehele codebase gecontroleerd — boiler_controller.py public API, coordinator data flow, alle JS cards, alle 204 dashboard cards, unique_id conflicts (geen gevonden), device_info/state_class aanwezig op alle nieuwe sensoren.

## v4.6.90
## v4.6.90
- Fix: `async_turn_on` riep `clear_manual_override` en `resume_boost` niet aan → controller bleef tot 4u geblokkeerd na "Aan" in UI.
- Fix: `async_turn_off` riep `set_manual_override` niet aan → controller negeerde de 24u-uit-override en zette boiler na 10s gewoon weer aan.
- Fix: `OP_ECO` riep `clear_manual_override` niet aan → bij wisseling van MANUAL naar ECO bleef controller geblokkeerd voor resterende MANUAL-timer.
- Fix: `OP_MANUAL` sp-berekening gebruikte `or`-operator — bij `setpoint_c=0.0` vóór eerste cyclus werd 0°C gestuurd. Nu expliciete `is not None` check met fallback 53°C.
- Fix: `CloudEMSEVPowerSensor` gebruikte niet-bestaand `session_phases` veld — vereenvoudigd naar `session_current_a × 230V` (identiek aan `_ev_w()` helper).
- Fix: `CloudEMSBoilerPowerSensor.native_value` retourneerde `0` als boiler niet gevonden of vermogen `None` is — nu `None` zodat recorder geen onjuist 0W wegschrijft.
- Fix: `CloudEMSBuitenTempSensor` fallback-loop zocht `outdoor_temp_c` in `boiler_groups_status` maar dat veld bestaat niet — misleidende fallback verwijderd.
- Fix: JS boiler card `_fetchHistory` werd elke ~10s aangeroepen (bij elke sensor state-update) → recorder API bombardement. Nu throttle van 5 minuten. `_historyPower` geïnitialiseerd in constructor.

## v4.6.89
- Fix: Virtual thermostat manual modus stuurde geen `set_manual_override` naar de controller — boiler bleef in `hold_off` steken als OP_MANUAL werd geactiveerd zonder setpoint-wijziging.
- Fix: OP_STALL reset wiste `_manual_override_until` niet — na boost/legionella bleef controller blokkeren. Nu wordt `clear_manual_override` aangeroepen bij stall-reset.
- Nieuw: `CloudEMSBoilerTempSensor` — per boiler `sensor.cloudems_boiler_<slug>_temp` (device_class: temperature, recorder). Dynamisch geregistreerd zodra boilers bekend zijn.
- Nieuw: `CloudEMSBoilerPowerSensor` — per boiler `sensor.cloudems_boiler_<slug>_power` (device_class: power, recorder).
- Nieuw: `CloudEMSBuitenTempSensor` — `sensor.cloudems_buiten_temp` (°C, recorder). Persists als externe weer-entity tijdelijk unavailable is.
- Nieuw: `CloudEMSPoolWaterTempSensor` — `sensor.cloudems_pool_water_temp` (°C, recorder).
- Nieuw: `CloudEMSEVPowerSensor` — `sensor.cloudems_ev_laad_power` (W, recorder). Berekend via session_current_a × 230V × fasen.
- Fix: JS boiler card temperatuurgraaf haalt history op van `sensor.cloudems_boiler_<slug>_temp` i.p.v. `water_heater.*` — die had geen numerieke state (altijd "Geen history beschikbaar").
- JS boiler card: dual grafiek temperatuur + vermogen naast elkaar, 4 uur venster.
- JS boiler card: beslissingslog per boiler toegevoegd (max 8 unieke regels, duplicaten samengevouwen).
- Dashboard: "Boilers — Live status", "Beslissingen", "Sturing & triggers", Dimmer/COP conditionele kaarten verwijderd van boiler-tab.
- Dashboard: "Leerdata wissen (alle groepen)" knop verplaatst naar Leerdata Beheer grid.
- README: "Own your data" ontwerpprincipe gedocumenteerd — alle fysieke waarden die CloudEMS intern gebruikt moeten een eigen `sensor.cloudems_*` entity hebben.

## v4.6.85
- Fix: Na verwijderen van het CloudEMS dashboard via de HA UI en integratie herladen, werd het dashboard niet opnieuw aangemaakt. Na schrijven van de storage files wordt nu ook lovelace systeem reload geforceerd.
- Nieuwe cloudems-zelfconsumptie-card.js — toont nooit meer "Entiteit niet gevonden".

## v4.6.83
- Fix: Zelfconsumptie kaart toonde 4x "Entiteit niet gevonden". HA `type: attribute` rows tonen deze fout wanneer de sensor `unavailable` is — dit is HA gedrag dat niet omzeild kan worden met een entities card. Vervangen door `type: template` rows die altijd `—` tonen als de waarde ontbreekt, ongeacht de sensor state.

## v4.6.82
- Fix: Beheer card (Alles tab) stretchte niet volledig over de breedte. `:host` had geen `display:block` waardoor het element als inline gedroeg. Toegevoegd: `display:block; width:100%` op `:host` + `getLayoutOptions()` met `grid_columns:4` zodat HA de card de volledige kolombreedte geeft.

## v4.6.81
- Fix: Boiler, shutter en beheer cards onterecht van prod naar dev verplaatst — die werkten gewoon. Alleen solar-card en battery-card naar dev dashboard (die tonen nog fouten). Prod dashboard hersteld.
- Dev dashboard aangemaakt (`cloudems-dashboard-dev.yaml`) met solar-card en battery-card voor verdere tests.

## v4.6.80
- Fix: `SolarLearner`, `PVForecast` en `SolarDimmer` ontbraken in de `coordinator_startup` log (`active_modules`). Hierdoor was niet te zien of de solar modules actief waren na herstart. Nu gelogd als `SolarLearner`, `PVForecast`, `SolarDimmer` in het opstartrapport.
- Analyse GitHub issue #21: gebruiker heeft nooit werkende PV gehad ondanks geconfigureerde omvormer. Oorzaak: `SolarLearner` initialiseerde niet. Oplossing voor gebruiker: CloudEMS opties → Omvormers → opnieuw configureren → opslaan → HA herstarten. De logging fix in deze versie maakt dit soort problemen direct zichtbaar in de toekomst.

## v4.6.79
- Intern: CLAUDE_INSTRUCTIONS bijgewerkt met verplichte GUI editor regel (bij elke nieuwe/bijgewerkte card) en correcte sensor mapping tabel (welke data van welke sensor komt).

## v4.6.78
- Nieuw: GUI editors voor alle 7 custom cards — "Visuele editor niet ondersteund" melding verdwijnt:
  - `cloudems-battery-card`: titel
  - `cloudems-solar-card`: titel
  - `cloudems-shutter-card`: titel, toon leervoortgang (checkbox)
  - `cloudems-boiler-card`: titel, tank inhoud, koud water temp, douchetemperatuur, liter/min, douchetijd
  - `cloudems-beheer-card`: titel, max beslissingen
  - `cloudems-pv-forecast-card`: titel, toon morgen forecast, EPEX overlay, onzekerheidsband (checkboxes)
  - `cloudems-switches-card`: had al editor (titel, acties, annuleer-knop)
  Elke editor stuurt `config-changed` events zodat HA de kaart direct opslaat.

## v4.6.77
- Fix KRITISCH: Beheer card las alle data van de verkeerde sensor. `sensor.cloudems_status` heeft alleen `system`, `guardian`, `watchdog` en `shutters` — geen `version`, `battery_decision`, `decision_log`, `boiler_status` of `inverter_data`. Correcte sensor mapping:
  - `version` → `sensor.cloudems_watchdog.attributes.cloudems_version`
  - `decision_log` → `sensor.cloudems_watchdog.attributes.last_10`
  - `battery_decision` → `sensor.cloudems_batterij_epex_schema.attributes`
  - `boilers` → `sensor.cloudems_boiler_status.attributes.boilers`
  - `soc_pct` → `sensor.cloudems_batterij_epex_schema.attributes.soc_pct` (Zonneplan fallback)
  - `shutters` → `sensor.cloudems_status.attributes.shutters.shutters` (was al correct)
- Fix: Beheer card `hass` setter watchte verkeerde sensoren en miste updates van batterij/solar.
- Test: 20/20 geautomatiseerde tests groen voor release.

## v4.6.76
- Fix KRITISCH: Battery card re-renderde nooit na cold start. De `hass` setter watchte `sensor.cloudems_battery_schedule` (oude naam, bestaat niet) en `sensor.cloudems_battery_so_c` (altijd unavailable bij Zonneplan). Nu worden ook `sensor.cloudems_batterij_epex_schema`, de `soc_pct` attribuut, en `sensor.cloudems_battery_power` gewatcht — SoC-wijzigingen van Zonneplan triggeren nu correct een re-render.
- Fix: Solar card `hass` setter watchte niet `switch.cloudems_module_solar_learner` — als de module aanging zonder dat de sensoren veranderden, bleef de card op "Laden..." staan. Nu ook module-switch en `inverter_data` count gewatcht.
- Fix: Beheer card (Alles tab) te smal. Card heeft nu `width:100%` en de module-grid gebruikt `auto-fill` met `minmax(160px,1fr)` voor responsive kolommen op elke breedte.
- Test: 18/18 geautomatiseerde tests groen voor release.

## v4.6.75
- Revert: Zelfconsumptie kaart teruggezet naar `type: entities` (was onterecht omgezet naar markdown in 4.6.74). De onderliggende bugs (verkeerde entity ID + dode code) zijn al gefixed in 4.6.64 en 4.6.69. De entities kaart werkt correct met `sensor.cloudems_self_consumption`.

## v4.6.74
- Fix: Solar sensor `native_value` retourneerde `None` bij cold start (coordinator.data nog leeg) waardoor solar card bleef tonen "Geen omvormer geconfigureerd". Nu retourneert de sensor alleen `None` als `coordinator.data is None`, anders altijd `0.0` of hoger.
- Fix: Solar JS card toont bij unavailable + module ON geen "geen omvormer" meer maar een neutrale laadstate. Toont alleen "geen omvormer geconfigureerd" als de module UIT staat EN er geen inverter data aanwezig is.
- Fix: Zelfconsumptie kaart vervangen van `type: entities` (met `type: attribute` rijen die crashen bij unavailable sensor) naar een `markdown` card die graceful degradeert — toont "Laden..." bij unavailable en de actuele data zodra de sensor beschikbaar is.
- Geverifieerd: `sensor.cloudems_self_consumption` valt buiten alle pruner-prefixen — orphan pruner verwijdert deze sensor nooit.

## v4.6.73
- Fix: Shutter card crash bij render — `Object.values(h.states)` gaf state-objecten zonder `entity_id` property terug (normaal HA gedrag). `e.entity_id.startsWith(...)` crashte met TypeError. Gefix met optional chaining: `e?.entity_id?.startsWith(...)`.
- Test: 20 geautomatiseerde tests gedraaid in Node.js simulator voor battery, solar, shutter en beheer card. Alle 20 groen vóór het zippen.

## v4.6.72
- Fix: Interactieve beheerkaart (Alles tab) toonde nog steeds de kleine flow-card. Oorzaak: `cloudems-cards.js` definieert zelf ook al een `cloudems-overview-card` element (de compacte hero-kaart), waardoor de nieuwe interactieve card altijd verloor. Interactieve card hernoemd naar `cloudems-beheer-card` — geen naamconflict meer.
- Fix: Solar card toonde "Geen omvormer geconfigureerd" ook als er wel omvormers zijn maar de sensor `unavailable` is (bijv. 's nachts door de 0W→None bug). Card valt nu terug op het `inverters` attribuut als dat beschikbaar is, ook bij unavailable state.

## v4.6.71
- Fix: Alles tab toonde de kleine cloudems-flow-card (4 waarden) in plaats van de interactieve beheerkaart. Oorzaak: de nieuwe card was geregistreerd als `cloudems-control-card` maar het dashboard vroeg `custom:cloudems-overview-card`. Het bestand heet `cloudems-overview-card.js` maar de `customElements.define()` gebruikte de verkeerde naam. Gefix: element heet nu `cloudems-overview-card`, alias `cloudems-control-card` voor compatibiliteit.

## v4.6.70
- Fix: Shutter card flikkerde elke seconde. De `hass` setter keek naar `st?.last_updated` en de volledige state van override-restant sensoren (HH:MM:SS countdown). Die veranderen elke seconde → re-render elke seconde → visuele flicker. Nu wordt alleen gehasht op inhoudelijke data: rolluikposities, last_action, auto_enabled, override_active, module aan/uit. Override timers triggeren alleen een re-render als een timer verschijnt of verdwijnt — niet bij elke afteltik.

## v4.6.69
- Fix: Solar card toonde "Geen omvormer geconfigureerd" 's avonds en 's nachts. `CloudEMSSolarSystemSensor.native_value` deed `round(...) or None` — in Python is `0.0 or None = None`, dus bij 0W productie werd de sensor `unavailable`. De solar card interpreteert `unavailable` als "niet geconfigureerd". Fix: sensor geeft nu altijd een waarde terug (ook 0.0) zolang er omvormers geconfigureerd zijn.
- Fix: Zelfconsumptie entities-kaart toonde "Entiteit niet gevonden" voor alle attribute-rijen. `CloudEMSSelfConsumptionSensor.native_value` had dode code: een tweede `return`-statement met de attributen die nooit bereikt werd (Python stopt bij de eerste `return`). De attributen `best_solar_hour`, `monthly_saving_eur`, `advice` etc. zijn verplaatst naar `extra_state_attributes`. Dashboard hersteld naar de originele attributen.

## v4.6.68
- Fix: Batterij card toonde "Geen batterij geconfigureerd" terwijl Zonneplan Nexus wél actief is. `sensor.cloudems_battery_so_c` geeft `null` terug wanneer de batteries-array leeg is (Zonneplan gebruikt een ander data-pad). Fallback toegevoegd: card leest SoC nu ook uit `sensor.cloudems_batterij_epex_schema` attributen (`soc_pct`).
- Fix: Zelfconsumptie entities-kaart toonde "Entiteit niet gevonden" voor 4 attribute-rijen. Attributen `best_solar_hour` en `monthly_saving_eur` bestaan niet in de sensor. Vervangen door de bestaande attributen: `self_covered_kwh`, `total_consumption_kwh`, `grid_import_kwh`, `advice`.
- Fix: CloudEMS Control Card (Alles tab) re-renderde elke seconde door `new Date().toLocaleTimeString()` in de HTML. `sh.innerHTML !== html` was altijd `true` door de veranderende timestamp, waardoor tabs en interactie niet werkten. Timestamp verwijderd uit de render-string.
- Fix: Boiler card — temperatuur/liters/douche-tellers begonnen altijd bij 0 bij elke update, waardoor de animatie telkens opnieuw optelde. Nu worden de tellers geanimeerd van de vorige weergegeven waarde naar de nieuwe waarde — alleen zichtbaar verschil als de waarde echt verandert.

## v4.6.67
- Fix KRITISCH: JS-cards werden niet geladen via de Lovelace resources API. `_async_register_panel()` registreerde alleen `cloudems-cards.js` en `cloudems-card-mod.js`. Nu worden alle 9 JS-resources geregistreerd via `_ALL_JS_RESOURCES` constante in `__init__.py` — dit is de enige plek die HA Storage-mode dashboards gebruikt voor custom element loading.
- Nieuw: `cloudems-overview-card` v2.0 — volledig interactieve beheerkaart met 5 tabs: Overzicht (energiestroom + beslissingen), Modules (15 tiles, klik om aan/uit te zetten), Rolluiken (open/stop/sluit per rolluik + automaat toggle), Boiler (modus kiezen + setpoint instellen per boiler), Batterij (SoC ring, vermogen, laden/ontladen/auto knoppen voor Zonneplan). Klaar voor gebruik als enige kaart op de Alles tab.

## v4.6.66
- Fix: Template crash op batterij-tab — `zp.get('probe_current_w', 0) | int` en `zp.get('probe_confirmed_w', 0) | int` crashen als de key bestaat maar `None` als waarde heeft (dict `.get()` default geldt alleen bij ontbrekende key). Vervangen door `| int(0)` (Jinja2 default bij None/fout). Zelfde fix voor `lmd | int` en `lms | int` in de Zonneplan max-vermogen templates.

## v4.6.65
- Fix KRITISCH: alle nieuwe JS-kaarten (battery, solar, boiler, shutter, pv-forecast, overview, switches) werden nooit geladen. In `__init__.py` werden de Lovelace storage-resources overschreven met alleen `cloudems-cards.js` en `cloudems-card-mod.js` — de `resources:` sectie uit de YAML wordt door HA Storage-mode genegeerd. Alle 9 JS-resources worden nu programmatisch geregistreerd bij iedere HA-herstart. Na installatie + HA-herstart laden alle custom cards correct.

## v4.6.64
- Fix: `sensor.cloudems_pv_zelfconsumptiegraad` was een verkeerde entity ID — alle 7 verwijzingen vervangen door de correcte `sensor.cloudems_self_consumption` (expliciete entity_id in sensor.py). Dit veroorzaakte Configuratiefout op de Solar tab.
- Fix: Boiler tab — `type: thermostat` in cloudems-entity-list werkt alleen met `climate.*` entities, niet met `water_heater.*`. Vervangen door `type: entities` met titel "Virtuele thermostaten". Dit veroorzaakte twee Configuratiefout kaarten bovenaan de Warm Water tab.
- Fix: Cache busters bijgewerkt naar v=4.6.64 in alle JS resource-URLs.

## v4.6.63
- Nieuw: `cloudems-overview-card.js` v1.0 — alles-in-één kaart met energiestroom (solar/grid/batterij/huis), module-status tiles (15 modules, AAN/UIT + detail), NILM actieve apparaten, rolluiken samenvatting, boiler status, recente beslissingen log.
- Nieuw: Dashboard tab "Alles" (path: cloudems-alles) met de overview card — volledig overzicht van heel CloudEMS op één tab.
- Fix: Rolluiken tab — `cloudems-shutter-card` v2.0 nu als primaire kaart boven de legacy markdown. Beslissingen en shadow-hints zichtbaar in de JS card.
- Fix: Cache busters bijgewerkt van 4.6.61 naar 4.6.63 in alle JS resource-URLs — HA laadt voortaan de juiste versies.

## v4.6.62
- Nieuw: cloudems-battery-card v2.0 — SoC arc animatie, schema-tijdlijn (24u), live vermogen flow-bar, multi-batterij rijen, kWh vandaag, Ariston verify/retry badge, beslissingsreden.
- Nieuw: cloudems-solar-card v2.0 — live vermogen, forecast vandaag/morgen, uurlijkse yield-barchart, omvormer rijen met utilisation bar, oriëntatie/fase/clipping chips, forecast nauwkeurigheid.
- Nieuw: cloudems-shutter-card v2.0 — animated blind-visualisatie per rolluik (positie als gesloten slats), summary strip, auto/override/open badges, shadow-hint bij uitgeschakelde automaat, override-timers sectie. Fix: triggert nu ook op last_updated zodat unavailable→available overgang altijd opvangt.
- Fix: Boiler tab — kapotte entities-kaart (sensor.cloudems_goedkoopste_warmtebron bestaat niet) vervangen door werkende markdown. Redundante "Setpoint instellen" tekst-only kaart verwijderd.
- Nieuw: Boiler tab kolom 2 — cloudems-entity-list kaart met alle water_heater.cloudems_* entiteiten (virtuele thermostaten) plus sturing & triggers markdown.
- Fix: cloudems-dashboard.yaml niet in zip-root geplaatst.

## v4.6.61
- Nieuw: `cloudems-battery-card.js` — volledig nieuwe custom card voor de batterij-tab. Toont: SoC-ring met kleurcodering (groen/amber/rood), live vermogen met bidirectionele powerbar, kWh geladen/ontladen vandaag, actie-badge (Laden/Ontladen/Idle/Gestopt), reden van beslissing, en per-batterij rijen bij meerdere batterijen.
- Nieuw: `cloudems-solar-card.js` — volledig nieuwe custom card voor de zon-tab. Toont: huidig totaalvermogen, forecast vandaag/morgen, uur-voor-uur forecast barchart, per-omvormer rij met utilisation-bar, azimuth/tilt/fase/clipping badges, en forecast nauwkeurigheidsindicator.
- Fix: Boiler-tab — verwijderd de kapotte `entities` kaart met `sensor.cloudems_goedkoopste_warmtebron` (sensor bestaat niet → toonde 2× Configuratiefout). Vervangen door werkende `⚡ Sturing & triggers` markdown met EPEX prijs, PV forecast en per-boiler modus.
- Nieuw: Boiler-tab — virtuele thermostaat `water_heater.cloudems_*` entiteiten getoond via `cloudems-entity-list`.
- Nieuw: `cloudems-solar-card.js` toegevoegd aan dashboard resources.

## v4.6.61
- Nieuw: cloudems-boiler-card.js — tank SVG, liters, douches, 24u grafiek, donut, COP, multi-boiler tabs
- Fix: Configuratiefout kaarten verwijderd (sensor.cloudems_goedkoopste_warmtebron bestaat niet)
- Fix: Overbodige Setpoint instellen markdown verwijderd
- Nieuw: Virtuele thermostaat kaart op boiler-tab via cloudems-entity-list water_heater.cloudems_*
- Dashboard: JS resources geupdate naar v4.6.61 cache-buster
## v4.6.60
- Nieuw: Ariston cloud verify/retry systeem. Na elke preset-commando naar de fysieke boiler wordt de gewenste state opgeslagen als `_pending`. Bij elke coordinator-cyclus (~10s) checkt `async_verify_pending()` of de Ariston de setting ook echt heeft verwerkt door de actuele `operation_mode` en `temperature` te vergelijken. Bij mismatch → retry met backoff (15s, 30s, 60s, 120s). Max 4 retries, daarna waarschuwing in logs.
- Nieuw: 429 rate-limit detectie — bij een HTTP 429 response wacht CloudEMS automatisch 3 minuten voor de volgende poging (`ARISTON_RATE_LIMIT_S = 180`).
- Nieuw: Constanten voor tuning: `ARISTON_VERIFY_DELAY_S` (15s), `ARISTON_RETRY_BACKOFF` ([15,30,60,120]s), `ARISTON_MAX_RETRIES` (4), `ARISTON_RATE_LIMIT_S` (180s), `ARISTON_TEMP_TOLERANCE` (±1°C).
- Nieuw: Verify logt `✓ Ariston cloud verify OK` zodra de state overeenkomt, inclusief het aantal retries dat nodig was.

## v4.6.59
- Fix: Virtuele boiler — operatiemodi `boost`, `legionella` en `stall` deden niets (vielen in de `else`-tak die alleen een debug log schreef). Alle drie afgehandeld:
  - `boost`: roept `force_boost_once()` aan en stuurt direct `send_now` met `max_setpoint_boost_c` als setpoint (4u override).
  - `legionella`: roept `force_legionella()` aan en stuurt direct `send_now` met ≥65°C setpoint (2u override).
  - `stall`: reset stall-detectie via `force_stall_reset()` en stuurt boiler opnieuw aan met huidig setpoint.
- Fix: Override-verloopadres breidt nu ook `clear_manual_override()` aan zodat na BOOST/LEGIONELLA de coordinator het setpoint correct overneemt.
- Nieuw: `force_boost_once()`, `force_legionella()`, `force_stall_reset()` methodes toegevoegd aan `BoilerController`.

## v4.6.58
- Fix: Rolluiken tab — Status & Beslissing kaart toonde lege inhoud. Oorzaak: de `---`, `####`, `💬` en `🤖` regels stonden op kolom 0 in de YAML `|-` block scalar. YAML interpreteert `---` op kolom 0 als documentseparator waardoor de block scalar werd afgekapt vóór de eigenlijke output-regels. Jinja2 kreeg een onvolledige template (zonder `endfor`/`endif`) en renderde niets. Fix: alle output-regels ingesprongen naar 8 spaties.

## v4.6.57
- Fix: Boiler setpoint van virtuele thermostaat werd niet doorgezet naar fysieke boiler bij handmatige override. Oorzaak: bij BOOST-modus stuurde `_switch()` altijd `max_setpoint_boost_c` (bijv. 75°C) als setpoint, ook als de gebruiker een lagere waarde (bijv. 71°C) had ingesteld. Fix: als `_manual_override_until` actief is én `active_setpoint_c < max_setpoint_boost_c`, wordt het handmatige setpoint gebruikt.
- Fix: Delays toegevoegd in de stuurvolgorde voor Ariston Lydos (preset-mode): 2s na `set_operation_mode` zodat cloud-sync verwerkt is vóór `set_value(max_setpoint)`, en 1s daarna vóór `set_temperature`. Voorkomt dat max_setpoint of setpoint genegeerd wordt door timing-issues.
- Fix: `cloudems-dashboard.yaml` werd per ongeluk in de zip-root geplaatst. Dashboard YAML staat uitsluitend in `custom_components/cloudems/www/`.
- Fix: `asyncio` toegevoegd als top-level import in `boiler_controller.py` (was alleen lokaal geïmporteerd).

## v4.6.56
- Fix: Alle ontbrekende vertaalsleutels toegevoegd aan nl/en/de/fr (189 sleutels — o.a. boiler_unit, boiler_brand, managed_battery, dsmr_source, price_provider, cheap_switches, phase_sensors, ai_config, ollama_config, features, peak_config). Config flow toont nu overal correcte labels.
- Fix: cloudems-shutter-card triggert nu ook bij `last_updated` en `state` wijzigingen van sensor.cloudems_status (was alleen last_changed). Kaart bleef leeg na sensor-unavailable state.
- Fix: cloudems-shutter-card toont nu een duidelijke foutmelding als sensor.cloudems_status unavailable/unknown is, i.p.v. een lege kaart.

## v4.5.130
- Fix: Crash bij opstarten — `async_set_discharge`, `async_set_auto` en `get_wizard_hint` waren per ongeluk verwijderd tijdens de probe-cleanup in v4.5.128/129. Hersteld.

## v4.5.130
- Fix: Alle verwijzingen naar MIT License vervangen door CloudEMS Proprietary License (zie LICENSE bestand). Betreft: dashboard YAML footers, README badge en footer, docs/CLOUDEMS_SAAS_ROADMAP.md, Python bestandsheaders.

## v4.5.129
- Fix: CLAUDE_INSTRUCTIONS.md gecorrigeerd — dashboard-yaml root sync verwijderd (root dashboard bestaat niet meer)
- Refactor: Zonneplan slider max-probe systeem volledig verwijderd. Slider maxima worden nu direct uitgelezen uit het `max` attribuut van de HA number-entiteit (bijv. `max: 10000`). Geen stapsgewijze kalibratie meer nodig.
- Knop "Slider max leren" hernoemd naar "Slider max vernieuwen" — leest attributen opnieuw uit en toont de waarden.

## v4.5.128
- Fix: Slijtagekosten batterij toonden 360 ct/kWh door foutieve formule (chemistry_factor vermenigvuldigd in plaats van gedeeld door levensduurcycli). Correcte formule: `battery_price / (capacity_kwh × total_cycles)`.
- Fix: Standaard batterijprijs gecorrigeerd naar €4.190 (Zonneplan Nexus 10 kWh, incl. installatie, na btw-teruggave, prijspeil 2026).
- Nieuw: Nexus-prijstabel toegevoegd voor alle capaciteiten (10/15/20/30 kWh) met automatische interpolatie. Slijtagekosten kloppen nu altijd zonder handmatige prijsinvoer.
- Nieuw: Geleerde batterijcapaciteit (`BatterySocLearner`) wordt nu doorgegeven aan `BatteryCycleEconomics` in zowel `battery_scheduler` als `zonneplan_bridge`, zodat slijtagekosten ook kloppen als capaciteit niet handmatig is geconfigureerd.
- Fix: Boiler temperatuursensor-selectie: als de geconfigureerde `bu_temp_sensor` meer dan 15°C afwijkt van de `current_temperature` van de boiler-entiteit zelf (bijv. koud-inlaat sensor), gebruikt CloudEMS automatisch de boiler-entiteit temperatuur. Setpoints (normaal/boost/surplus) worden niet aangepast.
- Fix: Zonneplan slider max-leer test hing op eerste stap: readback kon niet onderscheiden tussen cloud-sync vertraging en een geclipte sliderwaarde. Geclipte waarden (slider springt terug naar `confirmed_w`) worden nu direct herkend zonder 3× 60s wachttijd.

## v4.5.126
- Fix: Probe readback vergeleek de gestuurde waarde met de HA-entity state zonder te controleren of de cloud de write al verwerkt had. Als de Zonneplan cloud traag is (poll-interval > 60s) of als de slider handmatig op 10000W was gezet, las de readback de verkeerde oude waarde en maakte verkeerde beslissingen.
  - Nieuw: `_probe_state_before_w` — entity-waarde wordt opgeslagen vóór elke write
  - Readback detecteert nu "state ongewijzigd" (actual ≈ before ≠ sent) → wacht tot 3× 60s extra (max 3 min) zodat de cloud-sync afloopt
  - Na 3 retries: waarschuwing in probelog en doorgaan met beschikbare waarde
- Feature: Probe diagnostieklog (`_probe_log`, max 100 regels):
  - Elke probe-stap (STUUR / READBACK / GEACCEPTEERD / FASE2 / KLAAR) wordt gelogd met timestamp
  - Zichtbaar in `get_status()` als `probe_log` veld
  - Nieuwe service `cloudems.dump_probe_log`: schrijft log naar `/config/cloudems_probe_log.txt` én toont als HA persistent notificatie
  - Gebruik dit om probe-problemen te debuggen

## v4.5.125
- Feature: ACRouter (RobotDyn DimmerLink hardware) integratie voor variable boiler sturing.
  - Nieuw `control_mode: "acrouter"` in boiler-configuratie
  - Nieuw veld `acrouter_host: "192.168.x.x"` — IP-adres van het ACRouter device
  - CloudEMS stuurt via REST API: surplus → MANUAL mode + dimmer%, goedkoop uur → BOOST (100%), uit → OFF
  - Debounce: minimale 10s tussen dimmer-updates, alleen sturen bij ≥5% wijziging
  - Geen HA-entity vereist — controle gaat volledig via HTTP naar het ESP32 device
  - `_is_on` detectie via interne mode-tracking (geen HA state polling nodig)
  - Graceful fallback bij ontbrekende host of aiohttp-fout (WARNING log, geen crash)
  - Firmware vereist: ACRouter v1.2.0+ (MQTT + HA support release, dec 2025)

## v4.5.124
- Fix: `_start_probe_for_key` resettte `probe_last_run` niet — inconsistentie met handmatige start. Nu ook gereset naar 0.0 zodat de 30-dagen reprobe-timer correct herstart.
- Fix: Probe startte op `current_max + 1000W` ook als current_max nog op default (10000W) stond → eerste testwaarde was 11000W, buiten slider-range. Nu geldt: als max nog op default staat begint de probe bij 1000W en `probe_confirmed_w` bij 0W. Bij herprobe (max al geleerd) blijft het `current_max + 1000W` gedrag behouden.

## v4.5.123
- Fix: `async_force_slider_calibrate` (knop "Slider kalibratie") gebruikte `self._effective_discharge_w` / `self._effective_charge_w` — die worden begrensd op het geleerde maximum. Daardoor stuurde de knop nooit meer dan 400/600W. Nu worden de ongeclampte `_charge_w` / `_discharge_w` gebruikt.
- Fix: `async_force_slider_calibrate` mag niet starten tijdens een actieve max-probe — retourneert nu direct een foutmelding zodat de twee processen elkaar niet in de weg zitten.
- Fix: `_set_slider_idempotent` readback-callback paste `learned_max` aan terwijl een probe actief was — dit vervuilde de probe-resultaten. Guard toegevoegd: readback slaat learned_max update over als `_probe_active = True`.
- Fix: `probe_last_run` werd niet gereset bij handmatige herstart via "Slider max leren" knop — hierdoor dacht het systeem de reprobe-timer al te hebben lopen. Nu gereset naar 0.0 bij handmatige start.
- Feature: Dashboard toont nu Fase (grof 1000W / verfijning 100W) en slider-naam (Leveren aan huis / Zonneladen) tijdens actieve probe.
- Feature: `sensor.cloudems_zonneplan_kalibratie` — losse sensor met state `niet_gestart` / `bezig` / `klaar` en attributen `progress_pct`, `probe_fase`, `probe_key_label`, `learned_max_deliver_w`, `learned_max_solar_w`.
- Fix: `services.yaml` — entity-velden krijgen `entity: {}` selector, boolean-velden `boolean: {}`, area-velden `area: {}`.

## v4.5.122
- Fix: Probe werd elke 10 seconden overschreven door de normale coordinator-cyclus (400/600W). Guards toegevoegd in `async_apply_forecast_decision_v3`, `async_set_charge` en `async_set_discharge`: als `_probe_active = True` wordt alle slider-sturing overgeslagen.
- Fix: `probe_confirmed_w`, `probe_step_w` en `probe_key` worden nu geëxporteerd in `get_status()` en doorgegeven via `sensor.py` naar het dashboard.
- Feature: Probe-state (`probe_active`, `probe_key`, `probe_current_w`, `probe_confirmed_w`, `probe_step_w`) wordt nu gepersisteerd in HA Storage en hersteld na herstart. Probe hervat automatisch na 30s.

## v4.5.121
- Fix: `zonneplan_info` in `sensor.py` miste `learned_max_deliver_w`, `learned_max_solar_w`, `probe_active`, `probe_current_w`, `probe_confirmed_w` — dashboard kon geen progress bar tonen.
- Fix: `probe_confirmed_w` ontbrak in `get_status()` export van `ZonneplanProvider`.

## v4.5.120
- Fix: `BatteryProviderRegistry: property '_effective_charge_w' of 'ZonneplanProvider' object has no setter` — `__init__` en `update_config` schreven naar `self._effective_charge_w` terwijl dat een `@property` zonder setter is. Backing variabelen hernoemd naar `_charge_w` en `_discharge_w`.
- Fix: `services.yaml` duplicate key `meter_topology_approve` op regels 991 en 1036 — tweede blok verwijderd, selectors verbeterd van `text: {}` naar `entity: {}`.

## v4.5.113
- Fix: `human_reason` wordt nu getoond als extra rij **Toelichting** naast de bestaande **Reden** (niet als vervanging). Reden toont technische `all_reasons`, Toelichting toont leesbare `human_reason` — alleen zichtbaar als gevuld.

## v4.5.112
- Fix: `human_reason` werd nooit in de sensor-attributen geschreven — alleen in het beslissingslog. Nu wordt `battery_schedule["human_reason"]` gevuld vanuit het Zonneplan-resultaat (beide paden: with_scheduler en standalone), en `sensor.py` exposeert het als attribuut. Dashboard toont nu daadwerkelijk de leesbare reden.

## v4.5.111
- Fix: Dashboard toont nu `human_reason` (leesbare beslissingsreden) in alle weergaven — prod dashboard, dev dashboard, battery card en dashboard.html. Fallback naar technische `reason` als `human_reason` leeg is.

## v4.5.110
- Feature: PV forecast seeding vanuit `solar_learner` — na herstart worden ontbrekende uren gevuld met leerdata zodat `pv_kwh_next_8h` niet onterecht op 0 staat.
- Feature: Saldering-bewuste batterijbeslissingen — PV-hold drempel schaalt mee met het actuele salderingspercentage (`net_metering_pct`).
- Feature: `human_reason` veld in `DecisionResult` — alle beslissingstakken geven nu een leesbare Nederlandstalige reden terug.
- Feature: `NET_METERING_PHASES` per land in `const.py` met helper `get_net_metering_pct()` — NL 2025: 64%, 2026: 36%, 2027: 0%.

## v4.5.85
- Fix: content: > vervangen door content: | zodat newlines behouden blijven in markdown tabellen

## v4.5.84
- Fix: Energie Monitor markdown tabel rendert nu correct ({% set %} en {% for %} op dezelfde regel als pipe-tekens)

# Changelog

## [4.5.66] — 2026-03-11

### Zelflerend batterijsysteem (battery_soc_learner.py — nieuw)

Nieuwe module die zonder geconfigureerde sensoren zelfstandig leert:

- **SOC (state of charge)**: ankerdetectie via vermogenspatronen (vol-anker na ≥10 min laden, leeg-anker na ≥5 min ontladen). Tussen ankerpunten wordt SOC geïntegreerd via vermogen × tijdstap met 96% rendementscorrectie. Confidence daalt gradueel naarmate het laatste anker verder weg is (0.90 → 0.20 over 12 uur). Na 24 uur zonder anker drijft SOC terug naar 50%.
- **Capaciteit** (twee methoden parallel): methode A met sensor — Wh per SoC-% mediaan over ≥10 samples; methode B zonder sensor — volledige laad/ontlaadcycli integreren, mediaan van ≥3 cycli.
- **Max-vermogen**: observed maximum + plateau-detectie (stabiel ≥30s = hardware-maximum, geen toevalspiek).
- Persisteert via HA Store (`cloudems_battery_soc_learner_v1`) — overleeft herstarts.
- Vervangt de niet-persistente ad-hoc `_battery_learned` dict volledig.

### EnergyBalancer: slimme battery-vs-PV discriminatie (energy_balancer.py)

PV-vermogen verandert langzaam (wolken, zonshoek: typisch <100 W/s). Batterijen springen in één stap van 0 naar ±10 000 W. Als het net snel springt (>500 W/s) maar de battery-sensor nog niet reageert (cloud-lag), infereert de balancer nu de batterijwaarde direct uit de grid-sprong minus geschatte PV-bijdrage. Dit voorkomt het vals-hoog huisverbruik dat voorheen tot `balancer_anomaly: high_imbalance` leidde.

### Bugfix: soc_pct: null in log terwijl Zonneplan SOC wel bekend is

`_last_soc_pct` werd alleen bijgewerkt als `battery_soc_entity` een waarde gaf. De provider-fallback (Zonneplan, en straks alle andere providers) werkte de log-context niet bij. Gecorrigeerd: `_last_soc_pct` wordt nu ook bijgewerkt bij provider-SOC.

### Ontkoppeling Zonneplan (coordinator.py)

Drie plaatsen waar Zonneplan hardcoded was als enige cloud-batterijprovider zijn vervangen door generieke `BatteryProviderRegistry.available_providers` iteratie:
- SOC-fallback voor `batt_soc` (flex-score, BDE-context)
- SOC-fallback voor batterijdegradatie-tracking
- SOC + power-fallback in de battery-config loop

Zonneplan blijft volledig werken via de bestaande `ZonneplanProvider` in de registry. Toekomstige providers (Tibber Volt, Eneco, etc.) werken automatisch mee zonder coordinator-aanpassingen.



### Bugfixes op basis van log-analyse

- **house_w = 0W bij teruglevering** (`energy_balancer.py`): solar sensor rapporteert 0W terwijl grid sterk negatief is (teruglevering). EnergyBalancer infereert nu solar via Kirchhoff (`house_trend - grid + battery`) als `grid < -500W` en `solar = 0`. Voorkomt dat CloudEMS denkt dat het huis 0W verbruikt terwijl er volop wordt teruggeleverd.

- **Ariston boiler niet aangestuurd** (`boiler_controller.py`): `control_mode = "preset"` werkte alleen voor `climate.*` entiteiten, niet voor `water_heater.*`. Ariston Lydos en vergelijkbare boilers met een `water_heater`-entity worden nu aangestuurd via `water_heater.set_operation_mode` (met fallback naar `set_preset_mode`). `_is_on` leest nu ook `operation_mode` attribuut voor water_heater preset-detectie.

- **Boiler `is_on: null` in log** (`coordinator.py`): `getattr(bd, "is_on", None)` was verkeerd — `BoilerDecision` heeft het veld `current_state`, niet `is_on`. Gecorrigeerd naar `bd.current_state`.

- **Shutter log altijd leeg** (`coordinator.py`): `last_reason` wordt alleen opgeslagen bij een daadwerkelijke actie, nooit bij `idle`. Log gebruikt nu de verse `ShutterDecision` uit `async_evaluate()` zodat de echte reden (bijv. "nacht — al gesloten", "automaat uitgeschakeld") altijd zichtbaar is.

- **NILM battery_overlap te agressief** (`nilm/detector.py`): apparaten van <150W werden onterecht verwijderd door batterij-overlap check. Minimum drempel van 150W toegevoegd — kleine apparaten worden nooit door batterij-overlap weggegooid.



### Automatische dashboard-update na HACS-installatie

**Probleem:** Na een HACS-update werden de .storage bestanden wel bijgewerkt maar had HA de oude
dashboard-versie nog in memory. Gebruikers moesten handmatig YAML kopiëren of HA herstarten.

**Oplossing:** `_async_reload_cloudems_dashboards()` — na elke setup roept CloudEMS
`async_load(force=True)` aan op de live Lovelace dashboard-objecten. HA laadt de nieuwe
views direct in memory en stuurt een `lovelace_updated` event naar open browsers.
Resultaat: na HACS-update en HA-reload van de integratie ziet de gebruiker meteen het
bijgewerkte dashboard zonder herstart en zonder handmatig YAML kopiëren.

## [4.5.55] — 2026-03-11

### cloudems-nilm-card v2.2.0 — Volledig herbouwd

4 tabbladen: Kamers / Topologie / Review / Alle. Topologie met approve/decline per node + suggesties. Review met zekerheidsbar en 3-knops interface. Live pulse-dots per apparaat.

## [4.5.54] — 2026-03-11

### Bugfix
- DEV dashboard: dubbele YAML root-key (`title`/`views`) verwijderd — veroorzaakte YAMLException op regel 9
- Versienummer gecorrigeerd (was abusievelijk teruggevallen naar 4.5.52)

Alle noemenswaardige wijzigingen per versie.

## [4.5.53] — 2026-03-11

### DEV Dashboard volledig herbouwd

- **Aanpak gewijzigd:** DEV dashboard is nu een exacte kopie van productie
  met alle `card_mod` styling-blokken verwijderd (~5500 regels geschrapt)
- Alle 20 views behouden: Overzicht, Prijzen & Kosten, Huis Intelligentie,
  Fasen, Solar & PV, Batterij, NILM Apparaten, NILM Beheer, Warm Water,
  Klimaat, EV & Mobiliteit, E-bike, Zwembad, Rolluiken, Lampen, ERE,
  Zelflerend, Meldingen, Diagnose, Configuratie
- DEV oranje banner toegevoegd aan élke view (sticky)
- Nieuwe JS custom cards op de juiste views ingevoegd:
  - Overzicht: `cloudems-overview-card` + `cloudems-flow-card`
  - Prijzen: `cloudems-price-card` + `cloudems-cost-card` + `cloudems-schedule-card`
  - NILM Apparaten: `cloudems-nilm-card`
  - NILM Beheer: `cloudems-topology-card`
- Alle originele productie-kaarten (markdown, entities, conditional, etc.)
  blijven volledig intact en werken dus zeker
- Background images vervangen door CSS gradients (geen `/local/` afhankelijkheid)

## [4.5.52] — 2026-03-11

### Nieuw — Meter Topologie volledig geïntegreerd (backend)

- **`coordinator.py`** — `MeterTopologyLearner` correct opgezet:
  - Persistentie via eigen `Store` (`cloudems_meter_topology_v1`)
  - Laden bij opstarten, opslaan elke ~5 minuten automatisch
  - `observe()` aangeroepen elke cyclus voor grid, extra meters en room meters
- **`sensor.cloudems_meter_topology`** — nieuwe sensor met attributen:
  `tree` (geneste boom), `stats` (approved/tentative/learning), `suggestions`
- **3 nieuwe HA services**:
  `meter_topology_approve`, `meter_topology_decline`, `meter_topology_set_root`
  Elke service slaat direct op via de store

### Nieuw — JS Kaarten v2.1.0 (`cloudems-cards.js`)

- **`cloudems-cost-card`** — Energie kosten kaart:
  - Tabs: Dag / Maand / Simulator
  - Verbruik donut-diagram met categorieën en bar-charts
  - Bill simulator tab met besparing vs. vast tarief + pulserende animatie
  - Verwachting en kostentrend

- **`cloudems-schedule-card`** — Schema beheer kaart:
  - 24-uurs tijdlijn met kleurgecodeerde EPEX-prijsblokken
  - Batterijplanning (laden/ontladen) direct zichtbaar per uur
  - Goedkope-uren schakelaars met actieve status
  - Tooltips per uur met exacte prijs

### Nieuw — DEV Dashboard uitgebreid (9 views)

- **View 7: 💶 Kosten** — cost-card + grafiek 7 dagen + 4 chips
- **View 8: 📅 Schema** — schedule-card + flex grafiek 24u
- **View 9: 🤖 Systeem** — health chips, NILM, topologie, runtime warnings



## [4.5.51] — 2026-03-11

### Nieuw — DEV Dashboard (DTAP-workflow)

- **`cloudems-dashboard-dev.yaml`** — Apart ontwikkel-dashboard (`⚗️ CloudEMS DEV`)
  in Home Assistant naast het bestaande productiescherm. Bevat 6 nieuwe views:
  *Live, Prijzen, NILM, Topologie, Flow, Scratchpad*.
  Workflow: bouw en test in DEV → goedkeuren → overzetten naar productie.

### Nieuw — JS Kaarten v2.0.0 (`cloudems-cards.js`)

- **`cloudems-price-card`** — EPEX uurprijzen heatmap met:
  - SVG sparkline met animated huidige-uurindicator
  - Kleurgecodeerde uurblokken (groen=goedkoop → rood=duur)
  - Morgen samenvatting met goedkoopste uur
  - Badges met min/max/gem

- **`cloudems-topology-card`** — Meter-boom weergave met:
  - Inklapbare boom (root → meter → meter → device)
  - Inline ✓/✗ knoppen voor approve/decline van relaties
  - Suggesties uit het leer-algoritme
  - Status-dots met glow per relatie-status

- **`cloudems-overview-card`** — Compacte live hero-kaart:
  - Grid/Solar/Huis/Batterij in één rij
  - Pulserende glow-animatie op actieve nodes
  - Huidige prijs + flex score in statusregel

### Nieuw — Meter Topologie leermodule (`meter_topology.py`)

- Nieuwe module leert welke meetpunten "upstream" van andere hangen
  via correlatie van vermogensfluctuaties (co-bewegingen)
- Ondersteunt volledige boom: `root → meter → meter → device`
- Status per relatie: `tentative` → `approved` / `declined`
- `MeterTopologyLearner.get_tree()` geeft boom terug voor dashboard
- Persisteerbaar via `dump()` / `load()`

Alle noemenswaardige wijzigingen per versie.

## [4.5.51] — 2026-03-11

### Nieuw — Meter topologie (meter_topology.py)

- **Nieuw module `meter_topology.py`**: Leert automatisch welke meetpunten achter
  andere meetpunten hangen via correlatie van co-bewegingen in vermogensdata.
  Ondersteunt volledige boom: `root_meter → meter → meter → device`.
- **3 nieuwe HA services**:
  - `cloudems.meter_topology_approve` — bevestig upstream→downstream relatie
  - `cloudems.meter_topology_decline` — wijs relatie af (nooit opnieuw suggereren)
  - `cloudems.meter_topology_set_root` — markeer entity als root/P1-meter
- Relaties hebben status `tentative` (geleerd), `approved` (gebruiker OK) of
  `declined` (gebruiker afgewezen). Auto-suggest na ≥8 co-bewegingen.

### Verbeterd — NILM kaart compleet herschreven (cloudems-cards.js v1.9.0)

- **Kamer-navigatie**: klik op een kamer-tegel → kamer-detail view met alle
  apparaten van die kamer, inclusief fase-topologie als er ≥2 apparaten zijn.
- **Pending-status "Jij beslist"**: apparaten die wachten op gebruikersinput
  krijgen een oranje badge en worden bovenaan gesorteerd. Pulserende oranje pill
  in de header laat direct zien hoeveel apparaten wachten.
- **Naam bewerken inline**: klik op de naam van een apparaat → modal met
  nieuw naamlabel + type-selectie.
- **Filter-tabs per kamer**: filter op Alle / Wacht / Bevestigd / Onzeker.
- **Topologie-weergave per kamer**: bij meerdere apparaten wordt de
  fase-structuur als boom getoond (ook als indicator voor sub-circuits).
- Approve ✓ / Tentative ? / Decline ✗ knoppen consistent en duidelijker.

### Verbeterd — Auto-confirm drempel verhoogd (nilm/power_learner.py)

- `AUTO_CONFIRM_MIN_CONFIDENCE`: 0.92 → **0.96** (alleen bij heel hoge zekerheid)
- `AUTO_CONFIRM_MIN_DETECTIONS`: 8 → **12** (meer herhalingen vereist)
- Alles tussen 0.75 en 0.96 confidence blijft `pending_confirmation=True` —
  de gebruiker beslist zelf via Approve/Tentative/Decline in de NILM-kaart.

### Opgelost — room en device_id ontbraken in sensor attributes (sensor.py)

- `sensor.cloudems_nilm_devices` attributen bevatten nu ook:
  - `device_id` — vereist voor service-calls vanuit de JS-kaart
  - `room` — geladen vanuit de room_meter engine op het moment van polling
  - `pending` — of het apparaat wacht op gebruikersbevestiging



### Opgelost — NILM devices verdwijnen na herstart

- **Infra-cleanup te agressief** (`nilm/detector.py`):
  De v4.5.11 cleanup bij het laden verwijderde ten onrechte NILM-apparaten waarvan
  het `device_type` op `"battery"`, `"pv"`, `"inverter"` of `"opslag"` stond. Een
  acculader of smart plug bij een zonnepaneel kon zo na elke herstart verdwijnen.
  Oplossing: deze te brede types uit `_INFRA_TYPES_CLEANUP` verwijderd; alleen
  expliciete infra-typen (`solar_inverter`, `pv_inverter`, `home_battery`, etc.) blijven.
- **Confirmed devices beschermd** (`nilm/detector.py`):
  Apparaten die de gebruiker heeft bevestigd (`confirmed=True`) worden nooit meer
  door de infra-cleanup verwijderd, ongeacht type of naam.

### Opgelost — Flow kaart: 1 zon bij 2 inverters + maan bij nacht

- **Inverter filter te strikt** (`cloudems-cards.js`):
  `_getInverters()` filterde inverters met `'peak_w' in i` — als een omvormer
  nog aan het leren is en `peak_w=null` heeft, viel die weg waardoor er maar
  1 zon zichtbaar was. Fix: filter alleen op `i != null`, `peak_w=0` is toegestaan.
- **Maan-icoon bij nacht** (`cloudems-cards.js`):
  Tussen 22:00–05:59 wordt er nu 1 halvemaan-node getoond in plaats van een
  inactieve zon. De maan is blauw/zilveren half-circle SVG met zachte glow.
  `solarNode()` detecteert zelf het uur en toont automatisch zon of maan.
- **Nacht = altijd 1 node** (`cloudems-cards.js`):
  Bij nacht wordt de layout teruggebracht naar 1 centrale maan (ongeacht aantal
  geconfigureerde inverters) zodat de flow-kaart overzichtelijk blijft.



### Opgelost — NILM: 3-fase thuisbatterij veroorzaakt geen duplicaten meer

- **battery_overlap lus-bug** (`detector.py`):
  Apparaten met ≥2 on-events worden niet meer verwijderd door de battery_overlap check.
  Voorheen werd een echte warmtepomp (3300W op L2) elke 10 seconden verwijderd en
  opnieuw aangemaakt omdat de batterij toevallig tegelijk van vermogen wisselde.
  Overlap-ratio versmald van 30–170% naar 60–140% voor striktere matching.

- **3-fase batterij edge-suppressie** (`detector.py`):
  Bij grote batterij-transities (>2kW) worden NILM-edges die overeenkomen met
  1/3 of 2/3 van het batterijvermogen nu ook geblokkeerd. Dit vangt de per-fase
  distributie van een 3-fase thuisbatterij op (bijv. 7.4kW laden → ~2.5kW per fase).

## [4.5.14] — 2026-03-11

### Opgelost — NILM: 3-fase apparaten + warmtepomp duplicaten

**3-fase herkenning (database.py, detector.py):**
- Nieuw `three_phase=True` vlag op `ApplianceSignature` — apparaten die hun vermogen
  over 3 fasen verdelen worden nu gematcht op het **totaalvermogen** (huis_w),
  niet op de per-fase delta (die bij `total_split` slechts 1/3 van het werkelijke
  vermogen is). Hierdoor werden een 7kW warmtepomp en 7kW batterijlading
  ten onrechte als "Elektrische boiler 3kW" op L2 gelabeld.
- Nieuwe 3-fase profielen toegevoegd:
  - `heat_pump`: Lucht-WP 3-fase 6/9/12kW, Bodem-WP 3-fase 8/12kW
  - `ev_charger`: EV 3-fase 11kW en 22kW voorzien van `three_phase=True`
  - `home_battery`: Thuisbatterij laden 3/5/6/7/10kW (worden direct gefilterd
    uit apparatenlijst — alleen voor correcte labeling intern)
- `set_infra_powers()` leidt nu het totale huisvermogen af uit grid+solar+battery
  en slaat dit op als `_last_house_power_w` voor gebruik bij classify().
- `classify()` krijgt `total_power_w` parameter mee.

**Warmtepomp duplicaten (detector.py):**
- `_handle_match()`: bij een on-event wordt nu ook gezocht naar een bestaand
  apparaat van hetzelfde type dat al `is_on=True` staat met vergelijkbaar
  vermogen (±40%), ongeacht de fase. Bij `total_split` schommelt het per-fase
  signaal waardoor steeds opnieuw een positieve delta zichtbaar was en een
  nieuw apparaat werd aangemaakt (7 IDs in 3 minuten voor dezelfde warmtepomp).

## [4.5.13] — 2026-03-11

### Opgelost — NILM: omvormers en netmeters niet meer als verbruiker

- **Smart plug bypass verwijderd** (`detector.py`, `hybrid_nilm.py`, `smart_sensor_discovery.py`):
  apparaten met `source="smart_plug"` werden volledig vrijgesteld van de infra-naam-filter.
  Hierdoor verschenen PV-omvormers ("Growatt Oost Output Power"), netmeters
  ("Electricity Meter Energieverbruik") en geschatte productiesensoren
  ("Thuis - West- PV1 Geschatte energieproductie") ten onrechte als verbruiker in NILM.

  Drie lagen gefixed:
  1. `get_anchored_devices()` in `hybrid_nilm.py` filtert nu infra-ankernamen vóór output.
  2. `_is_infra_name()` in `detector.py` controleert smart_plug apparaten op de meest
     ondubbelzinnige infra-termen (energieproductie, output power, electricity, growatt, etc.).
  3. `_EXCLUDE_SUBSTRINGS` in `smart_sensor_discovery.py` uitgebreid met PV-productietermen
     zodat ze ook bij ontdekking al worden tegengehouden.
  4. `_INFRA_SUBS` in `hybrid_nilm.py` uitgebreid met dezelfde termen voor purge van
     reeds geregistreerde infra-ankers.

## [4.5.12] — 2026-03-11

### Gewijzigd — NILM: bij twijfel niet detecteren, meer zelflerend

- **Hogere confidence-drempels** (`const.py`): `NILM_MIN_CONFIDENCE` verhoogd van 0.55 → 0.75,
  `NILM_HIGH_CONFIDENCE` van 0.80 → 0.92. Bij twijfel wordt een event nooit als nieuw apparaat
  opgeslagen — de unsupervised clusterer verzamelt het event en vraagt de gebruiker om
  bevestiging zodra er genoeg bewijs is.

- **Database minimale match-drempel omhoog** (`database.py`): `confidence >= 0.45` verhoogd
  naar `>= 0.60`. Zachte-zone partial matches die nét boven 0.45 uitkomen zijn te onzeker
  om aan de detector terug te geven.

- **Type `unknown` krijgt niche-cap** (`database.py`): loopband, stofzuiger, strijkijzer
  en andere vage `unknown`-types worden nooit automatisch gedetecteerd (cap 0.55 < 0.75).
  Ze landen in de clusterer en verschijnen pas na gebruikersbevestiging.

- **Alle nieuwe apparaten starten als `pending`** (`detector.py`): was alleen `pending`
  bij confidence < `NILM_HIGH_CONFIDENCE`, nu altijd. Een apparaat is pas zichtbaar
  op het dashboard als het voldoende herhaalde detecties heeft én de steady-state
  validatie doorstaat.

- **Striktere steady-state validatie** (`detector.py`): delay terug naar 35 s (was 20 s),
  minimale stijging van 40 % → 55 % van verwacht vermogen.

- **Meer herhalingen vereist voor zichtbaarheid** (`detector.py`): `MIN_ON_EVENTS_DEFAULT`
  verhoogd van 2 → 3, type `unknown` vereist 5 events (nieuw), `kitchen` 5, `garden` 6,
  `power_tool` 8.

- **Clusterer strenger** (`unsupervised_cluster.py`): suggestie pas na 8 events (was 5),
  cluster-eps strikter (W: 150 → 120, duur: 180 s → 150 s).

- **Auto-confirm vereist meer bewijs** (`power_learner.py`): minimale detecties 5 → 8,
  confidence-drempel 0.90 → 0.92.

### Opgelost

- **Boiler: `is_on=null` bij unavailable entiteit** (`boiler_controller.py`): wanneer
  `water_heater.boiler` (of andere boiler-entiteit) de status `unavailable` of `unknown`
  heeft, wordt sturing nu overgeslagen met een duidelijke `WARNING` in de logs.
  Voorheen veroorzaakte dit stille beslissingen met `is_on=None` die misleidend waren.

- **Rolluiken: ontbrekende sensoren geven nu duidelijke waarschuwing** (`shutter_controller.py`):
  als `solar_elevation_deg` of `outdoor_temp_c` niet beschikbaar is (geen `sun.sun` of
  buitentemperatuursensor gekoppeld), wordt een `WARNING` gelogd met instructie hoe te
  koppelen. Eerder was dit alleen zichtbaar als `null` in beslissings-payloads.

- **Batterij: SoC=None geeft nu duidelijke waarschuwing** (`battery_decision_engine.py`):
  als geen SoC-sensor gekoppeld is aan de batterijconfiguratie, wordt een `WARNING`
  gelogd. Batterijsturing werkt dan zonder laadtoestand, wat suboptimaal is.



### Opgelost

- **Batterij providers tabel: vertraging niet zichtbaar** (`www/cloudems-dashboard.yaml`):
  de geleerde grid→batterij vertraging (`battery_lag_s`) en het update-interval waren
  beschikbaar in de sensordata maar ontbraken in de markdowntabel. Twee nieuwe kolommen
  toegevoegd: **Interval** (updatefrequentie, oranje bij stale) en **Vertraging**
  (geleerde lag in seconden met confidence-%, of leervoortgang als nog lerend).

## [4.5.11] — 2026-03-11

### Opgelost

- **Batterijsensor altijd "stale" bij constante waarde** (`energy_balancer.py`): de
  `_SensorTracker` markeerde een sensor als stale zodra de *waarde* gedurende >25 s niet
  veranderde — ook al kwamen er gewoon elke 10 s updates binnen. Dit trad op wanneer de
  batterij op een vast vermogen bleef (bijv. -590 W nacht-limiet). De balancer schatte de
  batterij dan via Kirchhoff op ~+1100 W (onjuist teken!), wat leidde tot aanhoudende
  `balancer_anomaly`-meldingen en een fout berekend huisverbruik. Opgelost door
  `last_update_ts` (elke `update()`-aanroep) te scheiden van `last_change_ts` (alleen bij
  waarde-wijziging); `is_stale()` gebruikt nu `last_update_ts`.

- **Prijs-waarschuwing bij ontbrekende belasting/BTW-configuratie** (`coordinator.py`):
  wanneer EPEX spotprijs actief is maar energiebelasting én BTW allebei **niet** zijn
  aangevinkt in de wizard, wordt nu een `price_anomaly`-entry in het high-log geschreven
  met de reden en de geschatte werkelijke prijs. Zo is direct zichtbaar wanneer CloudEMS
  met enkel de EPEX-spotprijs rekent (€0.07/kWh) in plaats van de all-in prijs (~€0.24/kWh).

- **Sensor-hints dubbel gelogd bij opstarten** (`coordinator.py`): wanneer de coordinator
  snel na elkaar twee cycli uitvoerde bij het opstarten, werden actieve hints (bijv.
  "spanningssensor ontbreekt") tot 4× gelogd. Opgelost door per hint_id bij te houden
  wanneer hij voor het laatst gelogd werd; herlogs binnen 1 uur worden overgeslagen.

## [4.5.11] — 2026-03-11

### Opgelost

- **`balancer_anomaly` spam elke 10s in high.log** (`coordinator.py`): Bij gebruik van de
  legacy `battery_sensor` (enkelvoudig, zonder `battery_configs`) werd de reconcile-pre-read
  overgeslagen. De `EnergyBalancer` ontving `battery_w=None` op de eerste cyclus, markeerde
  de batterij-tracker als stale, en berekende via Kirchhoff een positieve batterijwaarde
  (~+1100W) die een imbalans van >1500W veroorzaakte. Fix: de pre-read leest nu ook
  `CONF_BATTERY_SENSOR` als `battery_configs` leeg is.
- **Boiler reden "0.0°C onder setpoint" bij ontbrekende temperatuursensor**
  (`boiler_controller.py`): Wanneer `current_temp_c is None` (sensor ontbreekt of entity
  bestaat niet) gaf `temp_deficit_c` altijd `0.0` terug, wat de misleidende beslissingsreden
  `"seq [...]: 0.0°C onder setpoint"` opleverde. Fix: duidelijke reden
  `"seq [...]: geen temperatuursensor — trigger actief"`.

## [4.5.11] — 2026-03-11

### Opgelost

- **Versie in elke logregel** (`learning_backup.py`): elke regel in `cloudems_normal.log`,
  `cloudems_high.log` en `cloudems_decisions.log` bevat nu `"_v": "4.5.11"` zodat bij
  troubleshooting direct duidelijk is welke versie de log produceerde.
- **Startup-samenvatting met versie + actieve modules** (`coordinator.py`): bij elke start
  verschijnt nu in de HA-log én in `cloudems_high.log` een regel als:
  `CloudEMS v4.5.11 gestart — actieve modules: NILM, Boiler, GasAnalysis, PhaseBalancer`
- **Uitgeschakelde modules niet meer als INFO loggen** (`coordinator.py`): NILM motor, 
  HybridNILM, Bayesian, HMM toestand "UIT" gaat nu naar DEBUG in plaats van INFO,
  zodat de logboeken niet vol staan met meldingen over modules die niet actief zijn.

## [4.5.10] — 2026-03-11

### Opgelost

- **`dashboards_collection` waarschuwing bij opstarten** (`__init__.py`): niet-kritieke melding
  dat het Lovelace-dashboard niet automatisch aangemaakt kon worden, gepromoveerd van WARNING
  naar DEBUG. Verschijnt alleen bij expliciete debug-logging.
- **PhaseBalancer imbalance als WARNING** (`phase_balancer.py`): fase-onbalans is normaal
  gedrag dat de balancer zelf afhandelt — niveau verlaagd van WARNING naar INFO.
- **Ontbrekende NILM-vertalingen niet zichtbaar** (`nilm/translations.py`): wanneer een
  apparaatnaam geen vertaling heeft in de gevraagde taal, wordt nu éénmalig een WARNING
  gelogd met de ontbrekende sleutel zodat die snel aangevuld kan worden.

## [4.5.9] — 2026-03-11

### Opgelost

- **Backup logging niet zichtbaar** (`learning_backup.py`): schrijffouten voor logbestanden
  werden stil genegeerd op DEBUG-niveau. Nu gepromoveerd naar WARNING + er wordt direct een
  schrijftest uitgevoerd bij opstarten zodat permissieproblemen meteen als ERROR verschijnen.
- **Gas verbruik altijd `—` na herstart** (`gas_analysis.py`): de periode-startwaarden
  (vandaag / week / maand / jaar) werden nooit opgeslagen in de HA-store. Na elke herstart
  waren ze `None`, waardoor het verbruik altijd 0 was. Alle vier de startpunten worden nu
  persistent bewaard en hersteld.
- **NILM rommel blijft staan na auto-confirm** (`nilm/detector.py`): apparaten met
  `confirmed=True` werden door de infra-filter uit de output gehouden, maar bleven in
  `self._devices` staan en doken elke cycle opnieuw op. Nu worden bevestigde infra-apparaten
  definitief uit het interne model verwijderd. Ook uitgebreide `_INFRA_CLEANUP_KW` bij laden
  met merk-namen (growatt, output power, etc.).
- **Vertaling validatiefouten** (`translations/nl.json`, `translations/en.json`, `strings.json`):
  ontbrekende stappen `price_provider`, `price_provider_credentials` en `price_provider_creds_opts`
  toegevoegd; placeholder-mismatches tussen vertalingen en `strings.json` opgelost.

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

