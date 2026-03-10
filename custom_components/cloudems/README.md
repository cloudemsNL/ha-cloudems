# CloudEMS v2.0.0 — Custom Component

Deze map bevat de CloudEMS Home Assistant custom component.

## Structuur

```
custom_components/cloudems/
├── __init__.py              # Integratie entry point + service registratie
├── config_flow.py           # Installatie- en configuratiewizard (UI)
├── coordinator.py           # Centrale data-coördinator (~10s update loop)
├── sensor.py                # Alle sensor-entiteiten
├── binary_sensor.py         # Binary sensors (aanwezigheid, goedkoop uur, etc.)
├── switch.py                # Schakelaar-entiteiten
├── number.py                # Nummer-entiteiten (max stroom, etc.)
├── button.py                # Knop-entiteiten
├── select.py                # Selectie-entiteiten
├── const.py                 # Constanten en configuratiesleutels
├── manifest.json            # HACS/HA integratie manifest
├── services.yaml            # Service definities
├── strings.json             # Vertalingssleutels (basis)
├── translations/            # Vertalingen NL / EN / DE
├── energy/                  # Prijzen, CO2, fase-limiter
├── energy_manager/          # Alle intelligentie-modules
│   ├── absence_detector.py      # Aanwezigheidsdetectie op basis van verbruik
│   ├── lamp_circulation.py      # ★ NIEUW v2.0: Lampcirculatie & beveiliging
│   ├── pool_controller.py       # Zwembad filter + warmtepomp
│   ├── phase_prober.py          # Actieve fase-detectie via puls
│   ├── boiler_controller.py     # Slimme boiler-sturing
│   ├── battery_scheduler.py     # EPEX batterij-schema
│   ├── peak_shaving.py          # Piekafschaving
│   └── ...                      # 40+ andere modules
└── nilm/                    # NILM apparaatdetectie engine
    ├── hybrid_nilm.py           # Hybride lokaal+cloud NILM
    ├── analyzer.py              # Signaalanalyse
    └── ...
```

## Nieuw in v2.0.0

### `energy_manager/lamp_circulation.py`

Intelligente lampenbeveiliging met:
- Dynamische circulatie (willekeurige tijden + wisselend aantal lampen)
- Gedragsmimicry (geleerd bewonersgedrag nabootsen)
- Seizoensintelligentie via `sun.sun`
- PIR-bypass, buurt-correlatie, negatieve prijs-koppeling
- Passieve fase-detectie bij schakelacties

Zie [CHANGELOG.md](../../CHANGELOG.md) voor alle wijzigingen.
