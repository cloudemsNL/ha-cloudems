// CloudEMS Battery Plan Card v1.0
// Toont uur-voor-uur laad/ontlaad plan: gisteren, vandaag, morgen
// Leest van sensor.cloudems_battery_schedule / sensor.cloudems_batterij_epex_schema

class CloudEMSBatteryPlanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._activeDay = 'vandaag';
  }

  setConfig(config) { this._config = config || {}; }

  set hass(h) {
    this._hass = h;
    this._render();
  }

  _sensor() {
    const h = this._hass;
    return h.states['sensor.cloudems_batterij_epex_schema']
        || h.states['sensor.cloudems_battery_schedule']
        || null;
  }

  // All-in prijs: EPEX + energiebelasting + ODE + BTW
  _allin(epex_eur) {
    return +((epex_eur * 100 + 18.2) * 1.21).toFixed(1);
  }

  _render() {
    if (!this._hass) return;
    const sch   = this._sensor();
    const schA  = sch?.attributes || {};
    const today     = schA.schedule          || [];
    const yesterday = schA.schedule_yesterday || [];
    const tomorrow  = schA.schedule_tomorrow  || [];
    const surplus   = schA.surplus_forecast   || [];
    const zp    = schA.zonneplan        || {};
    const socNow = schA.soc_pct ?? zp?.soc_pct ?? null;
    const nowH  = new Date().getHours();
    const day   = this._activeDay;

    // Morgen = echte prognose op basis van EPEX+PV van morgen
    const slots = day === 'gisteren' ? yesterday
                : day === 'morgen'   ? (tomorrow.length > 0 ? tomorrow : today.map(s => ({...s, is_tomorrow: true})))
                : today;

    // Verrijk slots met surplus_forecast data als house_w ontbreekt
    const surplusByHour = {};
    for (const s of surplus) surplusByHour[s.hour] = s;

    const enriched = Array.from({length: 24}, (_, h) => {
      const s  = slots.find(x => parseInt(x.hour) === h) || {hour:h, action:'idle', price:0};
      const sf = surplusByHour[h] || {};
      return {
        h,
        action:    (s.action || 'idle').toLowerCase(),
        price_eur: s.price      ?? 0,
        pv_w:      s.pv_w       ?? sf.pv_w    ?? 0,
        house_w:   s.house_w    ?? sf.house_w  ?? 0,
        power_w:   s.power_w    ?? null,
        soc_start: s.soc_start  ?? null,
        soc_end:   s.soc_end    ?? null,
        price_allin: s.price_allin ?? this._allin(s.price ?? 0),
        reason:    s.reason     ?? '',
        executed:  !!(s.is_tomorrow ? false : day === 'gisteren' || (day === 'vandaag' && h < nowH)),
      };
    });

    const chSlots = enriched.filter(s => s.action === 'charge');
    const diSlots = enriched.filter(s => s.action === 'discharge');
    const chKwh   = (chSlots.reduce((a,s) => a+(s.power_w||0), 0)/1000).toFixed(1);
    const diKwh   = (diSlots.reduce((a,s) => a+(s.power_w||0), 0)/1000).toFixed(1);
    const maxPV   = Math.max(...enriched.map(s => s.pv_w||0), 1);
    const maxPR   = Math.max(...enriched.map(s => s.price_allin||0), 1);

    const pc = ct  => ct < 30 ? '#10b981' : ct < 45 ? '#64748b' : '#ef4444';
    const sc = pct => pct > 70 ? '#10b981' : pct > 30 ? '#f59e0b' : '#ef4444';
    const ac = a   => a === 'charge' ? '#10b981' : a === 'discharge' ? '#f97316' : null;

    const rows = enriched.map(d => {
      const isNow  = day === 'vandaag' && d.h === nowH;
      const isPast = d.executed;
      const C  = pc(d.price_allin);
      const A  = ac(d.action);
      const S  = d.soc_end != null ? sc(d.soc_end) : '#475569';
      const pvB  = Math.round((d.pv_w    / maxPV) * 52);
      const prB  = Math.round((d.price_allin / maxPR) * 52);
      const socB = d.soc_end != null ? Math.round(d.soc_end / 100 * 56) : 0;
      const surplus = d.pv_w > 0 && d.house_w > 0 ? d.pv_w - d.house_w : null;

      return `<tr style="
        border-bottom:1px solid rgba(255,255,255,.03);
        ${isNow ? 'background:rgba(245,158,11,.06);box-shadow:inset 3px 0 0 #f59e0b;' : ''}
        ${isPast && !isNow ? 'opacity:.38;' : ''}
      ">
        <!-- Uur -->
        <td style="padding:8px 10px 8px 20px;white-space:nowrap">
          <div style="font-family:var(--m);font-size:12px;font-weight:600;color:${isNow?'#f59e0b':'#475569'}">
            ${isNow ? '<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#f59e0b;margin-right:5px;animation:p 1.4s ease-in-out infinite;vertical-align:middle"></span>' : ''}
            ${String(d.h).padStart(2,'0')}:00
          </div>
          ${d.executed && d.action !== 'idle' ? '<div style="font-size:8px;color:#1e3a2f;margin-top:1px">✓ uitgevoerd</div>' : ''}
        </td>

        <!-- Tarief badge + all-in prijs -->
        <td style="padding:8px 10px 8px 0">
          <div style="font-family:var(--m);font-size:11px;font-weight:700;color:${C}">${d.price_allin.toFixed(1)} ct</div>
          <div style="font-size:9px;color:#475569;margin-top:1px">EPEX ${(d.price_eur*100).toFixed(1)}ct</div>
          <div style="height:2px;background:rgba(255,255,255,.06);border-radius:2px;margin-top:4px;width:52px">
            <div style="height:2px;border-radius:2px;width:${prB}px;background:${C}"></div>
          </div>
        </td>

        <!-- PV -->
        <td style="padding:8px 10px 8px 0">
          ${d.pv_w > 0
            ? `<div style="font-family:var(--m);font-size:12px;color:#f59e0b">
                 ${d.pv_w>=1000?(d.pv_w/1000).toFixed(2)+' kW':d.pv_w+' W'}
               </div>
               <div style="height:2px;background:rgba(255,255,255,.06);border-radius:2px;margin-top:4px;width:52px">
                 <div style="height:2px;border-radius:2px;width:${pvB}px;background:#f59e0b"></div>
               </div>`
            : '<div style="color:rgba(255,255,255,.1);font-size:13px">—</div>'}
        </td>

        <!-- Huis + surplus/tekort -->
        <td style="padding:8px 10px 8px 0">
          ${d.house_w > 0
            ? `<div style="font-family:var(--m);font-size:12px;color:#94a3b8">
                 ${d.house_w>=1000?(d.house_w/1000).toFixed(2)+' kW':d.house_w+' W'}
               </div>
               ${surplus !== null ? `<div style="font-size:9px;margin-top:2px;color:${surplus>=0?'#10b981':'#ef4444'}">
                 ${surplus>=0?'↑ +'+Math.round(surplus)+'W':'↓ '+Math.round(-surplus)+'W'}
               </div>` : ''}`
            : '<div style="color:rgba(255,255,255,.1);font-size:13px">—</div>'}
        </td>

        <!-- Actie + vermogen -->
        <td style="padding:8px 10px 8px 0">
          ${d.action !== 'idle'
            ? `<div style="display:flex;align-items:center;gap:7px">
                 <div style="font-size:17px;line-height:1">${d.action==='charge'?'⚡':'↓'}</div>
                 <div>
                   <div style="font-size:12px;font-weight:700;color:${A}">${d.action==='charge'?'Laden':'Ontladen'}</div>
                   ${d.power_w!=null?`<div style="font-family:var(--m);font-size:10px;color:${A};margin-top:1px">
                     ${d.power_w>=1000?(d.power_w/1000).toFixed(2)+' kW':d.power_w+' W'}
                   </div>`:''}
                 </div>
               </div>`
            : '<div style="color:rgba(255,255,255,.1);font-size:13px">—</div>'}
        </td>

        <!-- SoC -->
        <td style="padding:8px 10px 8px 0">
          ${d.soc_end != null
            ? `<div style="display:flex;align-items:center;gap:7px">
                 <div style="width:56px;height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;flex-shrink:0">
                   <div style="height:6px;border-radius:3px;width:${socB}px;background:${S}"></div>
                 </div>
                 <div>
                   <div style="font-family:var(--m);font-size:12px;font-weight:700;color:${S}">${d.soc_end.toFixed(0)}%</div>
                   ${d.soc_start!=null&&d.soc_start!==d.soc_end
                     ?`<div style="font-family:var(--m);font-size:9px;color:#475569;margin-top:1px">van ${d.soc_start.toFixed(0)}%</div>`:''}
                 </div>
               </div>`
            : '<div style="color:rgba(255,255,255,.1)">—</div>'}
        </td>

        <!-- Reden -->
        <td style="padding:8px 20px 8px 0">
          <div style="font-size:10px;color:#475569;line-height:1.5;max-width:220px">${d.reason || (d.action==='idle'?'Geen actie gepland':'')}</div>
        </td>
      </tr>`;
    }).join('');

    const s0 = enriched[0]?.soc_start;
    const s1 = enriched[23]?.soc_end;

    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}
        *{box-sizing:border-box;margin:0;padding:0}
        ha-card{
          background:#0d1117;border:1px solid rgba(255,255,255,.06);
          border-radius:16px;overflow:hidden;
          font-family:'Inter',ui-sans-serif,sans-serif;color:#cbd5e1;
        }
        :host{--m:'JetBrains Mono',monospace}
        .hdr{padding:16px 20px 14px;border-bottom:1px solid rgba(255,255,255,.06);display:flex;align-items:center;gap:12px}
        .hicon{width:38px;height:38px;background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.2);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px}
        .htxt{flex:1}
        .htitle{font-size:14px;font-weight:700;color:#f1f5f9}
        .hsub{font-size:10px;color:#475569;margin-top:2px}
        .tabs{display:flex;border-bottom:1px solid rgba(255,255,255,.06);background:#0a0e14}
        .tab{padding:10px 20px;font-size:11px;font-weight:600;color:#475569;cursor:pointer;border-bottom:2px solid transparent;transition:all .15s}
        .tab:hover{color:#cbd5e1}
        .tab.active{color:#f59e0b;border-bottom-color:#f59e0b;background:#0d1117}
        .sum{display:grid;grid-template-columns:repeat(5,1fr);border-bottom:1px solid rgba(255,255,255,.06)}
        .si{padding:11px 16px;border-right:1px solid rgba(255,255,255,.06)}
        .si:last-child{border-right:none}
        .sv{font-family:var(--m);font-size:13px;font-weight:700;line-height:1}
        .sl{font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-top:3px}
        .tw{overflow-x:auto}
        table{width:100%;border-collapse:collapse}
        thead tr{border-bottom:1px solid rgba(255,255,255,.06)}
        th{font-size:8px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:.12em;text-align:left;padding:9px 10px 9px 0;white-space:nowrap}
        th:first-child{padding-left:20px}
        tbody tr:hover{background:rgba(255,255,255,.01)}
        @keyframes p{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}
        .no-data{padding:28px;text-align:center;color:#374151;font-size:12px}
      </style>
      <ha-card>
        <div class="hdr">
          <div class="hicon">🔋</div>
          <div class="htxt">
            <div class="htitle">Uur-voor-uur Batterijplan</div>
            <div class="hsub">Zonneplan Nexus · EPEX spotprijs + all-in · PV forecast · geleerd huisverbruik</div>
          </div>
          ${socNow!=null?`<div style="text-align:right">
            <div style="font-family:var(--m);font-size:22px;font-weight:700;color:#f59e0b;line-height:1">${parseFloat(socNow).toFixed(0)}%</div>
            <div style="font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-top:2px">SoC nu</div>
          </div>`:''}
        </div>

        <div class="tabs">
          <div class="tab ${day==='gisteren'?'active':''}" id="tab-g">Gisteren</div>
          <div class="tab ${day==='vandaag' ?'active':''}" id="tab-v">Vandaag</div>
          <div class="tab ${day==='morgen'  ?'active':''}" id="tab-m">Morgen</div>
        </div>

        ${slots.length > 0 ? `
          <div class="sum">
            <div class="si"><div class="sv" style="color:#10b981">⚡ ${chSlots.length}u</div><div class="sl">Laaduren</div></div>
            <div class="si"><div class="sv" style="color:#f97316">↓ ${diSlots.length}u</div><div class="sl">Ontlaaduren</div></div>
            <div class="si"><div class="sv" style="color:#10b981">+${chKwh} kWh</div><div class="sl">Geladen</div></div>
            <div class="si"><div class="sv" style="color:#f97316">−${diKwh} kWh</div><div class="sl">Ontladen</div></div>
            <div class="si"><div class="sv">${s0!=null?s0.toFixed(0):'—'}% → ${s1!=null?s1.toFixed(0):'—'}%</div><div class="sl">SoC verloop</div></div>
          </div>
          <div class="tw">
            <table>
              <thead><tr>
                <th>UUR</th><th>ALL-IN · EPEX</th><th>PV</th><th>HUIS</th>
                <th>ACTIE &amp; VERMOGEN</th><th>SOC</th><th>REDEN</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        ` : `<div class="no-data">Geen data beschikbaar voor ${day}.</div>`}
      </ha-card>
    `;

    // Tab click handlers
    this.shadowRoot.getElementById('tab-g')?.addEventListener('click', () => { this._activeDay='gisteren'; this._render(); });
    this.shadowRoot.getElementById('tab-v')?.addEventListener('click', () => { this._activeDay='vandaag';  this._render(); });
    this.shadowRoot.getElementById('tab-m')?.addEventListener('click', () => { this._activeDay='morgen';   this._render(); });
  }

  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig()    { return {}; }
}

customElements.define('cloudems-battery-plan-card', CloudEMSBatteryPlanCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-battery-plan-card')) {
  window.customCards.push({
    type:        'cloudems-battery-plan-card',
    name:        'CloudEMS Batterijplan',
    description: 'Uur-voor-uur laad/ontlaad plan: gisteren, vandaag, morgen',
  });
}
