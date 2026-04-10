"""
CloudEMS Battery Plan Controller — v5.5.465
Vervangt de BDE voor batterij-sturing. Het plan IS de controller.

Architectuur:
- PlanBuilder:   bouwt 24-uurs plan per cyclus met actuele data
- PlanExecutor:  voert huidig-uur slot uit per batterij
- Meerdere accu's: prioriteits-gebaseerde verdeling
"""
from __future__ import annotations
import logging, time, math
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)


# ─── Batterij definitie ───────────────────────────────────────────────────────

@dataclass
class BatterySpec:
    """Configuratie + real-time staat van één accu."""
    battery_id:       str
    battery_type:     str          # 'nexus' | 'generic' | 'switch'
    label:            str
    max_charge_w:     float = 3000.0
    max_discharge_w:  float = 3000.0
    capacity_kwh:     float = 10.0
    min_soc_pct:      float = 10.0
    max_soc_pct:      float = 100.0
    priority:         int   = 0    # lager = hogere prioriteit bij ontladen
    charge_priority:  int   = 0    # lager = eerder laden
    # Real-time state (wordt elke cyclus bijgewerkt)
    soc_pct:          float = 50.0
    power_w:          float = 0.0  # positief = laden, negatief = ontladen
    is_available:     bool  = True
    bridge:           object = field(default=None, repr=False)


# ─── Plan slot ────────────────────────────────────────────────────────────────

@dataclass
class PlanSlot:
    """Één uur in het 24-uurs plan."""
    hour:          int
    action:        str    # 'charge' | 'discharge' | 'idle'
    price_eur:     float  = 0.0
    price_allin:   float  = 0.0
    tariff_group:  str    = 'normal'
    pv_w:          float  = 0.0
    house_w:       float  = 0.0
    surplus_w:     float  = 0.0
    deficit_w:     float  = 0.0
    # Totaal vermogen (som van alle accu's)
    total_charge_w:    float = 0.0
    total_discharge_w: float = 0.0
    # Per-accu opdrachten: {battery_id: {'action': str, 'power_w': float, 'soc_end': float}}
    battery_commands:  dict  = field(default_factory=dict)
    # SOC per accu einde uur: {battery_id: float}
    soc_end:       dict  = field(default_factory=dict)
    soc_start:     dict  = field(default_factory=dict)
    reason:        str   = ''
    house_estimated: bool = True
    actual:        Optional[dict] = None


# ─── Plan Builder ─────────────────────────────────────────────────────────────

