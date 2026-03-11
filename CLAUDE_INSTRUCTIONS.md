# Instructies voor Claude

## ALTIJD DOEN bij het maken van een nieuwe zip:
1. Start met de **originele geüploade zip** als basis — unzip volledig
2. Kopieer alleen de **gewijzigde bestanden** over de uitgepakte map
3. Zip de **volledige map** opnieuw in — nooit een submap zoals `custom_components/`
4. Controleer met `diff` of alle originele bestanden nog aanwezig zijn

## NOOIT DOEN:
- Nooit een zip maken vanuit alleen `custom_components/` — dan ontbreken docs, esphome, tests, hacs.json, CHANGELOG, LICENSE, README
- Nooit aannemen dat een submap de volledige zip is

## Versie bumpen — ALTIJD, ook bij kleine fixes:
- `manifest.json` → `"version": "x.x.xx"` verhogen met 1
- Elke zip die gedeeld wordt krijgt een nieuwe versie, geen uitzonderingen
