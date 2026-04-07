// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Lamp Card  v5.4.96

const LAMP_VERSION = '5.5.318';

const LAMP_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host { display:block; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  .card{ background:#0e1520; border-radius:16px; border:1px solid rgba(255,255,255,0.06); overflow:hidden; font-family:'Syne',sans-serif; }
  .hdr{ display:flex; align-items:center; gap:10px; padding:14px 18px 12px; border-bottom:1px solid rgba(255,255,255,0.06); position:relative; overflow:hidden; }
  .hdr::before{ content:''; position:absolute; inset:0; background:linear-gradient(135deg,rgba(255,214,0,0.05) 0%,transparent 60%); pointer-events:none; }
  .hdr-icon{ font-size:20px; flex-shrink:0; }
  .hdr-texts{ flex:1; min-width:0; }
  .hdr-title{ font-size:13px; font-weight:700; color:#f1f5f9; letter-spacing:.04em; text-transform:uppercase; }
  .hdr-sub{ font-size:11px; color:#6b7280; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .toggle-pill{ display:flex; align-items:center; gap:6px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:20px; padding:4px 10px; cursor:pointer; flex-shrink:0; }
  .toggle-dot{ width:10px; height:10px; border-radius:50%; transition:background .2s; }
  .toggle-dot.on{ background:#4ade80; box-shadow:0 0 6px rgba(74,222,128,0.5); }
  .toggle-dot.off{ background:#4b5563; }
  .toggle-lbl{ font-size:11px; font-weight:700; letter-spacing:.04em; }
  .toggle-lbl.on{ color:#4ade80; }
  .toggle-lbl.off{ color:#4b5563; }
  .mod-off{ padding:10px 18px; background:rgba(251,146,60,0.08); border-bottom:1px solid rgba(251,146,60,0.2); font-size:11px; font-weight:600; color:#fb923c; }
  .stat-grid{ display:grid; grid-template-columns:repeat(4,1fr); border-bottom:1px solid rgba(255,255,255,0.06); }
  .stat-tile{ padding:10px 6px; display:flex; flex-direction:column; align-items:center; gap:3px; border-right:1px solid rgba(255,255,255,0.06); }
  .stat-tile:last-child{ border-right:none; }
  .stat-lbl{ font-size:8px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#374151; text-align:center; }
  .stat-val{ font-size:14px; font-weight:800; font-family:'JetBrains Mono',monospace; }
  .c-green{ color:#4ade80; } .c-amber{ color:#fb923c; } .c-muted{ color:#4b5563; }
  .c-blue{ color:#7dd3fc; } .c-yellow{ color:#fde047; } .c-red{ color:#f87171; }
  .ctx-strip{ display:flex; gap:6px; padding:10px 18px 8px; flex-wrap:wrap; }
  .ctx-pill{ display:flex; align-items:center; gap:4px; padding:4px 10px; border-radius:12px; font-size:11px; font-weight:600; }
  .ctx-home{ background:rgba(74,222,128,0.10); color:#4ade80; border:1px solid rgba(74,222,128,0.2); }
  .ctx-away{ background:rgba(248,113,113,0.10); color:#f87171; border:1px solid rgba(248,113,113,0.2); }
  .ctx-night{ background:rgba(125,211,252,0.08); color:#7dd3fc; border:1px solid rgba(125,211,252,0.15); }
  .ctx-day{ background:rgba(253,224,71,0.08); color:#fde047; border:1px solid rgba(253,224,71,0.15); }
  .ctx-circ{ background:rgba(251,146,60,0.10); color:#fb923c; border:1px solid rgba(251,146,60,0.2); }
  .sec-hdr{ display:flex; align-items:center; justify-content:space-between; padding:10px 18px 6px; }
  .sec-title{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:.12em; color:#374151; }
  .sec-action{ font-size:10px; font-weight:700; color:#60a5fa; cursor:pointer; padding:3px 8px; border-radius:6px; background:rgba(96,165,250,0.08); border:1px solid rgba(96,165,250,0.2); }
  .lamp-list{ padding:0 18px; }
  .lamp-row{ display:flex; align-items:center; gap:8px; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
  .lamp-row:last-child{ border-bottom:none; }
  .lamp-state{ font-size:15px; flex-shrink:0; width:22px; text-align:center; cursor:pointer; }
  .lamp-info{ flex:1; min-width:0; }
  .lamp-name{ font-size:12px; font-weight:600; color:#e2e8f0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .lamp-name.on{ color:#fde047; }
  .lamp-meta{ font-size:10px; color:#4b5563; margin-top:1px; display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
  .lamp-outdoor{ font-size:9px; color:#34d399; }
  .lamp-presence{ font-size:9px; color:#7dd3fc; }
  .mode-btns{ display:flex; gap:3px; flex-shrink:0; }
  .mode-btn{ padding:3px 8px; border-radius:8px; font-size:9px; font-weight:700; letter-spacing:.04em; cursor:pointer; border:1px solid; transition:opacity .15s,transform .1s; text-transform:uppercase; }
  .mode-btn:active{ opacity:.6; transform:scale(.95); }
  .mode-btn.m-manual{ background:rgba(255,255,255,0.03); border-color:rgba(255,255,255,0.08); color:#4b5563; }
  .mode-btn.m-semi  { background:rgba(251,146,60,0.08);  border-color:rgba(251,146,60,0.2);  color:#6b7280; }
  .mode-btn.m-auto  { background:rgba(74,222,128,0.06);  border-color:rgba(74,222,128,0.15); color:#4b5563; }
  .mode-btn.active.m-manual{ background:rgba(255,255,255,0.08); border-color:rgba(255,255,255,0.2); color:#e2e8f0; }
  .mode-btn.active.m-semi  { background:rgba(251,146,60,0.18);  border-color:rgba(251,146,60,0.5);  color:#fb923c; }
  .mode-btn.active.m-auto  { background:rgba(74,222,128,0.18);  border-color:rgba(74,222,128,0.4);  color:#4ade80; }
  .no-lamps{ padding:24px 18px; text-align:center; }
  .no-lamps-icon{ font-size:32px; margin-bottom:10px; }
  .no-lamps-title{ font-size:13px; font-weight:700; color:#9ca3af; margin-bottom:6px; }
  .no-lamps-sub{ font-size:11px; color:#4b5563; line-height:1.6; }
  .scan-btn-big{ display:inline-block; margin-top:14px; padding:8px 20px; background:rgba(96,165,250,0.12); border:1px solid rgba(96,165,250,0.3); border-radius:10px; color:#60a5fa; font-size:12px; font-weight:700; cursor:pointer; }
  .circ-row{ display:flex; align-items:center; gap:8px; padding:10px 18px; background:rgba(251,146,60,0.04); border-top:1px solid rgba(255,255,255,0.05); }
  .circ-icon{ font-size:18px; flex-shrink:0; }
  .circ-info{ flex:1; }
  .circ-title{ font-size:12px; font-weight:700; color:#e2e8f0; }
  .circ-sub{ font-size:11px; color:#4b5563; margin-top:2px; }
  .circ-badge{ font-size:9px; font-weight:700; padding:3px 9px; border-radius:10px; text-transform:uppercase; letter-spacing:.05em; flex-shrink:0; }
  .circ-on { background:rgba(251,146,60,0.15); color:#fb923c; border:1px solid rgba(251,146,60,0.3); }
  .circ-off{ background:rgba(255,255,255,0.04); color:#4b5563; border:1px solid rgba(255,255,255,0.08); }
  .circ-btns{ display:flex; gap:6px; padding:8px 18px 12px; background:rgba(251,146,60,0.03); border-bottom:1px solid rgba(255,255,255,0.05); }
  .circ-btn{ flex:1; padding:6px 4px; border-radius:8px; font-size:10px; font-weight:700; cursor:pointer; border:1px solid; text-align:center; }
  .cb-on { background:rgba(251,146,60,0.10); border-color:rgba(251,146,60,0.25); color:#fb923c; }
  .cb-off{ background:rgba(255,255,255,0.04); border-color:rgba(255,255,255,0.1); color:#6b7280; }
  .cb-test{ background:rgba(167,139,250,0.10); border-color:rgba(167,139,250,0.25); color:#a78bfa; }
  .actions-list{ padding:0 18px 12px; }
  .action-row{ display:flex; align-items:flex-start; gap:8px; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
  .action-row:last-child{ border-bottom:none; }
  .action-icon{ font-size:12px; flex-shrink:0; margin-top:1px; }
  .action-text{ flex:1; font-size:11px; color:#6b7280; line-height:1.4; }
  .action-text b{ color:#9ca3af; }
  .action-time{ font-family:'JetBrains Mono',monospace; font-size:9px; color:#374151; flex-shrink:0; }
  .legend{ display:flex; gap:12px; padding:10px 18px 12px; border-top:1px solid rgba(255,255,255,0.05); flex-wrap:wrap; }
  .legend-item{ display:flex; align-items:center; gap:5px; font-size:10px; color:#4b5563; }
  .legend-dot{ width:7px; height:7px; border-radius:50%; flex-shrink:0; }
  .ld-manual{ background:#6b7280; } .ld-semi{ background:#fb923c; } .ld-auto{ background:#4ade80; }
`;

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const fmtAgo = ts => {
  if (!ts) return '';
  const s = Math.round(Date.now()/1000 - ts);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}m`;
  return `${Math.floor(s/3600)}u`;
};

class CloudEMSLampCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); this._prev=''; }
  setConfig(c){ this._cfg={title:'Slimme Verlichting',...c}; }

  set hass(h){
    this._hass=h;
    const la=h.states['sensor.cloudems_lamp_auto']?.attributes||{};
    const lc=h.states['sensor.cloudems_lampcirculatie_status']?.attributes||{};
    const sig=[la.enabled,la.lamp_count,la.auto_count,la.semi_count,
               (la.lamps||[]).map(l=>l.mode).join(','),
               (la.last_actions||[]).length,lc.mode,lc.enabled,
               h.states['switch.cloudems_module_lampcirculatie']?.state,
               h.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state,
              ].join('|');
    if(sig!==this._prev){this._prev=sig;this._render();}
  }

  _svc(domain,service,data={}){ this._hass?.callService(domain,service,data); }

  _render(){
    const sh=this.shadowRoot; if(!sh) return;
    const h=this._hass, c=this._cfg||{};
    if(!h){sh.innerHTML=`<style>${LAMP_CSS}</style><div class="card"><div class="no-lamps"><div class="no-lamps-icon">💡</div></div></div>`;return;}

    const la      = h.states['sensor.cloudems_lamp_auto']?.attributes||{};
    const lamps   = la.lamps||[];
    const laOn    = !!la.enabled;
    const autoC   = la.auto_count||0;
    const semiC   = la.semi_count||0;
    const manC    = la.manual_count||0;
    const acts    = la.last_actions||[];

    const lc      = h.states['sensor.cloudems_lampcirculatie_status']?.attributes||{};
    const circOn  = h.states['switch.cloudems_module_lampcirculatie']?.state==='on';
    const circAct = lc.mode==='circulation';
    const lampsOnIds = lc.lamps_on||[];
    const lampsOnLbl = lc.lamps_on_labels||[];

    const home  = h.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state==='on';
    const night = !!(lc.sun_derived_night);

    const sub = !lamps.length
      ? 'Druk op Scan om lampen te ontdekken'
      : `${autoC} automatisch · ${semiC} semi · ${manC} handmatig`;

    const ctxHtml = `<div class="ctx-strip">
      ${home?'<div class="ctx-pill ctx-home">🏠 Thuis</div>':'<div class="ctx-pill ctx-away">🚗 Afwezig</div>'}
      ${night?'<div class="ctx-pill ctx-night">🌙 Nacht</div>':'<div class="ctx-pill ctx-day">☀️ Dag</div>'}
      ${circAct?'<div class="ctx-pill ctx-circ">🔒 Beveiliging actief</div>':''}
    </div>`;

    const statHtml = `<div class="stat-grid">
      <div class="stat-tile"><span class="stat-lbl">Automatisch</span><span class="stat-val c-green">${autoC}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Semi-auto</span><span class="stat-val c-amber">${semiC}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Handmatig</span><span class="stat-val c-muted">${manC}</span></div>
      <div class="stat-tile"><span class="stat-lbl">Nu aan</span><span class="stat-val c-yellow">${lampsOnIds.length}</span></div>
    </div>`;

    let lampsHtml;
    if(!lamps.length){
      lampsHtml=`<div class="no-lamps">
        <div class="no-lamps-icon">🔍</div>
        <div class="no-lamps-title">Nog geen lampen geconfigureerd</div>
        <div class="no-lamps-sub">CloudEMS scant alle <b>light.*</b> entiteiten en koppelt ze aan de juiste ruimte.<br>
        Slaapkamer → Handmatig &nbsp;·&nbsp; Woonkamer → Semi &nbsp;·&nbsp; Hal/Buiten → Automatisch</div>
        <div class="scan-btn-big" data-action="scan">🔍 Scan lampen</div>
      </div>`;
    } else {
      const rows=lamps.map(l=>{
        const lampOn=h.states[l.entity_id]?.state==='on';
        return`<div class="lamp-row">
          <span class="lamp-state" data-toggle="${esc(l.entity_id)}">${lampOn?'💡':'○'}</span>
          <div class="lamp-info">
            <div class="lamp-name${lampOn?' on':''}">${esc(l.label)}</div>
            <div class="lamp-meta">
              ${l.area?`📍 ${esc(l.area)}`:''}
              ${l.outdoor?'<span class="lamp-outdoor">🌿 buiten</span>':''}
              ${l.has_presence?'<span class="lamp-presence">📡 aanwezigheid</span>':''}
            </div>
          </div>
          <div class="mode-btns">
            <div class="mode-btn m-manual${l.mode==='manual'?' active':''}" data-setmode="${esc(l.entity_id)}" data-mode="manual" title="Handmatig — leert alleen">H</div>
            <div class="mode-btn m-semi${l.mode==='semi'?' active':''}"   data-setmode="${esc(l.entity_id)}" data-mode="semi"   title="Semi — vraagt bevestiging">S</div>
            <div class="mode-btn m-auto${l.mode==='auto'?' active':''}"   data-setmode="${esc(l.entity_id)}" data-mode="auto"   title="Auto — direct automatisch">A</div>
          </div>
        </div>`;
      }).join('');
      lampsHtml=`
        <div class="sec-hdr">
          <span class="sec-title">💡 Lampen (${lamps.length})</span>
          <span class="sec-action" data-action="scan">🔍 Opnieuw scannen</span>
        </div>
        <div class="lamp-list">${rows}</div>`;
    }

    const circSub=circAct
      ?`Actief · ${lampsOnLbl.length?lampsOnLbl.join(', '):'lampen wisselen'}`
      :circOn?(home?'Standby — wacht op afwezigheid':'Standby'):'Module uitgeschakeld';

    const circHtml=`
      <div class="circ-row">
        <span class="circ-icon">🔒</span>
        <div class="circ-info">
          <div class="circ-title">Inbraakbeveiliging</div>
          <div class="circ-sub">${esc(circSub)}</div>
        </div>
        <span class="circ-badge ${circAct?'circ-on':'circ-off'}">${circAct?'ACTIEF':circOn?'STANDBY':'UIT'}</span>
      </div>
      <div class="circ-btns">
        <div class="circ-btn cb-on"  data-action="circ_on">✅ Inschakelen</div>
        <div class="circ-btn cb-off" data-action="circ_off">❌ Uitschakelen</div>
        <div class="circ-btn cb-test" data-action="circ_test">🔬 Test</div>
      </div>`;

    const actHtml=acts.length?`
      <div class="sec-hdr" style="padding-top:12px">
        <span class="sec-title">⏱ Recente acties</span>
      </div>
      <div class="actions-list">${acts.slice().reverse().slice(0,6).map(a=>{
        const icon=a.action==='on'?'💡':a.action==='off'?'⬛':a.action==='confirm_request'?'🔔':'ℹ️';
        return`<div class="action-row">
          <span class="action-icon">${icon}</span>
          <span class="action-text"><b>${esc(a.label)}</b> — ${esc(a.reason)}</span>
          <span class="action-time">${fmtAgo(a.ts)}</span>
        </div>`;
      }).join('')}</div>`:'';

    sh.innerHTML=`<style>${LAMP_CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">💡</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub">${esc(sub)}</div>
        </div>
        <div class="toggle-pill" data-action="toggle_auto">
          <div class="toggle-dot ${laOn?'on':'off'}"></div>
          <span class="toggle-lbl ${laOn?'on':'off'}">${laOn?'AAN':'UIT'}</span>
        </div>
      </div>
      ${!laOn&&lamps.length?'<div class="mod-off">⚠️ Slimme verlichting staat uit — zet AAN om te activeren.</div>':''}
      ${ctxHtml}
      ${statHtml}
      ${lampsHtml}
      ${circHtml}
      ${actHtml}
      <div class="legend">
        <div class="legend-item"><div class="legend-dot ld-manual"></div>H — leert, doet niets</div>
        <div class="legend-item"><div class="legend-dot ld-semi"></div>S — vraagt bevestiging</div>
        <div class="legend-item"><div class="legend-dot ld-auto"></div>A — direct automatisch</div>
      </div>
    </div>`;

    sh.querySelectorAll('[data-action]').forEach(el=>{
      el.addEventListener('click',()=>{
        const a=el.dataset.action;
        if(a==='toggle_auto') this._svc('cloudems','lamp_set_mode',{enabled:!laOn});
        else if(a==='scan')   this._svc('cloudems','lamp_scan',{});
        else if(a==='circ_on')   this._svc('cloudems','lamp_circulation_set_enabled',{enabled:true});
        else if(a==='circ_off')  this._svc('cloudems','lamp_circulation_set_enabled',{enabled:false});
        else if(a==='circ_test') this._svc('cloudems','lamp_circulation_test',{});
      });
    });
    sh.querySelectorAll('[data-toggle]').forEach(el=>{
      el.addEventListener('click',()=>{
        const eid=el.dataset.toggle;
        const on=this._hass?.states[eid]?.state==='on';
        this._svc('light',on?'turn_off':'turn_on',{entity_id:eid});
      });
    });
    sh.querySelectorAll('[data-setmode]').forEach(el=>{
      el.addEventListener('click',()=>{
        this._svc('cloudems','lamp_set_mode',{entity_id:el.dataset.setmode,mode:el.dataset.mode});
        this._prev='';
      });
    });
  }

  getCardSize(){ return 7; }
  static getConfigElement(){ return document.createElement('cloudems-lamp-card-editor'); }
  static getStubConfig(){ return {title:'Slimme Verlichting'}; }
}

class CloudEMSLampCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" value="${esc(cfg.title||'Slimme Verlichting')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change',e=>{this._cfg={...this._cfg,title:e.target.value};this._fire();});
  }
}

if (!customElements.get('cloudems-lamp-card')) customElements.define('cloudems-lamp-card',CloudEMSLampCard);
if (!customElements.get('cloudems-lamp-card-editor')) customElements.define('cloudems-lamp-card-editor',CloudEMSLampCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-lamp-card',name:'CloudEMS Lamp Card',description:'Slimme Verlichting — automatisering, beveiliging en bediening'});
console.info('%c CLOUDEMS-LAMP-CARD %c v'+LAMP_VERSION+' ','background:#fde047;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#fde047;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
