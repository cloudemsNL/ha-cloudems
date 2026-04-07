// CloudEMS Dynamic Fuse Monitor Card v5.5.6
const FM_VERSION = "5.5.318";

class CloudEMSFuseMonitorCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={title:'Groepenkast Bewaking',fuse_a:25,warn_pct:80,alert_pct:95,...c}; }

  set hass(h){
    this._hass=h;
    const l1 = h?.states['sensor.cloudems_current_l1'];
    const l2 = h?.states['sensor.cloudems_current_l2'];
    const l3 = h?.states['sensor.cloudems_current_l3'];
    const p1  = h?.states['sensor.cloudems_p1'];
    const nilm= h?.states['sensor.cloudems_nilm_running_devices'];

    const fuse = this._cfg.fuse_a;

    const phases = ['L1','L2','L3'].map((ph,i)=>{
      const st=[l1,l2,l3][i];
      const a = parseFloat(st?.state||0)||0;
      const max_a = parseFloat(st?.attributes?.max_current_a||fuse)||fuse;
      const power_w = parseFloat(st?.attributes?.power_w||0)||0;
      const pct = max_a>0 ? a/max_a*100 : 0;
      return {ph, a, max_a, power_w, pct};
    });

    // Running devices from NILM
    const devices = nilm?.attributes?.devices||[];

    const sig=phases.map(p=>p.a.toFixed(1)).join('|');
    if(sig===this._prev)return;
    this._prev=sig;
    this._render(phases, devices, fuse);
  }

  _col(pct, warn, alert){
    if(pct>=alert) return '#f87171';
    if(pct>=warn)  return '#fb923c';
    return '#4ade80';
  }

  _render(phases, devices, fuse){
    const sh=this.shadowRoot;
    const warn=this._cfg.warn_pct, alert=this._cfg.alert_pct;
    const maxPct = Math.max(...phases.map(p=>p.pct));
    const status = maxPct>=alert?'🚨 KRITIEK':maxPct>=warn?'⚠️ Let Op':'✅ OK';
    const statusCol = maxPct>=alert?'#f87171':maxPct>=warn?'#fb923c':'#4ade80';

    const phaseHtml = phases.map(p=>{
      const col=this._col(p.pct,warn,alert);
      const barW=Math.min(100,p.pct);
      const warnLine=warn;
      const alertLine=alert;
      return `
        <div class="phase-row">
          <div class="phase-name" style="color:${col}">${p.ph}</div>
          <div class="phase-bar-wrap">
            <div class="phase-bar-bg">
              <div class="phase-bar-fill" style="width:${barW}%;background:${col}"></div>
              <div class="phase-mark warn" style="left:${warnLine}%"></div>
              <div class="phase-mark alert" style="left:${alertLine}%"></div>
            </div>
          </div>
          <div class="phase-vals">
            <span style="color:${col};font-weight:700;font-family:monospace">${p.a.toFixed(1)}A</span>
            <span style="color:#475569">/${p.max_a}A</span>
          </div>
          <div class="phase-pct" style="color:${col}">${p.pct.toFixed(0)}%</div>
          <div class="phase-w" style="color:#64748b">${p.power_w>=1000?(p.power_w/1000).toFixed(1)+'kW':Math.round(p.power_w)+'W'}</div>
        </div>`;
    }).join('');

    // Headroom: how much can we still add per phase
    const headroom = phases.map(p=>({ph:p.ph, free_a: Math.max(0,p.max_a-p.a), free_w: Math.max(0,(p.max_a-p.a)*230)}));
    const headHtml = headroom.map(h=>`
      <div class="head-item">
        <div class="head-ph">${h.ph}</div>
        <div class="head-val">${h.free_a.toFixed(1)}A vrij</div>
        <div class="head-w">${h.free_w>=1000?(h.free_w/1000).toFixed(1)+'kW':Math.round(h.free_w)+'W'}</div>
        <div class="head-hint" style="color:#475569;font-size:10px">${
          h.free_w>=3700?'✓ EV (3.7kW)':
          h.free_w>=2000?'✓ Inductie':
          h.free_w>=1200?'✓ Koffie':
          h.free_w>=500?'✓ Vaatwasser':
          '⚠ Vol'
        }</div>
      </div>`).join('');

    // Top running devices
    const devHtml = devices.slice(0,5).map(d=>`
      <div class="dev-row">
        <span>${d.label||d.device_type||'Apparaat'}</span>
        <span style="color:#94a3b8;font-family:monospace">${d.power_w>=1000?(d.power_w/1000).toFixed(1)+'kW':Math.round(d.power_w)+'W'} · ${d.phase||'?'}</span>
      </div>`).join('');

    sh.innerHTML=`
    <style>
      :host{display:block}
      .card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:14px 16px;font-family:var(--primary-font-family,sans-serif)}
      .hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
      .title{font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b}
      .status{font-size:12px;font-weight:700}
      .phase-row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
      .phase-row:last-child{border:none}
      .phase-name{width:24px;font-weight:700;font-size:13px;flex-shrink:0}
      .phase-bar-wrap{flex:1;position:relative}
      .phase-bar-bg{height:10px;background:rgba(255,255,255,0.06);border-radius:5px;position:relative;overflow:visible}
      .phase-bar-fill{position:absolute;left:0;top:0;height:100%;border-radius:5px;transition:width .4s}
      .phase-mark{position:absolute;top:-3px;width:2px;height:16px;border-radius:1px}
      .phase-mark.warn{background:rgba(251,146,60,.6)}
      .phase-mark.alert{background:rgba(248,113,113,.6)}
      .phase-vals{width:72px;text-align:right;font-size:12px;flex-shrink:0}
      .phase-pct{width:36px;text-align:right;font-size:11px;font-family:monospace;flex-shrink:0}
      .phase-w{width:50px;text-align:right;font-size:11px;flex-shrink:0}
      .sep{height:1px;background:rgba(255,255,255,0.05);margin:12px 0}
      .sec-title{font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#475569;margin-bottom:8px}
      .head-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
      .head-item{background:rgba(255,255,255,0.03);border-radius:7px;padding:8px;border:1px solid rgba(255,255,255,0.05)}
      .head-ph{font-size:10px;color:#64748b;margin-bottom:2px}
      .head-val{font-size:13px;font-weight:700;font-family:monospace;color:#e2e8f0}
      .head-w{font-size:10px;color:#64748b;margin-bottom:3px}
      .dev-row{display:flex;justify-content:space-between;padding:5px 0;font-size:12px;color:#94a3b8;border-bottom:1px solid rgba(255,255,255,0.03)}
      .dev-row:last-child{border:none}
    </style>
    <div class="card">
      <div class="hdr">
        <span class="title">${this._cfg.title}</span>
        <span class="status" style="color:${statusCol}">${status}</span>
      </div>
      ${phaseHtml}
      <div class="sep"></div>
      <div class="sec-title">Ruimte per fase</div>
      <div class="head-grid">${headHtml}</div>
      ${devHtml?`<div class="sep"></div><div class="sec-title">Actieve apparaten</div>${devHtml}`:''}
    </div>`;
  }
  getCardSize(){ return 3; }
  static getConfigElement(){ return document.createElement('cloudems-fuse-monitor-card-editor'); }
  static getStubConfig(){ return {fuse_a:25}; }
}
class CloudEMSFuseMonitorCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){}
  set hass(h){}
  connectedCallback(){ this.shadowRoot.innerHTML=`<div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">Config: <code>fuse_a: 25</code> · <code>warn_pct: 80</code> · <code>alert_pct: 95</code></div>`; }
}
if(!customElements.get('cloudems-fuse-monitor-card')) customElements.define('cloudems-fuse-monitor-card', CloudEMSFuseMonitorCard);
if(!customElements.get('cloudems-fuse-monitor-card-editor')) customElements.define('cloudems-fuse-monitor-card-editor', CloudEMSFuseMonitorCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-fuse-monitor-card',name:'CloudEMS Groepenkast Bewaking',description:'Live fase-stroom bewaking met vrije capaciteit en actieve apparaten'});
console.info('%c CLOUDEMS-FUSE-MONITOR %c v'+FM_VERSION+' ','background:#fb923c;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#fb923c;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
