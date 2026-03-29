/**
 * CloudEMS Learning Card  v1.0.0
 * Zelflerend — leervoortgang, anomalie, standby hunters, weerkalibratie, EV leermodel
 */
const LEARNING_VERSION = '5.4.96';

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// Progress bar helper
const progBar = (pct, col='#7dd3fc', h=6) => {
  const p = Math.min(100, Math.max(0, Math.round(pct)));
  const c = p >= 80 ? '#4ade80' : p >= 40 ? col : '#f87171';
  return `<div style="height:${h}px;background:rgba(255,255,255,0.07);border-radius:${h/2}px;overflow:hidden;margin-top:4px">
    <div style="height:100%;width:${p}%;background:${c};border-radius:${h/2}px;transition:width .4s"></div>
  </div>`;
};

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{display:block}*{box-sizing:border-box;margin:0;padding:0}
  .card{background:#0e1520;border-radius:16px;border:1px solid rgba(255,255,255,0.06);font-family:'Syne',sans-serif;overflow:hidden}

  /* Header */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid rgba(255,255,255,0.06);position:relative;overflow:hidden}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(128,222,234,0.05) 0%,transparent 60%);pointer-events:none}
  .hdr-icon{font-size:20px}
  .hdr-texts{flex:1}
  .hdr-title{font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.04em;text-transform:uppercase}
  .hdr-sub{font-size:11px;color:#6b7280;margin-top:2px}

  /* Modules grid */
  .modules{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(255,255,255,0.05);border-bottom:1px solid rgba(255,255,255,0.06)}
  .mod-tile{background:#0e1520;padding:12px 14px}
  .mod-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#374151;margin-bottom:6px}
  .mod-val{font-size:15px;font-weight:800;font-family:'JetBrains Mono',monospace;margin-bottom:2px}
  .mod-sub{font-size:10px;color:#4b5563}
  .c-green{color:#4ade80}.c-blue{color:#7dd3fc}.c-amber{color:#fbbf24}.c-red{color:#f87171}.c-muted{color:#4b5563}.c-purple{color:#a78bfa}

  /* Section header */
  .sec-hdr{display:flex;align-items:center;gap:8px;padding:10px 18px 4px}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#374151}
  .sec-line{flex:1;height:1px;background:rgba(255,255,255,0.05)}

  /* Anomalie block */
  .anomaly-block{margin:8px 18px;padding:12px 14px;border-radius:10px}
  .anomaly-ok{background:rgba(74,222,128,0.06);border:1px solid rgba(74,222,128,0.15)}
  .anomaly-warn{background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25)}
  .anomaly-title{font-size:12px;font-weight:700;margin-bottom:4px}
  .anomaly-row{display:flex;gap:16px;flex-wrap:wrap;margin-top:6px}
  .anomaly-kv{display:flex;flex-direction:column;gap:2px}
  .anomaly-k{font-size:9px;color:#374151;text-transform:uppercase;letter-spacing:.08em}
  .anomaly-v{font-size:12px;font-weight:700;font-family:'JetBrains Mono',monospace}

  /* Standby hunters */
  .hunters-list{padding:0 18px 10px}
  .hunter-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
  .hunter-row:last-child{border-bottom:none}
  .hunter-dot{width:6px;height:6px;border-radius:50%;background:#fbbf24;flex-shrink:0}
  .hunter-name{flex:1;font-size:11px;color:#9ca3af}
  .hunter-w{font-family:'JetBrains Mono',monospace;font-size:11px;color:#fbbf24}
  .hunter-time{font-size:10px;color:#374151}

  /* Weerkalibratie */
  .wk-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:0 18px 12px}
  .wk-tile{background:rgba(255,255,255,0.03);border-radius:8px;padding:8px 10px}
  .wk-lbl{font-size:9px;color:#374151;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
  .wk-val{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#7dd3fc}
  .wk-sub{font-size:9px;color:#4b5563;margin-top:2px}

  /* EV leermodel */
  .ev-row{display:flex;align-items:center;gap:12px;padding:8px 18px 12px}
  .ev-stat{display:flex;flex-direction:column;gap:2px;flex:1}
  .ev-lbl{font-size:9px;color:#374151;text-transform:uppercase;letter-spacing:.08em}
  .ev-val{font-size:14px;font-weight:800;font-family:'JetBrains Mono',monospace;color:#4ade80}

  /* Lege staat */
  .empty{padding:16px 18px;font-size:11px;color:#374151;font-style:italic}
`;

class CloudEMSLearningCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._prev='';}
  setConfig(c){this._cfg={title:'Zelflerend',...c};}

  set hass(h){
    this._hass=h;
    const sig=[
      h.states['sensor.cloudems_home_baseline_anomalie']?.last_changed,
      h.states['sensor.cloudems_standby_verbruik_altijd_aan']?.last_changed,
      h.states['sensor.cloudems_pv_weerkalibratie']?.last_changed,
      h.states['sensor.cloudems_ev_sessie_leermodel']?.last_changed,
      h.states['sensor.cloudems_dag_type_classificatie']?.last_changed,
      h.states['sensor.cloudems_solar_system_intelligence']?.last_changed,
    ].join('|');
    if(sig!==this._prev){this._prev=sig;this._render();}
  }

  _a(e,k,d=null){return this._hass?.states?.[e]?.attributes?.[k]??d;}
  _v(e,d='—'){const s=this._hass?.states?.[e];return s&&!['unavailable','unknown'].includes(s.state)?s.state:d;}

  _render(){
    const sh=this.shadowRoot; if(!sh||!this._hass) return;

    // ── Baseline / anomalie ───────────────────────────────────────────────
    const trainPct   = this._a('sensor.cloudems_home_baseline_anomalie','training_pct',0);
    const trainSlots = this._a('sensor.cloudems_home_baseline_anomalie','trained_slots',0);
    const anomaly    = this._a('sensor.cloudems_home_baseline_anomalie','anomaly',false);
    const curW       = this._a('sensor.cloudems_home_baseline_anomalie','current_w',0);
    const expW       = this._a('sensor.cloudems_home_baseline_anomalie','expected_w',0);
    const devW       = this._a('sensor.cloudems_home_baseline_anomalie','deviation_w',0);
    const aanMin     = this._a('sensor.cloudems_home_baseline_anomalie','aanhoudend_min',0);
    const modelReady = this._a('sensor.cloudems_home_baseline_anomalie','model_ready',false);
    const baseStatus = this._a('sensor.cloudems_home_baseline_anomalie','status','—');

    // ── Standby hunters ───────────────────────────────────────────────────
    const hunters    = this._a('sensor.cloudems_standby_verbruik_altijd_aan','suspicious_devices',[]) || [];
    const standbyW   = parseFloat(this._v('sensor.cloudems_standby_verbruik_altijd_aan','0')) || 0;

    // ── Weerkalibratie ────────────────────────────────────────────────────
    const wkPct      = this._a('sensor.cloudems_pv_weerkalibratie','progress_pct',0);
    const wkSamples  = this._a('sensor.cloudems_pv_weerkalibratie','global_samples',0);
    const wkConf     = this._a('sensor.cloudems_pv_weerkalibratie','global_confident',false);
    const wkInv      = this._a('sensor.cloudems_pv_weerkalibratie','inverters',[]) || [];

    // ── EV leermodel ──────────────────────────────────────────────────────
    const evSessions = this._a('sensor.cloudems_ev_sessie_leermodel','sessions_total',0);
    const evPredKwh  = this._a('sensor.cloudems_ev_sessie_leermodel','predicted_kwh');
    const evTypStart = this._a('sensor.cloudems_ev_sessie_leermodel','typical_start_hour');

    // ── Dag-type ──────────────────────────────────────────────────────────
    const dagType    = this._v('sensor.cloudems_dag_type_classificatie','—');
    const dagConf    = this._a('sensor.cloudems_dag_type_classificatie','confidence_pct',0);

    // ── Modules strip ─────────────────────────────────────────────────────
    const modulesHtml = `<div class="modules">
      <div class="mod-tile">
        <div class="mod-lbl">Baseline model</div>
        <div class="mod-val ${modelReady?'c-green':'c-amber'}">${Math.round(trainPct)}%</div>
        <div class="mod-sub">${trainSlots}/168 slots</div>
        ${progBar(trainPct,'#7dd3fc')}
      </div>
      <div class="mod-tile">
        <div class="mod-lbl">Weerkalibratie</div>
        <div class="mod-val ${wkConf?'c-green':'c-blue'}">${Math.round(wkPct)}%</div>
        <div class="mod-sub">${wkSamples}/30 samples</div>
        ${progBar(wkPct,'#7dd3fc')}
      </div>
      <div class="mod-tile">
        <div class="mod-lbl">EV sessies geleerd</div>
        <div class="mod-val c-purple">${evSessions}</div>
        <div class="mod-sub">${evPredKwh!=null?`~${parseFloat(evPredKwh).toFixed(1)} kWh voorspeld`:'nog aan het leren'}</div>
      </div>
      <div class="mod-tile">
        <div class="mod-lbl">Dag-type</div>
        <div class="mod-val c-blue" style="font-size:12px">${esc(dagType)}</div>
        <div class="mod-sub">${dagConf>0?Math.round(dagConf)+'% zekerheid':'geen data'}</div>
      </div>
    </div>`;

    // ── Anomalie block ────────────────────────────────────────────────────
    const anomalyHtml = `
      <div class="sec-hdr"><span class="sec-title">Verbruiksanomalie</span><div class="sec-line"></div></div>
      <div class="anomaly-block ${anomaly?'anomaly-warn':'anomaly-ok'}" style="margin-bottom:8px">
        <div class="anomaly-title" style="color:${anomaly?'#fbbf24':'#4ade80'}">${esc(baseStatus)}</div>
        ${modelReady?`<div class="anomaly-row">
          <div class="anomaly-kv"><div class="anomaly-k">Huidig</div><div class="anomaly-v" style="color:#fff">${Math.round(curW)} W</div></div>
          <div class="anomaly-kv"><div class="anomaly-k">Verwacht</div><div class="anomaly-v" style="color:#7dd3fc">${Math.round(expW)} W</div></div>
          ${anomaly?`<div class="anomaly-kv"><div class="anomaly-k">Afwijking</div><div class="anomaly-v" style="color:#fbbf24">+${Math.round(devW)} W · ${aanMin}min</div></div>`:''}
        </div>`:
        `<div style="font-size:11px;color:#4b5563;margin-top:4px">Model nog aan het leren — ${Math.round(trainPct)}% compleet (${168-trainSlots} slots resterend)</div>`}
      </div>`;

    // ── Standby hunters ───────────────────────────────────────────────────
    let huntersHtml = '';
    if(hunters.length > 0){
      const rows = hunters.slice(0,6).map(h=>`<div class="hunter-row">
        <div class="hunter-dot"></div>
        <span class="hunter-name">Weekdag ${h.weekday??'?'} · ${h.hour??'?'}:00</span>
        <span class="hunter-w">${Math.round(h.avg_w??0)} W</span>
      </div>`).join('');
      huntersHtml=`<div class="sec-hdr"><span class="sec-title">🔍 Standby hunters (${hunters.length})</span><div class="sec-line"></div></div>
        <div class="hunters-list">${rows}</div>`;
    } else if(standbyW > 0){
      huntersHtml=`<div class="sec-hdr"><span class="sec-title">🔍 Standby</span><div class="sec-line"></div></div>
        <div class="hunters-list">
          <div class="hunter-row">
            <div class="hunter-dot" style="background:#38bdf8"></div>
            <span class="hunter-name">Geschat altijd-aan verbruik</span>
            <span class="hunter-w" style="color:#38bdf8">${Math.round(standbyW)} W</span>
          </div>
          <div style="font-size:10px;color:#374151;padding:4px 0">✅ Geen verdachte apparaten gevonden</div>
        </div>`;
    }

    // ── Weerkalibratie ────────────────────────────────────────────────────
    const wkTiles = [
      {lbl:'Voortgang',val:Math.round(wkPct)+'%',sub:`${wkSamples} heldere dagen`},
      {lbl:'Status',val:wkConf?'✅ Klaar':'⏳ Leren',sub:wkConf?'Calibratie actief':'Nog '+Math.max(0,30-wkSamples)+' dagen nodig'},
      {lbl:'Omvormers',val:wkInv.length,sub:wkInv.map(i=>i.label||i.inverter_id||'?').join(' · ')||'—'},
    ].map(t=>`<div class="wk-tile">
      <div class="wk-lbl">${t.lbl}</div>
      <div class="wk-val">${esc(String(t.val))}</div>
      <div class="wk-sub">${esc(t.sub)}</div>
    </div>`).join('');

    const wkHtml=`<div class="sec-hdr"><span class="sec-title">☁️ PV Weerkalibratie</span><div class="sec-line"></div></div>
      <div class="wk-grid">${wkTiles}</div>`;

    // ── EV leermodel ──────────────────────────────────────────────────────
    const evHtml = evSessions > 0 ? `<div class="sec-hdr"><span class="sec-title">🚗 EV Leermodel</span><div class="sec-line"></div></div>
      <div class="ev-row">
        <div class="ev-stat"><div class="ev-lbl">Sessies geleerd</div><div class="ev-val">${evSessions}</div></div>
        ${evPredKwh!=null?`<div class="ev-stat"><div class="ev-lbl">Voorspeld gebruik</div><div class="ev-val c-blue">${parseFloat(evPredKwh).toFixed(1)} kWh</div></div>`:''}
        ${evTypStart!=null?`<div class="ev-stat"><div class="ev-lbl">Typisch start</div><div class="ev-val c-purple">${evTypStart}:00</div></div>`:''}
      </div>` : '';

    sh.innerHTML=`<style>${CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🧠</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(this._cfg.title)}</div>
          <div class="hdr-sub">Baseline ${Math.round(trainPct)}% · Weerkalibratie ${Math.round(wkPct)}% · ${evSessions} EV-sessies</div>
        </div>
      </div>
      ${modulesHtml}
      ${anomalyHtml}
      ${huntersHtml}
      ${wkHtml}
      ${evHtml}
    </div>`;
  }

  getCardSize(){return 8;}
  static getConfigElement(){return document.createElement('cloudems-learning-card-editor');}
  static getStubConfig(){return{title:'Zelflerend'};}
}

class CloudEMSLearningCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(c){this._cfg={...c};this._render();}
  _fire(){this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));}
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" value="${esc(cfg.title||'Zelflerend')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change',e=>{this._cfg={...this._cfg,title:e.target.value};this._fire();});
  }
}

if (!customElements.get('cloudems-learning-card')) customElements.define('cloudems-learning-card',CloudEMSLearningCard);
if (!customElements.get('cloudems-learning-card-editor')) customElements.define('cloudems-learning-card-editor',CloudEMSLearningCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-learning-card',name:'CloudEMS Learning Card',description:'Zelflerend — baseline, anomalie, standby hunters, weerkalibratie, EV'});
console.info('%c CLOUDEMS-LEARNING-CARD %c v'+LEARNING_VERSION+' ','background:#67e8f9;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#67e8f9;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
