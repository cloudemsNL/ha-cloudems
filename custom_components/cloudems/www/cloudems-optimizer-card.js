// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Battery Optimizer Card v5.5.465
// Toont het 48-uurs kostengeoptimaliseerde batterijplan

const OPT_VERSION = '5.5.465';
const OPT_SENSOR  = 'sensor.cloudems_battery_optimizer';

const STYLES_OPT = `
  :host{--bg:#0d1117;--surf:#161b22;--bord:rgba(255,255,255,.07);
    --text:#f0f6fc;--muted:#7d8590;--green:#3fb950;--red:#f85149;
    --blue:#58a6ff;--yellow:#d29922;--purple:#bc8cff;--orange:#f97316;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--bg);border-radius:12px;border:1px solid var(--bord);
    font-family:'Syne',system-ui,sans-serif;overflow:hidden;color:var(--text);}
  .hdr{display:flex;align-items:center;justify-content:space-between;
    padding:14px 16px 12px;border-bottom:1px solid var(--bord);
    background:rgba(88,166,255,.04);}
  .hdr-left{display:flex;align-items:center;gap:10px;}
  .hdr-icon{font-size:20px;}
  .hdr-title{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;}
  .hdr-sub{font-size:10px;color:var(--muted);margin-top:1px;}
  .summary{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;
    background:var(--bord);border-bottom:1px solid var(--bord);}
  .sum-item{background:var(--bg);padding:12px;text-align:center;}
  .sum-val{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums;}
  .sum-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;margin-top:2px;}
  .green{color:var(--green);} .red{color:var(--red);}
  .blue{color:var(--blue);} .yellow{color:var(--yellow);}
  .orange{color:var(--orange);}
  .plan-wrap{padding:12px 16px;}
  .plan-title{font-size:10px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.06em;margin-bottom:8px;}
  .timeline{position:relative;height:120px;background:var(--surf);
    border-radius:8px;overflow:hidden;border:1px solid var(--bord);}
  .tl-bars{display:flex;align-items:flex-end;height:100%;padding:4px 4px 0;gap:1px;}
  .tl-bar{flex:1;border-radius:2px 2px 0 0;min-height:2px;position:relative;
    transition:opacity .2s;}
  .tl-bar:hover{opacity:.8;}
  .tl-bar[data-action="charge_grid"]{background:var(--blue);}
  .tl-bar[data-action="charge_pv"]{background:var(--yellow);}
  .tl-bar[data-action="discharge"]{background:var(--orange);}
  .tl-bar[data-action="idle"]{background:rgba(255,255,255,.06);}
  .soc-line{position:absolute;bottom:0;left:0;right:0;height:2px;
    background:var(--green);opacity:.7;pointer-events:none;}
  .legend{display:flex;gap:12px;margin-top:8px;flex-wrap:wrap;}
  .leg-item{display:flex;align-items:center;gap:4px;font-size:10px;color:var(--muted);}
  .leg-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0;}
  .slots-list{margin-top:10px;}
  .slot-row{display:flex;align-items:center;gap:8px;padding:6px 0;
    border-bottom:1px solid rgba(255,255,255,.03);font-size:12px;}
  .slot-row:last-child{border-bottom:none;}
  .slot-time{width:42px;font-weight:700;font-variant-numeric:tabular-nums;
    color:var(--muted);flex-shrink:0;}
  .slot-badge{padding:2px 6px;border-radius:4px;font-size:10px;
    font-weight:700;flex-shrink:0;min-width:70px;text-align:center;}
  .badge-charge_grid{background:rgba(88,166,255,.15);color:var(--blue);}
  .badge-charge_pv{background:rgba(210,153,34,.15);color:var(--yellow);}
  .badge-discharge{background:rgba(249,115,22,.15);color:var(--orange);}
  .slot-soc{width:48px;text-align:right;color:var(--green);font-weight:600;
    flex-shrink:0;}
  .slot-price{width:48px;text-align:right;flex-shrink:0;font-size:11px;}
  .slot-reason{flex:1;color:var(--muted);font-size:10px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .empty{padding:24px;text-align:center;color:var(--muted);font-size:12px;}
  .now-line{position:absolute;top:0;bottom:0;width:2px;background:var(--red);
    opacity:.7;pointer-events:none;}
`;

class CloudEMSOptimizerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._cfg  = {};
  }

  
  static getConfigElement(){return document.createElement('cloudems-optimizer-card-editor');}
  set hass(h) {
    this._hass = h;
    this._render();
  }

  setConfig(c) { this._cfg = c || {}; }
  getCardSize() { return 6; }
  static getConfigElement(){return document.createElement('cloudems-optimizer-card-editor');}
  static getStubConfig() { return {}; }

  _render() {
    const sh = this.shadowRoot;
    const h  = this._hass;
    if (!h) return;

    const st   = h.states[OPT_SENSOR];
    const attr = st?.attributes || {};
    const slots = attr.plan_slots || [];
    const savings = attr.savings_vs_idle_eur;
    const totalCost = attr.total_cost_eur;
    const chgSlots = attr.charge_slots || 0;
    const disSlots = attr.discharge_slots || 0;

    if (!slots.length) {
      sh.innerHTML = `<style>${STYLES_OPT}</style>
        <div class="card">
          <div class="hdr"><div class="hdr-left">
            <span class="hdr-icon">🔋</span>
            <div><div class="hdr-title">Batterij Optimizer</div>
            <div class="hdr-sub">48-uurs kostenoptimalisatie</div></div>
          </div></div>
          <div class="empty">Nog geen plan berekend. Wacht op eerste slow-tick...</div>
        </div>`;
      return;
    }

    // Filter actieve slots voor weergave
    const activeSlots = slots.filter(s => s.action !== 'idle').slice(0, 12);

    // Timeline bars — alle 96 slots
    const maxPwr = 3.7; // kW
    const bars = slots.map((s, i) => {
      const pct = s.action === 'discharge'
        ? Math.min(100, (s.discharge_kwh / (maxPwr * 0.5)) * 100)
        : Math.min(100, (s.charge_kwh   / (maxPwr * 0.5)) * 100);
      const h = Math.max(4, pct);
      const now = new Date();
      const slotH = s.hour || 0;
      return `<div class="tl-bar" data-action="${s.action}"
        style="height:${h}%"
        title="${Math.floor(slotH)}:${slotH%1?'30':'00'} — ${s.action} SoC:${(s.soc_end||0).toFixed(0)}%">
      </div>`;
    }).join('');

    // SoC lijn als polyline
    const socPts = slots.map((s, i) => {
      const x = (i / slots.length) * 100;
      const y = 100 - ((s.soc_end || 50));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');

    // Huidige positie in timeline
    const now = new Date();
    const nowH = now.getHours() + now.getMinutes() / 60;
    // Eerste slot = current_hour, slots zijn 30 min elk
    const firstH = slots[0]?.hour || nowH;
    const nowPct = Math.min(100, Math.max(0, ((nowH - firstH) / 48) * 100));

    // Actieve slots lijst
    const slotRows = activeSlots.map(s => {
      const h = Math.floor(s.hour || 0);
      const m = ((s.hour || 0) % 1) ? '30' : '00';
      const price = s.epex != null ? `€${Number(s.epex).toFixed(3)}` : '';
      const badgeLbl = {
        charge_grid: '⚡ Net laden',
        charge_pv:   '☀️ PV laden',
        discharge:   '🔋 Ontladen',
      }[s.action] || s.action;
      return `<div class="slot-row">
        <span class="slot-time">${h.toString().padStart(2,'0')}:${m}</span>
        <span class="slot-badge badge-${s.action}">${badgeLbl}</span>
        <span class="slot-soc">${(s.soc_end||0).toFixed(0)}%</span>
        <span class="slot-price ${s.epex<0?'green':s.epex>0.25?'orange':''}">${price}</span>
        <span class="slot-reason">${(s.reason||'').slice(0,60)}</span>
      </div>`;
    }).join('');

    sh.innerHTML = `<style>${STYLES_OPT}</style>
    <div class="card">
      <div class="hdr">
        <div class="hdr-left">
          <span class="hdr-icon">🔋</span>
          <div>
            <div class="hdr-title">Batterij Optimizer</div>
            <div class="hdr-sub">48-uurs plan · v${OPT_VERSION}</div>
          </div>
        </div>
        <div style="font-size:10px;color:var(--muted);">${chgSlots} laden · ${disSlots} ontladen</div>
      </div>

      <div class="summary">
        <div class="sum-item">
          <div class="sum-val ${savings>0?'green':'red'}">
            ${savings!=null?(savings>0?'+':'')+Number(savings).toFixed(2)+'€':'—'}
          </div>
          <div class="sum-lbl">Besparing</div>
        </div>
        <div class="sum-item">
          <div class="sum-val blue">${totalCost!=null?Number(totalCost).toFixed(2)+'€':'—'}</div>
          <div class="sum-lbl">Kosten 48u</div>
        </div>
        <div class="sum-item">
          <div class="sum-val yellow">${chgSlots + disSlots}</div>
          <div class="sum-lbl">Acties</div>
        </div>
      </div>

      <div class="plan-wrap">
        <div class="plan-title">48-uurs plan timeline</div>
        <div class="timeline">
          <div class="tl-bars">${bars}</div>
          <svg style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none"
               viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline points="${socPts}" fill="none" stroke="#3fb950"
              stroke-width="0.8" opacity="0.6"/>
          </svg>
          <div class="now-line" style="left:${nowPct.toFixed(1)}%"></div>
        </div>
        <div class="legend">
          <div class="leg-item"><div class="leg-dot" style="background:#58a6ff"></div>Net laden</div>
          <div class="leg-item"><div class="leg-dot" style="background:#d29922"></div>PV laden</div>
          <div class="leg-item"><div class="leg-dot" style="background:#f97316"></div>Ontladen</div>
          <div class="leg-item"><div class="leg-dot" style="background:#3fb950"></div>SoC %</div>
        </div>

        <div class="slots-list">
          <div class="plan-title" style="margin-top:10px">Geplande acties</div>
          ${slotRows || '<div class="empty">Alle slots zijn idle — optimale situatie</div>'}
        </div>
      </div>
    </div>`;
  }
}




class CloudemsOptimizerCardEditor extends HTMLElement{
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  setConfig(c){this._cfg=c||{};this._render();}
  _render(){
    var self=this;var c=this._cfg;var sh=this.shadowRoot;sh.innerHTML='';
    var style=document.createElement('style');
    style.textContent=':host{display:block;padding:12px}';
    sh.appendChild(style);
    // Titel veld
    var rowT=document.createElement('div');rowT.style.marginBottom='10px';
    var lblT=document.createElement('label');lblT.textContent='Titel';lblT.style.cssText='display:block;font-size:12px;color:#aaa;margin-bottom:4px';
    var inpT=document.createElement('input');inpT.type='text';inpT.id='title';
    inpT.style.cssText='background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;box-sizing:border-box;width:100%';inpT.value=c.title||'';inpT.placeholder='(automatisch)';
    rowT.appendChild(lblT);rowT.appendChild(inpT);sh.appendChild(rowT);
    inpT.addEventListener('change',function(){
      var nc=Object.assign({},c);
      if(inpT.value)nc.title=inpT.value;else delete nc.title;
      self.dispatchEvent(new CustomEvent('config-changed',{detail:{config:nc},bubbles:true,composed:true}));
    });
    
  }
}
if(!customElements.get('cloudems-optimizer-card-editor'))customElements.define('cloudems-optimizer-card-editor',CloudemsOptimizerCardEditor);
if(!customElements.get('cloudems-optimizer-card-editor'))customElements.define('cloudems-optimizer-card-editor',CloudemsOptimizerCardEditor);

if (!customElements.get('cloudems-optimizer-card'))
  customElements.define('cloudems-optimizer-card', CloudEMSOptimizerCard);

class CloudEMSOptimizerCardEditor extends HTMLElement {
  setConfig(c) { this._cfg = c || {}; this._render(); }
  _render() {
    this.innerHTML = `<div style="padding:12px;font-size:13px;color:#aaa">
      Geen configuratie vereist. De kaart laadt automatisch van ${OPT_SENSOR}.
    </div>`;
  }
}
if (!customElements.get('cloudems-optimizer-card-editor'))
  customElements.define('cloudems-optimizer-card-editor', CloudEMSOptimizerCardEditor);
