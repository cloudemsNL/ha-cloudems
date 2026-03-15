// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Battery Card  v2.0.0

const BAT_VERSION = "2.0.2";
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
  .hdr-icon{font-size:18px;flex-shrink:0;}
  .hdr-texts{flex:1;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--b-text);letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:var(--b-subtext);margin-top:2px;}
  .action-pill{font-family:var(--b-mono);font-size:10px;font-weight:600;padding:4px 10px;border-radius:20px;text-transform:uppercase;letter-spacing:.08em;}
  .action-pill.charge{background:var(--b-green-dim);color:var(--b-green);border:1px solid rgba(63,185,80,.25);}
  .action-pill.discharge{background:var(--b-amber-dim);color:var(--b-amber);border:1px solid rgba(210,153,34,.25);}
  .action-pill.idle{background:var(--b-blue-dim);color:var(--b-blue);border:1px solid rgba(88,166,255,.15);}
  .action-pill.forced_off{background:var(--b-red-dim);color:var(--b-red);border:1px solid rgba(248,81,73,.2);}
  .main-row{display:flex;align-items:center;padding:18px 20px 14px;border-bottom:1px solid var(--b-border);gap:4px;}
  .arc-wrap{position:relative;flex-shrink:0;width:110px;height:80px;}
  .arc-svg{display:block;overflow:visible;}
  .arc-track{fill:none;stroke:rgba(255,255,255,.06);stroke-width:8;stroke-linecap:round;}
  .arc-fill{fill:none;stroke-width:8;stroke-linecap:round;transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1),stroke .5s;}
  .arc-glow{fill:none;stroke-width:14;stroke-linecap:round;opacity:.12;filter:blur(3px);transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1),stroke .5s;}
  .arc-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;padding-bottom:8px;}
  .arc-pct{font-family:var(--b-mono);font-size:22px;font-weight:700;line-height:1;}
  .arc-soc-label{font-size:8px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--b-subtext);margin-top:1px;}
  .stats-col{flex:1;padding-left:16px;display:flex;flex-direction:column;gap:9px;}
  .stat{display:flex;flex-direction:column;gap:1px;}
  .stat-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--b-muted);}
  .stat-val{font-family:var(--b-mono);font-size:15px;font-weight:600;color:var(--b-text);}
  .stat-val.pos{color:var(--b-green);}
  .stat-val.neg{color:var(--b-amber);}
  .stat-val.zero{color:var(--b-subtext);}
  .flow-wrap{padding:6px 20px 12px;border-bottom:1px solid var(--b-border);}
  .flow-labels{display:flex;justify-content:space-between;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--b-muted);margin-bottom:5px;}
  .flow-track{height:6px;background:rgba(255,255,255,.04);border-radius:3px;position:relative;overflow:hidden;}
  .flow-center{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--b-border);transform:translateX(-50%);}
  .flow-fill{position:absolute;top:0;bottom:0;border-radius:3px;transition:left .8s ease,width .8s ease,background .5s;}
  .kwh-row{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--b-border);}
  .kwh-box{padding:10px 18px;display:flex;flex-direction:column;gap:3px;border-right:1px solid var(--b-border);}
  .kwh-box:last-child{border-right:none;}
  .kwh-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--b-muted);}
  .kwh-val{font-family:var(--b-mono);font-size:15px;font-weight:600;}
  .schedule-section{padding:10px 18px 12px;border-bottom:1px solid var(--b-border);}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--b-muted);margin-bottom:7px;}
  .timeline{display:flex;gap:2px;align-items:flex-end;height:32px;}
  .tl-cell{flex:1;border-radius:2px;min-height:4px;cursor:default;position:relative;transition:height .4s;}
  .tl-cell.charge{background:var(--b-green);}
  .tl-cell.discharge{background:var(--b-amber);}
  .tl-cell.idle{background:rgba(255,255,255,.06);height:4px!important;}
  .tl-cell.now{outline:1px solid var(--b-blue);outline-offset:1px;}
  .tl-labels{display:flex;justify-content:space-between;font-family:var(--b-mono);font-size:8px;color:var(--b-muted);margin-top:4px;}
  .bats-section{padding:10px 18px 12px;border-bottom:1px solid var(--b-border);}
  .bat-row{display:grid;grid-template-columns:1fr 56px auto auto;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.03);animation:fadeUp .35s ease both;}
  .bat-row:last-child{border-bottom:none;}
  .bat-label{font-size:12px;font-weight:600;color:var(--b-text);}
  .bat-bar-wrap{height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;}
  .bat-bar-fill{height:100%;border-radius:2px;transition:width .8s ease;}
  .bat-soc{font-family:var(--b-mono);font-size:11px;font-weight:600;text-align:right;}
  .bat-pwr{font-family:var(--b-mono);font-size:10px;color:var(--b-subtext);text-align:right;}
  .reason{padding:10px 18px 12px;font-size:11.5px;color:var(--b-subtext);font-style:italic;line-height:1.6;border-top:1px solid var(--b-border);display:flex;gap:8px;align-items:flex-start;}
  .verify-badge{padding:6px 18px;font-size:10px;color:var(--b-subtext);display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--b-border);}
  .verify-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
  .verify-dot.pending{background:var(--b-amber);animation:pulse 1.2s infinite;}
  .verify-dot.limited{background:var(--b-red);}
  .empty{padding:36px;text-align:center;color:var(--b-muted);display:flex;flex-direction:column;align-items:center;gap:12px;}
  .empty-icon{font-size:40px;opacity:.3;}
  @keyframes fadeUp{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
`;

const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const socColor = p => p>=60?"#3fb950":p>=30?"#d29922":"#f85149";
const actCls = a => { const s=(a||"").toLowerCase(); return s==="charge"||s==="laden"?"charge":s==="discharge"||s==="ontladen"?"discharge":s==="forced_off"||s==="uit"?"forced_off":"idle"; };
const actLabel = a => ({"charge":"⚡ Laden","laden":"⚡ Laden","discharge":"⬇ Ontladen","ontladen":"⬇ Ontladen","idle":"● Idle","hold":"● Idle","forced_off":"✕ Geblokkeerd"}[(a||"").toLowerCase()]||a||"Idle");

class CloudemsBatteryCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._prev=""; }
  setConfig(c){ this._cfg={title:c.title??"Batterij",...c}; this._render(); }
  set hass(h){
    this._hass=h;
    const soc=h.states["sensor.cloudems_battery_so_c"];
    const sch=h.states["sensor.cloudems_batterij_epex_schema"]||h.states["sensor.cloudems_battery_schedule"];
    const pwr=h.states["sensor.cloudems_battery_power"];
    // Watch zpSoc explicitly so Zonneplan SoC changes trigger re-render
    const zpSoc=sch?.attributes?.soc_pct??sch?.attributes?.zonneplan?.soc_pct??null;
    const j=JSON.stringify([soc?.state,soc?.last_changed,sch?.state,sch?.last_changed,zpSoc,pwr?.state]);
    if(j!==this._prev){this._prev=j;this._render();}
  }
  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass, c=this._cfg??{};
    if(!h){ sh.innerHTML=`<style>${BAT_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">🔋</span></div></div>`; return; }

    const socS=h.states["sensor.cloudems_battery_so_c"];
    const pwrS=h.states["sensor.cloudems_battery_power"];
    const schS=h.states["sensor.cloudems_batterij_epex_schema"]||h.states["sensor.cloudems_battery_schedule"];

    // Fallback: haal SoC op uit Zonneplan EPEX schema als directe sensor unavailable is
    const zpAttr=h.states["sensor.cloudems_batterij_epex_schema"]?.attributes||{};
    const zpSoc=zpAttr.soc_pct??zpAttr.zonneplan?.soc_pct??null;
    const zpPwr=zpAttr.batteries?.[0]?.power_w??null;

    const socRaw=parseFloat(socS?.state);
    const socAvail=socS&&!isNaN(socRaw)&&socS.state!=="unavailable"&&socS.state!=="unknown";

    if(!socAvail&&zpSoc==null){
      sh.innerHTML=`<style>${BAT_STYLES}</style><div class="card"><div class="hdr"><span class="hdr-icon">🔋</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:var(--b-amber)">⚠️ Geen batterij geconfigureerd</div></div></div><div class="empty"><span class="empty-icon">🔋</span>Configureer een batterij via CloudEMS instellingen.</div></div>`;
      return;
    }

    const soc=socAvail?socRaw:(zpSoc||0);
    const sA=socS.attributes||{}, pA=pwrS?.attributes||{}, schA=schS?.attributes||{};
    const powerW=parseFloat(pwrS?.state)||0;
    const action=schS?.state||(powerW>50?"charge":powerW<-50?"discharge":"idle");
    const reason=schA.human_reason||schA.reason||sA.reason||"";
    const capKwh=parseFloat(sA.capacity_kwh)||0;
    const chargeKwh=parseFloat(pA.charge_kwh_today)||0;
    const disKwh=parseFloat(pA.discharge_kwh_today)||0;
    const allBats=pA.batteries||sA.all_batteries||[];
    const schedule=schA.schedule||[];
    const pendingPreset=sA._pending_preset||"";
    const rateLimited=parseFloat(sA._rate_limited_until||0)>Date.now()/1000;
    const pendingRetries=parseInt(sA._pending_retries||0);

    const ac=actCls(action);
    const color=socColor(soc);
    const socLow=soc<20;

    // Arc SVG — 240° arc
    const R=40,cx=55,cy=58,sweep=240*Math.PI/180;
    const start=-210*Math.PI/180;
    const circ=R*sweep;
    const offset=circ-(soc/100)*circ;
    const ap=(r)=>{
      const sx=cx+r*Math.cos(start),sy=cy+r*Math.sin(start);
      const ex=cx+r*Math.cos(start+sweep),ey=cy+r*Math.sin(start+sweep);
      return `M ${sx.toFixed(1)} ${sy.toFixed(1)} A ${r} ${r} 0 1 1 ${ex.toFixed(1)} ${ey.toFixed(1)}`;
    };

    const pwrStr=powerW>50?`+${Math.round(powerW)} W`:powerW<-50?`${Math.round(powerW)} W`:"0 W";
    const pwrCls=powerW>50?"pos":powerW<-50?"neg":"zero";
    const maxW=Math.max(5000,Math.abs(powerW)*1.2);
    const barPct=Math.min(Math.abs(powerW)/maxW*50,50);
    const barLeft=powerW<0?(50-barPct):50;
    const barColor=powerW>50?"var(--b-green)":powerW<-50?"var(--b-amber)":"var(--b-blue)";

    const nowH=new Date().getHours();

    // Schedule timeline
    let tlHtml="";
    if(schedule.length>0){
      const slots=new Array(24).fill("idle");
      for(const s of schedule){
        const hh=parseInt((s.hour??s.time??"0").toString().split(":")[0]);
        if(hh>=0&&hh<24) slots[hh]=(s.action||"idle").toLowerCase();
      }
      tlHtml=`<div class="schedule-section">
        <div class="sec-title">📅 Schema vandaag</div>
        <div class="timeline">${slots.map((a,i)=>{
          const cl=actCls(a);
          const ht=cl==="charge"?28:cl==="discharge"?20:4;
          return `<div class="tl-cell ${cl}${i===nowH?" now":""}" style="height:${ht}px" title="${i}:00 — ${a}"></div>`;
        }).join("")}</div>
        <div class="tl-labels"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
      </div>`;
    }

    // Multi-bat
    let batsHtml="";
    if(allBats.length>1){
      batsHtml=`<div class="bats-section"><div class="sec-title">Batterijen (${allBats.length})</div>
        ${allBats.map((b,i)=>{
          const bs=parseFloat(b.soc_pct??0);
          const bpw=parseFloat(b.power_w??0);
          const bc=socColor(bs);
          const bps=bpw>10?`+${Math.round(bpw)}W`:bpw<-10?`${Math.round(bpw)}W`:"0W";
          return `<div class="bat-row" style="animation-delay:${i*.06}s">
            <span class="bat-label">${esc(b.label||`Bat ${i+1}`)}</span>
            <div class="bat-bar-wrap"><div class="bat-bar-fill" style="width:${bs}%;background:${bc}"></div></div>
            <span class="bat-soc" style="color:${bc}">${bs.toFixed(0)}%</span>
            <span class="bat-pwr">${esc(bps)}</span>
          </div>`;
        }).join("")}
      </div>`;
    }

    // Verify
    let verHtml="";
    if(pendingPreset){
      const st=rateLimited?"limited":"pending";
      const msg=rateLimited?"Rate-limited (429) — wacht...":`Verificatie bezig… poging ${pendingRetries}`;
      verHtml=`<div class="verify-badge"><div class="verify-dot ${st}"></div><span>${esc(msg)}</span></div>`;
    }

    const sub=socLow?`⚠️ Laag — ${soc.toFixed(1)}%`:`${soc.toFixed(1)}%${capKwh?" · "+(capKwh*soc/100).toFixed(2)+" kWh opgeslagen":""}`;

    sh.innerHTML=`<style>${BAT_STYLES}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🔋</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub" style="color:${socLow?"var(--b-red)":"var(--b-subtext)"}">${esc(sub)}</div>
        </div>
        <span class="action-pill ${ac}">${actLabel(action)}</span>
      </div>
      <div class="main-row">
        <div class="arc-wrap">
          <svg class="arc-svg" width="110" height="80" viewBox="0 0 110 80">
            <path class="arc-track" d="${ap(R)}" stroke-dasharray="${circ}" stroke-dashoffset="0"/>
            <path class="arc-glow" d="${ap(R)}" stroke="${color}" stroke-dasharray="${circ}" stroke-dashoffset="${offset}"/>
            <path class="arc-fill" d="${ap(R)}" stroke="${color}" stroke-dasharray="${circ}" stroke-dashoffset="${offset}"/>
          </svg>
          <div class="arc-center">
            <span class="arc-pct" style="color:${color}">${soc.toFixed(0)}<span style="font-size:11px;color:var(--b-subtext)">%</span></span>
            <span class="arc-soc-label">SoC</span>
          </div>
        </div>
        <div class="stats-col">
          <div class="stat"><span class="stat-label">Vermogen</span><span class="stat-val ${pwrCls}">${esc(pwrStr)}</span></div>
          ${capKwh?`<div class="stat"><span class="stat-label">Capaciteit</span><span class="stat-val" style="color:var(--b-subtext)">${capKwh.toFixed(1)} kWh</span></div>`:""}
          <div class="stat"><span class="stat-label">Status</span><span class="stat-val" style="font-size:12px;color:${ac==="charge"?"var(--b-green)":ac==="discharge"?"var(--b-amber)":"var(--b-subtext)"}">${actLabel(action)}</span></div>
        </div>
      </div>
      <div class="flow-wrap">
        <div class="flow-labels"><span>⬇ Ontladen</span><span>Laden ⚡</span></div>
        <div class="flow-track">
          <div class="flow-center"></div>
          <div class="flow-fill" style="left:${barLeft}%;width:${barPct}%;background:${barColor}"></div>
        </div>
      </div>
      <div class="kwh-row">
        <div class="kwh-box"><span class="kwh-label">⚡ Geladen vandaag</span><span class="kwh-val" style="color:var(--b-green)">${chargeKwh.toFixed(2)} kWh</span></div>
        <div class="kwh-box"><span class="kwh-label">⬇ Ontladen vandaag</span><span class="kwh-val" style="color:var(--b-amber)">${disKwh.toFixed(2)} kWh</span></div>
      </div>
      ${tlHtml}${batsHtml}${verHtml}
      ${reason?`<div class="reason"><span>💡</span><span>${esc(reason)}</span></div>`:""}
    </div>`;
  }
  static getStubConfig(){ return {title:"Batterij"}; }
  getCardSize(){ return 6; }

  static getConfigElement(){ return document.createElement("cloudems-battery-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-battery-card"}; }
}



class CloudemsBatteryCardEditor extends HTMLElement {
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
        <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"Batterij"}"></div>
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
customElements.define("cloudems-battery-card-editor", CloudemsBatteryCardEditor);
customElements.define("cloudems-battery-card",CloudemsBatteryCard);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-battery-card",name:"CloudEMS Battery Card",description:"Batterij SoC, schema-tijdlijn, live vermogen & beslissing",preview:true});
console.info(`%c CLOUDEMS-BATTERY-CARD %c v${BAT_VERSION} `,"background:#3fb950;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0d1117;color:#3fb950;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
