/**
 * CloudEMS Pool Card  v1.0.0
 * Zwembad — filtreerpomp, warmtepomp, temperatuur, UV, robot, advies
 */
const POOL_VERSION = '5.4.1';

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
  :host{display:block}*{box-sizing:border-box;margin:0;padding:0}
  .card{background:#0e1520;border-radius:16px;border:1px solid rgba(255,255,255,0.06);font-family:'Syne',sans-serif;overflow:hidden}

  /* Header */
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid rgba(255,255,255,0.06);position:relative;overflow:hidden}
  .hdr::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(41,182,246,0.06) 0%,transparent 60%);pointer-events:none}
  .hdr-icon{font-size:20px}
  .hdr-texts{flex:1}
  .hdr-title{font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.04em;text-transform:uppercase}
  .hdr-sub{font-size:11px;color:#6b7280;margin-top:2px}
  .hdr-badge{font-size:10px;font-weight:700;padding:3px 10px;border-radius:10px}
  .badge-ok{background:rgba(74,222,128,0.12);color:#4ade80;border:1px solid rgba(74,222,128,0.25)}
  .badge-act{background:rgba(41,182,246,0.12);color:#38bdf8;border:1px solid rgba(41,182,246,0.25)}
  .badge-off{background:rgba(255,255,255,0.05);color:#4b5563;border:1px solid rgba(255,255,255,0.08)}
  .badge-nc{background:rgba(245,158,11,0.10);color:#fbbf24;border:1px solid rgba(245,158,11,0.2)}

  /* Temp + voortgang */
  .hero{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(255,255,255,0.05);border-bottom:1px solid rgba(255,255,255,0.06)}
  .hero-tile{padding:14px 18px;background:#0e1520;display:flex;flex-direction:column;gap:4px}
  .hero-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#374151}
  .hero-val{font-size:22px;font-weight:800;font-family:'JetBrains Mono',monospace}
  .hero-sub{font-size:11px;color:#4b5563}
  .c-blue{color:#38bdf8}.c-green{color:#4ade80}.c-amber{color:#fbbf24}.c-muted{color:#4b5563}.c-red{color:#f87171}

  /* Filter progressie */
  .filter-prog{padding:10px 18px 8px;border-bottom:1px solid rgba(255,255,255,0.05)}
  .fp-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#374151;margin-bottom:5px;display:flex;justify-content:space-between}
  .fp-track{height:6px;background:rgba(255,255,255,0.07);border-radius:3px;overflow:hidden}
  .fp-fill{height:100%;border-radius:3px;transition:width .4s;background:linear-gradient(90deg,#0ea5e9,#38bdf8)}

  /* Apparaten grid */
  .devices{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:12px 18px;border-bottom:1px solid rgba(255,255,255,0.05)}
  .dev-tile{background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;border:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:8px}
  .dev-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .dev-dot.on{background:#4ade80;box-shadow:0 0 6px rgba(74,222,128,0.4)}
  .dev-dot.off{background:#374151}
  .dev-dot.na{background:#1f2937}
  .dev-info{flex:1;min-width:0}
  .dev-name{font-size:11px;font-weight:700;color:#9ca3af}
  .dev-state{font-size:10px;color:#4b5563;margin-top:1px}
  .dev-mode{font-size:9px;color:#374151;margin-top:1px;font-family:'JetBrains Mono',monospace}

  /* Advies */
  .advice{margin:0 18px 14px;padding:10px 14px;border-radius:10px;background:rgba(41,182,246,0.06);border:1px solid rgba(41,182,246,0.15);font-size:11px;color:#93c5fd;line-height:1.6}
  .advice.warn{background:rgba(245,158,11,0.07);border-color:rgba(245,158,11,0.2);color:#fbbf24}
  .advice.ok{background:rgba(74,222,128,0.06);border-color:rgba(74,222,128,0.15);color:#86efac}

  /* Niet geconfigureerd */
  .not-cfg{padding:28px 18px;text-align:center}
  .not-cfg-icon{font-size:36px;margin-bottom:12px}
  .not-cfg-title{font-size:13px;font-weight:700;color:#9ca3af;margin-bottom:6px}
  .not-cfg-sub{font-size:11px;color:#4b5563;line-height:1.6}

  /* Section label */
  .sec-hdr{display:flex;align-items:center;gap:8px;padding:10px 18px 4px}
  .sec-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#374151}
  .sec-line{flex:1;height:1px;background:rgba(255,255,255,0.05)}
`;

class CloudEMSPoolCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); this._prev=''; }
  setConfig(c){ this._cfg={title:'Zwembad',...c}; }

  set hass(h){
    this._hass=h;
    const st=h.states['sensor.cloudems_zwembad_status'];
    const sig=[st?.state, JSON.stringify(st?.attributes||{})].join('|');
    if(sig!==this._prev){this._prev=sig;this._render();}
  }

  _a(e,k,d=null){return this._hass?.states?.[e]?.attributes?.[k]??d;}
  _s(e){return this._hass?.states?.[e]||null;}

  _render(){
    const sh=this.shadowRoot; if(!sh||!this._hass) return;

    const poolSt = this._s('sensor.cloudems_zwembad_status');
    const notCfg = !poolSt || ['unavailable','unknown','Niet geconfigureerd',''].includes(poolSt.state);
    const a = poolSt?.attributes || {};

    // Niet geconfigureerd
    if(notCfg){
      sh.innerHTML=`<style>${CSS}</style>
      <div class="card">
        <div class="hdr">
          <span class="hdr-icon">🏊</span>
          <div class="hdr-texts">
            <div class="hdr-title">${esc(this._cfg.title)}</div>
            <div class="hdr-sub">Nog niet geconfigureerd</div>
          </div>
          <span class="hdr-badge badge-nc">INACTIEF</span>
        </div>
        <div class="not-cfg">
          <div class="not-cfg-icon">⚙️</div>
          <div class="not-cfg-title">Zwembad nog niet geconfigureerd</div>
          <div class="not-cfg-sub">Koppel je apparaten via<br><b>CloudEMS → Configureren → Zwembad Controller</b><br><br>Ondersteund: filtreerpomp · warmtepomp · UV/zout · robotreiniger · temperatuursensor</div>
        </div>
      </div>`;
      return;
    }

    const filterOn  = !!a.filter_is_on;
    const heatOn    = !!a.heat_is_on;
    const uvOn      = !!a.uv_is_on;
    const robotOn   = !!a.robot_is_on;
    const anyOn     = filterOn || heatOn;
    const waterTemp = a.water_temp_c;
    const setpoint  = a.heat_setpoint_c ?? 28;
    const filterH   = a.filter_hours_today ?? 0;
    const filterTgt = a.filter_target_hours ?? 4;
    const filterPct = Math.min(100, Math.round((filterH / Math.max(filterTgt,1)) * 100));
    const filterPwr = a.filter_power_w ?? 0;
    const heatPwr   = a.heat_power_w ?? 0;
    const advice    = a.advice || '';

    // Header badge
    const badgeCls = filterOn || heatOn ? 'badge-act' : 'badge-ok';
    const badgeLbl = filterOn && heatOn ? '🔄 Filter + Warmte'
                   : filterOn ? '🔄 Filteren'
                   : heatOn   ? '🌡️ Verwarmen'
                   : '✅ Standby';

    // Hero tiles
    const tempColor = waterTemp == null ? '#4b5563'
                    : waterTemp >= setpoint - 0.5 ? '#4ade80'
                    : waterTemp >= setpoint - 3   ? '#fbbf24'
                    : '#f87171';
    const tempHtml = waterTemp != null
      ? `<div class="hero-val" style="color:${tempColor}">${waterTemp.toFixed(1)}<span style="font-size:14px">°C</span></div>
         <div class="hero-sub">setpoint ${setpoint}°C</div>`
      : `<div class="hero-val c-muted">—</div><div class="hero-sub">geen sensor</div>`;

    const pwrTotal = filterPwr + heatPwr;
    const pwrHtml = pwrTotal > 0
      ? `<div class="hero-val c-blue">${Math.round(pwrTotal)}<span style="font-size:14px"> W</span></div>
         <div class="hero-sub">${filterPwr>0?`filter ${Math.round(filterPwr)}W`:''}${filterPwr>0&&heatPwr>0?' + ':''}${heatPwr>0?`warmte ${Math.round(heatPwr)}W`:''}</div>`
      : `<div class="hero-val c-muted">0 W</div><div class="hero-sub">geen verbruik</div>`;

    // Apparaten
    const devs = [
      { icon:'🔄', name:'Filtreerpomp', on:filterOn, state:filterOn?`Aan · ${a.filter_mode||''}`:a.filter_reason?`Uit: ${a.filter_reason}`:'Uit', mode:a.filter_mode||'' },
      { icon:'🌡️', name:'Warmtepomp',   on:heatOn,   state:heatOn?`Aan · ${a.heat_mode||''}`:a.heat_reason?`Uit: ${a.heat_reason}`:'Uit',   mode:a.heat_mode||'' },
      { icon:'☀️', name:'UV / Zout',    on:uvOn,     state:uvOn?'Aan · mee met filtratie':'Uit', mode:'' },
      { icon:'🤖', name:'Robotreiniger',on:robotOn,  state:robotOn?'Aan':'Uit', mode:'' },
    ].map(d=>`<div class="dev-tile">
        <div class="dev-dot ${d.on?'on':'off'}"></div>
        <div class="dev-info">
          <div class="dev-name">${d.icon} ${esc(d.name)}</div>
          <div class="dev-state" style="color:${d.on?'#4ade80':'#4b5563'}">${esc(d.state)}</div>
        </div>
      </div>`).join('');

    // Advies kleur
    const advCls = advice.startsWith('✅') ? 'ok'
                 : advice.startsWith('⚠️') ? 'warn'
                 : '';

    sh.innerHTML=`<style>${CSS}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">🏊</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(this._cfg.title)}</div>
          <div class="hdr-sub">${esc(poolSt.state)}</div>
        </div>
        <span class="hdr-badge ${badgeCls}">${badgeLbl}</span>
      </div>
      <div class="hero">
        <div class="hero-tile">
          <div class="hero-lbl">Watertemperatuur</div>
          ${tempHtml}
        </div>
        <div class="hero-tile">
          <div class="hero-lbl">Huidig verbruik</div>
          ${pwrHtml}
        </div>
      </div>
      <div class="filter-prog">
        <div class="fp-lbl">
          <span>Filtratie vandaag</span>
          <span style="font-family:'JetBrains Mono',monospace;color:${filterPct>=100?'#4ade80':'#38bdf8'}">${filterH.toFixed(1)}u / ${filterTgt}u doel</span>
        </div>
        <div class="fp-track"><div class="fp-fill" style="width:${filterPct}%;background:${filterPct>=100?'linear-gradient(90deg,#4ade80,#86efac)':'linear-gradient(90deg,#0ea5e9,#38bdf8)'}"></div></div>
      </div>
      <div class="sec-hdr"><span class="sec-title">Apparaten</span><div class="sec-line"></div></div>
      <div class="devices">${devs}</div>
      ${advice?`<div class="advice ${advCls}">${esc(advice)}</div>`:''}
    </div>`;
  }

  getCardSize(){return 5;}
  static getConfigElement(){return document.createElement('cloudems-pool-card-editor');}
  static getStubConfig(){return{title:'Zwembad'};}
}

class CloudEMSPoolCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(c){this._cfg={...c};this._render();}
  _fire(){this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));}
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`<style>.wrap{padding:8px}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0}.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px}input{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px}</style>
    <div class="wrap"><div class="row"><label class="lbl">Titel</label><input type="text" value="${esc(cfg.title||'Zwembad')}"></div></div>`;
    this.shadowRoot.querySelector('input').addEventListener('change',e=>{this._cfg={...this._cfg,title:e.target.value};this._fire();});
  }
}

if (!customElements.get('cloudems-pool-card')) customElements.define('cloudems-pool-card',CloudEMSPoolCard);
if (!customElements.get('cloudems-pool-card-editor')) customElements.define('cloudems-pool-card-editor',CloudEMSPoolCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-pool-card',name:'CloudEMS Pool Card',description:'Zwembad — filtreerpomp, warmtepomp, temperatuur, UV, robot',preview:true});
console.info('%c CLOUDEMS-POOL-CARD %c v'+POOL_VERSION+' ','background:#38bdf8;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#38bdf8;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
