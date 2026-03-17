/** @version 4.6.300
 * CloudEMS Prijsverloop Card — cloudems-prijsverloop-card
 *
 * Nieuw in 4.6.300:
 *   - Header rij 1: titel + Gisteren/Vandaag/Morgen tabs
 *   - Header rij 2: excl. (EPEX) / incl. (all-in) / +delta huidig uur
 *   - Gisteren tab: gevoed vanuit yesterday_prices (coordinator slaat op via _price_hour_history)
 *   - Prijsopbouw toggle (EPEX/EB/Netkosten/BTW) persistent via localStorage
 *   - Hover tooltip met exacte bedragen per component
 *   - Negatieve prijzen: zero-lijn + cyaan balk naar links, proportionele schaal
 *
 * Sensoren:
 *   sensor.cloudems_energy_epex_today  → today_prices, yesterday_prices, tomorrow_prices,
 *                                        price_excl_tax, price_incl_tax, current_price_display,
 *                                        tomorrow_available, prev_hour_price
 *   sensor.cloudems_batterij_epex_schema → charge_hours, discharge_hours
 *   sensor.cloudems_solar_system        → hourly[].hour, hourly[].forecast_w
 *   sensor.cloudems_ev_session          → optimal_start (hour int)
 *   sensor.cloudems_boiler_planning     → trigger_om (HH:MM string)
 *   sensor.cloudems_pool_water_temp     → state
 *   switch.cloudems_module_accu/ev/ketel/zwembad → state on/off
 */

