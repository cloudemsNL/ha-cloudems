// CloudEMS eGauge Card v5.4.96
const CARD_EGAUGE_VERSION = '5.4.96';
// eGauge smart meter — grid and phase data

class CloudemsEgaugeCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "📊 eGauge Submeter", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_egauge"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_egauge"]?.attributes || {};
    const available = attr.available === true;
    const net = attr.net_power_w;
    const l1 = attr.l1_power_w, l2 = attr.l2_power_w, l3 = attr.l3_power_w;
    const solar = attr.solar_power_w;
    const fmt = v => v != null ? (v >= 0 ? "+" : "") + Math.round(v) + " W" : "—";
    const col = v => v == null ? "#6b7280" : v > 0 ? "#f87171" : "#4ade80";

    sh.innerHTML = `
<style>
  :host { display: block; width: 100%; }
  .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,.06);
    border-radius: 16px; overflow: hidden; font-family: var(--primary-font-family, sans-serif); }
  .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px;
    border-bottom: 1px solid rgba(255,255,255,.07); }
  .hdr-title { font-size: 12px; font-weight: 600; letter-spacing: .04em; color: #fff; }
  .net { text-align: center; padding: 16px; font-size: 22px; font-weight: 700;
    border-bottom: 1px solid rgba(255,255,255,.04); }
  .row { display: flex; align-items: center; justify-content: space-between;
    padding: 9px 16px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .row:last-child { border-bottom: none; }
  .lbl { font-size: 12px; color: rgba(163,163,163,1); }
  .val { font-size: 12px; font-weight: 600; }
  .na { padding: 16px; text-align: center; font-size: 12px; color: rgba(163,163,163,.5); }
</style>
<div class="card">
  <div class="hdr"><span class="hdr-title">${c.title}</span></div>
  ${!available ? `<div class="na">eGauge niet gevonden</div>` : `
  <div class="net" style="color:${col(net)}">${fmt(net)}</div>
  <div class="row"><span class="lbl">L1</span><span class="val" style="color:${col(l1)}">${fmt(l1)}</span></div>
  <div class="row"><span class="lbl">L2</span><span class="val" style="color:${col(l2)}">${fmt(l2)}</span></div>
  <div class="row"><span class="lbl">L3</span><span class="val" style="color:${col(l3)}">${fmt(l3)}</span></div>
  ${solar != null ? `<div class="row"><span class="lbl">☀️ PV</span><span class="val" style="color:#fb923c">${fmt(solar)}</span></div>` : ""}
  `}
</div>`;
  }

  getCardSize() { return 3; }
  static getConfigElement() { return document.createElement("cloudems-egauge-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsEgaugeCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;
color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Card title</label>
<input id="title" value="${this._config?.title || "📊 eGauge Submeter"}" />`;
    this.shadowRoot.getElementById("title").addEventListener("input", e => {
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } }));
    });
  }
}

if (!customElements.get('cloudems-egauge-card')) customElements.define("cloudems-egauge-card", CloudemsEgaugeCard);
if (!customElements.get('cloudems-egauge-card-editor')) customElements.define("cloudems-egauge-card-editor", CloudemsEgaugeCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-egauge-card", name: "CloudEMS eGauge", description: "eGauge smart meter data" });
