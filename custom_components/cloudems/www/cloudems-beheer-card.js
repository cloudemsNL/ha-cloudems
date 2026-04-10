// CloudEMS Beheer Card v5.5.465 — vervangen door cloudems-config-card
// Stub om compatibiliteit te behouden
class CloudemsBeheerCard extends HTMLElement {
  setConfig(c) { this._cfg = c; }
  
  static getConfigElement(){return document.createElement('cloudems-beheer-card-editor');}
  set hass(h) { if (!this._built) { this._built=true; this.innerHTML=`<ha-card style="padding:12px;opacity:.6"><p style="margin:0;font-size:13px">⚙️ Beheer-kaart is vervangen door de Config-kaart. Verwijder deze kaart uit je dashboard.</p></ha-card>`; } }
  static getConfigElement(){return document.createElement('cloudems-beheer-card-editor');}
  static getStubConfig() { return {}; }
}



class CloudemsBeheerCardEditor extends HTMLElement{
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
if(!customElements.get('cloudems-beheer-card-editor'))customElements.define('cloudems-beheer-card-editor',CloudemsBeheerCardEditor);
if(!customElements.get('cloudems-beheer-card-editor'))customElements.define('cloudems-beheer-card-editor',CloudemsBeheerCardEditor);

if (!customElements.get('cloudems-beheer-card')) customElements.define('cloudems-beheer-card', CloudemsBeheerCard);
