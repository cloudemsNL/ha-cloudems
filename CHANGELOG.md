# CloudEMS — Changelog

## v1.15.3 (2026-03-04)

### Dashboard (cloudems-card.js)
- **🏠 Inzichten-tab** (nieuw) — aanwezigheid + zekerheid%, verwarmingsadvies (modus / offset / reden / prijsverhouding), PV-nauwkeurigheid %, thermisch huismodel W/°C
- **🛡️ Diagnose-tab** (nieuw) — alle sanity-meldingen met beschrijving + advies, bevroren sensoren, geblokkeerde EMA-spikes, trage cloud-sensoren met update-interval en α-waarde
- **Contextbalk op Overzicht** — aanwezigheid + verwarmingsadvies + PV-accuracy in één rij boven de tabs
- **Sanity-banner** — rode/oranje balk als er sensor-problemen zijn, met samenvatting
- **Stub-config uitgebreid** — 6 nieuwe sensor-sleutels: `occupancy_sensor`, `preheat_sensor`, `pv_accuracy_sensor`, `ema_diag_sensor`, `sanity_sensor`, `thermal_sensor`

### Vertalingen (nl.json / en.json / de.json)
- Alle 5 nieuwe v1.15.x sensoren vertaald met display-naam + states
- `data_description` toegevoegd voor batterij- (cloud-waarschuwing), net- (W vs kW) en zonnestroom-sensor (W vs kW)

## v1.15.2 (2026-03-04)

### Nieuw — EMA-smoothing voor vertraagde cloud-sensoren
- Nieuwe module `sensor_ema.py` — meet automatisch update-interval per sensor, past α aan. Snelle P1: α=1.0, Zonneplan cloud-batterij (60s): α≈0.25
- Spike-detectie: waarden > 5× lopend gemiddelde worden afgevangen. Diagnostische sensor `CloudEMS · Sensor EMA Diagnostiek`

### Nieuw — Sanity guard voor fout-geconfigureerde sensoren
- Nieuwe module `sensor_sanity.py` met 6 checks (na 3 aaneengesloten hits):
  1. Harde limieten (> 55 kW net, > 50 kW PV, > 30 kW batterij)
  2. kW/W verwarring (kleine gehele getallen terwijl W verwacht)
  3. Spike vs. eigen geschiedenis (> 8× geleerd gemiddelde)
  4. Energiebehoud-check (teruglevering zonder zon/batterij → teken omgedraaid)
  5. Aansluiting-overschrijding (vermogen > geconfigureerde max A × fases)
  6. Fase-limiet (> 80A per fase)
- Alerts via NotificationEngine met prioriteit critical/warning, Nederlandse beschrijving + concreet advies

## v1.15.1 (2026-03-04)

### NILM: batterij + warmtepomp verbeteringen
- **Batterij-compensatie** — batterijvermogen wordt vóór NILM van het netsignaal afgetrokken; laad/ontlaad-transities triggeren geen valse NILM-events meer
- **Batterij-injectie** — batterij verschijnt als `Thuisbatterij (laden/ontladen)` in NILM-lijst met 100% zekerheid
- **Warmtepomp deduplicatie** — alle HP-subtypen op dezelfde fase worden samengevoegd tot één entry met vermogensbereik (bijv. `1.421–1.751 W (gem. 1.6 kW)`)

## v1.15.0 (2026-03-04)

### Nieuw — zelflerend & internet-data

#### Van AI Smart Boiler v2.2 geleerd
- **PVForecastAccuracyTracker** — volledig ingebed: MAPE 14d/30d, bias-factor, kalibratifactor per maand. Dagelijks vergelijkt forecast vs. werkelijkheid
- **Open-Meteo global_tilted_irradiance** — PV-prognose gebruikt geneigde bestraling op basis van geleerd azimut/helling (10–25% nauwkeuriger). Fallback-cascade: tilted → direct → shortwave → cloud_cover
- **Buitentemperatuur via Open-Meteo** — thermisch model werkt nu ook zonder extra sensor

#### Van CloudEMS v7 geleerd
- **AbsenceDetector** — detecteert thuis/weg/slapend/vakantie puur op verbruikspatroon. Twee signalen: afwijking van standby-last + afwijking van wekelijks patroon. Vakantiedetectie na > 8 uur
- **ClimatePreHeatAdvisor** — adviseert pre_heat/reduce/normal op basis van EPEX-prijsverhouding × thermische traagheid. Sensor: `CloudEMS Klimaat · Verwarmingsadvies`

### README & CHANGELOG
- Changelog verplaatst naar aparte `CHANGELOG.md`
- README bevat ASCII-screenshots en geen changelog meer

## v1.14.1 (2026-03-04) — Basis voor deze sessie

Zie vorige versie voor de complete v1.14.x history.

---

### Bronnen & Inspiratie

| Module | Geïnspireerd door |
|---|---|
| `absence_detector.py` | CloudEMS v7 `PresenceDetector` |
| `climate_preheat.py`  | CloudEMS v7 `ClimateOptimizer` |
| `pv_accuracy.py`      | AI Smart Boiler v2.2 `learned_pv_efficiency` |
| `sensor_ema.py`       | Eigen ontwerp voor Zonneplan-delay probleem |
| `sensor_sanity.py`    | Eigen ontwerp naar aanleiding van support-meldingen |

### Roadmap — volgende versies

- [ ] Warmtepomp COP-leren per seizoen (per maand COP bijhouden, ontdooicycli als COP-dips detecteren)
- [ ] NILM herontdekking bij sensorwijziging (hash van sensorconfig, zachte reset bij mismatch)
- [ ] EV-charger ↔ NILM koppeling (EVSessionLearner + NILM EV-entry samenvoegen)
- [ ] Demand response / DSO-signalering (ENTSOE of netbeheerder-API voor proactieve reactie)
- [ ] Meerdere tariefzones per dag (dag/nacht/piek, capaciteitstarief)
- [ ] Automatische eenheidsdetectie bij setup (wizard waarschuwt vóór afsluiten)
