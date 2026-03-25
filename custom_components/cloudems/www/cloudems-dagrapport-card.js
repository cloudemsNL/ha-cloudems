// CloudEMS Dagrapport Card v1.0.0 — Daily energy summary
const CARD_DAGRAPPORT_VERSION = '5.3.31';

class CloudemsDagrapportCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "📊 Dagrapport", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const k = JSON.stringify([
      h.states["sensor.cloudems_self_consumption"]?.last_changed,
      h.states["sensor.cloudems_kosten_vandaag"]?.state,
      h.states["sensor.cloudems_solar_energy_today"]?.state,
    ]);
    if (k !== this._p) { this._p = k; this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const sc   = h.states["sensor.cloudems_self_consumption"]?.attributes || {};
    const _scStored = parseFloat(h.states["sensor.cloudems_self_consumption"]?.state || 0);
    // _pvLiveW eerst declareren want wordt gebruikt in _solarW en scPct
    const _pvLiveW = parseFloat(h.states["sensor.cloudems_solar_power"]?.state || h.states["sensor.cloudems_zonnepanelen"]?.state || 0);
    // Instant fallback: SC = min(solar, house) / solar wanneer tracker nog geen kWh heeft
    const _solarW = _pvLiveW;
    const _houseW = parseFloat(h.states["sensor.cloudems_house_load"]?.state || h.states["sensor.cloudems_vermogen_huis"]?.state || 0);
    const scPct = _scStored > 0 ? _scStored : (_solarW > 100 && _houseW > 0 ? Math.min(100, Math.min(_solarW, _houseW) / _solarW * 100) : 0);
    const _pvKwhStored = parseFloat(sc.pv_today_kwh || h.states["sensor.cloudems_solar_energy_today"]?.state || 0);
    const pvKwh = _pvKwhStored > 0 ? _pvKwhStored : (_pvLiveW > 100 ? _pvLiveW / 1000 : 0);
    const selfKwh = parseFloat(sc.self_consumed_kwh || 0);
    const expKwh  = parseFloat(sc.exported_kwh || 0);
    const kostSt  = h.states["sensor.cloudems_kosten_vandaag"];
    const kost    = kostSt ? parseFloat(kostSt.state || 0) : null;
    const selfSuff = parseFloat(h.states["sensor.cloudems_zelfvoorzieningsgraad"]?.state || h.states["sensor.cloudems_self_sufficiency"]?.state || 0);
    const besparing = parseFloat(sc.monthly_saving_eur || 0);
    const bestUur   = sc.best_solar_label || sc.best_solar_hour != null ? `${sc.best_solar_hour}:00` : "—";
    const advice    = sc.advice || "";
    const bar = (pct, col) => `<div style="height:4px;background:rgba(255,255,255,.1);border-radius:2px;margin-top:3px"><div style="height:4px;background:${col};border-radius:2px;width:${Math.min(100,pct)}%"></div></div>`;
    const kv = (l, v, c2="#fff") => `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)"><span style="font-size:12px;color:rgba(163,163,163,.8)">${l}</span><span style="font-size:12px;font-weight:600;color:${c2}">${v}</span></div>`;
    sh.innerHTML = `
<style>:host{display:block;width:100%}.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}.big-grid{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid rgba(255,255,255,.07)}.big-item{padding:12px 16px;text-align:center}.big-val{font-size:22px;font-weight:700}.big-lbl{font-size:10px;color:rgba(163,163,163,.5);margin-top:2px}.detail{padding:8px 16px}.advice{padding:8px 16px 12px;font-size:11px;color:rgba(163,163,163,.7);font-style:italic}</style>
<div class="card">
  <div class="hdr"><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span><span style="font-size:10px;color:rgba(163,163,163,.4)">${new Date().toLocaleDateString('nl-NL',{day:'numeric',month:'short'})}</span></div>
  <div class="big-grid">
    <div class="big-item">
      <div class="big-val" style="color:#fb923c">${pvKwh.toFixed(1)}<span style="font-size:12px;font-weight:400"> kWh</span></div>
      <div class="big-lbl">☀️ PV vandaag</div>
    </div>
    <div class="big-item">
      <div class="big-val" style="color:${scPct>=60?'#4ade80':scPct>=30?'#fbbf24':'#f87171'}">${scPct.toFixed(0)}<span style="font-size:12px;font-weight:400">%</span></div>
      <div class="big-lbl">♻️ Zelfconsumptie</div>
      ${bar(scPct, scPct>=60?'#4ade80':scPct>=30?'#fbbf24':'#f87171')}
    </div>
    ${selfSuff > 0 ? `<div class="big-item">
      <div class="big-val" style="color:#60a5fa">${selfSuff.toFixed(0)}<span style="font-size:12px;font-weight:400">%</span></div>
      <div class="big-lbl">🏠 Zelfvoorzienend</div>
      ${bar(selfSuff,'#60a5fa')}
    </div>` : ""}
    ${kost !== null ? `<div class="big-item">
      <div class="big-val" style="color:${kost<0?'#4ade80':kost<2?'#fbbf24':'#f87171'}">${kost<0?'':''}€${Math.abs(kost).toFixed(2)}</div>
      <div class="big-lbl">${kost<0?'💰 Verdiend':'💸 Kosten'} vandaag</div>
    </div>` : ""}
  </div>
  <div class="detail">
    ${kv('Zelf verbruikt', selfKwh>0?selfKwh.toFixed(2)+' kWh':'—', '#4ade80')}
    ${kv('Teruggeleverd', expKwh>0?expKwh.toFixed(2)+' kWh':'—', '#60a5fa')}
    ${kv('Beste zonuur', bestUur, '#fbbf24')}
    ${besparing>0?kv('Besparing/maand (schatting)', '€'+besparing.toFixed(2), '#4ade80'):''}
  </div>
  ${advice?`<div class="advice">💡 ${advice}</div>`:''}
</div>`;
  }
  getCardSize() { return 4; }
  static getConfigElement() { return document.createElement("cloudems-dagrapport-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsDagrapportCardEditor extends HTMLElement {
  setConfig(c) { this._config=c; this._r(); }
  _r() { if(!this.shadowRoot)this.attachShadow({mode:"open"}); this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'📊 Dagrapport'}"/>`; this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}}))); }
}
if (!customElements.get('cloudems-dagrapport-card')) customElements.define("cloudems-dagrapport-card", CloudemsDagrapportCard);
if (!customElements.get('cloudems-dagrapport-card-editor')) customElements.define("cloudems-dagrapport-card-editor", CloudemsDagrapportCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:"cloudems-dagrapport-card",name:"CloudEMS Dagrapport"});
