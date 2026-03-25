// CloudEMS Standby Intelligence Card v1.0.0
const CARD_STANDBY_VERSION = '5.3.31';
// Bundled inefficiency report: always-on, creep, unaccounted power

class CloudemsStandbyCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "💤 Sluimerverbruik", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_standby_intelligence"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_standby_intelligence"]?.attributes || {};
    const score = parseInt(h?.states["sensor.cloudems_standby_intelligence"]?.state || 0);
    const totalW = attr.total_standby_w || 0;
    const costMonth = attr.total_cost_month || 0;
    const alwaysOn = attr.always_on_count || 0;
    const creep = attr.creep_count || 0;
    const unaccounted = attr.unaccounted_w || 0;
    const advice = attr.advice || "";
    const topSavings = attr.top_savings || [];
    const devices = attr.devices || [];

    const scoreCol = score >= 80 ? "#4ade80" : score >= 50 ? "#fb923c" : "#f87171";
    const catIcon = c => c === "always_on" ? "🔌" : c === "creep" ? "📈" : c === "unaccounted" ? "❓" : "✅";
    const catLabel = c => c === "always_on" ? "Altijd aan" : c === "creep" ? "Sluiping" : c === "unaccounted" ? "Onverklaard" : "OK";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .hdr-title{font-size:12px;font-weight:600;letter-spacing:.04em;color:#fff;flex:1}
  .score-wrap{display:flex;align-items:center;gap:12px;padding:14px 16px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .score-num{font-size:36px;font-weight:700;color:${scoreCol};min-width:56px}
  .score-info{flex:1}
  .score-bar{height:6px;background:rgba(255,255,255,.1);border-radius:3px;margin-top:6px}
  .score-fill{height:6px;background:${scoreCol};border-radius:3px;width:${score}%}
  .score-lbl{font-size:13px;font-weight:500;color:#fff}
  .stat-row{display:grid;grid-template-columns:1fr 1fr 1fr;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .stat{padding:10px 16px;text-align:center}
  .stat-val{font-size:16px;font-weight:700;color:#fff}
  .stat-lbl{font-size:10px;color:rgba(163,163,163,.6);margin-top:2px}
  .advice{padding:10px 16px;font-size:12px;color:rgba(163,163,163,.8);font-style:italic;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .section-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);
    text-transform:uppercase;padding:10px 16px 4px}
  .dev{display:flex;align-items:center;gap:8px;padding:8px 16px;
    border-bottom:1px solid rgba(255,255,255,.04)}
  .dev:last-child{border-bottom:none}
  .dev-icon{font-size:14px;min-width:18px}
  .dev-name{flex:1;font-size:12px;color:#fff}
  .dev-cost{font-size:12px;font-weight:600;color:#f87171;text-align:right;min-width:60px}
  .dev-w{font-size:11px;color:rgba(163,163,163,.6);text-align:right}
  .tip{font-size:10px;color:rgba(163,163,163,.5);padding:0 16px 8px;font-style:italic}
  .na{padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr"><span>💤</span><span class="hdr-title">${c.title}</span></div>
  ${!attr.score && attr.score !== 0 ? `<div class="na">Nog geen sluimerdata — loopt na eerste NILM-cyclus</div>` : `
  <div class="score-wrap">
    <div class="score-num">${score}</div>
    <div class="score-info">
      <div class="score-lbl">${score>=80?"Uitstekend":score>=60?"Goed":score>=40?"Matig":"Actie vereist"}</div>
      <div class="score-bar"><div class="score-fill"></div></div>
      <div style="font-size:10px;color:rgba(163,163,163,.5);margin-top:3px">${score}% van 100</div>
    </div>
  </div>
  <div class="stat-row">
    <div class="stat"><div class="stat-val" style="color:#f87171">${Math.round(totalW)} W</div><div class="stat-lbl">Sluimervermogen</div></div>
    <div class="stat"><div class="stat-val" style="color:#fb923c">€${costMonth.toFixed(0)}/mnd</div><div class="stat-lbl">Kosten</div></div>
    <div class="stat"><div class="stat-val" style="color:#60a5fa">${alwaysOn + creep}</div><div class="stat-lbl">Apparaten</div></div>
  </div>
  ${advice ? `<div class="advice">${advice}</div>` : ""}
  ${topSavings.length > 0 ? `
  <div class="section-title">Top besparingen</div>
  ${topSavings.map(d => `
  <div class="dev">
    <span class="dev-icon">${catIcon(d.category)}</span>
    <span class="dev-name">${d.name}</span>
    <span class="dev-w">${Math.round(d.excess_w)}W</span>
    <span class="dev-cost">€${d.cost_month_eur}/mnd</span>
  </div>
  ${d.tip ? `<div class="tip">${d.tip}</div>` : ""}`).join("")}` : ""}
  ${unaccounted > 30 ? `
  <div class="dev" style="border-top:1px solid rgba(255,255,255,.07)">
    <span class="dev-icon">❓</span>
    <span class="dev-name">Onverklaard verbruik</span>
    <span class="dev-w">${Math.round(unaccounted)}W</span>
    <span class="dev-cost" style="color:#6b7280">—</span>
  </div>` : ""}
  `}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-standby-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsStandbyCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "💤 Sluimerverbruik"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-standby-card')) customElements.define("cloudems-standby-card", CloudemsStandbyCard);
if (!customElements.get('cloudems-standby-card-editor')) customElements.define("cloudems-standby-card-editor", CloudemsStandbyCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-standby-card", name: "CloudEMS Standby Intelligence", description: "Sluimerverbruik analyse" });
