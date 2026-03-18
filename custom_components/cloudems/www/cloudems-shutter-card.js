// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Shutter Card  v3.0.0

const SHUTTER_VERSION = "3.1.0";
const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

const CSS = `
  :host {
    --s-bg:var(--ha-card-background,var(--card-background-color,#1c1c1c));
    --s-surface:rgba(255,255,255,.04);
    --s-border:rgba(255,255,255,.08);
    --s-text:var(--primary-text-color,#e8eaed);
    --s-muted:var(--secondary-text-color,#9aa0a6);
    --s-green:#1D9E75;--s-amber:#BA7517;--s-blue:#378ADD;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--s-bg);border-radius:12px;overflow:hidden;font-family:var(--primary-font-family,sans-serif);}
  .hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 12px;border-bottom:0.5px solid var(--s-border);}
  .hdr-title{font-size:13px;font-weight:500;color:var(--s-muted);}
  .hdr-btns{display:flex;gap:6px;}
  .btn-all{font-size:12px;padding:4px 10px;border-radius:6px;border:0.5px solid var(--s-border);background:var(--s-surface);cursor:pointer;color:var(--s-text);}
  .btn-all:hover{background:rgba(255,255,255,.08);}
  .body{padding:12px 16px;}
  .ov-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:0.5px solid var(--s-border);}
  .ov-row:last-child{border-bottom:none;}
  .ov-name{font-size:14px;font-weight:500;color:var(--s-text);min-width:110px;}
  .ov-sun{font-size:13px;min-width:16px;text-align:center;}
  .badge{font-size:11px;padding:2px 7px;border-radius:4px;font-weight:500;}
  .b-on{background:rgba(29,158,117,.15);color:#4ade80;}
  .b-off{background:rgba(255,255,255,.07);color:var(--s-muted);}
  .b-ov{background:rgba(186,117,23,.18);color:#fbbf24;}
  .bar-wrap{flex:1;height:7px;background:rgba(255,255,255,.08);border-radius:4px;overflow:hidden;}
  .bar-fill{height:100%;border-radius:4px;background:var(--s-green);transition:width .3s;}
  .pct{font-size:13px;color:var(--s-muted);min-width:32px;text-align:right;}
  .bs{width:26px;height:26px;border-radius:5px;border:0.5px solid var(--s-border);background:var(--s-surface);cursor:pointer;font-size:11px;color:var(--s-text);display:flex;align-items:center;justify-content:center;}
  .bs:hover{background:rgba(255,255,255,.1);}
  .divider{border:none;border-top:0.5px solid var(--s-border);margin:12px 0;}
  .detail-hdr{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
  .detail-hdr label{font-size:13px;color:var(--s-muted);white-space:nowrap;}
  .detail-hdr select{flex:1;font-size:14px;background:var(--s-surface);border:0.5px solid var(--s-border);border-radius:6px;color:var(--s-text);padding:5px 8px;}
  .dr{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid var(--s-border);font-size:14px;}
  .dr:last-child{border-bottom:none;}
  .dl{color:var(--s-muted);}
  .dv{color:var(--s-text);font-weight:500;}
  .tog{width:36px;height:20px;border-radius:10px;cursor:pointer;position:relative;border:none;transition:background .2s;flex-shrink:0;}
  .tog.on{background:var(--s-green);}.tog.off{background:rgba(255,255,255,.15);}
  .tog::after{content:'';position:absolute;width:14px;height:14px;border-radius:50%;background:#fff;top:3px;transition:left .2s;}
  .tog.on::after{left:19px;}.tog.off::after{left:3px;}
  .pos-wrap{display:flex;align-items:center;gap:8px;flex:1;margin-left:12px;}
  .pos-wrap input[type=range]{flex:1;}
  .learn-btn{width:100%;font-size:13px;padding:7px 10px;border-radius:8px;border:0.5px solid var(--s-border);background:var(--s-surface);cursor:pointer;color:var(--s-muted);text-align:left;margin-top:10px;}
  .learn-btn:hover{background:rgba(255,255,255,.07);}
  .lr{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:0.5px solid var(--s-border);}
  .lr:last-child{border-bottom:none;}
  .lname{font-size:13px;font-weight:500;color:var(--s-text);min-width:110px;}
  .pw{flex:1;height:5px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;}
  .pf{height:100%;border-radius:3px;background:var(--s-blue);}
  .lpct{font-size:12px;color:var(--s-muted);min-width:30px;text-align:right;}
  .lori{font-size:12px;color:var(--s-muted);min-width:60px;text-align:right;}
  .learn-panel{margin-top:10px;}
  .empty{padding:32px;text-align:center;color:var(--s-muted);font-size:13px;}
  .module-warn{padding:8px 16px;background:rgba(192,57,43,.1);border-bottom:0.5px solid rgba(192,57,43,.3);font-size:12px;color:#f87171;}
`;

