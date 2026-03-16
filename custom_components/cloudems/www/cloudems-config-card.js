/**
 * CloudEMS Config Card — cloudems-config-card
 * Version: 1.1.0
 *
 * Module toggles + Leerdata beheer met bevestigingsdialoog
 */

class CloudEMSConfigCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = {};
    this._confirm = null;
    this._prev = '';
  }

  setConfig(c) { this._config = c || {}; }

  set hass(h) {
    this._hass = h;
    this._render();
  }

  _s(e) { return this._hass?.states?.[e] || null; }
  _on(e) { return this._s(e)?.state === 'on'; }
  _avail(e) { return this._s(e) !== null; }

  _render() {
    if (!this._hass) return;

    const states = Object.entries(this._hass.states)
      .filter(([k]) => k.startsWith('switch.cloudems_module') || k.startsWith('switch.cloudems_zonneplan') || k === 'switch.cloudems_slaapstand_actief')
      .map(([k, v]) => `${k}:${v.state}`)
      .join(',');

    const sig = states + '|' + (this._confirm?.label || '');
    if (sig === this._prev) return;
    this._prev = sig;

    const MODULES = [
      { section: '⚡ Energie & Vermogen' },
      { entity: 'switch.cloudems_module_nilm',            name: 'NILM Apparaatdetectie' },
      { entity: 'switch.cloudems_module_piekbeperking',   name: 'Piekbeperking (capaciteitstarief)' },
      { entity: 'switch.cloudems_module_faseverdeling',   name: 'Faseverdeling' },
      { entity: 'switch.cloudems_module_goedkope_uren',   name: 'Goedkope uren schakelaars' },
      { entity: 'switch.cloudems_module_nilm_load_shift', name: 'NILM Lastverschuiving' },
      { section: '☀️ Zonne-energie' },
      { entity: 'switch.cloudems_module_pv_forecast',     name: 'PV-prognose & Azimuth leren' },
      { entity: 'switch.cloudems_module_schaduw',         name: 'Schaduwdetectie' },
      { entity: 'switch.cloudems_module_solar_learner',   name: 'Omvormer fase-detectie (SolarLearner)' },
      { section: '🌡️ Klimaat' },
      { entity: 'switch.cloudems_module_klimaat',         name: 'Slim Klimaatbeheer (zones)' },
      { entity: 'switch.cloudems_module_ketel',           name: 'Boiler sturing' },
      { section: '🚗 Laden & Accu' },
      { entity: 'switch.cloudems_module_ev_lader',        name: 'EV-lader sturing' },
      { entity: 'switch.cloudems_module_batterij',        name: 'Thuisbatterij scheduler' },
      { entity: 'switch.cloudems_zonneplan_auto_sturing', name: 'Zonneplan Nexus auto-sturing' },
      { entity: 'switch.cloudems_module_ere',             name: 'ERE Certificaten (NEa)' },
      { section: '💶 Budget & Kosten' },
      { entity: 'switch.cloudems_module_budget',          name: 'Energiebudget bewaking' },
      { section: '📊 Rapportage & Meldingen' },
      { entity: 'switch.cloudems_module_inzichten',       name: 'Wekelijkse inzichten' },
      { entity: 'switch.cloudems_slaapstand_actief',      name: 'Nachtstand detectie' },
      { entity: 'switch.cloudems_module_notificaties',    name: 'Notificaties (alle modules)' },
      { section: '🔌 Optionele modules' },
      { entity: 'switch.cloudems_module_lampcirculatie',  name: 'Lampcirculatie & Beveiliging' },
      { entity: 'switch.cloudems_module_ebike',           name: 'E-bike & Scooter' },
      { entity: 'switch.cloudems_module_zwembad',         name: 'Zwembad Controller' },
      { entity: 'switch.cloudems_module_rolluiken',       name: 'Rolluiken' },
    ];

    const LEERDATA = [
      { label: 'Azimuth / tilt',     emoji: '🔄', bg: '#3d3000', border: '#856600', service: 'cloudems', action: 'reset_pv_orientation',  data: {},                         confirm: 'Azimuth, hellingshoek en kalibratie resetten?' },
      { label: 'Fase-detectie',      emoji: '〰️', bg: '#001a3d', border: '#1a4a8a', service: 'cloudems', action: 'reset_phase_detection', data: {},                         confirm: 'Omvormer fase-toewijzing resetten?' },
      { label: 'NILM apparaten',     emoji: '⚡', bg: '#003d1a', border: '#1a7a3d', service: 'cloudems', action: 'reset_nilm',            data: {},                         confirm: 'Alle geleerde NILM apparaten wissen?' },
      { label: 'Aanwezigheid',       emoji: '🏠', bg: '#2d0050', border: '#6a1a9a', service: 'cloudems', action: 'reset_presence',        data: {},                         confirm: '7×24 aanwezigheidspatroon wissen?' },

      { label: '⚠️ Boiler leerdata', emoji: '🧹', bg: '#3d0000', border: '#8a2020', service: 'cloudems', action: 'wis_boiler_leerdata',   data: {},                         confirm: 'Alle boiler leerdata wissen?' },
      { label: '⚠️ Alle leerdata',   emoji: '🗑️', bg: '#3d0000', border: '#cc2020', service: 'cloudems', action: 'reset_all_learning',   data: {},                         confirm: 'ALLES wissen — vers begin? Dit kan niet ongedaan worden gemaakt.' },
    ];

    const moduleRows = MODULES.map(m => {
      if (m.section) {
        return `<div class="section-lbl">${m.section}</div>`;
      }
      const on = this._on(m.entity);
      const avail = this._avail(m.entity);
      return `<div class="mod-row${avail ? '' : ' unavail'}" data-entity="${m.entity}">
        <span class="mod-name">${m.name}</span>
        <button class="tog ${on ? 'on' : 'off'}" data-entity="${m.entity}" ${avail ? '' : 'disabled'}>
          <span class="knob"></span>
        </button>
      </div>`;
    }).join('');

    const leerdataGrid = LEERDATA.map((b, i) => `
      <button class="lb" data-idx="${i}"
        style="background:${b.bg};border:1px solid ${b.border}">
        <span class="lb-emoji">${b.emoji}</span>
        <span class="lb-label">${b.label}</span>
      </button>`
    ).join('');

    const dialog = this._confirm ? `
      <div class="overlay">
        <div class="dlg">
          <div class="dlg-title">Weet je het zeker?</div>
          <div class="dlg-msg">${this._confirm.confirm}</div>
          <div class="dlg-btns">
            <button class="btn-no">Annuleren</button>
            <button class="btn-yes">OK</button>
          </div>
        </div>
      </div>` : '';

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; font-family: var(--primary-font-family,sans-serif); }
        .wrap { background:rgb(34,34,34); border:1px solid rgba(255,255,255,0.06);
          border-radius:16px; overflow:hidden; }
        /* title */
        .t { font-size:13px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
          color:rgba(255,255,255,0.5); padding:14px 16px 8px; }
        /* modules */
        .mods { padding:0 8px 8px; }
        .section-lbl { font-size:11px; font-weight:700; letter-spacing:.07em; text-transform:uppercase;
          color:rgba(255,255,255,0.3); padding:10px 8px 4px; }
        .mod-row { display:flex; align-items:center; justify-content:space-between;
          padding:6px 8px; border-radius:8px; }
        .mod-row:hover { background:rgba(255,255,255,0.04); }
        .mod-row.unavail { opacity:.35; pointer-events:none; }
        .mod-name { font-size:13px; color:rgba(255,255,255,0.85); }
        /* toggle */
        .tog { position:relative; width:40px; height:22px; border-radius:11px;
          border:none; cursor:pointer; flex-shrink:0; transition:background .2s;
          background:rgba(255,255,255,0.12); }
        .tog.on  { background:#06b6d4; }
        .tog:disabled { opacity:.4; cursor:default; }
        .knob { position:absolute; top:3px; width:16px; height:16px;
          border-radius:50%; background:#fff; transition:left .2s;
          box-shadow:0 1px 3px rgba(0,0,0,.4); pointer-events:none; }
        .tog.off .knob { left:3px; }
        .tog.on  .knob { left:21px; }
        /* divider */
        hr { border:none; border-top:1px solid rgba(255,255,255,0.07); margin:4px 0; }
        /* leerdata */
        .lg { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:0 12px 14px; }
        .lb { display:flex; flex-direction:column; align-items:center; gap:8px;
          padding:16px 8px 14px; border-radius:12px; cursor:pointer;
          transition:opacity .15s, transform .1s; }
        .lb:hover { opacity:.8; transform:translateY(-1px); }
        .lb:active { transform:scale(.97); }
        .lb-emoji { font-size:28px; line-height:1; }
        .lb-label { font-size:12px; color:rgba(255,255,255,0.85); text-align:center; line-height:1.3; }
        /* dialog */
        .overlay { position:fixed; inset:0; background:rgba(0,0,0,.65);
          display:flex; align-items:center; justify-content:center; z-index:9999; }
        .dlg { background:#1e1e1e; border:1px solid rgba(255,255,255,0.14);
          border-radius:16px; padding:24px 20px 16px; max-width:320px; width:90%; }
        .dlg-title { font-size:16px; font-weight:700; color:#fff; margin-bottom:10px; }
        .dlg-msg { font-size:13px; color:rgba(255,255,255,0.7); margin-bottom:20px; line-height:1.5; }
        .dlg-btns { display:flex; justify-content:flex-end; gap:10px; }
        .btn-no  { background:none; border:none; color:#06b6d4; font-size:14px;
          font-weight:600; cursor:pointer; padding:6px 12px; border-radius:8px; }
        .btn-no:hover { background:rgba(6,182,212,.1); }
        .btn-yes { background:#06b6d4; border:none; color:#000; font-size:14px;
          font-weight:700; cursor:pointer; padding:6px 16px; border-radius:8px; }
        .btn-yes:hover { background:#22d3ee; }
      </style>

      <div class="wrap">
        <div class="t">🔧 CloudEMS Modules</div>
        <div class="mods">${moduleRows}</div>
        <hr>
        <div class="t">🧹 Leerdata Beheer</div>
        <div class="lg">${leerdataGrid}</div>
      </div>
      ${dialog}`;

    // Toggle events
    this.shadowRoot.querySelectorAll('.tog').forEach(btn => {
      btn.addEventListener('click', () => {
        const eid = btn.dataset.entity;
        const on = btn.classList.contains('on');
        this._hass.callService('homeassistant', on ? 'turn_off' : 'turn_on', { entity_id: eid });
      });
    });

    // Leerdata events
    this.shadowRoot.querySelectorAll('.lb').forEach(btn => {
      btn.addEventListener('click', () => {
        this._confirm = LEERDATA[parseInt(btn.dataset.idx)];
        this._prev = '';
        this._render();
      });
    });

    // Dialog events
    const no = this.shadowRoot.querySelector('.btn-no');
    const yes = this.shadowRoot.querySelector('.btn-yes');
    if (no) {
      no.addEventListener('click', () => {
        this._confirm = null;
        this._prev = '';
        this._render();
      });
      yes.addEventListener('click', () => {
        const c = this._confirm;
        this._confirm = null;
        this._prev = '';
        this._hass.callService(c.service, c.action, c.data || {});
        this._render();
      });
    }
  }

  getCardSize() { return 10; }
  static getConfigElement() { return document.createElement('cloudems-config-card-editor'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-config-card')) {
  customElements.define('cloudems-config-card', CloudEMSConfigCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-config-card')) {
  window.customCards.push({
    type: 'cloudems-config-card',
    name: 'CloudEMS Config Card',
    description: 'Module toggles + leerdata beheer',
  });
}

if (!customElements.get('cloudems-config-card-editor')) {
  class _cloudems_config_card_editor extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});}
    setConfig(c){this._cfg=c;this._render();}
    _fire(key,val){
      this._cfg={...this._cfg,[key]:val};
      this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this._cfg},bubbles:true,composed:true}));
    }
    _render(){
      const cfg=this._cfg||{};
      this.shadowRoot.innerHTML=`<style>
        .row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:0.5px solid rgba(255,255,255,0.08)}
        label{font-size:12px;color:rgba(255,255,255,0.6)}
        input{background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:6px;color:#fff;padding:4px 8px;font-size:12px;width:180px}
      </style>
      <div style="padding:8px"><div class="row"><label>Titel</label><input type="text" .value="${cfg.title||''}"
      @input="${e=>this._fire('title',e.target.value)}" /></div></div>`;
    }
  }
  customElements.define('cloudems-config-card-editor', _cloudems_config_card_editor);
}
