// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Battery Card  v5.4.96

const BAT_VERSION = "5.4.96";
const BAT_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host {
    --b-bg:#0d1117;--b-surface:#161b22;--b-border:rgba(255,255,255,0.06);
    --b-green:#3fb950;--b-green-dim:rgba(63,185,80,0.12);
    --b-amber:#d29922;--b-amber-dim:rgba(210,153,34,0.12);
    --b-red:#f85149;--b-red-dim:rgba(248,81,73,0.12);
    --b-blue:#58a6ff;--b-blue-dim:rgba(88,166,255,0.10);
    --b-muted:#484f58;--b-subtext:#8b949e;--b-text:#e6edf3;
    --b-mono:'JetBrains Mono',monospace;--b-sans:'Syne',sans-serif;--b-r:14px;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--b-bg);border-radius:var(--b-r);border:1px solid var(--b-border);overflow:hidden;font-family:var(--b-sans);transition:border-color .3s,box-shadow .3s;}
  .card:hover{border-color:rgba(63,185,80,.18);box-shadow:0 8px 40px rgba(0,0,0,.7);}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid var(--b-border);position:relative;overflow:hidden;}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,var(--b-green-dim) 0%,transparent 60%);pointer-events:none;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--b-text);letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:var(--b-subtext);margin-top:2px;}
  .action-pill{font-family:var(--b-mono);font-size:10px;font-weight:600;padding:4px 10px;border-radius:20px;text-transform:uppercase;letter-spacing:.08em;margin-left:auto;}
  .action-pill.charge{background:var(--b-green-dim);color:var(--b-green);border:1px solid rgba(63,185,80,.25);}
  .action-pill.discharge{background:var(--b-amber-dim);color:var(--b-amber);border:1px solid rgba(210,153,34,.25);}
  .action-pill.idle{background:var(--b-blue-dim);color:var(--b-blue);border:1px solid rgba(88,166,255,.15);}
  .action-pill.forced_off{background:var(--b-red-dim);color:var(--b-red);border:1px solid rgba(248,81,73,.2);}
  .main-row{display:flex;align-items:center;padding:20px 20px 16px;border-bottom:1px solid var(--b-border);gap:4px;}
  .arc-wrap{position:relative;flex-shrink:0;width:130px;height:130px;}
  .arc-svg{display:block;overflow:visible;}
  .arc-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;}
  .arc-pct{font-family:var(--b-mono);font-size:28px;font-weight:700;line-height:1;}
  .arc-kwh{font-size:11px;color:var(--b-subtext);margin-top:4px;}
  .arc-cap{font-size:10px;color:var(--b-muted);margin-top:1px;}
  .stats-col{flex:1;padding-left:16px;display:flex;flex-direction:column;gap:12px;}
  .stat{display:flex;flex-direction:column;gap:2px;}
  .stat-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--b-muted);}
  .stat-val{font-family:var(--b-mono);font-size:15px;font-weight:600;color:var(--b-text);}
  .stat-val.pos{color:var(--b-green);}
  .stat-val.neg{color:var(--b-amber);}
  .stat-val.zero{color:var(--b-subtext);}
  .kwh-row{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--b-border);}
  .kwh-box{padding:10px 18px;display:flex;flex-direction:column;gap:3px;border-right:1px solid var(--b-border);}
  .kwh-box:last-child{border-right:none;}
  .kwh-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--b-muted);}
  .kwh-val{font-family:var(--b-mono);font-size:15px;font-weight:600;}
  .chart-section{padding:14px 18px;border-bottom:1px solid var(--b-border);}
  .chart-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;}
  .chart-title{font-size:11px;font-weight:700;color:var(--b-subtext);text-transform:uppercase;letter-spacing:.08em;}
  .range-btns{display:flex;gap:4px;}
  .range-btn{font-family:var(--b-mono);font-size:10px;padding:2px 8px;border-radius:10px;border:1px solid var(--b-border);background:none;color:var(--b-subtext);cursor:pointer;}
  .range-btn.active{background:var(--b-surface);color:var(--b-text);border-color:rgba(255,255,255,0.15);}
  .chart-stats{display:flex;gap:16px;margin-top:6px;font-family:var(--b-mono);font-size:10px;color:var(--b-muted);}
  .chart-legend{display:flex;gap:14px;margin-top:5px;font-size:10px;color:var(--b-subtext);}
  .legend-dot{width:8px;height:3px;border-radius:2px;display:inline-block;margin-right:4px;}
  .schedule-section{padding:10px 18px 12px;border-bottom:1px solid var(--b-border);}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--b-muted);margin-bottom:7px;}
  .timeline{display:flex;gap:2px;align-items:flex-end;height:32px;}
  .tl-cell{flex:1;border-radius:2px;min-height:4px;cursor:default;position:relative;transition:height .4s;}
  .tl-cell.charge{background:var(--b-green);}
  .tl-cell.discharge{background:var(--b-amber);}
  .tl-cell.idle{background:rgba(255,255,255,.06);height:4px!important;}
  .tl-cell.now{outline:1px solid var(--b-blue);outline-offset:1px;}
  .tl-labels{display:flex;justify-content:space-between;font-family:var(--b-mono);font-size:8px;color:var(--b-muted);margin-top:4px;}
  .providers-section{padding:10px 18px 12px;border-bottom:1px solid var(--b-border);}
  .prov-table{width:100%;border-collapse:collapse;font-size:12px;}
  .prov-table th{font-size:9px;color:var(--b-muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700;text-align:left;padding:0 8px 7px 0;border-bottom:1px solid var(--b-border);}
  .prov-table td{padding:8px 8px 4px 0;vertical-align:middle;color:var(--b-text);}
  .prov-table tr:last-child td{padding-bottom:2px;}
  .status-dot{width:7px;height:7px;border-radius:50%;background:var(--b-green);display:inline-block;margin-right:5px;}
  .interval-wrap{display:flex;align-items:center;gap:6px;}
  .interval-bar{width:44px;height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;flex-shrink:0;}
  .interval-fill{height:100%;border-radius:2px;background:var(--b-blue);transition:width 1s linear;}
  .retry-pips{display:flex;gap:3px;margin-top:4px;}
  .pip{width:7px;height:7px;border-radius:2px;}
  .pip.done{background:var(--b-green);}
  .pip.active{background:var(--b-amber);}
  .pip.todo{background:rgba(255,255,255,.08);}
  .zp-toggle{display:flex;align-items:center;justify-content:space-between;padding:10px 18px;cursor:pointer;border-bottom:1px solid var(--b-border);}
  .zp-toggle:hover{background:rgba(255,255,255,.02);}
  .zp-label{font-size:12px;font-weight:700;color:var(--b-text);display:flex;align-items:center;gap:8px;}
  .zp-badge{font-size:10px;padding:2px 8px;border-radius:10px;background:var(--b-green-dim);color:var(--b-green);}
  .zp-arrow{font-size:11px;color:var(--b-muted);transition:transform .2s;}
  .zp-body{overflow:hidden;transition:max-height .3s ease;}
  .zp-row{display:grid;grid-template-columns:110px 1fr;gap:8px;padding:7px 18px;border-bottom:1px solid var(--b-border);align-items:center;}
  .zp-row:last-child{border-bottom:none;}
  .zp-slider-row{padding:8px 18px;border-bottom:1px solid var(--b-border);}
  .zp-slider-label{font-size:11px;color:var(--b-subtext);margin-bottom:4px;display:flex;justify-content:space-between;}
  .zp-slider-label span{color:var(--b-text);font-weight:600;}
  .zp-range{width:100%;height:4px;-webkit-appearance:none;appearance:none;background:rgba(255,255,255,.1);border-radius:2px;outline:none;cursor:pointer;}
  .zp-range::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:#f0c040;cursor:pointer;}
  .zp-range:disabled{opacity:.3;cursor:default;}
  .zp-mode-row{padding:8px 18px;border-bottom:1px solid var(--b-border);display:flex;gap:6px;flex-wrap:wrap;}
  .zp-mode-btn{padding:4px 10px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:transparent;color:rgba(255,255,255,.5);font-size:10px;cursor:pointer;}
  .zp-mode-btn.active{background:rgba(240,192,64,.15);border-color:#f0c040;color:#f0c040;}
  .zp-key{font-size:12px;color:var(--b-subtext);}
  .zp-val{font-size:12px;color:var(--b-text);font-weight:600;}
  .zp-val.muted{color:var(--b-subtext);font-weight:400;}
  .zp-val.green{color:var(--b-green);}
  .dots{display:flex;gap:4px;align-items:center;}
  .dot{width:10px;height:10px;border-radius:50%;border:1.5px solid;}
  .dot.g{background:var(--b-green-dim);border-color:var(--b-green);}
  .dot.y{background:var(--b-amber-dim);border-color:var(--b-amber);}
  .dot.r{background:var(--b-red-dim);border-color:var(--b-red);}
  .reason{padding:10px 18px 12px;font-size:11.5px;color:var(--b-subtext);font-style:italic;line-height:1.6;border-top:1px solid var(--b-border);display:flex;gap:8px;align-items:flex-start;}
  .empty{padding:36px;text-align:center;color:var(--b-muted);display:flex;flex-direction:column;align-items:center;gap:12px;}
  .empty-icon{font-size:40px;opacity:.3;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
`;

const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const socColor = p => p>=60?'#3fb950':p>=30?'#d29922':'#f85149';
const actCls = a => { const s=(a||'').toLowerCase(); return s==='charge'||s==='laden'?'charge':s==='discharge'||s==='ontladen'?'discharge':s==='forced_off'||s==='uit'?'forced_off':'idle'; };
const actLabel = a => ({'charge':'⚡ Laden','laden':'⚡ Laden','discharge':'⬇ Ontladen','ontladen':'⬇ Ontladen','idle':'● Idle','hold':'● Idle','forced_off':'✕ Geblokkeerd'}[(a||'').toLowerCase()]||a||'Idle');

class CloudemsBatteryCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:'open'});
    this._prev='';
    this._zpOpen=true;
    this._intervalTick=null;
    this._chartData24=null;
    this._chartData6=null;
    this._chartRange=24;
  }
  setConfig(c){
    this._cfg={title:c.title??'Batterij',...c};
    this._render();
    // Force re-render na 3s — vangt startup op waar last_changed niet verandert
    setTimeout(()=>{ this._prev=''; this._render(); }, 3000);
  }
  set hass(h){
    this._hass=h;
    const soc=h.states['sensor.cloudems_battery_so_c'];
    const sch=h.states['sensor.cloudems_batterij_epex_schema']||h.states['sensor.cloudems_battery_schedule'];
    const pwr=h.states['sensor.cloudems_battery_power'];
    const zpSoc=sch?.attributes?.soc_pct??sch?.attributes?.zonneplan?.soc_pct??null;
    const j=JSON.stringify([soc?.state,soc?.last_changed,sch?.state,sch?.last_changed,zpSoc,pwr?.state]);
    if(j!==this._prev){this._prev=j;this._render();}
  }
  _staleWarning(sensorId, maxAgeMin=5) {
    const s = this._hass?.states[sensorId];
    if (!s?.last_updated) return '';
    const ageMin = (Date.now() - new Date(s.last_updated).getTime()) / 60000;
    if (ageMin < maxAgeMin) return '';
    return `<span style="font-size:9px;color:#f87171;opacity:0.7" title="Data is ${Math.round(ageMin)} min oud">⚠ ${Math.round(ageMin)}m oud</span>`;
  }
  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass, c=this._cfg??{};
    if(!h){ sh.innerHTML=`<style>${BAT_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">🔋</span></div></div>`; return; }

    // Data versheid
    const _batStale = this._staleWarning('sensor.cloudems_batterij_epex_schema', 5);
    const _zpStale  = this._staleWarning('sensor.cloudems_battery_decision', 5);
    const socS=h.states['sensor.cloudems_battery_so_c'];
    const pwrS=h.states['sensor.cloudems_battery_power'];
    const schS=h.states['sensor.cloudems_batterij_epex_schema']||h.states['sensor.cloudems_battery_schedule'];
    const zpAttr=h.states['sensor.cloudems_batterij_epex_schema']?.attributes||{};
    const zpSoc=zpAttr.soc_pct??zpAttr.zonneplan?.soc_pct??null;

    const socRaw=parseFloat(socS?.state);
    const socAvail=socS&&!isNaN(socRaw)&&socS.state!=='unavailable'&&socS.state!=='unknown';

    if(!socAvail&&zpSoc==null){
      const modOff=h.states['switch.cloudems_module_batterij']?.state==='off';
      const msg=modOff?'Batterij module staat uit — schakel in via Modules tab':'Geen batterij data beschikbaar. Even geduld na herstart...';
      sh.innerHTML=`<style>${BAT_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">🔋</span><span style="font-size:12px;color:rgba(255,255,255,0.4)">${msg}</span></div></div>`;
      return;
    }

    const soc=socAvail?socRaw:(zpSoc||0);
    const sA=socS?.attributes||{}, pA=pwrS?.attributes||{}, schA=schS?.attributes||{};
    const powerW=parseFloat(pwrS?.state)||0;
    const action=schS?.state||(powerW<-50?'charge':powerW>50?'discharge':'idle');
    const reason=schA.human_reason||schA.reason||sA.reason||'';
    const capKwh=parseFloat(sA.capacity_kwh)||0;
    const chargeKwh=parseFloat(pA.charge_kwh_today)||0;
    const disKwh=parseFloat(pA.discharge_kwh_today)||0;
    const schedule=schA.schedule||[];
    const zp=schA.zonneplan||{};
    const hasSliders   = zp.has_sliders || false;
    const hasCtrlMode  = zp.has_control_mode || false;
    const eidDeliver   = zp.entity_deliver_to_home || '';
    const eidSolar     = zp.entity_solar_charge || '';
    const eidCtrl      = zp.entity_control_mode || '';
    // Slider maxima: uit ZP entity attributen (meest betrouwbaar) → geleerde max → default
    const _deliverEid = zp.entity_deliver_to_home;
    const _solarEid   = zp.entity_solar_charge;
    const _deliverMax = _deliverEid ? parseFloat(h.states[_deliverEid]?.attributes?.max || 0) : 0;
    const _solarMax   = _solarEid   ? parseFloat(h.states[_solarEid]?.attributes?.max   || 0) : 0;
    const maxDeliver = _deliverMax > 100 ? _deliverMax : parseFloat(zp.learned_max_deliver_w || 6000);
    const maxSolar   = _solarMax   > 100 ? _solarMax   : parseFloat(zp.learned_max_solar_w  || 6000);
    // Current slider values from HA entities
    const curDeliver   = eidDeliver ? (parseFloat(h.states[eidDeliver]?.state)||0) : 0;
    const curSolar     = eidSolar   ? (parseFloat(h.states[eidSolar]?.state)||0)   : 0;
    const curMode      = eidCtrl    ? (h.states[eidCtrl]?.state||'')               : '';

    const ac=actCls(action);
    const color=socColor(soc);
    const socLow=soc<20;

    // Full circle arc
    const R=52,cx=65,cy=65;
    const circ=2*Math.PI*R;
    const offset=circ-(soc/100)*circ;

    const pwrStr=powerW<-50?`+${Math.round(Math.abs(powerW))} W`:powerW>50?`${Math.round(powerW)} W`:'0 W';
    const pwrCls=powerW<-50?'pos':powerW>50?'neg':'zero';
    const wear=parseFloat(zpAttr.forecast?.wear_cost_ct_per_kwh||0)||parseFloat(schA.wear_cost_ct||0)||0;

    // v4.6.571: tooltip variabelen
    const _TT = window.CloudEMSTooltip;
    const _balA = h.states['sensor.cloudems_energy_balancer']?.attributes||{};
    const _lagS  = _balA.battery_lag_learned_s;
    const _lagN  = _balA.battery_lag_samples||0;
    const _fastRamp = _balA.fast_ramp_active||false;
    const _fastEst  = _balA.fast_ramp_battery_est_w;
    const _bde  = schA.battery_decision||{};
    const _bdeAction = _bde.action||action||'idle';
    const _bdePrio   = _bde.priority;
    const _bdeConf   = _bde.confidence;
    const _bdeSrc    = _bde.source||'—';
    const _bdeExpl   = _bde.explain||'';
    const _socSrc    = socAvail ? 'sensor.cloudems_battery_so_c' : 'Zonneplan fallback';

    const _ttSoc = _TT ? _TT.html('bat-soc','Batterij SoC',[
      {label:'Sensor',    value:_socSrc},
      {label:'SoC',       value:soc.toFixed(1)+'%'},
      {label:'Capaciteit',value:capKwh ? capKwh.toFixed(1)+' kWh' : (sA.estimated_capacity_kwh ? '~'+parseFloat(sA.estimated_capacity_kwh).toFixed(1)+' kWh (lerende)' : '—')},
      {label:'Opgeslagen',value:capKwh?(capKwh*soc/100).toFixed(2)+' kWh':'—'},
      {label:'Leer-cycli',value:(()=>{const c=sA.capacity_cycles??0;const n=sA.capacity_cycles_needed??3;return c>=n?'✅ Klaar':c+' / '+n+' cycli (nog '+(n-c)+' nodig)';})(),dim:!(sA.capacity_cycles>=( sA.capacity_cycles_needed??3))},
      {label:'Bron',      value:socAvail?'● Directe sensor':'○ Zonneplan attribute',dim:!socAvail},
    ],{trusted:socAvail}) : {wrap:'',tip:''};

    const _ttPwr = _TT ? _TT.html('bat-pwr','Batterij vermogen',[
      {label:'Sensor',      value:'cloudems_battery_power'},
      {label:'Vermogen nu', value:pwrStr},
      {label:'Geleerde lag',value:_lagS!=null?_lagS.toFixed(1)+'s':'nog aan het leren'},
      {label:'Lag samples', value:_lagN.toString()},
      {label:'Fast-ramp',   value:_fastRamp?('actief · '+(_fastEst?Math.round(_fastEst)+' W est.':'')):'inactief',dim:!_fastRamp},
    ],{trusted:true}) : {wrap:'',tip:''};

    const _ttWear = _TT ? _TT.html('bat-wear','Slijtagekosten',[
      {label:'Waarde',  value:wear.toFixed(2)+' ct/kWh'},
      {label:'Formule', value:'Batterijprijs ÷ garantied cycli × 100',dim:true},
      {label:'Gebruik', value:'Verrekend in EPEX laad/ontlaad beslissing',dim:true},
    ],{footer:'Lager = goedkopere batterijslijtage per kWh doorvoer'}) : {wrap:'',tip:''};

    const _bdeChargeThr    = _bde.charge_threshold_eur;
    const _bdeDisThr       = _bde.discharge_threshold_eur;
    const _bdeNm           = _bde.net_metering_pct;
    const _ttDec = _TT ? _TT.html('bat-dec','BDE Beslissing',[
      {label:'Actie',             value:_bdeAction},
      {label:'Prioriteit',        value:_bdePrio!=null?_bdePrio.toString():'—'},
      {label:'Zekerheid',         value:_bdeConf!=null?((_bdeConf*100).toFixed(0)+'%'):'—'},
      {label:'Bron',              value:_bdeSrc},
      {label:'Reden',             value:_bdeExpl||reason||'—'},
      {label:'Laaddrempel',       value:_bdeChargeThr!=null?('≤ €'+(_bdeChargeThr*100).toFixed(1)+'/kWh'):'—', dim:true},
      {label:'Ontlaaddrempel',    value:_bdeDisThr!=null?('≥ €'+(_bdeDisThr*100).toFixed(1)+'/kWh'):'—', dim:true},
      {label:'Saldering',         value:_bdeNm!=null?((_bdeNm*100).toFixed(0)+'%'):'—', dim:true},
    ],{footer:'BDE = Battery Decision Engine — drempels worden geleerd via AI'}) : {wrap:'',tip:''};

    // Schedule timeline
    let tlHtml='';
    if(schedule.length>0){
      const slots=new Array(24).fill('idle');
      for(const s of schedule){
        const hh=parseInt((s.hour??s.time??'0').toString().split(':')[0]);
        if(hh>=0&&hh<24) slots[hh]=(s.action||'idle').toLowerCase();
      }
      const nowH=new Date().getHours();
      tlHtml=`<div class="schedule-section">
        <div class="sec-title">📅 Schema vandaag</div>
        <div class="timeline">${slots.map((a,i)=>{
          const cl=actCls(a);
          const ht=cl==='charge'?28:cl==='discharge'?20:4;
          return `<div class="tl-cell ${cl}${i===nowH?' now':''}" style="height:${ht}px" title="${i}:00 — ${a}"></div>`;
        }).join('')}</div>
        <div class="tl-labels"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
      </div>`;
    }

    // Providers table
    const bp=schA.battery_providers||{};
    const providers=bp.providers||[];
    let provHtml='';
    // Only show detected providers
    const visibleProviders = providers.filter(p => p.detected === true || p.available === true);
    if(visibleProviders.length>0){
      const provRows=visibleProviders.map((p,pi)=>{
        const intSec=parseInt(p.interval_s||p.interval||127);
        const maxSec=300;
        const retries=parseInt(p.retry_count||p.retries||3);
        const retryMax=parseInt(p.retry_max||5);
        const pips=Array.from({length:retryMax},(_, i)=>`<div class="pip ${i<retries-1?'done':i===retries-1?'active':'todo'}"></div>`).join('');
        const pLabel = p.provider_label || p.label || p.name || p.type || 'Provider';
        return `<tr>
          <td><span style="color:#d29922;margin-right:4px">⚡</span>${esc(pLabel)}</td>
          <td><span class="status-dot"></span>${p.available?'Actief':p.detected?'Gevonden':'Inactief'}</td>
          <td><span style="margin-right:3px">🏠</span>${esc(p.mode||zp.active_mode||'Thuisopt.').slice(0,8)}</td>
          <td>
            <div class="interval-wrap">
              <span id="iv-${pi}" style="font-family:var(--b-mono);font-size:11px;min-width:34px">${intSec}s</span>
              <div class="interval-bar"><div class="interval-fill" id="if-${pi}" style="width:${Math.min(100,intSec/maxSec*100)}%"></div></div>
            </div>
          </td>
          <td>
            <div style="font-size:10px;color:var(--b-subtext)">lerend</div>
            <div class="retry-pips">${pips}</div>
          </td>
        </tr>`;
      }).join('');
      provHtml=`<div class="providers-section">
        <div class="sec-title" style="margin-bottom:10px">Batterij providers</div>
        <table class="prov-table">
          <thead><tr>
            <th>Provider</th><th>Status</th><th>Modus</th><th>Interval</th><th>Vertraging</th>
          </tr></thead>
          <tbody>${provRows}</tbody>
        </table>
      </div>`;
    } else if(zp.detected){
      // Zonneplan fallback when no providers array but zp info available
      const intSec=127, maxSec=300;
      provHtml=`<div class="providers-section">
        <div class="sec-title" style="margin-bottom:10px">Batterij providers</div>
        <table class="prov-table">
          <thead><tr><th>Provider</th><th>Status</th><th>Modus</th><th>Interval</th><th>Vertraging</th></tr></thead>
          <tbody><tr>
            <td><span style="color:#d29922;margin-right:4px">⚡</span>Zonneplan Nexus</td>
            <td><span class="status-dot"></span>Actief</td>
            <td><span style="margin-right:3px">🏠</span>${esc((zp.active_mode||'Thuisopt.').slice(0,8))}</td>
            <td>
              <div class="interval-wrap">
                <span id="iv-0" style="font-family:var(--b-mono);font-size:11px;min-width:34px">${intSec}s</span>
                <div class="interval-bar"><div class="interval-fill" id="if-0" style="width:${intSec/maxSec*100}%"></div></div>
              </div>
            </td>
            <td><div style="font-size:10px;color:var(--b-subtext)">lerend</div><div class="retry-pips"><div class="pip done"></div><div class="pip done"></div><div class="pip active"></div><div class="pip todo"></div><div class="pip todo"></div></div></td>
          </tr></tbody>
        </table>
      </div>`;
    }

    // Zonneplan section
    const tariff=zp.tariff_group||'—';
    const zpDec=zp.forecast||{};
    const _recAction=zpDec.recommended_action||zpDec.action||schA.action||'';
    const _recLabels={'hold':'⏸ Wacht op PV','charge':'⚡ Laden','discharge':'⬇ Ontladen','powerplay':'🤖 Powerplay','idle':'○ Idle'};
    const actionStr=zpDec.action_label||_recLabels[_recAction]||_recAction||'—';
    const _epxS=h.states['sensor.cloudems_energy_epex_today'];
    const _epxA=_epxS?.attributes||{};
    const priceCt=(_epxA.current_price_display??parseFloat(h.states['sensor.cloudems_price_current_hour']?.state||0))*100||0;
    const _taxPer=(_epxA.tax_per_kwh||0)*100;
    const btw=21;
    const ebCt=_taxPer>0?_taxPer:priceCt/(1+btw/100);
    const fc8=zp.forecast?.forecast_8h||[];
    const dotCls=v=>v==='high'||v>0.7?'r':v==='medium'||v>0.4?'y':'g';
    const fc8html=fc8.length?`<div class="dots">${fc8.slice(0,8).map(v=>`<div class="dot ${dotCls(v)}"></div>`).join('')}</div>`:
      `<div class="dots">${Array.from({length:8},(_,i)=>i<3?'g':i<4?'y':'r').map(c=>`<div class="dot ${c}"></div>`).join('')}</div>`;
    const _rawAction=zpDec.action||schA.action||'';
    const _actionLabel={'hold':'⏸ Wacht op PV','charge':'⚡ Laden','discharge':'⬇ Ontladen','idle':'○ Idle'};
    const _modeLabels={'home_optimization':'⏸ Home opt.','self_consumption':'♻ Zelfcons.','powerplay':'🤖 Powerplay','manual_control':'✋ Handmatig','charge':'⚡ Laden','discharge':'⬇ Ontladen','hold':'⏸ Hold','idle':'○ Idle'};
    const _rawSent=zp.last_sent_str||'';
    const _sentLabel=_rawSent?(_modeLabels[_rawSent]||_rawSent.replace('hold (','').replace(')','')):'';
    const lastDec=_sentLabel||zp.last_decision_str||schA._last_decision_str||(_rawAction?_actionLabel[_rawAction]||_rawAction:'—');

    const zpHtml=`
      <div class="zp-toggle" id="zp-toggle">
        <span class="zp-label">Zonneplan sturing <span class="zp-badge">Actief</span></span>
        <span class="zp-arrow" id="zp-arrow">${this._zpOpen?'▲':'▼'}</span>
      </div>
      <div class="zp-body" id="zp-body" style="max-height:${this._zpOpen?'400px':'0'}">
        ${zp.manual_override_active?`
        <div class="zp-row" style="background:rgba(251,191,36,.08);border-radius:6px;padding:4px 8px;margin-bottom:4px">
          <span style="font-size:11px;color:#fbbf24">✋ Handmatige override: <strong>${esc(zp.manual_override_mode||'')}</strong> — nog ${zp.manual_override_min_left||0} min</span>
        </div>`:``}
        <div class="zp-row"><span class="zp-key">Modus</span><span class="zp-val">${(()=>{
          const _modeMap={'home_optimization':'🏠 Thuisoptimalisatie','self_consumption':'♻ Zelfconsumptie','powerplay':'🤖 Powerplay','manual_control':'✋ Handmatig'};
          const _m=zp.active_mode||'';
          return esc(_modeMap[_m]||_m||'Thuisoptimalisatie');
        })()}</span></div>
        <div class="zp-row"><span class="zp-key">Tariefgroep</span><span class="zp-val ${tariff==='LOW'||tariff==='low'?'green':''}">${esc(tariff)}</span></div>
        <div class="zp-row"><span class="zp-key">Beslissing</span><span class="zp-val">${esc(actionStr)} · ${esc(lastDec)}</span></div>
        <div class="zp-row"><span class="zp-key">Prijs (all-in)</span><span class="zp-val">€${priceCt.toFixed(1)} ct · EB ${ebCt.toFixed(1)} ct · BTW ${btw}%</span></div>
        <div class="zp-row"><span class="zp-key">Forecast 8u</span>${fc8html}</div>
        <div class="zp-row"><span class="zp-key">Laatste sturing</span><span class="zp-val muted">${esc(lastDec)} ${_batStale||_zpStale||''}</span></div>
        ${hasCtrlMode && eidCtrl ? `
        <div class="zp-mode-row" id="zp-mode-row">
          ${['home_optimization','self_consumption','powerplay'].map(m =>
            `<button class="zp-mode-btn ${curMode===m?'active':''}" data-mode="${m}">${
              m==='home_optimization'?'🏠 Thuisopt.':m==='self_consumption'?'♻ Zelfcons.':'🤖 Powerplay'
            }</button>`
          ).join('')}
        </div>`:''
        }
        ${hasSliders && eidDeliver ? `
        <div class="zp-slider-row">
          <div class="zp-slider-label">Levering thuis<span id="lbl-deliver">${Math.round(curDeliver)} W</span></div>
          <input class="zp-range" type="range" id="sl-deliver" min="0" max="${Math.round(maxDeliver)}" step="50" value="${Math.round(curDeliver)}"
            data-eid="${eidDeliver}"/>
        </div>`:''
        }
        ${hasSliders && eidSolar ? `
        <div class="zp-slider-row">
          <div class="zp-slider-label">Solar laden<span id="lbl-solar">${Math.round(curSolar)} W</span></div>
          <input class="zp-range" type="range" id="sl-solar" min="0" max="${Math.round(maxSolar)}" step="50" value="${Math.round(curSolar)}"
            data-eid="${eidSolar}"/>
        </div>`:''
        }
      </div>`;

    const sub=socLow?`⚠️ Laag — ${soc.toFixed(1)}%`:`${soc.toFixed(1)}% · ${capKwh?(capKwh*soc/100).toFixed(2)+' kWh opgeslagen':''}`;

    sh.innerHTML=`<style>${BAT_STYLES}</style>
    <div class="card">
      <div class="hdr">
        <div>
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub" style="color:${socLow?'var(--b-red)':'var(--b-subtext)'}">${esc(sub)}</div>
        </div>
        <span class="action-pill ${ac}">${actLabel(action)}</span>
      </div>
      <div class="main-row">
        <div class="arc-wrap" style="position:relative;cursor:default" ${_ttSoc.wrap}>
          <svg class="arc-svg" width="130" height="130" viewBox="0 0 130 130">
            <circle cx="65" cy="65" r="52" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="9"/>
            <circle cx="65" cy="65" r="52" fill="none" stroke="${color}" stroke-width="9"
              stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
              stroke-linecap="round" transform="rotate(-90 65 65)"/>
          </svg>
          <div class="arc-center">
            <span class="arc-pct" style="color:${color}">${soc.toFixed(0)}<span style="font-size:14px;color:var(--b-subtext)">%</span></span>
            ${capKwh?`<span class="arc-kwh">${(capKwh*soc/100).toFixed(2)} kWh</span><span class="arc-cap">van ${capKwh.toFixed(1)} kWh</span>`:''}
          </div>
          ${_ttSoc.tip}
        </div>
        <div class="stats-col">
          <div class="stat" style="position:relative;cursor:default" ${_ttPwr.wrap}><span class="stat-label">Vermogen</span><span class="stat-val ${pwrCls}">${esc(pwrStr)}</span>${_ttPwr.tip}</div>
          <div class="stat"><span class="stat-label">Capaciteit</span><span class="stat-val" style="font-size:13px">${capKwh?capKwh.toFixed(1)+' kWh':(sA.estimated_capacity_kwh?`~${parseFloat(sA.estimated_capacity_kwh).toFixed(1)} kWh`:'—')}</span></div>
          <div class="stat"><span class="stat-label">SoC doel</span><span class="stat-val">${schA.soc_target_pct!=null?schA.soc_target_pct+'%':zpDec.soc_target!=null?zpDec.soc_target+'%':'—'}</span></div>
          ${wear?`<div class="stat" style="position:relative;cursor:default" ${_ttWear.wrap}><span class="stat-label">Slijtage</span><span class="stat-val" style="font-size:13px">${wear.toFixed(2)} ct/kWh</span>${_ttWear.tip}</div>`:''}
        </div>
      </div>
      <div class="kwh-row">
        <div class="kwh-box"><span class="kwh-label">⚡ Geladen vandaag</span><span class="kwh-val" style="color:var(--b-green)">${chargeKwh.toFixed(2)} kWh</span></div>
        <div class="kwh-box"><span class="kwh-label">⬇ Ontladen vandaag</span><span class="kwh-val" style="color:var(--b-amber)">${disKwh.toFixed(2)} kWh</span></div>
      </div>
      <div class="chart-section" id="chart-section">
        <div class="chart-hdr">
          <span class="chart-title">Vermogen</span>
          <div class="range-btns">
            <button class="range-btn${this._chartRange===6?' active':''}" id="rb-6">6u</button>
            <button class="range-btn${this._chartRange===24?' active':''}" id="rb-24">24u</button>
          </div>
        </div>
        <div style="position:relative;height:80px"><canvas id="bat-chart" style="width:100%;height:80px"></canvas></div>
        <div class="chart-stats">
          <span>Min: <strong id="c-min">—</strong></span>
          <span>Max: <strong id="c-max">—</strong></span>
          <span>Gem: <strong id="c-avg">—</strong></span>
        </div>
        <div class="chart-legend">
          <span><span class="legend-dot" style="background:var(--b-green)"></span>Laden</span>
          <span><span class="legend-dot" style="background:var(--b-amber)"></span>Ontladen</span>
        </div>
      </div>
      ${tlHtml}
      ${provHtml}
      ${zpHtml}
      ${reason?`<div class="reason" style="position:relative;cursor:default" ${_ttDec.wrap}><span>💡</span><span>${esc(reason)}</span>${_ttDec.tip}</div>`:''}
    </div>`;

    // Bind events
    sh.querySelector('#zp-toggle')?.addEventListener('click',()=>{
      this._zpOpen=!this._zpOpen;
      const body=sh.querySelector('#zp-body');
      const arrow=sh.querySelector('#zp-arrow');
      if(body) body.style.maxHeight=this._zpOpen?'400px':'0';
      if(arrow) arrow.textContent=this._zpOpen?'▲':'▼';
    });
    sh.querySelector('#rb-6')?.addEventListener('click',()=>{this._chartRange=6;this._drawChart();sh.querySelector('#rb-6').classList.add('active');sh.querySelector('#rb-24').classList.remove('active');});

    // ── ZP Sliders ────────────────────────────────────────────────────────────
    const _callSvc = (domain, svc, data) => {
      this._hass?.callService(domain, svc, data);
    };

    // Slider: deliver_to_home
    const slDeliver = sh.getElementById('sl-deliver');
    if(slDeliver){
      slDeliver.addEventListener('input', e => {
        const lbl = sh.getElementById('lbl-deliver');
        if(lbl) lbl.textContent = Math.round(e.target.value) + ' W';
      });
      slDeliver.addEventListener('change', e => {
        const eid = slDeliver.dataset.eid;
        if(eid) _callSvc('number', 'set_value', {entity_id: eid, value: parseFloat(e.target.value)});
      });
    }

    // Slider: solar_charge
    const slSolar = sh.getElementById('sl-solar');
    if(slSolar){
      slSolar.addEventListener('input', e => {
        const lbl = sh.getElementById('lbl-solar');
        if(lbl) lbl.textContent = Math.round(e.target.value) + ' W';
      });
      slSolar.addEventListener('change', e => {
        const eid = slSolar.dataset.eid;
        if(eid) _callSvc('number', 'set_value', {entity_id: eid, value: parseFloat(e.target.value)});
      });
    }

    // Mode buttons
    sh.querySelectorAll('.zp-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const eid = sh.querySelector('#zp-mode-row')?.closest('[data-ctrl-eid]')?.dataset.ctrlEid
                 || this._hass?.states['sensor.cloudems_batterij_epex_schema']?.attributes?.zonneplan?.entity_control_mode
                 || '';
        if(eid) _callSvc('select', 'select_option', {entity_id: eid, option: btn.dataset.mode});
        // Optimistic UI update
        sh.querySelectorAll('.zp-mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
    sh.querySelector('#rb-24')?.addEventListener('click',()=>{this._chartRange=24;this._drawChart();sh.querySelector('#rb-24').classList.add('active');sh.querySelector('#rb-6').classList.remove('active');});

    // Start interval countdown animation
    this._startIntervalTick();

    // Herlaad historiek elke 5 min of als de dag veranderd is
    const today=new Date().toDateString();
    if(this._chartDay!==today){this._chartDay=today;this._chartData24=null;this._chartData6=null;}
    if(!this._chartData24||Date.now()-this._chartLoadedAt>5*60*1000){
      setTimeout(()=>this._initAndDrawChart(),50);
    } else {
      setTimeout(()=>this._drawChart(),50);
    }
  }

  _initAndDrawChart(){
    const h=this._hass;
    if(!h) return;
    // Gebruik sensor.cloudems_battery_power voor echte historiek
    const entity='sensor.cloudems_battery_power';
    const now=new Date();
    const start24=new Date(now.getTime()-24*3600*1000).toISOString();
    // HA history API: /api/history/period/<start>?filter_entity_id=<entity>&end_time=<end>&minimal_response=true
    h.callApi('GET',
      `history/period/${start24}?filter_entity_id=${entity}&end_time=${now.toISOString()}&minimal_response=true&significant_changes_only=false`
    ).then(result=>{
      const series=(result&&result[0])||[];
      if(series.length<2){ this._drawChart(); return; }
      // Resample naar ~144 punten (10-min intervals voor 24u)
      const resample=(pts)=>{
        const step=Math.max(1,Math.floor(series.length/pts));
        const out=[];
        for(let i=0;i<series.length;i+=step){
          const v=parseFloat(series[i].s??series[i].state);
          if(!isNaN(v)) out.push(Math.round(v));
        }
        return out.length>2?out:[0];
      };
      this._chartData24=resample(144);
      this._chartData6=resample(36);
      this._chartLoadedAt=Date.now();
      this._drawChart();
    }).catch(()=>{ this._drawChart(); });
  }

  _drawChart(){
    const sh=this.shadowRoot; if(!sh) return;
    const canvas=sh.getElementById('bat-chart'); if(!canvas) return;
    const data=this._chartRange===6?this._chartData6:this._chartData24;
    const dpr=window.devicePixelRatio||1;
    const W=canvas.offsetWidth||440, H=80;
    canvas.width=W*dpr; canvas.height=H*dpr;
    canvas.style.width=W+'px'; canvas.style.height=H+'px';
    const ctx=canvas.getContext('2d'); ctx.scale(dpr,dpr);
    const mn=Math.min(...data), mx=Math.max(...data), rng=mx-mn||1;
    const pad=12;
    const toY=v=>H-pad-((v-mn)/rng*(H-pad*2));
    const zY=toY(0);
    const green='#3fb950', amber='#d29922';
    const gridC='rgba(255,255,255,0.06)', txtC='rgba(255,255,255,0.25)';
    ctx.clearRect(0,0,W,H);
    [mn,0,mx].forEach(v=>{
      const y=toY(v);
      ctx.strokeStyle=gridC; ctx.lineWidth=0.5;
      ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
      const lbl=Math.abs(v)>=1000?`${(v/1000).toFixed(1)}k`:`${v}`;
      ctx.fillStyle=txtC; ctx.font='9px monospace'; ctx.fillText(lbl,2,y-3);
    });
    const xStep=(W-4)/(data.length-1);
    // Teken elk segment correct aan beide kanten van de nul-lijn
    // Bij zero-crossing: splits het segment op het exacte kruispunt
    const drawSeg=(ax,ay,bx,by,val)=>{
      if(Math.abs(val)<50){ return; }
      const c=val>0?green:amber;
      ctx.strokeStyle=c; ctx.lineWidth=1.5;
      ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by); ctx.stroke();
      const grad=ctx.createLinearGradient(0,Math.min(ay,zY),0,Math.max(ay,zY)+1);
      if(val>0){grad.addColorStop(0,c+'35');grad.addColorStop(1,'transparent');}
      else{grad.addColorStop(0,'transparent');grad.addColorStop(1,c+'35');}
      ctx.fillStyle=grad;
      ctx.beginPath(); ctx.moveTo(ax,zY); ctx.lineTo(ax,ay); ctx.lineTo(bx,by); ctx.lineTo(bx,zY); ctx.closePath(); ctx.fill();
    };
    for(let i=0;i<data.length-1;i++){
      const x0=2+i*xStep, y0=toY(data[i]);
      const x1=2+(i+1)*xStep, y1=toY(data[i+1]);
      const v0=data[i], v1=data[i+1];
      // Teken neutrale lijn altijd (als achtergrond)
      ctx.strokeStyle=gridC; ctx.lineWidth=0.5;
      ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y1); ctx.stroke();
      // Zit er een zero-crossing in dit segment?
      if((v0>50&&v1<-50)||(v0<-50&&v1>50)){
        // Bereken het exacte kruispunt
        const t=v0/(v0-v1); // 0..1 waar de waarde nul wordt
        const xZ=x0+(x1-x0)*t;
        // Eerste helft
        drawSeg(x0,y0,xZ,zY,v0);
        // Tweede helft
        drawSeg(xZ,zY,x1,y1,v1);
      } else {
        // Geen crossing: teken het hele segment in de juiste kleur
        const dominant=Math.abs(v0)>=Math.abs(v1)?v0:v1;
        drawSeg(x0,y0,x1,y1,dominant);
      }
    }
    const fmtKw=v=>`${v>=0?'+':''}${(v/1000).toFixed(1)} kW`;
    const minEl=this.shadowRoot?.getElementById('c-min');
    const maxEl=this.shadowRoot?.getElementById('c-max');
    const avgEl=this.shadowRoot?.getElementById('c-avg');
    if(minEl) minEl.textContent=fmtKw(Math.min(...data));
    if(maxEl) maxEl.textContent=fmtKw(Math.max(...data));
    if(avgEl) avgEl.textContent=fmtKw(Math.round(data.reduce((a,b)=>a+b,0)/data.length));
  }

  _startIntervalTick(){
    if(this._intervalTick) clearInterval(this._intervalTick);
    let sec=127;
    const max=180;
    this._intervalTick=setInterval(()=>{
      const sh=this.shadowRoot; if(!sh){clearInterval(this._intervalTick);return;}
      sec=Math.max(0,sec-1);
      const pct=((max-sec)/max*100).toFixed(0);
      const iv=sh.getElementById('iv-0');
      const ifl=sh.getElementById('if-0');
      if(iv) iv.textContent=sec+'s';
      if(ifl) ifl.style.width=pct+'%';
      if(sec===0) sec=max;
    },1000);
  }

  disconnectedCallback(){ if(this._intervalTick) clearInterval(this._intervalTick); }

  static getConfigElement(){ return document.createElement('cloudems-battery-card-editor'); }
  static getStubConfig(){ return {type:'cloudems-battery-card',title:'Batterij'}; }
  getCardSize(){ return 8; }
}

class CloudemsBatteryCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}.row:last-child{border-bottom:none;}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??'Batterij'}"></div></div>`;
    this.shadowRoot.querySelectorAll('input').forEach(el=>{
      el.addEventListener('change',()=>{ const nc={...this._cfg}; nc[el.name]=el.value; this._cfg=nc; this._fire(); });
    });
  }
}
if (!customElements.get('cloudems-battery-card-editor')) customElements.define('cloudems-battery-card-editor', CloudemsBatteryCardEditor);
if (!customElements.get('cloudems-battery-card')) customElements.define('cloudems-battery-card', CloudemsBatteryCard);
window.customCards=window.customCards??[];
if(!window.customCards.find(c=>c.type==='cloudems-battery-card'))
  window.customCards.push({type:'cloudems-battery-card',name:'CloudEMS Battery Card v3',description:'Batterij SoC arc, 24u grafiek, schema-tijdlijn, providers & Zonneplan sturing'});
console.info(`%c CLOUDEMS-BATTERY-CARD %c v${BAT_VERSION} `,'background:#3fb950;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0d1117;color:#3fb950;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
