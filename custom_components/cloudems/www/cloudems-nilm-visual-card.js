// CloudEMS NILM Visual Card v1.1.0
// Animated device icons per type/brand — washer, dishwasher, dryer, TV, router, NAS, fridge, boiler, EV, switch, generic

const NVC_VERSION = '1.1.0';


// ── Brand color map ───────────────────────────────────────────────────────────
const NVC_BRAND = {
  // washing machines / dryers
  'miele':      { color: '#e63946', short: 'Miele' },
  'bosch':      { color: '#007bc0', short: 'Bosch' },
  'siemens':    { color: '#009999', short: 'Siemens' },
  'samsung':    { color: '#1428a0', short: 'Samsung' },
  'lg':         { color: '#a50034', short: 'LG' },
  'aeg':        { color: '#cc0000', short: 'AEG' },
  'electrolux': { color: '#005eb8', short: 'Electrolux' },
  'whirlpool':  { color: '#003399', short: 'Whirlpool' },
  'beko':       { color: '#e31e25', short: 'Beko' },
  'zanussi':    { color: '#1b468c', short: 'Zanussi' },
  // routers / network
  'ubiquiti':   { color: '#0559c9', short: 'Ubiquiti' },
  'unifi':      { color: '#0559c9', short: 'UniFi' },
  'tp-link':    { color: '#44aa00', short: 'TP-Link' },
  'fritzbox':   { color: '#e3001a', short: 'Fritz!' },
  'fritz':      { color: '#e3001a', short: 'Fritz!' },
  'asus':       { color: '#00adef', short: 'Asus' },
  'netgear':    { color: '#8c2299', short: 'Netgear' },
  // NAS / servers
  'synology':   { color: '#b5a642', short: 'Synology' },
  'qnap':       { color: '#00a651', short: 'QNAP' },
  'proxmox':    { color: '#e57000', short: 'Proxmox' },
  // TVs
  'sony':       { color: '#ffffff', short: 'Sony' },
  'philips':    { color: '#0050a0', short: 'Philips' },
  'panasonic':  { color: '#003087', short: 'Panasonic' },
  'hisense':    { color: '#ff6600', short: 'Hisense' },
  'tcl':        { color: '#dc0028', short: 'TCL' },
  'loewe':      { color: '#c8a800', short: 'Loewe' },
  // fridges
  'liebherr':   { color: '#009fe3', short: 'Liebherr' },
  'smeg':       { color: '#e8004d', short: 'Smeg' },
  // boilers
  'ariston':    { color: '#e31837', short: 'Ariston' },
  'vaillant':   { color: '#007a33', short: 'Vaillant' },
  'nefit':      { color: '#0050a0', short: 'Nefit' },
  'intergas':   { color: '#005587', short: 'Intergas' },
  // EV chargers
  'easee':      { color: '#00b4d8', short: 'Easee' },
  'alfen':      { color: '#003082', short: 'Alfen' },
  'wallbox':    { color: '#2b2d42', short: 'Wallbox' },
  'evbox':      { color: '#6cb33f', short: 'EVBox' },
  // generic
  'default':    { color: '#64748b', short: '' },
};

function _nvcBrand(brandStr) {
  if (!brandStr) return NVC_BRAND.default;
  const lower = brandStr.toLowerCase();
  for (const key of Object.keys(NVC_BRAND)) {
    if (lower.includes(key)) return NVC_BRAND[key];
  }
  return { color: '#64748b', short: brandStr.split(' ')[0].substring(0, 8) };
}

