# ⚡ CloudEMS Platform

Monorepo voor het CloudEMS energieplatform. Twee projecten, één repository, één gedeeld API contract.

```
cloudems-platform/
├── cloudems/          HA integratie — lokale energie-intelligentie
├── adaptivehome/      Cloud SaaS — leren, rapporteren, beheren op afstand
├── shared/            API contract — de koppellaag tussen beide
└── docs/              Gedeelde tools (calculators, documentatie)
```

## Hoe de twee projecten met elkaar praten

```
Thuisinstallatie (HA)              Cloud (Proxmox/VPS)
─────────────────────              ──────────────────
CloudEMS integratie                AdaptiveHome API
  │                                  │
  │  sensor.cloudems_*    ──lezen──► CloudEMSBridge
  │  binary_sensor.*                 │ (leest alleen, beslist niet)
  │                                  │
  │  cloudems.* services  ◄─push──── PatternEngine
  │  (manual override)               (pusht geleerde patronen)
```

**Architectuurregel:** AdaptiveHome leest CloudEMS data maar implementeert geen CloudEMS-functionaliteit opnieuw. Beslissingen over batterij, boiler, EV blijven altijd bij CloudEMS.

## shared/cloudems_contract.py

Dit is de **enige bron van waarheid** voor entity IDs en service namen. Beide projecten importeren hieruit.

```python
# In AdaptiveHome:
from shared.cloudems_contract import SENSORS, BINARY_SENSORS, SERVICES

# In CloudEMS (via const.py alias):
from .cloudems_contract import SENSORS as CLOUDEMS_SENSOR_IDS
```

**Bij het hernoemen van een CloudEMS sensor:**
1. Pas `shared/cloudems_contract.py` aan
2. Bump `CONTRACT_VERSION`
3. Beide projecten zijn automatisch gesynchroniseerd

## Versies

| Project | Versie |
|---|---|
| CloudEMS | 4.6.671 |
| AdaptiveHome | 0.1.0 |
| Shared contract | 1.1.0 |

## Releaseproces

**Platform zip** (altijd — beide projecten samen):
```bash
python3 shared/bump_version.py 5.0.2
zip -r cloudems-platform-5.0.2.zip \
  cloudems/ adaptivehome/ shared/ docs/ \
  README.md CLAUDE_INSTRUCTIONS.md \
  -x "*.pyc" -x "*/__pycache__/*" \
  -x "adaptivehome/.env.*"
```

Voor HACS installatie: extraheer de `cloudems/` map uit de platform zip.

**AdaptiveHome** (cloud deploy):
```bash
cd adaptivehome/
./deploy.sh production
```

**Gedeeld contract** — geen aparte release. Beide projecten pakken de laatste versie uit `shared/`.

## Lokale ontwikkeling

```bash
# CloudEMS tests
cd cloudems && python -m pytest tests/

# AdaptiveHome tests
cd adaptivehome && python -m pytest tests/

# Contract validatie
python shared/validate_contract.py
```
