// CloudEMS Batterij Arbitrage Card v1.0.0
const CARD_BATTERIJ_ARBITRAGE_VERSION = '5.3.31';
// Shows battery savings breakdown: eigenverbruik, arbitrage, PV zelfconsumptie

class CloudemsBatterijArbitrageCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "💰 Batterij Besparingen", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_battery_savings"];
    if (JSON.stringify(s?.last_changed) !== this._p) {
      this._p = JSON.stringify(s?.last_changed);
      this._r();
    }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const st   = h.states["sensor.cloudems_battery_savings"];
    const a    = st?.attributes || {};
    const soc  = parseFloat(h.states["sensor.cloudems_battery_so_c"]?.state || 0);

    // Vandaag
    const todayTotal  = parseFloat(a.savings_today_eur || 0);
    const todayEV     = parseFloat(a.eigenverbruik_today_eur || 0);
    const todayArb    = parseFloat(a.arbitrage_today_eur || 0);
    const todayPV     = parseFloat(a.pv_selfconsumption_today_eur || 0);
    const todayLoss   = parseFloat(a.saldering_loss_today_eur || 0);
    const kwhIn       = parseFloat(a.kwh_charged_today || 0);
    const kwhOut      = parseFloat(a.kwh_discharged_today || 0);
    const sessToday   = parseInt(a.sessions_today || 0);

    // Dit jaar
    const yearTotal   = parseFloat(a.savings_year_eur || 0);
    const yearEV      = parseFloat(a.eigenverbruik_year_eur || 0);
    const yearArb     = parseFloat(a.arbitrage_year_eur || 0);
    const yearPV      = parseFloat(a.pv_selfconsumption_year_eur || 0);
    const yearLoss    = parseFloat(a.saldering_loss_year_eur || 0);
    const sessYear    = parseInt(a.sessions_year || 0);
    const saldPct     = parseInt(a.saldering_pct || 0);
    const history     = a.history_years || [];

    const fmt = (v) => v >= 0 ? `€${v.toFixed(2)}` : `-€${Math.abs(v).toFixed(2)}`;
    const fmtSmall = (v) => v >= 0 ? `€${v.toFixed(3)}` : `-€${Math.abs(v).toFixed(3)}`;
    const col = (v) => v > 0 ? '#4ade80' : v < 0 ? '#f87171' : '#94a3b8';

    const barRow = (label, val, max, color, icon) => {
      const pct = max > 0 ? Math.min(100, Math.abs(val) / max * 100) : 0;
      return `<div style="margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px">
          <span style="color:rgba(163,163,163,.7)">${icon} ${label}</span>
          <span style="font-weight:600;color:${color}">${fmtSmall(val)}</span>
        </div>
        <div style="height:4px;background:rgba(255,255,255,.08);border-radius:2px">
          <div style="height:4px;background:${color};border-radius:2px;width:${pct.toFixed(1)}%;transition:width .4s"></div>
        </div>
      </div>`;
    };

    const maxToday = Math.max(todayEV, todayArb, todayPV, 0.001);

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.hero{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}
.hero-item{padding:12px 16px;text-align:center}
.hero-val{font-size:22px;font-weight:700}
.hero-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
.section{padding:10px 16px 8px}
.section-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;margin-bottom:8px}
.stat-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px}
.stat-lbl{color:rgba(163,163,163,.7)}
.hist-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.hist-year{font-size:11px;font-weight:600;color:#fff;min-width:36px}
.hist-bar-wrap{flex:1;height:6px;background:rgba(255,255,255,.08);border-radius:3px}
.hist-bar{height:6px;border-radius:3px;background:#4ade80;transition:width .4s}
.hist-val{font-size:11px;font-weight:600;color:#4ade80;min-width:44px;text-align:right}
.footer{padding:8px 16px;border-top:1px solid rgba(255,255,255,.06);font-size:10px;color:rgba(100,100,110,.6);display:flex;justify-content:space-between}
</style>
<div class="card">
  <div class="hdr">
    <span>💰</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:10px;color:rgba(163,163,163,.4)">Saldering ${saldPct}%</span>
  </div>

  <div class="hero">
    <div class="hero-item">
      <div class="hero-val" style="color:${col(todayTotal)}">${fmt(todayTotal)}</div>
      <div class="hero-lbl">💰 Vandaag</div>
    </div>
    <div class="hero-item">
      <div class="hero-val" style="color:${col(yearTotal)}">${fmt(yearTotal)}</div>
      <div class="hero-lbl">📅 Dit jaar</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Vandaag uitgesplitst</div>
    ${barRow("Eigenverbruik", todayEV, maxToday, "#60a5fa", "🏠")}
    ${barRow("Prijs-arbitrage", todayArb, maxToday, "#fbbf24", "📈")}
    ${barRow("PV zelfconsumptie", todayPV, maxToday, "#fb923c", "☀️")}
    ${todayLoss > 0 ? barRow("Salderings­verlies", -todayLoss, maxToday, "#f87171", "📉") : ""}
    <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;text-align:center">
      <div style="padding:6px;background:rgba(255,255,255,.04);border-radius:8px">
        <div style="font-size:13px;font-weight:600;color:#60a5fa">${kwhIn.toFixed(1)}</div>
        <div style="font-size:9px;color:rgba(163,163,163,.5)">kWh geladen</div>
      </div>
      <div style="padding:6px;background:rgba(255,255,255,.04);border-radius:8px">
        <div style="font-size:13px;font-weight:600;color:#fb923c">${kwhOut.toFixed(1)}</div>
        <div style="font-size:9px;color:rgba(163,163,163,.5)">kWh ontladen</div>
      </div>
      <div style="padding:6px;background:rgba(255,255,255,.04);border-radius:8px">
        <div style="font-size:13px;font-weight:600;color:#94a3b8">${sessToday}</div>
        <div style="font-size:9px;color:rgba(163,163,163,.5)">cycli vandaag</div>
      </div>
    </div>
  </div>

  ${history.length > 0 ? `
  <div class="section">
    <div class="section-title">Historisch</div>
    ${(() => {
      const maxH = Math.max(...history.map(y => y.total_eur), 0.001);
      return history.slice(0, 4).map(y => `
        <div class="hist-row">
          <span class="hist-year">${y.year}</span>
          <div class="hist-bar-wrap">
            <div class="hist-bar" style="width:${Math.min(100, y.total_eur/maxH*100).toFixed(1)}%"></div>
          </div>
          <span class="hist-val">€${y.total_eur.toFixed(0)}</span>
        </div>`).join('');
    })()}
  </div>` : ""}

  <div class="footer">
    <span>${sessYear} cycli dit jaar</span>
    <span>SOC ${soc.toFixed(0)}%</span>
  </div>
</div>`;
  }
  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-batterij-arbitrage-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsBatterijArbitrageCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'💰 Batterij Besparingen'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-batterij-arbitrage-card')) customElements.define("cloudems-batterij-arbitrage-card", CloudemsBatterijArbitrageCard);
if (!customElements.get('cloudems-batterij-arbitrage-card-editor')) customElements.define("cloudems-batterij-arbitrage-card-editor", CloudemsBatterijArbitrageCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-batterij-arbitrage-card", name: "CloudEMS Batterij Besparingen" });
