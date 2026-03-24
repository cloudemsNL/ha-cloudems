// CloudEMS VvE Energy Split Card v1.0.0

class CloudemsVveCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🏢 VvE Energieverdeling", ...c }; this._render(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_vve"];
    const j = JSON.stringify(s?.last_changed);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_vve"]?.attributes || {};
    const enabled = attr.enabled === true;
    const units = attr.units || [];
    const totalSolar = attr.total_solar_kwh || 0;
    const method = attr.split_method || "equal";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .summary{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px 16px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .sum-item{text-align:center}
  .sum-val{font-size:16px;font-weight:700;color:#fff}
  .sum-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
  .unit{display:flex;align-items:center;gap:8px;padding:10px 16px;
    border-bottom:1px solid rgba(255,255,255,.04)}
  .unit:last-child{border-bottom:none}
  .unit-name{flex:1;font-size:13px;font-weight:500;color:#fff}
  .unit-share{font-size:11px;color:rgba(163,163,163,.5)}
  .unit-net{font-size:13px;font-weight:700;text-align:right;min-width:70px}
  .unit-detail{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}
  .na{padding:20px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr"><span>🏢</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:10px;color:rgba(163,163,163,.5)">${method}</span>
  </div>
  ${!enabled ? `<div class="na">VvE energieverdeling niet geconfigureerd</div>` : `
  <div class="summary">
    <div class="sum-item">
      <div class="sum-val" style="color:#fb923c">${totalSolar.toFixed(1)} kWh</div>
      <div class="sum-lbl">Gedeelde solar vandaag</div>
    </div>
    <div class="sum-item">
      <div class="sum-val">${units.length}</div>
      <div class="sum-lbl">Appartementen</div>
    </div>
  </div>
  ${units.map(u => `
  <div class="unit">
    <div style="flex:1">
      <div class="unit-name">${u.label}</div>
      <div class="unit-detail">
        ☀️ ${u.solar_share_pct}% — ${u.solar_kwh} kWh |
        🚗 ${u.ev_kwh} kWh
      </div>
    </div>
    <div style="text-align:right">
      <div class="unit-net" style="color:${u.net_eur>=0?'#4ade80':'#f87171'}">
        ${u.net_eur >= 0 ? "+" : ""}€${u.net_eur.toFixed(3)}
      </div>
      <div class="unit-share">☀️ €${u.solar_credit_eur.toFixed(3)}</div>
    </div>
  </div>`).join("")}
  `}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-vve-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsVveCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "🏢 VvE Energieverdeling"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

customElements.define("cloudems-vve-card", CloudemsVveCard);
customElements.define("cloudems-vve-card-editor", CloudemsVveCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-vve-card", name: "CloudEMS VvE Energieverdeling" });
