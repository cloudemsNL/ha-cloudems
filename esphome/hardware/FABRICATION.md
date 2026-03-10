# CloudEMS NILM Meter — PCB Fabricatie Instructies

## JLCPCB bestelling (goedkoopste optie, ~€5 voor 5 stuks)

### Gerber export (vanuit KiCad)
1. Open `cloudems_nilm.kicad_pcb` in KiCad PCB Editor
2. **File → Plot → Gerber**
3. Selecteer lagen:
   - `F.Cu` (voorkant koper)
   - `B.Cu` (achterkant koper)
   - `F.SilkS` (voorkant opdruk)
   - `B.SilkS` (achterkant opdruk)
   - `F.Mask` (soldeermasker voor)
   - `B.Mask` (soldeermasker achter)
   - `Edge.Cuts` (PCB omtrek)
4. **File → Drill Files → Generate Drill File**
5. Zip alle gegenereerde bestanden → upload naar JLCPCB

### JLCPCB instellingen
| Parameter | Waarde |
|-----------|--------|
| PCB afmetingen | 100 × 80 mm |
| Lagen | 2 |
| Dikte | 1.6 mm |
| Kleur soldeermasker | Groen |
| Oppervlaktebehandeling | HASL (loodvrij) |
| Koper dikte | 1 oz |
| Minimale track/ruimte | 0.2/0.2 mm |
| Minimale via | 0.5 mm diameter, 0.3 mm boor |
| Hoeveelheid | 5 (minimale bestelling) |
| **Totaal** | **~€5 excl. verzending** |

---

## Soldeervolgorde (aanbevolen)

1. **SMD componenten eerst** (reflow of handmatig):
   - C1–C4 (100nF 0402)
   - C7–C9 (10µF 0805)
   - D1, D3, D5 (SOD-123)

2. **THT componenten daarna** (handmatig solderen):
   - R1–R11 (axiaal)
   - C10 (100µF axiaal)
   - J1–J4 (Phoenix schroefklemmen)
   - LED1
   - SW1, SW2

3. **Modules als laatste**:
   - U1 ESP32-S3 DevKitC via 2×19 pin headers
   - J5 USB-C connector

---

## Testprocedure na montage

```
1. Visuele inspectie — geen solder bridges, alle componenten juist georiënteerd
2. Weerstandsmeting VOOR inschakelen:
   - GND–3V3: moet > 1kΩ zijn (niet kortgesloten)
   - Bias-punten: meten ~1.65V t.o.v. GND na inschakelen
3. Eerste inschakeling met stroombegrenzer (100mA max)
4. Controleer spanningen:
   - J5 USB-C → 5V aanwezig
   - 3V3 rail → 3.28–3.32V
   - Bias-punten GPIO1/2/3/4 → 1.60–1.70V (= 3V3/2)
5. ESPHome flashen:
   - Houd SW2 (BOOT) ingedrukt, druk SW1 (RESET), laat RESET los, laat BOOT los
   - esphome run cloudems_nilm_meter.yaml --device /dev/ttyUSB0
6. HA koppelen en sensoren controleren
```

---

## Kalibratie

### CT kalibratie (eenmalig na montage)
Verbind een bekende last (bijv. 2kW waterkoker) op L1:
```yaml
# In cloudems_nilm_meter.yaml — pas I_SCALE aan tot vermogen klopt:
# I_SCALE = werkelijk_ampere / gemeten_ampere * huidige_I_SCALE
```

### ZMPT101B kalibratie
Meet spanning met een kalibratiemeter. Pas `V_SCALE` aan:
```yaml
# V_SCALE = werkelijke_V / gemeten_V * huidige_V_SCALE
```

---

## Alternatieve PCB-fabrikanten (Europa)

| Fabrikant | Levertijd | Prijs 5st | Opmerking |
|-----------|-----------|-----------|-----------|
| JLCPCB | 7–14 dagen | €5 + verzending | Goedkoopst |
| PCBWay | 7–14 dagen | €8 + verzending | Goede kwaliteit |
| Eurocircuits | 3–5 dagen | €30–50 | Europese fabrikant |
| Aisler | 5–7 dagen | €15–25 | Duits, GDPR-vriendelijk |
