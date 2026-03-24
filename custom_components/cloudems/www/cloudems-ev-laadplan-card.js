// CloudEMS EV Laadplan Card v1.0.0 — 24h EPEX-based EV + battery charging plan

class CloudemsEvLaadplanCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title:"🚗 EV Laadplan 24u", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const k = JSON.stringify([
      h.states["sensor.cloudems_batterij_epex_schema"]?.last_changed,
      h.states["sensor.cloudems_price_current_hour"]?.state,
    ]);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    const schA    = h.states["sensor.cloudems_batterij_epex_schema"]?.attributes || {};
    const schedule = schA.schedule || schA.today_schedule || [];
    const epexSt  = h.states["sensor.cloudems_energy_epex_today"];
    const prices  = epexSt?.attributes?.prices || epexSt?.attributes?.today || [];
    const soc     = parseFloat(h.states["sensor.cloudems_battery_so_c"]?.state || 0);
    const priceNow = parseFloat(h.states["sensor.cloudems_price_current_hour"]?.state || 0);
    const nowH    = new Date().getHours();

    // Build 24-slot data
    const slots = Array.from({length: 24}, (_, i) => {
      const sch  = schedule.find(s => {
        const h2 = parseInt((s.hour ?? s.time ?? '').toString().split(':')[0]);
        return h2 === i;
      });
      const p = prices.find(p => {
        const h2 = p.hour ?? (p.time ? parseInt(p.time.split(':')[0]) : -1);
        return h2 === i;
      });
      return {
        hour:   i,
        action: (sch?.action || 'idle').toLowerCase(),
        price:  p?.price ?? p?.value ?? null,
        isnow:  i === nowH,
      };
    });

    const validPrices = slots.map(s => s.price).filter(p => p != null);
    const maxP  = validPrices.length ? Math.max(...validPrices) : 0.001;
    const minP  = validPrices.length ? Math.min(...validPrices) : 0;
    const range = Math.max(maxP - minP, 0.001);

    const priceCol = p => {
      if (p == null) return '#374151';
      const norm = (p - minP) / range;
      if (norm < 0.25) return '#4ade80';
      if (norm < 0.55) return '#fbbf24';
      return '#f87171';
    };
    const actCol = a => ({
      charge:    '#60a5fa',
      discharge: '#fb923c',
      idle:      'rgba(255,255,255,.1)',
      hold:      'rgba(255,255,255,.06)',
    })[a] || 'rgba(255,255,255,.06)';

    const chargeSlots  = slots.filter(s => s.action === 'charge').length;
    const cheapCount   = validPrices.filter(p => p <= minP * 1.3).length;
    const cheapestHour = slots.reduce((best, s) =>
      s.price != null && (best == null || s.price < best.price) ? s : best, null);

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.summary{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}
.sum{padding:10px 0;text-align:center}
.sum-val{font-size:16px;font-weight:700}
.sum-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
.chart-wrap{padding:12px 16px 4px}
.chart-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;margin-bottom:6px}
.bars{display:grid;grid-template-columns:repeat(24,1fr);gap:1px;height:52px;align-items:end}
.bar{border-radius:2px 2px 0 0;position:relative;min-height:3px}
.bar.now{outline:2px solid rgba(255,255,255,.6);outline-offset:1px;z-index:2}
.act-row{display:grid;grid-template-columns:repeat(24,1fr);gap:1px;margin-top:2px;height:10px}
.act{border-radius:2px}
.axis{display:flex;justify-content:space-between;padding:2px 0 8px;font-size:8px;color:rgba(163,163,163,.3)}
.legend{display:flex;gap:12px;padding:4px 16px 10px;font-size:10px;color:rgba(163,163,163,.5);border-top:1px solid rgba(255,255,255,.06);flex-wrap:wrap}
.leg{display:flex;align-items:center;gap:4px}
.leg-dot{width:10px;height:10px;border-radius:2px}
.tip{margin:0 16px 12px;padding:8px 12px;background:${cheapestHour ? `rgba(96,165,250,.08)` : 'transparent'};border-radius:8px;font-size:11px;color:rgba(163,163,163,.8);text-align:center}
</style>
<div class="card">
  <div class="hdr">
    <span>🚗</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:11px;color:${priceNow<0.15?'#4ade80':priceNow>0.30?'#f87171':'#fbbf24'}">${(priceNow*100).toFixed(1)} ct</span>
  </div>

  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${soc>80?'#4ade80':soc>40?'#fbbf24':'#f87171'}">${soc.toFixed(0)}%</div>
      <div class="sum-lbl">🔋 Batterij SOC</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#60a5fa">${chargeSlots}u</div>
      <div class="sum-lbl">Laden gepland</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#4ade80">${cheapCount}u</div>
      <div class="sum-lbl">Goedkoop vandaag</div>
    </div>
  </div>

  <div class="chart-wrap">
    <div class="chart-title">EPEX Prijzen + Laadplan</div>
    <div class="bars">
      ${slots.map(s => {
        const pct = s.price != null ? Math.max(8, Math.round((s.price - minP) / range * 44 + 8)) : 8;
        return `<div class="bar${s.isnow?' now':''}"
          style="height:${pct}px;background:${priceCol(s.price)};opacity:${s.isnow?1:0.75}"
          title="${s.hour}:00 ${s.price!=null?(s.price*100).toFixed(1)+'ct':'—'}"></div>`;
      }).join('')}
    </div>
    <div class="act-row">
      ${slots.map(s => `<div class="act" style="background:${actCol(s.action)}" title="${s.hour}:00 ${s.action}"></div>`).join('')}
    </div>
    <div class="axis">
      <span>00</span><span>03</span><span>06</span><span>09</span>
      <span>12</span><span>15</span><span>18</span><span>21</span><span>23</span>
    </div>
  </div>

  ${cheapestHour ? `<div class="tip">
    💡 Goedkoopste uur: <strong>${cheapestHour.hour}:00</strong> — ${(cheapestHour.price*100).toFixed(1)} ct/kWh
    ${cheapestHour.action === 'charge' ? ' ✓ Laden gepland' : ''}
  </div>` : ''}

  <div class="legend">
    <span class="leg"><span class="leg-dot" style="background:#4ade80"></span>Goedkoop</span>
    <span class="leg"><span class="leg-dot" style="background:#fbbf24"></span>Gemiddeld</span>
    <span class="leg"><span class="leg-dot" style="background:#f87171"></span>Duur</span>
    <span class="leg"><span class="leg-dot" style="background:#60a5fa"></span>Laden</span>
    <span class="leg"><span class="leg-dot" style="background:#fb923c"></span>Ontladen</span>
  </div>
</div>`;
  }
  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-ev-laadplan-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsEvLaadplanCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'🚗 EV Laadplan 24u'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-ev-laadplan-card')) customElements.define("cloudems-ev-laadplan-card", CloudemsEvLaadplanCard);
if (!customElements.get('cloudems-ev-laadplan-card-editor')) customElements.define("cloudems-ev-laadplan-card-editor", CloudemsEvLaadplanCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type:"cloudems-ev-laadplan-card", name:"CloudEMS EV Laadplan 24u" });
