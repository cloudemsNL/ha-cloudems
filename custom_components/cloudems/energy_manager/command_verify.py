"""
CloudEMS — command_verify.py
Generieke send-and-verify utility voor elk type sturing.

Principe: nooit aannemen dat een commando aankomt.
Stuur → wacht → lees terug → retry bij mismatch.

Werkt voor:
  - select entities (mode keuze)
  - switch entities (aan/uit)
  - number entities (setpoint)
  - cover entities (positie)
  - light entities (dimmer %)
  - climate entities (temperatuur/modus)
  - water_heater entities
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

# Standaard backoff reeks in seconden
_DEFAULT_BACKOFF = [5, 10, 15, 30, 60]


async def send_and_verify(
    hass,
    domain: str,
    service: str,
    service_data: dict,
    entity_id: str,
    verify_fn: Callable[[Any], bool],
    description: str = "",
    backoff: list[int] | None = None,
    max_attempts: int = 5,
    verify_delay: float = 3.0,
) -> bool:
    """
    Stuur een HA service-aanroep en verifieer dat de entity de verwachte staat aanneemt.

    Args:
        hass:           HomeAssistant instance
        domain:         Service domain (bijv. "select", "switch", "number")
        service:        Service naam (bijv. "select_option", "turn_on", "set_value")
        service_data:   Dict met parameters voor de service
        entity_id:      Entity om te verifiëren
        verify_fn:      Functie die hass.states.get(entity_id) ontvangt en True geeft als correct
        description:    Beschrijving voor in de logs
        backoff:        Lijst van wachttijden per poging (standaard [5, 10, 15, 30, 60])
        max_attempts:   Maximaal aantal pogingen (0 = oneindig)
        verify_delay:   Seconden wachten na sturen voor verificatie

    Returns:
        True als bevestigd, False als max_attempts bereikt
    """
    from .audit_log import get_audit_log
    _audit = get_audit_log()

    backoff = backoff or _DEFAULT_BACKOFF
    attempt = 0
    label = description or f"{domain}.{service} → {entity_id}"
    _start_ts = time.time()

    # Registreer commando in audit log
    _audit_id = _audit.record_command(
        module=domain,
        entity_id=entity_id,
        action=f"{service} → {str(next(iter(service_data.values()), ''))[:30]}",
        expected=str(next(iter(service_data.values()), ''))[:50],
        context={},
    )

    while max_attempts == 0 or attempt < max_attempts:
        try:
            # Stuur commando
            await hass.services.async_call(
                domain, service, service_data, blocking=False
            )
            _LOGGER.debug("CloudEMS send_and_verify: %s gestuurd (poging %d)", label, attempt + 1)

            # Wacht dan verifieer
            await asyncio.sleep(verify_delay)
            state = hass.states.get(entity_id)

            if state is None:
                _LOGGER.warning(
                    "CloudEMS send_and_verify: %s — entity %s niet gevonden (poging %d)",
                    label, entity_id, attempt + 1
                )
            elif verify_fn(state):
                _LOGGER.info(
                    "CloudEMS send_and_verify: %s bevestigd — %s = %s (poging %d)",
                    label, entity_id, state.state, attempt + 1
                )
                _audit.update_command(
                    _audit_id, success=True, actual=state.state,
                    attempts=attempt + 1,
                    duration_ms=(time.time() - _start_ts) * 1000,
                )
                return True
            else:
                _LOGGER.warning(
                    "CloudEMS send_and_verify: %s niet bevestigd — %s = %s (poging %d)",
                    label, entity_id, state.state, attempt + 1
                )

        except Exception as exc:
            _LOGGER.warning(
                "CloudEMS send_and_verify: %s fout (poging %d): %s",
                label, attempt + 1, exc
            )

        attempt += 1
        if max_attempts > 0 and attempt >= max_attempts:
            _LOGGER.error(
                "CloudEMS send_and_verify: %s mislukt na %d pogingen — opgegeven",
                label, max_attempts
            )
            state = hass.states.get(entity_id)
            _audit.update_command(
                _audit_id, success=False,
                actual=state.state if state else "entity_not_found",
                attempts=attempt,
                duration_ms=(time.time() - _start_ts) * 1000,
            )
            return False

        wait = backoff[min(attempt - 1, len(backoff) - 1)]
        _LOGGER.debug("CloudEMS send_and_verify: %s retry over %ds", label, wait)
        await asyncio.sleep(wait)

    return False


# ── Kant-en-klare helpers ──────────────────────────────────────────────────────

async def send_select(
    hass, entity_id: str, option: str,
    description: str = "", **kwargs
) -> bool:
    """Stuur select.select_option en verifieer dat entity.state == option."""
    return await send_and_verify(
        hass=hass,
        domain="select", service="select_option",
        service_data={"entity_id": entity_id, "option": option},
        entity_id=entity_id,
        verify_fn=lambda s: s.state == option,
        description=description or f"select {entity_id} → {option}",
        **kwargs,
    )


async def send_switch(
    hass, entity_id: str, turn_on: bool,
    description: str = "", **kwargs
) -> bool:
    """Stuur switch.turn_on/off en verifieer state."""
    service = "turn_on" if turn_on else "turn_off"
    expected = "on" if turn_on else "off"
    return await send_and_verify(
        hass=hass,
        domain="switch", service=service,
        service_data={"entity_id": entity_id},
        entity_id=entity_id,
        verify_fn=lambda s: s.state == expected,
        description=description or f"switch {entity_id} → {expected}",
        **kwargs,
    )


async def send_number(
    hass, entity_id: str, value: float, tolerance: float = 1.0,
    description: str = "", **kwargs
) -> bool:
    """Stuur number.set_value en verifieer dat waarde binnen tolerantie ligt."""
    return await send_and_verify(
        hass=hass,
        domain="number", service="set_value",
        service_data={"entity_id": entity_id, "value": value},
        entity_id=entity_id,
        verify_fn=lambda s: abs(float(s.state or 0) - value) <= tolerance,
        description=description or f"number {entity_id} → {value}",
        **kwargs,
    )


async def send_cover_position(
    hass, entity_id: str, position: int, tolerance: int = 3,
    description: str = "", **kwargs
) -> bool:
    """Stuur cover.set_cover_position en verifieer current_position."""
    def _verify(s):
        pos = s.attributes.get("current_position")
        return pos is not None and abs(int(pos) - position) <= tolerance
    return await send_and_verify(
        hass=hass,
        domain="cover", service="set_cover_position",
        service_data={"entity_id": entity_id, "position": position},
        entity_id=entity_id,
        verify_fn=_verify,
        description=description or f"cover {entity_id} → {position}%",
        **kwargs,
    )
