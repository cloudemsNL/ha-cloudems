// CloudEMS Vacation Mode Card v5.4.96
const CARD_VACATION_VERSION = '5.5.318';

class CloudemsVacationCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🏖️ Vakantiemodus", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_vacation_mode"];
    if (JSON.stringify(s?.state) !== this._prev) { this._prev = JSON.stringify(s?.state); this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_vacation_mode"]?.attributes || {};
    const active = attr.active === true;
    const days = attr.days_away || 0;
    const saved = attr.saved_kwh || 0;
    const setpoint = attr.boiler_setpoint || 45;
    const col = active ? "#4ade80" : "#6b7280";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;
    background:${active?"rgba(74,222,128,.15)":"rgba(107,114,128,.15)"};color:${col}}
  .row{display:flex;align-items:center;justify-content:space-between;
    padding:9px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .row:last-child{border-bottom:none}
  .lbl{font-size:12px;color:rgba(163,163,163,1)}
  .val{font-size:12px;font-weight:600;color:#fff}
  .na{padding:16px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
</style>
<div class="card">
  <div class="hdr">
    
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span class="badge">${active ? "Actief" : "Inactief"}</span>
  </div>
  ${active ? `
  <div class="row"><span class="lbl">Dagen weg</span><span class="val">${days}</span></div>
  <div class="row"><span class="lbl">Bespaard</span><span class="val">${saved} kWh</span></div>
  <div class="row"><span class="lbl">Boiler setpoint</span><span class="val">${setpoint}°C</span></div>
  ` : `<div class="na">Vakantiemodus uitgeschakeld — activeer via CloudEMS instellingen</div>`}
</div>`;
  }

  getCardSize() { return 2; }
  static getConfigElement() { return document.createElement("cloudems-vacation-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsVacationCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "🏖️ Vakantiemodus"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-vacation-card')) customElements.define("cloudems-vacation-card", CloudemsVacationCard);
if (!customElements.get('cloudems-vacation-card-editor')) customElements.define("cloudems-vacation-card-editor", CloudemsVacationCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-vacation-card", name: "CloudEMS Vakantiemodus" });
