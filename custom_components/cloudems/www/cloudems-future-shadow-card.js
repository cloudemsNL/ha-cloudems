// CloudEMS Future Shadow Card v5.4.96
// "Wat zou je verbruik/kosten zijn geweest zonder CloudEMS?"
// Leest DOL uitkomsten + cost_today_eur voor vergelijking werkelijkheid vs schaduw

const FSC_VERSION = '5.5.318';
const FSC_SENSOR  = 'sensor.cloudems_decision_learner';
const FSC_STATUS  = 'sensor.cloudems_status';

const FSC_STYLES = `
  :host { display:block; width:100%; }
  .card { background:rgb(18,20,28); border-radius:14px; border:1px solid rgba(255,255,255,.07);
    font-family:var(--primary-font-family,system-ui,sans-serif); overflow:hidden; }
  .hdr { display:flex; align-items:center; gap:10px; padding:12px 16px 10px;
    border-bottom:1px solid rgba(255,255,255,.07); }
  .hdr-title { font-size:13px; font-weight:700; color:#f1f5f9; flex:1; }
  .hdr-sub { font-size:10px; color:rgba(163,163,163,.5); }
  .body { padding:14px 16px; }
  .saving-hero { display:flex; align-items:baseline; gap:6px; margin-bottom:14px; }
  .saving-amt { font-size:28px; font-weight:700; color:#4ade80; font-family:monospace; }
  .saving-lbl { font-size:11px; color:rgba(163,163,163,.5); }
  .bars { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
  .bar-row { display:flex; align-items:center; gap:8px; }
  .bar-label { font-size:10px; color:rgba(163,163,163,.6); width:70px; flex-shrink:0; }
  .bar-track { flex:1; height:14px; background:rgba(255,255,255,.06); border-radius:3px; overflow:hidden; position:relative; }
  .bar-fill { height:100%; border-radius:3px; transition:width .6s ease; }
  .bar-val { font-size:10px; font-family:monospace; font-weight:600; width:52px; text-align:right; flex-shrink:0; }
  .shadow-fill { background:rgba(248,113,113,.5); }
  .real-fill   { background:rgba(74,222,128,.7); }
  .divider { border:none; border-top:1px solid rgba(255,255,255,.06); margin:12px 0; }
  .decisions-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-bottom:12px; }
  .dec-cell { background:rgba(255,255,255,.04); border-radius:8px; padding:8px 6px; text-align:center; }
  .dec-val  { font-size:16px; font-weight:700; color:#f1f5f9; font-family:monospace; }
  .dec-lbl  { font-size:9px; color:rgba(163,163,163,.4); margin-top:2px; }
  .insight  { font-size:11px; color:rgba(163,163,163,.6); font-style:italic;
    background:rgba(99,102,241,.06); border-left:2px solid rgba(99,102,241,.3);
    padding:8px 10px; border-radius:0 6px 6px 0; margin-bottom:10px; }
  .outcomes { display:flex; flex-direction:column; gap:4px; }
  .outcome-row { display:flex; align-items:center; gap:8px; font-size:10px; padding:4px 0;
    border-bottom:1px solid rgba(255,255,255,.03); }
  .outcome-row:last-child { border-bottom:none; }
  .oc-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }
  .oc-action { flex:1; color:rgba(200,200,210,.8); }
  .oc-val { font-family:monospace; font-weight:600; }
  .oc-pos { color:#4ade80; }
  .oc-neg { color:#f87171; }
  .empty { padding:32px; text-align:center; font-size:11px; color:rgba(163,163,163,.4); }
`;

class CloudEMSFutureShadowCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._prev = '';
  }

  setConfig(c) { this._config = c; }

  set hass(h) {
    this._hass = h;
    const s  = h.states[FSC_SENSOR];
    const st = h.states[FSC_STATUS];
    const sig = JSON.stringify([s?.state, s?.attributes?.total_value_eur, st?.attributes?.cost_today_eur]);
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    const h  = this._hass;
    if (!h) return;

    const s   = h.states[FSC_SENSOR];
    const st  = h.states[FSC_STATUS];
    const a   = s?.attributes || {};
    const sta = st?.attributes || {};

    const totalSaved  = parseFloat(a.total_value_eur || 0);
    const totalEval   = parseInt(a.total_evaluated   || 0);
    const totalDec    = parseInt(a.total_decisions   || 0);
    const pending     = parseInt(a.pending_evaluations || 0);
    const insight     = a.top_insight || '';
    const outcomes    = (a.recent_outcomes || []).slice(-6).reverse();

    // Vandaag kosten
    const costToday    = parseFloat(sta.cost_today_eur || 0);
    // Schaduw: wat zou het gekost hebben zonder CloudEMS
    // Benadering: kosten + besparing vandaag (DOL daily_value_eur als beschikbaar)
    const dailySaved   = parseFloat(a.daily_value_eur || totalSaved / Math.max(1, a.active_days || 30));
    const shadowToday  = costToday + Math.max(0, dailySaved);
    const maxBar       = Math.max(shadowToday, costToday, 0.01);

    const fmt = (v) => v >= 0 ? `+€${v.toFixed(2)}` : `-€${Math.abs(v).toFixed(2)}`;
    const fmtEur = (v) => `€${Math.abs(v).toFixed(2)}`;

    sh.innerHTML = `<style>${FSC_STYLES}</style>
<div class="card">
  <div class="hdr">
    <span style="font-size:16px">👥</span>
    <div style="flex:1">
      <div class="hdr-title">Future Shadow</div>
      <div class="hdr-sub">Werkelijkheid vs zonder CloudEMS</div>
    </div>
    <div style="font-size:10px;color:rgba(163,163,163,.35);font-family:monospace">v${FSC_VERSION}</div>
  </div>
  <div class="body">

    <div class="saving-hero">
      <div class="saving-amt">${totalSaved >= 0 ? '+' : ''}€${Math.abs(totalSaved).toFixed(2)}</div>
      <div class="saving-lbl">totaal geleerd voordeel</div>
    </div>

    <div class="bars">
      <div class="bar-row">
        <div class="bar-label">Zonder EMS</div>
        <div class="bar-track">
          <div class="bar-fill shadow-fill" style="width:${(shadowToday/maxBar*100).toFixed(1)}%"></div>
        </div>
        <div class="bar-val" style="color:#f87171">${fmtEur(shadowToday)}</div>
      </div>
      <div class="bar-row">
        <div class="bar-label">Met CloudEMS</div>
        <div class="bar-track">
          <div class="bar-fill real-fill" style="width:${(costToday/maxBar*100).toFixed(1)}%"></div>
        </div>
        <div class="bar-val" style="color:#4ade80">${fmtEur(costToday)}</div>
      </div>
    </div>

    <div class="decisions-grid">
      <div class="dec-cell">
        <div class="dec-val">${totalDec.toLocaleString()}</div>
        <div class="dec-lbl">beslissingen</div>
      </div>
      <div class="dec-cell">
        <div class="dec-val">${totalEval.toLocaleString()}</div>
        <div class="dec-lbl">geëvalueerd</div>
      </div>
      <div class="dec-cell">
        <div class="dec-val">${pending}</div>
        <div class="dec-lbl">wachten</div>
      </div>
    </div>

    ${insight ? `<div class="insight">💡 ${insight}</div>` : ''}

    ${outcomes.length ? `
    <hr class="divider">
    <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
      color:rgba(163,163,163,.3);margin-bottom:6px">Recente uitkomsten</div>
    <div class="outcomes">
      ${outcomes.map(o => {
        const v = parseFloat(o.value_eur || 0);
        const pos = v >= 0;
        const comp = o.component || o.action || '—';
        const reason = o.reason || o.outcome || '';
        return `<div class="outcome-row">
          <div class="oc-dot" style="background:${pos ? '#4ade80' : '#f87171'}"></div>
          <div class="oc-action">${comp}${reason ? ` — ${reason}` : ''}</div>
          <div class="oc-val ${pos ? 'oc-pos' : 'oc-neg'}">${fmt(v)}</div>
        </div>`;
      }).join('')}
    </div>` : ''}

  </div>
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() {
    const el = document.createElement('cloudems-future-shadow-card-editor');
    return el;
  }
  static getStubConfig() { return {}; }
}

class CloudEMSFutureShadowCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; }
  connectedCallback() {
    if (!this.innerHTML) this.innerHTML = `<p style="font-size:12px;color:#aaa;padding:8px">Geen configuratie vereist.</p>`;
  }
}

if (!customElements.get('cloudems-future-shadow-card'))
  customElements.define('cloudems-future-shadow-card', CloudEMSFutureShadowCard);
if (!customElements.get('cloudems-future-shadow-card-editor'))
  customElements.define('cloudems-future-shadow-card-editor', CloudEMSFutureShadowCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-future-shadow-card',
  name: 'CloudEMS Future Shadow',
  description: 'Werkelijkheid vs zonder CloudEMS — besparing door slimme beslissingen',
  preview: true,
});
