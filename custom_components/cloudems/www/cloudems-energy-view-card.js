// CloudEMS Energy View Card — flow + sankey gecombineerd met tabs
// Flow card (cloudems-cards.js) en Sankey card worden als child elements gebruikt
const EV_CARD_VERSION = "5.5.318";

class CloudEMSEnergyViewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._tab = 'flow';
    this._flowCard   = null;
    this._sankeyCard = null;
  }

  setConfig(config) {
    this._config = config || {};

    // Maak child cards aan als die nog niet bestaan
    if (!this._flowCard) {
      this._flowCard = document.createElement('cloudems-flow-card');
      if (this._flowCard.setConfig) this._flowCard.setConfig(config);
    }
    if (!this._sankeyCard) {
      this._sankeyCard = document.createElement('cloudems-sankey-card');
      if (this._sankeyCard.setConfig) this._sankeyCard.setConfig({ max_ampere: config.max_ampere });
    }
  }

  set hass(h) {
    this._hass = h;
    // Geef hass door aan beide child cards — ook de verborgen kaart blijft up-to-date
    if (this._flowCard)   this._flowCard.hass   = h;
    if (this._sankeyCard) this._sankeyCard.hass  = h;
    this._renderShell();
  }

  _renderShell() {
    const tab = this._tab;
    const sh  = this.shadowRoot;

    // Schrijf de shell maar één keer — daarna alleen visibility aanpassen
    if (!sh.getElementById('shell')) {
      sh.innerHTML = `
        <style>
          :host { display: block }
          #shell { position: relative }
          .tab-bar {
            display: flex; gap: 0; margin-bottom: 0;
            background: rgba(255,255,255,.05); border-radius: 10px 10px 0 0;
            padding: 4px 4px 0; border-bottom: 1px solid rgba(255,255,255,.08);
          }
          .tab {
            padding: 7px 20px; font-size: 12px; font-weight: 600;
            border-radius: 8px 8px 0 0; cursor: pointer; color: #475569;
            transition: all .15s; user-select: none; letter-spacing: .3px;
          }
          .tab.active { background: rgba(255,255,255,.08); color: #f1f5f9; }
          #flow-slot, #sankey-slot { display: block }
        </style>
        <div id="shell">
          <div class="tab-bar">
            <div class="tab" id="tab-flow">⚡ Stroom</div>
            <div class="tab" id="tab-sankey">〰 Sankey</div>
          </div>
          <div id="flow-slot"></div>
          <div id="sankey-slot"></div>
        </div>`;

      // Mount child cards in their slots
      sh.getElementById('flow-slot').appendChild(this._flowCard);
      sh.getElementById('sankey-slot').appendChild(this._sankeyCard);

      // Tab click handlers
      sh.getElementById('tab-flow').addEventListener('click', () => this._switchTab('flow'));
      sh.getElementById('tab-sankey').addEventListener('click', () => this._switchTab('sankey'));
    }

    // Update tab state en visibility
    sh.getElementById('tab-flow').className   = 'tab' + (tab === 'flow'   ? ' active' : '');
    sh.getElementById('tab-sankey').className = 'tab' + (tab === 'sankey' ? ' active' : '');
    sh.getElementById('flow-slot').style.display   = tab === 'flow'   ? 'block' : 'none';
    sh.getElementById('sankey-slot').style.display = tab === 'sankey' ? 'block' : 'none';
  }

  _switchTab(tab) {
    this._tab = tab;
    this._renderShell();
    // Re-trigger hass setter op de nu zichtbare kaart zodat die direct rendert
    if (this._hass) {
      if (tab === 'flow'   && this._flowCard)   this._flowCard.hass   = this._hass;
      if (tab === 'sankey' && this._sankeyCard) this._sankeyCard.hass = this._hass;
    }
  }

  getCardSize() { return 6; }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-energy-view-card'))
  customElements.define('cloudems-energy-view-card', CloudEMSEnergyViewCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-energy-view-card'))
  window.customCards.push({ type: 'cloudems-energy-view-card', name: 'CloudEMS Energy View (Flow + Sankey)' });
console.info(`%c CLOUDEMS-ENERGY-VIEW %c v${EV_CARD_VERSION} `, 'background:#60a5fa;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0d1117;color:#60a5fa;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
