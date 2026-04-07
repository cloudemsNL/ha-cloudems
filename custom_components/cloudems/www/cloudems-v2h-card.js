// CloudEMS V2H Card v5.4.96
const CARD_V2H_VERSION = '5.5.318';
// Vehicle-to-Home status and control

class CloudemsV2hCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🔄 Vehicle-to-Home", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_v2h_status"];
    const j = JSON.stringify([s?.state, s?.attributes?.active, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const s = h?.states["sensor.cloudems_v2h_status"];
    const attr = s?.attributes || {};
    const active = attr.active === true;
    const available = attr.available === true;
    const enabled = attr.enabled === true;
    const soc = attr.car_soc_pct != null ? Math.round(attr.car_soc_pct) : null;
    const price = attr.price_eur_kwh != null ? attr.price_eur_kwh.toFixed(3) : null;
    const discharge = attr.discharge_w || 0;
    const reason = attr.reason || "";
    const session = attr.session || null;

    const statusColor = active ? "#4ade80" : available ? "#fb923c" : "#6b7280";
    const statusLabel = active ? "Ontladen → huis" : available ? "Standby" : enabled ? "Auto niet aangesloten" : "Uitgeschakeld";

    sh.innerHTML = `
<style>
  :host { display: block; width: 100%; }
  .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,.06); border-radius: 16px;
    overflow: hidden; font-family: var(--primary-font-family, sans-serif); }
  .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px;
    border-bottom: 1px solid rgba(255,255,255,.07); }
  .hdr-title { font-size: 12px; font-weight: 600; letter-spacing: .04em; color: #fff; flex: 1; }
  .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 8px;
    background: ${active ? "rgba(74,222,128,.15)" : "rgba(107,114,128,.15)"}; color: ${statusColor}; }
  .row { display: flex; align-items: center; justify-content: space-between;
    padding: 9px 16px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .row:last-child { border-bottom: none; }
  .lbl { font-size: 12px; color: rgba(163,163,163,1); }
  .val { font-size: 12px; font-weight: 600; color: #fff; }
  .reason { padding: 10px 16px; font-size: 11px; color: rgba(163,163,163,.7); font-style: italic; }
  .session { margin: 8px 16px; padding: 8px 12px; background: rgba(74,222,128,.08);
    border: 1px solid rgba(74,222,128,.2); border-radius: 8px; }
  .session-title { font-size: 11px; font-weight: 600; color: #4ade80; margin-bottom: 4px; }
  .session-row { display: flex; justify-content: space-between; font-size: 11px;
    color: rgba(163,163,163,.8); padding: 1px 0; }
  .na { padding: 16px; text-align: center; font-size: 12px; color: rgba(163,163,163,.5); }
</style>
<div class="card">
  <div class="hdr">
    <span style="font-size:16px">🔄</span>
    <span class="hdr-title">${c.title}</span>
    <span class="badge">${statusLabel}</span>
  </div>
  ${!enabled ? `<div class="na">V2H uitgeschakeld — activeer via CloudEMS configuratie</div>` : `
  <div class="row"><span class="lbl">Auto SOC</span><span class="val">${soc != null ? soc + "%" : "—"}</span></div>
  <div class="row"><span class="lbl">Ontlaadvermogen</span><span class="val">${active ? Math.round(discharge) + " W" : "—"}</span></div>
  <div class="row"><span class="lbl">EPEX prijs</span><span class="val">${price ? "€" + price + "/kWh" : "—"}</span></div>
  ${session && session.active ? `
  <div class="session">
    <div class="session-title">⚡ Actieve sessie</div>
    <div class="session-row"><span>Energie ontladen</span><span>${session.energy_kwh} kWh</span></div>
    <div class="session-row"><span>Duur</span><span>${session.duration_m} min</span></div>
    <div class="session-row"><span>Besparing</span><span>€${session.saving_eur}</span></div>
  </div>` : ""}
  <div class="reason">${reason}</div>
  `}
</div>`;
  }

  getCardSize() { return 3; }
  static getConfigElement() { return document.createElement("cloudems-v2h-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsV2hCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;
color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Card title</label>
<input id="title" value="${this._config?.title || "🔄 Vehicle-to-Home"}" />`;
    this.shadowRoot.getElementById("title").addEventListener("input", e => {
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } }));
    });
  }
}

if (!customElements.get('cloudems-v2h-card')) customElements.define("cloudems-v2h-card", CloudemsV2hCard);
if (!customElements.get('cloudems-v2h-card-editor')) customElements.define("cloudems-v2h-card-editor", CloudemsV2hCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-v2h-card", name: "CloudEMS V2H", description: "Vehicle-to-Home status" });