// ── Icon SVG builders ────────────────────────────────────────────────────────
function _nvcIcon(type, on, w = 48) {
  const s = on ? 1 : 0.35;
  const c = (r,g,b,a=1) => `rgba(${r},${g},${b},${a*s})`;
  const green = c(29,158,117), blue = c(55,138,221), amber = c(239,159,39),
        red = c(226,75,74), white = c(255,255,255), gray = c(120,120,130),
        dim = c(80,80,90);

  const T = {
    washer: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="4" width="40" height="40" rx="6" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="6" y="6" width="12" height="4" rx="1" fill="${on?amber:dim}"/>
      <circle cx="24" cy="28" r="13" fill="none" stroke="${gray}" stroke-width="2"/>
      <circle cx="24" cy="28" r="9" fill="none" stroke="${on?green:dim}" stroke-width="1.5">
        ${on?`<animateTransform attributeName="transform" type="rotate" from="0 24 28" to="360 24 28" dur="2s" repeatCount="indefinite"/>`:''}
      </circle>
      <circle cx="24" cy="19" r="2" fill="${on?green:dim}"/>
      <circle cx="24" cy="37" r="2" fill="${on?green:dim}"/>
    </svg>`,

    dishwasher: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="4" width="40" height="40" rx="6" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="8" y="8" width="32" height="8" rx="3" fill="${c(50,50,60)}" stroke="${gray}" stroke-width="1"/>
      <rect x="10" y="20" width="28" height="2" rx="1" fill="${gray}"/>
      <rect x="10" y="26" width="28" height="2" rx="1" fill="${gray}"/>
      <rect x="10" y="32" width="28" height="2" rx="1" fill="${gray}"/>
      <circle cx="20" cy="12" r="2" fill="${on?blue:dim}"/>
      <rect cx="24" cy="29" width="${on?'28':'0'}" height="2" rx="1" fill="${on?green:dim}" x="10">
        ${on?`<animate attributeName="width" values="0;28;0" dur="1.2s" repeatCount="indefinite"/>`:''}
      </rect>
    </svg>`,

    dryer: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="4" width="40" height="40" rx="6" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="6" y="6" width="12" height="4" rx="1" fill="${on?amber:dim}"/>
      <circle cx="24" cy="28" r="13" fill="none" stroke="${gray}" stroke-width="2"/>
      <circle cx="24" cy="28" r="9" fill="none" stroke="${on?amber:dim}" stroke-width="1.5">
        ${on?`<animateTransform attributeName="transform" type="rotate" from="360 24 28" to="0 24 28" dur="2.5s" repeatCount="indefinite"/>`:''}
      </circle>
      ${on?`<circle cx="24" cy="28" r="4" fill="${red}"><animate attributeName="r" values="3;5;3" dur="1s" repeatCount="indefinite"/></circle>`:`<circle cx="24" cy="28" r="4" fill="${dim}"/>`}
    </svg>`,

    tv: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="8" width="40" height="26" rx="4" fill="${c(20,20,30)}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="7" y="11" width="34" height="20" rx="2" fill="${on?c(15,25,40):c(10,10,15)}"/>
      ${on?`<rect x="7" y="11" width="34" height="3" fill="${c(56,189,248,0.4)}"><animate attributeName="y" values="11;29;11" dur="2s" repeatCount="indefinite"/></rect>`:''}
      <rect x="20" y="34" width="8" height="4" rx="1" fill="${gray}"/>
      <rect x="14" y="38" width="20" height="2" rx="1" fill="${gray}"/>
      <circle cx="38" cy="34" r="2" fill="${on?green:dim}"/>
    </svg>`,

    router: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="6" y="20" width="36" height="16" rx="4" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="14" y="8" width="3" height="14" rx="1" fill="${gray}"/>
      <rect x="31" y="8" width="3" height="14" rx="1" fill="${gray}"/>
      <circle cx="16" cy="30" r="2.5" fill="${on?green:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.2;1" dur="1.1s" repeatCount="indefinite"/>`:''}
      </circle>
      <circle cx="24" cy="30" r="2.5" fill="${on?blue:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.2;1" dur="1.1s" begin="0.4s" repeatCount="indefinite"/>`:''}
      </circle>
      <circle cx="32" cy="30" r="2.5" fill="${on?amber:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.2;1" dur="1.1s" begin="0.8s" repeatCount="indefinite"/>`:''}
      </circle>
    </svg>`,

    nas: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="8" y="4" width="32" height="40" rx="4" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      ${[10,18,26,34].map((y,i)=>`
      <rect x="11" y="${y}" width="22" height="6" rx="2" fill="${c(40,40,50)}" stroke="${gray}" stroke-width="0.5"/>
      <circle cx="28" cy="${y+3}" r="2" fill="${on?[green,blue,green,amber][i]:dim}">
        ${on?`<animate attributeName="opacity" values="1;0.3;1" dur="${1.5+i*0.3}s" repeatCount="indefinite"/>`:''}
      </circle>`).join('')}
    </svg>`,

    fridge: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="8" y="4" width="32" height="40" rx="6" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="8" y="4" width="32" height="16" rx="6" fill="${c(30,35,45)}" stroke="${gray}" stroke-width="1.5"/>
      <line x1="8" y1="20" x2="40" y2="20" stroke="${gray}" stroke-width="1.5"/>
      <rect x="34" y="10" width="3" height="8" rx="1.5" fill="${gray}"/>
      <rect x="34" y="24" width="3" height="12" rx="1.5" fill="${gray}"/>
      ${on?`<text x="20" y="16" font-size="10" fill="${blue}" font-family="sans-serif">❄</text>`:''}
      <circle cx="14" cy="44" r="2" fill="${on?green:dim}"/>
    </svg>`,

    boiler: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <ellipse cx="24" cy="26" rx="16" ry="18" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="8" y="4" width="32" height="6" rx="3" fill="${gray}"/>
      ${on?`<ellipse cx="24" cy="32" rx="12" ry="10" fill="${c(234,99,39,0.3)}">
        <animate attributeName="ry" values="8;12;8" dur="2s" repeatCount="indefinite"/>
      </ellipse>`:''}
      <circle cx="24" cy="44" r="4" fill="${c(40,40,50)}" stroke="${gray}" stroke-width="1"/>
      <circle cx="24" cy="26" r="6" fill="none" stroke="${on?amber:dim}" stroke-width="2"/>
      <circle cx="24" cy="26" r="2" fill="${on?amber:dim}"/>
    </svg>`,

    ev: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="14" width="36" height="18" rx="4" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="8" y="10" width="24" height="8" rx="3" fill="${c(40,45,55)}"/>
      <rect x="40" y="20" width="5" height="6" rx="2" fill="${gray}"/>
      <circle cx="12" cy="36" r="5" fill="${c(30,30,35)}" stroke="${gray}" stroke-width="1.5"/>
      <circle cx="12" cy="36" r="2" fill="${gray}"/>
      <circle cx="34" cy="36" r="5" fill="${c(30,30,35)}" stroke="${gray}" stroke-width="1.5"/>
      <circle cx="34" cy="36" r="2" fill="${gray}"/>
      <rect x="10" y="18" width="${on?'24':'8'}" height="6" rx="2" fill="${on?green:dim}">
        ${on?`<animate attributeName="width" values="4;24;4" dur="2.5s" repeatCount="indefinite"/>`:''}
      </rect>
      ${on?`<text x="22" y="24" font-size="9" fill="white" text-anchor="middle" font-family="sans-serif">⚡</text>`:''}
    </svg>`,

    ebike: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <circle cx="12" cy="34" r="9" fill="none" stroke="${gray}" stroke-width="2"/>
      <circle cx="36" cy="34" r="9" fill="none" stroke="${gray}" stroke-width="2"/>
      <circle cx="12" cy="34" r="3" fill="${on?green:dim}"/>
      <circle cx="36" cy="34" r="3" fill="${on?green:dim}"/>
      <path d="M24 14 L18 26 L12 34" fill="none" stroke="${gray}" stroke-width="2" stroke-linecap="round"/>
      <path d="M24 14 L30 26 L36 34" fill="none" stroke="${gray}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="24" cy="12" r="4" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="20" y="20" width="8" height="5" rx="1" fill="${on?c(55,138,221):dim}">
        ${on?`<animate attributeName="width" values="2;8;2" dur="2s" repeatCount="indefinite"/>`:''}</rect>
    </svg>`,

        switch: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="6" y="16" width="36" height="16" rx="8" fill="${on?c(29,158,117,0.3):dim}" stroke="${on?green:gray}" stroke-width="1.5"/>
      <circle cx="${on?32:16}" cy="24" r="7" fill="${on?green:gray}">
        <animate attributeName="cx" values="${on?'16;32':'32;16'}" dur="0.2s" fill="freeze"/>
      </circle>
    </svg>`,

    heatpump: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="12" width="40" height="24" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="7" y="15" width="20" height="18" rx="3" fill="${c(30,35,45)}"/>
      <circle cx="17" cy="24" r="6" fill="none" stroke="${on?blue:dim}" stroke-width="1.5">
        ${on?`<animateTransform attributeName="transform" type="rotate" from="0 17 24" to="360 17 24" dur="3s" repeatCount="indefinite"/>`:''}
      </circle>
      <rect x="30" y="16" width="10" height="16" rx="2" fill="${c(35,40,50)}"/>
      ${[18,22,26,30].map(y=>`<line x1="31" y1="${y}" x2="39" y2="${y}" stroke="${gray}" stroke-width="1"/>`).join('')}
    </svg>`,

    airco: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="4" y="10" width="40" height="20" rx="5" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <rect x="7" y="13" width="26" height="14" rx="3" fill="${c(25,30,40)}"/>
      ${on?[16,20,24,28].map(y=>`<line x1="8" y1="${y}" x2="32" y2="${y}" stroke="${c(56,189,248,0.5)}" stroke-width="1"/>`).join(''):''}
      <circle cx="36" cy="18" r="2" fill="${on?green:dim}"/>
      ${on?`<text x="8" y="42" font-size="9" fill="${blue}" font-family="sans-serif">❄ ${''}</text>`:''}
    </svg>`,

    default: () => `<svg width="${w}" height="${w}" viewBox="0 0 48 48">
      <rect x="6" y="6" width="36" height="36" rx="6" fill="${dim}" stroke="${gray}" stroke-width="1.5"/>
      <circle cx="24" cy="22" r="8" fill="none" stroke="${on?green:dim}" stroke-width="2"/>
      <line x1="24" y1="14" x2="24" y2="10" stroke="${on?green:dim}" stroke-width="2" stroke-linecap="round"/>
      <line x1="24" y1="30" x2="24" y2="34" stroke="${on?green:dim}" stroke-width="2" stroke-linecap="round"/>
      <line x1="16" y1="22" x2="12" y2="22" stroke="${on?green:dim}" stroke-width="2" stroke-linecap="round"/>
      <line x1="32" y1="22" x2="36" y2="22" stroke="${on?green:dim}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="24" cy="22" r="3" fill="${on?green:dim}"/>
      <circle cx="16" cy="36" r="2" fill="${on?c(29,158,117):dim}"/>
    </svg>`
  };
  return (T[type] || T.default)();
}

