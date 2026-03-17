// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Shutter Card  v2.0.0

const SHUTTER_VERSION = "2.3.0";
const SHUTTER_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host {
    --s-bg:#0e1520;--s-surface:#141c2b;--s-border:rgba(255,255,255,0.06);
    --s-sky:#7dd3fc;--s-sky-dim:rgba(125,211,252,0.10);
    --s-indigo:#818cf8;--s-indigo-dim:rgba(129,140,248,0.10);
    --s-green:#4ade80;--s-amber:#fb923c;--s-red:#f87171;
    --s-muted:#374151;--s-subtext:#6b7280;--s-text:#f1f5f9;
    --s-mono:'JetBrains Mono',monospace;--s-sans:'Syne',sans-serif;--s-r:14px;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--s-bg);border-radius:var(--s-r);border:1px solid var(--s-border);overflow:hidden;font-family:var(--s-sans);transition:border-color .3s,box-shadow .3s;}
  .card:hover{border-color:rgba(125,211,252,.15);box-shadow:0 8px 40px rgba(0,0,0,.7);}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid var(--s-border);position:relative;overflow:hidden;}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,var(--s-sky-dim) 0%,transparent 60%);pointer-events:none;}
  .hdr-icon{font-size:18px;flex-shrink:0;}
  .hdr-texts{flex:1;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--s-text);letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:var(--s-subtext);margin-top:2px;}
  .hdr-badges{display:flex;gap:5px;}
  .badge{font-family:var(--s-mono);font-size:9px;padding:3px 8px;border-radius:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;}
  .badge-ok{background:var(--s-sky-dim);color:var(--s-sky);border:1px solid rgba(125,211,252,.2);}
  .badge-warn{background:rgba(251,146,60,.12);color:var(--s-amber);border:1px solid rgba(251,146,60,.2);}
  .badge-auto{background:var(--s-indigo-dim);color:var(--s-indigo);border:1px solid rgba(129,140,248,.2);}
  .sum-strip{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid var(--s-border);}
  .sum-box{padding:11px 14px;border-right:1px solid var(--s-border);display:flex;flex-direction:column;gap:2px;text-align:center;}
  .sum-box:last-child{border-right:none;}
  .sum-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--s-muted);}
  .sum-val{font-family:var(--s-mono);font-size:18px;font-weight:700;}
  .shutters-section{padding:10px 18px 12px;}
  .shutter-row{padding:10px 0;border-bottom:1px solid rgba(255,255,255,.04);animation:fadeUp .35s ease both;}
  .shutter-row:last-child{border-bottom:none;}
  .shutter-top{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
  .shutter-name{font-size:13px;font-weight:600;color:var(--s-text);flex:1;}
  .auto-badge{font-family:var(--s-mono);font-size:9px;font-weight:600;padding:2px 7px;border-radius:10px;text-transform:uppercase;letter-spacing:.06em;}
  .auto-badge.on{background:var(--s-sky-dim);color:var(--s-sky);border:1px solid rgba(125,211,252,.2);}
  .auto-badge.off{background:rgba(248,113,113,.12);color:var(--s-red);border:1px solid rgba(248,113,113,.2);}
  .auto-badge.ov{background:rgba(251,146,60,.12);color:var(--s-amber);border:1px solid rgba(251,146,60,.2);}
  /* Shutter visual — animated slats */
  .blind-wrap{width:100%;height:28px;background:rgba(255,255,255,.03);border-radius:4px;overflow:hidden;position:relative;margin-bottom:6px;border:1px solid var(--s-border);}
  .blind-closed{position:absolute;left:0;top:0;height:100%;background:linear-gradient(90deg,var(--s-sky-dim),rgba(125,211,252,.06));border-right:1px solid rgba(125,211,252,.2);transition:width .8s cubic-bezier(.4,0,.2,1);}
  .blind-pct{position:absolute;right:8px;top:50%;transform:translateY(-50%);font-family:var(--s-mono);font-size:10px;font-weight:600;color:var(--s-sky);}
  .blind-slats{position:absolute;left:0;top:0;height:100%;overflow:hidden;transition:width .8s cubic-bezier(.4,0,.2,1);}
  .slat{height:4px;background:rgba(125,211,252,.25);border-radius:1px;margin:3px 4px;}
  .shutter-meta{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;}
  .meta-chip{font-family:var(--s-mono);font-size:9px;padding:2px 7px;border-radius:10px;background:rgba(255,255,255,.05);color:var(--s-subtext);border:1px solid var(--s-border);}
  .meta-chip.action-open{background:rgba(74,222,128,.08);color:var(--s-green);border-color:rgba(74,222,128,.2);}
  .meta-chip.action-close{background:rgba(125,211,252,.08);color:var(--s-sky);border-color:rgba(125,211,252,.2);}
  .meta-chip.action-idle{color:var(--s-muted);}
  .meta-chip.override{background:rgba(251,146,60,.1);color:var(--s-amber);border-color:rgba(251,146,60,.2);}
  .shadow-hint{font-size:10px;color:var(--s-subtext);font-style:italic;padding:3px 0 0;display:flex;gap:5px;align-items:center;}
  .overrides-section{border-top:1px solid var(--s-border);padding:10px 18px 12px;}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--s-muted);margin-bottom:7px;}
  .ov-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.03);animation:fadeUp .3s ease both;}
  .ov-row:last-child{border-bottom:none;}
  .ov-name{flex:1;font-size:12px;color:var(--s-text);}
  .ov-timer{font-family:var(--s-mono);font-size:12px;font-weight:600;color:var(--s-amber);}
  .module-off{padding:10px 18px;background:rgba(248,113,113,.08);border-bottom:1px solid rgba(248,113,113,.2);font-size:11px;font-weight:600;color:var(--s-red);}
  .empty{padding:36px;text-align:center;color:var(--s-muted);display:flex;flex-direction:column;align-items:center;gap:12px;}
  .empty-icon{font-size:40px;opacity:.3;}
  .unavail{padding:16px 18px;text-align:center;color:var(--s-amber);font-size:12px;}
  @keyframes fadeUp{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
`;

const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

class CloudemsShutterCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._prev=""; }
  setConfig(c){ this._cfg={title:c.title??"Rolluiken",show_learning:c.show_learning!==false,...c}; this._render(); }
  set hass(h){
    this._hass=h;
    const st=h.states["sensor.cloudems_status"];
    const sw=h.states["switch.cloudems_module_rolluiken"];
    // Hash only meaningful shutter data — NOT last_updated/timer countdowns
    const shutterData=st?.attributes?.shutters??{};
    const shutters=shutterData.shutters??[];
    const shutterHash=shutters.map(s=>`${s.entity_id}:${s.position}:${s.last_action}:${s.auto_enabled}:${s.override_active}:${s.schedule_learning}`).join("|");
    // Also track learning switch states
    const learnHash=Object.keys(h.states).filter(k=>k.startsWith("switch.cloudems_shutter_")&&k.endsWith("_learning")).map(k=>h.states[k].state).sort().join("|");
    // For override timers: only re-render when a timer appears/disappears (not every tick)
    const ovActive=Object.keys(h.states).filter(k=>
      k.startsWith("sensor.cloudems_rolluik_")&&k.endsWith("_override_restant")&&
      h.states[k].state&&h.states[k].state!=="00:00:00"&&
      h.states[k].state!=="unavailable"&&h.states[k].state!=="unknown"
    ).sort().join(",");
    const j=JSON.stringify([shutterHash,learnHash,sw?.state,st?.state,ovActive]);
    if(j!==this._prev){this._prev=j;this._render();}
  }
  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass, c=this._cfg??{};
    if(!h){ sh.innerHTML=`<style>${SHUTTER_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">🪟</span></div></div>`; return; }

    const stS=h.states["sensor.cloudems_status"];
    const sw=h.states["switch.cloudems_module_rolluiken"];

    if(!stS||stS.state==="unavailable"||stS.state==="unknown"){
      sh.innerHTML=`<style>${SHUTTER_STYLES}</style><div class="card">
        <div class="hdr"><span class="hdr-icon">🪟</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub" style="color:var(--s-amber)">⚠️ CloudEMS status sensor niet beschikbaar</div></div></div>
        <div class="unavail">sensor.cloudems_status is ${esc(stS?.state??"niet gevonden")} — controleer de integratie logs.</div>
      </div>`;
      return;
    }

    const shutterData=stS.attributes?.shutters??{};
    const shutters=shutterData.shutters??[];
    const total=shutters.length;
    const autoOn=shutters.filter(s=>s.auto_enabled!==false).length;
    const overrides=shutters.filter(s=>s.override_active).length;
    const openCnt=shutters.filter(s=>(s.last_action||"").toLowerCase()==="open").length;

    const hasWarn=overrides>0||shutters.some(s=>s.auto_enabled===false);
    const moduleOff=sw?.state==="off";

    if(total===0){
      sh.innerHTML=`<style>${SHUTTER_STYLES}</style><div class="card">
        ${moduleOff?`<div class="module-off">⚠️ Rolluiken module staat uit — schakel in via Configuratie.</div>`:""}
        <div class="hdr"><span class="hdr-icon">🪟</span><div class="hdr-texts"><div class="hdr-title">${esc(c.title)}</div><div class="hdr-sub">Geen rolluiken geconfigureerd</div></div></div>
        <div class="empty"><span class="empty-icon">🪟</span>Configureer rolluiken via <strong>CloudEMS → Rolluiken</strong>.</div>
      </div>`;
      return;
    }

    // Shutter rows
    const rows=shutters.map((s,i)=>{
      const pos=parseFloat(s.position??s.current_position??-1);
      const act=(s.last_action||"").toLowerCase();
      const reason=s.last_reason||"";
      const shadow=s.shadow_action||"";
      const shadowReason=s.shadow_reason||"";
      const autoEnabled=s.auto_enabled!==false;
      const overrideActive=s.override_active||false;
      const openToday=s.schedule_open_today||"08:00";
      const closeToday=s.schedule_close_today||"20:00";
      const needsData=s.schedule_needs_data||0;
      const isLearned=needsData===0 && s.schedule_learning!==false;
      const label=s.label||s.entity_id||`Rolluik ${i+1}`;
      const scheduleLearning=s.schedule_learning!==false;
      const scheduleData=s.schedule_learned||{};

      // Auto badge
      const autoCls=!autoEnabled?"off":overrideActive?"ov":"on";
      const autoLabel=!autoEnabled?"🔴 UIT":overrideActive?"🟠 Override":"🤖 AAN";
      // Learning switch state
      const safeName=s.entity_id.split(".").pop().replace(/-/g,"_");
      const learnSwitchId=`switch.cloudems_shutter_${safeName}_learning`;
      const learnProgSensorId=`sensor.cloudems_rolluik_${safeName}_leer_voortgang`;
      const learnSwitchState=h.states[learnSwitchId];
      const learnProgState=h.states[learnProgSensorId];
      const learningEnabled=learnSwitchState?learnSwitchState.state==="on":scheduleLearning;
      const needsDataFinal=learnProgState&&learnProgState.state!=='unavailable'&&learnProgState.state!=='unknown'?parseInt(learnProgState.state)||0:needsData;

      // Action chip
      const actChipCls=act==="open"?"action-open":act==="close"?"action-close":"action-idle";
      const actIcon=act==="open"?"🔼":act==="close"?"🔽":"⏸";

      // Blind visual — slats showing position
      const closedPct=pos>=0?(100-pos):50;
      const nSlats=5;
      const slatsHtml=Array.from({length:nSlats},()=>`<div class="slat"></div>`).join("");

      // Learned schedule section
      let schedHtml="";
      if(c.show_learning!==false && s.schedule_learning!==false){
        if(needsDataFinal>0){
          // First-time hint
          schedHtml=`<div style="margin:6px 0 0;padding:6px 8px;background:rgba(255,200,0,0.08);border-radius:8px;border:1px solid rgba(255,200,0,0.2)">
            <div style="font-size:10px;color:rgba(255,200,0,0.8)">📅 Tijdleren: bedien dit rolluik nog ~${needsDataFinal}× op je gewenste tijd</div>
            <div style="font-size:9px;color:rgba(255,255,255,0.3);margin-top:2px">Starttijden: 🔼 ${openToday} · 🔽 ${closeToday}</div>
          </div>`;
        } else {
          // Today times prominent + per-day table
          const openData=scheduleData.open||{};
          const closeData=scheduleData.close||{};
          const dayKeys=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
          const dayNames=["Ma","Di","Wo","Do","Vr","Za","Zo"];
          const tableRows=dayKeys.map((dk,di)=>{
            const od=openData[dk]||{};
            const cd=closeData[dk]||{};
            const oConf=od.confidence||0;
            const cConf=cd.confidence||0;
            const oApplied=od.applied||od.learned||"08:00";
            const cApplied=cd.applied||cd.learned||"20:00";
            const oColor=oConf>=0.8?"var(--s-green)":oConf>=0.5?"var(--s-amber)":"var(--s-muted)";
            const cColor=cConf>=0.8?"var(--s-green)":cConf>=0.5?"var(--s-amber)":"var(--s-muted)";
            const oSamples=Math.round(od.effective_samples||od.samples||0);
            const cSamples=Math.round(cd.effective_samples||cd.samples||0);
            return `<tr>
              <td style="color:var(--s-muted);padding:2px 5px;font-size:10px">${dayNames[di]}</td>
              <td style="color:${oColor};padding:2px 5px;font-size:10px;font-family:monospace">🔼 ${oApplied}</td>
              <td style="color:var(--s-muted);padding:2px 2px;font-size:9px">${oSamples>0?Math.round(oConf*100)+"%":"-"}</td>
              <td style="color:${cColor};padding:2px 5px;font-size:10px;font-family:monospace">🔽 ${cApplied}</td>
              <td style="color:var(--s-muted);padding:2px 2px;font-size:9px">${cSamples>0?Math.round(cConf*100)+"%":"-"}</td>
            </tr>`;
          }).join("");
          schedHtml=`<div style="margin:6px 0 0">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <div style="flex:1;font-size:11px;color:var(--s-green)">🔼 ${openToday}</div>
              <div style="flex:1;font-size:11px;color:rgba(180,120,255,0.9)">🔽 ${closeToday}</div>
              <span style="font-size:9px;color:var(--s-muted)">${isLearned?"🧠 geleerd":"📅 standaard"}</span>
            </div>
            <details style="padding:0">
              <summary style="font-size:9px;color:var(--s-muted);cursor:pointer;list-style:none">
                📅 Per dag <span style="opacity:.6">(klik voor details)</span>
              </summary>
              <table style="width:100%;border-collapse:collapse;margin-top:4px">${tableRows}</table>
              <button onclick="this.getRootNode().host._resetSchedule('${s.entity_id}')"
                style="margin-top:6px;font-size:9px;padding:3px 8px;background:rgba(255,80,80,0.15);border:1px solid rgba(255,80,80,0.3);border-radius:6px;color:rgba(255,120,120,0.9);cursor:pointer">
                🗑️ Leerdata wissen
              </button>
            </details>
          </div>`;
        }
      } else if(s.schedule_learning===false){
        schedHtml=`<div style="font-size:9px;color:var(--s-muted);padding:3px 0;opacity:.5">📅 Tijdleren uit · 🔼 ${openToday} · 🔽 ${closeToday}</div>`;
      }

      return `<div class="shutter-row" style="animation-delay:${i*.07}s">
        <div class="shutter-top">
          <span class="shutter-name">${esc(label)}</span>
          <span class="auto-badge ${autoCls}">${autoLabel}</span>
          <span class="auto-badge ${learningEnabled?'on':'off'}" title="${learningEnabled?'Tijdleren aan — CloudEMS leert je open/sluit tijden':'Tijdleren uit — vaste tijden uit config'}" style="cursor:pointer;margin-left:4px;" onclick="this.getRootNode().host._toggleLearning('${learnSwitchId}','${learnSwitchState?learnSwitchState.state:'on'}')">🧠 ${learningEnabled?'Leert':'Vast'}</span>
        </div>
        <div class="blind-wrap">
          <div class="blind-closed" style="width:${Math.min(closedPct,100)}%">
            <div class="blind-slats" style="width:100%">${slatsHtml}</div>
          </div>
          <span class="blind-pct">${pos>=0?Math.round(pos)+"%":"—"}</span>
        </div>
        <div class="shutter-meta">
          <span class="meta-chip ${actChipCls}">${actIcon} ${esc(act||"idle")}</span>
          ${overrideActive?`<span class="meta-chip override">⏱️ Override</span>`:""}
          ${reason?`<span class="meta-chip">${esc(reason.length>40?reason.slice(0,40)+"…":reason)}</span>`:""}
        </div>
        ${shadow&&shadow!==act&&!autoEnabled?`<div class="shadow-hint">🤖 <span>Automaat zou: <strong>${esc(shadow)}</strong>${shadowReason?" — "+esc(shadowReason):""}</span></div>`:""}
        ${c.show_orientation_learning!==false&&(shadow||s.orientation||s.sun_elevation_threshold!=null)?`<div style="margin:5px 0 0;padding:5px 8px;background:rgba(129,140,248,0.07);border-radius:8px;border:1px solid rgba(129,140,248,0.18)"><div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(129,140,248,0.6);margin-bottom:4px">🧭 Oriëntatie leren</div><div style="display:flex;flex-wrap:wrap;gap:6px">${s.orientation?`<span style="font-family:monospace;font-size:10px;padding:2px 7px;border-radius:8px;background:rgba(129,140,248,0.12);color:rgba(129,140,248,0.9);border:1px solid rgba(129,140,248,0.2)">🧭 ${esc(s.orientation)}</span>`:""
        }${s.sun_elevation_threshold!=null?`<span style="font-family:monospace;font-size:10px;padding:2px 7px;border-radius:8px;background:rgba(129,140,248,0.12);color:rgba(129,140,248,0.9);border:1px solid rgba(129,140,248,0.2)">☀️ drempel ${s.sun_elevation_threshold}°</span>`:""
        }${shadow?`<span style="font-family:monospace;font-size:10px;padding:2px 7px;border-radius:8px;background:rgba(125,211,252,0.08);color:var(--s-sky);border:1px solid rgba(125,211,252,0.2)">🤖 ${esc(shadow)}</span>`:""
        }${shadowReason?`<span style="font-size:9px;color:var(--s-subtext);padding:2px 0">${esc(shadowReason.length>50?shadowReason.slice(0,50)+"…":shadowReason)}</span>`:""}</div></div>`:""}
        ${schedHtml}
      </div>`;
    }).join("");

    // Override timers — guard against state objects without entity_id
    const ovEntities=Object.values(h.states).filter(e=>
      e?.entity_id?.startsWith("sensor.cloudems_rolluik_")&&
      e.entity_id.endsWith("_override_restant")&&
      e.state&&e.state!=="00:00:00"&&
      e.state!=="unavailable"&&e.state!=="unknown"
    );
    const ovHtml=ovEntities.length>0?`
      <div class="overrides-section">
        <div class="sec-title">⏱️ Actieve overrides</div>
        ${ovEntities.map((e,i)=>{
          const name=(e.attributes.friendly_name||e.entity_id).replace(/override restant/i,"").trim();
          return `<div class="ov-row" style="animation-delay:${i*.05}s">
            <span>⏰</span><span class="ov-name">${esc(name)}</span>
            <span class="ov-timer">${esc(e.state)}</span>
          </div>`;
        }).join("")}
      </div>`:"";

    sh.innerHTML=`<style>${SHUTTER_STYLES}</style>
    <div class="card">
      ${moduleOff?`<div class="module-off">⚠️ Rolluiken module staat uit — schakel in via Configuratie.</div>`:""}
      <div class="hdr">
        <span class="hdr-icon">🪟</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub">${autoOn} automaat aan · ${openCnt} open · ${total} totaal</div>
        </div>
        <div class="hdr-badges">
          <span class="badge ${hasWarn?"badge-warn":"badge-ok"}">${total} rolluik${total!==1?"en":""}</span>
          ${autoOn>0?`<span class="badge badge-auto">${autoOn} auto</span>`:""}
        </div>
      </div>
      <div class="sum-strip">
        <div class="sum-box"><span class="sum-label">Totaal</span><span class="sum-val" style="color:var(--s-sky)">${total}</span></div>
        <div class="sum-box"><span class="sum-label">Automaat</span><span class="sum-val" style="color:${autoOn>0?"var(--s-green)":"var(--s-muted)"}">${autoOn}</span></div>
        <div class="sum-box"><span class="sum-label">Overrides</span><span class="sum-val" style="color:${overrides>0?"var(--s-amber)":"var(--s-muted)"}">${overrides}</span></div>
      </div>
      <div class="shutters-section">${rows}</div>
      ${ovHtml}
    </div>`;
  }
  _toggleLearning(switchEntityId, currentState){
    if(!this._hass) return;
    const newState = currentState === 'on' ? 'off' : 'on';
    const service = newState === 'on' ? 'turn_on' : 'turn_off';
    this._hass.callService('switch', service, {entity_id: switchEntityId})
      .catch(e => console.warn('CloudEMS: toggle learning failed', e));
  }
  _resetSchedule(entityId){
    if(!this._hass) return;
    if(!confirm(`Leerdata wissen voor ${entityId}?\nDit kan niet ongedaan worden.`)) return;
    this._hass.callService('cloudems','reset_shutter_schedule',{entity_id: entityId})
      .catch(()=>{
        // Fallback: call via persistent notification
        this._hass.callService('persistent_notification','create',{
          message: `Reset shutter schedule voor ${entityId} via CloudEMS instellingen.`,
          title: 'CloudEMS'
        });
      });
  }
  static getStubConfig(){ return {title:"Rolluiken",show_learning:true}; }
  getCardSize(){ return 6; }

  static getConfigElement(){ return document.createElement("cloudems-shutter-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-shutter-card"}; }
}



class CloudemsShutterCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._hass=null; this._cfg={}; }
  setConfig(c){ this._cfg={...c}; this._render(); }
  set hass(h){ this._hass=h; this._render(); }
  _fire(){
    this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true}));
  }
  _render(){
    const cfg=this._cfg||{};
    const h=this._hass;

    // Build per-shutter learning rows if hass available
    let shutterRows="";
    if(h){
      const st=h.states["sensor.cloudems_status"];
      const shutters=(st?.attributes?.shutters?.shutters)||[];
      if(shutters.length>0){
        shutterRows=`<div class="section-title">🧠 Tijdleren per rolluik</div>`+shutters.map(s=>{
          const safeName=s.entity_id.split(".").pop().replace(/-/g,"_");
          const swId=`switch.cloudems_shutter_${safeName}_learning`;
          const swState=h.states[swId];
          const label=s.label||s.entity_id||safeName;
          const isOn=swState?swState.state==="on":s.schedule_learning!==false;
          const unavail=!swState;
          return `<div class="row">
            <label class="lbl" title="${swId}">${label}</label>
            <button class="learn-btn ${isOn?"btn-on":"btn-off"}" data-switch="${swId}" data-state="${isOn?"on":"off"}" ${unavail?"disabled title='Switch niet gevonden'":""}>
              🧠 ${isOn?"Leert":"Vast"}
            </button>
          </div>`;
        }).join("");
      }
    }

    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.section-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--secondary-text-color,#888);padding:8px 0 4px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.row:last-child{border-bottom:none;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color,#03a9f4);cursor:pointer;}
.learn-btn{font-size:11px;padding:4px 10px;border-radius:8px;cursor:pointer;border:1px solid;font-weight:600;transition:all .2s;}
.btn-on{background:rgba(125,211,252,0.12);color:#7dd3fc;border-color:rgba(125,211,252,0.3);}
.btn-off{background:rgba(248,113,113,0.12);color:#f87171;border-color:rgba(248,113,113,0.3);}
.learn-btn:disabled{opacity:.4;cursor:not-allowed;}
</style>
<div class="wrap">
  <div class="section-title">⚙️ Weergave</div>
  <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"Rolluiken"}"></div>
  <div class="row"><label class="lbl">Toon leervoortgang</label><input type="checkbox" name="show_learning" ${cfg.show_learning!==false?"checked":""}></div>
  <div class="row"><label class="lbl">Toon oriëntatie leren</label><input type="checkbox" name="show_orientation_learning" ${cfg.show_orientation_learning!==false?"checked":""}></div>
  ${shutterRows}
</div>`;

    // Text / checkbox change handlers
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{
        const n=el.name, nc={...this._cfg};
        if(n==="title") nc[n]=el.value;
        if(n==="show_learning") nc[n]=el.checked;
        if(n==="show_orientation_learning") nc[n]=el.checked;
        this._cfg=nc; this._fire();
      });
    });

    // Per-shutter learning toggle buttons
    this.shadowRoot.querySelectorAll(".learn-btn").forEach(btn=>{
      btn.addEventListener("click",()=>{
        if(!this._hass||btn.disabled) return;
        const swId=btn.dataset.switch;
        const cur=btn.dataset.state;
        const svc=cur==="on"?"turn_off":"turn_on";
        this._hass.callService("switch",svc,{entity_id:swId})
          .catch(e=>console.warn("CloudEMS editor: toggle learning failed",e));
      });
    });
  }
}
customElements.define("cloudems-shutter-card-editor", CloudemsShutterCardEditor);
customElements.define("cloudems-shutter-card",CloudemsShutterCard);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-shutter-card",name:"CloudEMS Shutter Card",description:"Rolluiken status, positie-visualisatie & automaat-beheer",preview:true});
console.info(`%c CLOUDEMS-SHUTTER-CARD %c v${SHUTTER_VERSION} `,"background:#7dd3fc;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0e1520;color:#7dd3fc;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
