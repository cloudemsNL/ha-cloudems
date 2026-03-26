// CloudEMS Piekdagen Kalender Card v1.0.0 — monthly EPEX price calendar
const CARD_PIEKDAGEN_VERSION = '5.4.1';

class CloudemsPiekdagenCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title:"📅 Piekdagen Kalender", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const k = h.states["sensor.cloudems_price_current_hour"]?.state;
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    // Get price history from cost sensor or bill simulator
    const billA = h.states["sensor.cloudems_bill_simulator"]?.attributes || {};
    const dayHistory = billA.daily_history || billA.cost_history || [];
    // Also try decisions history for price data
    const epexA = h.states["sensor.cloudems_energy_epex_today"]?.attributes || {};
    const priceNow = parseFloat(h.states["sensor.cloudems_price_current_hour"]?.state || 0);

    const today = new Date();
    const year  = today.getFullYear();
    const month = today.getMonth();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
    const firstMon = (firstDay + 6) % 7; // 0=Mon

    // Build day data — use history if available, otherwise estimate from known data
    const dayData = {};
    for (const d of dayHistory) {
      if (d.date) {
        const dd = new Date(d.date);
        if (dd.getMonth() === month && dd.getFullYear() === year) {
          dayData[dd.getDate()] = {
            cost: parseFloat(d.cost ?? d.value ?? 0),
            avgPrice: parseFloat(d.avg_price ?? d.price ?? 0),
          };
        }
      }
    }

    // Color based on cost or estimated from price
    const dayColor = (day) => {
      if (day > today.getDate()) return 'rgba(255,255,255,.04)'; // future
      const d = dayData[day];
      if (!d) return 'rgba(255,255,255,.08)'; // no data
      const cost = d.cost || d.avgPrice * 8 || 0; // rough estimate
      if (cost < 0) return '#4ade80';     // earned money (solar export)
      if (cost < 1) return '#86efac';     // very cheap
      if (cost < 2.5) return '#fbbf24';   // moderate
      if (cost < 4) return '#fb923c';     // expensive
      return '#f87171';                   // peak/very expensive
    };

    const DAYS = ['Ma','Di','Wo','Do','Vr','Za','Zo'];
    const MONTHS = ['Januari','Februari','Maart','April','Mei','Juni',
                    'Juli','Augustus','September','Oktober','November','December'];

    // Build calendar grid
    let cells = '';
    // Empty cells before first day
    for (let i = 0; i < firstMon; i++) {
      cells += '<div class="day empty"></div>';
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const isToday = d === today.getDate();
      const col = dayColor(d);
      const dd = dayData[d];
      const isFuture = d > today.getDate();
      cells += `<div class="day${isToday?' today':''}" title="${d} ${MONTHS[month]}${dd?` — €${dd.cost?.toFixed(2)||'—'}`:''}" style="background:${col};opacity:${isFuture?0.3:1}">
        <span class="day-num" style="color:${isToday?'#fff':col==='rgba(255,255,255,.04)'?'rgba(163,163,163,.2)':'rgba(0,0,0,.7)'}">${d}</span>
        ${dd?.cost ? `<span class="day-cost" style="color:rgba(0,0,0,.6)">€${Math.abs(dd.cost).toFixed(0)}</span>` : ''}
      </div>`;
    }

    // Stats
    const knownDays = Object.values(dayData);
    const totalCost = knownDays.reduce((s, d) => s + (d.cost || 0), 0);
    const peakDays  = knownDays.filter(d => d.cost >= 4).length;
    const cheapDays = knownDays.filter(d => d.cost < 0).length;

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.month-title{font-size:13px;font-weight:600;color:#fff;flex:1}
.cal-wrap{padding:10px 14px 12px}
.day-headers{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;margin-bottom:4px}
.day-hdr{font-size:9px;font-weight:600;color:rgba(163,163,163,.4);text-align:center;padding:2px 0}
.days-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.day{border-radius:6px;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;position:relative;min-height:28px}
.day.empty{background:transparent}
.day.today{outline:2px solid rgba(255,255,255,.8);outline-offset:1px}
.day-num{font-size:10px;font-weight:600;line-height:1}
.day-cost{font-size:7px;font-weight:600;line-height:1}
.summary{display:grid;grid-template-columns:1fr 1fr 1fr;border-top:1px solid rgba(255,255,255,.06)}
.sum{padding:8px 0;text-align:center}
.sum-val{font-size:14px;font-weight:700}
.sum-lbl{font-size:9px;color:rgba(163,163,163,.5);margin-top:1px}
.legend{display:flex;gap:8px;padding:8px 14px;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,.06);font-size:9px;color:rgba(163,163,163,.5)}
.leg{display:flex;align-items:center;gap:3px}
.leg-sq{width:8px;height:8px;border-radius:2px}
</style>
<div class="card">
  <div class="hdr">
    <span>📅</span>
    <span class="month-title">${MONTHS[month]} ${year}</span>
    <span style="font-size:11px;color:rgba(163,163,163,.4)">${knownDays.length} dagen</span>
  </div>

  <div class="cal-wrap">
    <div class="day-headers">
      ${DAYS.map(d => `<div class="day-hdr">${d}</div>`).join('')}
    </div>
    <div class="days-grid">${cells}</div>
  </div>

  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${totalCost<0?'#4ade80':totalCost<30?'#fbbf24':'#f87171'}">€${Math.abs(totalCost).toFixed(0)}</div>
      <div class="sum-lbl">${totalCost < 0 ? '💰 Verdiend' : '💸 Kosten'} maand</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#f87171">${peakDays}</div>
      <div class="sum-lbl">🔴 Piekdagen</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#4ade80">${cheapDays}</div>
      <div class="sum-lbl">🟢 Goedkoop</div>
    </div>
  </div>

  <div class="legend">
    <span class="leg"><span class="leg-sq" style="background:#4ade80"></span>Verdiend</span>
    <span class="leg"><span class="leg-sq" style="background:#86efac"></span>&lt;€1</span>
    <span class="leg"><span class="leg-sq" style="background:#fbbf24"></span>€1–2.50</span>
    <span class="leg"><span class="leg-sq" style="background:#fb923c"></span>€2.50–4</span>
    <span class="leg"><span class="leg-sq" style="background:#f87171"></span>&gt;€4 piek</span>
  </div>
</div>`;
  }
  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-piekdagen-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsPiekdagenCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'📅 Piekdagen Kalender'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-piekdagen-card')) customElements.define("cloudems-piekdagen-card", CloudemsPiekdagenCard);
if (!customElements.get('cloudems-piekdagen-card-editor')) customElements.define("cloudems-piekdagen-card-editor", CloudemsPiekdagenCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type:"cloudems-piekdagen-card", name:"CloudEMS Piekdagen Kalender" });