// Map device name/label to icon type
function _nvcType(name, brand) {
  const n = (name||'').toLowerCase(), b = (brand||'').toLowerCase(), nb = n+' '+b;
  // Washing & laundry
  if (/wasmach|washer|washing|miele w|bosch w|siemens w/.test(nb)) return 'washer';
  if (/vaatwa|dishwash|vaatwas|geschirrsp/.test(nb)) return 'dishwasher';
  if (/droog|dryer|droger|tumble|lg heat/.test(nb)) return 'dryer';
  // Entertainment
  if (/tv|television|televisie|samsung qled|lg oled|philips ambi|bravia/.test(nb)) return 'tv';
  // Network
  if (/router|modem|wifi|unifi|ubiquiti|fritzbox|fritz!|draytek/.test(nb)) return 'router';
  // Servers / NAS
  if (/nas|server|proxmox|synology|qnap|truenas|plex|homeserver/.test(nb)) return 'nas';
  // Cold appliances
  if (/koel|fridge|koelkast|ijskast|vriezer|freezer|liebherr/.test(nb)) return 'fridge';
  // Hot water
  if (/boiler|warmwater|hot.?water|ariston|daikin dhw|atlantic/.test(nb)) return 'boiler';
  // EV
  if (/ev|elektrisch.?auto|wallbox|easee|alfen|zaptec|mennekes|type.?2|laadpaal/.test(nb)) return 'ev';
  // E-bike
  if (/ebike|e-bike|scooter|pedelec|brompton|gazelle|batavus/.test(nb)) return 'ebike';
  // HVAC
  if (/warmtepomp|heat.?pump|wp|daikin wp|mitsubishi wp/.test(nb)) return 'heatpump';
  if (/airco|ac|split|aircond|mitsubishi ac|lg ac|toshiba ac|samsung wind/.test(nb)) return 'airco';
  // Generic switch/plug
  if (/schakelaar|switch|plug|stekker|shelly|sonoff|tasmota/.test(nb)) return 'switch';
  return 'default';
}

