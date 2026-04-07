// CloudEMS Kosten Calculator Card v5.5.6
const KC_VERSION = "5.5.318";

class CloudEMSKostenCalculatorCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={title:'Energie Kosten',...c}; }

  set hass(h){
    this._hass=h;
    const price  = h?.states['sensor.cloudems_price_current_hour'];
    const cost   = h?.states['sensor.cloudems_energy_cost'];
    const solar  = h?.states['sensor.cloudems_solar_system'];
    const sc     = h?.states['sensor.cloudems_self_consumption'];
    const wcomp  = h?.states['sensor.cloudems_weekly_comparison'];
    const dagk   = h?.states['sensor.cloudems_dagkosten_stroom'];

    const cur_price  = parseFloat(price?.state||0.25)||0.25;
    const today_eur  = parseFloat(dagk?.state||0)||0;
    const sc_pct     = parseFloat(sc?.state||0)||0;
    const pv_today   = parseFloat(solar?.attributes?.pv_today_kwh||0)||0;
    const this_week  = parseFloat(wcomp?.state||0)||0;
    const last_week  = parseFloat(wcomp?.attributes?.last_week_kwh||0)||0;
    const week_eur   = parseFloat(wcomp?.attributes?.this_week_eur||0)||0;
    const month_eur  = parseFloat(cost?.attributes?.month_eur||0)||0;
    const year_eur   = parseFloat(cost?.attributes?.year_eur||0)||0;
    const saved_today= parseFloat(solar?.attributes?.saved_eur||0)||parseFloat(cost?.attributes?.solar_saved_today||0)||0;

    const sig=[today_eur,cur_price,sc_pct,month_eur].join('|');
    if(sig===this._prev)return;
    this._prev=sig;
    this._render(cur_price,today_eur,saved_today,pv_today,sc_pct,this_week,last_week,week_eur,month_eur,year_eur);
  }

  _render(price,today,saved,pv_today,sc_pct,this_w,last_w,week_eur,month_eur,year_eur){
    const sh=this.shadowRoot;
    const f2=n=>'€'+Math.abs(n).toFixed(2);
    const fw=n=>n>=1000?f2(n/1000).replace('€','€')+'k':f2(n);
    const priceCol=price<0.10?'#4ade80':price<0.25?'#fbbf24':price>0.40?'#f87171':'#e2e8f0';
    const weekDiff=this_w-last_w;
    const weekCol=weekDiff<=0?'#4ade80':'#fb923c';
    const todayCol=today<0.5?'#4ade80':today<2?'#e2e8f0':'#fb923c';

    sh.innerHTML=`
    <style>
      :host{display:block}
      .card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:14px 16px;font-family:var(--primary-font-family,sans-serif)}
      .hdr{font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:14px}
      .grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
      .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px}
      .tile{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:9px;padding:10px 12px}
      .tile-label{font-size:10px;color:#64748b;margin-bottom:4px;letter-spacing:.3px}
      .tile-val{font-size:18px;font-weight:700;font-family:monospace;line-height:1.2}
      .tile-sub{font-size:10px;color:#475569;margin-top:3px}
      .row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:12px}
      .row:last-child{border:none}
      .row-lbl{color:#94a3b8}
      .row-val{font-family:monospace;font-weight:600;color:#e2e8f0}
      .sep{height:1px;background:rgba(255,255,255,0.05);margin:10px 0}
    </style>
    <div class="card">
      <div class="hdr">${this._cfg.title}</div>
      <div class="grid2">
        <div class="tile">
          <div class="tile-label">Huidig tarief</div>
          <div class="tile-val" style="color:${priceCol}">€${price.toFixed(3)}</div>
          <div class="tile-sub">per kWh incl. belasting</div>
        </div>
        <div class="tile">
          <div class="tile-label">Kosten vandaag</div>
          <div class="tile-val" style="color:${todayCol}">€${today.toFixed(2)}</div>
          <div class="tile-sub">${saved>0?'Bespaard via PV: €'+saved.toFixed(2):sc_pct>0?'Zelfconsumptie: '+sc_pct.toFixed(0)+'%':''}</div>
        </div>
      </div>
      <div class="grid3">
        <div class="tile">
          <div class="tile-label">Deze week</div>
          <div class="tile-val" style="font-size:15px;color:#e2e8f0">€${week_eur.toFixed(2)}</div>
          <div class="tile-sub" style="color:${weekCol}">${weekDiff>=0?'+':''}${weekDiff.toFixed(1)} kWh vs vorige</div>
        </div>
        <div class="tile">
          <div class="tile-label">Deze maand</div>
          <div class="tile-val" style="font-size:15px;color:#e2e8f0">€${month_eur.toFixed(2)}</div>
          <div class="tile-sub">~ €${(month_eur/new Date().getDate()).toFixed(2)}/dag</div>
        </div>
        <div class="tile">
          <div class="tile-label">Dit jaar</div>
          <div class="tile-val" style="font-size:15px;color:#e2e8f0">€${year_eur.toFixed(0)}</div>
          <div class="tile-sub">~ €${(year_eur/12).toFixed(0)}/mnd</div>
        </div>
      </div>
      ${pv_today>0?`
      <div class="sep"></div>
      <div class="row"><span class="row-lbl">☀️ PV geproduceerd vandaag</span><span class="row-val">${pv_today.toFixed(2)} kWh</span></div>
      <div class="row"><span class="row-lbl">♻️ Zelfconsumptie</span><span class="row-val">${sc_pct.toFixed(0)}%</span></div>
      `:''}
    </div>`;
  }
  getCardSize(){ return 3; }
  static getConfigElement(){ return document.createElement('cloudems-kosten-calculator-card-editor'); }
  static getStubConfig(){ return {}; }
}
class CloudEMSKostenCalculatorCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){}
  set hass(h){}
  connectedCallback(){ this.shadowRoot.innerHTML=`<div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">Geen configuratie nodig.</div>`; }
}
if(!customElements.get('cloudems-kosten-calculator-card')) customElements.define('cloudems-kosten-calculator-card', CloudEMSKostenCalculatorCard);
if(!customElements.get('cloudems-kosten-calculator-card-editor')) customElements.define('cloudems-kosten-calculator-card-editor', CloudEMSKostenCalculatorCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-kosten-calculator-card',name:'CloudEMS Kosten Calculator',description:'Huidig tarief, vandaag/week/maand/jaar kosten, PV besparing'});
console.info('%c CLOUDEMS-KOSTEN %c v'+KC_VERSION+' ','background:#a78bfa;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#a78bfa;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
