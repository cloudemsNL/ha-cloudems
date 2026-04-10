// CloudEMS Battery Plan Card v5.5.528
// Toont uur-voor-uur laad/ontlaad plan: gisteren, vandaag, morgen
// Leest van sensor.cloudems_battery_schedule / sensor.cloudems_batterij_epex_schema

class CloudEMSBatteryPlanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._activeDay = 'vandaag';
  }

  setConfig(config) { this._config = config || {}; }

  
  static getConfigElement(){return document.createElement('cloudems-battery-plan-card-editor');}
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
        soc_start:       s.soc_start       ?? s.actual?.soc_pct ?? null,
        soc_end:         s.soc_end         ?? s.actual?.soc_pct ?? null,
        house_estimated: s.house_estimated  ?? true,
        house_actual:    h === nowH,
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
      const S  = d.soc_end != null ? sc(d.soc_end) : '#475569';
      const socB = d.soc_end != null ? Math.round(d.soc_end / 100 * 56) : 0;

      // Formatteer watt/kWh: altijd een getal, nooit een streepje
      const fmtW = v => v >= 1000 ? (v/1000).toFixed(2)+'kWh' : Math.round(v)+'W';
      const fmtKwh = v => v == null ? null : v === 0 ? '0 kWh' : v < 0.05 ? Math.round(v*1000)+'W' : v.toFixed(2)+' kWh';

      // LADEN verleden: gemiddeld laadvermogen W (uit accumulator chg_w), toekomst: plan W
      // LEVER verleden: gemiddeld ontlaadvermogen W (uit accumulator dis_w), toekomst: plan W
      const _ladValP = isPast ? (d.actual?.chg_w ?? d.charge_kwh*1000 ?? 0) : (d.charge_w ?? 0);
      const _levValP = isPast ? (d.actual?.dis_w ?? d.discharge_kwh*1000 ?? 0) : (d.discharge_w ?? 0);
      const chgDisp = isPast ? (_ladValP > 0 ? Math.round(_ladValP)+'W' : '0W') : fmtW(_ladValP);
      const disDisp = isPast ? (_levValP > 0 ? Math.round(_levValP)+'W' : '0W') : fmtW(_levValP);
      const chgVal  = _ladValP;
      const disVal  = _levValP;

      const pvW    = Math.round(d.pv_w || 0);
      const hwW    = Math.round(d.house_w || 0);
      const hwSrc  = isNow ? '●' : d.house_estimated ? '~' : '✓';
      const pvDisp = fmtW(pvW);
      const hwDisp = fmtW(hwW);
      const priceStr = d.price_allin != null ? d.price_allin.toFixed(1)+'ct' : '0.0ct';

      // SOC: toon soc_end% als hoofd, "van X%" als kleine regel eronder wanneer start ≠ eind
      const _s0 = d.soc_start != null ? Math.round(d.soc_start) : null;
      const _s1 = d.soc_end   != null ? Math.round(d.soc_end)   : null;
      const _sA = d.actual?.soc_pct != null ? Math.round(d.actual.soc_pct) : null;
      const socEnd = _s1 ?? _sA;
      // SOC: start→eind als beiden bekend, anders enkel eind
      const socDisp = socEnd != null
        ? (_s0 != null ? _s0+'%→'+socEnd+'%' : socEnd+'%')
        : '—';

      const chgColor = chgVal > 0 ? '#22c55e' : '#475569';
      const disColor = disVal > 0 ? '#f97316' : '#475569';
      const pvColor  = pvW   > 0 ? '#fbbf24' : '#475569';
      return `<tr style="border-bottom:1px solid rgba(255,255,255,.03);${isNow?'background:rgba(245,158,11,.06);box-shadow:inset 3px 0 0 #f59e0b;':''}${isPast&&!isNow?'opacity:.55;':''}">
        <td style="padding:5px 8px 5px 16px;font-family:var(--m);font-size:12px;font-weight:600;color:${isNow?'#f59e0b':'#475569'};white-space:nowrap">${isNow?'<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#f59e0b;margin-right:4px;vertical-align:middle"></span>':''}${String(d.h).padStart(2,'0')}:00</td>
        <td style="padding:5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:${chgColor}">${chgDisp}</td>
        <td style="padding:5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:${disColor}">${disDisp}</td>
        <td style="padding:5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:${pvColor}">${pvDisp}</td>
        <td style="padding:5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:#94a3b8">${hwDisp}<span style="font-size:8px;opacity:.5;margin-left:2px">${hwSrc}</span></td>
        <td style="padding:5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:${C}">${priceStr}</td>
        <td style="padding:5px 16px 5px 6px;text-align:right;font-family:var(--m);font-size:11px;color:${S};line-height:1.3">${socDisp}</td>
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
                <th style='text-align:left;padding:0 8px 6px 16px;font-size:9px;color:#4b5563'>UUR</th>
                <th style='text-align:right;padding:0 6px 6px;font-size:9px;color:#22c55e'>LADEN</th>
                <th style='text-align:right;padding:0 6px 6px;font-size:9px;color:#f97316'>LEVER.</th>
                <th style='text-align:right;padding:0 6px 6px;font-size:9px;color:#fbbf24'>PV</th>
                <th style='text-align:right;padding:0 6px 6px;font-size:9px;color:#4b5563'>HUIS</th>
                <th style='text-align:right;padding:0 6px 6px;font-size:9px;color:#4b5563'>PRIJS</th>
                <th style='text-align:right;padding:0 16px 6px 6px;font-size:9px;color:#4b5563'>SOC</th>
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

  static getConfigElement(){return document.createElement('cloudems-battery-plan-card-editor');}
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


class CloudemsBatteryPlanCardEditor extends HTMLElement{
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  setConfig(c){this._cfg=c||{};this._render();}
  _render(){
    var self=this;var c=this._cfg;var sh=this.shadowRoot;sh.innerHTML='';
    var style=document.createElement('style');
    style.textContent=':host{display:block;padding:12px}';
    sh.appendChild(style);
    // Titel veld
    var rowT=document.createElement('div');rowT.style.marginBottom='10px';
    var lblT=document.createElement('label');lblT.textContent='Titel';lblT.style.cssText='display:block;font-size:12px;color:#aaa;margin-bottom:4px';
    var inpT=document.createElement('input');inpT.type='text';inpT.id='title';
    inpT.style.cssText='background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;box-sizing:border-box;width:100%';inpT.value=c.title||'';inpT.placeholder='(automatisch)';
    rowT.appendChild(lblT);rowT.appendChild(inpT);sh.appendChild(rowT);
    inpT.addEventListener('change',function(){
      var nc=Object.assign({},c);
      if(inpT.value)nc.title=inpT.value;else delete nc.title;
      self.dispatchEvent(new CustomEvent('config-changed',{detail:{config:nc},bubbles:true,composed:true}));
    });
    
  }
}
if(!customElements.get('cloudems-battery-plan-card-editor'))customElements.define('cloudems-battery-plan-card-editor',CloudemsBatteryPlanCardEditor);
if(!customElements.get('cloudems-battery-plan-card-editor'))customElements.define('cloudems-battery-plan-card-editor',CloudemsBatteryPlanCardEditor);