// ── Card definition ───────────────────────────────────────────────────────────
class CloudemsNilmVisualCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:'open' }); this._p = ''; }

  setConfig(c) {
    this._cfg = { title:'📡 Apparaten Live', show_off:false, columns:3, ...c };
    this._r();
  }

  set hass(h) {
    this._hass = h;
    const k = JSON.stringify([
      h.states['sensor.cloudems_nilm_running_devices']?.last_changed,
      h.states['sensor.cloudems_nilm_devices']?.last_changed,
    ]);
    if (k !== this._p) { this._p = k; this._r(); }
  }

  _getDevices() {
    const h = this._hass;
    const all  = h?.states['sensor.cloudems_nilm_devices']?.attributes?.devices || [];
    const running = h?.states['sensor.cloudems_nilm_running_devices']?.attributes?.devices || [];
    const runMap = {};
    running.forEach(d => { runMap[d.name||d.label||d.id] = d; });

    return all.map(d => {
      const key = d.name || d.label || d.id || '';
      const r = runMap[key];
      return {
        ...d,
        is_on: !!r,
        current_power: r?.power_w ?? r?.current_power ?? d.power_w ?? d.current_power ?? d.avg_power_w ?? 0,
        type: _nvcType(key, d.brand || ''),
      };
    }).sort((a,b) => (b.is_on?1:0) - (a.is_on?1:0) || (b.current_power||0) - (a.current_power||0));
  }

  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh) return;
    if (!h) { sh.innerHTML = '<div style="padding:16px;font-size:12px;color:#666">Laden…</div>'; return; }

    const devs = this._getDevices();
    const shown = c.show_off ? devs : devs.filter(d => d.is_on || devs.indexOf(d) < 9);
    const cols = Math.min(4, Math.max(2, parseInt(c.columns)||3));
    const totalW = devs.filter(d=>d.is_on).reduce((s,d)=>s+(parseFloat(d.current_power)||0),0);
    const onCount = devs.filter(d=>d.is_on).length;

    const fmtW = w => w >= 1000 ? (w/1000).toFixed(1)+' kW' : Math.round(w)+' W';

    sh.innerHTML = `
<style>
  * { box-sizing: border-box; margin:0; padding:0 }
  :host { display:block; width:100% }
  .card { background:rgb(28,28,30); border:1px solid rgba(255,255,255,.07); border-radius:16px; overflow:hidden; font-family:var(--primary-font-family,system-ui,sans-serif) }
  .hdr { display:flex; align-items:center; gap:10px; padding:12px 16px 10px; border-bottom:1px solid rgba(255,255,255,.07) }
  .hdr-title { font-size:12px; font-weight:600; color:#fff; flex:1 }
  .hdr-badge { font-size:11px; font-weight:600; padding:2px 8px; border-radius:8px; background:rgba(29,158,117,.2); color:#4ade80 }
  .hdr-watt  { font-size:11px; color:rgba(255,255,255,.4) }
  .grid { display:grid; grid-template-columns:repeat(${cols},1fr); gap:1px; background:rgba(255,255,255,.06) }
  .cell { background:rgb(28,28,30); padding:12px 8px 10px; display:flex; flex-direction:column; align-items:center; gap:5px; cursor:default; transition:background .15s; position:relative }
  .cell.on { background:rgb(32,36,32) }
  .cell:active { background:rgba(255,255,255,.05) }
  .cell-name { font-size:10px; font-weight:500; color:rgba(163,163,163,.9); text-align:center; line-height:1.3; max-width:68px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
  .cell-name.on { color:#fff }
  .cell-power { font-size:11px; font-weight:600; color:rgba(29,158,117,1) }
  .cell-power.off { color:rgba(100,100,110,.6); font-weight:400; font-size:10px }
  .cell-brand { font-size:9px; color:rgba(120,120,130,.6); text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:68px }
  .cell-conf { font-size:9px; color:rgba(100,100,110,.5) }
  .dot { width:5px; height:5px; border-radius:50%; position:absolute; top:7px; right:7px }
  .dot.on { background:#4ade80 }
  .dot.off { background:rgba(80,80,90,.5) }
  .footer { display:flex; justify-content:space-between; padding:7px 14px; border-top:1px solid rgba(255,255,255,.06); font-size:10px; color:rgba(100,100,110,.7) }
  .empty { padding:20px; text-align:center; font-size:12px; color:rgba(120,120,130,.6) }
</style>
<div class="card">
  <div class="hdr">
    <span style="font-size:14px">📡</span>
    <span class="hdr-title">${c.title}</span>
    ${onCount>0 ? `<span class="hdr-badge">${onCount} actief</span>` : ''}
    ${totalW>0 ? `<span class="hdr-watt">${fmtW(totalW)}</span>` : ''}
  </div>
  ${shown.length===0 ? '<div class="empty">Geen NILM-apparaten geconfigureerd</div>' : `
  <div class="grid">
    ${shown.map(d => {
      const pw = parseFloat(d.current_power) || 0;
      const conf = d.confidence != null ? Math.round(d.confidence*100) : null;
      const brand = d.brand || '';
      const bInfo = _nvcBrand(d.brand);
      const maxCellW = 2500;
      const barPct = d.is_on && pw > 0 ? Math.min(100, pw / maxCellW * 100) : 0;
      const barCol = pw > 1500 ? '#f87171' : pw > 800 ? '#fbbf24' : '#4ade80';
      return `<div class="cell${d.is_on?' on':''}">
        <div class="dot ${d.is_on?'on':'off'}"></div>
        ${_nvcIcon(d.type, d.is_on, 44)}
        <div class="cell-name${d.is_on?' on':''}">${d.name||d.label||'Apparaat'}</div>
        ${d.is_on && pw>0
          ? `<div class="cell-power">${fmtW(pw)}</div>`
          : `<div class="cell-power off">uit</div>`}
        ${barPct > 0 ? `<div style="width:100%;height:3px;background:rgba(255,255,255,.08);border-radius:1.5px;margin-top:1px"><div style="height:3px;background:${barCol};border-radius:1.5px;width:${barPct.toFixed(0)}%"></div></div>` : ''}
        ${brand ? `<div class="cell-brand" style="color:${bInfo.color};opacity:${d.is_on?'0.9':'0.4'}">${bInfo.short||brand}</div>` : ''}
        ${conf!=null ? `<div class="cell-conf">${conf}%</div>` : ''}
      </div>`;
    }).join('')}
  </div>`}
  <div class="footer">
    <span>${devs.length} apparaten herkend</span>
    <span>NILM v${NVC_VERSION}</span>
  </div>
</div>`;
  }

  getCardSize() {
    const d = this._getDevices?.() || [];
    const cols = Math.min(4, parseInt(this._cfg?.columns||3));
    return Math.ceil(d.length/cols) + 2;
  }

  static getConfigElement() {
    const el = document.createElement('cloudems-nilm-visual-card-editor');
    return el;
  }
  static getStubConfig() { return {}; }
}

