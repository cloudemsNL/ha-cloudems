// CloudEMS Atmospheric Heat Pump Card v1.0.0

class CloudemsAtmosphericCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._prev = ""; }
  setConfig(c) { this._cfg = { title: "🌡️ WP Atmosfeer Optimizer", ...c }; this._render(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_atmospheric_hp"];
    const j = JSON.stringify(s?.last_changed);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    const attr = h?.states["sensor.cloudems_atmospheric_hp"]?.attributes || {};
    const risk = attr.icing_risk || "none";
    const icing = attr.icing_pct || 0;
    const copDeg = attr.cop_degradation_pct || 0;
    const defrost = attr.defrost_recommended;
    const defrostReason = attr.defrost_reason || "";
    const optimal = attr.optimal_run_now;
    const optReason = attr.optimal_run_reason || "";
    const cond = attr.conditions || {};

    const riskCol = risk === "none" ? "#4ade80" : risk === "low" ? "#86efac" :
                    risk === "medium" ? "#fb923c" : "#f87171";

    sh.innerHTML = `
<style>
  :host{display:block;width:100%}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .risk-row{display:flex;align-items:center;gap:12px;padding:12px 16px;
    border-bottom:1px solid rgba(255,255,255,.07)}
  .risk-num{font-size:28px;font-weight:700;color:${riskCol}}
  .risk-bar{flex:1}
  .bar-bg{height:6px;background:rgba(255,255,255,.1);border-radius:3px}
  .bar-fill{height:6px;background:${riskCol};border-radius:3px;width:${icing}%}
  .row{display:flex;justify-content:space-between;align-items:center;
    padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.04)}
  .lbl{font-size:12px;color:rgba(163,163,163,1)}
  .val{font-size:12px;font-weight:600;color:#fff}
  .alert{margin:8px 16px;padding:8px 12px;border-radius:8px;font-size:11px}
  .alert-warn{background:rgba(251,146,60,.1);border:1px solid rgba(251,146,60,.3);color:#fb923c}
  .alert-ok{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.3);color:#4ade80}
  .cond{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:8px 16px}
  .cond-item{font-size:11px;color:rgba(163,163,163,.7)}
</style>
<div class="card">
  <div class="hdr"><span>🌡️</span><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span></div>
  <div class="risk-row">
    <div class="risk-num">${icing.toFixed(0)}%</div>
    <div class="risk-bar">
      <div style="font-size:11px;color:${riskCol};margin-bottom:4px">IJsrisico: ${risk}</div>
      <div class="bar-bg"><div class="bar-fill"></div></div>
    </div>
  </div>
  <div class="row"><span class="lbl">COP degradatie</span>
    <span class="val" style="color:${copDeg>10?'#f87171':'#4ade80'}">${copDeg.toFixed(0)}%</span></div>
  <div class="row"><span class="lbl">Optimaal nu draaien</span>
    <span class="val" style="color:${optimal?'#4ade80':'#6b7280'}">${optimal?"Ja":"Nee"}</span></div>
  ${defrost ? `<div class="alert alert-warn">❄️ Ontdooien aanbevolen — ${defrostReason}</div>` : ""}
  ${optimal ? `<div class="alert alert-ok">✅ ${optReason}</div>` : ""}
  <div class="cond">
    <span class="cond-item">🌡️ ${cond.temp_c?.toFixed(1) || "—"}°C</span>
    <span class="cond-item">💧 ${cond.humidity_pct?.toFixed(0) || "—"}%</span>
    <span class="cond-item">🌬️ ${cond.wind_ms?.toFixed(1) || "—"} m/s</span>
    <span class="cond-item">📊 ${cond.pressure_hpa?.toFixed(0) || "—"} hPa</span>
  </div>
</div>`;
  }

  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-atmospheric-card-editor"); }
  static getStubConfig() { return {}; }
}

class CloudemsAtmosphericCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._render(); }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px}</style>
<label>Titel</label><input id="t" value="${this._config?.title || "🌡️ WP Atmosfeer Optimizer"}" />`;
    this.shadowRoot.getElementById("t").addEventListener("input", e =>
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: { ...this._config, title: e.target.value } } })));
  }
}

if (!customElements.get('cloudems-atmospheric-card')) customElements.define("cloudems-atmospheric-card", CloudemsAtmosphericCard);
if (!customElements.get('cloudems-atmospheric-card-editor')) customElements.define("cloudems-atmospheric-card-editor", CloudemsAtmosphericCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "cloudems-atmospheric-card", name: "CloudEMS WP Atmosfeer" });
