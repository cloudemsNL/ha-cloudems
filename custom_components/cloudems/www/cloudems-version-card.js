// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
const CARD_VERSION_VERSION = '5.5.465';
// All rights reserved. See LICENSE for full terms.
// CloudEMS Version Card  v5.5.465

class CloudEMSVersionCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg = c; }
  
  static getConfigElement(){return document.createElement('cloudems-version-card-editor');}
  set hass(h){
    this._hass = h;
    // Lees van sensor.cloudems_version_info — kleine dedicated sensor, nooit 16KB issue
    const vi  = h?.states['sensor.cloudems_version_info']?.attributes || {};
    // Fallback: lees rechtstreeks uit watchdog subdicts
    const wd  = h?.states['sensor.cloudems_watchdog']?.attributes || {};
    const _sys = wd.system || {};
    const _wdg = wd.watchdog || {};
    const _prf = wd.performance || {};

    const ver      = vi.cloudems_version || _sys.version || '?';
    const uptime_s = vi.uptime_s != null ? vi.uptime_s : _sys.uptime_s;
    const cycles_v = vi.update_cycles != null ? vi.update_cycles : _sys.update_cycles;
    const fails_v  = vi.total_failures != null ? vi.total_failures : _wdg.total_failures;
    const restart_v= vi.total_restarts != null ? vi.total_restarts : _wdg.total_restarts;
    const avgms_v  = vi.avg_ms != null ? vi.avg_ms : _prf.avg_ms;
    const err_up_v  = vi.errors_since_uptime ?? null;
    const err_td_v  = vi.errors_today ?? null;
    const err_7d_v  = vi.errors_7d_avg ?? null;

    const sig = [ver, uptime_s, restart_v, avgms_v, err_up_v, err_td_v, err_7d_v].join('|');
    if(sig === this._prev) return;
    this._prev = sig;

    const uptime  = uptime_s != null ? _fmtUp(uptime_s) : '—';
    const cycles  = cycles_v != null ? Number(cycles_v).toLocaleString('nl') : '—';
    const errUptime  = err_up_v != null ? err_up_v : '—';
    const errToday   = err_td_v != null ? err_td_v : '—';
    const err7d      = err_7d_v != null ? err_7d_v : '—';
    const err7dCol   = err_7d_v > 5 ? '#f87171' : err_7d_v > 0 ? '#fb923c' : '#4ade80';
    const restarts= restart_v != null ? restart_v : '—';
    const perf    = avgms_v  != null ? `${Math.round(avgms_v)} ms` : '—';

    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}
        .card{background:var(--ha-card-background,var(--card-background-color,#1c1c1c));
          border-radius:12px;border:1px solid rgba(255,255,255,0.07);padding:12px 16px;
          font-family:var(--primary-font-family,sans-serif);font-size:12px;color:var(--secondary-text-color,#9ca3af)}
        .row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
        .row:last-child{border:none}
        .lbl{color:var(--secondary-text-color,#6b7280)}
        .val{font-weight:600;color:var(--primary-text-color,#e2e8f0);font-family:monospace}
        .ver{font-size:13px;font-weight:700;color:#4ade80}
      </style>
      <div class="card">
        <div class="row"><span class="lbl">Versie</span><span class="val ver">v${ver}</span></div>
        <div class="row"><span class="lbl">Uptime</span><span class="val">${uptime}</span></div>
        <div class="row"><span class="lbl">Update cycli</span><span class="val">${cycles}</span></div>
        <div class="row"><span class="lbl">Fouten (gem. 7d)</span><span class="val" style="color:${err7dCol}">${err7d}</span></div>
        <div class="row"><span class="lbl">Fouten (uptime)</span><span class="val" style="color:${errUptime>0?'#fb923c':'#4ade80'}">${errUptime}</span></div>
        <div class="row"><span class="lbl">Fouten (vandaag)</span><span class="val" style="color:${errToday>0?'#fb923c':'#4ade80'}">${errToday}</span></div>
        <div class="row"><span class="lbl">Herstarts</span><span class="val" style="color:${restarts>0?'#fb923c':'#4ade80'}">${restarts}</span></div>
        <div class="row"><span class="lbl">Cyclustijd</span><span class="val">${perf}</span></div>
      </div>`;
  }
  getCardSize(){ return 2; }
  static getConfigElement(){return document.createElement('cloudems-version-card-editor');}
  static getStubConfig(){ return {}; }
}

function _fmtUp(s){
  const d=Math.floor(s/86400), h=Math.floor((s%86400)/3600), m=Math.floor((s%3600)/60);
  return d>0?`${d}d ${h}h`:h>0?`${h}h ${m}m`:`${m}m`;
}

class CloudEMSVersionCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg=c; }
  set hass(h){}
  connectedCallback(){
    this.shadowRoot.innerHTML=`<div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">Geen configuratie nodig.</div>`;
  }
}




class CloudemsVersionCardEditor extends HTMLElement{
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
if(!customElements.get('cloudems-version-card-editor'))customElements.define('cloudems-version-card-editor',CloudemsVersionCardEditor);
if(!customElements.get('cloudems-version-card-editor'))customElements.define('cloudems-version-card-editor',CloudemsVersionCardEditor);

if (!customElements.get('cloudems-version-card')) customElements.define('cloudems-version-card', CloudEMSVersionCard);
if (!customElements.get('cloudems-version-card-editor')) customElements.define('cloudems-version-card-editor', CloudEMSVersionCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({type:'cloudems-version-card', name:'CloudEMS Versie Card', description:'CloudEMS versie, uptime en systeem statistieken'});
console.info('%c CLOUDEMS-VERSION-CARD %c v1.0.1 ','background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
