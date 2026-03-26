// CloudEMS Phase Outlet Detector Card v1.0.0
const CARD_PHASE_OUTLET_VERSION = '5.4.1';
// Auto-detected phase assignments for devices

class CloudemsPhaseOutletCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "⚡ Fase Detectie", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_phase_outlet_detector"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_phase_outlet_detector"]?.attributes || {};
    const devices = attr.devices || [];
    const total = attr.total_devices || 0;
    const locked = attr.locked_devices || 0;
    const pct = total > 0 ? Math.round(locked / total * 100) : 0;

    const phaseColor = p => p === "L1" ? "#f87171" : p === "L2" ? "#fb923c" : p === "L3" ? "#4ade80" : "#6b7280";
    const confBar = (c) => {
      const w = Math.round(c * 100);
      const col = c >= 0.75 ? "#4ade80" : c >= 0.5 ? "#fb923c" : "#6b7280";
      return `<div style="height:3px;width:100%;background:rgba(255,255,255,.1);border-radius:2px;margin-top:2px">
        <div style="height:3px;width:${w}%;background:${col};border-radius:2px"></div></div>`;
    };

    sh.innerHTML = `
<style>
  :host { display: block; width: 100%; }
  .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,.06);
    border-radius: 16px; overflow: hidden; font-family: var(--primary-font-family, sans-serif); }
  .hdr { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px;
    border-bottom: 1px solid rgba(255,255,255,.07); }
  .hdr-title { font-size: 12px; font-weight: 600; letter-spacing: .04em; color: #fff; flex: 1; }
  .progress { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .progress-row { display: flex; justify-content: space-between; font-size: 11px;
    color: rgba(163,163,163,.7); margin-bottom: 4px; }
  .progress-bar { height: 6px; background: rgba(255,255,255,.1); border-radius: 3px; }
  .progress-fill { height: 6px; background: #4ade80; border-radius: 3px; transition: width .3s; }
  .device { display: flex; align-items: center; gap: 8px; padding: 8px 16px;
    border-bottom: 1px solid rgba(255,255,255,.04); }
  .device:last-child { border-bottom: none; }
  .device-name { flex: 1; font-size: 12px; color: ${total > 0 ? "#fff" : "rgba(163,163,163,.5)"}; }
  .phase-badge { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; min-width: 24px; text-align: center; }
  .pending { color: rgba(163,163,163,.4); font-size: 10px; }
  .na { padding: 16px; text-align: center; font-size: 12px; color: rgba(163,163,163,.5); }
  .summary { display: flex; gap: 12px; padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .sum-item { text-align: center; flex: 1; }
  .sum-val { font-size: 16px; font-weight: 700; }
  .sum-lbl { font-size: 10px; color: rgba(163,163,163,.6); margin-top: 2px; }
</style>
<div class="card">
  <div class="hdr"><span>⚡</span><span class="hdr-title">${c.title}</span></div>
  ${total > 0 ? `
  <div class="progress">
    <div class="progress-row"><span>Detectievoortgang</span><span>${locked}/${total} apparaten</span></div>
    <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
  </div>
  <div class="summary">
    <div class="sum-item"><div class="sum-val" style="color:#f87171">${attr.l1_devices || 0}</div><div class="sum-lbl">L1</div></div>
    <div class="sum-item"><div class="sum-val" style="color:#fb923c">${attr.l2_devices || 0}</div><div class="sum-lbl">L2</div></div>
    <div class="sum-item"><div class="sum-val" style="color:#4ade80">${attr.l3_devices || 0}</div><div class="sum-lbl">L3</div></div>
    <div class="sum-item"><div class="sum-val" style="color:#6b7280">${total - locked}</div><div class="sum-lbl">Onbekend</div></div>
  </div>
  ${devices.slice(0, 12).map(d => `
  <div class="device">
    <span class="device-name">${d.device_name}</span>
    ${d.locked ? `<span class="phase-badge" style="background:${phaseColor(d.phase)}22;color:${phaseColor(d.phase)}">${d.phase}</span>` :
      `<span class="pending">${d.observations}/${3} obs</span>`}
  </div>`).join("")}
  ${devices.length > 12 ? `<div style="padding:8px 16px;font-size:11px;color:rgba(163,163,163,.5)">+${devices.length-12} meer...</div>` : ""}
  ` : `<div class="na">Geen fase-gegevens beschikbaar</div>`}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-phase-outlet-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsPhaseOutletCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;
color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Card title</label>
<input id="title" value="${this._config?.title || "⚡ Fase Detectie"}" />`;
    this.shadowRoot.getElementById("title").addEventListener("input", e => {
      this.dispatchEvent(new CustomEvent("config-changed", {
        detail: { config: { ...this._config, title: e.target.value } }
      }));
    });
  }
}

if (!customElements.get('cloudems-phase-outlet-card')) customElements.define("cloudems-phase-outlet-card", CloudemsPhaseOutletCard);
if (!customElements.get('cloudems-phase-outlet-card-editor')) customElements.define("cloudems-phase-outlet-card-editor", CloudemsPhaseOutletCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-phase-outlet-card", name: "CloudEMS Phase Detector",
  description: "Auto-detected phase assignments for devices" });
