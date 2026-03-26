// CloudEMS Lifecycle Arbitrage Card v1.0.0
const CARD_LIFECYCLE_VERSION = '5.4.1';
// Shows whether running appliances is worth the wear cost

class CloudemsLifecycleCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "⚙️ Slijtage Arbitrage", ...c }; this._render(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_lifecycle_arbitrage"];
    const j = JSON.stringify(s?.last_changed);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_lifecycle_arbitrage"]?.attributes || {};
    const price = attr.price || 0;
    const apps = attr.appliances || [];

    const icon = a => a.should_activate ? "✅" : "🚫";
    const col  = a => a.should_activate ? "#4ade80" : "#f87171";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .price-row{display:flex;justify-content:space-between;align-items:center;
    padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.07);
    font-size:11px;color:rgba(163,163,163,.6)}
  .app{padding:10px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .app:last-child{border-bottom:none}
  .app-top{display:flex;align-items:center;gap:8px;margin-bottom:3px}
  .app-name{flex:1;font-size:13px;font-weight:500;color:#fff}
  .app-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px}
  .app-nums{display:flex;gap:16px;font-size:11px;color:rgba(163,163,163,.6)}
  .app-reason{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px;font-style:italic}
  .na{padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr"><span>⚙️</span><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span></div>
  <div class="price-row"><span>Huidige EPEX prijs</span><span style="color:#fbbf24;font-weight:600">€${price.toFixed(3)}/kWh</span></div>
  ${apps.length === 0 ? `<div class="na">Geen slijtagedata beschikbaar</div>` :
    apps.map(a => `
  <div class="app">
    <div class="app-top">
      <span>${icon(a)}</span>
      <span class="app-name">${a.label}</span>
      <span class="app-badge" style="background:${col(a)}22;color:${col(a)}">
        ${a.should_activate ? "Rendabel" : "Niet rendabel"}
      </span>
    </div>
    <div class="app-nums">
      <span>Slijtage: €${(a.wear_eur||0).toFixed(4)}</span>
      <span>Winst: <span style="color:${(a.net_eur||0)>=0?'#4ade80':'#f87171'}">€${(a.net_eur||0).toFixed(4)}</span></span>
      <span>Break-even: €${(a.price_needed||0).toFixed(3)}/kWh</span>
    </div>
    ${a.reason ? `<div class="app-reason">${a.reason}</div>` : ""}
  </div>`).join("")}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-lifecycle-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsLifecycleCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "⚙️ Slijtage Arbitrage"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-lifecycle-card')) customElements.define("cloudems-lifecycle-card", CloudemsLifecycleCard);
if (!customElements.get('cloudems-lifecycle-card-editor')) customElements.define("cloudems-lifecycle-card-editor", CloudemsLifecycleCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-lifecycle-card", name: "CloudEMS Slijtage Arbitrage" });
