// cloudems-apparaat-tabs-card — tab-wrapper v5.5.183
const CLOUDEMS_APPARAAT_TABS_CARD_VERSION = "5.5.318";

class CloudEMSApparaatTabsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._tab = 'tijdlijn';
    this._cards = {};
    this._hass = null;
    this._ready = false;
    this._setting = false;
    this._tabs = [
    {id:'tijdlijn', label:'📅 Tijdlijn', type:'custom:cloudems-apparaat-tijdlijn-card'},
    {id:'apparaten', label:'🔌 Apparaten', type:'custom:cloudems-appliance-card'},
    {id:'levensduur', label:'⏳ Levensduur', type:'custom:cloudems-lifecycle-card'}
    ];
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(h) {
    this._hass = h;
    // Geef hass door aan alle al gecreëerde child cards
    Object.values(this._cards).forEach(c => { if (c && c.hass !== undefined) try { c.hass = h; } catch(e) {} });
    if (!this._ready) {
      this._setup();
    } else {
      this._updateView();
    }
  }

  async _setup() {
    if (this._setting) return;
    this._setting = true;

    const sh = this.shadowRoot;
    sh.innerHTML = `
      <style>
        :host { display: block }
        .tab-bar {
          display: flex; background: rgba(255,255,255,.05);
          border-radius: 10px 10px 0 0; padding: 4px 4px 0;
          border-bottom: 1px solid rgba(255,255,255,.08);
        }
        .tab {
          padding: 7px 16px; font-size: 12px; font-weight: 600;
          border-radius: 8px 8px 0 0; cursor: pointer; color: #475569;
          transition: all .15s; user-select: none; letter-spacing: .3px;
        }
        .tab.active { background: rgba(255,255,255,.08); color: #f1f5f9; }
      </style>
      <div id="shell">
        <div class="tab-bar">
            <div class='tab' id='tab-tijdlijn' data-tab='tijdlijn'>📅 Tijdlijn</div>
            <div class='tab' id='tab-apparaten' data-tab='apparaten'>🔌 Apparaten</div>
            <div class='tab' id='tab-levensduur' data-tab='levensduur'>⏳ Levensduur</div>
        </div>
            <div id='slot-tijdlijn'></div>
            <div id='slot-apparaten'></div>
            <div id='slot-levensduur'></div>
      </div>`;

    // Tab click handlers
    this._tabs.forEach(t => {
      const el = sh.getElementById('tab-' + t.id);
      if (el) el.addEventListener('click', () => this._switch(t.id));
    });

    // Maak child cards via HA helpers — dit is de correcte HA-manier
    try {
      const helpers = await window.loadCardHelpers();
      for (const t of this._tabs) {
        try {
          const card = await helpers.createCardElement({ type: t.type });
          if (this._hass) card.hass = this._hass;
          this._cards[t.id] = card;
          const slot = sh.getElementById('slot-' + t.id);
          if (slot) slot.appendChild(card);
        } catch(e) {
          console.warn('[CloudEMS tabs] Kon ' + t.type + ' niet laden:', e);
        }
      }
    } catch(e) {
      console.warn('[CloudEMS tabs] loadCardHelpers mislukt:', e);
    }

    this._ready = true;
    this._updateView();
  }

  _updateView() {
    const sh = this.shadowRoot;
    const tab = this._tab;
    this._tabs.forEach(t => {
      const tabEl  = sh.getElementById('tab-' + t.id);
      const slotEl = sh.getElementById('slot-' + t.id);
      if (tabEl)  tabEl.className  = 'tab' + (t.id === tab ? ' active' : '');
      if (slotEl) slotEl.style.display = t.id === tab ? 'block' : 'none';
    });
  }

  _switch(tab) {
    this._tab = tab;
    // Trigger hass update op nu zichtbare card
    if (this._cards[tab] && this._hass) {
      try { this._cards[tab].hass = this._hass; } catch(e) {}
    }
    this._updateView();
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-apparaat-tabs-card'))
  customElements.define('cloudems-apparaat-tabs-card', CloudEMSApparaatTabsCard);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-apparaat-tabs-card'))
  window.customCards.push({ type: 'cloudems-apparaat-tabs-card', name: 'CloudEMSApparaatTabsCard' });
console.info(`%c CLOUDEMS-APPARAAT-TABS-CARD %c v${CLOUDEMS_APPARAAT_TABS_CARD_VERSION} `, 'background:#60a5fa;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px', 'background:#0d1117;color:#60a5fa;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0');
