// CloudEMS Energy Visual Card v5.4.96
// Animated energy flow with NILM device icons as nodes

const EVC_VER = '1.0.0';

// Reuse icon builder (inline copy — no import needed in HA)
function _evcIcon(type, on, size=36) {
  const s = on ? 1 : 0.3;
  const g = (r,g,b,a=1) => `rgba(${r},${g},${b},${a*s})`;
  const green=g(29,158,117), blue=g(55,138,221), amber=g(239,159,39),
        gray=g(120,120,130), dim=g(50,52,62);

  const icons = {
    washer: `<rect x="2" y="2" width="32" height="32" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <circle cx="18" cy="20" r="9" fill="none" stroke="${gray}" stroke-width="1.5"/>
      <circle cx="18" cy="20" r="6" fill="none" stroke="${on?green:dim}" stroke-width="1.2">
        ${on?`<animateTransform attributeName="transform" type="rotate" from="0 18 20" to="360 18 20" dur="2s" repeatCount="indefinite"/>`:''}
      </circle>`,
    dishwasher: `<rect x="2" y="2" width="32" height="32" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="5" y="12" width="26" height="2" rx="1" fill="${gray}"/>
      <rect x="5" y="17" width="26" height="2" rx="1" fill="${gray}"/>
      <rect x="5" y="22" width="${on?'26':'6'}" height="1.5" rx="1" fill="${on?blue:dim}">
        ${on?`<animate attributeName="width" values="0;26;0" dur="1.2s" repeatCount="indefinite"/>`:''}
      </rect>`,
    dryer: `<rect x="2" y="2" width="32" height="32" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <circle cx="18" cy="20" r="9" fill="none" stroke="${gray}" stroke-width="1.5"/>
      <circle cx="18" cy="20" r="6" fill="none" stroke="${on?amber:dim}" stroke-width="1.2">
        ${on?`<animateTransform attributeName="transform" type="rotate" from="360 18 20" to="0 18 20" dur="2.5s" repeatCount="indefinite"/>`:''}
      </circle>
      ${on?`<circle cx="18" cy="20" r="3" fill="${g(226,75,74)}"><animate attributeName="r" values="2;4;2" dur="1s" repeatCount="indefinite"/></circle>`:`<circle cx="18" cy="20" r="3" fill="${dim}"/>`}`,
    tv: `<rect x="2" y="5" width="32" height="20" rx="3" fill="${g(15,18,28)}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="4" y="7" width="28" height="16" rx="2" fill="${on?g(15,25,40):g(8,8,12)}"/>
      ${on?`<rect x="4" y="7" width="28" height="2" fill="${g(56,189,248,0.5)}"><animate attributeName="y" values="7;21;7" dur="2s" repeatCount="indefinite"/></rect>`:''}
      <rect x="14" y="25" width="8" height="3" rx="1" fill="${gray}"/>`,
    router: `<rect x="3" y="14" width="30" height="12" rx="3" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="10" y="6" width="2.5" height="10" rx="1" fill="${gray}"/>
      <rect x="23.5" y="6" width="2.5" height="10" rx="1" fill="${gray}"/>
      ${[9,17,25].map((x,i)=>`<circle cx="${x}" cy="22" r="2" fill="${on?[green,blue,amber][i]:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.2;1" dur="1.1s" begin="${i*0.4}s" repeatCount="indefinite"/>`:''}
      </circle>`).join('')}`,
    nas: `<rect x="6" y="2" width="24" height="32" rx="3" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      ${[6,12,18,24].map((y,i)=>`<rect x="8" y="${y}" width="20" height="5" rx="1.5" fill="${g(35,38,48)}" stroke="${gray}" stroke-width="0.5"/>
      <circle cx="23" cy="${y+2.5}" r="1.8" fill="${on?[green,blue,green,amber][i]:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.3;1" dur="${1.4+i*0.3}s" repeatCount="indefinite"/>`:''}
      </circle>`).join('')}`,
    fridge: `<rect x="6" y="2" width="24" height="32" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="6" y="2" width="24" height="13" rx="5" fill="${g(25,28,38)}" stroke="${gray}" stroke-width="1.2"/>
      <line x1="6" y1="15" x2="30" y2="15" stroke="${gray}" stroke-width="1.2"/>
      <rect x="25" y="6" width="2.5" height="6" rx="1.2" fill="${gray}"/>
      <rect x="25" y="18" width="2.5" height="9" rx="1.2" fill="${gray}"/>
      ${on?`<text x="14" y="12" font-size="8" fill="${blue}" font-family="sans-serif">❄</text>`:''}`,
    boiler: `<ellipse cx="18" cy="20" rx="12" ry="14" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="6" y="2" width="24" height="5" rx="2.5" fill="${gray}"/>
      ${on?`<ellipse cx="18" cy="25" rx="9" ry="7" fill="${g(234,99,39,0.25)}"><animate attributeName="ry" values="5;9;5" dur="2s" repeatCount="indefinite"/></ellipse>`:''}
      <circle cx="18" cy="20" r="4" fill="none" stroke="${on?amber:dim}" stroke-width="1.5"/>`,
    ev: `<rect x="2" y="10" width="28" height="14" rx="3" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <rect x="5" y="7" width="18" height="7" rx="2.5" fill="${g(35,40,50)}"/>
      <rect x="30" y="15" width="4" height="4" rx="1.5" fill="${gray}"/>
      <circle cx="8" cy="28" r="3.5" fill="${g(30,30,35)}" stroke="${gray}" stroke-width="1"/>
      <circle cx="27" cy="28" r="3.5" fill="${g(30,30,35)}" stroke="${gray}" stroke-width="1"/>
      <rect x="6" y="14" width="${on?'20':'5'}" height="4" rx="1.5" fill="${on?green:dim}">
        ${on?`<animate attributeName="width" values="3;20;3" dur="2.5s" repeatCount="indefinite"/>`:''}
      </rect>`,
    default: `<rect x="4" y="4" width="28" height="28" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.2"/>
      <circle cx="18" cy="16" r="6" fill="none" stroke="${on?green:dim}" stroke-width="1.5"/>
      <circle cx="18" cy="16" r="2" fill="${on?green:dim}"/>
      <line x1="18" y1="10" x2="18" y2="7" stroke="${on?green:dim}" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="18" y1="22" x2="18" y2="25" stroke="${on?green:dim}" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="12" y1="16" x2="9" y2="16" stroke="${on?green:dim}" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="24" y1="16" x2="27" y2="16" stroke="${on?green:dim}" stroke-width="1.5" stroke-linecap="round"/>`,
  };
  const body = icons[type] || icons.default;
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
}

