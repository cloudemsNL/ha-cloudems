# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

#!/usr/bin/env python3
"""
CloudEMS lint-check: detecteer nieuwe directe hass.states.get() calls
in energy_manager modules die de EntityProvider abstractie zouden moeten gebruiken.

Gebruik: python3 check_hass_states.py
Geeft exit code 1 als nieuwe schendingen gevonden worden.

Intentioneel uitgezonderd:
  - ha_provider.py  (dit IS de provider, mag hass.states gebruiken)
  - health_check.py (diagnostics, mag direct lezen)
  - p1_detector.py  (config-flow helper, eenmalig gebruik)

Cloud-pad: deze check draait ook in CI voor de Proxmox SaaS variant
om te garanderen dat geen HA-specifieke code in de business-logica sluipt.
"""
import ast, os, sys

ENERGY_MANAGER = "custom_components/cloudems/energy_manager"
ALLOWED = {"ha_provider.py", "health_check.py", "p1_detector.py", "p1_reader.py"}

violations = []

for fname in sorted(os.listdir(ENERGY_MANAGER)):
    if not fname.endswith(".py") or fname in ALLOWED:
        continue
    path = os.path.join(ENERGY_MANAGER, fname)
    src = open(path).read()
    for i, line in enumerate(src.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "hass.states.get(" in line or ".hass.states.get(" in line:
            violations.append(f"  {fname}:{i}  →  {stripped[:80]}")

if violations:
    print(f"⚠️  {len(violations)} directe hass.states.get() calls gevonden in energy_manager:")
    for v in violations:
        print(v)
    print("\nGebruik self._provider.get_state(entity_id) via de EntityProvider abstractie.")
    print("Dit garandeert compatibiliteit met de toekomstige Proxmox cloud-variant.")
    sys.exit(1)
else:
    print(f"✅ Geen directe hass.states.get() calls in energy_manager ({len(os.listdir(ENERGY_MANAGER))} modules)")
    sys.exit(0)

# ── Gebruik in CI/CD ──────────────────────────────────────────────────────────
# GitHub Actions:
#   - name: Check EntityProvider compliance
#     run: python3 custom_components/cloudems/check_hass_states.py
#
# Proxmox SaaS build:
#   Draai dit script als pre-build check. Bij exit code 1 wordt de build geblokkeerd.
#   Elke module die nog hass.states gebruikt moet worden omgezet naar EntityProvider
#   voordat hij in de cloud-variant kan draaien.
