// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Solar Card  v2.0.0

const SOL_VERSION = "2.0.1";
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
  .yield-section{padding:12px 18px 0;border-bottom:1px solid var(--sl-border);}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--sl-muted);margin-bottom:7px;}
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
  .util-bar{height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;margin-bottom:5px;}
  .util-fill{height:100%;border-radius:2px;transition:width .8s ease;}
  .inv-chips{display:flex;flex-wrap:wrap;gap:4px;}
  .chip{font-family:var(--sl-mono);font-size:9px;padding:2px 7px;border-radius:10px;background:rgba(255,255,255,.06);color:var(--sl-subtext);border:1px solid var(--sl-border);}
  .chip.phase{background:rgba(134,239,172,.08);color:var(--sl-green);border-color:rgba(134,239,172,.2);}
  .chip.clip{background:rgba(239,68,68,.12);color:#f87171;border-color:rgba(239,68,68,.2);}
  .chip.orient{background:var(--sl-gold-dim);color:var(--sl-gold);border-color:rgba(240,192,64,.2);}
  .accuracy{display:flex;align-items:center;gap:8px;padding:8px 18px;font-size:11px;color:var(--sl-subtext);border-top:1px solid var(--sl-border);}
  .acc-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
  .empty{padding:36px;text-align:center;color:var(--sl-muted);display:flex;flex-direction:column;align-items:center;gap:12px;}
  .empty-icon{font-size:40px;opacity:.3;}
  @keyframes fadeUp{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
`;

const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const compassLabel = a => { const labels=["Z","ZZW","ZW","WZW","W","WNW","NW","NNW","N","NNO","NO","ONO","O","OZO","ZO","ZZO"]; return labels[Math.round(((a%360)+360)%360/22.5)%16]||"?"; };

class CloudemsSolarCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._prev=""; }
  setConfig(c){ this._cfg={title:c.title??"Zonnepanelen",...c}; this._render(); }
  set hass(h){
    this._hass=h;
    const sol=h.states["sensor.cloudems_solar_system"];
    const fc=h.states["sensor.cloudems_pv_forecast_today"];
    const mod=h.states["switch.cloudems_module_solar_learner"];
    // Also include inverter_data from status sensor so we render when it appears
    const invCount=(h.states["sensor.cloudems_status"]?.attributes?.inverter_data||[]).length;
    const j=JSON.stringify([sol?.state,sol?.last_changed,fc?.state,fc?.last_changed,mod?.state,invCount]);
    if(j!==this._prev){this._prev=j;this._render();}
  }
  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass, c=this._cfg??{};
    if(!h){ sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">☀️</span></div></div>`; return; }

    const solS=h.states["sensor.cloudems_solar_system"];
    const fcS=h.states["sensor.cloudems_pv_forecast_today"];
    const accS=h.states["sensor.cloudems_pv_forecast_accuracy"];

    // Only show "no inverter" when module is truly disabled or no data at all
    const hasInverters = (solS?.attributes?.inverters||[]).length > 0;
    // Also check status sensor for inverter data (available sooner after restart)
    const statusInvs = h.states["sensor.cloudems_status"]?.attributes?.inverter_data || [];
    const moduleOn = h.states["switch.cloudems_module_solar_learner"]?.state === "on";
    const hasAnyData = hasInverters || statusInvs.length > 0;
    if((!solS||solS.state==="unavailable"||solS.state==="unknown") && !hasAnyData && !moduleOn){
      sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="hdr"><span class="hdr-icon">☀️</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:rgba(251,146,60,.7)">⚠️ Geen omvormer geconfigureerd</div></div></div><div class="empty"><span class="empty-icon">☀️</span>Configureer een omvormer via CloudEMS instellingen.</div></div>`;
      return;
    }
    // If unavailable but module is on, show loading state instead
    if((!solS||solS.state==="unavailable"||solS.state==="unknown") && !hasAnyData){
      sh.innerHTML=`<style>${SOL_STYLES}</style><div class="card"><div class="hdr"><span class="hdr-icon">☀️</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:var(--sl-subtext)">⏳ Laden...</div></div></div></div>`;
      return;
    }

    const sA=solS.attributes||{}, fcA=fcS?.attributes||{};
    const totalW=parseFloat(solS.state)||0;
    const inverters=sA.inverters||[];
    const peakW=sA.total_peak_w||0;
    const clipping=sA.clipping_active||false;
    const fcKwh=parseFloat(fcA.forecast_kwh||fcA.total_kwh||0)||0;
    const fcTomKwh=parseFloat(fcA.forecast_kwh_tomorrow||0)||0;
    const fcHourly=fcA.hourly||[];
    const nowH=new Date().getHours();

    // Yield bars
    let yieldHtml="";
    if(fcHourly.length>0){
      const maxH=Math.max(...fcHourly.map(x=>x?.wh??x??0),1);
      yieldHtml=`<div class="yield-section">
        <div class="sec-title">☀️ Forecast vandaag per uur</div>
        <div class="yield-grid">${fcHourly.map((h2,i)=>{
          const wh=h2?.wh??h2??0;
          const pct=Math.max((wh/maxH)*100,2);
          const col=i===nowH?"#f0c040":i<nowH?"rgba(240,192,64,.2)":"rgba(134,239,172,.45)";
          return `<div class="yield-col"><div class="yield-bar${i===nowH?" now":""}" style="height:${pct*.42}px;background:${col}"></div></div>`;
        }).join("")}</div>
        <div class="yield-label-row"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
      </div>`;
    }

    // Inverter rows
    let invHtml="";
    if(inverters.length>0){
      invHtml=`<div class="inv-section">
        <div class="sec-title">Omvormers (${inverters.length})</div>
        ${inverters.map((inv,i)=>{
          const w=parseFloat(inv.current_w)||0;
          const rated=inv.rated_power_w||inv.estimated_wp||0;
          const util=rated?Math.min(Math.round(w/rated*100),100):0;
          const utilCol=util>80?"#f0c040":util>40?"#86efac":"#3d5229";
          const az=inv.azimuth_learned??inv.azimuth_compass??null;
          const tilt=inv.tilt_deg;
          const phase=inv.phase_display||inv.phase;
          const clip=inv.clipping;
          const orientConf=inv.orientation_confident;
          return `<div class="inv-row" style="animation-delay:${i*.06}s">
            <div class="inv-top">
              <span class="inv-name">☀️ ${esc(inv.label||`Omvormer ${i+1}`)}</span>
              <span class="inv-pwr">${Math.round(w)} W</span>
            </div>
            <div class="util-bar"><div class="util-fill" style="width:${util}%;background:${utilCol}"></div></div>
            <div class="inv-chips">
              ${rated?`<span class="chip">${Math.round(rated)} Wp</span>`:""}
              ${az!==null?`<span class="chip orient">${compassLabel(az)} ${Math.round(az)}°${orientConf?"":" ~"}</span>`:""}
              ${tilt?`<span class="chip">∠${Math.round(tilt)}°</span>`:""}
              ${phase?`<span class="chip phase">Fase ${esc(phase)}</span>`:""}
              ${clip?`<span class="chip clip">⚡ Clipping</span>`:""}
              ${util>0?`<span class="chip">${util}% benut</span>`:""}
            </div>
          </div>`;
        }).join("")}
      </div>`;
    }

    // Accuracy
    let accHtml="";
    if(accS){
      const err=parseFloat(accS.attributes?.last_day_error_pct??0);
      const col=err<15?"#86efac":err<30?"#fbbf24":"#f87171";
      accHtml=`<div class="accuracy"><div class="acc-dot" style="background:${col}"></div><span>Forecast nauwkeurigheid gisteren: <strong>${err.toFixed(1)}%</strong> afwijking</span></div>`;
    }

    const sub=`${inverters.length} omvormer${inverters.length!==1?"s":""}${clipping?" · ⚡ Clipping":""}${peakW?` · piek ${Math.round(peakW)} W`:""}`;

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
      <div class="top-strip">
        <div class="top-box"><span class="top-label">Nu</span><span class="top-val" style="color:var(--sl-gold)">${Math.round(totalW)} W</span>${peakW?`<span class="top-sub">piek ${Math.round(peakW)} W</span>`:""}</div>
        <div class="top-box"><span class="top-label">Vandaag</span><span class="top-val" style="color:var(--sl-green)">${fcKwh.toFixed(1)} kWh</span><span class="top-sub">verwacht</span></div>
        <div class="top-box"><span class="top-label">Morgen</span><span class="top-val">${fcTomKwh.toFixed(1)} kWh</span><span class="top-sub">verwacht</span></div>
      </div>
      ${yieldHtml}${invHtml}${accHtml}
    </div>`;
  }
  static getStubConfig(){ return {title:"Zonnepanelen"}; }
  getCardSize(){ return 6; }

  static getConfigElement(){ return document.createElement("cloudems-solar-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-solar-card"}; }
}



class CloudemsSolarCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){
    this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true}));
  }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.row:last-child{border-bottom:none;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input[type=text],input[type=number]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color,#03a9f4);cursor:pointer;}
</style>
<div class="wrap">
        <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"Zonnepanelen"}"></div>
</div>`;
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{
        const n=el.name, nc={...this._cfg};
        if(n==="title") nc[n]=el.value;
        this._cfg=nc; this._fire();
      });
    });
  }
}
customElements.define("cloudems-solar-card-editor", CloudemsSolarCardEditor);
customElements.define("cloudems-solar-card",CloudemsSolarCard);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-solar-card",name:"CloudEMS Solar Card",description:"Zonnepanelen — vermogen, forecast & omvormer details",preview:true});
console.info(`%c CLOUDEMS-SOLAR-CARD %c v${SOL_VERSION} `,"background:#f0c040;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0c1409;color:#f0c040;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