function _evcType(name, brand='') {
  const n=(name||'').toLowerCase(), b=(brand||'').toLowerCase();
  if(/wasmach|washer/.test(n)) return 'washer';
  if(/vaatwa|dishwash/.test(n)) return 'dishwasher';
  if(/droog|dryer/.test(n)) return 'dryer';
  if(/\btv\b|televisie|television/.test(n)) return 'tv';
  if(/router|modem|wifi|unifi|ubiquiti/.test(n+b)) return 'router';
  if(/nas|proxmox|server|synology/.test(n+b)) return 'nas';
  if(/koel|fridge/.test(n)) return 'fridge';
  if(/boiler|warmwater/.test(n)) return 'boiler';
  if(/\bev\b|auto|car|lader.*elektrisch|easee|wallbox/.test(n+b)) return 'ev';
  return 'default';
}

class CloudemsEnergyVisualCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this._p = ''; }

  setConfig(c) { this._cfg = {title:'⚡ Energiestroom', max_devices:6, ...c}; this._r(); }

  set hass(h) {
    this._hass = h;
    const k = JSON.stringify([
      h.states['sensor.cloudems_nilm_running_devices']?.last_changed,
      h.states['sensor.cloudems_status']?.last_changed,
    ]);
    if(k !== this._p) { this._p = k; this._r(); }
  }

  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    const st  = h.states['sensor.cloudems_status']?.attributes || {};
    // Lees solar via ruwe inverter-som (zelfde bron als flow card) voor consistentie.
    // Fallback 1: solar_system inverters[], Fallback 2: status-attribuut (EMA), Fallback 3: intelligence sensor
    const _solarInvs = (h.states['sensor.cloudems_solar_system']?.attributes?.inverters || []);
    const _pvRaw = _solarInvs.length > 0
      ? _solarInvs.reduce((s, i) => s + (parseFloat(i.current_w) || 0), 0)
      : null;
    const pvW   = _pvRaw !== null ? _pvRaw
      : parseFloat(st.solar_power_w || h.states['sensor.cloudems_solar_system_intelligence']?.state || 0);
    const gridW = parseFloat(st.grid_power_w || h.states['sensor.cloudems_grid_net_power']?.state || 0);
    const batW  = parseFloat(st.battery_power_w || h.states['sensor.cloudems_battery_power']?.state || h.states['sensor.thuisbatterij_power']?.state || 0);
    const soc   = parseFloat(h.states['sensor.thuisbatterij_percentage']?.state || 0);
    const houseW = parseFloat(st.house_load_w || h.states['sensor.cloudems_home_rest']?.state || 0);
    const imp = gridW > 50, exp = gridW < -50;

    // NILM running devices
    const running = h.states['sensor.cloudems_nilm_running_devices']?.attributes?.devices || [];
    const topDevs = running
      .sort((a,b) => (b.power_w||b.current_power||0)-(a.power_w||a.current_power||0))
      .slice(0, parseInt(c.max_devices)||6);
    const nilmTotalW = topDevs.reduce((s,d)=>s+(parseFloat(d.power_w??d.current_power??0)||0),0);
    const otherW = Math.max(0, houseW - nilmTotalW);

    const fmtW = w => Math.abs(w)>=1000 ? (w/1000).toFixed(1)+'kW' : Math.round(Math.abs(w))+'W';
    const col  = w => w>0 ? '#4ade80' : w<0 ? '#60a5fa' : '#6b7280';

    // Flow dots animation keyframe percentage
    const flowDot = (id, col, dur=1.5) =>
      `<circle id="${id}" r="3" fill="${col}"><animateMotion dur="${dur}s" repeatCount="indefinite"><mpath href="#path-${id}"/></animateMotion></circle>`;

    sh.innerHTML = `
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :host{display:block;width:100%}
  .card{background:rgb(22,24,30);border:1px solid rgba(255,255,255,.07);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,system-ui,sans-serif)}
  .hdr{display:flex;align-items:center;gap:10px;padding:12px 16px 10px;border-bottom:1px solid rgba(255,255,255,.08)}
  .hdr-title{font-size:12px;font-weight:600;color:#fff;flex:1}
  .flow-area{padding:12px 16px 6px;position:relative}
  .top-row{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;margin-bottom:8px}
  .node{display:flex;flex-direction:column;align-items:center;gap:4px}
  .node-icon{width:48px;height:48px;border-radius:12px;border:1.5px solid rgba(255,255,255,.12);display:flex;align-items:center;justify-content:center;background:rgb(32,34,42)}
  .node-val{font-size:13px;font-weight:700}
  .node-lbl{font-size:9px;color:rgba(163,163,163,.6);text-align:center}
  .hub{width:44px;height:44px;border-radius:50%;background:rgb(36,38,48);border:2px solid rgba(255,255,255,.15);display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:rgba(255,255,255,.5)}
  .connectors{height:60px;position:relative;margin-bottom:6px}
  svg.connectors-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
  .devices-row{display:grid;gap:1px;background:rgba(255,255,255,.06)}
  .dev-cell{background:rgb(26,28,36);padding:8px 6px;display:flex;flex-direction:column;align-items:center;gap:3px}
  .dev-name{font-size:9px;color:rgba(163,163,163,.8);text-align:center;max-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dev-pow{font-size:10px;font-weight:600;color:#4ade80}
  .other-cell{background:rgb(26,28,36);padding:8px 6px;display:flex;flex-direction:column;align-items:center;gap:3px}
  .footer{display:flex;justify-content:space-between;padding:6px 14px;font-size:9px;color:rgba(100,100,110,.6)}
</style>
<div class="card">
  <div class="hdr">
    <span style="font-size:14px">⚡</span>
    <span class="hdr-title">${c.title}</span>
    <span style="font-size:11px;color:rgba(163,163,163,.4)">${fmtW(houseW)} huis</span>
  </div>
  <div class="flow-area">
    <!-- Top row: PV · HUB · Grid/Battery -->
    <div class="top-row">
      <div class="node" style="align-items:flex-start">
        ${pvW > 50 ? `
        <div class="node-icon" style="border-color:rgba(251,191,36,.3)">
          <svg width="32" height="32" viewBox="0 0 48 48">
            <circle cx="24" cy="24" r="10" fill="rgba(251,191,36,0.2)" stroke="#fbbf24" stroke-width="1.5"/>
            ${[0,45,90,135,180,225,270,315].map(a=>`<line x1="24" y1="10" x2="24" y2="6" stroke="#fbbf24" stroke-width="1.5" stroke-linecap="round" transform="rotate(${a} 24 24)"/>`).join('')}
            <circle cx="24" cy="24" r="6" fill="#fbbf24"/>
          </svg>
        </div>
        <div class="node-val" style="color:#fbbf24">${fmtW(pvW)}</div>
        <div class="node-lbl">☀️ Zonne</div>
        ` : `<div class="node-icon" style="opacity:.3"><svg width="28" height="28" viewBox="0 0 48 48"><circle cx="24" cy="24" r="10" fill="none" stroke="#666" stroke-width="1.5"/></svg></div>
        <div class="node-val" style="color:#444">${fmtW(pvW)}</div><div class="node-lbl">☀️ Zonne</div>`}
      </div>

      <div class="hub">HUB</div>

      <div class="node" style="align-items:flex-end">
        ${Math.abs(gridW) > 20 ? `
        <div class="node-icon" style="border-color:${imp?'rgba(248,113,113,.3)':'rgba(96,165,250,.3)'}">
          <svg width="28" height="28" viewBox="0 0 48 48">
            <rect x="10" y="8" width="28" height="32" rx="4" fill="none" stroke="${imp?'#f87171':'#60a5fa'}" stroke-width="1.5"/>
            <line x1="24" y1="4" x2="24" y2="8" stroke="${imp?'#f87171':'#60a5fa'}" stroke-width="2"/>
            <line x1="24" y1="40" x2="24" y2="44" stroke="${imp?'#f87171':'#60a5fa'}" stroke-width="2"/>
            <text x="24" y="28" text-anchor="middle" font-size="12" fill="${imp?'#f87171':'#60a5fa'}" font-family="sans-serif">${imp?'↓':'↑'}</text>
          </svg>
        </div>
        <div class="node-val" style="color:${imp?'#f87171':'#60a5fa'}">${fmtW(gridW)}</div>
        <div class="node-lbl">${imp?'⬇️ Import':'⬆️ Export'}</div>
        ` : `
        <div class="node-icon" style="opacity:.3"><svg width="28" height="28" viewBox="0 0 48 48"><rect x="10" y="8" width="28" height="32" rx="4" fill="none" stroke="#666" stroke-width="1.5"/></svg></div>
        <div class="node-val" style="color:#444">0W</div><div class="node-lbl">⚖️ Balans</div>`}
      </div>
    </div>

    <!-- Battery row -->
    ${Math.abs(batW) > 20 ? `
    <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid rgba(255,255,255,.05);border-bottom:1px solid rgba(255,255,255,.05);margin-bottom:8px">
      <svg width="28" height="18" viewBox="0 0 48 32">
        <rect x="2" y="4" width="40" height="24" rx="4" fill="none" stroke="#6b7280" stroke-width="1.5"/>
        <rect x="42" y="11" width="5" height="10" rx="2" fill="#6b7280"/>
        <rect x="4" y="6" width="${Math.round(soc*0.36)}" height="20" rx="2" fill="${soc>50?'#4ade80':soc>20?'#fbbf24':'#f87171'}"/>
      </svg>
      <div style="font-size:11px;font-weight:600;color:${batW>0?'#60a5fa':'#4ade80'}">${batW>0?'Laden':'Ontladen'} ${fmtW(batW)}</div>
      <div style="font-size:10px;color:rgba(163,163,163,.5);margin-left:auto">${Math.round(soc)}% SOC</div>
    </div>` : ''}

    <!-- House total -->
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;padding:6px 10px;background:rgba(255,255,255,.03);border-radius:8px">
      <svg width="24" height="22" viewBox="0 0 48 44">
        <path d="M24 4L4 20V42h16V30h8V42h16V20z" fill="none" stroke="rgba(163,163,163,.5)" stroke-width="2" stroke-linejoin="round"/>
      </svg>
      <span style="font-size:12px;color:rgba(163,163,163,.7);flex:1">Huisverbruik</span>
      <span style="font-size:14px;font-weight:700;color:#fff">${fmtW(houseW)}</span>
    </div>
  </div>

  <!-- NILM devices grid -->
  ${topDevs.length > 0 ? `
  <div class="devices-row" style="grid-template-columns:repeat(${Math.min(topDevs.length+(otherW>10?1:0), parseInt(c.max_devices)||6)},1fr)">
    ${topDevs.map(d => {
      const pw = parseFloat(d.power_w ?? d.current_power ?? 0)||0;
      const type = _evcType(d.name||d.label||'', d.brand||'');
      return `<div class="dev-cell">
        ${_evcIcon(type, true, 32)}
        <div class="dev-name">${d.name||d.label||'Apparaat'}</div>
        <div class="dev-pow">${fmtW(pw)}</div>
      </div>`;
    }).join('')}
    ${otherW > 10 ? `<div class="other-cell">
      <svg width="32" height="32" viewBox="0 0 36 36"><rect x="4" y="4" width="28" height="28" rx="4" fill="rgba(100,100,110,.3)" stroke="rgba(120,120,130,.5)" stroke-width="1.2"/>
        <text x="18" y="22" text-anchor="middle" font-size="13" fill="rgba(163,163,163,.7)" font-family="sans-serif">…</text></svg>
      <div class="dev-name">Overig</div>
      <div class="dev-pow">${fmtW(otherW)}</div>
    </div>` : ''}
  </div>` : ''}

  <div class="footer">
    <span>${topDevs.length} apparaten actief</span>
    <span>EVC v${EVC_VER}</span>
  </div>
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() {
    const el = document.createElement('cloudems-energy-visual-card-editor');
    return el;
  }
  static getStubConfig() { return {}; }
}

class CloudemsEnergyVisualCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._r(); }
  _r() {
    if (!this.shadowRoot) this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-bottom:6px}</style>
<label>Titel</label><input id="t" value="${this._config?.title||'⚡ Energiestroom'}"/>
<label>Max apparaten (2-8)</label><input id="md" type="number" min="2" max="8" value="${this._config?.max_devices||6}"/>`;
    const fire = () => this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:{
      ...this._config,
      title: this.shadowRoot.getElementById('t').value,
      max_devices: parseInt(this.shadowRoot.getElementById('md').value)||6,
    }}}));
    ['t','md'].forEach(id => this.shadowRoot.getElementById(id).addEventListener('input', fire));
  }
}

if (!customElements.get('cloudems-energy-visual-card')) customElements.define('cloudems-energy-visual-card', CloudemsEnergyVisualCard);
if (!customElements.get('cloudems-energy-visual-card-editor')) customElements.define('cloudems-energy-visual-card-editor', CloudemsEnergyVisualCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-energy-visual-card',
  name: 'CloudEMS Energy Visual',
  description: 'Energiestroom met animaties en NILM apparaat-nodes',
  preview: true,
});
