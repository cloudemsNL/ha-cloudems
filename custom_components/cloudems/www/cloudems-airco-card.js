// CloudEMS Multi-Split Airco v5.5.465
const CARD_AIRCO_VERSION = '5.5.465';

class CloudemsAircoCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._cfg={};}
  static getConfigElement(){return document.createElement('cloudems-airco-card-editor');}
  setConfig(c){this._cfg=c||{};this._render();}
  _render(){
    var sh=this.shadowRoot;sh.innerHTML='';
    var s=document.createElement('style');s.textContent=':host{display:block;padding:12px}';
    sh.appendChild(s);
    var d=document.createElement('div');d.style.cssText='color:var(--secondary-text-color);font-size:13px';
    d.textContent='Geen configuratie nodig.';sh.appendChild(d);
  }
}
if(!customElements.get('cloudems-airco-card-editor'))customElements.define('cloudems-airco-card-editor',CloudemsAircoCardEditor);

class CloudemsAircoCard extends HTMLElement {
  set hass(h){this._hass=h;}
  setConfig(c){this._config=c;}
  getCardSize(){return 2;}
  connectedCallback(){
    if(!this.innerHTML)
      this.innerHTML=`<ha-card><div style="padding:16px;color:var(--secondary-text-color)"><p style="margin:0;font-size:13px;opacity:.7">⚙️ Multi-Split Airco — wordt geladen...</p></div></ha-card>`;
  }
}
if(!customElements.get('cloudems-airco-card'))customElements.define('cloudems-airco-card',CloudemsAircoCard);

window.customCards=window.customCards||[];
window.customCards.push({type:'cloudems-airco-card',name:'CloudEMS Multi-Split Airco',description:'Multi-Split Airco'});