class CloudemsShutterCard extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._prev = "";
    this._selIdx = 0;
    this._learnOpen = false;
  }

  setConfig(c){ this._cfg = {title:"Rolluiken",...c}; this._render(); }

  set hass(h){
    this._hass = h;
    const st = h.states["sensor.cloudems_status"];
    const shutters = (st?.attributes?.shutters?.shutters) ?? [];
    const hash = shutters.map(s =>
      `${s.entity_id}:${s.position??s.current_position}:${s.last_action}:${s.auto_enabled}:${s.override_active}`
    ).join("|");
    const sw = h.states["switch.cloudems_module_rolluiken"]?.state;
    const j = JSON.stringify([hash, sw]);
    if(j !== this._prev){ this._prev = j; this._render(); }
  }

  _sunHint(s){
    return (s.shadow_action === "close" && (s.shadow_reason||"").toLowerCase().includes("zon"))
        || (s.shadow_reason||"").toLowerCase().includes("zon");
  }

  _render(){
    const sh = this.shadowRoot; if(!sh) return;
    const h = this._hass, c = this._cfg ?? {};
    if(!h){ sh.innerHTML=`<style>${CSS}</style><div class="card"><div class="empty">Laden…</div></div>`; return; }

    const stS = h.states["sensor.cloudems_status"];
    const sw = h.states["switch.cloudems_module_rolluiken"];
    const moduleOff = sw?.state === "off";
    const shutterData = stS?.attributes?.shutters ?? {};
    const shutters = shutterData.shutters ?? [];

    if(!stS || stS.state === "unavailable"){
      sh.innerHTML=`<style>${CSS}</style><div class="card"><div class="empty">sensor.cloudems_status niet beschikbaar</div></div>`;
      return;
    }
    if(shutters.length === 0){
      sh.innerHTML=`<style>${CSS}</style><div class="card">
        ${moduleOff?`<div class="module-warn">⚠️ Rolluiken module staat uit — schakel in via Configuratie.</div>`:""}
        <div class="empty">Geen rolluiken geconfigureerd.<br>Koppel via CloudEMS → Rolluiken.</div>
      </div>`;
      return;
    }

    if(this._selIdx >= shutters.length) this._selIdx = 0;

    // Overzicht
    const ovRows = shutters.map((s,i) => {
      const pos = Math.round(parseFloat(s.position ?? s.current_position ?? 0));
      const auto = s.auto_enabled !== false;
      const over = s.override_active || false;
      const label = s.label || s.entity_id || `Rolluik ${i+1}`;
      const bc = over?"b-ov":auto?"b-on":"b-off";
      const bt = over?"override":auto?"auto":"uit";
      const sun = this._sunHint(s);
      return `<div class="ov-row">
        <span class="ov-name">${esc(label)}</span>
        <span class="ov-sun">${sun?"☀":""}</span>
        <span class="badge ${bc}">${bt}</span>
        <div class="bar-wrap"><div class="bar-fill" style="width:${pos}%"></div></div>
        <span class="pct">${pos}%</span>
        <button class="bs" data-action="up" data-idx="${i}">&#9650;</button>
        <button class="bs" data-action="dn" data-idx="${i}">&#9660;</button>
      </div>`;
    }).join("");

    // Detail
    const s = shutters[this._selIdx];
    const pos = Math.round(parseFloat(s.position ?? s.current_position ?? 0));
    const auto = s.auto_enabled !== false;
    const over = s.override_active || false;
    const sun = this._sunHint(s);
    const safeName = (s.entity_id||"").split(".").pop().replace(/-/g,"_");
    const autoSwitchId   = `switch.cloudems_shutter_${safeName}_auto`;
    const learnSwitchId  = `switch.cloudems_shutter_${safeName}_learning`;
    const learnSwitchSt  = h.states[learnSwitchId];
    const learnEnabled   = learnSwitchSt ? learnSwitchSt.state === 'on' : true;
    const ovSensor = h.states[`sensor.cloudems_rolluik_${safeName}_override_restant`];
    const ovTime = ovSensor?.state && ovSensor.state !== "00:00:00" && ovSensor.state !== "unavailable" ? ovSensor.state : null;

    const selectOpts = shutters.map((s2,i) =>
      `<option value="${i}" ${i===this._selIdx?"selected":""}>${esc(s2.label||s2.entity_id||`Rolluik ${i+1}`)}</option>`
    ).join("");

    // Leervoortgang
    const learnRows = shutters.map(s2 => {
      const sn = (s2.entity_id||"").split(".").pop().replace(/-/g,"_");
      const prog = (() => {
        const ps = h.states[`sensor.cloudems_rolluik_${sn}_leer_voortgang`];
        if(ps && ps.state !== "unavailable" && ps.state !== "unknown") return parseInt(ps.state)||0;
        return s2.schedule_needs_data === 0 ? 100 : 0;
      })();
      return `<div class="lr">
        <span class="lname">${esc(s2.label||s2.entity_id||sn)}</span>
        <div class="pw"><div class="pf" style="width:${prog}%"></div></div>
        <span class="lpct">${prog}%</span>
        <span class="lori">${esc(s2.orientation||"leren…")}</span>
      </div>`;
    }).join("");

    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      ${moduleOff?`<div class="module-warn">⚠️ Rolluiken module staat uit — schakel in via Configuratie.</div>`:""}
      <div class="hdr">
        <span class="hdr-title">${esc(c.title??"Rolluiken")}</span>
        <div class="hdr-btns">
          <button class="btn-all" data-action="all-up">&#9650; Alles</button>
          <button class="btn-all" data-action="all-dn">&#9660; Alles</button>
        </div>
      </div>
      <div class="body">
        ${ovRows}
        <hr class="divider">
        <div class="detail-hdr">
          <label>Detail</label>
          <select id="shutter-picker">${selectOpts}</select>
        </div>
        <div class="dr">
          <span class="dl">Positie</span>
          <div class="pos-wrap">
            <input type="range" min="0" max="100" step="5" value="${pos}" data-action="pos">
            <span class="dv" style="min-width:32px;text-align:right" id="pos-lbl">${pos}%</span>
          </div>
        </div>
        <div class="dr">
          <span class="dl">🤖 Automaat</span>
          <button class="tog ${auto?"on":"off"}" data-action="toggle-auto" data-switch="${autoSwitchId}" data-state="${auto?"on":"off"}"></button>
        </div>
        <div class="dr">
          <span class="dl">🧠 Tijdschema leren</span>
          <button class="tog ${learnEnabled?"on":"off"}" data-action="toggle-learn-switch" data-switch="${learnSwitchId}" data-state="${learnEnabled?"on":"off"}"></button>
        </div>
        <div class="dr"><span class="dl">Openen</span><span class="dv">${esc(s.schedule_open_today||"09:00")}</span></div>
        <div class="dr"><span class="dl">Sluiten</span><span class="dv">${esc(s.schedule_close_today||"21:00")}</span></div>
        <div class="dr"><span class="dl">Zonnestand</span><span class="dv">${sun?"☀ Zon schijnt op dit rolluik":"Geen directe zon"}</span></div>
        ${over&&ovTime?`<div class="dr"><span class="dl">Override restant</span><span class="dv" style="color:#fbbf24">${esc(ovTime)}</span></div>`:""}
        <button class="learn-btn" data-action="toggle-learn">
          ${this._learnOpen?"▼":"▶"} Leervoortgang &amp; oriëntatie
        </button>
        ${this._learnOpen?`<div class="learn-panel">${learnRows}</div>`:""}
      </div>
    </div>`;

    // Events
    sh.getElementById("shutter-picker")?.addEventListener("change", e => {
      this._selIdx = parseInt(e.target.value);
      this._render();
    });

    const slider = sh.querySelector("input[type=range][data-action=pos]");
    slider?.addEventListener("input", e => {
      sh.getElementById("pos-lbl").textContent = e.target.value + "%";
    });
    slider?.addEventListener("change", e => {
      const s2 = shutters[this._selIdx];
      if(!s2||!this._hass) return;
      this._hass.callService("cover","set_cover_position",{entity_id:s2.entity_id,position:parseInt(e.target.value)})
        .catch(err=>console.warn("CloudEMS shutter pos:",err));
    });

    sh.querySelector(".card")?.addEventListener("click", e => {
      const btn = e.target.closest("[data-action]");
      if(!btn) return;
      const action = btn.dataset.action;

      if(action === "toggle-learn"){
        this._learnOpen = !this._learnOpen;
        this._render();
        return;
      }
      if(action === "toggle-learn-switch"){
        const sw = btn.dataset.switch;
        const newState = btn.dataset.state === "on" ? "off" : "on";
        if(sw && this._hass){
          this._hass.callService("switch", newState==="on"?"turn_on":"turn_off", {entity_id: sw})
            .catch(err=>console.warn("CloudEMS toggle learn:",err));
        }
        return;
      }
      if(action === "toggle-auto"){
        if(!this._hass) return;
        const svc = btn.dataset.state === "on" ? "turn_off" : "turn_on";
        this._hass.callService("switch", svc, {entity_id: btn.dataset.switch})
          .catch(err=>console.warn("CloudEMS toggle auto:",err));
        return;
      }
      if(action === "up" || action === "dn"){
        const idx = parseInt(btn.dataset.idx);
        const s2 = shutters[idx];
        if(!s2||!this._hass) return;
        const cur = Math.round(parseFloat(s2.position ?? s2.current_position ?? 0));
        const np = action==="up" ? Math.min(100,cur+10) : Math.max(0,cur-10);
        this._hass.callService("cover","set_cover_position",{entity_id:s2.entity_id,position:np})
          .catch(err=>console.warn("CloudEMS shutter move:",err));
        return;
      }
      if(action === "all-up" || action === "all-dn"){
        if(!this._hass) return;
        const svc = action==="all-up" ? "open_cover" : "close_cover";
        shutters.forEach(s2 => {
          this._hass.callService("cover", svc, {entity_id:s2.entity_id})
            .catch(err=>console.warn("CloudEMS all move:",err));
        });
        return;
      }
    });
  }

  static getConfigElement(){ return document.createElement("cloudems-shutter-card-editor"); }
  static getStubConfig(){ return {type:"custom:cloudems-shutter-card",title:"Rolluiken"}; }
  getCardSize(){ return 5; }
}

class CloudemsShutterCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._cfg={}; }
  setConfig(c){ this._cfg={...c}; this._render(); }
  set hass(h){ this._hass=h; }
  _fire(){ this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg = this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;}
</style>
<div class="wrap">
  <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${esc(cfg.title??"Rolluiken")}"></div>
</div>`;
    this.shadowRoot.querySelector("input[name=title]")?.addEventListener("change",e=>{
      this._cfg={...this._cfg,title:e.target.value}; this._fire();
    });
  }
}

customElements.define("cloudems-shutter-card-editor", CloudemsShutterCardEditor);
customElements.define("cloudems-shutter-card", CloudemsShutterCard);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-shutter-card",name:"CloudEMS Shutter Card",description:"Rolluiken overzicht, detail & leervoortgang",preview:true});
console.info(`%c CLOUDEMS-SHUTTER-CARD %c v${SHUTTER_VERSION} `,"background:#1D9E75;color:#fff;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0e1520;color:#1D9E75;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
