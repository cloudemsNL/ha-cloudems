// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Energy Demand Card  v1.0.0

const DEMAND_CARD_VERSION = "5.3.56";

const S = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  :host{display:block;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:#111318;border:1px solid rgba(255,255,255,.07);border-radius:20px;overflow:hidden;font-family:'Syne',sans-serif;position:relative;}
  .card::before{content:'';position:absolute;inset:-60px;background:radial-gradient(ellipse 60% 40% at 20% 0%,rgba(99,102,241,.06) 0%,transparent 60%),radial-gradient(ellipse 50% 35% at 80% 100%,rgba(52,140,220,.05) 0%,transparent 60%);pointer-events:none;z-index:0;}
  .inner{position:relative;z-index:1;}
  .hdr{display:flex;align-items:center;gap:12px;padding:16px 20px 12px;border-bottom:1px solid rgba(255,255,255,.06);}
  .hdr-icon{width:38px;height:38px;background:linear-gradient(135deg,rgba(99,102,241,.25),rgba(139,92,246,.1));border:1px solid rgba(99,102,241,.3);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
  .hdr-title{font-size:15px;font-weight:700;color:#f0f0f0;letter-spacing:.02em;}
  .hdr-sub{font-size:11px;color:#5a6070;margin-top:1px;font-family:'JetBrains Mono',monospace;}
  .hdr-total{margin-left:auto;text-align:right;}
  .hdr-total-kwh{font-size:20px;font-weight:800;color:#a78bfa;font-family:'JetBrains Mono',monospace;line-height:1;}
  .hdr-total-eur{font-size:11px;color:#6b7280;margin-top:2px;}

  /* ── Battery adequacy strip ── */
  .bat-strip{margin:12px 20px 0;padding:10px 14px;border-radius:12px;display:flex;align-items:center;gap:10px;}
  .bat-ok{background:rgba(74,222,128,.08);border:1px solid rgba(74,222,128,.2);}
  .bat-warn{background:rgba(251,146,60,.08);border:1px solid rgba(251,146,60,.2);}
  .bat-danger{background:rgba(248,113,113,.10);border:1px solid rgba(248,113,113,.2);}
  .bat-icon{font-size:20px;flex-shrink:0;}
  .bat-body{flex:1;}
  .bat-label{font-size:12px;font-weight:700;color:#e2e8f0;}
  .bat-sub{font-size:11px;color:#6b7280;margin-top:1px;}
  .bat-kwh{font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace;flex-shrink:0;}

  /* ── Tabs ── */
  .ctabs{display:flex;border-bottom:1px solid rgba(255,255,255,.06);margin-top:12px;}
  .ctab{flex:1;padding:8px 4px;text-align:center;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#444;cursor:pointer;border:none;background:transparent;transition:all .15s;}
  .ctab:hover{color:#777;}
  .ctab.active{color:#a78bfa;border-bottom:2px solid #a78bfa;}

  /* ── Row items ── */
  .section{padding:12px 20px 16px;}
  .row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.05);margin-bottom:6px;transition:background .15s;cursor:default;}
  .row:hover{background:rgba(255,255,255,.04);}
  .row:last-child{margin-bottom:0;}
  .row-icon{font-size:18px;flex-shrink:0;width:28px;text-align:center;}
  .row-body{flex:1;min-width:0;}
  .row-label{font-size:13px;font-weight:700;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .row-reason{font-size:10px;color:#4b5563;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .row-right{text-align:right;flex-shrink:0;}
  .row-kwh{font-size:14px;font-weight:800;color:#a78bfa;font-family:'JetBrains Mono',monospace;line-height:1;}
  .row-eta{font-size:10px;color:#6b7280;margin-top:2px;font-family:'JetBrains Mono',monospace;}
  .row-cost{font-size:11px;margin-top:2px;}
  .row-cost .now{color:#f87171;}
  .row-cost .cheap{color:#4ade80;}
  .row-cost .saving{color:#fbbf24;font-weight:700;}

  /* Advies kaarten */
  .advice-card{padding:10px 12px;border-radius:10px;margin-bottom:8px;display:flex;align-items:flex-start;gap:10px;border:1px solid;}
  .advice-gas{background:rgba(251,146,60,.07);border-color:rgba(251,146,60,.2);}
  .advice-electric{background:rgba(99,102,241,.07);border-color:rgba(99,102,241,.2);}
  .advice-battery{background:rgba(248,113,113,.08);border-color:rgba(248,113,113,.2);}
  .advice-behavior{background:rgba(74,222,128,.06);border-color:rgba(74,222,128,.15);}
  .advice-icon{font-size:22px;flex-shrink:0;margin-top:1px;}
  .advice-body{flex:1;}
  .advice-title{font-size:13px;font-weight:700;color:#e2e8f0;}
  .advice-desc{font-size:11px;color:#6b7280;margin-top:3px;line-height:1.5;}
  .advice-action{margin-top:6px;display:inline-block;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.04em;}
  .advice-saving{text-align:right;flex-shrink:0;}
  .advice-eur{font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace;color:#4ade80;}
  .advice-unit{font-size:9px;color:#4b5563;margin-top:2px;}

  /* Progress bar for day progress */
  .progress-row{margin:0 20px 10px;display:flex;align-items:center;gap:8px;}
  .progress-bar{flex:1;height:4px;background:rgba(255,255,255,.07);border-radius:3px;overflow:hidden;}
  .progress-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,#6366f1,#a78bfa);transition:width .8s ease;}
  .progress-label{font-size:10px;color:#4b5563;font-family:'JetBrains Mono',monospace;white-space:nowrap;}

  /* Totaal footer */
  .total-row{display:flex;justify-content:space-between;align-items:center;padding:10px 20px;border-top:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.02);}
  .total-label{font-size:11px;color:#6b7280;font-weight:600;}
  .total-val{font-size:14px;font-weight:800;color:#a78bfa;font-family:'JetBrains Mono',monospace;}
  .total-saving{font-size:11px;color:#fbbf24;font-family:'JetBrains Mono',monospace;}

  .empty{padding:32px 20px;text-align:center;color:#333;font-size:13px;}
  .spinner{display:inline-block;width:18px;height:18px;border:2px solid rgba(255,255,255,.1);border-top-color:#a78bfa;border-radius:50%;animation:spin .8s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}
`;

const SUBSYSTEM_ICONS = {
  boiler:  '🚿', battery: '🔋', zone: '🌡️', ev: '🚗',
  ebike:   '🚴', pool:    '🏊', device: '🔌',
};

function esc(s){const d=document.createElement('div');d.textContent=String(s??'');return d.innerHTML;}
function fmtEta(min){if(min==null)return '—';if(min<60)return `${Math.round(min)}min`;return `${(min/60).toFixed(1)}u`;}
function fmtEur(v){return v!=null?`€${v.toFixed(2)}`:'—';}

class CloudemsDemandCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._prev='';this._tab='systemen';}

  setConfig(cfg){this._cfg=cfg;this._render();}

  set hass(hass){
    this._hass=hass;
    const st=hass.states['sensor.cloudems_energy_demand'];
    const bat=hass.states['sensor.cloudems_batterij_soc'];
    const sig=`${st?.state}|${st?.last_updated}|${bat?.state}`;
    if(sig!==this._prev){this._prev=sig;this._render();}
  }

  _render(){
    const sh=this.shadowRoot;if(!sh)return;
    const hass=this._hass;
    if(!hass){sh.innerHTML=`<style>${S}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;return;}

    const st=hass.states['sensor.cloudems_energy_demand'];
    if(!st||st.state==='unavailable'){
      sh.innerHTML=`<style>${S}</style><div class="card"><div class="empty">⚡ sensor.cloudems_energy_demand niet beschikbaar</div></div>`;return;}

    const attr=st.attributes||{};
    const subsystems  = attr.subsystems || [];
    const devices     = attr.devices    || [];
    const totalKwh    = attr.total_kwh  || 0;
    const advices     = attr.advices     || [];
    const sysTotalKwh = attr.system_total_kwh || 0;
    const devTotalKwh = attr.device_total_kwh || 0;
    const costNow     = attr.total_cost_now   || 0;
    const costCheap   = attr.total_cost_cheap || 0;
    const saving      = attr.total_saving     || 0;
    const cfg         = this._cfg||{};

    // Battery adequacy
    const batSt   = hass.states['sensor.cloudems_batterij_soc'];
    const batCap  = parseFloat(hass.states['sensor.cloudems_status']?.attributes?.battery_capacity_kwh||0)||0;
    const batSoc  = batSt?parseFloat(batSt.state):null;
    const batKwh  = batSoc!=null&&batCap>0?(batSoc-10)/100*batCap:null;
    const gap     = batKwh!=null?Math.max(0,totalKwh-batKwh):null;
    let batCls='bat-warn',batIcon='🔋',batLabel='Batterijstatus onbekend',batSub='Koppel SOC-sensor',batKwhTxt='';
    if(batKwh!=null){
      batKwhTxt=`${batKwh.toFixed(1)} kWh beschikbaar`;
      if(gap<0.3){batCls='bat-ok';batIcon='✅';batLabel='Accu is voldoende';batSub=`${batKwh.toFixed(1)} kWh > ${totalKwh.toFixed(1)} kWh verwacht`;}
      else{batCls='bat-danger';batIcon='⚠️';batLabel=`Tekort: ${gap.toFixed(1)} kWh`;batSub=`Accu ${batKwh.toFixed(1)} kWh < verwacht ${totalKwh.toFixed(1)} kWh — laden aanbevolen`;}
    }

    // Dag-voortgang
    const hr=new Date().getHours(),min=new Date().getMinutes();
    const dayPct=Math.round((hr*60+min)/(24*60)*100);

    const tab=this._tab;
    const ADVICE_CLS={'gas':'advice-gas','electric':'advice-electric','battery':'advice-battery','behavior':'advice-behavior'};
    const renderAdvices = (items) => {
      if(!items.length) return `<div class="empty" style="padding:20px;font-size:12px">Geen adviezen — alles ziet er goed uit ✅</div>`;
      return items.map(a=>`<div class="advice-card ${ADVICE_CLS[a.category]||'advice-electric'}">
        <span class="advice-icon">${a.icon}</span>
        <div class="advice-body">
          <div class="advice-title">${esc(a.title)}</div>
          <div class="advice-desc">${esc(a.description)}</div>
          <span class="advice-action" style="background:rgba(255,255,255,.06);color:rgba(255,255,255,.5)">${esc(a.action)}</span>
        </div>
        <div class="advice-saving">
          <div class="advice-eur">€${a.saving_eur.toFixed(2)}</div>
          <div class="advice-unit">${esc(a.saving_unit)}</div>
        </div>
      </div>`).join('');
    };
    const renderRows = (items) => {
      if(!items.length) return `<div class="empty" style="padding:20px;font-size:12px">Geen data beschikbaar</div>`;
      return items.map(s=>{
        const icon=SUBSYSTEM_ICONS[s.name]||'🔌';
        const costHtml=s.cost_now_eur>0.005?`<div class="row-cost">
          <span class="now">${fmtEur(s.cost_now_eur)}</span>
          ${s.cost_cheap_eur<s.cost_now_eur-0.005?`<span style="color:#4b5563"> → </span><span class="cheap">${fmtEur(s.cost_cheap_eur)}</span>
          <span style="color:#4b5563"> · </span><span class="saving">besparing ${fmtEur(s.saving_eur)}</span>`:''}
        </div>`:'';
        const progressBarHtml=s.current_val!=null&&s.target_val!=null&&s.target_val>0?
          `<div style="margin-top:4px"><div style="height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden">
            <div style="height:100%;width:${Math.min(100,s.current_val/s.target_val*100).toFixed(0)}%;background:#a78bfa;border-radius:2px"></div>
          </div></div>`:'';
        return `<div class="row">
          <span class="row-icon">${icon}</span>
          <div class="row-body">
            <div class="row-label">${esc(s.label)}</div>
            <div class="row-reason">${esc(s.reason||'')}</div>
            ${progressBarHtml}
          </div>
          <div class="row-right">
            <div class="row-kwh">${s.kwh_needed.toFixed(2)} kWh</div>
            <div class="row-eta">${fmtEta(s.eta_minutes)}${s.unit&&s.current_val!=null?` · ${s.current_val.toFixed(s.unit==='%'?0:1)}${s.unit}`:''}</div>
            ${costHtml}
          </div>
        </div>`;
      }).join('');
    };

    sh.innerHTML=`<style>${S}</style>
    <div class="card"><div class="inner">
      <div class="hdr">
        <div class="hdr-icon">⚡</div>
        <div>
          <div class="hdr-title">${esc(cfg.title||'Energiebehoefte vandaag')}</div>
          <div class="hdr-sub">${subsystems.length} systemen · ${devices.length} apparaten</div>
        </div>
        <div class="hdr-total">
          <div class="hdr-total-kwh">${totalKwh.toFixed(2)} kWh</div>
          <div class="hdr-total-eur">${fmtEur(costNow)} → ${fmtEur(costCheap)}</div>
        </div>
      </div>

      <div class="bat-strip ${batCls}">
        <span class="bat-icon">${batIcon}</span>
        <div class="bat-body">
          <div class="bat-label">${batLabel}</div>
          <div class="bat-sub">${batSub}</div>
        </div>
        ${batKwhTxt?`<span class="bat-kwh" style="color:${gap>0.3?'#f87171':'#4ade80'}">${gap>0.3?'-'+gap.toFixed(1):'✓'} kWh</span>`:''}
      </div>

      <div class="progress-row" style="margin-top:10px">
        <span class="progress-label">00:00</span>
        <div class="progress-bar"><div class="progress-fill" style="width:${dayPct}%"></div></div>
        <span class="progress-label">${String(hr).padStart(2,'0')}:${String(min).padStart(2,'0')} · ${dayPct}%</span>
      </div>

      <div class="ctabs">
        <button class="ctab ${tab==='systemen'?'active':''}" data-tab="systemen">🎯 Systemen (${sysTotalKwh.toFixed(1)} kWh)</button>
        <button class="ctab ${tab==='apparaten'?'active':''}" data-tab="apparaten">🔌 Apparaten (${devTotalKwh.toFixed(1)} kWh)</button>
        <button class="ctab ${tab==='advies'?'active':''}" data-tab="advies">💡 Advies${advices.length?` (${advices.length})`:''}</button>
      </div>

      <div class="section">
        ${tab==='systemen'?renderRows(subsystems):tab==='apparaten'?renderRows(devices):renderAdvices(advices)}
      </div>

      ${saving>0.05?`<div class="total-row">
        <span class="total-label">Besparingspotentieel vandaag</span>
        <div style="text-align:right">
          <div class="total-val">${totalKwh.toFixed(2)} kWh</div>
          <div class="total-saving">bespaar ${fmtEur(saving)} slim plannen</div>
        </div>
      </div>`:''}
    </div></div>`;

    sh.querySelectorAll('.ctab').forEach(b=>b.addEventListener('click',()=>{this._tab=b.dataset.tab;this._render();}));
  }

  getCardSize(){return 6;}
  static getConfigElement(){return document.createElement('cloudems-demand-card-editor');}
  static getStubConfig(){return {title:'Energiebehoefte vandaag'};}
}

class CloudemsDemandCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(c){this._cfg={...c};this._render();}
  _fire(){this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));}
  _render(){
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06)}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:180px}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${this._cfg.title||'Energiebehoefte vandaag'}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change',e=>{this._cfg={...this._cfg,title:e.target.value};this._fire();});
  }
}

if (!customElements.get('cloudems-demand-card-editor')) customElements.define('cloudems-demand-card-editor', CloudemsDemandCardEditor);
if (!customElements.get('cloudems-demand-card')) customElements.define('cloudems-demand-card', CloudemsDemandCard);
window.customCards=window.customCards??[];
window.customCards.push({type:'cloudems-demand-card',name:'CloudEMS Energiebehoefte',description:'Verwacht verbruik vandaag per systeem en apparaat',preview:true});
console.info('%c CLOUDEMS-DEMAND-CARD %c v'+DEMAND_CARD_VERSION+' ','background:#6366f1;color:#fff;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#111318;color:#a78bfa;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
