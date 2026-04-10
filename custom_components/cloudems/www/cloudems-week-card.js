// CloudEMS Week Overzicht Kaart v1.0
// Toont batterij prestaties per dag van de afgelopen week
// Leest van sensor.cloudems_battery_savings + sensor.cloudems_battery_schedule

class CloudEMSWeekCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  setConfig(c) { this._config = c || {}; }
  
  static getConfigElement(){return document.createElement('cloudems-week-card-editor');}
  set hass(h) { this._hass = h; this._render(); }

  _render() {
    if (!this._hass) return;
    const sav = this._hass.states['sensor.cloudems_battery_savings'];
    const sch = this._hass.states['sensor.cloudems_battery_schedule']
             || this._hass.states['sensor.cloudems_batterij_epex_schema'];
    const savA = sav?.attributes || {};
    const history = savA.daily_history || savA.history || [];
    const statusSt = this._hass.states['sensor.cloudems_status'];
    const co2 = statusSt?.attributes?.co2_saved_today_kg;
    const co2label = statusSt?.attributes?.co2_label;

    // Bouw 7-daagse weergave
    const days = ['Ma','Di','Wo','Do','Vr','Za','Zo'];
    const today = new Date().getDay(); // 0=zo
    const todayIdx = (today + 6) % 7;  // 0=ma

    const bars = Array.from({length:7}, (_, i) => {
      const d = history[history.length - 7 + i] || null;
      return {
        label: days[(todayIdx - 6 + i + 7) % 7],
        isToday: i === 6,
        charge_kwh:    d?.charge_kwh    ?? 0,
        discharge_kwh: d?.discharge_kwh ?? 0,
        saving_eur:    d?.saving_eur    ?? d?.savings_eur ?? 0,
        cycles:        d?.cycles        ?? 0,
      };
    });

    const maxKwh = Math.max(...bars.map(b => Math.max(b.charge_kwh, b.discharge_kwh)), 0.1);

    const totalSaving = bars.reduce((s,b) => s + (b.saving_eur||0), 0);
    const totalCharge = bars.reduce((s,b) => s + (b.charge_kwh||0), 0);
    const totalDisch  = bars.reduce((s,b) => s + (b.discharge_kwh||0), 0);

    const barsHtml = bars.map(b => {
      const chH = Math.round((b.charge_kwh / maxKwh) * 80);
      const diH = Math.round((b.discharge_kwh / maxKwh) * 80);
      return `
        <div style="display:flex;flex-direction:column;align-items:center;gap:3px;flex:1">
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#475569">
            ${b.saving_eur > 0 ? '+€'+b.saving_eur.toFixed(2) : ''}
          </div>
          <div style="height:80px;display:flex;align-items:flex-end;gap:2px">
            <div title="Geladen ${b.charge_kwh.toFixed(1)} kWh" style="width:10px;height:${chH}px;background:#10b981;border-radius:2px 2px 0 0;min-height:${b.charge_kwh>0?2:0}px"></div>
            <div title="Ontladen ${b.discharge_kwh.toFixed(1)} kWh" style="width:10px;height:${diH}px;background:#f97316;border-radius:2px 2px 0 0;min-height:${b.discharge_kwh>0?2:0}px"></div>
          </div>
          <div style="font-size:10px;font-weight:${b.isToday?700:400};color:${b.isToday?'#f59e0b':'#475569'}">${b.label}</div>
          ${b.isToday?'<div style="width:4px;height:4px;border-radius:50%;background:#f59e0b;margin-top:1px"></div>':''}
        </div>`;
    }).join('');

    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}
        ha-card{background:#0d1117;border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:'Inter',ui-sans-serif,sans-serif;color:#cbd5e1;padding:16px 20px}
      </style>
      <ha-card>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <div style="font-size:18px">📊</div>
          <div style="font-size:13px;font-weight:700;color:#f1f5f9;flex:1">Week overzicht batterij</div>
          ${co2!=null?`<div style="font-size:10px;color:#10b981">🌿 ${co2}kg CO₂ bespaard ${co2label||''}</div>`:''}
        </div>

        <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
          <div style="background:#0a1a10;border-radius:8px;padding:8px 12px">
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:#10b981">+€${totalSaving.toFixed(2)}</div>
            <div style="font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-top:2px">Bespaard week</div>
          </div>
          <div style="background:#0a1210;border-radius:8px;padding:8px 12px">
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:#10b981">⚡ ${totalCharge.toFixed(1)} kWh</div>
            <div style="font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-top:2px">Geladen</div>
          </div>
          <div style="background:#1a0f0a;border-radius:8px;padding:8px 12px">
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:#f97316">↓ ${totalDisch.toFixed(1)} kWh</div>
            <div style="font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-top:2px">Ontladen</div>
          </div>
        </div>

        <div style="display:flex;gap:4px;align-items:flex-end;padding:0 4px">${barsHtml}</div>

        <div style="display:flex;gap:12px;margin-top:10px;font-size:9px;color:#374151">
          <span><span style="display:inline-block;width:8px;height:8px;background:#10b981;border-radius:1px;margin-right:3px"></span>Geladen</span>
          <span><span style="display:inline-block;width:8px;height:8px;background:#f97316;border-radius:1px;margin-right:3px"></span>Ontladen</span>
        </div>
      </ha-card>`;
  }

  static getStubConfig() { return {}; }
}
customElements.define('cloudems-week-card', CloudEMSWeekCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-week-card'))
  window.customCards.push({ type:'cloudems-week-card', name:'CloudEMS Week Overzicht' });


class CloudemsWeekCardEditor extends HTMLElement{
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
if(!customElements.get('cloudems-week-card-editor'))customElements.define('cloudems-week-card-editor',CloudemsWeekCardEditor);
if(!customElements.get('cloudems-week-card-editor'))customElements.define('cloudems-week-card-editor',CloudemsWeekCardEditor);
