from __future__ import annotations
"""
CloudEMS Utilities
Gedeelde hulpfuncties voor gebruik door alle modules.
"""
import re


def slugify(name: str) -> str:
    """
    Zet een label om naar een HA-entiteit-veilige slug.
    "Boiler 1" → "boiler_1", "Zonneplan Nexus" → "zonneplan_nexus"
    Identiek aan virtual_boiler._slugify() — centraal gedefinieerd.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def slugify_entity_id(entity_id: str) -> str:
    """
    Extraheer de slug uit een entity_id.
    "water_heater.ariston" → "ariston"
    """
    return entity_id.split(".")[-1].replace("-", "_")


def format_duration(seconds: float) -> str:
    """Formatteer seconden naar leesbare string: "2u 15m" of "45m"."""
    if seconds < 60:
        return f"{int(seconds)}s"
    m = int(seconds // 60)
    h = m // 60
    m = m % 60
    if h > 0:
        return f"{h}u {m}m" if m > 0 else f"{h}u"
    return f"{m}m"


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Begrens een waarde tussen min en max."""
    return max(min_val, min(max_val, value))
