// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// CloudEMS Alerts Ticker Card v5.5.465
const ALERTS_VERSION = "5.5.465";

class CloudEMSAlertsTickerCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this._idx=0; this._timer=null; }
  setConfig(c){ this._cfg={title:'CloudEMS Meldingen',interval:5000,...c}; }
  disconnectedCallback(){ if(this._timer)clearInterval(this._timer); }

  
  static getConfigElement(){return document.createElement('cloudems-alerts-ticker-card-editor');}
  set hass(h){
    this._hass=h;
    const st=h?.states['sensor.cloudems_notifications'];
    if(!st){this._render([],0,0,0);return;}
    const a=st.attributes;
    const alerts=(a.active_alerts||[]).slice().sort((x,y)=>{
      const p={'critical':0,'warning':1,'info':2};
      return (p[x.severity]??3)-(p[y.severity]??3);
    });
    this._alerts=alerts;
    const crit=a.critical_count||0, warn=a.warning_count||0, info=a.info_count||0;
    if(!this._running && alerts.length>1){
      this._running=true;
      this._timer=setInterval(()=>{
        this._idx=(this._idx+1)%this._alerts.length;
        this._tick();
      }, this._cfg.interval);
    }
    this._render(alerts,crit,warn,info);
  }

  _tick(){
    const sh=this.shadowRoot;
    const a=this._alerts[this._idx];
    if(!a)return;
    const txt=sh.getElementById('txt');
    const dot=sh.getElementById('dot');
    if(!txt||!dot)return;
    txt.style.opacity='0';
    setTimeout(()=>{
      txt.textContent=`${a.title} — ${a.message}`;
      dot.style.background=this._col(a.severity);
      txt.style.opacity='1';
    },250);
  }

  _col(s){ return s==='critical'?'#f87171':s==='warning'?'#fb923c':'#60a5fa'; }

  _render(alerts,crit,warn,info){
    const sh=this.shadowRoot;
    if(!alerts.length){
      sh.innerHTML=`<style>:host{display:block}.card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:12px 16px;font-family:var(--primary-font-family,sans-serif);display:flex;align-items:center;gap:10px;font-size:12px;color:#4ade80}  </style><div class="card">✅ Geen actieve meldingen</div>`;
      return;
    }
    const first=alerts[0];
    const badges=[];
    if(crit) badges.push(`<span style="background:rgba(248,113,113,.15);color:#f87171;border:1px solid rgba(248,113,113,.3);border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">${crit} kritiek</span>`);
    if(warn) badges.push(`<span style="background:rgba(251,146,60,.12);color:#fb923c;border:1px solid rgba(251,146,60,.25);border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">${warn} waarsch.</span>`);
    if(info) badges.push(`<span style="background:rgba(96,165,250,.12);color:#60a5fa;border:1px solid rgba(96,165,250,.25);border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">${info} info</span>`);

    sh.innerHTML=`
    <style>
      :host{display:block}
      .card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:12px 16px;font-family:var(--primary-font-family,sans-serif);font-size:12px}
      .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
      .title{font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b}
      .badges{display:flex;gap:6px;flex-wrap:wrap}
      .ticker{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.04);border-radius:8px;padding:10px 14px;border:1px solid rgba(255,255,255,0.06)}
      .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;transition:background .3s}
      .txt{flex:1;color:#e2e8f0;line-height:1.5;transition:opacity .25s;font-size:12px}
      .counter{font-size:10px;color:#475569;flex-shrink:0;font-family:monospace}
    </style>
    <div class="card">
      <div class="top">
        <span class="title">Meldingen</span>
        <div class="badges">${badges.join('')}</div>
      </div>
      <div class="ticker">
        <div class="dot" id="dot" style="background:${this._col(first.severity)}"></div>
        <div class="txt" id="txt">${first.title} — ${first.message}</div>
        ${alerts.length>1?`<div class="counter" id="ctr">1/${alerts.length}</div>`:''}
      </div>
    </div>`;
    this._idx=0;
  }

  getCardSize(){ return 1; }
  static getConfigElement(){return document.createElement('cloudems-alerts-ticker-card-editor');}
  static getStubConfig(){ return {}; }
}

class CloudEMSAlertsTickerCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){}
  set hass(h){}
  connectedCallback(){ this.shadowRoot.innerHTML=`<div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">Geen configuratie nodig.</div>`; }
}




class CloudemsAlertsTickerCardEditor extends HTMLElement{
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
    
    var row_interval=document.createElement('div');row_interval.style.marginBottom='10px';
    var lbl_interval=document.createElement('label');lbl_interval.textContent='Interval (ms)';lbl_interval.style.cssText='display:block;font-size:12px;color:#aaa;margin-bottom:4px';
    var inp_interval=document.createElement('input');
    inp_interval.id='interval';
    inp_interval.type='number';
    inp_interval.style.cssText='background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;box-sizing:border-box;width:100%';
    inp_interval.value=c.interval||'4000';
    
    row_interval.appendChild(lbl_interval);row_interval.appendChild(inp_interval);sh.appendChild(row_interval);
    inp_interval.addEventListener('change',function(){
      var nc=Object.assign({},c);
      nc["interval"]=inp_interval.type==="number"?parseFloat(inp_interval.value)||0:inp_interval.value||undefined;
      if(nc['interval']===undefined||nc['interval']==='')delete nc['interval'];
      self.dispatchEvent(new CustomEvent('config-changed',{detail:{config:nc},bubbles:true,composed:true}));
    });
  }
}
if(!customElements.get('cloudems-alerts-ticker-card-editor'))customElements.define('cloudems-alerts-ticker-card-editor',CloudemsAlertsTickerCardEditor);
if(!customElements.get('cloudems-alerts-ticker-card-editor'))customElements.define('cloudems-alerts-ticker-card-editor',CloudemsAlertsTickerCardEditor);

if(!customElements.get('cloudems-alerts-ticker-card')) customElements.define('cloudems-alerts-ticker-card', CloudEMSAlertsTickerCard);
if(!customElements.get('cloudems-alerts-ticker-card-editor')) customElements.define('cloudems-alerts-ticker-card-editor', CloudEMSAlertsTickerCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-alerts-ticker-card',name:'CloudEMS Alerts Ticker',description:'Roterende meldingen ticker met prioriteit kritiek→waarschuwing→info'});
console.info('%c CLOUDEMS-ALERTS-TICKER %c v'+ALERTS_VERSION+' ','background:#f87171;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#f87171;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
