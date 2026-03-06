# Bijdragen aan CloudEMS

Bedankt voor je interesse in het bijdragen aan CloudEMS! 🎉

## Hoe bijdragen?

### Bug melden
1. Controleer eerst of het issue al bestaat in [GitHub Issues](https://github.com/cloudemsNL/ha-cloudems/issues)
2. Maak een nieuw issue aan met:
   - HA versie
   - CloudEMS versie
   - Beschrijving van het probleem + logregels

### Feature request
Open een issue met het label `enhancement` en beschrijf het gewenste gedrag.

### Code bijdragen

```bash
# Fork de repository via GitHub
git clone https://github.com/JOUWGEBRUIKERSNAAM/ha-cloudems
cd ha-cloudems

# Maak een feature branch
git checkout -b feature/mijn-verbetering

# Kopieer naar je HA custom_components map voor testen
cp -r custom_components/cloudems ~/.homeassistant/custom_components/

# Commit en push
git commit -m "feat: beschrijving van wijziging"
git push origin feature/mijn-verbetering

# Open een Pull Request op GitHub
```

### Code stijl
- Python 3.11+, type hints waar mogelijk
- Docstrings in het Nederlands of Engels
- Logging via `_LOGGER = logging.getLogger(__name__)`
- Async waar HA dit vereist

### Tests
Voeg tests toe in de `tests/` map als je nieuwe functionaliteit introduceert.

## Licentie

Door bij te dragen ga je akkoord dat je bijdrage wordt gelicenseerd onder de [MIT licentie](LICENSE).
