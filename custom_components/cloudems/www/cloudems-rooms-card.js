/**
 * CloudEMS Rooms Card — cloudems-rooms-card
 * Version: 1.1.0
 *
 * Sensors:
 *   sensor.cloudems_kamers_overzicht  → rooms[], total_power_w, top_room
 *   sensor.cloudems_nilm_devices      → device_list[] { name, room, power_w, phase, confirmed, is_on, user_suppressed }
 */

const ROOMS_VERSION = "5.4.96";

class CloudEMSRoomsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._prevJson = '';
    this._expanded = new Set();
    this._shadowBuilt = false;
  }

  setConfig(config) {
    this._config = config || {};
  }

  getCardSize() { return 6; }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _fmt(w) {
    if (w >= 1000) return (w / 1000).toFixed(2) + ' kW';
    return Math.round(w) + ' W';
  }

  _phaseColor(ph) {
    if (ph === 'L1') return '#60a5fa';
    if (ph === 'L2') return '#a78bfa';
    if (ph === 'L3') return '#34d399';
    return 'rgba(255,255,255,0.25)';
  }

  _statusLabel(d) {
    if (d.user_suppressed) return { txt: 'genegeerd', col: 'rgba(255,255,255,0.3)' };
    if (d.confirmed)       return { txt: 'bevestigd', col: '#34d399' };
    return { txt: 'lerend', col: '#a78bfa' };
  }

  _render() {
    if (!this._hass) return;
    const eid     = this._config.entity || 'sensor.cloudems_kamers_overzicht';
    const devEid  = this._config.devices_entity || 'sensor.cloudems_nilm_devices';
    const st      = this._hass.states[eid];
    const devSt   = this._hass.states[devEid];

    if (!st) {
      this.shadowRoot.innerHTML = `<div style="padding:16px;font-size:12px;color:rgba(255,255,255,0.4)">Sensor niet gevonden: ${eid}</div>`;
      return;
    }

    const total_w = parseFloat(st.attributes.total_power_w || 0);
    const top     = st.state || '';
    const rooms   = (st.attributes.rooms || []).slice().sort((a, b) => b.power_w - a.power_w);
    const devList = devSt?.attributes?.device_list || devSt?.attributes?.devices || [];

    const json = JSON.stringify([total_w, rooms.map(r => r.power_w), devList.length]);
    if (json === this._prevJson) return;
    this._prevJson = json;

    const totalKwh = rooms.reduce((s, r) => s + (r.kwh_today || 0), 0);
    const maxW     = rooms[0]?.power_w || 1;
    const active   = rooms.filter(r => r.power_w > 0);
    const inactive = rooms.filter(r => r.power_w <= 0);

    const roomDevices = (room) =>
      devList.filter(d => (d.room || '').toLowerCase() === (room || '').toLowerCase());

    const buildRow = (r) => {
      const isTop  = r.room?.toLowerCase() === top?.toLowerCase() && r.power_w > 0;
      const barPct = Math.round(r.power_w / maxW * 100);
      const kwh    = (r.kwh_today || 0).toFixed(2);
      const devs   = roomDevices(r.room);
      const name   = r.room ? r.room.charAt(0).toUpperCase() + r.room.slice(1) : '?';
      const isExp  = this._expanded.has(r.room);
      const barColor = isTop ? '#EF9F27' : '#378ADD';
      const inactive_room = r.power_w <= 0;

      let devRows = '';
      if (isExp && devs.length > 0) {
        devRows = devs.map(d => {
          const st = this._statusLabel(d);
          const phc = this._phaseColor(d.phase || '?');
          const on_dot = d.is_on ? '#22c55e' : 'rgba(255,255,255,0.15)';
          return `<div class="dev-row">
            <div class="dev-dot" style="background:${on_dot}"></div>
            <div class="dev-name">${d.name || d.device_type || '?'}</div>
            <div class="dev-w">${d.is_on ? Math.round(d.power_w || 0) + ' W' : '—'}</div>
            <div class="dev-phase" style="color:${phc}">${d.phase || '?'}</div>
            <div class="dev-status" style="color:${st.col}">${st.txt}</div>
          </div>`;
        }).join('');
      } else if (isExp && devs.length === 0) {
        devRows = `<div class="dev-empty">Geen apparaten bekend</div>`;
      }

      const hasDevs = devs.length > 0;
      const expandIcon = isExp ? '▲' : '▼';

      return `<div class="row${isTop ? ' top' : ''}${inactive_room ? ' off' : ''}" data-room="${r.room}" style="cursor:${hasDevs ? 'pointer' : 'default'}">
        <div class="room-name">${name}</div>
        <div class="pw">${inactive_room ? '<span class="zero">0 W</span>' : this._fmt(r.power_w)}</div>
        <div class="bar-bg"><div class="bar-fg" style="width:${barPct}%;background:${barColor}"></div></div>
        <div class="kwh">${kwh} kWh</div>
        <div class="expand-btn">${hasDevs ? expandIcon : ''}</div>
      </div>
      ${isExp ? `<div class="dev-block">${devRows}</div>` : ''}`;
    };

    const html = `
<style>
*{box-sizing:border-box;margin:0;padding:0}
:host{display:block}
.card{background:rgb(22,22,22);border-radius:14px;border:1px solid rgba(255,255,255,0.07);overflow:hidden;color:#fff;font-family:Inter,sans-serif}
.hdr{padding:12px 16px 10px;border-bottom:1px solid rgba(255,255,255,0.07);display:flex;justify-content:space-between;align-items:center}
.hdr-title{font-size:13px;font-weight:700}
.hdr-sub{font-size:10px;color:rgba(255,255,255,0.35);margin-top:2px}
.hdr-w{font-size:22px;font-weight:700;text-align:right}
.hdr-lbl{font-size:10px;color:rgba(255,255,255,0.35);text-align:right}
.banner{padding:7px 16px;background:rgba(239,159,39,0.08);border-bottom:1px solid rgba(239,159,39,0.15);display:flex;align-items:center;gap:6px;font-size:11px;color:rgba(255,255,255,0.45)}
.banner strong{color:#EF9F27;font-weight:700}
.sec-lbl{font-size:9px;font-weight:700;letter-spacing:0.08em;color:rgba(255,255,255,0.2);padding:6px 14px 2px;text-transform:uppercase}
.row{display:grid;grid-template-columns:105px 56px 1fr 64px 16px;align-items:center;gap:0 6px;padding:5px 14px;transition:background 0.1s;user-select:none}
.row:hover{background:rgba(255,255,255,0.03)}
.row.top{background:rgba(239,159,39,0.04)}
.row.off .room-name{color:rgba(255,255,255,0.3)}
.room-name{font-size:12px;color:rgba(255,255,255,0.85);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.top .room-name{color:#EF9F27;font-weight:700}
.pw{font-size:12px;font-weight:700;text-align:right;font-variant-numeric:tabular-nums;color:rgba(255,255,255,0.9)}
.row.top .pw{color:#EF9F27}
.zero{color:rgba(255,255,255,0.2)}
.bar-bg{height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden}
.bar-fg{height:100%;border-radius:2px;transition:width 0.4s}
.kwh{font-size:10px;color:rgba(255,255,255,0.35);text-align:right;font-variant-numeric:tabular-nums}
.expand-btn{font-size:9px;color:rgba(255,255,255,0.25);text-align:center}
.sep{height:1px;background:rgba(255,255,255,0.06);margin:3px 14px}
.dev-block{background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.05);padding:4px 0}
.dev-row{display:grid;grid-template-columns:14px 1fr 52px 28px 70px;align-items:center;gap:0 6px;padding:4px 14px 4px 28px;font-size:11px}
.dev-dot{width:7px;height:7px;border-radius:50%}
.dev-name{color:rgba(255,255,255,0.7);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dev-w{text-align:right;font-variant-numeric:tabular-nums;color:rgba(255,255,255,0.5)}
.dev-phase{text-align:center;font-weight:700;font-size:10px}
.dev-status{text-align:right;font-size:10px}
.dev-empty{padding:6px 28px;font-size:11px;color:rgba(255,255,255,0.2)}
.footer{padding:7px 14px 9px;border-top:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;font-size:10px;color:rgba(255,255,255,0.2)}
</style>
<div class="card">
  <div class="hdr">
    <div>
      <div class="hdr-title">⚡ Huisverbruik per kamer</div>
      <div class="hdr-sub">${rooms.length} kamers · klik voor apparaten</div>
    </div>
    <div>
      <div class="hdr-w">${this._fmt(total_w)}</div>
      <div class="hdr-lbl">totaal nu</div>
    </div>
  </div>
  ${top ? `<div class="banner">🏆 Hoogste verbruiker: <strong>${top.charAt(0).toUpperCase() + top.slice(1)}</strong></div>` : ''}
  <div id="rows-container">
    ${active.length > 0 ? `<div class="sec-lbl">actief</div>${active.map(buildRow).join('')}` : ''}
    ${inactive.length > 0 ? `<div class="sep"></div><div class="sec-lbl">uit · vandaag kWh</div>${inactive.map(buildRow).join('')}` : ''}
  </div>
  <div class="footer">
    <span>Vandaag: ${totalKwh.toFixed(2)} kWh</span>
    <span>CloudEMS Rooms v${ROOMS_VERSION}</span>
  </div>
</div>`;

    this.shadowRoot.innerHTML = html;

    // Click handlers voor expand/collapse
    this.shadowRoot.querySelectorAll('.row[data-room]').forEach(el => {
      el.addEventListener('click', () => {
        const room = el.dataset.room;
        if (this._expanded.has(room)) {
          this._expanded.delete(room);
        } else {
          this._expanded.add(room);
        }
        this._prevJson = '';
        this._render();
      });
    });
  }

  static getConfigElement() {
    return document.createElement('cloudems-rooms-card-editor');
  }

  static getStubConfig() {
    return { entity: 'sensor.cloudems_kamers_overzicht', devices_entity: 'sensor.cloudems_nilm_devices' };
  }
}

