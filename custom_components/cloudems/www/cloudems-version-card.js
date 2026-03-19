// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Version Card  v1.0.1

class CloudEMSVersionCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg = c; }
  set hass(h){
    this._hass = h;
    const wd  = h?.states['sensor.cloudems_watchdog']?.attributes || {};
    const sig = [wd.cloudems_version, wd.version, wd.uptime_s, wd.update_cycles, wd.errors_total].join('|');
    if(sig === this._prev) return;
    this._prev = sig;

    const ver     = wd.cloudems_version || wd.version || h?.states['sensor.cloudems_watchdog']?.attributes?.cloudems_version || '?';
    const uptime  = wd.uptime_s  ? _fmtUp(wd.uptime_s)  : '—';
    const cycles  = wd.update_cycles != null ? wd.update_cycles.toLocaleString('nl') : '—';
    const errors  = wd.errors_total  != null ? wd.errors_total  : '—';
    const restarts= wd.restart_count != null ? wd.restart_count : '—';
    const perf    = wd.cycle_ms != null ? `${wd.cycle_ms} ms` : '—';

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
        <div class="row"><span class="lbl">Fouten (ooit)</span><span class="val" style="color:${errors>0?'#f87171':'#4ade80'}">${errors}</span></div>
        <div class="row"><span class="lbl">Herstarts</span><span class="val" style="color:${restarts>0?'#fb923c':'#4ade80'}">${restarts}</span></div>
        <div class="row"><span class="lbl">Cyclustijd</span><span class="val">${perf}</span></div>
      </div>`;
  }
  getCardSize(){ return 2; }
  static getConfigElement(){ return document.createElement('cloudems-version-card-editor'); }
  static getStubConfig(){ return {type:'custom:cloudems-version-card'}; }
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

customElements.define('cloudems-version-card', CloudEMSVersionCard);
customElements.define('cloudems-version-card-editor', CloudEMSVersionCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({type:'cloudems-version-card', name:'CloudEMS Versie Card', description:'CloudEMS versie, uptime en systeem statistieken', preview:true});
console.info('%c CLOUDEMS-VERSION-CARD %c v1.0.1 ','background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
