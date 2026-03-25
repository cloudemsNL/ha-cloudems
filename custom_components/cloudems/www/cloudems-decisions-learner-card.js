// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Decision Outcome Learner Card v1.0

const DLC_VERSION = "5.3.31";
const DLC_SENSOR  = "sensor.cloudems_decision_learner";

const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

const COMP_ICON = { battery:"🔋", boiler:"🚿", ev:"🚗", heatpump:"♨️", shutter:"🪟" };
const COMP_NL   = { battery:"Batterij", boiler:"Boiler", ev:"EV", heatpump:"Warmtepomp", shutter:"Rolluiken" };
const ACTION_NL = {
  charge:"Laden", discharge:"Ontladen", hold:"Hold",
  hold_on:"Aan houden", hold_off:"Uit houden", turn_on:"Inschakelen",
  boost:"BOOST", green:"GREEN",
  solar:"Zonneladen", cheap:"Goedkoop laden", wait:"Wachten",
};

const STYLES = `
  :host{--dl-bg:#0d1117;--dl-surf:#161b22;--dl-bord:rgba(255,255,255,.07);
    --dl-text:#f0f6fc;--dl-muted:#7d8590;--dl-green:#3fb950;--dl-red:#f85149;
    --dl-blue:#58a6ff;--dl-yellow:#d29922;--dl-purple:#bc8cff;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--dl-bg);border-radius:12px;border:1px solid var(--dl-bord);
    font-family:'Syne',system-ui,sans-serif;overflow:hidden;color:var(--dl-text);}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid var(--dl-bord);background:rgba(88,166,255,.04);}
  .hdr-icon{font-size:20px;}
  .hdr-title{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:10px;color:var(--dl-muted);margin-top:1px;}
  .hdr-right{margin-left:auto;text-align:right;}
  .hdr-eur{font-size:18px;font-weight:700;color:var(--dl-green);font-family:monospace;}
  .hdr-eur.neg{color:var(--dl-red);}
  .hdr-eurl{font-size:9px;color:var(--dl-muted);}

  .insight{padding:10px 16px;border-bottom:1px solid var(--dl-bord);
    background:rgba(188,140,255,.05);font-size:11px;color:var(--dl-purple);
    display:flex;gap:8px;align-items:flex-start;line-height:1.5;}
  .insight-icon{flex-shrink:0;font-size:14px;}

  .tabs{display:flex;border-bottom:1px solid var(--dl-bord);}
  .tab{padding:8px 14px;font-size:11px;font-weight:600;cursor:pointer;
    border-bottom:2px solid transparent;color:var(--dl-muted);}
  .tab.active{color:var(--dl-blue);border-bottom-color:var(--dl-blue);}

  .section{padding:10px 16px;}
  .sec-lbl{font-size:9px;font-weight:700;text-transform:uppercase;
    letter-spacing:.1em;color:var(--dl-muted);margin-bottom:8px;}

  /* Stats row */
  .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;}
  .stat-box{background:var(--dl-surf);border-radius:8px;padding:8px 10px;text-align:center;}
  .stat-val{font-size:16px;font-weight:700;font-family:monospace;color:var(--dl-blue);}
  .stat-lbl{font-size:9px;color:var(--dl-muted);margin-top:2px;}

  /* Bias list */
  .bias-row{display:grid;grid-template-columns:22px 1fr 80px 50px;align-items:center;
    gap:6px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);}
  .bias-row:last-child{border-bottom:none;}
  .bias-comp{font-size:14px;}
  .bias-info{display:flex;flex-direction:column;gap:1px;}
  .bias-action{font-size:11px;font-weight:600;}
  .bias-bucket{font-size:9px;color:var(--dl-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .bias-bar-wrap{height:6px;background:rgba(255,255,255,.08);border-radius:3px;position:relative;}
  .bias-bar{height:6px;border-radius:3px;position:absolute;}
  .bias-bar.pos{background:var(--dl-green);left:50%;}
  .bias-bar.neg{background:var(--dl-red);right:50%;}
  .bias-val{font-size:10px;font-family:monospace;text-align:right;font-weight:700;}
  .bias-val.pos{color:var(--dl-green);}
  .bias-val.neg{color:var(--dl-red);}
  .bias-samples{font-size:9px;color:var(--dl-muted);}
  .not-ready{opacity:.4;}

  /* Outcomes list */
  .outcome-row{display:flex;gap:8px;align-items:flex-start;padding:7px 0;
    border-bottom:1px solid rgba(255,255,255,.04);}
  .outcome-row:last-child{border-bottom:none;}
  .out-icon{font-size:14px;flex-shrink:0;margin-top:1px;}
  .out-body{flex:1;min-width:0;}
  .out-title{font-size:11px;font-weight:600;}
  .out-detail{font-size:10px;color:var(--dl-muted);margin-top:1px;}
  .out-val{font-size:12px;font-family:monospace;font-weight:700;flex-shrink:0;}
  .out-val.pos{color:var(--dl-green);}
  .out-val.neg{color:var(--dl-red);}

  .empty{padding:20px;text-align:center;color:var(--dl-muted);font-size:12px;}
  .pending-badge{display:inline-block;background:rgba(210,153,34,.15);color:var(--dl-yellow);
    border-radius:10px;padding:1px 7px;font-size:9px;font-weight:700;margin-left:6px;}
`;

class CloudEMSDecisionsLearnerCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._tab = "biases";
  }

  set hass(h){
    this._hass = h;
    const s = h.states[DLC_SENSOR];
    const j = JSON.stringify([s?.state, s?.last_changed]);
    if(j !== this._prev){ this._prev = j; this._render(); }
  }

  _render(){
    const sh = this.shadowRoot;
    const h  = this._hass;
    if(!h){ sh.innerHTML=`<style>${STYLES}</style><div class="card"><div class="empty">Laden…</div></div>`; return; }

    const s  = h.states[DLC_SENSOR];
    const a  = s?.attributes || {};

    const totalEur     = parseFloat(a.total_value_eur || 0);
    const totalEval    = parseInt(a.total_evaluated   || 0);
    const totalDec     = parseInt(a.total_decisions   || 0);
    const pendingEval  = parseInt(a.pending_evaluations || 0);
    const insight      = a.top_insight || "Leerproces wordt opgebouwd…";
    const biases       = a.biases       || [];
    const outcomes     = (a.recent_outcomes || []).slice().reverse();

    const eurCls  = totalEur >= 0 ? "" : " neg";
    const eurSign = totalEur >= 0 ? "+" : "";

    sh.innerHTML = `<style>${STYLES}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🧠</span>
        <div>
          <div class="hdr-title">Decision Outcome Learner</div>
          <div class="hdr-sub">CloudEMS v${DLC_VERSION} · zelflerend beslissingsysteem</div>
        </div>
        <div class="hdr-right">
          <div class="hdr-eur${eurCls}">${eurSign}€${Math.abs(totalEur).toFixed(2)}</div>
          <div class="hdr-eurl">totaal geleerd voordeel</div>
        </div>
      </div>

      ${insight ? `<div class="insight">
        <span class="insight-icon">💡</span>
        <span>${esc(insight)}</span>
      </div>` : ""}

      <div class="section">
        <div class="stats">
          <div class="stat-box">
            <div class="stat-val">${totalDec}</div>
            <div class="stat-lbl">beslissingen</div>
          </div>
          <div class="stat-box">
            <div class="stat-val">${totalEval}</div>
            <div class="stat-lbl">geëvalueerd</div>
          </div>
          <div class="stat-box">
            <div class="stat-val">${pendingEval}</div>
            <div class="stat-lbl">wachten</div>
          </div>
        </div>
      </div>

      <div class="tabs">
        <div class="tab${this._tab==="biases"?" active":""}" data-tab="biases">
          Geleerde Biases${biases.filter(b=>b.ready).length ? ` (${biases.filter(b=>b.ready).length})` : ""}
        </div>
        <div class="tab${this._tab==="outcomes"?" active":""}" data-tab="outcomes">
          Uitkomsten${pendingEval ? `<span class="pending-badge">${pendingEval} wachtend</span>` : ""}
        </div>
      </div>

      <div class="section">
        ${this._tab === "biases" ? this._renderBiases(biases) : this._renderOutcomes(outcomes)}
      </div>
    </div>`;

    sh.querySelectorAll(".tab").forEach(t =>
      t.addEventListener("click", () => { this._tab = t.dataset.tab; this._render(); })
    );
  }

  _renderBiases(biases){
    if(!biases.length)
      return `<div class="empty">Nog geen biases geleerd.<br>Wacht op de eerste evaluaties.</div>`;

    const rows = biases.map(b => {
      const comp     = COMP_ICON[b.component] || "⚙️";
      const action   = ACTION_NL[b.action] || b.action;
      const bucket   = b.context_bucket.split(":").slice(1).join(" · ");
      const bias     = parseFloat(b.bias || 0);
      const isPos    = bias >= 0;
      const barPct   = Math.round(Math.min(Math.abs(bias), 1.0) * 50);
      const valCls   = isPos ? "pos" : "neg";
      const notReady = !b.ready ? " not-ready" : "";
      const eur      = parseFloat(b.value_eur || 0);
      const eurTxt   = (eur >= 0 ? "+" : "") + "€" + Math.abs(eur).toFixed(2);

      return `<div class="bias-row${notReady}">
        <span class="bias-comp">${comp}</span>
        <div class="bias-info">
          <span class="bias-action">${esc(COMP_NL[b.component] || b.component)} — ${esc(action)}</span>
          <span class="bias-bucket">${esc(bucket)}</span>
          <span class="bias-samples">${b.samples} samples · ${eurTxt}</span>
        </div>
        <div class="bias-bar-wrap">
          <div class="bias-bar ${isPos?"pos":"neg"}" style="width:${barPct}%"></div>
        </div>
        <div class="bias-val ${valCls}">${bias >= 0?"+":""}${(bias*100).toFixed(0)}%</div>
      </div>`;
    }).join("");

    return `<div class="sec-lbl">Bias per component · context</div>${rows}
    <div style="font-size:9px;color:var(--dl-muted);margin-top:8px;line-height:1.5">
      Groen = agressiever (drempel omlaag) · Rood = voorzichtiger (drempel omhoog) ·
      Minimaal ${5} samples voor toepassing
    </div>`;
  }

  _renderOutcomes(outcomes){
    if(!outcomes.length)
      return `<div class="empty">Nog geen uitkomsten beschikbaar.</div>`;

    const rows = outcomes.slice(0,10).map(o => {
      const comp    = COMP_ICON[o.component] || "⚙️";
      const action  = ACTION_NL[o.action] || o.action;
      const val     = parseFloat(o.decision_value || 0);
      const isPos   = val >= 0;
      const valTxt  = (isPos?"+":"") + "€" + Math.abs(val).toFixed(3);
      const ago     = this._ago(o.ts);
      const bucket  = (o.context_bucket || "").split(":").slice(1,4).join(" · ");

      return `<div class="outcome-row">
        <span class="out-icon">${comp}</span>
        <div class="out-body">
          <div class="out-title">${esc(COMP_NL[o.component] || o.component)} · ${esc(action)}</div>
          <div class="out-detail">${esc(bucket)} · ${ago}</div>
        </div>
        <div class="out-val ${isPos?"pos":"neg"}">${valTxt}</div>
      </div>`;
    }).join("");

    return `<div class="sec-lbl">Laatste uitkomsten</div>${rows}`;
  }

  _ago(ts){
    if(!ts) return "";
    const diff = Math.round((Date.now()/1000) - ts);
    if(diff < 60)    return `${diff}s geleden`;
    if(diff < 3600)  return `${Math.round(diff/60)}m geleden`;
    if(diff < 86400) return `${Math.round(diff/3600)}u geleden`;
    return `${Math.round(diff/86400)}d geleden`;
  }

  setConfig(c){ this._cfg = c; }
  getCardSize(){ return 4; }
  static getConfigElement(){ return document.createElement("cloudems-decisions-learner-card-editor"); }
  static getStubConfig(){ return {type:"custom:cloudems-decisions-learner-card"}; }
}

if (!customElements.get('cloudems-decisions-learner-card')) customElements.define("cloudems-decisions-learner-card", CloudEMSDecisionsLearnerCard);

class CloudEMSDecisionsLearnerCardEditor extends HTMLElement {
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    this.innerHTML = `<p style="padding:8px;color:#aaa;font-size:12px">Geen configuratie vereist. De kaart laadt automatisch van sensor.cloudems_decision_learner.</p>`;
  }
}
if (!customElements.get('cloudems-decisions-learner-card-editor')) customElements.define("cloudems-decisions-learner-card-editor", CloudEMSDecisionsLearnerCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "cloudems-decisions-learner-card",
  name: "CloudEMS Decision Learner",
  description: "Toont geleerde biases en beslissingsuitkomsten per component (batterij, boiler, EV)",
});
