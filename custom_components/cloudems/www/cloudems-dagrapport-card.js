// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Dagrapport Card v5.5.63

const DR_VERSION = "5.5.63";
const DR_STYLES = `
  :host{--dr-bg:#0d1117;--dr-border:rgba(255,255,255,.07);--dr-gold:#f0c040;
    --dr-green:#3fb950;--dr-blue:#60a5fa;--dr-red:#f85149;--dr-muted:rgba(255,255,255,.3);
    --dr-sub:rgba(255,255,255,.5);--dr-text:#e6edf3;--dr-mono:'JetBrains Mono',monospace;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--dr-bg);border-radius:14px;border:1px solid var(--dr-border);
    overflow:hidden;font-family:system-ui,sans-serif;}
  .hdr{padding:14px 18px 12px;border-bottom:1px solid var(--dr-border);
    background:linear-gradient(135deg,rgba(240,192,64,.08) 0%,transparent 60%);
    display:flex;align-items:center;justify-content:space-between;}
  .hdr-left{display:flex;flex-direction:column;gap:2px;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--dr-text);text-transform:uppercase;letter-spacing:.05em;}
  .hdr-date{font-size:11px;color:var(--dr-muted);}
  .hdr-score{font-family:var(--dr-mono);font-size:28px;font-weight:700;color:var(--dr-gold);}
  .hdr-score-lbl{font-size:9px;color:var(--dr-muted);text-align:right;}
  /* KPI grid */
  .kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid var(--dr-border);}
  .kpi{padding:12px 10px;border-right:1px solid var(--dr-border);text-align:center;}
  .kpi:last-child{border-right:none;}
  .kpi-lbl{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--dr-muted);margin-bottom:3px;}
  .kpi-val{font-family:var(--dr-mono);font-size:15px;font-weight:700;color:var(--dr-text);}
  .kpi-sub{font-size:9px;color:var(--dr-muted);margin-top:2px;}
  /* Bar sectie */
  .bar-section{padding:12px 16px;border-bottom:1px solid var(--dr-border);}
  .bar-row{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
  .bar-row:last-child{margin-bottom:0;}
  .bar-lbl{font-size:10px;color:var(--dr-sub);width:90px;flex-shrink:0;}
  .bar-track{flex:1;height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;}
  .bar-fill{height:100%;border-radius:3px;transition:width .6s ease;}
  .bar-val{font-family:var(--dr-mono);font-size:10px;color:var(--dr-text);width:52px;text-align:right;flex-shrink:0;}
  /* Top apparaten */
  .dev-section{padding:10px 16px 12px;border-bottom:1px solid var(--dr-border);}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--dr-muted);margin-bottom:8px;}
  .dev-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.03);}
  .dev-row:last-child{border-bottom:none;}
  .dev-name{font-size:11px;color:var(--dr-sub);}
  .dev-kwh{font-family:var(--dr-mono);font-size:11px;font-weight:600;color:var(--dr-text);}
  /* Vergelijk */
  .compare-section{padding:10px 16px 12px;}
  .compare-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;}
  .compare-lbl{font-size:11px;color:var(--dr-sub);}
  .compare-val{font-family:var(--dr-mono);font-size:11px;font-weight:700;}
  .pos{color:var(--dr-green);}
  .neg{color:var(--dr-red);}
  .neu{color:var(--dr-muted);}
  .empty{padding:32px;text-align:center;color:var(--dr-muted);font-size:12px;}
`;

const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const fmtKwh = v => v!=null ? `${parseFloat(v).toFixed(1)} kWh` : '—';
const fmtEur = v => v!=null ? `€${parseFloat(v).toFixed(2)}` : '—';

class CloudemsDagrapportCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:'open'});
    this._hass=null;
    this._prev='';
  }
  setConfig(c){ this._cfg=c||{}; }
  set hass(h){
    this._hass=h;
    const sc=h.states['sensor.cloudems_self_consumption'];
    const j=JSON.stringify([sc?.state,sc?.last_changed,Math.floor(Date.now()/30000)]);
    if(j!==this._prev){this._prev=j;this._render();}
  }

  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass; if(!h) return;
    try{ this._renderInner(h,sh); }
    catch(e){ sh.innerHTML=`<style>${DR_STYLES}</style><div class="card"><div class="empty">⚠️ ${e.message}</div></div>`; }
  }

  _renderInner(h,sh){
    // Sensoren
    const scS   = h.states['sensor.cloudems_self_consumption'];
    const p1S   = h.states['sensor.cloudems_p1_power'];
    const wdgS  = h.states['sensor.cloudems_watchdog'];  // bevat daily_summary_yesterday
    const nilmS = h.states['sensor.cloudems_nilm_running_devices'];
    const priceS= h.states['sensor.cloudems_energy_cost'];
    const solS  = h.states['sensor.cloudems_solar_system_intelligence']??h.states['sensor.cloudems_solar_system'];
    const batS  = h.states['sensor.cloudems_batterij_epex_schema']??h.states['sensor.cloudems_battery_schedule'];

    const scA   = scS?.attributes||{};
    const ystData = wdgS?.attributes?.daily_summary_yesterday || {};
    const p1A   = p1S?.attributes||{};
    const prA   = priceS?.attributes||{};

    // Vandaag data
    const pvKwh     = parseFloat(scA.pv_today_kwh||0);
    const importKwh = parseFloat(p1A.electricity_import_today_kwh||scA.import_today_kwh||0);
    const exportKwh = parseFloat(p1A.electricity_export_today_kwh||scA.export_today_kwh||0);
    const selfConsumePct = parseFloat(scS?.state||0);
    const costToday = parseFloat(prA.cost_today_eur||0);
    const costMonth = parseFloat(prA.cost_month_eur||0);
    const earnedToday = parseFloat(scA.earned_today_eur||exportKwh*0.08||0);

    // NILM top-5 apparaten
    const nilmDevs = (nilmS?.attributes?.devices||[])
      .filter(d => (d.energy_today_kwh||d.energy?.today_kwh||0) > 0.01)
      .sort((a,b)=>(b.energy_today_kwh||b.energy?.today_kwh||0)-(a.energy_today_kwh||a.energy?.today_kwh||0))
      .slice(0,5);

    // Zelfconsumptie score (0-100)
    const score = Math.min(100, Math.round(selfConsumePct));
    const scoreColor = score>=75?'#3fb950':score>=50?'#f0c040':'#f85149';

    // Datum
    const today = new Date().toLocaleDateString('nl',{weekday:'long',day:'numeric',month:'long'});

    // Max voor bars
    const totalKwh = pvKwh + importKwh;
    const maxBar   = Math.max(totalKwh, 1);

    sh.innerHTML=`<style>${DR_STYLES}</style>
    <div class="card">
      <!-- Header -->
      <div class="hdr">
        <div class="hdr-left">
          <div class="hdr-title">📋 Dagrapport</div>
          <div class="hdr-date">${esc(today)}</div>
        </div>
        <div style="text-align:right;">
          <div class="hdr-score" style="color:${scoreColor}">${score}<span style="font-size:16px">%</span></div>
          <div class="hdr-score-lbl">zelfconsumptie</div>
        </div>
      </div>

      <!-- KPI grid -->
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-lbl">Opgewekt</div>
          <div class="kpi-val" style="color:#f0c040">${pvKwh.toFixed(1)}</div>
          <div class="kpi-sub">kWh</div>
        </div>
        <div class="kpi">
          <div class="kpi-lbl">Kosten</div>
          <div class="kpi-val" style="color:${costToday<=0?'#3fb950':costToday<2?'#f0c040':'#f85149'}">${fmtEur(costToday)}</div>
          <div class="kpi-sub">vandaag</div>
        </div>
        <div class="kpi">
          <div class="kpi-lbl">Maand</div>
          <div class="kpi-val">${fmtEur(costMonth)}</div>
          <div class="kpi-sub">tot nu toe</div>
        </div>
      </div>

      <!-- Energiebalans bars -->
      <div class="bar-section">
        <div class="bar-row">
          <div class="bar-lbl">☀️ Opgewekt</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100,pvKwh/maxBar*100).toFixed(0)}%;background:#f0c040"></div></div>
          <div class="bar-val">${fmtKwh(pvKwh)}</div>
        </div>
        <div class="bar-row">
          <div class="bar-lbl">⚡ Geïmporteerd</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100,importKwh/maxBar*100).toFixed(0)}%;background:#f85149"></div></div>
          <div class="bar-val">${fmtKwh(importKwh)}</div>
        </div>
        <div class="bar-row">
          <div class="bar-lbl">↩️ Teruggeleverd</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100,exportKwh/maxBar*100).toFixed(0)}%;background:#60a5fa"></div></div>
          <div class="bar-val">${fmtKwh(exportKwh)}</div>
        </div>
        ${earnedToday>0?`<div class="bar-row">
          <div class="bar-lbl">💰 Opbrengst</div>
          <div class="bar-track"><div class="bar-fill" style="width:80%;background:#3fb950"></div></div>
          <div class="bar-val">${fmtEur(earnedToday)}</div>
        </div>`:''}
      </div>

      <!-- Top apparaten -->
      ${nilmDevs.length?`<div class="dev-section">
        <div class="sec-title">⚡ Top verbruikers vandaag</div>
        ${nilmDevs.map(d=>{
          const kwh=parseFloat(d.energy_today_kwh||d.energy?.today_kwh||0);
          return `<div class="dev-row">
            <div class="dev-name">${esc(d.name||d.label||'Apparaat')}</div>
            <div class="dev-kwh">${kwh.toFixed(2)} kWh</div>
          </div>`;
        }).join('')}
      </div>`:''}

      <!-- Vergelijking gisteren -->
      <div class="compare-section">
        <div class="sec-title">📊 Vandaag vs gisteren</div>
        ${ystData.date ? `<div style="font-size:10px;color:rgba(255,255,255,.3);margin-bottom:8px">${esc(ystData.date)}</div>` : ''}
        <div class="compare-row">
          <div class="compare-lbl">Zelfconsumptie</div>
          <div style="display:flex;gap:8px;align-items:center">
            <div class="compare-val ${score>=70?'pos':score>=40?'neu':'neg'}">${score}%</div>
            ${ystData.self_cons_pct!=null?`<div style="font-size:10px;color:rgba(255,255,255,.3)">gist: ${ystData.self_cons_pct}%</div>`:''}
          </div>
        </div>
        <div class="compare-row">
          <div class="compare-lbl">Opgewekt</div>
          <div style="display:flex;gap:8px;align-items:center">
            <div class="compare-val neu">${pvKwh.toFixed(1)} kWh</div>
            ${ystData.pv_kwh!=null?`<div style="font-size:10px;color:rgba(255,255,255,.3)">gist: ${ystData.pv_kwh} kWh</div>`:''}
          </div>
        </div>
        <div class="compare-row">
          <div class="compare-lbl">Kosten</div>
          <div style="display:flex;gap:8px;align-items:center">
            <div class="compare-val ${costToday<=0?'pos':costToday<2?'neu':'neg'}">${fmtEur(costToday)}</div>
            ${ystData.cost_eur!=null?`<div style="font-size:10px;color:rgba(255,255,255,.3)">gist: ${fmtEur(ystData.cost_eur)}</div>`:''}
          </div>
        </div>
        <div class="compare-row">
          <div class="compare-lbl">Kosten maand</div>
          <div class="compare-val ${costMonth<50?'pos':costMonth<100?'neu':'neg'}">${fmtEur(costMonth)}</div>
        </div>
      </div>
    </div>`;
  }

  static getConfigElement(){ return document.createElement('cloudems-dagrapport-card-editor'); }
  static getStubConfig(){ return {type:'cloudems-dagrapport-card'}; }
  getCardSize(){ return 6; }
}

class CloudemsDagrapportCardEditor extends HTMLElement {
  setConfig(c){ this._c=c||{}; }
  set hass(h){}
  connectedCallback(){
    this.innerHTML=`<div style="padding:12px;font-family:system-ui;color:#ccc;font-size:12px;">
      Geen configuratie nodig — leest automatisch alle CloudEMS sensoren.
    </div>`;
  }
}

if(!customElements.get('cloudems-dagrapport-card-editor'))
  customElements.define('cloudems-dagrapport-card-editor',CloudemsDagrapportCardEditor);
if(!customElements.get('cloudems-dagrapport-card'))
  customElements.define('cloudems-dagrapport-card',CloudemsDagrapportCard);

window.customCards=window.customCards||[];
if(!window.customCards.find(c=>c.type==='cloudems-dagrapport-card'))
  window.customCards.push({type:'cloudems-dagrapport-card',name:'CloudEMS Dagrapport',description:'Dagelijkse energiesamenvatting'});

console.info(`%c CLOUDEMS-DAGRAPPORT-CARD %c v${DR_VERSION} `,'background:#f0c040;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0d1117;color:#f0c040;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
