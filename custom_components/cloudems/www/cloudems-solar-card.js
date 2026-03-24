// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Solar Card  v2.1.1

const SOL_VERSION = "2.1.1";
const SOL_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host {
    --sl-bg:#0c1409;--sl-surface:#121a0e;--sl-border:rgba(255,255,255,0.06);
    --sl-gold:#f0c040;--sl-gold-dim:rgba(240,192,64,0.10);
    --sl-green:#86efac;--sl-green-dim:rgba(134,239,172,0.08);
    --sl-orange:#fb923c;--sl-clip:#ef4444;
    --sl-muted:#3d5229;--sl-subtext:#86a876;--sl-text:#f0fdf4;
    --sl-mono:'JetBrains Mono',monospace;--sl-sans:'Syne',sans-serif;--sl-r:14px;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--sl-bg);border-radius:var(--sl-r);border:1px solid var(--sl-border);overflow:hidden;font-family:var(--sl-sans);transition:border-color .3s,box-shadow .3s;}
  .card:hover{border-color:rgba(240,192,64,.2);box-shadow:0 8px 40px rgba(0,0,0,.7);}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid var(--sl-border);position:relative;overflow:hidden;}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,var(--sl-gold-dim) 0%,transparent 60%);pointer-events:none;}
  .hdr-icon{font-size:18px;flex-shrink:0;}
  .hdr-texts{flex:1;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--sl-text);letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:var(--sl-subtext);margin-top:2px;}
  .hdr-watt{font-family:var(--sl-mono);font-size:20px;font-weight:700;color:var(--sl-gold);}
  .hdr-watt span{font-size:11px;color:var(--sl-muted);margin-left:2px;}
  .top-strip{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid var(--sl-border);}
  .top-box{padding:12px 14px;border-right:1px solid var(--sl-border);display:flex;flex-direction:column;gap:3px;text-align:center;}
  .top-box:last-child{border-right:none;}
  .top-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--sl-muted);}
  .top-val{font-family:var(--sl-mono);font-size:16px;font-weight:600;color:var(--sl-text);}
  .top-sub{font-size:10px;color:var(--sl-muted);margin-top:2px;}
  .clip-banner{padding:7px 18px;background:rgba(239,68,68,.12);border-bottom:1px solid rgba(239,68,68,.2);font-size:11px;font-weight:600;color:#f87171;display:flex;align-items:center;gap:6px;}
  .alert-banner{padding:8px 16px;font-size:11px;font-weight:600;display:flex;align-items:center;gap:8px;border-bottom:1px solid transparent;}
  .alert-red{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.2);color:#f87171;}
  .alert-yellow{background:rgba(245,158,11,.1);border-color:rgba(245,158,11,.2);color:#fbbf24;}
  .alert-orange{background:rgba(255,128,64,.1);border-color:rgba(255,128,64,.2);color:#ff8040;}
  .sec{border-top:1px solid var(--sl-border);padding:12px 16px;}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--sl-muted);margin-bottom:8px;}
  .yield-section{padding:12px 18px 0;border-bottom:1px solid var(--sl-border);}
  .fc-nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
  .fc-nav-btn{background:none;border:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.4);border-radius:5px;padding:2px 8px;font-size:10px;cursor:pointer;font-family:var(--sl-font);}
  .fc-nav-btn:hover{border-color:rgba(255,255,255,.3);color:#fff;}
  .fc-nav-lbl{text-align:center;}
  .fc-nav-day{font-size:12px;font-weight:700;color:var(--sl-text);}
  .fc-nav-sub{font-size:9px;color:#3d5229;}
  .fc-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-bottom:8px;}
  .fc-stat{background:rgba(255,255,255,.04);border-radius:5px;padding:4px 6px;text-align:center;}
  .fc-stat-l{font-size:8px;color:rgba(255,255,255,.35);margin-bottom:1px;}
  .fc-stat-v{font-size:11px;font-weight:700;}
  .fc-legend{display:flex;gap:10px;margin-bottom:6px;}
  .fc-leg{display:flex;align-items:center;gap:4px;font-size:9px;color:rgba(255,255,255,.4);}
  .fc-leg-dot{width:8px;height:5px;border-radius:1px;}
  .fc-bars{display:flex;align-items:flex-end;gap:1px;height:60px;position:relative;}
  .fc-grp{display:flex;align-items:flex-end;gap:0;flex:1;position:relative;}
  .fc-bar{border-radius:1px 1px 0 0;transition:height .3s;}
  .fc-now{position:absolute;top:0;bottom:0;left:50%;width:1px;background:#f0c040;z-index:3;}
  .fc-now-dot{width:5px;height:5px;border-radius:50%;background:#f0c040;position:absolute;top:-2px;left:-2px;}
  .fc-xlbl{display:flex;justify-content:space-between;font-size:8px;color:rgba(255,255,255,.2);padding:2px 0 6px;}
    .fc-nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px;}
  .fc-nav-btn{background:none;border:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.4);border-radius:5px;padding:2px 8px;font-size:10px;cursor:pointer;font-family:var(--sl-font);}
  .fc-nav-btn:hover{border-color:rgba(255,255,255,.3);color:#fff;}
  .fc-nav-day{font-size:12px;font-weight:700;color:var(--sl-text);text-align:center;}
  .fc-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:7px;}
  .fc-stat{background:rgba(255,255,255,.04);border-radius:5px;padding:4px 6px;text-align:center;}
  .fc-stat-l{font-size:8px;color:rgba(255,255,255,.35);margin-bottom:1px;}
  .fc-stat-v{font-size:11px;font-weight:700;}
  .fc-legend{display:flex;gap:10px;margin-bottom:5px;}
  .fc-leg{display:flex;align-items:center;gap:4px;font-size:9px;color:rgba(255,255,255,.4);}
  .fc-leg-dot{width:8px;height:5px;border-radius:1px;}
  .fc-bars{display:flex;align-items:flex-end;gap:1px;height:60px;position:relative;}
  .fc-grp{display:flex;align-items:flex-end;flex:1;position:relative;}
  .fc-bar{border-radius:1px 1px 0 0;}
  .fc-now{position:absolute;top:0;bottom:0;left:50%;width:1px;background:#f0c040;z-index:3;}
  .fc-now-dot{width:5px;height:5px;border-radius:50%;background:#f0c040;position:absolute;top:-2px;left:-2px;}
  .fc-xlbl{display:flex;justify-content:space-between;font-size:8px;color:rgba(255,255,255,.2);padding:2px 0 5px;}
    .yield-grid{display:flex;gap:2px;align-items:flex-end;height:48px;}
  .yield-col{display:flex;flex-direction:column;align-items:center;flex:1;gap:2px;}
  .yield-bar{border-radius:2px 2px 0 0;width:100%;min-height:2px;transition:height .5s ease;}
  .yield-bar.now{outline:1px solid var(--sl-gold);outline-offset:1px;}
  .yield-label-row{display:flex;justify-content:space-between;padding:3px 0 8px;font-family:var(--sl-mono);font-size:8px;color:var(--sl-muted);}
  .inv-section{padding:10px 18px 12px;border-bottom:1px solid var(--sl-border);}
  .inv-row{padding:6px 0;border-bottom:1px solid rgba(255,255,255,.03);animation:fadeUp .35s ease both;}
  .inv-row:last-child{border-bottom:none;}
  .inv-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
  .inv-name{font-size:12px;font-weight:600;color:var(--sl-text);}
  .inv-pwr{font-family:var(--sl-mono);font-size:13px;font-weight:600;color:var(--sl-gold);}
  .util-bar{height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;margin-bottom:5px;position:relative;}
  .util-fill{height:100%;border-radius:2px;transition:width .8s ease;}
  .util-ceil{position:absolute;top:0;width:2px;height:100%;background:#f59e0b;opacity:.7;}
  .inv-chips{display:flex;flex-wrap:wrap;gap:4px;}
  .chip{font-family:var(--sl-mono);font-size:9px;padding:2px 7px;border-radius:10px;background:rgba(255,255,255,.06);color:var(--sl-subtext);border:1px solid var(--sl-border);}
  .chip.phase{background:rgba(134,239,172,.08);color:var(--sl-green);border-color:rgba(134,239,172,.2);}
  .chip.clip{background:rgba(239,68,68,.12);color:#f87171;border-color:rgba(239,68,68,.2);}
  .chip.orient{background:var(--sl-gold-dim);color:var(--sl-gold);border-color:rgba(240,192,64,.2);}
  .summary-table{width:100%;border-collapse:collapse;font-size:12px;}
  .summary-table td{padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);}
  .summary-table tr:last-child td{border-bottom:none;}
  .summary-table .lbl{color:rgba(255,255,255,.45);}
  .summary-table .val{text-align:right;font-weight:600;}
  .clip-bar-wrap{background:rgba(255,255,255,.06);border-radius:3px;height:6px;overflow:hidden;margin:4px 0 2px;position:relative;}
  .clip-bar-fill{height:100%;border-radius:3px;transition:width .8s;}
  .clip-bar-ceil{position:absolute;top:0;width:2px;height:100%;background:#f59e0b;opacity:.7;}
  .clip-row{margin-bottom:12px;}
  .clip-row:last-child{margin-bottom:0;}
  .clip-row-top{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;}
  .clip-row-bot{display:flex;justify-content:space-between;font-size:10px;color:rgba(255,255,255,.3);margin-top:2px;}
  .shadow-note{font-size:11px;color:rgba(255,255,255,.4);font-style:italic;line-height:1.6;margin-bottom:8px;}
  .tab-bar{display:flex;gap:6px;padding:10px 12px 0;background:rgba(0,0,0,.3);border-bottom:2px solid rgba(255,255,255,.06);}
  .tab-btn{flex:1;padding:9px 8px 10px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;
    color:rgba(255,255,255,.45);background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);
    border-bottom:3px solid transparent;border-radius:8px 8px 0 0;cursor:pointer;
    transition:all .15s;white-space:nowrap;}
  .tab-btn:hover{color:rgba(255,255,255,.75);background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.15);}
  .tab-btn.active{color:#ffd600;background:rgba(255,214,0,.1);border-color:rgba(255,214,0,.25);border-bottom-color:#ffd600;font-size:12px;}
  @keyframes pulse-tab{0%,100%{border-bottom-color:rgba(251,146,60,.4);color:rgba(255,255,255,.45);}50%{border-bottom-color:#fb923c;color:#fb923c;background:rgba(251,146,60,.08);}}
  .tab-btn.dimmer-active{animation:pulse-tab 1.5s ease-in-out infinite;}
  .tab-btn.dimmer-active.active{animation:none;}
  .tab-pane{display:none;}
  .tab-pane.active{display:block;}
  .accuracy{display:flex;align-items:center;gap:8px;padding:8px 18px;font-size:11px;color:var(--sl-subtext);border-top:1px solid var(--sl-border);}
  .acc-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
  .empty{padding:36px;text-align:center;color:var(--sl-muted);display:flex;flex-direction:column;align-items:center;gap:12px;}
  .empty-icon{font-size:40px;opacity:.3;}
  @keyframes fadeUp{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
`;

const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const compassLabel = a => { const labels=["N","NNO","NO","ONO","O","OZO","ZO","ZZO","Z","ZZW","ZW","WZW","W","WNW","NW","NNW"]; return labels[Math.round(((a%360)+360)%360/22.5)%16]||"?"; };
const fmt = (w,thr=1000) => Math.abs(w)>=thr?(w/1000).toFixed(2)+" kW":Math.round(w)+" W";

class CloudemsSolarCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._prev="";
    this._startupTimer=null;
  }
  setConfig(c){
    this._cfg={title:c.title??"Zonnepanelen",...c};
    this._render();
    if(this._startupTimer) clearTimeout(this._startupTimer);
    this._startupTimer=setTimeout(()=>{ this._prev=""; this._render(); }, 3000);
    setTimeout(()=>{ this._prev=""; this._render(); }, 8000);
  }
  set hass(h){
    this._hass=h;
    const sol = h.states["sensor.cloudems_solar_system_intelligence"] ?? h.states["sensor.cloudems_solar_system"];
    const fc  = h.states["sensor.cloudems_solar_pv_forecast_today"]   ?? h.states["sensor.cloudems_pv_forecast_today"];
    const mod = h.states["switch.cloudems_module_solar_learner"];
    const invCount=(sol?.attributes?.inverters||[]).length;
    const invHash=invCount>0?(sol.attributes.inverters||[]).map(i=>i.current_w).join(","):"";
    const j=JSON.stringify([sol?.state,sol?.last_changed,fc?.state,fc?.last_changed,mod?.state,invCount,invHash]);
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
    if(!h){ sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">☀️</span></div></div>`; return; }

    const solS = h.states["sensor.cloudems_solar_system_intelligence"] ?? h.states["sensor.cloudems_solar_system"];
    const fcS  = h.states["sensor.cloudems_solar_pv_forecast_today"]   ?? h.states["sensor.cloudems_pv_forecast_today"];
    const fcTS = h.states["sensor.cloudems_solar_pv_forecast_tomorrow"]?? h.states["sensor.cloudems_pv_forecast_tomorrow"];
    const accS = h.states["sensor.cloudems_solar_pv_forecast_accuracy"]?? h.states["sensor.cloudems_pv_forecast_accuracy"];
    const scS  = h.states["sensor.cloudems_self_consumption"];
    const sdS  = h.states["sensor.cloudems_schaduwdetectie"] ?? h.states["sensor.cloudems_shadow_detection"];
    const clS  = h.states["sensor.cloudems_clipping_verlies"]?? h.states["sensor.cloudems_clipping_loss"];
    const pkS  = h.states["sensor.cloudems_solar_pv_forecast_peak_today"] ?? h.states["sensor.cloudems_pv_forecast_peak_today"];

    const hasInverters = (solS?.attributes?.inverters||[]).length > 0;
    const moduleOn = h.states["switch.cloudems_module_solar_learner"]?.state === "on";
    if((!solS||solS.state==="unavailable"||solS.state==="unknown") && !hasInverters && !moduleOn){
      sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="hdr"><span class="hdr-icon">☀️</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:rgba(251,146,60,.7)">⚠️ Geen omvormer geconfigureerd</div></div></div><div class="empty"><span class="empty-icon">☀️</span>Configureer een omvormer via CloudEMS instellingen.</div></div>`;
      return;
    }
    if((!solS||solS.state==="unavailable"||solS.state==="unknown") && !hasInverters){
      sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="hdr"><span class="hdr-icon">☀️</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:var(--sl-subtext)">⏳ Laden...</div></div></div></div>`;
      return;
    }

    const sA=solS?.attributes||{};
    const totalW=parseFloat(solS?.state)||0;
    const inverters=sA.inverters||[];
    const peakW=sA.total_peak_w||0;
    const clipping=sA.clipping_active||false;

    const fcA=fcS?.attributes||{};
    const fcKwh=parseFloat(fcS?.state||0)||0;
    const _solarStale = this._staleWarning('sensor.cloudems_solar_system_intelligence', 5)
                     || this._staleWarning('sensor.cloudems_solar_system', 5);
    const fcTomKwh=parseFloat(fcTS?.state||0)||0;
    const fcHourly=fcA.hourly||[];
    const fcTomHourly=(fcTS?.attributes?.hourly_tomorrow)||[];
    // v4.6.492: werkelijke productie per uur vandaag — uit backend (persistent over reload)
    const nowH=new Date().getHours();
    const _backendHourly = fcA.actual_hourly_kwh || null;
    if(_backendHourly && _backendHourly.length === 24){
      // Backend data beschikbaar — gebruik die (persistent, herstart-bestendig)
      // Houd in-memory fallback in sync zodat bij korte onderbreking data behouden blijft
      this._pvHist = _backendHourly.slice();
      this._pvHistDay = new Date().getDate();
    } else {
      // Fallback: in-memory accumulatie (werkt alleen zolang pagina open is)
      if(!this._pvHist) this._pvHist = new Array(24).fill(0);
      if(!this._pvHistDay) this._pvHistDay = new Date().getDate();
      if(new Date().getDate() !== this._pvHistDay){ this._pvHist = new Array(24).fill(0); this._pvHistDay = new Date().getDate(); }
      const _kwh_inc = totalW / 1000 * (10/3600);
      if(_kwh_inc > 0) this._pvHist[nowH] = (this._pvHist[nowH] || 0) + _kwh_inc;
    }
    const actualHourly = this._pvHist;
    // Gisteren: gebruik pv_forecast_accuracy hourly_actual_kwh als die beschikbaar is,
    // anders solar_learner actual_kwh_per_hour. hourly_peak_w is GEEN gisteren-data.
    const lrn = h.states['sensor.cloudems_solar_system_intelligence']?.attributes?.inverters || [];
    const accAttr = accS?.attributes || {};
    const yesterdayRef = new Array(24).fill(0);
    // Probeer echte gisteren-uurdata uit accuracy sensor
    const _ystHourly = accAttr.yesterday_hourly_kwh || accAttr.actual_hourly_kwh || null;
    if(_ystHourly && typeof _ystHourly === 'object') {
      Object.entries(_ystHourly).forEach(([hr,kwh]) => {
        yesterdayRef[parseInt(hr)] = (yesterdayRef[parseInt(hr)]||0) + parseFloat(kwh||0);
      });
    } else {
      // Fallback: gebruik actual_kwh_per_hour uit learner als die beschikbaar is
      lrn.forEach(inv => {
        const akh = inv.actual_kwh_per_hour || inv.hourly_actual_kwh || {};
        if(Object.keys(akh).length > 0) {
          Object.entries(akh).forEach(([hr,kwh]) => {
            yesterdayRef[parseInt(hr)] = (yesterdayRef[parseInt(hr)]||0) + parseFloat(kwh||0);
          });
        }
        // hourly_peak_w is piek-vermogen, NIET energie — niet gebruiken voor gisteren
      });
    }
    if(!this._chartDay) this._chartDay = 'today';

    // Self-consumption
    const scA=scS?.attributes||{};
    const scPct=(()=>{
      const stored=parseFloat(scS?.state||0)||0;
      if(stored>0) return stored;
      // Fallback: instant ratio from coordinator data
      const pvW=parseFloat(solS?.attributes?.solar_power_w||0)||0;
      const expW=parseFloat(solS?.attributes?.export_power_w||0)||0;
      if(pvW>50) return Math.max(0,Math.min(100,Math.round((pvW-expW)/pvW*1000)/10));
      return 0;
    })();
    const pvTodayKwh = (scA.pv_today_kwh != null && scA.pv_today_kwh !== undefined)
      ? scA.pv_today_kwh : fcKwh;
    const selfKwh=scA.self_consumed_kwh ?? null;
    const exportKwh=scA.exported_kwh ?? null;
    const bestHour=scA.best_solar_hour;
    const monthSaving=scA.monthly_saving_eur;

    // Shadow
    const sdA=sdS?.attributes||{};
    const shadowAny=sdA.any_shadow||false;
    const shadowSummary=sdA.summary||"Onvoldoende data voor schaduwanalyse.";
    const shadowLost=parseFloat(sdS?.state||0)||0;
    const shadowInvs=sdA.inverters||[];

    // Clipping
    const clA=clS?.attributes||{};
    const clipInvs=clA.inverters||[];
    const clipLostEur=clA.total_eur_lost_year||0;
    const clipWorst=clA.worst_inverter||"";
    const clipAdvice=clA.advice||"";
    const clipAny=clA.any_curtailment||false;

    // Peak hour
    const peakHour=pkS?.attributes?.peak_hour??null;

    // Accuracy
    const accErr=parseFloat(accS?.attributes?.last_day_error_pct??0);
    const accCol=accErr<15?"#86efac":accErr<30?"#fbbf24":"#f87171";

    // ── Forecast bars — gisteren/vandaag/morgen navigatie ────────────────────
    const _cd_key = this._chartDay || 'today';
    const _fcByDay = {
      yesterday: { label:'Gisteren', isTomorrow:false, isToday:false,
        fc: yesterdayRef, ac: yesterdayRef },
      today: { label:'Vandaag', isTomorrow:false, isToday:true,
        fc: (() => { const arr=new Array(24).fill(0); fcHourly.forEach(x=>{ const h=x?.hour??-1; if(h>=nowH&&h<24) arr[h]+=((x?.forecast_w??x?.wh??0)/1000); }); return arr; })(),
        ac: actualHourly },
      tomorrow: { label:'Morgen', isTomorrow:true, isToday:false,
        fc: (() => { const arr=new Array(24).fill(0); fcTomHourly.forEach(x=>{ const h=x?.hour??-1; if(h>=0&&h<24) arr[h]+=((x?.forecast_w??x?.wh??0)/1000); }); return arr; })(), ac:[] },
    };
    const _cd = _fcByDay[_cd_key];
    const _fcA = _cd.fc; const _acA = _cd.ac.length?_cd.ac:new Array(24).fill(0);
    const _ysA = _cd.isToday ? yesterdayRef : new Array(24).fill(0);
    const _mxV = Math.max(..._fcA,..._acA,..._ysA,0.01);
    const _BH = 60;
    const _nKwh = _cd.isToday?(_acA[nowH]||0):0;
    const _fKwh = _cd.isToday?(_fcA[nowH]||0):0;
    const _totF=_fcA.reduce((a,b)=>a+b,0), _totA=_acA.reduce((a,b)=>a+b,0);
    // v4.6.492: afwijking proportioneel op verstreken minuten van het uur
    // v4.6.506: gebruik sensor attribute minutes_into_hour voor proportionele verwachting
    const _nowMin = parseInt(fcA.minutes_into_hour ?? new Date().getMinutes());
    const _hourFrac = Math.max(_nowMin/60, 0.01);
    // "Verwacht tot nu" = fractie van het uurforecast op basis van verstreken minuten
    const _fKwhSoFar = _fKwh * _hourFrac;
    const _difNow = _fKwhSoFar>0.001?Math.round((_nKwh-_fKwhSoFar)/_fKwhSoFar*100):0;
    const _fmtKwh = v => v>=0.1?v.toFixed(2)+' kWh':(v*1000).toFixed(0)+' Wh';
    const _stHtml = _cd.isToday
      ? `<div class="fc-stat"><div class="fc-stat-l">Uur ${nowH} (${_nowMin}min)</div><div class="fc-stat-v" style="color:#f0c040">${_fmtKwh(_nKwh)}</div></div>
         <div class="fc-stat"><div class="fc-stat-l">Verwacht tot nu</div><div class="fc-stat-v" style="color:#86efac">${_fmtKwh(_fKwhSoFar)}<span style="font-size:8px;color:rgba(255,255,255,.3)"> (vol: ${_fmtKwh(_fKwh)})</span></div></div>
         <div class="fc-stat"><div class="fc-stat-l">Afwijking</div><div class="fc-stat-v" style="color:${_difNow>=0?'#34d399':'#f87171'}">${_nowMin<5?'—':(_difNow>=0?'+':'')+_difNow+'%'}</div></div>`
      : _cd.isTomorrow
      ? `<div class="fc-stat" style="grid-column:1/-1"><div class="fc-stat-l">Verwacht totaal morgen</div><div class="fc-stat-v" style="color:#86efac">${_totF.toFixed(1)} kWh</div></div>`
      : `<div class="fc-stat"><div class="fc-stat-l">Werkelijk</div><div class="fc-stat-v" style="color:#f0c040">${_totA.toFixed(1)} kWh</div></div>
         <div class="fc-stat"><div class="fc-stat-l">Verwacht was</div><div class="fc-stat-v" style="color:rgba(255,255,255,.5)">${_totF.toFixed(1)} kWh</div></div>
         <div class="fc-stat"><div class="fc-stat-l">Afwijking</div><div class="fc-stat-v" style="color:${_totF>0&&(_totA-_totF)/_totF>=0?'#34d399':'#f87171'}">${_totF>0?((_totA-_totF)/_totF>=0?'+':'')+Math.round((_totA-_totF)/_totF*100)+'%':'—'}</div></div>`;

        const _bH = Array.from({length:24},(_,i)=>{
      const isNow=_cd.isToday&&i===nowH, isPast=_cd.isToday&&i<nowH;
      const fh=Math.max((_fcA[i]||0)/_mxV*_BH,(_fcA[i]||0)>0?1:0);
      const ah=Math.max((_acA[i]||0)/_mxV*_BH,(_acA[i]||0)>0?1:0);
      const yh=Math.max((_ysA[i]||0)/_mxV*_BH,(_ysA[i]||0)>0?1:0);
      const fcBg=isNow?'rgba(134,239,172,.6)':isPast?'rgba(134,239,172,.12)':'rgba(134,239,172,.4)';
      const acBg=isNow?'#f0c040':isPast?'rgba(240,192,64,.5)':'rgba(240,192,64,.12)';
      return `<div class="fc-grp">
        <div class="fc-bar" style="width:33%;height:${fh.toFixed(1)}px;background:${fcBg}"></div>
        <div class="fc-bar" style="width:33%;height:${ah.toFixed(1)}px;background:${acBg}"></div>
        ${_cd.isToday?`<div class="fc-bar" style="width:33%;height:${yh.toFixed(1)}px;background:rgba(240,192,64,.15)"></div>`:'<div class="fc-bar" style="width:33%;height:0"></div>'}
        ${isNow?'<div class="fc-now"><div class="fc-now-dot"></div></div>':''}
      </div>`;
    }).join('');
    const _prevLbl = _cd_key==='today'?'Gisteren':_cd_key==='tomorrow'?'Vandaag':'';
    const _nextLbl = _cd_key==='today'?'Morgen':_cd_key==='yesterday'?'Vandaag':'';
    const yieldHtml = `<div class="yield-section">
      <div class="sec-title">☀️ Forecast per uur</div>
      <div class="fc-nav">
        <button class="fc-nav-btn" data-fcnav="prev" style="${_cd_key==='yesterday'?'opacity:.3;pointer-events:none':''}">← ${_prevLbl}</button>
        <div class="fc-nav-lbl"><div class="fc-nav-day">${_cd.label}</div></div>
        <button class="fc-nav-btn" data-fcnav="next" style="${_cd_key==='tomorrow'?'opacity:.3;pointer-events:none':''}${!fcTomHourly.length&&_cd_key==='today'?'opacity:.3;pointer-events:none':''}">${_nextLbl} →</button>
      </div>
      <div class="fc-stats">${_stHtml}</div>
      <div class="fc-legend">
        <div class="fc-leg"><div class="fc-leg-dot" style="background:rgba(134,239,172,.5)"></div>Verwacht</div>
        <div class="fc-leg"><div class="fc-leg-dot" style="background:#f0c040"></div>Werkelijk</div>
        ${_cd.isToday?'<div class="fc-leg"><div class="fc-leg-dot" style="background:rgba(240,192,64,.2)"></div>Gisteren</div>':''}
      </div>
      <div class="fc-bars">${_bH}</div>
      <div class="fc-xlbl"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
    </div>`;

    // ── Inverters ─────────────────────────────────────────────────────────────
    let invHtml="", clippingHtml="";
    if(inverters.length>0){
      // Omvormer + benutting samengevoegd
      invHtml=`<div class="inv-section">
        <div class="sec-title">Omvormers (${inverters.length})</div>
        ${inverters.map((inv,i)=>{
          const w=parseFloat(inv.current_w)||0;
          const peak=inv.peak_w||inv.rated_power_w||inv.estimated_wp||0;
          const util=peak?Math.min(Math.round(w/peak*100),100):0;
          const utilCol=util>85?"#f59e0b":util>40?"#86efac":"rgba(134,239,172,.3)";
          const az=inv.azimuth_learned??inv.azimuth_compass??null;
          const tilt=inv.tilt_deg;
          const phase=inv.phase_display||inv.phase;
          const clip=inv.clipping;
          const orientConf=inv.orientation_confident;
          const ceiling=inv.clipping_ceiling_w||peak;
          const ceilPct=peak?Math.min(Math.round(ceiling/peak*100),100):100;
          return `<div class="inv-row" style="animation-delay:${i*.06}s">
            <div class="inv-top">
              <span class="inv-name">☀️ ${esc(inv.label||`Omvormer ${i+1}`)}</span>
              <span class="inv-pwr" style="color:#f0c040">${Math.round(w)} W${clip?" ⚡":""}</span>
            </div>
            <div class="util-bar-wrap" style="position:relative;margin-bottom:3px">
              <div class="util-bar"><div class="util-fill" style="width:${util}%;background:${utilCol}"></div></div>
              ${ceilPct<100?`<div style="position:absolute;top:0;bottom:0;left:${ceilPct}%;width:2px;background:rgba(248,113,113,.6)"></div>`:""}
            </div>
            <div style="display:flex;justify-content:space-between;font-size:9px;color:rgba(255,255,255,.3);margin-bottom:4px">
              <span>${util}% benut</span>
              <span>${peak?Math.round(peak)+" W":"—"}</span>
            </div>
            <div class="inv-chips">
              ${peak?`<span class="chip">${Math.round(inv.estimated_wp||peak)} Wp</span>`:""}
              ${az!==null?`<span class="chip orient" title="${orientConf?'Bevestigd':'Nog aan het leren'}">${compassLabel(az)} ${Math.round(az)}°${orientConf?"":(" ~"+(inv.orientation_progress_pct!=null?` (${inv.orientation_progress_pct}%)`:""))}</span>`:``}
              ${tilt?`<span class="chip">∠${Math.round(tilt)}°</span>`:""}
              ${phase?`<span class="chip phase">Fase ${esc(phase)}</span>`:`<span class="chip">Fase unknown</span>`}
            </div>
          </div>`;
        }).join("")}
        ${clipAdvice?`<div style="font-size:10px;color:rgba(255,255,255,.3);font-style:italic;margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,.04)">${esc(clipAdvice)}</div>`:""}
      </div>`;
    }

    // ── PV Samenvatting ───────────────────────────────────────────────────────
    const _TTS = window.CloudEMSTooltip;
    const _ttPvNu = _TTS ? _TTS.html('sl-pvnu','PV vermogen nu',[
      {label:'Sensor',    value:'cloudems_solar_system'},
      {label:'Vermogen',  value:Math.round(totalW)+' W'},
      {label:'Piek 7d',   value:peakW?Math.round(peakW)+' W':'—'},
      {label:'Omvormers', value:inverters.length?inverters.map(i=>i.label||'?').join(', '):'—'},
      {label:'Clipping',  value:clipping?'⚠️ Actief':'Geen',dim:!clipping},
    ],{trusted:true}) : {wrap:'',tip:''};
    const _ttScSol = _TTS ? _TTS.html('sl-sc','Zelfconsumptie',[
      {label:'Sensor',        value:'cloudems_self_consumption'},
      {label:'Ratio',         value:scPct.toFixed(1)+'%'},
      {label:'Formule',       value:'(PV − Export) / PV × 100',dim:true},
      {label:'PV vandaag',    value:pvTodayKwh?pvTodayKwh.toFixed(2)+' kWh':'—'},
      {label:'Zelf verbruikt',value:selfKwh!=null?selfKwh.toFixed(2)+' kWh':'—'},
      {label:'Teruggeleverd', value:exportKwh!=null?exportKwh.toFixed(2)+' kWh':'—',dim:true},
    ],{footer:'Hogere % = meer zonne-energie direct thuis verbruikt'}) : {wrap:'',tip:''};
    const _ttFcSol = _TTS ? _TTS.html('sl-fc','PV Forecast',[
      {label:'Vandaag',  value:fcKwh.toFixed(1)+' kWh'},
      {label:'Morgen',   value:fcTomKwh.toFixed(1)+' kWh'},
      {label:'Bron',     value:'Open-Meteo + oriëntatie leren',dim:true},
    ],{footer:'Nauwkeurigheid neemt toe naarmate het systeem langer draait'}) : {wrap:'',tip:''};
    const summaryHtml=`<div class="sec">
      <div class="sec-title">☀️ PV samenvatting</div>
      <table class="summary-table">
        <tr style="position:relative;cursor:default" ${_ttPvNu.wrap}><td class="lbl">☀️ <strong>PV nu</strong></td><td class="val" style="color:#f0c040">${Math.round(totalW)} W</td>${_ttPvNu.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttScSol.wrap}><td class="lbl">♻️ Zelfconsumptie</td><td class="val" style="color:${scPct>60?"#86efac":scPct>30?"#fbbf24":"rgba(255,255,255,.5)"}">${scPct.toFixed(1)} %</td>${_ttScSol.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttFcSol.wrap}><td class="lbl">⏰ Piekuur vandaag</td><td class="val">${peakHour!=null?peakHour+":00":"—"}</td>${_ttFcSol.tip}</tr>
      </table>
    </div>`;

    // ── Zelfconsumptie detail ─────────────────────────────────────────────────
    const selfHtml=`<div class="sec">
      <div class="sec-title">♻️ Zelfconsumptie</div>
      <table class="summary-table">
        ${(()=>{const _TT2=window.CloudEMSTooltip;
          const _ttPv  =_TT2?_TT2.html('sl-sc-pv','PV productie vandaag',[
            {label:'Sensor', value:'cloudems_self_consumption → pv_today_kwh'},
            {label:'Waarde', value:pvTodayKwh?pvTodayKwh.toFixed(2)+' kWh':'—'},
            {label:'Bron',   value:pvTodayKwh>0?'● Gemeten':'○ Forecast fallback',dim:true},
          ],{trusted:pvTodayKwh>0}):{wrap:'',tip:''};
          const _ttSelf=_TT2?_TT2.html('sl-sc-self','Zelf verbruikt',[
            {label:'Sensor',  value:'cloudems_self_consumption → self_consumed_kwh'},
            {label:'Waarde',  value:selfKwh!=null?selfKwh.toFixed(2)+' kWh':'lerende…'},
            {label:'Formule', value:'PV productie − Teruglevering',dim:true},
          ],{footer:'Energie direct thuis verbruikt zonder via net te gaan'}):{wrap:'',tip:''};
          const _ttExp =_TT2?_TT2.html('sl-sc-exp','Teruggeleverd',[
            {label:'Sensor',  value:'cloudems_self_consumption → exported_kwh'},
            {label:'Waarde',  value:exportKwh!=null?exportKwh.toFixed(2)+' kWh':'—'},
            {label:'Formule', value:'PV productie − Zelf verbruikt',dim:true},
          ]):{wrap:'',tip:''};
          const _ttBest=_TT2?_TT2.html('sl-sc-best','Beste zonuur',[
            {label:'Sensor', value:'cloudems_self_consumption → best_solar_hour'},
            {label:'Uur',    value:bestHour!=null?bestHour+':00':'—'},
            {label:'Gebruik',value:'Optimaal tijdstip voor PV-afhankelijke apparaten',dim:true},
          ]):{wrap:'',tip:''};
          const _ttSav =_TT2?_TT2.html('sl-sc-sav','Besparing per maand',[
            {label:'Sensor',  value:'cloudems_self_consumption → monthly_saving_eur'},
            {label:'Waarde',  value:monthSaving!=null?'€'+monthSaving.toFixed(2):'lerende…'},
            {label:'Formule', value:'Zelf verbruikt kWh × import-tariefprijs',dim:true},
          ],{footer:'Schatting — groeit naarmate meer data beschikbaar is'}):{wrap:'',tip:''};
          return`
        <tr style="position:relative;cursor:default" ${_ttPv.wrap}><td class="lbl">PV productie vandaag</td><td class="val" style="color:#86efac">${pvTodayKwh?pvTodayKwh.toFixed(2)+" kWh":"—"}</td>${_ttPv.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttSelf.wrap}><td class="lbl">Zelf verbruikt</td><td class="val" style="color:#86efac">${selfKwh!=null?selfKwh.toFixed(2)+" kWh":"—"}</td>${_ttSelf.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttExp.wrap}><td class="lbl">Teruggeleverd</td><td class="val">${exportKwh!=null?exportKwh.toFixed(2)+" kWh":"—"}</td>${_ttExp.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttBest.wrap}><td class="lbl">Beste zonuur</td><td class="val">${bestHour!=null?bestHour+":00":"—"}</td>${_ttBest.tip}</tr>
        <tr style="position:relative;cursor:default" ${_ttSav.wrap}><td class="lbl">Besparing / maand</td><td class="val" style="color:#f0c040">${monthSaving!=null?"€ "+monthSaving.toFixed(2):"—"}</td>${_ttSav.tip}</tr>`; })()}
      </table>
    </div>`;

    // ── Schaduw ───────────────────────────────────────────────────────────────
    const shadowInvRows=shadowInvs.map(si=>`
      <tr><td class="lbl">${esc(si.label||"Omvormer")}</td><td class="val" style="color:${si.severity==="high"?"#f87171":si.severity==="medium"?"#fbbf24":"#86efac"}">${si.lost_kwh_day_est!=null?si.lost_kwh_day_est.toFixed(2)+" kWh":"—"}</td></tr>
    `).join("");
    const shadowHtml=`<div class="sec">
      <div class="sec-title">☁️ Structurele Schaduwdetectie</div>
      <div class="shadow-note">${esc(shadowSummary)}</div>
      <table class="summary-table">
        <tr><td class="lbl">Totaal geschat verlies (kWh/dag)</td><td class="val">${shadowLost.toFixed(2)} kWh</td></tr>
        <tr><td class="lbl">Schaduw gedetecteerd</td><td class="val" style="color:${shadowAny?"#f87171":"#86efac"}">${shadowAny?"Ja":"Nee"}</td></tr>
        ${shadowInvRows}
      </table>
    </div>`;

    // ── Accuracy footer ───────────────────────────────────────────────────────
    const accHtml=accS?`<div class="accuracy">
      <div class="acc-dot" style="background:${accCol}"></div>
      <span>Forecast nauwkeurigheid gisteren: <strong>${accErr.toFixed(1)}%</strong> afwijking</span>
    </div>`:"";

    const sub=`${inverters.length} omvormer${inverters.length!==1?"s":""}${clipping?" · ⚡ Clipping":""}${peakW?` · piek ${Math.round(peakW)} W`:""}`;

    const activeTab = this._activeTab || 'live';
    // Dimmer actief als minstens één switch.cloudems_zonnedimmer_N = on en pct < 100
    const dimmerActive = [1,2,3,4].some(n => {
      const sw = h.states[`switch.cloudems_zonnedimmer_${n}`];
      const num = h.states[`number.cloudems_zonnedimmer_${n}`];
      return sw?.state === 'on' && parseFloat(num?.state||100) < 99;
    });
    // Auto-switch naar dimmer tab als actief en gebruiker niet handmatig geswitcht
    if(dimmerActive && !this._tabManualSet) this._activeTab = 'dimmer';
    sh.innerHTML=`<style>${SOL_STYLES}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">☀️</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub">${esc(sub)}</div>
        </div>
        <span class="hdr-watt">${Math.round(totalW)}<span>W</span></span>
      </div>
      ${clipping?`<div class="clip-banner">⚡ Clipping actief — productie begrensd door omvormer capaciteit</div>`:""}
      ${(() => {
        const alerts = h.states['sensor.cloudems_actieve_meldingen']?.attributes?.active_alerts || [];
        const dimAlerts = alerts.filter(a =>
          a.key === 'inverter_negative_price_dim' || a.key === 'inverter_dimmer_disabled'
        );
        const clipTomS = h.states['sensor.cloudems_clipping_voorspelling_morgen'];
        const clipTomKwh = parseFloat(clipTomS?.attributes?.total_clipped_kwh || 0);
        let html = '';
        // Clipping forecast banner
        if (clipTomKwh > 0.05) {
          html += `<div class="alert-banner alert-orange">⚡ Clipping verwacht morgen: ${clipTomKwh.toFixed(1)} kWh — laad batterij vóór piekuren</div>`;
        }
        // Dimmer alerts
        dimAlerts.forEach(a => {
          const cls = a.key === 'inverter_negative_price_dim' ? 'alert-red' : 'alert-yellow';
          html += `<div class="alert-banner ${cls}">⚠️ ${esc(a.title||'')} — ${esc(a.message||'')}</div>`;
        });
        return html;
      })()}
      <div class="top-strip">
        ${(()=>{const _TTS=window.CloudEMSTooltip;
          const _ttNu=_TTS?_TTS.html('sl-top-nu','PV vermogen nu',[
            {label:'Sensor',   value:'cloudems_solar_system'},
            {label:'Vermogen', value:Math.round(totalW)+' W'},
            {label:'Piek 7d',  value:peakW?Math.round(peakW)+' W':'\u2014'},
            {label:'Clipping', value:clipping?'\u26a1 Actief':'Geen',dim:!clipping},
          ],{trusted:totalW>0}):{wrap:'',tip:''};
          const _ttVandaag=_TTS?_TTS.html('sl-top-vd','Productie vandaag',[
            {label:'Sensor',   value:'cloudems_self_consumption'},
            {label:'Gemeten',  value:scA.pv_today_kwh>0.05?scA.pv_today_kwh.toFixed(2)+' kWh':'nog niet'},
            {label:'Forecast', value:fcKwh.toFixed(2)+' kWh',dim:scA.pv_today_kwh>0.05},
            {label:'Bron',     value:scA.pv_today_kwh>0.05?'\u25cf Gemeten':'\u25cb Dagforecast',dim:true},
          ],{trusted:scA.pv_today_kwh>0.05}):{wrap:'',tip:''};
          const _ttMorgen=_TTS?_TTS.html('sl-top-tm','Forecast morgen',[
            {label:'Sensor',   value:'cloudems_pv_forecast_tomorrow'},
            {label:'Verwacht', value:fcTomKwh.toFixed(2)+' kWh'},
            {label:'Bron',     value:'Open-Meteo + ori\u00ebntatie',dim:true},
          ],{footer:'Nauwkeurigheid neemt toe na meer meetdagen'}):{wrap:'',tip:''};
          return`
        <div class="top-box" style="position:relative;cursor:default" ${_ttNu.wrap}><span class="top-label">Nu</span><span class="top-val" style="color:var(--sl-gold)">${Math.round(totalW)} W</span>${peakW?`<span class="top-sub">piek ${Math.round(peakW)} W</span>`:""} ${_ttNu.tip}</div>
        <div class="top-box" style="position:relative;cursor:default" ${_ttVandaag.wrap}><span class="top-label">Vandaag</span><span class="top-val" style="color:${scA.pv_today_kwh > 0.05 ? 'var(--sl-green)' : 'var(--sl-amber)'}">${scA.pv_today_kwh > 0.05 ? scA.pv_today_kwh.toFixed(1) : fcKwh.toFixed(1)} kWh</span><span class="top-sub">${scA.pv_today_kwh > 0.05 ? 'gemeten' : 'dagschatting'}</span>${_ttVandaag.tip}</div>
        <div class="top-box" style="position:relative;cursor:default" ${_ttMorgen.wrap}><span class="top-label">Morgen</span><span class="top-val">${fcTomKwh.toFixed(1)} kWh</span><span class="top-sub">verwacht</span>${_ttMorgen.tip}</div>`; })()}
      </div>

      <div class="tab-bar">
        <button class="tab-btn ${activeTab==='live'?'active':''}" data-tab="live">☀️ Live</button>
        <button class="tab-btn ${activeTab==='analyse'?'active':''}" data-tab="analyse">📊 Analyse</button>
        <button class="tab-btn ${activeTab==='advies'?'active':''}" data-tab="advies">💡 Advies</button>
        <button class="tab-btn ${activeTab==='dimmer'?'active':''}${dimmerActive?' dimmer-active':''}" data-tab="dimmer">⚡ Dimmer${dimmerActive?' 🟠':''}</button>
      </div>

      <div class="tab-pane ${activeTab==='live'?'active':''}">
        ${yieldHtml}
      ${invHtml}
      ${clippingHtml}
      </div>

      <div class="tab-pane ${activeTab==='analyse'?'active':''}">
        ${summaryHtml}
      ${selfHtml}
      ${shadowHtml}
      </div>

      <div class="tab-pane ${activeTab==='advies'?'active':''}">
        <!-- ── Oriëntatie leervoortgang ── -->
      ${(() => {
        const invs2 = (solS?.attributes?.inverters)||[];
        if(!invs2.length) return '';
        const rows = invs2.map(inv => {
          const have = inv.clear_sky_samples||0;
          const need = inv.orientation_samples_needed||1800;
          const pct  = Math.min(100, Math.round(have/need*100));
          const conf = inv.orientation_confident||false;
          const col  = conf?'#86efac':pct>=50?'#fbbf24':'#f87171';
          const icon = conf?'✅':pct>=50?'🟡':'🔴';
          const az   = inv.azimuth_learned??inv.azimuth_compass??null;
          const tilt = inv.tilt_learned??inv.tilt_deg??null;
          const hoursLeft = Math.max(0, Math.round((need-have)/60));
          return `<div style="margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
              <strong>${icon} ${esc(inv.label||'Omvormer')}</strong>
              <span style="color:${col}">${pct}% geleerd</span>
            </div>
            <div style="background:rgba(255,255,255,.06);border-radius:3px;height:5px;overflow:hidden;margin-bottom:3px">
              <div style="height:100%;width:${pct}%;background:${col};border-radius:3px"></div>
            </div>
            <div style="font-size:10px;color:rgba(255,255,255,.4)">
              ${az!=null?`${az} ${Math.round(az)}°`:''} ${tilt!=null?`· ∠${Math.round(tilt)}°`:''}
              ${!conf&&hoursLeft>0?` · nog ~${hoursLeft} zonne-uren`:''}
            </div>
          </div>`;
        }).join('');
        return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:8px">🧭 Oriëntatie leervoortgang</div>
          ${rows}
        </div>`;
      })()}

      <!-- ── Forecast nauwkeurigheid ── -->
      ${(() => {
        const accS2 = h.states['sensor.cloudems_solar_pv_forecast_accuracy']??h.states['sensor.cloudems_pv_forecast_accuracy'];
        const aA = accS2?.attributes||{};
        const samp = aA.samples||0;
        if(!samp) return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:6px">🎯 PV Voorspelling Nauwkeurigheid</div>
          <div style="font-size:11px;color:rgba(255,255,255,.35);font-style:italic">⏳ Data beschikbaar na ~7 meetdagen</div>
        </div>`;
        const acc2 = Math.min(100,Math.max(0,parseFloat(accS2?.state||0)));
        const m14  = aA.mape_14d_pct||0, m30=aA.mape_30d_pct||0;
        const bias = aA.bias_factor||1;
        const lastErr = aA.last_day_error_pct||0;
        const accCol = acc2>=85?'#86efac':acc2>=70?'#fbbf24':'#f87171';
        const biasLbl = bias>1.05?'Overschat':bias<0.95?'Onderschat':'✅ Gekalibreerd';
        return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229">🎯 Forecast nauwkeurigheid</div>
            <span style="font-family:monospace;font-size:14px;font-weight:700;color:${accCol}">${acc2.toFixed(1)}%</span>
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Gisteren</td><td style="text-align:right;color:rgba(255,255,255,.75)">${lastErr.toFixed(1)}% afwijking</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">14 dagen</td><td style="text-align:right;color:rgba(255,255,255,.75)">${m14.toFixed(1)}%</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">30 dagen</td><td style="text-align:right;color:rgba(255,255,255,.75)">${m30.toFixed(1)}%</td></tr>
            <tr><td style="padding:3px 0;color:rgba(255,255,255,.45)">Bias</td><td style="text-align:right;color:rgba(255,255,255,.75)">${bias.toFixed(2)} · ${biasLbl}</td></tr>
          </table>
          <div style="font-size:10px;color:rgba(255,255,255,.3);margin-top:4px">Gebaseerd op ${samp} meetdagen</div>
        </div>`;
      })()}

      <!-- ── Opbrengst & Terugverdientijd ── -->
      ${(() => {
        const roiS = h.states['sensor.cloudems_pv_opbrengst_terugverdientijd'];
        if(!roiS||roiS.state==='unavailable') return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:6px">💰 Opbrengst & Terugverdientijd</div>
          <div style="font-size:11px;color:rgba(255,255,255,.35);font-style:italic">⏳ Beschikbaar na eerste zonnige dag</div>
        </div>`;
        const rA = roiS.attributes||{};
        const wp = rA.estimated_wp_total||0;
        const kwh = rA.annual_yield_kwh_est||0;
        const eur = rA.annual_value_eur_est||0;
        const peak = rA.peak_w_alltime||0;
        const selfPct = rA.self_sufficiency_pct||0;
        const expKwp = rA.expansion_advice_kwp;
        const optWp = rA.optimal_wp||0;
        const roi7k = eur>0?(7000/eur).toFixed(1):'—';
        const roi12k = eur>0?(12000/eur).toFixed(1):'—';
        return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:8px">💰 Opbrengst & Terugverdientijd</div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Piekvermogen</td><td style="text-align:right;color:rgba(255,255,255,.75)">${(wp/1000).toFixed(2)} kWp</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Hoogste productie</td><td style="text-align:right;color:rgba(255,255,255,.75)">${Math.round(peak)} W</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Geschatte jaaropbrengst</td><td style="text-align:right;color:#86efac">${Math.round(kwh)} kWh</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Financiële jaarwaarde</td><td style="text-align:right;color:#f0c040;font-weight:700">€${Math.round(eur)}</td></tr>
            ${selfPct>0?`<tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Zelfvoorzieningsgraad</td><td style="text-align:right;color:rgba(255,255,255,.75)">${selfPct}%</td></tr>`:''}
          </table>
          ${eur>0?`<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,.04)">
            <div style="font-size:10px;color:rgba(255,255,255,.4);margin-bottom:4px">Terugverdientijd indicatie</div>
            <div style="display:flex;gap:8px;font-size:11px">
              <div style="flex:1;text-align:center;padding:5px;background:rgba(255,255,255,.04);border-radius:6px"><div style="color:#f0c040;font-weight:700">${roi7k}j</div><div style="color:rgba(255,255,255,.4);font-size:9px">€7.000 (5kWp)</div></div>
              <div style="flex:1;text-align:center;padding:5px;background:rgba(255,255,255,.04);border-radius:6px"><div style="color:#f0c040;font-weight:700">${roi12k}j</div><div style="color:rgba(255,255,255,.4);font-size:9px">€12.000 (10kWp)</div></div>
            </div>
          </div>`:''}
          ${expKwp!=null&&expKwp>0?`<div style="margin-top:8px;padding:8px 10px;background:rgba(240,192,64,.08);border:1px solid rgba(240,192,64,.2);border-radius:6px;font-size:11px">
            💡 Uitbreidingsadvies: <strong>+${expKwp} kWp</strong> (optimaal ${(optWp/1000).toFixed(1)} kWp)
          </div>`:''}
        </div>`;
      })()}

      <!-- ── Clipping detail ── -->
      ${(() => {
        const clS2 = h.states['sensor.cloudems_clipping_verlies']??h.states['sensor.cloudems_cloudems_clipping_verlies'];
        if(!clS2) return '';
        const cA2 = clS2.attributes||{};
        const lostKwh = parseFloat(clS2.state||0)||0;
        const lostEur = cA2.total_eur_lost_year||0;
        const worst  = cA2.worst_inverter||'—';
        const roiY   = cA2.expansion_roi_years;
        const anyCurt= cA2.any_curtailment||false;
        const advice2 = cA2.advice||'';
        return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:8px">✂️ Clipping Verlies & Curtailment</div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Verlies laatste 30 dagen</td><td style="text-align:right;color:rgba(255,255,255,.75)">${lostKwh.toFixed(2)} kWh</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Geschat verlies per jaar</td><td style="text-align:right;color:${lostEur>50?'#f87171':'rgba(255,255,255,.75)'}">€${lostEur.toFixed(0)}</td></tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Grootste verliezer</td><td style="text-align:right;color:rgba(255,255,255,.75)">${esc(worst)}</td></tr>
            ${roiY?`<tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:3px 0;color:rgba(255,255,255,.45)">Terugverdientijd uitbreiding</td><td style="text-align:right;color:rgba(255,255,255,.75)">${roiY} jaar</td></tr>`:''}
            <tr><td style="padding:3px 0;color:rgba(255,255,255,.45)">Feed-in curtailment</td><td style="text-align:right;color:${anyCurt?'#f59e0b':'rgba(255,255,255,.4)'}">${anyCurt?'Vermoed':'Nee'}</td></tr>
          </table>
          ${advice2?`<div style="font-size:11px;color:rgba(255,255,255,.45);font-style:italic;margin-top:6px">${esc(advice2)}</div>`:''}
        </div>`;
      })()}
      </div>

      <div class="tab-pane ${activeTab==='dimmer'?'active':''}">
        <!-- ── Zonnedimmer ── -->
      ${(() => {
        const dims = [1,2,3,4].map(n => ({
          sw: h.states[`switch.cloudems_zonnedimmer_${n}`],
          num: h.states[`number.cloudems_zonnedimmer_${n}`],
        })).filter(d => d.sw && d.sw.state !== 'unavailable');
        if(!dims.length) return '';
        const rows = dims.map((d,i) => {
          const on = d.sw.state === 'on';
          const pct = parseFloat(d.num?.state||0)||0;
          const status = d.num?.attributes?.status||'';
          return `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)">
            <div style="width:8px;height:8px;border-radius:50%;background:${on?'#86efac':'rgba(255,255,255,.2)'};flex-shrink:0"></div>
            <span style="flex:1;font-size:11px">Omvormer ${i+1}</span>
            <span style="font-family:monospace;font-size:11px;color:${on?'#f0c040':'rgba(255,255,255,.4)'}">${pct.toFixed(0)}%</span>
          </div>`;
        }).join('');
        return `<div style="border-top:1px solid rgba(255,255,255,.06);padding:12px 16px">
          <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#3d5229;margin-bottom:8px">☀️ Zonnedimmer</div>
          ${rows}
        </div>`;
      })()}
      </div>
      ${accHtml}
    </div>`;

    sh.querySelectorAll('[data-fcnav]').forEach(btn => {
      btn.addEventListener('click', () => {
        const dir = btn.dataset.fcnav;
        const order = ['yesterday','today','tomorrow'];
        const cur = order.indexOf(this._chartDay||'today');
        const nxt = dir==='prev' ? Math.max(0,cur-1) : Math.min(2,cur+1);
        this._chartDay = order[nxt];
        this._prev = ''; this._render();
      });
    });
    sh.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = btn.dataset.tab;
        this._tabManualSet = true;
        this._prev = '';
        this._render();
      });
    });


  }

  static getConfigElement(){ return document.createElement("cloudems-solar-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-solar-card",title:"Zonnepanelen"}; }
  getCardSize(){ return 10; }
}

class CloudemsSolarCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??'Zonnepanelen'}"></div></div>`;
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{ const nc={...this._cfg}; nc[el.name]=el.value; this._cfg=nc; this._fire(); });
    });
  }
}

if (!customElements.get('cloudems-solar-card-editor')) customElements.define("cloudems-solar-card-editor", CloudemsSolarCardEditor);
if (!customElements.get('cloudems-solar-card')) customElements.define("cloudems-solar-card", CloudemsSolarCard);
window.customCards=window.customCards??[];
if(!window.customCards.find(c=>c.type==="cloudems-solar-card"))
  window.customCards.push({type:"cloudems-solar-card",name:"CloudEMS Solar Card v2.1",description:"Zonnepanelen · forecast · benutting · clipping · zelfconsumptie · schaduw",preview:true});
console.info(`%c CLOUDEMS-SOLAR-CARD %c v${SOL_VERSION} `,"background:#f0c040;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0c1409;color:#f0c040;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