const TPL = document.createElement('template');
TPL.innerHTML = `
<style>
  :host { display: block; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  .card {
    background: var(--ha-card-background, var(--card-background-color, rgb(26,26,26)));
    border-radius: var(--ha-card-border-radius, 14px);
    border: 1px solid rgba(255,255,255,0.07);
    overflow: hidden;
    color: var(--primary-text-color, #fff);
    font-family: var(--paper-font-body1_-_font-family, 'Inter', sans-serif);
  }

  /* Rij 1: titel + tabs */
  .hdr {
    padding: 11px 16px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .hdr-left { display: flex; align-items: center; gap: 8px; }
  .hdr-title { font-size: 14px; font-weight: 700; }
  .tabs { display: flex; gap: 4px; }
  .tab {
    padding: 3px 10px; border-radius: 9px; font-size: 10px; font-weight: 600;
    cursor: pointer; border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.45); background: transparent; transition: all 0.15s;
  }
  .tab.active { background: rgba(0,177,64,0.15); border-color: rgba(0,177,64,0.35); color: #00d14e; }
  .tab.disabled { opacity: 0.25; cursor: default; pointer-events: none; }
  .tab.past { opacity: 0.6; }

  /* Rij 2: excl / incl / delta */
  .price-bar {
    padding: 5px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap;
    font-size: 11px; color: rgba(255,255,255,0.45);
  }
  .pval { font-size: 13px; font-weight: 700; color: #fff; }
  .pdelta {
    font-size: 10px; color: rgba(255,255,255,0.3);
    background: rgba(255,255,255,0.07); border-radius: 5px; padding: 1px 6px;
  }

  /* Summary */
  .summary {
    padding: 7px 16px 3px;
    display: flex; gap: 14px; flex-wrap: wrap;
    font-size: 11px; color: rgba(255,255,255,0.45);
  }
  .summary strong { color: rgba(255,255,255,0.9); }

  /* Legend */
  .legend { padding: 4px 16px 6px; }
  .legend-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 10px; margin-bottom: 4px; }
  .legend-row { display: flex; align-items: center; gap: 5px; font-size: 9px; color: rgba(255,255,255,0.35); }
  .legend-blocks { display: flex; gap: 1px; flex-shrink: 0; }
  .legend-block { width: 3px; height: 12px; border-radius: 2px; }
  .legend-divider { height: 1px; background: rgba(255,255,255,0.06); margin: 3px 0; }
  .legend-inline { display: flex; gap: 10px; flex-wrap: wrap; }

  /* Opbouw toggle rij */
  .opbouw-row {
    padding: 4px 16px 5px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 4px;
  }
  .opbouw-left { display: flex; gap: 10px; flex-wrap: wrap; }
  .oleg { display: flex; align-items: center; gap: 4px; font-size: 9px; color: rgba(255,255,255,0.35); }
  .oleg-dot { width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0; }
  .toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
  .toggle-lbl { font-size: 10px; color: rgba(255,255,255,0.45); }
  .sw {
    width: 30px; height: 17px; border-radius: 9px;
    background: rgba(255,255,255,0.15);
    position: relative; transition: background 0.2s; flex-shrink: 0;
  }
  .sw.on { background: #00d14e; }
  .knob {
    width: 13px; height: 13px; border-radius: 50%;
    background: white; position: absolute; top: 2px; left: 2px; transition: left 0.2s;
  }
  .sw.on .knob { left: 15px; }

  /* Rows */
  .rows { padding: 1px 0 6px; }
  .row {
    display: grid;
    grid-template-columns: 16px 40px 50px 1fr 56px;
    align-items: center;
    gap: 0 3px;
    padding: 2px 12px 2px 3px;
    cursor: pointer;
    position: relative;
    transition: filter 0.1s;
  }
  .row:hover { filter: brightness(1.15); }
  .row.current { background: rgba(255,255,255,0.03); }
  .row.current::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: #00d14e; border-radius: 0 2px 2px 0;
    animation: pulse-edge 2s ease-in-out infinite;
  }
  @keyframes pulse-edge { 0%,100%{opacity:1} 50%{opacity:0.2} }

  .block-strips { display: flex; gap: 1px; align-self: stretch; align-items: stretch; }
  .strip { width: 3px; border-radius: 2px; min-height: 20px; opacity: 0.1; }
  .strip.on { opacity: 1; }
  .s4 { background: #4488ee; }
  .s3 { background: #CD8840; }
  .s2 { background: #A0A8B0; }
  .s1 { background: #FFD700; animation: glow-gold 2s ease-in-out infinite; }
  .s1:not(.on) { animation: none; }
  @keyframes glow-gold { 0%,100%{opacity:1} 50%{opacity:0.45} }

  .row-hour { font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.4); }
  .row.current .row-hour { color: #fff; font-weight: 700; }

  .row-icons { display: flex; gap: 1px; align-items: center; font-size: 9px; width: 50px; }
  .ico { width: 10px; text-align: center; flex-shrink: 0; font-size: 9px; }

  /* Bar area */
  .bar-col { display: flex; flex-direction: column; gap: 1px; }
  .bar-area { position: relative; height: 13px; overflow: hidden; }
  .bar-track {
    position: absolute; inset: 0;
    background: rgba(255,255,255,0.05);
    border-radius: 3px; overflow: hidden;
  }
  .zero-line {
    position: absolute; top: 0; bottom: 0; width: 1px;
    background: rgba(255,255,255,0.3); z-index: 2; display: none;
  }
  .has-negative .zero-line { display: block; }
  .bar-fill {
    position: absolute; top: 0; bottom: 0;
    transition: width 0.45s cubic-bezier(0.25,0.46,0.45,0.94);
  }
  .bar-fill.rank1::after {
    content: ''; position: absolute; top: 0; left: -100%; width: 70%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.55), transparent);
    animation: wave 2.2s ease-in-out infinite;
  }
  @keyframes wave { 0%{left:-100%} 100%{left:120%} }
  .bar-fill.charging::before {
    content: ''; position: absolute; top: 0; left: -60%; width: 40%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
    animation: shimmer 1s ease-in-out infinite;
  }
  @keyframes shimmer { 0%{left:-60%} 100%{left:110%} }

  /* PV balk */
  .pv-wrap { position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 2px; overflow: hidden; }
  .pv-actual { position: absolute; right: 0; top: 0; bottom: 0; width: 0%; border-radius: 2px; background: linear-gradient(90deg, rgba(160,210,40,0.5), rgba(210,255,50,0.95)); transition: width 0.6s ease; }
  .pv-forecast { position: absolute; right: 0; top: 0; bottom: 0; width: 0%; border-radius: 2px; background: repeating-linear-gradient(90deg, rgba(200,255,80,0.45) 0px, rgba(200,255,80,0.45) 3px, transparent 3px, transparent 6px); transition: width 0.6s ease; }

  /* Opbouw balkje */
  .bd-wrap { height: 0; overflow: hidden; transition: height 0.2s ease; position: relative; }
  .bd-wrap.show { height: 5px; }
  .bd-bar { height: 5px; border-radius: 2px; overflow: hidden; display: flex; position: absolute; top: 0; }
  .seg { height: 100%; }

  /* Prijslabel */
  .row-price { font-size: 10px; font-weight: 700; text-align: right; white-space: nowrap; }

  /* Tooltip */
  .tt-wrap {
    position: fixed;
    background: var(--ha-card-background, rgb(36,36,36));
    border: 1px solid rgba(255,255,255,0.12); border-radius: 9px;
    padding: 8px 11px; font-size: 10px; color: rgba(255,255,255,0.55);
    pointer-events: none; z-index: 9999; display: none; white-space: nowrap; line-height: 1.8;
  }
  .tt-r { display: flex; align-items: center; gap: 6px; }
  .tt-d { width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0; }
  .tt-l { min-width: 110px; }
  .tt-v { font-weight: 700; color: #fff; margin-left: auto; padding-left: 12px; }
  .tt-tot { border-top: 1px solid rgba(255,255,255,0.08); margin-top: 4px; padding-top: 4px; display: flex; justify-content: space-between; font-weight: 700; color: #fff; }
</style>

<div class="card" id="card">
  <!-- Rij 1: titel + tabs -->
  <div class="hdr">
    <div class="hdr-left">
      <span>📊</span>
      <span class="hdr-title">Prijsverloop</span>
    </div>
    <div class="tabs">
      <button class="tab past disabled" data-day="yesterday" id="tab-yest">Gisteren</button>
      <button class="tab active" data-day="today">Vandaag</button>
      <button class="tab" data-day="tomorrow" id="tab-tmr">Morgen</button>
    </div>
  </div>

  <!-- Rij 2: excl / incl / delta (alleen zichtbaar op vandaag-dag) -->
  <div class="price-bar" id="price-bar">
    <span>excl.</span><span class="pval" id="p-excl">—</span>
    <span>incl.</span><span class="pval" id="p-incl">—</span>
    <span class="pdelta" id="p-delta" style="display:none"></span>
  </div>

  <div class="summary" id="sum-today"></div>
  <div class="summary" id="sum-yesterday" style="display:none"></div>
  <div class="summary" id="sum-tomorrow" style="display:none"></div>

  <div class="legend">
    <div class="legend-grid">
      <div class="legend-row">
        <div class="legend-blocks">
          <div class="legend-block" style="background:#4488ee;opacity:1"></div>
          <div class="legend-block" style="background:#CD8840;opacity:0.15"></div>
          <div class="legend-block" style="background:#A0A8B0;opacity:0.15"></div>
          <div class="legend-block" style="background:#FFD700;opacity:0.15"></div>
        </div>4 goedkoopste uren
      </div>
      <div class="legend-row">
        <div class="legend-blocks">
          <div class="legend-block" style="background:#4488ee;opacity:0.15"></div>
          <div class="legend-block" style="background:#CD8840;opacity:1"></div>
          <div class="legend-block" style="background:#A0A8B0;opacity:0.15"></div>
          <div class="legend-block" style="background:#FFD700;opacity:0.15"></div>
        </div>3 goedkoopste uren
      </div>
      <div class="legend-row">
        <div class="legend-blocks">
          <div class="legend-block" style="background:#4488ee;opacity:0.15"></div>
          <div class="legend-block" style="background:#CD8840;opacity:0.15"></div>
          <div class="legend-block" style="background:#A0A8B0;opacity:1"></div>
          <div class="legend-block" style="background:#FFD700;opacity:0.15"></div>
        </div>2 goedkoopste uren
      </div>
      <div class="legend-row">
        <div class="legend-blocks">
          <div class="legend-block" style="background:#4488ee;opacity:0.15"></div>
          <div class="legend-block" style="background:#CD8840;opacity:0.15"></div>
          <div class="legend-block" style="background:#A0A8B0;opacity:0.15"></div>
          <div class="legend-block" style="background:#FFD700;opacity:1"></div>
        </div>Goedkoopste uur ✨
      </div>
    </div>
    <div class="legend-divider"></div>
    <div class="legend-inline" id="legend-plan"></div>
    <div class="legend-row" id="neg-legend" style="display:none;margin-top:3px">
      <div style="width:16px;height:8px;background:#00c8f0;border-radius:2px;flex-shrink:0;margin-right:3px"></div>
      Negatief (terugverdienen)
    </div>
    <div class="legend-divider"></div>
    <div class="legend-inline">
      <div class="legend-row">
        <div style="width:22px;height:3px;border-radius:2px;background:linear-gradient(90deg,rgba(160,210,40,0.5),rgba(210,255,50,0.95))"></div>PV werkelijk
      </div>
      <div class="legend-row">
        <div style="width:22px;height:3px;border-radius:2px;background:repeating-linear-gradient(90deg,rgba(200,255,80,0.5) 0px,rgba(200,255,80,0.5) 3px,transparent 3px,transparent 6px)"></div>PV verwacht
      </div>
    </div>
  </div>

  <!-- Opbouw toggle -->
  <div class="opbouw-row">
    <div class="opbouw-left">
      <div class="oleg"><div class="oleg-dot" style="background:#5599ff"></div>EPEX inkoop</div>
      <div class="oleg"><div class="oleg-dot" style="background:#CD8840"></div>Energiebelasting</div>
      <div class="oleg"><div class="oleg-dot" style="background:#A0A8B0"></div>Netkosten</div>
      <div class="oleg"><div class="oleg-dot" style="background:#5ab85a"></div>BTW</div>
    </div>
    <div class="toggle" id="opbouw-toggle">
      <div class="sw" id="sw"><div class="knob"></div></div>
      <span class="toggle-lbl">Prijsopbouw</span>
    </div>
  </div>

  <div class="rows" id="rows-today"></div>
  <div class="rows" id="rows-yesterday" style="display:none"></div>
  <div class="rows" id="rows-tomorrow" style="display:none"></div>
</div>

<div class="tt-wrap" id="tt"></div>
`;

