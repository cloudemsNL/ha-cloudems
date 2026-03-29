// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// CloudEMS Energie Potentieel Card v5.5.4
const EP_VERSION = "5.5.4";

// ── Apparaat-definities ──────────────────────────────────────────────────────
// Elke entry: {id, icon, label, watt, unit, per}
// unit = "keer" of "uur" of "minuten"
const EP_APPLIANCES = [
  // Koken & keuken
  {id:'inductie',    icon:'🍳', label:'Inductie koken',   watt:2000, unit:'keer',    per:15,  per_unit:'min'},
  {id:'oven',        icon:'🫕', label:'Oven',              watt:2200, unit:'keer',    per:45,  per_unit:'min'},
  {id:'koffie',      icon:'☕', label:'Koffie zetten',     watt:1200, unit:'keer',    per:4,   per_unit:'min'},
  {id:'vaatwasser',  icon:'🍽', label:'Vaatwasser',        watt:1800, unit:'keer',    per:60,  per_unit:'min'},
  {id:'waterkoker',  icon:'🫖', label:'Waterkoker',        watt:2200, unit:'keer',    per:3,   per_unit:'min'},
  {id:'magnetron',   icon:'📦', label:'Magnetron',         watt:900,  unit:'keer',    per:5,   per_unit:'min'},
  {id:'broodrooster',icon:'🍞', label:'Broodrooster',      watt:900,  unit:'keer',    per:4,   per_unit:'min'},
  // Wassen & drogen
  {id:'wasmachine',  icon:'🫧', label:'Wasmachine',        watt:500,  unit:'keer',    per:90,  per_unit:'min'},
  {id:'droger',      icon:'🌀', label:'Droger',             watt:2500, unit:'keer',    per:60,  per_unit:'min'},
  // Comfort & verlichting
  {id:'lampen',      icon:'💡', label:'Lampen (huis)',      watt:300,  unit:'uur',     per:1,   per_unit:'uur'},
  {id:'tv',          icon:'📺', label:'TV kijken',          watt:120,  unit:'uur',     per:1,   per_unit:'uur'},
  {id:'pc',          icon:'💻', label:'PC / laptop',        watt:80,   unit:'uur',     per:1,   per_unit:'uur'},
  // Klimaat
  {id:'airco_cool',  icon:'❄️', label:'Airco koelen',       watt:1500, unit:'uur',     per:1,   per_unit:'uur'},
  {id:'airco_heat',  icon:'🔥', label:'Airco verwarmen',    watt:1200, unit:'uur',     per:1,   per_unit:'uur'},
  {id:'ventilator',  icon:'🌬', label:'Ventilator',         watt:50,   unit:'uur',     per:1,   per_unit:'uur'},
  // Mobiliteit
  {id:'ebike',       icon:'🚴', label:'E-bike laden',       watt:250,  unit:'keer',    per:120, per_unit:'min'},
  {id:'ev_10km',     icon:'🚗', label:'Auto 10 km',         watt:2000, unit:'keer',    per:30,  per_unit:'min'},
  // Persoonlijke verzorging
  {id:'douche',      icon:'🚿', label:'Douche (8 min)',     watt:0,    unit:'keer',    per:0,   per_unit:'min', boiler:true},
  {id:'haardroger',  icon:'💨', label:'Haardroger',         watt:2000, unit:'keer',    per:10,  per_unit:'min'},
];

// Berekend verbruik in kWh
function kwh(app) {
  if(app.boiler) return 0; // apart berekend
  return app.watt / 1000 * app.per / 60;
}

// Hoeveel keer past dit in een hoeveelheid kWh?
function howMany(app, available_kwh) {
  if(app.boiler) return null;
  const k = kwh(app);
  if(k <= 0) return null;
  if(app.unit === 'uur') return Math.floor(available_kwh / k);
  return Math.floor(available_kwh / k);
}

class CloudEMSEnergiePotentieelCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={title:'Energie Potentieel',show_pv:true,show_bat:true,...c}; }

  set hass(h){
    this._hass=h;
    const batSt   = h?.states['sensor.cloudems_battery_so_c'];
    const pvSt    = h?.states['sensor.cloudems_pv_forecast_today'];
    const solarSt = h?.states['sensor.cloudems_solar_system'];

    const soc_pct    = batSt ? parseFloat(batSt.state)||0 : 0;
    const cap_kwh    = parseFloat(batSt?.attributes?.capacity_kwh||0)||10;
    const bat_kwh    = cap_kwh * soc_pct / 100;

    const pv_today   = parseFloat(pvSt?.state||0)||0;
    const pv_done    = parseFloat(solarSt?.attributes?.pv_today_kwh||0)||0;
    const pv_remain  = Math.max(0, pv_today - pv_done);

    // Boiler beschikbare douches
    const boilerSt = h?.states['sensor.cloudems_boiler_status'];
    let boiler_min = null;
    if(boilerSt){
      const groups = boilerSt.attributes?.groups||[];
      for(const g of groups){
        for(const b of (g.boilers||[])){
          if(b.shower_minutes!=null && (boiler_min===null||b.shower_minutes>boiler_min))
            boiler_min=b.shower_minutes;
        }
      }
    }
    // Douches: 8 min per douche
    const douche_count = boiler_min!=null ? Math.floor(boiler_min/8) : null;

    const sig=[soc_pct,bat_kwh,pv_remain,boiler_min].join('|');
    if(sig===this._prev)return;
    this._prev=sig;

    this._render(bat_kwh, soc_pct, cap_kwh, pv_remain, pv_today, douche_count);
  }

  _render(bat_kwh, soc_pct, cap_kwh, pv_remain, pv_today, douche_count){
    const sh=this.shadowRoot;
    const cfg=this._cfg;

    const _fmt=(n,unit)=>{
      if(n===null||n===undefined) return '?';
      if(unit==='uur') return n>=1 ? n+' uur' : (n*60).toFixed(0)+' min';
      return n+'×';
    };

    // Bouw rijen per bron
    const sections=[];

    if(cfg.show_bat && bat_kwh>0.1){
      const rows=EP_APPLIANCES.map(app=>{
        let count, label_extra='';
        if(app.boiler){
          count=douche_count;
        } else {
          count=howMany(app,bat_kwh);
        }
        if(count===null||count===undefined) return null;
        return {icon:app.icon, label:app.label, count, unit:app.unit, app};
      }).filter(r=>r&&r.count>0);

      if(rows.length){
        sections.push({
          title:`🔋 Batterij  ${soc_pct.toFixed(0)}% · ${bat_kwh.toFixed(1)} kWh`,
          color:'#4ade80',
          rows
        });
      }
    }

    if(cfg.show_pv && pv_remain>0.1){
      const rows=EP_APPLIANCES.map(app=>{
        if(app.boiler) return null;
        const count=howMany(app,pv_remain);
        if(count===null||count===undefined||count===0) return null;
        return {icon:app.icon, label:app.label, count, unit:app.unit, app};
      }).filter(Boolean);

      if(rows.length){
        sections.push({
          title:`☀️ Verwachte PV vandaag  nog ${pv_remain.toFixed(1)} kWh`,
          color:'#fbbf24',
          rows
        });
      }
    }

    if(!sections.length){
      sh.innerHTML=`<style>:host{display:block}.card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:16px;font-family:var(--primary-font-family,sans-serif);color:#64748b;font-size:13px;text-align:center}</style><div class="card">Geen energie beschikbaar</div>`;
      return;
    }

    const sectHtml=sections.map(sec=>{
      // Top 8 meest interessante items (niet te lang)
      const top=sec.rows.slice(0,12);
      const pills=top.map(r=>{
        const val=r.app.boiler ? (r.count+'×') : r.unit==='uur' ? r.count+'u' : r.count+'×';
        const col=sec.color;
        return `<div class="pill">
          <span class="pill-icon">${r.icon}</span>
          <span class="pill-label">${r.label}</span>
          <span class="pill-val" style="color:${col}">${val}</span>
        </div>`;
      }).join('');
      return `<div class="section">
        <div class="sec-title" style="color:${sec.color}">${sec.title}</div>
        <div class="grid">${pills}</div>
      </div>`;
    }).join('<div class="sep"></div>');

    sh.innerHTML=`
    <style>
      :host{display:block}
      .card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:14px 16px;font-family:var(--primary-font-family,sans-serif)}
      .hdr{font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:14px}
      .section{}
      .sec-title{font-size:12px;font-weight:700;margin-bottom:10px;letter-spacing:.3px}
      .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px}
      .pill{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:8px 10px;display:flex;align-items:center;gap:7px}
      .pill-icon{font-size:16px;flex-shrink:0}
      .pill-label{font-size:11px;color:#94a3b8;flex:1;line-height:1.3}
      .pill-val{font-size:13px;font-weight:700;flex-shrink:0;font-family:monospace}
      .sep{height:1px;background:rgba(255,255,255,0.06);margin:14px 0}
    </style>
    <div class="card">
      <div class="hdr">${cfg.title}</div>
      ${sectHtml}
    </div>`;
  }

  getCardSize(){ return 3; }
  static getConfigElement(){ return document.createElement('cloudems-energie-potentieel-card-editor'); }
  static getStubConfig(){ return {}; }
}

class CloudEMSEnergiePotentieelCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg=c; }
  set hass(h){}
  connectedCallback(){
    this.shadowRoot.innerHTML=`
    <div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">
      Optionele config:<br>
      <code>show_bat: true/false</code><br>
      <code>show_pv: true/false</code><br>
      <code>title: "Energie Potentieel"</code>
    </div>`;
  }
}

if(!customElements.get('cloudems-energie-potentieel-card')) customElements.define('cloudems-energie-potentieel-card', CloudEMSEnergiePotentieelCard);
if(!customElements.get('cloudems-energie-potentieel-card-editor')) customElements.define('cloudems-energie-potentieel-card-editor', CloudEMSEnergiePotentieelCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-energie-potentieel-card',name:'CloudEMS Energie Potentieel',description:'Batterij + PV als universele rekenmachine — koken, koffie, lampen, airco, douche...'});
console.info('%c CLOUDEMS-ENERGIE-POTENTIEEL %c v'+EP_VERSION+' ','background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