class CloudemsNilmVisualCardEditor extends HTMLElement {
  setConfig(c) { this._config = c; this._r(); }
  _r() {
    if (!this.shadowRoot) this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML = `
<style>label{display:block;margin:8px 0 2px;font-size:12px;color:#aaa}
input,select{width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px;margin-bottom:6px}</style>
<label>Titel</label>
<input id="t" value="${this._config?.title||'📡 Apparaten Live'}"/>
<label>Kolommen (2-4)</label>
<select id="cols">
  ${[2,3,4].map(n=>`<option value="${n}"${(this._config?.columns||3)==n?' selected':''}>${n}</option>`).join('')}
</select>
<label>Toon uitgeschakeld</label>
<select id="off">
  <option value="false"${!this._config?.show_off?' selected':''}>Alleen aan</option>
  <option value="true"${this._config?.show_off?' selected':''}>Alles</option>
</select>`;
    const fire = () => this.dispatchEvent(new CustomEvent('config-changed', {detail:{config:{
      ...this._config,
      title: this.shadowRoot.getElementById('t').value,
      columns: parseInt(this.shadowRoot.getElementById('cols').value),
      show_off: this.shadowRoot.getElementById('off').value === 'true',
    }}}));
    ['t','cols','off'].forEach(id => this.shadowRoot.getElementById(id).addEventListener('input', fire));
  }
}

if (!customElements.get('cloudems-nilm-visual-card')) customElements.define('cloudems-nilm-visual-card', CloudemsNilmVisualCard);
if (!customElements.get('cloudems-nilm-visual-card-editor')) customElements.define('cloudems-nilm-visual-card-editor', CloudemsNilmVisualCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-nilm-visual-card',
  name: 'CloudEMS NILM Visual',
  description: 'Animated device icons — washer, TV, router, NAS, fridge, boiler, EV and more',
  preview: true,
});