// Vaste belastingcomponenten NL (indicatief, gebruikt voor prijsopbouw visualisatie)
const _EB  = 0.1226;
const _ODE = 0.0024;
const _NET = 0.038;
const _BTW = 0.09;

class CloudemsPrijsverloopCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.appendChild(TPL.content.cloneNode(true));
    this._day = 'today';
    this._lastHash = '';
    this._showOpbouw = false;
    try { this._showOpbouw = localStorage.getItem('cloudems_prijsopbouw') === '1'; } catch(e) {}

    this.shadowRoot.querySelectorAll('.tab').forEach(t => {
      t.addEventListener('click', () => {
        if (t.classList.contains('disabled')) return;
        this._switchDay(t.dataset.day);
      });
    });

    this.shadowRoot.getElementById('opbouw-toggle').addEventListener('click', () => {
      this._showOpbouw = !this._showOpbouw;
      this.shadowRoot.getElementById('sw').classList.toggle('on', this._showOpbouw);
      this.shadowRoot.querySelectorAll('.bd-wrap').forEach(el => el.classList.toggle('show', this._showOpbouw));
      try { localStorage.setItem('cloudems_prijsopbouw', this._showOpbouw ? '1' : '0'); } catch(e) {}
    });

    this.shadowRoot.getElementById('sw').classList.toggle('on', this._showOpbouw);
  }

  setConfig(config) { this._config = config || {}; }
  getCardSize() { return 8; }

  set hass(hass) {
    this._hass = hass;
    const hash = this._buildHash(hass);
    if (hash === this._lastHash) return;
    this._lastHash = hash;
    this._render(hass);
  }

  _buildHash(hass) {
    const ep = hass.states['sensor.cloudems_energy_epex_today'];
    const bat = hass.states['sensor.cloudems_batterij_epex_schema'];
    const prices = ep?.attributes?.today_prices || [];
    const currentHour = new Date().getHours();
    return [
      prices.length,
      prices[currentHour]?.price || '',
      ep?.attributes?.tomorrow_available,
      (ep?.attributes?.yesterday_prices || []).length,
      bat?.attributes?.schedule_summary || bat?.state,
      currentHour,
    ].join('|');
  }

  _totalPrice(epex) {
    return (epex + _EB + _ODE + _NET) * (1 + _BTW);
  }

  _render(hass) {
    const ep   = hass.states['sensor.cloudems_energy_epex_today'];
    const bat  = hass.states['sensor.cloudems_batterij_epex_schema'];
    const sol  = hass.states['sensor.cloudems_solar_system'];
    const ev   = hass.states['sensor.cloudems_ev_session'];

    if (!ep) return;

    const attr      = ep.attributes;
    const today     = attr.today_prices     || [];
    const tomorrow  = attr.tomorrow_prices  || [];
    const yesterday = attr.yesterday_prices || [];
    const tAvail    = attr.tomorrow_available || false;
    const yAvail    = yesterday.length > 0;

    // Modules
    const modBat  = hass.states['switch.cloudems_module_accu']?.state === 'on';
    const modEV   = hass.states['switch.cloudems_module_ev']?.state === 'on';
    const modBoil = hass.states['switch.cloudems_module_ketel']?.state === 'on';
    const modPool = hass.states['switch.cloudems_module_zwembad']?.state === 'on';

    // Battery planning
    const chargeHours    = (bat?.attributes?.charge_hours    || []).map(Number);
    const dischargeHours = (bat?.attributes?.discharge_hours || []).map(Number);

    // Solar forecast
    const solarHourly = sol?.attributes?.hourly || [];
    const solarByHour = {};
    solarHourly.forEach(h => {
      solarByHour[h.hour] = (solarByHour[h.hour] || 0) + (h.forecast_w || 0);
    });
    const maxSolar = Math.max(500, ...Object.values(solarByHour));

    // EV + boiler
    const evOptStart = ev?.attributes?.optimal_start != null ? parseInt(ev.attributes.optimal_start) : -1;
    const boilerTrigger = (() => {
      const bp = hass.states['sensor.cloudems_boiler_planning'];
      if (!bp?.attributes?.trigger_om) return -1;
      return parseInt(bp.attributes.trigger_om.split(':')[0]);
    })();

    const nowH = new Date().getHours();

    // Excl/incl/delta voor huidig uur
    // today_prices bevat all-in prices, today_prices_excl_tax bevat kale EPEX
    const _todayExcl = (attr.today_prices_excl_tax || attr.today_prices || []);
    const _slotExcl  = _todayExcl.find(s => s.hour === nowH);
    const curExcl = attr.price_excl_tax ?? (_slotExcl?.price ?? null);
    const curIncl = attr.current_price_display ?? attr.price_incl_tax ?? null;
    const pExcl  = this.shadowRoot.getElementById('p-excl');
    const pIncl  = this.shadowRoot.getElementById('p-incl');
    const pDelta = this.shadowRoot.getElementById('p-delta');
    if (pExcl) pExcl.textContent = curExcl != null ? '€' + parseFloat(curExcl).toFixed(3) : '—';
    if (pIncl) pIncl.textContent = curIncl != null ? '€' + parseFloat(curIncl).toFixed(3) : '—';
    if (pDelta && curExcl != null && curIncl != null) {
      const delta = parseFloat(curIncl) - parseFloat(curExcl);
      pDelta.textContent = (delta >= 0 ? '+' : '') + '€' + delta.toFixed(3);
      pDelta.style.display = '';
    }

    // Tabs
    const tabYest = this.shadowRoot.getElementById('tab-yest');
    const tabTmr  = this.shadowRoot.getElementById('tab-tmr');
    if (tabYest) {
      tabYest.classList.toggle('disabled', !yAvail);
      tabYest.classList.toggle('past', yAvail);
    }
    if (tabTmr) tabTmr.textContent = tAvail ? 'Morgen ✓' : 'Morgen';

    // Legend plan
    const legendPlan = this.shadowRoot.getElementById('legend-plan');
    if (legendPlan) {
      const items = [];
      if (modBat)  items.push(`<div class="legend-row"><span style="color:#aaddff">▲</span>/<span style="color:#ff8040">▼</span> Accu</div>`);
      if (modEV)   items.push(`<div class="legend-row">🔌 EV</div>`);
      if (modBoil) items.push(`<div class="legend-row">🔥 Boiler</div>`);
      if (modPool) items.push(`<div class="legend-row">🏊 Pool</div>`);
      items.push(`<div class="legend-row"><span style="color:#ffd700">☀</span> PV surplus</div>`);
      legendPlan.innerHTML = items.join('');
    }

    const planOpts  = { chargeHours, dischargeHours, solarByHour, maxSolar, evOptStart, boilerTrigger, modBat, modEV, modBoil, modPool, nowH };
    const emptyOpts = { chargeHours:[], dischargeHours:[], solarByHour:{}, maxSolar:500, evOptStart:-1, boilerTrigger:-1, modBat:false, modEV:false, modBoil:false, modPool:false, nowH:-1 };

    this._buildRows('today',     today,     'today',     planOpts);
    this._buildRows('tomorrow',  tomorrow,  'tomorrow',  emptyOpts);
    this._buildRows('yesterday', yesterday, 'yesterday', emptyOpts);

    this._buildSummary('today',     today,     attr);
    this._buildSummary('tomorrow',  tomorrow,  null);
    this._buildSummary('yesterday', yesterday, null);
  }

  _bestBlock(prices, n) {
    let best = 0, bestAvg = Infinity;
    for (let i = 0; i <= prices.length - n; i++) {
      const avg = prices.slice(i, i+n).reduce((s,p) => s+p, 0) / n;
      if (avg < bestAvg) { bestAvg = avg; best = i; }
    }
    return best;
  }

  _barColor(norm) {
    if (norm < 0.33) return `rgb(${Math.round(norm/0.33*190)},200,50)`;
    if (norm < 0.66) { const tt=(norm-0.33)/0.33; return `rgb(${Math.round(190+tt*40)},${Math.round(200-tt*60)},50)`; }
    const tt=(norm-0.66)/0.34; return `rgb(230,${Math.round(140-tt*110)},50)`;
  }

  _buildSummary(id, slots, attr) {
    const el = this.shadowRoot.getElementById('sum-' + id);
    if (!el || !slots.length) return;
    const prices = slots.map(s => s.price);
    const avg = (prices.reduce((a,b) => a+b, 0) / prices.length).toFixed(4);
    const sorted = [...slots].sort((a,b) => a.price - b.price);
    const ct = v => (parseFloat(v)*100).toFixed(1);
    el.innerHTML = `
      <span>gem. <strong>${ct(avg)} ct</strong></span>
      <span>💚 <strong>${String(sorted[0].hour).padStart(2,'0')}:00</strong> ${ct(sorted[0].price)} ct</span>
      <span>🔴 <strong>${String(sorted[sorted.length-1].hour).padStart(2,'0')}:00</strong> ${ct(sorted[sorted.length-1].price)} ct</span>
      ${attr?.prev_hour_price != null ? `<span>Vorig uur: ${ct(attr.prev_hour_price)} ct</span>` : ''}
    `;
  }

  _buildRows(dayId, slots, dayType, opts) {
    const container = this.shadowRoot.getElementById('rows-' + dayId);
    if (!container || !slots.length) { if (container) container.innerHTML = ''; return; }

    const { chargeHours, dischargeHours, solarByHour, maxSolar, evOptStart, boilerTrigger, modBat, modEV, modBoil, modPool, nowH } = opts;
    const prices   = slots.map(s => s.price);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const avgPrice = prices.reduce((a,b) => a+b, 0) / prices.length;
    const totalRange = maxPrice - minPrice || 0.001;
    const hasNeg = minPrice < 0;

    // Zero-lijn positie (% vanaf links van bar-track)
    const zeroPct = hasNeg ? (-minPrice / totalRange * 100) : 0;

    // Negatief legend tonen/verbergen
    const negLeg = this.shadowRoot.getElementById('neg-legend');
    if (negLeg) negLeg.style.display = hasNeg ? '' : 'none';

    // Card class voor zero-lijn CSS
    const card = this.shadowRoot.getElementById('card');
    if (card) card.classList.toggle('has-negative', hasNeg);

    const b4s = this._bestBlock(prices, 4);
    const b3s = this._bestBlock(prices, 3);
    const b2s = this._bestBlock(prices, 2);
    const cheapIdx = prices.indexOf(minPrice);
    const expIdx   = prices.indexOf(maxPrice);

    container.innerHTML = '';
    const barEls = [], pvAEls = [], pvFEls = [];

    slots.forEach((slot, idx) => {
      const hour  = slot.hour;
      const price = slot.price;
      const isNeg     = price < 0;
      const isCurrent = dayType === 'today' && hour === nowH;
      const isExp     = idx === expIdx;
      const in4 = idx >= b4s && idx < b4s+4;
      const in3 = idx >= b3s && idx < b3s+3;
      const in2 = idx >= b2s && idx < b2s+2;
      const in1 = idx === cheapIdx;

      // Balk: alle waarden schalen op totalRange zodat balken nooit over prijskolom gaan
      // zeroPct = positie van nul (% van links)
      // Positief: start op zeroPct, breedte = (price/totalRange)*100*(1-zeroPct/100) → geclipped rechts
      // Negatief: eindigt op zeroPct, groeit naar links
      let barLeft, barWidth, barBg, barRadius;
      if (isNeg) {
        barWidth  = Math.min(zeroPct, Math.abs(price) / totalRange * 100);
        barLeft   = zeroPct - barWidth;
        barBg     = '#00c8f0';
        barRadius = '3px 0 0 3px';
      } else {
        // Zonder negatieven: schaal op maxPrice (duurste = 100%) anders over de rand
        barWidth  = Math.min(100, hasNeg ? (price / totalRange * 100) : (price / maxPrice * 100));
        barLeft   = zeroPct;
        const norm = (price - Math.max(0, minPrice)) / (maxPrice - Math.max(0, minPrice) || 0.001);
        barBg = isExp ? 'rgb(220,80,50)' : isCurrent ? '#00d14e' : this._barColor(norm);
        barRadius = hasNeg ? '0 3px 3px 0' : '3px';
      }

      // Planning icons
      const hasBatCharge = modBat && chargeHours.includes(hour);
      const hasBatDisch  = modBat && dischargeHours.includes(hour);
      const hasEV        = modEV  && hour === evOptStart;
      const hasBoiler    = modBoil && hour === boilerTrigger;
      const hasPool      = modPool && hour >= nowH && hour < nowH+3;
      const pvW          = solarByHour[hour] || 0;
      const hasSurplus   = pvW > 500;
      const isCharging   = chargeHours.includes(hour);

      // PV bars (alleen voor today)
      const pvActPct = (dayType === 'today' && hour < nowH) ? Math.min(100, (pvW/maxSolar)*100) : 0;
      const pvFcPct  = ((dayType === 'today' && hour >= nowH) || dayType === 'tomorrow') ? Math.min(100, (pvW/maxSolar)*100) : 0;

      // Prijskleur label
      const priceColor = isNeg ? '#00c8f0' : isExp ? '#ff6040' : in1 ? '#FFD700' : in2 ? '#B0B8C0' : in3 ? '#CD8840' : in4 ? '#5599ee' : '#fff';
      const priceStr   = (isNeg ? '-' : '') + '€' + Math.abs(price).toFixed(3);

      // Opbouw: price = all-in display prijs, epexRaw = kale EPEX uit slot
      const totalIncl = price;  // price is al de all-in display prijs
      const epexRaw   = slot.price_excl_tax ?? (price / (1 + _BTW) - _EB - _ODE - _NET);
      const absT = Math.abs(totalIncl) || 0.001;
      const ebV   = _EB   * (1 + _BTW);
      const netV  = (_NET + _ODE) * (1 + _BTW);
      const epexV = epexRaw * (1 + _BTW);
      const btwV  = totalIncl - (epexRaw + _EB + _ODE + _NET);
      const epexPct = Math.abs(epexV) / absT * 100;
      const ebPct   = ebV / absT * 100;
      const netPct  = netV / absT * 100;
      const btwPct  = Math.max(0, Math.abs(btwV) / absT * 100);

      const row = document.createElement('div');
      row.className = 'row' + (isCurrent ? ' current' : '');
      row.innerHTML = `
        <div class="block-strips">
          <div class="strip s4${in4 ? ' on' : ''}"></div>
          <div class="strip s3${in3 ? ' on' : ''}"></div>
          <div class="strip s2${in2 ? ' on' : ''}"></div>
          <div class="strip s1${in1 ? ' on' : ''}"></div>
        </div>
        <div class="row-hour">${String(hour).padStart(2,'0')}:00</div>
        <div class="row-icons">
          <span class="ico" style="color:${hasBatCharge?'#aaddff':hasBatDisch?'#ff8040':'transparent'}">${hasBatCharge?'▲':hasBatDisch?'▼':'▲'}</span>
          <span class="ico">${hasEV?'🔌':''}</span>
          <span class="ico">${hasBoiler?'🔥':''}</span>
          <span class="ico">${hasPool?'🏊':''}</span>
          <span class="ico" style="color:${hasSurplus?'#ffd700':'transparent'}">☀</span>
        </div>
        <div class="bar-col">
          <div class="bar-area">
            <div class="bar-track"></div>
            <div class="zero-line" style="left:${zeroPct.toFixed(1)}%"></div>
            <div class="bar-fill${in1 && !isNeg ? ' rank1' : ''}${isCharging ? ' charging' : ''}"
              id="bf-${dayId}-${idx}"
              style="left:${barLeft.toFixed(1)}%;width:0%;background:${barBg};border-radius:${barRadius}"
              data-w="${barWidth.toFixed(2)}">
            </div>
            <div class="pv-wrap">
              <div class="pv-actual" data-pct="${pvActPct.toFixed(1)}"></div>
              <div class="pv-forecast" data-pct="${pvFcPct.toFixed(1)}"></div>
            </div>
          </div>
          <div class="bd-wrap${this._showOpbouw ? ' show' : ''}" id="bd-${dayId}-${idx}">
            <div class="bd-bar" style="left:${barLeft.toFixed(1)}%;width:${barWidth.toFixed(1)}%">
              <div class="seg" style="width:${epexPct.toFixed(1)}%;background:${isNeg?'#00c8f0':'#5599ff'}"></div>
              <div class="seg" style="width:${ebPct.toFixed(1)}%;background:#CD8840"></div>
              <div class="seg" style="width:${netPct.toFixed(1)}%;background:#A0A8B0"></div>
              <div class="seg" style="width:${btwPct.toFixed(1)}%;background:#5ab85a"></div>
            </div>
          </div>
        </div>
        <div class="row-price" style="color:${priceColor}">${priceStr}</div>
      `;

      // Tooltip
      const tt = this.shadowRoot.getElementById('tt');
      const fmt = v => (v >= 0 ? '€' : '-€') + Math.abs(v).toFixed(4);
      row.addEventListener('mouseenter', () => {
        tt.innerHTML = `
          <div class="tt-r"><div class="tt-d" style="background:${isNeg?'#00c8f0':'#5599ff'}"></div><span class="tt-l">EPEX inkoop</span><span class="tt-v">${fmt(epexV)}</span></div>
          <div class="tt-r"><div class="tt-d" style="background:#CD8840"></div><span class="tt-l">Energiebelasting</span><span class="tt-v">${fmt(ebV)}</span></div>
          <div class="tt-r"><div class="tt-d" style="background:#A0A8B0"></div><span class="tt-l">Netkosten + ODE</span><span class="tt-v">${fmt(netV)}</span></div>
          <div class="tt-r"><div class="tt-d" style="background:#5ab85a"></div><span class="tt-l">BTW (9%)</span><span class="tt-v">${fmt(btwV)}</span></div>
          <div class="tt-tot"><span>Totaal incl.</span><span>${fmt(totalIncl)}</span></div>
        `;
        tt.style.display = 'block';
      });
      row.addEventListener('mousemove', ev => {
        const x = ev.clientX + 12, y = ev.clientY - 10;
        tt.style.left = (x + tt.offsetWidth > window.innerWidth ? x - tt.offsetWidth - 24 : x) + 'px';
        tt.style.top = y + 'px';
      });
      row.addEventListener('mouseleave', () => { tt.style.display = 'none'; });

      container.appendChild(row);
      barEls.push(this.shadowRoot.getElementById('bf-' + dayId + '-' + idx));
      pvAEls.push(row.querySelector('.pv-actual'));
      pvFEls.push(row.querySelector('.pv-forecast'));
    });

    // Animeer balken
    barEls.forEach((el, i) => setTimeout(() => { if (el) el.style.width = el.dataset.w + '%'; }, i * 22));
    pvAEls.forEach((el, i) => setTimeout(() => { if (el) el.style.width = el.dataset.pct + '%'; }, i * 22 + 350));
    pvFEls.forEach((el, i) => setTimeout(() => { if (el) el.style.width = el.dataset.pct + '%'; }, i * 22 + 350));
  }

  _switchDay(day) {
    this._day = day;
    this.shadowRoot.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.day === day));

    // Toon/verberg rows + summary
    ['today', 'yesterday', 'tomorrow'].forEach(d => {
      this.shadowRoot.getElementById('rows-' + d).style.display   = d === day ? '' : 'none';
      this.shadowRoot.getElementById('sum-' + d).style.display    = d === day ? '' : 'none';
    });

    // Excl/incl balk alleen op vandaag
    const pb = this.shadowRoot.getElementById('price-bar');
    if (pb) pb.style.display = day === 'today' ? '' : 'none';

    // Re-animeer
    const rows = this.shadowRoot.getElementById('rows-' + day);
    rows.querySelectorAll('.bar-fill').forEach((el, i) => {
      el.style.transition = 'none'; el.style.width = '0%';
      setTimeout(() => {
        el.style.transition = 'width 0.45s cubic-bezier(0.25,0.46,0.45,0.94)';
        el.style.width = el.dataset.w + '%';
      }, (i % 24) * 22 + 20);
    });
    rows.querySelectorAll('.pv-actual,.pv-forecast').forEach((el, i) => {
      el.style.transition = 'none'; el.style.width = '0%';
      setTimeout(() => {
        el.style.transition = 'width 0.6s ease';
        el.style.width = el.dataset.pct + '%';
      }, (i % 24) * 22 + 400);
    });
  }

  static getConfigElement() {
    const el = document.createElement('cloudems-prijsverloop-card-editor');
    return el;
  }
  static getStubConfig() { return {}; }
}

customElements.define('cloudems-prijsverloop-card', CloudemsPrijsverloopCard);

// GUI Editor
class CloudemsPrijsverloopCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; }
  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `<p style="padding:8px;font-size:12px;color:#aaa">Geen configuratie vereist — kaart leest automatisch de juiste CloudEMS sensoren.</p>`;
    }
  }
}
customElements.define('cloudems-prijsverloop-card-editor', CloudemsPrijsverloopCardEditor);
