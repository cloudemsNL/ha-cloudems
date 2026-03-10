# CloudEMS DIY NILM Energie-meter — ESPHome v3.0 (3-fase)

## Waarom een eigen meter?

| Meter           | Samplerate  | Golflijn | Fasen | Kosten |
|-----------------|-------------|----------|-------|--------|
| DSMR P1         | 1 Hz        | ❌       | 3     | gratis |
| Slimme meter    | 0,017 Hz    | ❌       | 3     | gratis |
| Shelly 3EM      | 50 Hz       | ❌ RMS   | 3     | €60    |
| **Eigen ESP32** | **~10 kHz** | **✅**   | **3** | **~€35** |
| Sense           | 1 MHz       | ✅ volledig | 2 (US) | ~€300 |

Extra signalen t.o.v. P1 (per fase):
- **Power factor** → resistief/inductief/capacitief onderscheid voor NILM
- **Rise time** → nauwkeurigere delta-timing (<5ms vs ~20s bij P1)
- **Inrush piek** → motor/condensator herkenning bij apparaat-opstarten

---

## Hardware (3-fase, ~€35)

| Component | Doel | Prijs |
|-----------|------|-------|
| ESP32-S3 DevKit | Hoofdprocessor, dual-core 240MHz | €5 |
| SCT-013-000 (3×) | Split-core CT 100A/50mA, één per fase | €6 |
| ZMPT101B (1×) | Spanningssensor L1 (referentie) | €2 |
| 22Ω burden (3×) | SCT-013 belasting (indien geen ingebouwde) | €0,30 |
| 10kΩ + 100nF (6×) | Bias en decoupling per ADC-kanaal | €0,50 |
| DIN-rail behuizing | Veilige montage in meterkast | €8 |
| Mean Well HDR-15-5 | Geïsoleerde 5V voeding | €12 |

**Totaal: ~€35**

> **Optioneel nauwkeuriger:** voeg 2 extra ZMPT101B modules toe (GPIO5/L2, GPIO6/L3)
> voor correcte faseverschuiving bij vermogensfactor-meting per fase.
> Voor NILM is één spanningsreferentie voldoende.

---

## Pinout ESP32-S3

```
GPIO1  ──► SCT-013 L1  (22Ω burden + 1.65V bias)
GPIO2  ──► SCT-013 L2  (22Ω burden + 1.65V bias)
GPIO4  ──► SCT-013 L3  (22Ω burden + 1.65V bias)
GPIO3  ──► ZMPT101B    (230V→3.3V, L1 spanningsreferentie)
GPIO48 ──► Status LED  (ingebouwd)
```

> **Let op ADC1:** Gebruik uitsluitend GPIO1–GPIO10 (ADC1).
> ADC2 (GPIO11–GPIO20) is incompatibel met WiFi op ESP32.

### Schematisch bias-circuit (per CT-kanaal)

```
SCT-013 output ──┬── 22Ω burden ──┬── ADC pin
                 │                │
                3.3V              ┤ 100nF naar GND
                10kΩ             10kΩ
                GND               │
                                 GND
Middenpunt: 1.65V (BIAS = 2048 in 12-bit ADC)
```

---

## Gesensorde HA-entiteiten

Na installatie verschijnen in HA (auto-detecteerbaar door CloudEMS wizard):

| Entiteit | Eenheid | Beschrijving |
|----------|---------|-------------|
| `sensor.cloudems_vermogen_l1` | W | Werkzaam vermogen fase L1 |
| `sensor.cloudems_vermogen_l2` | W | Werkzaam vermogen fase L2 |
| `sensor.cloudems_vermogen_l3` | W | Werkzaam vermogen fase L3 |
| `sensor.cloudems_totaal_vermogen` | W | L1 + L2 + L3 |
| `sensor.cloudems_power_factor_l1` | — | cos φ L1 (0–1) |
| `sensor.cloudems_power_factor_l2` | — | cos φ L2 |
| `sensor.cloudems_power_factor_l3` | — | cos φ L3 |
| `sensor.cloudems_spanning_l1` | V | RMS spanning |
| `sensor.cloudems_inrush_piek_l1` | A | Stroomspike bij inschakelen L1 |
| `sensor.cloudems_inrush_piek_l2` | A | Stroomspike L2 |
| `sensor.cloudems_inrush_piek_l3` | A | Stroomspike L3 |
| `sensor.cloudems_stijgtijd_ms_l1` | ms | Rise time laatste delta L1 |
| `sensor.cloudems_stijgtijd_ms_l2` | ms | Rise time L2 |
| `sensor.cloudems_stijgtijd_ms_l3` | ms | Rise time L3 |

---

## CloudEMS wizard koppeling

Kies in de wizard **"🔬 DIY ESPHome 1kHz NILM-meter"** als DSMR-bron.
De wizard auto-detecteert alle `esphome` platform-sensoren en sorteert ze
alfabetisch, zodat L1/L2/L3 automatisch op de juiste velden staan.

CloudEMS gebruikt de extra features per fase:

| Feature | NILM-effect |
|---------|-------------|
| power_factor ≈ 1.0 | Resistieve last (waterkoker, gloeilamp) |
| power_factor 0.6–0.8 | Inductieve last (motor, transformator) |
| power_factor 0.5–0.7 | Elektronisch (computer, LED, TV) |
| inrush_ratio > 3 | Condensator/SMPS → snelle spike |
| inrush_ratio < 2 | Motor/resistief → geleidelijke opbouw |

---

## Installatie

1. Kopieer `cloudems_nilm_meter.yaml` naar je ESPHome-map
2. Maak `secrets.yaml` aan:
   ```yaml
   wifi_ssid: "UwNetwerk"
   wifi_password: "UwWachtwoord"
   api_encryption_key: "<32-byte base64 sleutel>"
   ota_password: "UwOTAWachtwoord"
   ```
3. Compileer en flash via ESPHome Dashboard of CLI:
   ```bash
   esphome run cloudems_nilm_meter.yaml
   ```
4. Voeg toe in HA → Instellingen → Apparaten → ESPHome

---

## Veiligheid ⚠️

- Gebruik **uitsluitend split-core CT's** (SCT-013) — nooit de 230V direct meten
- ZMPT101B heeft galvanische isolatie — veilig voor 230V
- Gebruik een **erkend elektricien** voor installatie in de meterkast
- **DIN-rail behuizing met deksel verplicht**
- ESP32 voeding via geïsoleerde schakelende voeding (Mean Well HDR-15-5)
- Sluit de CT's **nooit open-circuit** aan (gevaarlijke spanningsspike)