class CloudEMSRoomsCardEditor extends HTMLElement {
  setConfig(c) { this._config = c || {}; }
  set hass(h) {}
  connectedCallback() {
    if (this._built) return;
    this._built = true;
    this.innerHTML = `<div style="padding:12px;font-size:13px;display:flex;flex-direction:column;gap:8px">
      <label>Kamers sensor<br><input type="text" id="entity" value="${this._config.entity || 'sensor.cloudems_kamers_overzicht'}" style="width:100%;margin-top:4px;padding:4px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.07);color:inherit"></label>
      <label>Apparaten sensor<br><input type="text" id="dev_entity" value="${this._config.devices_entity || 'sensor.cloudems_nilm_devices'}" style="width:100%;margin-top:4px;padding:4px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.07);color:inherit"></label>
    </div>`;
    ['entity','dev_entity'].forEach(id => {
      this.querySelector('#'+id).addEventListener('change', () => {
        this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: {
          entity: this.querySelector('#entity').value,
          devices_entity: this.querySelector('#dev_entity').value,
        }}, bubbles: true, composed: true }));
      });
    });
  }
}

if (!customElements.get('cloudems-rooms-card')) customElements.define('cloudems-rooms-card', CloudEMSRoomsCard);
if (!customElements.get('cloudems-rooms-card-editor')) customElements.define('cloudems-rooms-card-editor', CloudEMSRoomsCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'cloudems-rooms-card', name: 'CloudEMS Rooms', description: 'Vermogen per kamer met apparaten' });
console.info('%c CloudEMS Rooms Card v' + ROOMS_VERSION, 'color:#EF9F27;font-weight:700');
