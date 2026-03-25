// CloudEMS Warmtebron Vergelijker Card v1.0.0 — Gas vs electricity heat cost
const CARD_WARMTEBRON_VERSION = '5.3.31';

class CloudemsWarmtebronCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._p = ""; }
  setConfig(c) { this._cfg = { title: "🔥 Verwarmingskosten", ...c }; this._r(); }
  set hass(h) {
    this._hass = h;
    const s = h.states["sensor.cloudems_goedkoopste_warmtebron"];
    if (JSON.stringify(s?.state) !== this._p) { this._p = JSON.stringify(s?.state); this._r(); }
  }
  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;
    const st   = h.states["sensor.cloudems_goedkoopste_warmtebron"];
    const attr = st?.attributes || {};
    const best = st?.state || "—";
    const gasPerKwh  = parseFloat(attr.gas_per_kwh_heat || 0);
    const elecPerKwh = parseFloat(attr.elec_boiler_per_kwh_heat || 0);
    const hpPerKwh   = parseFloat(attr.heat_pump_per_kwh_heat || 0);
    const gasPrice   = parseFloat(attr.gas_price_eur_m3 || 0);
    const elecPrice  = parseFloat(attr.electricity_price_eur_kwh || 0);
    const saving     = parseFloat(attr.saving_pct || 0);
    const isGas   = best === "gas";
    const isElec  = best === "electricity" || best === "boiler";
    const isHP    = best === "heat_pump";
    const badge = (active, label, val, col) => `
      <div style="flex:1;padding:12px 8px;text-align:center;border-radius:10px;border:2px solid ${active?col:'rgba(255,255,255,.08)'};background:${active?col+'18':'rgba(255,255,255,.03)'}">
        <div style="font-size:16px;margin-bottom:4px">${label}</div>
        <div style="font-size:15px;font-weight:700;color:${active?col:'#fff'}">${val>0?val.toFixed(1)+' ct':'—'}</div>
        <div style="font-size:9px;color:rgba(163,163,163,.5);margin-top:2px">ct/kWh warmte</div>
        ${active?`<div style="font-size:9px;font-weight:700;color:${col};margin-top:3px">✓ GOEDKOOPST</div>`:''}
      </div>`;
    sh.innerHTML = `
<style>:host{display:block;width:100%}.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}.badges{display:flex;gap:8px;padding:14px}.detail{padding:0 16px 12px}</style>
<div class="card">
  <div class="hdr"><span>🔥</span><span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span></div>
  ${!st ? `<div style="padding:16px;text-align:center;font-size:12px;color:rgba(163,163,163,.5)">Geen warmtebron-data</div>` : `
  <div class="badges">
    ${badge(isGas,  "🔥 Gas",    gasPerKwh*100,  "#fb923c")}
    ${badge(isElec, "⚡ Boiler",  elecPerKwh*100, "#60a5fa")}
    ${hpPerKwh > 0 ? badge(isHP, "🌡️ WP", hpPerKwh*100, "#4ade80") : ""}
  </div>
  <div class="detail">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:rgba(163,163,163,.6)">
      <span>⛽ Gasprijs: €${gasPrice.toFixed(3)}/m³</span>
      <span>⚡ Stroomprijs: ${(elecPrice*100).toFixed(1)} ct/kWh</span>
    </div>
    ${saving>0?`<div style="margin-top:8px;padding:6px 10px;background:rgba(74,222,128,.1);border-radius:8px;font-size:11px;color:#4ade80;text-align:center">Besparing t.o.v. duurste optie: ${saving.toFixed(0)}%</div>`:''}
  </div>`}
</div>`;
  }
  getCardSize() { return 3; }
  static getConfigElement() { return document.createElement("cloudems-warmtebron-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsWarmtebronCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-top:4px" id="t" value="${this._config?.title||'🔥 Verwarmingskosten'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-warmtebron-card')) customElements.define("cloudems-warmtebron-card",CloudemsWarmtebronCard);
if (!customElements.get('cloudems-warmtebron-card-editor')) customElements.define("cloudems-warmtebron-card-editor",CloudemsWarmtebronCardEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:"cloudems-warmtebron-card",name:"CloudEMS Verwarmingskosten Vergelijker"});
