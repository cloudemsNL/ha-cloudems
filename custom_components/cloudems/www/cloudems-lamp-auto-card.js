// CloudEMS Lamp Automatisering Card — v1.0.0
// Los van lamp-circulatie: aan/uit onafhankelijk

const CARD_VERSION = '5.4.8';
const MODES = { manual: '⏸ Handmatig', semi: '🔔 Semi-auto', auto: '⚡ Automatisch' };
const MODE_COLOR = { manual: '#6b7280', semi: '#f59e0b', auto: '#22c55e' };

class CloudEMSLampAutoCard extends HTMLElement {
  set hass(hass) {
    if (!this._hass || this._hass !== hass) {
      this._hass = hass;
      this._render();
    }
  }
  setConfig(config) { this._config = config || {}; }
  getCardSize() { return 4; }

  static getConfigElement() {
    const el = document.createElement('cloudems-lamp-auto-card-editor');
    return el;
  }
  static getStubConfig() { return {}; }

  _getData() {
    const st = this._hass?.states['sensor.cloudems_lampcirculatie_status'];
    const auto = st?.attributes?.lamp_auto || this._hass?.states['sensor.cloudems_status']?.attributes?.lamp_auto || {};
    return auto;
  }

  _render() {
    if (!this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });

    const data = this._getData();
    const enabled = !!data.enabled;
    const lamps = data.lamps || [];
    const actions = data.recent_actions || [];
    const activeLamps = lamps.filter(l => !l.excluded);

    const modeCount = { manual: 0, semi: 0, auto: 0 };
    activeLamps.forEach(l => { modeCount[l.mode] = (modeCount[l.mode] || 0) + 1; });

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block }
        ha-card { background: #111827; border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; overflow: hidden; font-family: ui-sans-serif, sans-serif; color: #e2e8f0 }
        .header { padding: 14px 16px 10px; border-bottom: 1px solid rgba(255,255,255,0.07); display: flex; align-items: center; justify-content: space-between }
        .title { font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 8px }
        .badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600 }
        .badge.on { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3) }
        .badge.off { background: rgba(107,114,128,0.15); color: #6b7280; border: 1px solid rgba(107,114,128,0.3) }
        .body { padding: 12px 16px }
        .stats { display: flex; gap: 8px; margin-bottom: 12px }
        .stat { flex: 1; background: rgba(255,255,255,0.04); border-radius: 8px; padding: 8px 10px; text-align: center }
        .stat-val { font-size: 18px; font-weight: 700 }
        .stat-lbl { font-size: 9px; color: #6b7280; letter-spacing: .06em; text-transform: uppercase; margin-top: 2px }
        .section-title { font-size: 10px; font-weight: 700; letter-spacing: .08em; color: #6b7280; text-transform: uppercase; margin: 12px 0 6px }
        .lamp-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 8px; margin-bottom: 4px; background: rgba(255,255,255,0.03) }
        .lamp-name { flex: 1; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
        .lamp-area { font-size: 10px; color: #6b7280 }
        .mode-badge { font-size: 9px; padding: 2px 7px; border-radius: 8px; font-weight: 600; cursor: pointer; white-space: nowrap }
        .presence-dot { width: 6px; height: 6px; border-radius: 50%; background: #6b7280; flex-shrink: 0 }
        .presence-dot.active { background: #22c55e }
        select { background: #1f2937; border: 1px solid rgba(255,255,255,0.12); color: #e2e8f0; border-radius: 6px; padding: 2px 4px; font-size: 10px; cursor: pointer }
        .action-row { font-size: 11px; padding: 4px 8px; border-radius: 6px; background: rgba(255,255,255,0.03); margin-bottom: 3px; display: flex; gap: 8px; align-items: center }
        .action-icon { font-size: 13px }
        .action-reason { color: #6b7280; font-size: 10px }
        .empty { text-align: center; color: #4b5563; font-size: 12px; padding: 16px; font-style: italic }
      </style>
      <ha-card>
        <div class="header">
          <div class="title">🏠 Lamp Automatisering
            <span class="badge ${enabled ? 'on' : 'off'}">${enabled ? 'AAN' : 'UIT'}</span>
          </div>
          <span style="font-size:10px;color:#4b5563">v${CARD_VERSION}</span>
        </div>
        <div class="body">
          ${enabled ? `
          <div class="stats">
            <div class="stat">
              <div class="stat-val" style="color:#22c55e">${modeCount.auto||0}</div>
              <div class="stat-lbl">Automatisch</div>
            </div>
            <div class="stat">
              <div class="stat-val" style="color:#f59e0b">${modeCount.semi||0}</div>
              <div class="stat-lbl">Semi-auto</div>
            </div>
            <div class="stat">
              <div class="stat-val" style="color:#6b7280">${modeCount.manual||0}</div>
              <div class="stat-lbl">Handmatig</div>
            </div>
            <div class="stat">
              <div class="stat-val">${activeLamps.length}</div>
              <div class="stat-lbl">Lampen</div>
            </div>
          </div>

          <div class="section-title">Lampen</div>
          ${activeLamps.length === 0
            ? '<div class="empty">Geen lampen geconfigureerd</div>'
            : activeLamps.map(l => `
            <div class="lamp-row">
              <div class="presence-dot ${l.has_presence ? 'active' : ''}" title="${l.has_presence ? 'Aanwezigheidssensor gekoppeld' : 'Geen sensor'}"></div>
              <div style="flex:1;min-width:0">
                <div class="lamp-name">${l.label}</div>
                ${l.area ? `<div class="lamp-area">${l.area}</div>` : ''}
              </div>
              <select onchange="this.getRootNode().host._setMode('${l.entity_id}', this.value)">
                ${['manual','semi','auto'].map(m =>
                  `<option value="${m}" ${l.mode===m?'selected':''}>${MODES[m]}</option>`
                ).join('')}
              </select>
            </div>`).join('')
          }

          ${actions.length > 0 ? `
          <div class="section-title">Recente acties</div>
          ${actions.slice(-5).reverse().map(a => `
            <div class="action-row">
              <span class="action-icon">${a.action==='on'?'💡':a.action==='off'?'🌑':a.action==='confirm_sent'?'🔔':'⚡'}</span>
              <span style="flex:1">${a.lamp}</span>
              <span class="action-reason">${a.reason||''}</span>
            </div>`).join('')}
          ` : ''}
          ` : `
          <div class="empty">
            Lamp automatisering is uitgeschakeld.<br>
            Schakel in via Configureren → Verbruik → Slimme Lamp Automatisering.
          </div>
          `}
        </div>
      </ha-card>`;
  }

  _setMode(entityId, mode) {
    // Sla modus op via CloudEMS service (toekomstig) of input_select fallback
    if (!this._hass) return;
    this._hass.callService('cloudems', 'lamp_auto_set_mode', {
      entity_id: entityId,
      mode: mode,
    }).catch(() => {
      // Fallback: log
      console.info(`CloudEMS lamp auto: ${entityId} → ${mode}`);
    });
  }
}

if (!customElements.get('cloudems-lamp-auto-card')) customElements.define('cloudems-lamp-auto-card', CloudEMSLampAutoCard);

// Editor (simpel)
class CloudEMSLampAutoCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; }
  get _title() { return this._config?.title || ''; }
}
if (!customElements.get('cloudems-lamp-auto-card-editor')) customElements.define('cloudems-lamp-auto-card-editor', CloudEMSLampAutoCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-lamp-auto-card',
  name: 'CloudEMS Lamp Automatisering',
  description: 'Slimme lamp sturing op basis van geleerd patroon — los van lampcirculatie',
});
