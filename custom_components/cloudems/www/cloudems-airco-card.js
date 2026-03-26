// CloudEMS Multi-Split Airco Card v1.0.0
const CARD_AIRCO_VERSION = '5.4.1';
// Shows all configured AC units with live status, temperature, power, EPEX mode

class CloudemsAircoCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }

  setConfig(c) { this._cfg = { title: "❄️ Multi-Split Airco", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_climate_epex_status"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    const attr  = h.states["sensor.cloudems_climate_epex_status"]?.attributes || {};
    const devs  = attr.devices || [];
    const price = parseFloat(h.states["sensor.cloudems_price_current_hour"]?.state || 0);

    const modeColor = m => m === "cheap" ? "#4ade80" : m === "dear" ? "#f87171" : m === "off" ? "#374151" : "#94a3b8";
    const modeLabel = m => m === "cheap" ? "✅ Goedkoop" : m === "dear" ? "🔺 Duur" : m === "off" ? "⏹ Uit" : "— Neutraal";
    const actionIcon = a => ({ heating: "🔥", cooling: "❄️", drying: "💧", fan: "💨", idle: "○" })[a] || "○";
    const typeLabel = t => ({ airco: "Airco", heat_pump: "WP", climate: "Klimaat", vt: "VT", trv: "TRV" })[t] || t;

    const totalW = devs.reduce((s, d) => s + (d.power_w || 0), 0);
    const activeDevs = devs.filter(d => d.is_on && d.action !== "idle");

    sh.innerHTML = `
<style>
  :host { display: block; width: 100% }
  .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,.06); border-radius: 16px;
    overflow: hidden; font-family: var(--primary-font-family, sans-serif) }
  .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px;
    border-bottom: 1px solid rgba(255,255,255,.07) }
  .hdr-title { font-size: 12px; font-weight: 600; letter-spacing: .04em; color: #fff; flex: 1 }
  .summary { display: grid; grid-template-columns: 1fr 1fr 1fr; border-bottom: 1px solid rgba(255,255,255,.07) }
  .sum { padding: 10px 16px; text-align: center }
  .sum-val { font-size: 16px; font-weight: 700; color: #fff }
  .sum-lbl { font-size: 10px; color: rgba(163,163,163,.5); margin-top: 2px }
  .section-title { font-size: 10px; font-weight: 700; letter-spacing: .08em;
    color: rgba(255,255,255,.3); text-transform: uppercase; padding: 10px 16px 4px }
  .unit { display: flex; flex-direction: column; padding: 10px 16px;
    border-bottom: 1px solid rgba(255,255,255,.04) }
  .unit:last-child { border-bottom: none }
  .unit-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px }
  .unit-name { flex: 1; font-size: 13px; font-weight: 500; color: #fff }
  .unit-action { font-size: 16px }
  .unit-state { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 8px }
  .unit-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px 8px; margin-top: 2px }
  .kv { display: flex; flex-direction: column }
  .kv-l { font-size: 10px; color: rgba(163,163,163,.5) }
  .kv-v { font-size: 12px; font-weight: 600; color: #fff }
  .mode-bar { height: 3px; border-radius: 1.5px; margin-top: 6px }
  .empty { padding: 20px; text-align: center; font-size: 12px; color: rgba(163,163,163,.5) }
  .off .unit-name { color: rgba(163,163,163,.5) }
  .price-row { display: flex; justify-content: space-between; padding: 7px 16px;
    font-size: 11px; color: rgba(163,163,163,.6);
    border-bottom: 1px solid rgba(255,255,255,.07) }
</style>
<div class="card">
  <div class="hdr">
    <span>❄️</span>
    <span class="hdr-title">${c.title}</span>
    <span style="font-size:11px;color:rgba(163,163,163,.5)">${devs.length} unit${devs.length !== 1 ? "s" : ""}</span>
  </div>

  ${devs.length === 0 ? `<div class="empty">Geen airco's geconfigureerd.<br>Ga naar CloudEMS → Klimaat EPEX om units toe te voegen.</div>` : `
  <div class="price-row">
    <span>EPEX prijs nu</span>
    <span style="color:${price < 0.15 ? '#4ade80' : price > 0.30 ? '#f87171' : '#fbbf24'};font-weight:600">
      €${(price * 100).toFixed(1)} ct/kWh
    </span>
  </div>

  <div class="summary">
    <div class="sum">
      <div class="sum-val" style="color:${totalW > 0 ? '#60a5fa' : '#6b7280'}">${Math.round(totalW)} W</div>
      <div class="sum-lbl">Totaal vermogen</div>
    </div>
    <div class="sum">
      <div class="sum-val" style="color:#4ade80">${activeDevs.length}</div>
      <div class="sum-lbl">Actief</div>
    </div>
    <div class="sum">
      <div class="sum-val">${devs.filter(d => d.is_on).length}</div>
      <div class="sum-lbl">Aan</div>
    </div>
  </div>

  <div class="section-title">Units</div>

  ${devs.map(d => {
    const col = modeColor(d.mode);
    const isOff = !d.is_on;
    return `
  <div class="unit ${isOff ? 'off' : ''}">
    <div class="unit-top">
      <span class="unit-action">${actionIcon(d.action)}</span>
      <span class="unit-name">${d.label || d.entity_id.split(".")[1].replace(/_/g," ")}</span>
      <span style="font-size:10px;color:rgba(163,163,163,.4)">${typeLabel(d.device_type)}</span>
      <span class="unit-state" style="background:${col}22;color:${col}">${modeLabel(d.mode)}</span>
    </div>
    <div class="unit-grid">
      <div class="kv">
        <span class="kv-l">Huidig</span>
        <span class="kv-v">${d.current_temp != null ? d.current_temp.toFixed(1) + "°C" : "—"}</span>
      </div>
      <div class="kv">
        <span class="kv-l">Setpoint</span>
        <span class="kv-v" style="color:#fbbf24">${d.target_temp != null ? d.target_temp.toFixed(1) + "°C" : "—"}</span>
      </div>
      <div class="kv">
        <span class="kv-l">Vermogen</span>
        <span class="kv-v" style="color:${(d.power_w||0)>0?'#60a5fa':'#6b7280'}">${Math.round(d.power_w || 0)} W</span>
      </div>
      ${d.applied_offset != null && d.applied_offset !== 0 ? `
      <div class="kv" style="grid-column:span 3">
        <span class="kv-l">EPEX offset</span>
        <span class="kv-v" style="color:${d.applied_offset>0?'#4ade80':'#f87171'}">
          ${d.applied_offset > 0 ? "+" : ""}${d.applied_offset.toFixed(1)}°C (${d.applied_offset > 0 ? "goedkoop uur — verhoogd" : "duur uur — verlaagd"})
        </span>
      </div>` : ""}
    </div>
    <div class="mode-bar" style="background:${col}44">
      <div style="height:3px;background:${col};border-radius:1.5px;width:${isOff?0:100}%"></div>
    </div>
  </div>`}).join("")}
  `}
</div>`;
  }

  getCardSize() { return Math.max(3, 2 + (this._hass?.states["sensor.cloudems_climate_epex_status"]?.attributes?.devices?.length || 0)); }
  static getConfigElement() { return document.createElement("cloudems-airco-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsAircoCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "❄️ Multi-Split Airco"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-airco-card')) customElements.define("cloudems-airco-card", CloudemsAircoCard);
if (!customElements.get('cloudems-airco-card-editor')) customElements.define("cloudems-airco-card-editor", CloudemsAircoCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-airco-card", name: "CloudEMS Multi-Split Airco", description: "Live status alle airco units met EPEX sturing" });
