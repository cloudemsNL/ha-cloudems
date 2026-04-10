// CloudEMS Off-Grid Survival Calculator v5.5.465
const OG_VERSION = "5.5.465";

class CloudEMSOffgridCard extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){ this._cfg={title:'Off-Grid Overleving',house_avg_w:500,...c}; }

  set hass(h){
    this._hass=h;
    const bat    = h?.states['sensor.cloudems_battery_so_c'];
    const pv     = h?.states['sensor.cloudems_pv_forecast_today'];
    const solar  = h?.states['sensor.cloudems_solar_system'];
    const home   = h?.states['sensor.cloudems_home_rest'];

    const soc_pct   = parseFloat(bat?.state||0)||0;
    const cap_kwh   = parseFloat(bat?.attributes?.capacity_kwh||10)||10;
    const bat_kwh   = cap_kwh * soc_pct / 100;
    const solar_w   = parseFloat(solar?.state||0)||0;
    const pv_today  = parseFloat(pv?.state||0)||0;
    const pv_done   = parseFloat(solar?.attributes?.pv_today_kwh||0)||0;
    const pv_remain = Math.max(0, pv_today - pv_done);
    const house_w   = parseFloat(home?.state||0)||this._cfg.house_avg_w;

    // Geleerd forecast van HouseConsumptionLearner
    const forecast   = home?.attributes?.remaining_kwh   ?? null;
    const consumed   = home?.attributes?.consumed_kwh    ?? null;
    const total_exp  = home?.attributes?.total_kwh       ?? null;
    const survival   = home?.attributes?.survival        ?? null;
    const learnerSt  = home?.attributes?.learner_status  ?? null;

    const sig=[soc_pct,solar_w,pv_remain,house_w,forecast].join('|');
    if(sig===this._prev)return;
    this._prev=sig;
    this._render(bat_kwh,soc_pct,cap_kwh,solar_w,pv_remain,house_w,forecast,consumed,total_exp,survival,learnerSt);
  }

  _render(bat_kwh,soc_pct,cap_kwh,solar_w,pv_remain,house_w,forecast,consumed,total_exp,survival,learnerSt){
    const sh=this.shadowRoot;
    // Net consumption (house minus solar currently producing)
    const net_w = Math.max(0, house_w - solar_w);
    // Hours on battery alone (no solar)
    const hrs_bat_only = net_w > 0 ? bat_kwh / (net_w/1000) : 999;
    // Hours including remaining PV today
    const total_kwh = bat_kwh + pv_remain;
    const hrs_with_pv = net_w > 0 ? total_kwh / (net_w/1000) : 999;

    // Survival scenarios
    const scenarios = [
      {label:'Alleen essentieel', w:200,  icon:'💡', desc:'verlichting + koelkast + telefoon'},
      {label:'Normaal thuis',     w:house_w||500, icon:'🏠', desc:'huidig verbruikspatroon'},
      {label:'Met airco',         w:(house_w||500)+1500, icon:'❄️', desc:'+ klimaatregeling'},
      {label:'Met EV laden',      w:(house_w||500)+3700, icon:'🚗', desc:'+ 3.7kW EV laden'},
    ];

    const bars = scenarios.map(sc=>{
      const h_bat = sc.w>0 ? bat_kwh/(sc.w/1000) : 999;
      const h_tot = sc.w>0 ? total_kwh/(sc.w/1000) : 999;
      const pct_bat = Math.min(100, h_bat/24*100);
      const pct_pv  = Math.min(100, Math.max(0,(h_tot-h_bat)/24*100));
      const col = h_bat>=8?'#4ade80':h_bat>=4?'#fbbf24':'#f87171';
      const fmtH = h=>h>=24?'24h+':h>=1?h.toFixed(1)+'u':(h*60).toFixed(0)+'min';
      return `
        <div class="sc-row">
          <div class="sc-left">
            <span class="sc-icon">${sc.icon}</span>
            <div>
              <div class="sc-label">${sc.label}</div>
              <div class="sc-desc">${sc.desc} · ${(sc.w/1000).toFixed(1)}kW</div>
            </div>
          </div>
          <div class="sc-right">
            <div class="sc-bar-wrap">
              <div class="sc-bar-bg">
                <div class="sc-bar-bat" style="width:${pct_bat}%;background:${col}"></div>
                <div class="sc-bar-pv"  style="width:${pct_pv}%;left:${pct_bat}%;background:rgba(251,191,36,.35)"></div>
              </div>
              <div class="sc-time" style="color:${col}">${fmtH(h_bat)}</div>
              ${h_tot>h_bat?`<div class="sc-time-pv">+${fmtH(h_tot-h_bat)} ☀️</div>`:''}
            </div>
          </div>
        </div>`;
    }).join('');

    sh.innerHTML=`
    <style>
      :host{display:block}
      .card{background:var(--ha-card-background,#1c1c1c);border-radius:12px;border:1px solid rgba(255,255,255,0.06);padding:14px 16px;font-family:var(--primary-font-family,sans-serif)}
      .hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
      .title{font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#64748b}
      .bat-pill{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.25);border-radius:20px;padding:3px 10px;font-size:11px;font-weight:700;color:#4ade80;font-family:monospace}
      .sc-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
      .sc-row:last-child{border:none}
      .sc-left{display:flex;align-items:center;gap:8px;width:185px;flex-shrink:0}
      .sc-icon{font-size:18px;width:24px;text-align:center}
      .sc-label{font-size:12px;font-weight:600;color:#e2e8f0}
      .sc-desc{font-size:10px;color:#475569;margin-top:1px}
      .sc-right{flex:1}
      .sc-bar-wrap{display:flex;align-items:center;gap:8px}
      .sc-bar-bg{flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;position:relative;overflow:hidden}
      .sc-bar-bat{position:absolute;left:0;top:0;height:100%;border-radius:4px;transition:width .5s}
      .sc-bar-pv{position:absolute;top:0;height:100%;border-radius:0 4px 4px 0;transition:width .5s}
      .sc-time{font-size:12px;font-weight:700;font-family:monospace;width:44px;text-align:right;flex-shrink:0}
      .sc-time-pv{font-size:10px;color:#fbbf24;width:52px;flex-shrink:0}
      .legend{display:flex;gap:16px;margin-top:10px;justify-content:center}
      .leg-item{display:flex;align-items:center;gap:5px;font-size:10px;color:#475569}
      .leg-dot{width:10px;height:10px;border-radius:2px}
    </style>
    <div class="card">
      <div class="hdr">
        <span class="title">${this._cfg.title}</span>
        <span class="bat-pill">🔋 ${soc_pct.toFixed(0)}% · ${bat_kwh.toFixed(1)}kWh</span>
      </div>
      ${bars}
      ${survival ? `
      <div style="margin-top:12px;background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.2);border-radius:8px;padding:10px 14px">
        <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#60a5fa;margin-bottom:8px">
          🧠 Geleerd verbruikspatroon ${learnerSt ? '· '+learnerSt.learn_pct+'% compleet' : ''}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
          <div>
            <div style="font-size:10px;color:#64748b;margin-bottom:2px">Verwacht vandaag</div>
            <div style="font-size:15px;font-weight:700;font-family:monospace;color:#e2e8f0">${total_exp ? total_exp.toFixed(1)+' kWh' : '—'}</div>
            <div style="font-size:10px;color:#475569">${consumed ? consumed.toFixed(1)+' kWh al verbruikt' : ''}</div>
          </div>
          <div>
            <div style="font-size:10px;color:#64748b;margin-bottom:2px">Nog nodig vandaag</div>
            <div style="font-size:15px;font-weight:700;font-family:monospace;color:#fbbf24">${forecast ? forecast.toFixed(1)+' kWh' : '—'}</div>
            <div style="font-size:10px;color:#475569">rest van dag</div>
          </div>
          <div>
            <div style="font-size:10px;color:#64748b;margin-bottom:2px">Autonoom tot</div>
            <div style="font-size:15px;font-weight:700;font-family:monospace;color:${survival.hours>=8?'#4ade80':survival.hours>=4?'#fbbf24':'#f87171'}">${survival.until_time || '—'}</div>
            <div style="font-size:10px;color:#475569">${survival.hours ? survival.hours.toFixed(1)+' uur op geleerd patroon' : ''}</div>
          </div>
        </div>
      </div>` : ''}
      <div class="legend">
        <div class="leg-item"><div class="leg-dot" style="background:#4ade80"></div>Batterij</div>
        <div class="leg-item"><div class="leg-dot" style="background:rgba(251,191,36,.5)"></div>PV vandaag nog</div>
        <div class="leg-item" style="color:#475569">24u balk = 1 dag</div>
      </div>
    </div>`;
  }
  getCardSize(){ return 3; }
  static getConfigElement(){ return document.createElement('cloudems-offgrid-card-editor'); }
  static getStubConfig(){ return {}; }
}
class CloudEMSOffgridCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); }
  setConfig(c){}
  set hass(h){}
  connectedCallback(){ this.shadowRoot.innerHTML=`<div style="padding:8px;font-size:12px;color:var(--secondary-text-color)">Optioneel: <code>house_avg_w: 500</code></div>`; }
}
if(!customElements.get('cloudems-offgrid-card')) customElements.define('cloudems-offgrid-card', CloudEMSOffgridCard);
if(!customElements.get('cloudems-offgrid-card-editor')) customElements.define('cloudems-offgrid-card-editor', CloudEMSOffgridCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-offgrid-card',name:'CloudEMS Off-Grid Survival',description:'Hoeveel uur ben je autonoom op batterij + zon bij verschillende verbruiksscenarios'});
console.info('%c CLOUDEMS-OFFGRID %c v'+OG_VERSION+' ','background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px','background:#0e1520;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
