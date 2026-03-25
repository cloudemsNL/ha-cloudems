// CloudEMS FCR/aFRR Card v1.0.0
const CARD_FCR_VERSION = '5.3.31';

class CloudemsFcrCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "📈 FCR/aFRR Gereedheid", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_fcr_afrr"];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if (j !== this._p) { this._p = j; this._r(); }
  }

  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_fcr_afrr"]?.attributes || {};
    const state = h?.states["sensor.cloudems_fcr_afrr"]?.state || "not_eligible";
    const fcrOk = attr.eligible_fcr;
    const afrrOk = attr.eligible_afrr;
    const issues = attr.issues || [];
    const revenue = attr.monthly_revenue_est || 0;
    const freq = attr.current_freq;
    const soc = attr.soc_ok;
    const nextStep = attr.next_step || "";

    const stateCol = fcrOk ? "#4ade80" : afrrOk ? "#fb923c" : "#6b7280";
    const stateLabel = fcrOk ? "FCR Gereed" : afrrOk ? "aFRR Gereed" : "Niet geschikt";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;
    background:${stateCol}22;color:${stateCol}}
  .revenue{text-align:center;padding:14px 16px;border-bottom:1px solid rgba(255,255,255,.07)}
  .rev-val{font-size:28px;font-weight:700;color:#4ade80}
  .rev-lbl{font-size:11px;color:rgba(163,163,163,.5);margin-top:2px}
  .row{display:flex;align-items:center;justify-content:space-between;
    padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .lbl{font-size:12px;color:rgba(163,163,163,1)}
  .val{font-size:12px;font-weight:600}
  .check{font-size:14px}
  .issue{padding:4px 16px;font-size:11px;color:#f87171;font-style:italic}
  .next{padding:10px 16px;font-size:11px;color:rgba(163,163,163,.6);
    border-top:1px solid rgba(255,255,255,.06)}
</style>
<div class="card">
  <div class="hdr">
    <span>📈</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span class="badge">${stateLabel}</span>
  </div>
  <div class="revenue">
    <div class="rev-val">€${revenue.toFixed(0)}/mnd</div>
    <div class="rev-lbl">Geschatte potentiële inkomsten</div>
  </div>
  <div class="row">
    <span class="lbl">FCR geschikt</span>
    <span class="check">${fcrOk ? "✅" : "❌"}</span>
  </div>
  <div class="row">
    <span class="lbl">aFRR geschikt</span>
    <span class="check">${afrrOk ? "✅" : "❌"}</span>
  </div>
  <div class="row">
    <span class="lbl">SOC bereik ok</span>
    <span class="check">${soc ? "✅" : "⚠️"}</span>
  </div>
  <div class="row">
    <span class="lbl">Netfrequentie</span>
    <span class="val" style="color:#60a5fa">${freq ? freq.toFixed(3) + " Hz" : "—"}</span>
  </div>
  ${issues.map(i => `<div class="issue">⚠️ ${i}</div>`).join("")}
  ${nextStep ? `<div class="next">💡 ${nextStep}</div>` : ""}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-fcr-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsFcrCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "📈 FCR/aFRR Gereedheid"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-fcr-card')) customElements.define("cloudems-fcr-card", CloudemsFcrCard);
if (!customElements.get('cloudems-fcr-card-editor')) customElements.define("cloudems-fcr-card-editor", CloudemsFcrCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-fcr-card", name: "CloudEMS FCR/aFRR" });
