// CloudEMS Beheer Card v1.0.0 — vervangen door cloudems-config-card
// Stub om compatibiliteit te behouden
class CloudemsBeheerCard extends HTMLElement {
  setConfig(c) { this._cfg = c; }
  set hass(h) { if (!this._built) { this._built=true; this.innerHTML=`<ha-card style="padding:12px;opacity:.6"><p style="margin:0;font-size:13px">⚙️ Beheer-kaart is vervangen door de Config-kaart. Verwijder deze kaart uit je dashboard.</p></ha-card>`; } }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return {}; }
}
if (!customElements.get('cloudems-beheer-card')) customElements.define('cloudems-beheer-card', CloudemsBeheerCard);