class BatteryPlanBuilder:
    """
    Bouwt een 24-uurs plan voor meerdere accu's.
    Vervangt de plan-builder + BDE in coordinator.py.
    """

    def __init__(self, batteries: list[BatterySpec]):
        self._batteries = batteries

    def build(self,
              now_h:         int,
              price_by_h:    dict,   # {hour: eur/kWh}
              pv_by_h:       dict,   # {hour: W}
              house_by_h:    dict,   # {hour: W}
              house_ema_w:   float,  # actuele gladgestreken waarde
              actual_by_h:   dict,   # {hour: {soc_pct, bat_w, pv_w, house_w}}
              export_limit_w: float = 0.0,
              ev_charge_w:   float  = 0.0,
              house_estimated: bool = True,
              ) -> list[PlanSlot]:

        slots: list[PlanSlot] = []
        # Per-accu gesimuleerde SOC, start bij actuele waarde
        sim_soc = {b.battery_id: b.soc_pct for b in self._batteries}

        # Prijs statistieken voor schaling
        prices = [v for v in price_by_h.values() if v is not None]
        p_min  = min(prices) if prices else 0.0
        p_max  = max(prices) if prices else 0.25
        p_rng  = max(0.01, p_max - p_min)

        def _tg(h):
            al = price_by_h.get(h, 0) * 100
            return 'high' if al > 35 else ('low' if al < 18 else 'normal')

        def _high_next(from_h, n=6):
            return sum(1 for i in range(1, n+1) if _tg((from_h+i)%24)=='high')

        for h in range(24):
            p   = price_by_h.get(h, 0.0)
            pv  = pv_by_h.get(h, 0.0)
            al  = round(p * 100, 1)
            tg  = _tg(h)

            # ── Verleden uren ──────────────────────────────────────────────
            if h < now_h:
                actual  = actual_by_h.get(h, {})
                hw      = actual.get('house_w', house_by_h.get(h, 500.0))
                bat_w   = actual.get('bat_w', 0.0)
                soc_val = actual.get('soc_pct')

                # Keten: soc_start = vorig slot soc_end
                prev_soc_end = slots[-1].soc_end.copy() if slots else {}
                soc_s = {}
                soc_e = {}
                for b in self._batteries:
                    bid = b.battery_id
                    soc_s[bid] = prev_soc_end.get(bid, soc_val or b.soc_pct)
                    soc_e[bid] = soc_val or b.soc_pct

                slots.append(PlanSlot(
                    hour=h, action='idle', price_eur=p, price_allin=al,
                    tariff_group=tg, pv_w=pv, house_w=hw,
                    total_discharge_w=max(0, -bat_w),
                    total_charge_w=max(0, bat_w),
                    soc_start=soc_s, soc_end=soc_e,
                    actual=actual, house_estimated=house_estimated,
                    reason=f'Verleden — {al:.1f}ct',
                ))
                continue

            # ── Huidig + toekomstig uur ────────────────────────────────────
            if h == now_h:
                # Huidig uur: actuele gladgestreken huisverbruik
                hw = house_ema_w if house_ema_w > 50 else house_by_h.get(h, 500.0)
                # Reset simulatie naar werkelijke SOC
                sim_soc = {b.battery_id: b.soc_pct for b in self._batteries}
            else:
                hw = house_by_h.get(h, 500.0)

            hw_ev   = hw + ev_charge_w
            surplus = max(0.0, pv - hw_ev)
            deficit = max(0.0, hw_ev - pv)

            # ── Bepaal gewenste actie en totaalvermogen ─────────────────────
            # Totale laad/ontlaadcapaciteit van alle beschikbare accu's
            total_max_chg = sum(b.max_charge_w  for b in self._batteries if b.is_available)
            total_max_dis = sum(b.max_discharge_w for b in self._batteries if b.is_available
                                and sim_soc[b.battery_id] > b.min_soc_pct)

            exp_chg_w = 0.0
            exp_dis_w = 0.0

            # Laden: PV surplus
            if surplus > 50:
                exp_chg_w = min(surplus, total_max_chg)

            # Laden: LOW tarief + HIGH verwacht
            if tg == 'low':
                n_high = _high_next(h)
                if n_high >= 1 or p < 0:
                    cheap_f = 1.0 - ((p - p_min) / p_rng)
                    urg = max(0.3, min(1.0, cheap_f + n_high * 0.15))
                    net_chg = max(300, round(total_max_chg * urg))
                    exp_chg_w = max(exp_chg_w, net_chg)

            # Negatief tarief: altijd maximaal laden
            if p < 0:
                exp_chg_w = total_max_chg

            # Ontladen: HIGH tarief
            if total_max_dis >= 50:
                if tg == 'high':
                    pf = min(1.0, (p - p_min) / p_rng)
                    exp_dis_w = min(total_max_dis, max(500, round(total_max_dis * (0.5 + 0.5*pf))))
                    if export_limit_w > 0:
                        exp_dis_w = min(exp_dis_w, export_limit_w + hw_ev)
                elif deficit > 50:
                    exp_dis_w = min(deficit, total_max_dis)

            # Bepaal actie
            if exp_dis_w >= 50 and exp_chg_w < exp_dis_w:
                action = 'discharge'
            elif exp_chg_w >= 50:
                action = 'charge'
            else:
                action = 'idle'
                exp_chg_w = exp_dis_w = 0.0

            # ── Verdeel over accu's ────────────────────────────────────────
            bat_cmds, soc_s, soc_e = self._distribute(
                action, exp_chg_w, exp_dis_w, sim_soc, h
            )

            # Update sim_soc voor volgende uur
            for bid, se in soc_e.items():
                sim_soc[bid] = se

            reason = (f'{tg.upper()} {al:.1f}ct — '
                      f'{"↑ " + str(round(exp_chg_w)) + "W" if action=="charge" else ""}'
                      f'{"↓ " + str(round(exp_dis_w)) + "W" if action=="discharge" else "idle"}')

            slots.append(PlanSlot(
                hour=h, action=action, price_eur=p, price_allin=al,
                tariff_group=tg, pv_w=pv, house_w=hw,
                surplus_w=surplus, deficit_w=deficit,
                total_charge_w=exp_chg_w,
                total_discharge_w=exp_dis_w,
                battery_commands=bat_cmds,
                soc_start=soc_s, soc_end=soc_e,
                house_estimated=(h != now_h or house_estimated),
                reason=reason,
            ))

        return slots

    def _distribute(self,
                    action: str,
                    chg_w: float,
                    dis_w: float,
                    sim_soc: dict,
                    hour: int,
                    ) -> tuple[dict, dict, dict]:
        """
        Verdeelt charge/discharge over meerdere accu's.
        Ontladen: hoogste SOC eerst (of laagste priority-getal).
        Laden:    laagste SOC eerst (vult gelijkmatig aan).
        Returns: (battery_commands, soc_start, soc_end)
        """
        cmds   = {}
        soc_s  = {b.battery_id: sim_soc[b.battery_id] for b in self._batteries}
        soc_e  = {b.battery_id: sim_soc[b.battery_id] for b in self._batteries}

        avail = [b for b in self._batteries if b.is_available]

        if action == 'discharge':
            remaining = dis_w
            # Prioriteit: laagste priority-getal, dan hoogste SOC
            ordered = sorted(avail,
                key=lambda b: (b.priority, -sim_soc[b.battery_id]))
            for b in ordered:
                bid = b.battery_id
                soc = sim_soc[bid]
                headroom = max(0.0, soc - b.min_soc_pct) / 100.0 * b.capacity_kwh
                max_dis   = min(b.max_discharge_w, headroom * 1000, remaining)
                if max_dis < 50:
                    cmds[bid] = {'action': 'idle', 'power_w': 0.0}
                    continue
                cmds[bid]  = {'action': 'discharge', 'power_w': max_dis}
                delta_soc  = (max_dis / 1000.0) / b.capacity_kwh * 100.0
                soc_e[bid] = round(max(b.min_soc_pct, soc - delta_soc), 1)
                remaining -= max_dis
                if remaining < 50:
                    break
            # Accu's die niet gebruikt worden: idle
            for b in avail:
                if b.battery_id not in cmds:
                    cmds[b.battery_id] = {'action': 'idle', 'power_w': 0.0}

        elif action == 'charge':
            remaining = chg_w
            # Prioriteit: laagste SOC eerst (gelijkmatig aanvullen)
            ordered = sorted(avail,
                key=lambda b: (b.charge_priority, sim_soc[b.battery_id]))
            for b in ordered:
                bid = b.battery_id
                soc = sim_soc[bid]
                headroom  = max(0.0, b.max_soc_pct - soc) / 100.0 * b.capacity_kwh
                max_chg   = min(b.max_charge_w, headroom * 1000, remaining)
                if max_chg < 50:
                    cmds[bid] = {'action': 'idle', 'power_w': 0.0}
                    continue
                cmds[bid]  = {'action': 'charge', 'power_w': max_chg}
                delta_soc  = (max_chg / 1000.0) / b.capacity_kwh * 100.0
                soc_e[bid] = round(min(b.max_soc_pct, soc + delta_soc), 1)
                remaining -= max_chg
                if remaining < 50:
                    break
            for b in avail:
                if b.battery_id not in cmds:
                    cmds[b.battery_id] = {'action': 'idle', 'power_w': 0.0}

        else:  # idle
            for b in avail:
                cmds[b.battery_id] = {'action': 'idle', 'power_w': 0.0}

        return cmds, soc_s, soc_e


