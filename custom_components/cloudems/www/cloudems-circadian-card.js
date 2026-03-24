// CloudEMS Circadian Nudge Card v1.0.0

class CloudemsCircadianCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🌅 Slimme Verlichting", ...c }; this._render(); }

  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_circadian_nudge"];
    if (JSON.stringify([s?.state, s?.last_changed]) !== this._prev) {
      this._prev = JSON.stringify([s?.state, s?.last_changed]); this._render();
    }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_circadian_nudge"]?.attributes || {};
    const enabled = attr.enabled === true;
    const mode = attr.mode || "nudge";
    const entities = attr.entities || 0;
    const maxShift = attr.max_shift_pct || 8;
    const states = attr.active_states || [];
    const modeLabel = mode === "nudge" ? "Nudge" : mode === "circadian" ? "Circadian HCL" : "Gecombineerd";

    const ctBar = (ct) => {
      const pct = Math.round((ct - 2700) / (6500 - 2700) * 100);
      const col = ct < 3500 ? "#fb923c" : ct < 5000 ? "#fbbf24" : "#60a5fa";
      return `<div style="height:4px;background:rgba(255,255,255,.1);border-radius:2px">
        <div style="height:4px;width:${pct}%;background:linear-gradient(90deg,#fb923c,#fbbf24,#60a5fa);border-radius:2px"></div></div>`;
    };

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;
    background:${enabled?"rgba(74,222,128,.15)":"rgba(107,114,128,.15)"};
    color:${enabled?"#4ade80":"#6b7280"}}
  .row{display:flex;align-items:center;justify-content:space-between;
    padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .lbl{font-size:12px;color:rgba(163,163,163,1)}
  .val{font-size:12px;font-weight:600;color:#fff}
  .light-row{padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .light-name{font-size:12px;color:#fff;margin-bottom:4px}
  .light-meta{display:flex;justify-content:space-between;font-size:10px;color:rgba(163,163,163,.6);margin-bottom:3px}
  .na{padding:16px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)}
  .ct-gradient{height:8px;border-radius:4px;
    background:linear-gradient(90deg,#fb923c 0%,#fbbf24 40%,#fff 60%,#60a5fa 100%);margin:12px 16px 4px}
  .ct-labels{display:flex;justify-content:space-between;font-size:9px;color:rgba(163,163,163,.4);padding:0 16px 8px}
</style>
<div class="card">
  <div class="hdr">
    <span>🌅</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span class="badge">${enabled ? modeLabel : "Uitgeschakeld"}</span>
  </div>
  ${!enabled ? `<div class="na">Activeer via CloudEMS → Automatisering → Slimme Verlichting</div>` : `
  <div class="row"><span class="lbl">Modus</span><span class="val">${modeLabel}</span></div>
  <div class="row"><span class="lbl">Lampen</span><span class="val">${entities}</span></div>
  <div class="row"><span class="lbl">Max aanpassing</span><span class="val">±${maxShift}%</span></div>
  <div class="ct-gradient"></div>
  <div class="ct-labels"><span>2700K warm</span><span>4000K neutraal</span><span>6500K daglicht</span></div>
  ${states.length > 0 ? `<div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;padding:8px 16px 2px">Actieve lampen</div>
  ${states.map(s => `<div class="light-row">
    <div class="light-name">${s.entity_id.split(".")[1].replace(/_/g," ")}</div>
    <div class="light-meta">
      <span>Helderheid: ${Math.round(s.last_bri/255*100)}%</span>
      <span>${s.last_ct_k}K</span>
    </div>
    ${ctBar(s.last_ct_k)}
  </div>`).join("")}` : ""}
  `}
</div>`;
  }

  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-circadian-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsCircadianCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "🌅 Slimme Verlichting"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-circadian-card')) customElements.define("cloudems-circadian-card", CloudemsCircadianCard);
if (!customElements.get('cloudems-circadian-card-editor')) customElements.define("cloudems-circadian-card-editor", CloudemsCircadianCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-circadian-card", name: "CloudEMS Slimme Verlichting" });
