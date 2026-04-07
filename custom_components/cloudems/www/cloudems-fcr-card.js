// CloudEMS FCR/aFRR Card v5.4.96
const CARD_FCR_VERSION = '5.5.318';

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
    if (!h || !h.states) return;
    const attr = h?.states["sensor.cloudems_fcr_afrr"]?.attributes || {};
    const state = h?.states["sensor.cloudems_fcr_afrr"]?.state || "not_eligible";
    const fcrOk = attr.eligible_fcr;
    const afrrOk = attr.eligible_afrr;
    const issues = attr.issues || [];
    const revenue = attr.monthly_revenue_est || 0;
    const freq = attr.current_freq;
    const soc = attr.soc_ok;
    const nextStep = attr.next_step || "";
    // Tennet onbalansmarkt signaal
    const imb = h?.states["sensor.cloudems_tennet_imbalance"]?.attributes || {};
    const imbDir = imb.direction || "neutral";
    const imbReason = imb.reason || "";
    const imbAdj = imb.soc_adjustment_pct || 0;
    const imbSource = imb.source || "";
    const imbConf = Math.round((imb.confidence || 0) * 100);
    // Mijnbatterij ranking
    const mb = h?.states["sensor.cloudems_mijnbatterij_score"]?.attributes || {};
    // Imbalance revenue
    const ir = h?.states["sensor.cloudems_imbalance_revenue"]?.attributes || {};
    // Zonneplan margin
    const zm = h?.states["sensor.cloudems_zonneplan_margin"]?.attributes || {};
    const zmConfigured  = zm.configured === true;
    const zmZpToday     = parseFloat(zm.zp_today_eur || 0);
    const zmZpTotal     = zm.zp_total_eur;
    const zmTheor       = parseFloat(zm.theoretical_eur || 0);
    const zmMarginEur   = parseFloat(zm.margin_eur || 0);
    const zmMarginPct   = parseFloat(zm.margin_pct || 0);
    const zmZpRate      = parseFloat(zm.zp_effective_rate_ct || 0);
    const zmTennetRate  = parseFloat(zm.tennet_up_rate_ct || 0);
    const zmExplain     = zm.margin_explanation || "";
    const zmDisKwh      = parseFloat(zm.zp_discharge_kwh || 0);
    const irActual  = parseFloat(ir.today_actual_eur  || 0);
    const irTheor   = parseFloat(ir.today_theoretical_eur || 0);
    const irMargin  = parseFloat(ir.today_margin_eur  || 0);
    const irMarginPct = parseFloat(ir.today_margin_pct || 0);
    const irUpEvts  = ir.today_up_events   || 0;
    const irDnEvts  = ir.today_down_events || 0;
    const irUpPrice = parseFloat(ir.avg_tennet_up_price_mwh   || 0);
    const irDnPrice = parseFloat(ir.avg_tennet_down_price_mwh || 0);
    const mbRank = mb.rank;
    const mbScore = mb.score;
    const mbTotal = mb.total_users;
    const mbUrl = mb.profile_url || "https://www.mijnbatterij.nl";

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
  <div style="border-top:1px solid rgba(255,255,255,.07);padding:10px 16px">
    <div style="font-size:10px;font-weight:600;color:#6b7280;margin-bottom:6px">ONBALANSMARKT (${imbSource==='tennet'?'Tennet live':'EPEX proxy'})</div>
    <div style="display:flex;align-items:center;gap:8px">
      <span style="font-size:18px">${imbDir==='up'?'⬆️':imbDir==='down'?'⬇️':'⚖️'}</span>
      <div style="flex:1">
        <div style="font-size:11px;color:#e2e8f0">${imbReason||'Neutraal'}</div>
        ${imbAdj!==0?`<div style="font-size:10px;color:${imbAdj>0?'#34d399':'#f97316'}">SOC doel ${imbAdj>0?'+':''}${imbAdj}% (conf ${imbConf}%)</div>`:''}
      </div>
    </div>
  </div>
  <div style="border-top:1px solid rgba(255,255,255,.07);padding:10px 16px">
    <div style="font-size:10px;font-weight:600;color:#6b7280;margin-bottom:6px">IMBALANCE MARKET REVENUE</div>
    ${irTheor > 0 ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px">
      <div>
        <div style="font-size:9px;color:#6b7280">Tennet theoretical</div>
        <div style="font-size:13px;font-weight:600;color:#4ade80">€${irTheor.toFixed(4)}</div>
      </div>
      <div>
        <div style="font-size:9px;color:#6b7280">Zonneplan actual</div>
        <div style="font-size:13px;font-weight:600;color:#60a5fa">€${irActual.toFixed(4)}</div>
      </div>
      <div>
        <div style="font-size:9px;color:#6b7280">Zonneplan margin</div>
        <div style="font-size:13px;font-weight:600;color:#f87171">€${irMargin.toFixed(4)} (${irMarginPct.toFixed(0)}%)</div>
      </div>
      <div>
        <div style="font-size:9px;color:#6b7280">Events today</div>
        <div style="font-size:11px;font-weight:600;color:#e2e8f0">⬆️${irUpEvts} ⬇️${irDnEvts}</div>
      </div>
    </div>
    ${irUpPrice > 0 ? `<div style="font-size:10px;color:#6b7280">Up: ${irUpPrice.toFixed(0)} €/MWh · Down: ${irDnPrice.toFixed(0)} €/MWh (Tennet)</div>` : ''}
    ` : `<div style="font-size:11px;color:#374151">Waiting for imbalance events...</div>`}
  </div>
  <div style="border-top:1px solid rgba(255,255,255,.07);padding:10px 16px">
    <div style="font-size:10px;font-weight:600;color:#6b7280;margin-bottom:6px">ZONNEPLAN MARGIN ANALYSIS</div>
    ${zmConfigured ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
      <div>
        <div style="font-size:9px;color:#6b7280">Zonneplan credits you</div>
        <div style="font-size:15px;font-weight:700;color:#4ade80">€${zmZpToday.toFixed(4)}</div>
        <div style="font-size:9px;color:#6b7280">${zmZpRate.toFixed(1)}ct/kWh</div>
      </div>
      <div>
        <div style="font-size:9px;color:#6b7280">Tennet would pay</div>
        <div style="font-size:15px;font-weight:700;color:#f59e0b">€${zmTheor.toFixed(4)}</div>
        <div style="font-size:9px;color:#6b7280">${zmTennetRate.toFixed(1)}ct/kWh</div>
      </div>
    </div>
    <div style="background:rgba(248,113,113,.1);border-radius:8px;padding:8px;margin-bottom:6px">
      <div style="font-size:10px;color:#6b7280">Estimated Zonneplan margin</div>
      <div style="font-size:22px;font-weight:700;color:#f87171">${zmMarginPct.toFixed(0)}%
        <span style="font-size:12px;font-weight:400">= €${zmMarginEur.toFixed(4)} today</span>
      </div>
    </div>
    ${zmZpTotal!=null?`<div style="font-size:10px;color:#6b7280">All-time Zonneplan earnings: <b style="color:#fff">€${zmZpTotal?.toFixed(2)}</b></div>`:''}
    <div style="font-size:10px;color:#4b5563;margin-top:4px;font-style:italic">${zmExplain}</div>
    ` : `
    <div style="font-size:11px;color:#374151">
      Auto-discovering Zonneplan sensors...<br>
      <small>Install <code>ha-zonneplan-one</code> integration to enable margin analysis.</small>
    </div>`}
  </div>
  <div style="border-top:1px solid rgba(255,255,255,.07);padding:10px 16px">
    <div style="font-size:10px;font-weight:600;color:#6b7280;margin-bottom:6px">MIJNBATTERIJ.NL</div>
    ${mbRank ? `<div style="display:flex;align-items:center;justify-content:space-between">
      <div><span style="font-size:22px;font-weight:700;color:#f59e0b">#${mbRank}</span>${mbTotal?`<span style="font-size:11px;color:#6b7280"> / ${mbTotal}</span>`:''}</div>
      ${mbScore?`<span style="font-size:13px;font-weight:600;color:#4ade80">${mbScore} pts</span>`:''}
    </div>
    <a href="${mbUrl}" target="_blank" style="font-size:10px;color:#60a5fa;text-decoration:none;display:block;margin-top:4px">Bekijk profiel →</a>`
    : '<div style="font-size:11px;color:#374151">Voeg mijnbatterij_api_key toe voor ranking</div>'}
  </div>
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