# ─── Plan Executor ────────────────────────────────────────────────────────────

class BatteryPlanExecutor:
    """
    Voert het huidig-uur plan slot uit per batterij.
    Vervangt de BDE→ZP bridge aanroep in coordinator.py.
    """

    def __init__(self, hass):
        self._hass = hass
        self._last_exec: dict = {}  # {battery_id: {action, power_w, ts}}

    async def async_execute(self,
                            current_slot: PlanSlot,
                            batteries:    list[BatterySpec]) -> None:
        """Voer huidig-uur slot uit voor alle accu's."""
        for bat in batteries:
            if not bat.is_available:
                continue
            bid = bat.battery_id
            cmd = current_slot.battery_commands.get(bid, {'action': 'idle', 'power_w': 0.0})
            action  = cmd['action']
            power_w = float(cmd.get('power_w', 0.0))

            # Debounce: stuur niet opnieuw als identiek aan vorige cyclus
            last = self._last_exec.get(bid, {})
            if (last.get('action') == action and
                    abs(last.get('power_w', 0) - power_w) < 50 and
                    time.time() - last.get('ts', 0) < 60):
                continue

            try:
                await self._execute_battery(bat, action, power_w, current_slot)
                self._last_exec[bid] = {'action': action, 'power_w': power_w, 'ts': time.time()}
                _LOGGER.info(
                    "BatteryPlanExecutor [%s]: %s %.0fW",
                    bat.label, action, power_w
                )
            except Exception as err:
                _LOGGER.warning("BatteryPlanExecutor [%s]: fout: %s", bat.label, err)

    async def _execute_battery(self, bat: BatterySpec, action: str, power_w: float, slot: 'PlanSlot') -> None:
        """Stuur individuele accu aan op basis van type."""
        if bat.battery_type == 'nexus' and bat.bridge:
            # v5.5.465: Nexus sliders worden gestuurd via plan_deliver_w/plan_charge_w
            # in async_apply_forecast_decision_v3 — geen directe async_set_mode aanroep
            # om dubbele API-calls en 429 rate-limiting te voorkomen.
            cmd = slot.battery_commands.get(bat.battery_id, {})
            chg_w = float(cmd.get('charge_w', 0) if action == 'charge_and_discharge' else (power_w if action == 'charge' else 0))
            dis_w = float(cmd.get('discharge_w', 0) if action == 'charge_and_discharge' else (power_w if action == 'discharge' else 0))
            _LOGGER.debug(
                "BatteryPlanExecutor [%s]: plan=%s chg=%.0fW dis=%.0fW (bridge handles sliders)",
                bat.label, action, chg_w, dis_w
            )

        elif bat.battery_type == 'switch' and bat.bridge:
            # Domme accu via schakelaar (toekomst)
            svc = 'turn_on' if action == 'charge' else 'turn_off'
            await self._hass.services.async_call(
                'homeassistant', svc,
                {'entity_id': bat.bridge}, blocking=False
            )

        elif bat.battery_type == 'generic' and bat.bridge:
            # Generieke accu via boiler_controller of eigen API (toekomst)
            if hasattr(bat.bridge, 'async_set_power_w'):
                await bat.bridge.async_set_power_w(
                    power_w if action == 'charge' else -power_w
                )
