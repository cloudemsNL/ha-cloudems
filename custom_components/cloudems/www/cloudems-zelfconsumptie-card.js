// CloudEMS Zelfconsumptie Card v1.1
const CARD_ZELFCONSUMPTIE_VERSION = '5.5.465';
// Leest sensor.cloudems_self_consumption en toont altijd data, ook bij unavailable

class CloudemsZelfconsumptieCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._prev=""; }
  setConfig(c){ this._cfg={title:"♻️ Zelfconsumptie",...c}; this._render(); }

  
  static getConfigElement(){return document.createElement('cloudems-zelfconsumptie-card-editor');}
  set hass(h){
    this._hass=h;
    const s=h.states["sensor.cloudems_self_consumption"];
    const j=JSON.stringify([s?.state,s?.attributes?.self_consumed_kwh,s?.attributes?.pv_today_kwh,s?.last_changed]);
    if(j!==this._prev){this._prev=j;this._render();}
  }

  _render(){
    const h=this._hass, c=this._cfg||{};
    const sh=this.shadowRoot; if(!sh) return;

    const s=h?.states["sensor.cloudems_self_consumption"];
    const state=s?.state;
    const attr=s?.attributes||{};

    const ratio   = (state!=null && state!=="unavailable" && state!=="unknown") ? parseFloat(state) : null;
    const bestH   = attr.best_solar_hour ?? null;
    const saving  = attr.monthly_saving_eur ?? null;
    const advice  = attr.advice || null;
    const pvKwh   = attr.pv_today_kwh ?? null;
    const selfKwh = attr.self_consumed_kwh ?? null;
    const expKwh  = attr.exported_kwh ?? null;

    const fmt = v => v!=null ? Math.round(v*100)/100 : "—";
    const pct  = v => v!=null ? Math.round(v)+"%" : "—";
    const euro = v => v!=null ? "€"+fmt(v) : "—";
    const kwh  = v => v!=null ? fmt(v)+" kWh" : (pvKwh > 0 ? "⏳" : "—");

    // Colour for ratio
    const col = ratio==null ? "#6b7280"
              : ratio>=70   ? "#4ade80"
              : ratio>=40   ? "#fb923c"
              : "#f87171";

    sh.innerHTML=`
<style>
  :host{display:block;width:100%;}
  .card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;
    overflow:hidden;font-family:var(--primary-font-family,sans-serif);
    transition:border-color .2s,box-shadow .2s;}
  .card:hover{border-color:rgba(0,177,64,.5);box-shadow:0 4px 20px rgba(0,0,0,.5),0 0 16px rgba(0,177,64,.12);}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;
    border-bottom:1px solid rgba(255,255,255,.07);}
  .hdr-icon{font-size:16px;}
  .hdr-title{font-size:12px;font-weight:600;letter-spacing:.04em;color:#fff;}
  .row{display:flex;align-items:center;justify-content:space-between;
    padding:9px 16px;border-bottom:1px solid rgba(255,255,255,.04);}
  .row:last-child{border-bottom:none;}
  .lbl{font-size:12px;color:rgba(163,163,163,1);}
  .val{font-size:12px;font-weight:600;color:#fff;text-align:right;max-width:60%;}
  .big{font-size:22px;font-weight:700;padding:16px;text-align:center;border-bottom:1px solid rgba(255,255,255,.04);}
  .adv{padding:10px 16px;font-size:11px;font-style:italic;color:rgba(163,163,163,.8);}
  .na{padding:16px;text-align:center;font-size:12px;color:rgba(163,163,163,.6);}
</style>
<div class="card">
  <div class="hdr">
    <span class="hdr-icon">♻️</span>
    <span class="hdr-title">${c.title||"Zelfconsumptie"}</span>
  </div>
  ${ratio!=null ? `<div class="big" style="color:${col}">${Math.round(ratio)}%</div>` : (pvKwh!=null ? `<div class="big" style="color:#6b7280">—%</div>` : `<div class="na">⏳ Nog geen data beschikbaar</div>`)}
  <div class="row"><span class="lbl">PV productie vandaag</span><span class="val">${kwh(pvKwh)}</span></div>
  <div class="row"><span class="lbl">Zelf verbruikt</span><span class="val">${kwh(selfKwh)}</span></div>
  <div class="row"><span class="lbl">Teruggeleverd</span><span class="val">${kwh(expKwh)}</span></div>
  <div class="row"><span class="lbl">Beste zonuur</span><span class="val">${bestH!=null?bestH+"h":"—"}</span></div>
  <div class="row"><span class="lbl">Besparing / maand</span><span class="val">${euro(saving)}</span></div>
  ${advice ? `<div class="adv">💡 ${advice}</div>` : ""}
</div>`;
  }

  static getConfigElement(){return document.createElement('cloudems-zelfconsumptie-card-editor');}
  static getStubConfig(){ return {title:"♻️ Zelfconsumptie"}; }
  getCardSize(){ return 5; }
}

class CloudemsZelfconsumptieCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){ this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
  .row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}
  .lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;}
  input{background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);
    border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:160px;}
</style>
<div style="padding:8px">
  <div class="row"><label class="lbl">Titel</label>
    <input name="title" value="${cfg.title||"♻️ Zelfconsumptie"}"></div>
</div>`;
    this.shadowRoot.querySelector("input").addEventListener("change", e=>{
      this._cfg={...this._cfg,title:e.target.value}; this._fire();
    });
  }
}

if (!customElements.get('cloudems-zelfconsumptie-card')) customElements.define("cloudems-zelfconsumptie-card", CloudemsZelfconsumptieCard);
if (!customElements.get('cloudems-zelfconsumptie-card-editor')) customElements.define("cloudems-zelfconsumptie-card-editor", CloudemsZelfconsumptieCardEditor);
window.customCards = window.customCards||[];
window.customCards.push({type:"cloudems-zelfconsumptie-card",name:"CloudEMS Zelfconsumptie",description:"Zelfconsumptiegraad met productie, verbruik en besparingen"});
