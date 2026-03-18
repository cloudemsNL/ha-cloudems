// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Lamp Card  v1.0.0

const LAMP_VERSION = '2.0.0';

const LAMP_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host { display:block; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  .card{ background:#0e1520; border-radius:16px; border:1px solid rgba(255,255,255,0.06); overflow:hidden; font-family:'Syne',sans-serif; }
  .card:hover{ border-color:rgba(255,214,0,0.12); box-shadow:0 8px 40px rgba(0,0,0,0.7); }

  /* ── Header ── */
  .hdr{ display:flex; align-items:center; gap:10px; padding:14px 18px 12px; border-bottom:1px solid rgba(255,255,255,0.06); position:relative; overflow:hidden; }
  .hdr::before{ content:''; position:absolute; inset:0; background:linear-gradient(135deg,rgba(255,214,0,0.06) 0%,transparent 60%); pointer-events:none; }
  .hdr-icon{ font-size:18px; flex-shrink:0; }
  .hdr-texts{ flex:1; }
  .hdr-title{ font-size:13px; font-weight:700; color:#f1f5f9; letter-spacing:.04em; text-transform:uppercase; }
  .hdr-sub{ font-size:11px; color:#6b7280; margin-top:2px; }
  .hdr-badge{ font-family:'JetBrains Mono',monospace; font-size:9px; padding:3px 8px; border-radius:10px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; }
  .badge-on  { background:rgba(74,222,128,0.12); color:#4ade80; border:1px solid rgba(74,222,128,0.25); }
  .badge-off { background:rgba(248,113,113,0.12); color:#f87171; border:1px solid rgba(248,113,113,0.25); }
  .badge-test{ background:rgba(167,139,250,0.15); color:#a78bfa; border:1px solid rgba(167,139,250,0.3); }
  .badge-circ{ background:rgba(251,146,60,0.12); color:#fb923c; border:1px solid rgba(251,146,60,0.25); }
  .badge-night{ background:rgba(125,211,252,0.10); color:#7dd3fc; border:1px solid rgba(125,211,252,0.2); }
  .badge-saving{ background:rgba(253,224,71,0.12); color:#fde047; border:1px solid rgba(253,224,71,0.25); }

  /* ── Module uit banner ── */
  .mod-off{ padding:10px 18px; background:rgba(251,146,60,0.08); border-bottom:1px solid rgba(251,146,60,0.2); font-size:11px; font-weight:600; color:#fb923c; }

  /* ── Status strip ── */
  .status-strip{ display:grid; grid-template-columns:repeat(5,1fr); border-bottom:1px solid rgba(255,255,255,0.06); }
  .stat-box{ padding:10px 8px; display:flex; flex-direction:column; gap:2px; align-items:center; text-align:center; border-right:1px solid rgba(255,255,255,0.06); }
  .stat-box:last-child{ border-right:none; }
  .stat-lbl{ font-size:8px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#374151; }
  .stat-val{ font-size:11px; font-weight:700; font-family:'JetBrains Mono',monospace; }
  .c-green{ color:#4ade80; } .c-red{ color:#f87171; } .c-amber{ color:#fb923c; }
  .c-blue{ color:#7dd3fc; } .c-purple{ color:#a78bfa; } .c-muted{ color:#4b5563; }
  .c-yellow{ color:#fde047; }

  /* ── Active lamp banner ── */
  .lamp-banner{ padding:12px 18px; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .lamp-active-names{ font-size:13px; font-weight:600; color:#f1f5f9; }
  .lamp-timer{ font-family:'JetBrains Mono',monospace; font-size:11px; color:#6b7280; flex-shrink:0; }

  /* ── Buttons ── */
  .btn-row{ display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:8px; padding:12px 18px; border-bottom:1px solid rgba(255,255,255,0.06); }
  .btn{ padding:8px 4px; border-radius:10px; font-family:'Syne',sans-serif; font-size:11px; font-weight:700; cursor:pointer; border:1px solid; transition:opacity .15s,transform .1s; text-align:center; letter-spacing:.02em; }
  .btn:active{ opacity:.6; transform:scale(.97); }
  .btn-enable { background:rgba(74,222,128,0.12); border-color:rgba(74,222,128,0.3); color:#4ade80; }
  .btn-disable{ background:rgba(248,113,113,0.10); border-color:rgba(248,113,113,0.25); color:#f87171; }
  .btn-test   { background:rgba(167,139,250,0.12); border-color:rgba(167,139,250,0.3); color:#a78bfa; }
  .btn-stop   { background:rgba(251,146,60,0.10); border-color:rgba(251,146,60,0.25); color:#fb923c; }

  /* ── Lamp table ── */
  .lamp-section{ padding:10px 18px 4px; }
  .sec-title{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:.12em; color:#374151; margin-bottom:6px; }
  .lamp-table{ width:100%; border-collapse:collapse; }
  .lamp-table th{ font-size:8px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#374151; padding:4px 6px; border-bottom:1px solid rgba(255,255,255,0.06); text-align:left; }
  .lamp-table td{ font-size:11px; color:#9ca3af; padding:5px 6px; border-bottom:1px solid rgba(255,255,255,0.04); font-family:'JetBrains Mono',monospace; }
  .lamp-table tr:last-child td{ border-bottom:none; }
  .lamp-table td.name{ font-family:'Syne',sans-serif; font-size:12px; font-weight:600; color:#e2e8f0; }
  .lamp-table td.name.excluded{ color:#4b5563; text-decoration:line-through; }
  .lamp-table td.name.on{ color:#fde047; }
  .mimicry-bar{ display:inline-block; width:40px; height:4px; background:rgba(255,255,255,0.07); border-radius:2px; vertical-align:middle; margin-right:4px; overflow:hidden; }
  .mimicry-fill{ height:100%; border-radius:2px; background:linear-gradient(90deg,#a78bfa,#818cf8); }

  /* ── Uitleg sectie ── */
  .info-section{ padding:12px 18px 14px; border-top:1px solid rgba(255,255,255,0.06); }
  .info-row{ display:flex; gap:8px; margin-bottom:7px; font-size:11px; line-height:1.5; }
  .info-row:last-child{ margin-bottom:0; }
  .info-icon{ flex-shrink:0; font-size:13px; margin-top:1px; }
  .info-text{ color:#6b7280; }
  .info-text b{ color:#9ca3af; }

  /* ── Advice ── */
  .advice-strip{ padding:8px 18px; background:rgba(253,224,71,0.04); border-bottom:1px solid rgba(255,255,255,0.04); font-size:11px; color:#9ca3af; font-style:italic; }

  /* ── Empty ── */
  .empty{ padding:24px 18px; text-align:center; color:#374151; font-size:12px; }

  /* ── Tabs ── */
  .tabs{ display:flex; border-bottom:1px solid rgba(255,255,255,0.06); }
  .tab{ flex:1; padding:9px 4px; font-size:11px; font-weight:700; text-align:center; cursor:pointer; color:#4b5563; letter-spacing:.04em; border-bottom:2px solid transparent; transition:color .15s,border-color .15s; }
  .tab.active{ color:#fde047; border-bottom-color:#fde047; }
  .tab-body{ display:none; }
  .tab-body.active{ display:block; }

  /* ── Auto tab ── */
  .auto-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; padding:10px 18px; border-bottom:1px solid rgba(255,255,255,0.06); }
  .auto-stat{ background:rgba(255,255,255,0.03); border-radius:8px; padding:8px 6px; text-align:center; }
  .auto-stat-lbl{ font-size:8px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#374151; }
  .auto-stat-val{ font-size:13px; font-weight:700; margin-top:3px; }
  .lamp-auto-row{ display:flex; align-items:center; gap:8px; padding:7px 18px; border-bottom:1px solid rgba(255,255,255,0.04); }
  .lamp-auto-row:last-child{ border-bottom:none; }
  .lamp-auto-icon{ font-size:14px; flex-shrink:0; width:20px; text-align:center; }
  .lamp-auto-name{ flex:1; font-size:12px; font-weight:600; color:#e2e8f0; }
  .lamp-auto-area{ font-size:10px; color:#4b5563; margin-top:1px; }
  .mode-badge{ font-size:9px; font-weight:700; padding:2px 7px; border-radius:8px; text-transform:uppercase; letter-spacing:.05em; flex-shrink:0; }
  .mode-auto  { background:rgba(74,222,128,0.12); color:#4ade80; border:1px solid rgba(74,222,128,0.2); }
  .mode-semi  { background:rgba(251,146,60,0.12); color:#fb923c; border:1px solid rgba(251,146,60,0.2); }
  .mode-manual{ background:rgba(255,255,255,0.05); color:#4b5563; border:1px solid rgba(255,255,255,0.08); }
  .auto-action-row{ padding:8px 18px; background:rgba(74,222,128,0.04); border-bottom:1px solid rgba(74,222,128,0.08); font-size:11px; color:#4ade80; display:flex; gap:8px; align-items:flex-start; }
  .action-icon{ flex-shrink:0; }
  .action-text{ flex:1; line-height:1.5; }
  .action-time{ font-family:'JetBrains Mono',monospace; font-size:10px; color:#374151; flex-shrink:0; }

  @keyframes pulse{ 0%,100%{opacity:1} 50%{opacity:.5} }
  .pulse{ animation:pulse 2s infinite; }
`;

const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const fmtTimer = s => s > 0 ? `${Math.floor(s/60)}m ${s%60}s` : '—';

class CloudEMSLampCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); this._prev=''; this._tab='circ'; }

  setConfig(c){ this._cfg = { title: c.title||'Lampcirculatie', ...c }; }

  set hass(h){
    this._hass = h;
    const st = h.states['sensor.cloudems_lampcirculatie_status'];
    const sw = h.states['switch.cloudems_module_lampcirculatie'];
    const a  = st?.attributes || {};
    const la  = h.states['sensor.cloudems_lampcirculatie_status']?.attributes?.automation || {};
    const sig = [st?.state, a.mode, a.enabled, a.test_mode, (a.lamps_on_labels||[]).join(','), a.next_switch_in_s, sw?.state, la.enabled, (la.lamps||[]).length].join('|');
    if(sig !== this._prev){ this._prev = sig; this._render(); }
  }

  _render(){
    const sh = this.shadowRoot; if(!sh) return;
    const h = this._hass, c = this._cfg || {};
    if(!h){ sh.innerHTML=`<style>${LAMP_CSS}</style><div class="card"><div class="empty">💡</div></div>`; return; }

    const st  = h.states['sensor.cloudems_lampcirculatie_status'];
    const sw  = h.states['switch.cloudems_module_lampcirculatie'];
    const modOn = sw?.state === 'on';
    const a   = st?.attributes || {};

    const mode       = a.mode || 'standby';
    const testMode   = !!a.test_mode;
    const enabled    = !!a.enabled;
    const negPrice   = !!a.neg_price_active;
    const mimicry    = !!a.mimicry_active;
    const sunNight   = !!a.sun_derived_night;
    const lampsOn    = a.lamps_on_labels || [];
    const lampsOnIds = a.lamps_on || [];
    const nextSwitch = a.next_switch_in_s || 0;
    const registered = a.lamps_registered || 0;
    const excluded   = a.lamps_excluded || 0;
    const withPhase  = a.lamps_with_phase || 0;
    const occConf    = a.occupancy_confidence;
    const advice     = a.advice || '';
    const phaseTip   = a.phase_tip || '';
    const lampPhases = a.lamp_phases || [];

    // ── Header badge ─────────────────────────────────────────────────────
    let badgeCls = 'badge-off', badgeLabel = 'UIT';
    if(testMode){ badgeCls='badge-test'; badgeLabel='🔬 TEST'; }
    else if(!enabled){ badgeCls='badge-off'; badgeLabel='UITGESCHAKELD'; }
    else if(mode==='circulation'){ badgeCls='badge-circ'; badgeLabel='🔒 BEVEILIGT'; }
    else if(mode==='night_off'){ badgeCls='badge-night'; badgeLabel='🌙 NACHT'; }
    else if(mode==='energy_saving'){ badgeCls='badge-saving'; badgeLabel='⚡ BESPARING'; }
    else{ badgeCls='badge-on'; badgeLabel='STANDBY'; }

    const sub = testMode ? 'Testmodus actief — lampen wisselen snel'
      : mode==='circulation' ? (negPrice ? '⚡ Negatieve prijs — verlengde circulatie' : 'Inbraakbeveiliging actief')
      : mode==='night_off' ? (sunNight ? 'Zon onder horizon' : 'Nachtmodus')
      : mode==='energy_saving' ? 'Afwezig — alle lampen worden uitgedaan'
      : enabled ? (advice||'Niemand weg — wacht op activatie') : 'Klik Inschakelen om te starten';

    // ── Status strip ─────────────────────────────────────────────────────
    const strip = [
      { lbl:'Aanwezig',  val: h.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state==='on' ? '🏠 Thuis' : '🚗 Weg', cls: h.states['binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom']?.state==='on' ? 'c-green':'c-red' },
      { lbl:'Zon',       val: sunNight ? '🌙 Nacht' : '☀️ Dag',         cls: sunNight ? 'c-blue':'c-yellow' },
      { lbl:'Neg. prijs',val: negPrice ? '⚡ Actief' : '—',               cls: negPrice ? 'c-green':'c-muted' },
      { lbl:'Mimicry',   val: mimicry  ? '✨ Actief' : '—',               cls: mimicry  ? 'c-purple':'c-muted' },
      { lbl:'Zekerheid', val: occConf!=null ? Math.round(occConf*100)+'%' : '—', cls: occConf>0.7?'c-red':occConf>0.4?'c-amber':'c-muted' },
    ].map(s => `<div class="stat-box"><span class="stat-lbl">${s.lbl}</span><span class="stat-val ${s.cls}">${s.val}</span></div>`).join('');

    // ── Active lamps banner ────────────────────────────────────────────
    const lampBanner = `<div class="lamp-banner">
      <span class="lamp-active-names">${lampsOn.length>0 ? '💡 '+esc(lampsOn.join(', ')) : '💡 Geen lamp actief'}</span>
      ${nextSwitch>0 ? `<span class="lamp-timer">⏱ wissel over ${fmtTimer(nextSwitch)}</span>` : ''}
    </div>`;

    // ── Lamp table ─────────────────────────────────────────────────────
    let tableHtml = '';
    if(lampPhases.length > 0){
      const rows = lampPhases.map(l => {
        const isOn = lampsOnIds.includes(l.entity_id);
        const nameCls = l.excluded ? 'name excluded' : isOn ? 'name on' : 'name';
        const mp = Math.round((l.mimicry||0)*100);
        const barW = Math.min(100, mp);
        return `<tr>
          <td class="${nameCls}">${isOn?'💡 ':''}${esc(l.label||l.entity_id)}</td>
          <td>${l.excluded ? '<span style="color:#4b5563">uitgesloten</span>' : isOn ? '<span style="color:#fde047">AAN</span>' : '<span style="color:#374151">uit</span>'}</td>
          <td>${l.phase||'?'}</td>
          <td>${l.power_w ? Math.round(l.power_w)+'W' : '—'}</td>
          <td><div class="mimicry-bar"><div class="mimicry-fill" style="width:${barW}%"></div></div>${mp}%</td>
        </tr>`;
      }).join('');
      tableHtml = `<div class="lamp-section">
        <div class="sec-title">💡 Lampen (${registered} gevonden · ${excluded} uitgesloten · ${withPhase} fase bekend)</div>
        <table class="lamp-table">
          <thead><tr><th>Lamp</th><th>Status</th><th>Fase</th><th>Watt</th><th>Mimicry</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    } else {
      tableHtml = `<div class="lamp-section"><div class="empty">Geen lampen gevonden. CloudEMS detecteert automatisch alle light.* entiteiten na herstart.</div></div>`;
    }

    // ── Advice / phase tip ────────────────────────────────────────────
    const adviceHtml = (advice||phaseTip) ? `<div class="advice-strip">${esc(phaseTip||advice)}</div>` : '';

    // ── Info sectie ──────────────────────────────────────────────────
    const info = [
      ['🔒', '<b>Inbraakbeveiliging</b> — Dynamische circulatie met willekeurige tijden (2-8 min) en wisselend 1-3 lampen. Geen herhaalbaar patroon.'],
      ['⚡', '<b>Energiebesparing</b> — Alle lampen automatisch uit bij gedetecteerde afwezigheid.'],
      ['🌙', '<b>Seizoensintelligentie</b> — Nacht bepaald op basis van zon onder de horizon.'],
      ['✨', '<b>Gedragsmimicry</b> — CloudEMS leert welke lampen bewoners normaal aandoen. Hogere mimicry-score = hogere kans om gekozen te worden.'],
      ['🏘️', '<b>Buurt-correlatie</b> — Als buur-lampen worden gedetecteerd, verschuift CloudEMS het eigen schakelmoment.'],
      ['💶', '<b>Negatieve prijs</b> — Bij negatieve EPEX-prijs wordt de circulatieduur verlengd.'],
    ].map(([icon,text]) => `<div class="info-row"><span class="info-icon">${icon}</span><span class="info-text">${text}</span></div>`).join('');

    // ── Automation tab data ──────────────────────────────────────────────
    const laSt  = this._hass?.states['sensor.cloudems_lampcirculatie_status'];
    const laData = laSt?.attributes?.automation || {};
    const laLamps = laData.lamps || [];
    const autoCount  = laData.auto_count  || 0;
    const semiCount  = laData.semi_count  || 0;
    const laEnabled  = !!laData.enabled;
    const lastActions = laData.last_actions || [];

    // Auto-stat blokken
    const autoStats = `
      <div class="auto-stat"><div class="auto-stat-lbl">Automatisch</div><div class="auto-stat-val c-green">${autoCount}</div></div>
      <div class="auto-stat"><div class="auto-stat-lbl">Semi-auto</div><div class="auto-stat-val c-amber">${semiCount}</div></div>
      <div class="auto-stat"><div class="auto-stat-lbl">Totaal</div><div class="auto-stat-val c-blue">${laLamps.length}</div></div>
    `;

    // Lamp rijen
    const modeIcon = m => m==='auto'?'🤖':m==='semi'?'🔔':'👤';
    const modeCls  = m => `mode-badge mode-${m}`;
    const modeLbl  = m => m==='auto'?'AUTO':m==='semi'?'SEMI':'HANDMATIG';
    const lampRows = laLamps.length > 0
      ? laLamps.map(l => `
        <div class="lamp-auto-row">
          <span class="lamp-auto-icon">${modeIcon(l.mode)}</span>
          <div class="flex-col" style="flex:1">
            <div class="lamp-auto-name">${esc(l.label)}</div>
            ${l.area?`<div class="lamp-auto-area">📍 ${esc(l.area)}</div>`:''}
          </div>
          ${l.has_presence?'<span style="font-size:10px;color:#7dd3fc" title="Presence sensor gekoppeld">📡</span>':''}
          <span class="${modeCls(l.mode)}">${modeLbl(l.mode)}</span>
        </div>`).join('')
      : `<div class="empty">Nog geen lampen geconfigureerd.<br>Ga naar Instellingen → Slimme Verlichting.</div>`;

    // Laatste acties
    const actionsHtml = lastActions.length > 0
      ? lastActions.slice(-3).reverse().map(a => {
          const ago = a.ts ? Math.round((Date.now()/1000 - a.ts)/60) : 0;
          const icon = a.action==='on'?'💡':a.action==='off'?'⬛':a.action==='confirm_request'?'🔔':'ℹ️';
          return `<div class="auto-action-row">
            <span class="action-icon">${icon}</span>
            <span class="action-text"><b>${esc(a.label)}</b> — ${esc(a.reason)}</span>
            <span class="action-time">${ago}m</span>
          </div>`;
        }).join('')
      : '';

    const autoTabBody = `
      <div class="auto-grid">${autoStats}</div>
      ${actionsHtml}
      <div style="padding:6px 18px 2px"><div class="sec-title">Lampen</div></div>
      ${lampRows}
      <div style="padding:10px 18px 14px;font-size:11px;color:#4b5563;line-height:1.6">
        💡 <b>Handmatig</b> — CloudEMS leert, doet niets &nbsp;·&nbsp;
        🔔 <b>Semi</b> — vraagt bevestiging via notificatie &nbsp;·&nbsp;
        🤖 <b>Auto</b> — direct op basis van geleerd patroon
      </div>
    `;

    const tab = this._tab || 'circ';

    sh.innerHTML = `<style>${LAMP_CSS}</style>
    <div class="card">
      ${!modOn ? `<div class="mod-off">⚠️ Lampcirculatie module staat uit — schakel in via Configuratie.</div>` : ''}
      <div class="hdr">
        <span class="hdr-icon">💡</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title)}</div>
          <div class="hdr-sub">${tab==='circ' ? esc(sub) : (laEnabled ? `${autoCount} auto · ${semiCount} semi` : 'Slimme verlichting — niet ingeschakeld')}</div>
        </div>
        <span class="hdr-badge ${tab==='circ'?badgeCls:'badge-on'}${testMode&&tab==='circ'?' pulse':''}">${tab==='circ'?badgeLabel:(laEnabled?'ACTIEF':'UIT')}</span>
      </div>
      <div class="tabs">
        <div class="tab${tab==='circ'?' active':''}" data-tab="circ">🔒 Beveiliging</div>
        <div class="tab${tab==='auto'?' active':''}" data-tab="auto">🏠 Slim Aan/Uit</div>
      </div>
      <div class="tab-body${tab==='circ'?' active':''}">
        <div class="status-strip">${strip}</div>
        ${lampBanner}
        <div class="btn-row">
          <button class="btn btn-enable"  data-action="enable">✅ Inschakelen</button>
          <button class="btn btn-disable" data-action="disable">❌ Uitschakelen</button>
          <button class="btn btn-test"    data-action="test">🔬 Test</button>
          <button class="btn btn-stop"    data-action="stop_test">⏹ Stop</button>
        </div>
        ${adviceHtml}
        ${tableHtml}
        <div class="info-section">${info}</div>
      </div>
      <div class="tab-body${tab==='auto'?' active':''}">
        ${autoTabBody}
      </div>
    </div>`;

    sh.querySelectorAll('.btn[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        if(!this._hass) return;
        const act = btn.dataset.action;
        if(act==='enable')      this._hass.callService('cloudems','lamp_circulation_set_enabled',{enabled:true});
        if(act==='disable')     this._hass.callService('cloudems','lamp_circulation_set_enabled',{enabled:false});
        if(act==='test')        this._hass.callService('cloudems','lamp_circulation_test',{});
        if(act==='stop_test')   this._hass.callService('cloudems','lamp_circulation_stop_test',{});
      });
    });
    sh.querySelectorAll('.tab[data-tab]').forEach(t => {
      t.addEventListener('click', () => {
        this._tab = t.dataset.tab;
        this._prev = '';  // force re-render
        this._render();
      });
    });
  }

  getCardSize(){ return 8; }
  static getConfigElement(){ return document.createElement('cloudems-lamp-card-editor'); }
  static getStubConfig(){ return {title:'Lampcirculatie'}; }
}

class CloudEMSLampCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.row:last-child{border-bottom:none;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input[type=text]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px;}
</style>
<div class="wrap">
  <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${esc(cfg.title||'Lampcirculatie')}"></div>
</div>`;
    this.shadowRoot.querySelector('input').addEventListener('change', e => {
      this._cfg={...this._cfg, title:e.target.value}; this._fire();
    });
  }
}

customElements.define('cloudems-lamp-card', CloudEMSLampCard);
customElements.define('cloudems-lamp-card-editor', CloudEMSLampCardEditor);
window.customCards = window.customCards||[];
window.customCards.push({type:'cloudems-lamp-card', name:'CloudEMS Lamp Card', description:'Lampcirculatie status, bediening en uitleg', preview:true});
console.info('%c CLOUDEMS-LAMP-CARD %c v'+LAMP_VERSION+' ','background:#fde047;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#fde047;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
