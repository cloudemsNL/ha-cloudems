// CloudEMS neighbourhood Card v1.0.0
const CARD_NEIGHBOURHOOD_VERSION = '5.4.1';
class CloudemsCardneighbourhood extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); this._p=""; }
  setConfig(c){ this._cfg={title:"CloudEMS neighbourhood",  ...c}; this._r(); }
  set hass(h){ this._h=h; const s=h.states["sensor.cloudems_neighbourhood"]; const j=JSON.stringify([s?.state,s?.last_changed]); if(j!==this._p){this._p=j;this._r();} }
  _r(){
    const h=this._h,c=this._cfg||{},sh=this.shadowRoot; if(!sh||!h)return;
    const attr=h.states["sensor.cloudems_neighbourhood"]?.attributes||{};
    const state=h.states["sensor.cloudems_neighbourhood"]?.state||"—";
    sh.innerHTML=`<style>:host{display:block;width:100%}.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:16px;font-family:var(--primary-font-family,sans-serif)}.t{font-size:12px;font-weight:600;color:#fff;margin-bottom:8px}.s{font-size:20px;font-weight:700;color:#fbbf24}.info{font-size:11px;color:rgba(163,163,163,.7);margin-top:6px}</style>
<div class="card"><div class="t">${c.title}</div><div class="s">${state}</div><div class="info">${JSON.stringify(attr).slice(0,200)}</div></div>`;
  }
  getCardSize(){return 2;}
  static getConfigElement(){return document.createElement("cloudems-neighbourhood-card-editor");}
  static getStubConfig(){return {};}
}
class CloudemsCardneighbourhoodEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Title</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||""}" />`;
  this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-neighbourhood-card')) customElements.define("cloudems-neighbourhood-card",CloudemsCardneighbourhood);
if (!customElements.get('cloudems-neighbourhood-card-editor')) customElements.define("cloudems-neighbourhood-card-editor",CloudemsCardneighbourhoodEditor);
window.customCards=window.customCards||[];
window.customCards.push({type:"cloudems-neighbourhood-card",name:"CloudEMS neighbourhood"});
