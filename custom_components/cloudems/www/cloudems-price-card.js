/**
 * CloudEMS Price Card — cloudems-price-card
 * Vervangt: 💶 Uurprijzen + 📊 Prijsverloop + 🕐 Goedkoopste uren
 *
 * Sensoren:
 *   sensor.cloudems_energy_epex_today  → today_prices, tomorrow_prices, cheapest_2h_start,
 *                                        cheapest_3h_start, cheapest_4h_start,
 *                                        avg_today, min_today, max_today,
 *                                        prev_hour_price, current_price_display
 *   sensor.cloudems_batterij_epex_schema → charge_hours, discharge_hours
 *   sensor.cloudems_solar_system        → hourly[].hour, hourly[].forecast_w
 *   sensor.cloudems_ev_session          → optimal_start (hour int)
 *   sensor.cloudems_boiler_planning     → trigger_om (HH:MM string)
 *   sensor.cloudems_pool_water_temp     → state (aanwezig = pool actief)
 *   switch.cloudems_module_accu         → state (on/off)
 *   switch.cloudems_module_ev           → state (on/off)
 *   switch.cloudems_module_ketel        → state (on/off)
 *   switch.cloudems_module_zwembad      → state (on/off)
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
  .hdr {
    padding: 13px 16px 9px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    display: flex; align-items: center; justify-content: space-between;
  }
  .hdr-left { display: flex; align-items: center; gap: 8px; }
  .hdr-title { font-size: 14px; font-weight: 700; }
  .price-now { font-size: 11px; color: rgba(255,255,255,0.5); }
  .price-now strong { font-size: 13px; font-weight: 700; color: #fff; }
  .tabs { display: flex; gap: 4px; }
  .tab {
    padding: 3px 10px; border-radius: 9px; font-size: 10px; font-weight: 600;
    cursor: pointer; border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.45); background: transparent; transition: all 0.15s;
  }
  .tab.active { background: rgba(0,177,64,0.15); border-color: rgba(0,177,64,0.35); color: #00d14e; }

  .summary {
    padding: 8px 16px 3px;
    display: flex; gap: 14px; flex-wrap: wrap;
    font-size: 11px; color: rgba(255,255,255,0.45);
  }
  .summary strong { color: rgba(255,255,255,0.9); }

  .legend { padding: 4px 16px 6px; }
  .legend-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 10px; margin-bottom: 4px; }
  .legend-row { display: flex; align-items: center; gap: 5px; font-size: 9px; color: rgba(255,255,255,0.35); }
  .legend-blocks { display: flex; gap: 1px; flex-shrink: 0; }
  .legend-block { width: 3px; height: 12px; border-radius: 2px; }
  .legend-divider { height: 1px; background: rgba(255,255,255,0.06); margin: 3px 0; }
  .legend-inline { display: flex; gap: 10px; flex-wrap: wrap; }

  .rows { padding: 1px 0 6px; }
  .row {
    display: grid;
    grid-template-columns: 16px 40px 50px 1fr 48px;
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

  .bar-area { position: relative; height: 19px; }
  .bar-wrap { position: absolute; top: 1px; left: 0; right: 0; height: 13px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden; }
  .bar { height: 100%; border-radius: 3px; width: 0%; position: relative; overflow: hidden; transition: width 0.45s cubic-bezier(0.25,0.46,0.45,0.94); }
  .bar.rank1::after {
    content: ''; position: absolute; top: 0; left: -100%; width: 70%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.55), transparent);
    animation: wave 2.2s ease-in-out infinite;
  }
  @keyframes wave { 0%{left:-100%} 100%{left:120%} }
  .bar.charging::before {
    content: ''; position: absolute; top: 0; left: -60%; width: 40%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
    animation: shimmer 1s ease-in-out infinite;
  }
  @keyframes shimmer { 0%{left:-60%} 100%{left:110%} }

  .pv-wrap { position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 2px; overflow: hidden; }
  .pv-actual { position: absolute; right: 0; top: 0; bottom: 0; width: 0%; border-radius: 2px; background: linear-gradient(90deg, rgba(160,210,40,0.5), rgba(210,255,50,0.95)); transition: width 0.6s ease; }
  .pv-forecast { position: absolute; right: 0; top: 0; bottom: 0; width: 0%; border-radius: 2px; background: repeating-linear-gradient(90deg, rgba(200,255,80,0.45) 0px, rgba(200,255,80,0.45) 3px, transparent 3px, transparent 6px); transition: width 0.6s ease; }

  .row-price { font-size: 10px; font-weight: 700; text-align: right; }
</style>
<div class="card">
  <div class="hdr">
    <div class="hdr-left">
      <span>📊</span>
      <span class="hdr-title">Prijsverloop</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <div class="price-now" id="price-now"></div>
      <div class="tabs">
        <button class="tab active" data-day="today">Vandaag</button>
        <button class="tab" data-day="tomorrow" id="tab-tmr">Morgen</button>
      </div>
    </div>
  </div>
  <div class="summary" id="sum-today"></div>
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
  <div class="rows" id="rows-today"></div>
  <div class="rows" id="rows-tomorrow" style="display:none"></div>
</div>
`;

class CloudemsPriceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.appendChild(TPL.content.cloneNode(true));
    this._day = 'today';
    this._lastHash = '';
    // Tab click
    this.shadowRoot.querySelectorAll('.tab').forEach(t => {
      t.addEventListener('click', () => this._switchDay(t.dataset.day));
    });
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
    return [
      ep?.last_updated,
      bat?.last_updated,
      new Date().getHours(),
    ].join('|');
  }

  _render(hass) {
    const ep   = hass.states['sensor.cloudems_energy_epex_today'];
    const bat  = hass.states['sensor.cloudems_batterij_epex_schema'];
    const sol  = hass.states['sensor.cloudems_solar_system'];
    const ev   = hass.states['sensor.cloudems_ev_session'];
    const pool = hass.states['sensor.cloudems_pool_water_temp'];

    if (!ep) return;

    const attr = ep.attributes;
    const today    = attr.today_prices    || [];
    const tomorrow = attr.tomorrow_prices || [];
    const tAvail   = attr.tomorrow_available || false;

    // Module flags
    const modBat  = hass.states['switch.cloudems_module_accu']?.state === 'on';
    const modEV   = hass.states['switch.cloudems_module_ev']?.state === 'on';
    const modBoil = hass.states['switch.cloudems_module_ketel']?.state === 'on';
    const modPool = hass.states['switch.cloudems_module_zwembad']?.state === 'on';

    // Battery planning
    const chargeHours    = (bat?.attributes?.charge_hours    || []).map(Number);
    const dischargeHours = (bat?.attributes?.discharge_hours || []).map(Number);

    // Solar forecast hourly
    const solarHourly = sol?.attributes?.hourly || [];
    const solarByHour = {};
    solarHourly.forEach(h => {
      solarByHour[h.hour] = (solarByHour[h.hour] || 0) + (h.forecast_w || 0);
    });
    const maxSolar = Math.max(500, ...Object.values(solarByHour));

    // EV optimal start
    const evOptStart = ev?.attributes?.optimal_start != null ? parseInt(ev.attributes.optimal_start) : -1;

    // Boiler trigger hour
    const boilerTrigger = (() => {
      const bp = hass.states['sensor.cloudems_boiler_planning'];
      if (!bp?.attributes?.trigger_om) return -1;
      return parseInt(bp.attributes.trigger_om.split(':')[0]);
    })();

    // Pool active hours (simple: next 2h after current if pool module on)
    const nowH = new Date().getHours();

    // Current price display
    const curPrice = attr.current_price_display || ep.state;
    const prevPrice = attr.prev_hour_price;
    const priceNowEl = this.shadowRoot.getElementById('price-now');
    if (priceNowEl) {
      const ct = v => v != null ? (parseFloat(v)*100).toFixed(1)+' ct' : '—';
      priceNowEl.innerHTML = `Nu: <strong>${ct(curPrice)}/kWh</strong>`;
    }

    // Tomorrow tab label
    const tabTmr = this.shadowRoot.getElementById('tab-tmr');
    if (tabTmr) tabTmr.textContent = tAvail ? 'Morgen ✓' : 'Morgen';

    // Legend — only show active modules
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

    this._buildRows('today',    today,    hass, { chargeHours, dischargeHours, solarByHour, maxSolar, evOptStart, boilerTrigger, modBat, modEV, modBoil, modPool, nowH });
    this._buildRows('tomorrow', tomorrow, hass, { chargeHours:[], dischargeHours:[], solarByHour:{}, maxSolar, evOptStart:-1, boilerTrigger:-1, modBat, modEV, modBoil, modPool, nowH:-1 });
    this._buildSummary('today',    today,    attr);
    this._buildSummary('tomorrow', tomorrow, null);

    // Extra: bill simulator, kosten, goedkope uren schakelaars
    this._renderExtras(hass, attr);
  }

  _renderExtras(hass, attr) {
    let el = this.shadowRoot.getElementById('price-extras');
    if (!el) {
      el = document.createElement('div');
      el.id = 'price-extras';
      el.style.cssText = 'padding:0 0 4px';
      this.shadowRoot.querySelector('.card')?.appendChild(el);
    }

    const bill = hass.states['sensor.cloudems_bill_simulator'];
    const kv   = hass.states['sensor.cloudems_energie_kosten_verwachting'];
    const ec   = hass.states['sensor.cloudems_energy_cost'];
    const fv   = s => s?.state && s.state !== 'unavailable' ? parseFloat(s.state) : null;
    const billV = bill?.attributes?.projected_month_eur ?? fv(bill);
    const kvV   = fv(kv);
    const ecV   = fv(ec);

    // Goedkope uren schakelaars
    const gus = hass.states['sensor.cloudems_goedkope_uren_schakelaars'];
    const switches = gus?.attributes?.schakelaars || [];

    const css = `<style>
      .p-extra{padding:10px 14px;border-top:1px solid rgba(255,255,255,0.06)}
      .p-extra-row{display:flex;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);gap:8px}
      .p-extra-lbl{font-size:11px;color:rgba(255,255,255,0.45);flex:1}
      .p-extra-val{font-size:12px;font-weight:600;color:rgba(255,255,255,0.85)}
      .p-sub{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:rgba(255,255,255,0.3);padding:8px 0 3px}
    </style>`;

    const costRows = [
      ecV !== null ? `<div class="p-extra-row"><span class="p-extra-lbl">Kosten vandaag</span><span class="p-extra-val">€ ${ecV.toFixed(2)}</span></div>` : '',
      kvV !== null ? `<div class="p-extra-row"><span class="p-extra-lbl">Verwacht vandaag</span><span class="p-extra-val">€ ${kvV.toFixed(2)}</span></div>` : '',
      billV !== null ? `<div class="p-extra-row"><span class="p-extra-lbl">Maandprognose</span><span class="p-extra-val">€ ${parseFloat(billV).toFixed(0)}</span></div>` : '',
    ].filter(Boolean).join('');

    const swRows = switches.slice(0,6).map(s => {
      const on = hass.states[s.entity_id]?.state === 'on';
      const sched = s.schedule ? ` · ${s.schedule}` : '';
      return `<div class="p-extra-row"><span class="p-extra-lbl">${s.name || s.entity_id}${sched}</span><span class="p-extra-val" style="color:${on?'#34d399':'rgba(255,255,255,0.35)'}">${on?'aan':'uit'}</span></div>`;
    }).join('');

    if (!costRows && !swRows) { el.innerHTML = ''; return; }

    el.innerHTML = css + `<div class="p-extra">
      ${costRows ? `<div class="p-sub">Kosten</div>${costRows}` : ''}
      ${swRows ? `<div class="p-sub">Goedkope uren schakelaars</div>${swRows}` : ''}
    </div>`;
  }

  _bestBlock(prices, n) {
    let best = 0, bestAvg = Infinity;
    for (let i = 0; i <= prices.length - n; i++) {
      const avg = prices.slice(i,i+n).reduce((s,p)=>s+p,0)/n;
      if (avg < bestAvg) { bestAvg = avg; best = i; }
    }
    return best;
  }

  _barColor(t) {
    if (t < 0.33) return `rgb(${Math.round(t/0.33*190)},200,50)`;
    if (t < 0.66) { const tt=(t-0.33)/0.33; return `rgb(${Math.round(190+tt*40)},${Math.round(200-tt*60)},50)`; }
    const tt=(t-0.66)/0.34; return `rgb(230,${Math.round(140-tt*110)},50)`;
  }

  _buildSummary(id, slots, attr) {
    const el = this.shadowRoot.getElementById('sum-'+id);
    if (!el || !slots.length) return;
    const prices = slots.map(s => s.price);
    const avg = (prices.reduce((a,b)=>a+b,0)/prices.length).toFixed(4);
    const sorted = [...slots].sort((a,b)=>a.price-b.price);
    const ct = v => (parseFloat(v)*100).toFixed(1);
    el.innerHTML = `
      <span>gem. <strong>${ct(avg)} ct</strong></span>
      <span>💚 <strong>${String(sorted[0].hour).padStart(2,'0')}:00</strong> ${ct(sorted[0].price)} ct</span>
      <span>🔴 <strong>${String(sorted[sorted.length-1].hour).padStart(2,'0')}:00</strong> ${ct(sorted[sorted.length-1].price)} ct</span>
      ${attr?.prev_hour_price != null ? `<span>Vorig uur: ${ct(attr.prev_hour_price)} ct</span>` : ''}
    `;
  }

  _buildRows(dayId, slots, hass, opts) {
    const container = this.shadowRoot.getElementById('rows-'+dayId);
    if (!container || !slots.length) return;

    const { chargeHours, dischargeHours, solarByHour, maxSolar, evOptStart, boilerTrigger, modBat, modEV, modBoil, modPool, nowH } = opts;
    const prices = slots.map(s => s.price);
    const min = Math.min(...prices), max = Math.max(...prices);
    const avg = prices.reduce((a,b)=>a+b,0)/prices.length;
    const range = max - min || 0.001;
    const b4s = this._bestBlock(prices, 4);
    const b3s = this._bestBlock(prices, 3);
    const b2s = this._bestBlock(prices, 2);
    const cheapIdx = prices.indexOf(min);
    const expIdx   = prices.indexOf(max);

    container.innerHTML = '';
    const barEls = [], pvAEls = [], pvFEls = [];

    slots.forEach((slot, idx) => {
      const hour  = slot.hour;
      const price = slot.price;
      const isCurrent = dayId === 'today' && hour === nowH;
      const isExp  = idx === expIdx, isCheap = idx === cheapIdx;
      const in4 = idx>=b4s&&idx<b4s+4, in3=idx>=b3s&&idx<b3s+3;
      const in2 = idx>=b2s&&idx<b2s+2, in1=isCheap;

      const t = (price-min)/range;
      const color = isExp ? 'rgb(220,80,50)' : this._barColor(t);
      const pct = Math.max(4, t*88+12);
      const isCharging = chargeHours.includes(hour);
      const vsAvg = ((price-avg)/avg*100).toFixed(1);

      // Planning
      const hasBatCharge = modBat && chargeHours.includes(hour);
      const hasBatDisch  = modBat && dischargeHours.includes(hour);
      const hasEV        = modEV  && hour === evOptStart;
      const hasBoiler    = modBoil && hour === boilerTrigger;
      const hasPool      = modPool && hour >= nowH && hour < nowH+3;
      const pvW          = solarByHour[hour] || 0;
      const hasSurplus   = pvW > 500;

      // PV bar percentages
      const pvActPct = (dayId === 'today' && hour < nowH) ? Math.min(100,(pvW/maxSolar)*100) : 0;
      const pvFcPct  = (dayId === 'today' && hour >= nowH) || dayId === 'tomorrow' ? Math.min(100,(pvW/maxSolar)*100) : 0;

      // Price color
      const priceColor = isExp?'#ff6040':in1?'#FFD700':in2?'#B0B8C0':in3?'#CD8840':in4?'#5599ee':'#fff';
      const ct = v => (v*100).toFixed(1);

      const row = document.createElement('div');
      row.className = 'row' + (isCurrent ? ' current' : '');
      row.innerHTML = `
        <div class="block-strips">
          <div class="strip s4${in4?' on':''}"></div>
          <div class="strip s3${in3?' on':''}"></div>
          <div class="strip s2${in2?' on':''}"></div>
          <div class="strip s1${in1?' on':''}"></div>
        </div>
        <div class="row-hour">${String(hour).padStart(2,'0')}:00</div>
        <div class="row-icons">
          <span class="ico" style="color:${hasBatCharge?'#aaddff':hasBatDisch?'#ff8040':'transparent'}">${hasBatCharge?'▲':hasBatDisch?'▼':'▲'}</span>
          <span class="ico">${hasEV?'🔌':''}</span>
          <span class="ico">${hasBoiler?'🔥':''}</span>
          <span class="ico">${hasPool?'🏊':''}</span>
          <span class="ico" style="color:${hasSurplus?'#ffd700':'transparent'}">☀</span>
        </div>
        <div class="bar-area">
          <div class="bar-wrap">
            <div class="bar${in1?' rank1':''}${isCharging?' charging':''}" style="background:${color}" data-pct="${pct.toFixed(1)}"></div>
          </div>
          <div class="pv-wrap">
            <div class="pv-actual" data-pct="${pvActPct.toFixed(1)}"></div>
            <div class="pv-forecast" data-pct="${pvFcPct.toFixed(1)}"></div>
          </div>
        </div>
        <div class="row-price" style="color:${priceColor}">${ct(price)}ct</div>
      `;
      container.appendChild(row);
      barEls.push(row.querySelector('.bar'));
      pvAEls.push(row.querySelector('.pv-actual'));
      pvFEls.push(row.querySelector('.pv-forecast'));
    });

    // Animate in
    barEls.forEach((el,i) => setTimeout(() => { el.style.width = el.dataset.pct + '%'; }, i*22));
    pvAEls.forEach((el,i) => setTimeout(() => { el.style.width = el.dataset.pct + '%'; }, i*22+350));
    pvFEls.forEach((el,i) => setTimeout(() => { el.style.width = el.dataset.pct + '%'; }, i*22+350));
  }

  _switchDay(day) {
    this._day = day;
    this.shadowRoot.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.day === day));
    ['today','tomorrow'].forEach(d => {
      this.shadowRoot.getElementById('rows-'+d).style.display = d===day ? '' : 'none';
      this.shadowRoot.getElementById('sum-'+d).style.display  = d===day ? '' : 'none';
    });
    // Re-animate
    const rows = this.shadowRoot.getElementById('rows-'+day);
    rows.querySelectorAll('.bar,.pv-actual,.pv-forecast').forEach((el,i) => {
      el.style.transition = 'none'; el.style.width = '0%';
      setTimeout(() => { el.style.transition = 'width 0.45s cubic-bezier(0.25,0.46,0.45,0.94)'; el.style.width = el.dataset.pct + '%'; }, (i%24)*22+20);
    });
  }
  static getConfigElement() { return document.createElement('cloudems-price-card-editor'); }
  static getStubConfig() { return { title: 'Prijzen & Kosten' }; }
}

customElements.define('cloudems-price-card', CloudemsPriceCard);

if (!customElements.get('cloudems-price-card-editor')) {
  class _cloudems_price_card_editor extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});}
    setConfig(c){this._cfg=c;this._render();}
    _fire(key,val){
      this._cfg={...this._cfg,[key]:val};
      this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));
    }
    _render(){
      const cfg=this._cfg||{};
      this.shadowRoot.innerHTML=`<div style="padding:8px">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0">
          <label style="font-size:12px;color:rgba(255,255,255,0.6)">Titel</label>
          <input type="text" value="${cfg.title||''}" style="background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:6px;color:#fff;padding:4px 8px;font-size:12px;width:180px"
            @input="${e=>this._fire('title',e.target.value)}" />
        </div>
      </div>`;
    }
  }
  customElements.define('cloudems-price-card-editor', _cloudems_price_card_editor);
}
