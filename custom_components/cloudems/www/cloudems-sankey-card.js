/**
 * CloudEMS Sankey Energy Flow Card
 * Toont energie-stromen als Sankey diagram: PV/net → huis/batterij/apparaten
 * Geïnspireerd op Sankey Chart Card maar gebouwd op CloudEMS data
 */

const SANKEY_STYLES = `
  :host { display:block; }
  .card { background:var(--ha-card-background,#1a2332); border-radius:12px; padding:14px; font-family:var(--primary-font-family,sans-serif); color:#e2e8f0; }
  .card-title { font-size:12px; font-weight:600; color:rgba(255,255,255,.45); text-transform:uppercase; letter-spacing:.06em; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; }
  .sankey-wrap { width:100%; overflow:hidden; position:relative; }
  svg text { font-family:inherit; }
  .node-label { font-size:11px; fill:#e2e8f0; }
  .node-value { font-size:10px; fill:rgba(255,255,255,.5); }
  .flow-path { opacity:0.55; transition:opacity .2s; }
  .flow-path:hover { opacity:0.85; }
  .legend { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
  .leg { display:flex; align-items:center; gap:4px; font-size:10px; color:rgba(255,255,255,.5); }
  .leg-dot { width:8px; height:8px; border-radius:50%; }
  .animate-flow { animation: flow-anim 3s linear infinite; }
  @keyframes flow-anim { from{stroke-dashoffset:100} to{stroke-dashoffset:0} }
`;

const COLORS = {
  solar:   '#f0c040',
  grid:    '#60a5fa',
  battery: '#34d399',
  house:   '#94a3b8',
  boiler:  '#f97316',
  ev:      '#a78bfa',
  export:  '#06b6d4',
  loss:    '#475569',
};

class CloudemsSankeyCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); this._cfg = {}; }

  static getConfigElement() {
    const e = document.createElement('cloudems-sankey-card-editor');
    return e;
  }
  static getStubConfig() { return { title: 'Energie Stromen' }; }
  setConfig(cfg) { this._cfg = cfg || {}; }
  set hass(h) { this._hass = h; this._render(); }

  _w(id, fallback=0) {
    const s = this._hass?.states[id];
    if (!s || s.state === 'unavailable' || s.state === 'unknown') return fallback;
    return Math.abs(parseFloat(s.state) || fallback);
  }

  _render() {
    const h = this._hass;
    if (!h) return;
    const sh = this.shadowRoot;

    // Read power values
    const solar_w   = this._w('sensor.cloudems_zon_vermogen') || this._w('sensor.cloudems_solar_power');
    const grid_imp  = Math.max(0, parseFloat(h.states['sensor.cloudems_net_vermogen']?.state || 0));
    const grid_exp  = Math.max(0, -(parseFloat(h.states['sensor.cloudems_net_vermogen']?.state || 0)));
    const bat_w     = parseFloat(h.states['sensor.cloudems_battery_power']?.state || 0);
    const bat_chg   = Math.max(0,  bat_w);
    const bat_dis   = Math.max(0, -bat_w);

    // House breakdown from coordinator
    const house_w   = this._w('sensor.cloudems_home_rest') || this._w('sensor.cloudems_house_power');
    const boiler_w  = this._w('sensor.cloudems_boiler_efficiency') || this._w('sensor.cloudems_boiler_power');
    const ev_w      = this._w('sensor.cloudems_ev_session');
    const other_w   = Math.max(0, house_w - boiler_w - ev_w);

    // Total sources and sinks
    const total_in  = solar_w + grid_imp + bat_dis;
    const total_out = house_w + bat_chg + grid_exp;
    const scale     = Math.max(total_in, total_out, 100);

    // SVG dimensions
    const W = 340, H = 200;
    const COL1_X = 30, COL2_X = 150, COL3_X = 270;
    const NODE_W = 14;

    // Build nodes
    const sources = [
      { id:'solar',   label:'PV',    val:solar_w,  color:COLORS.solar },
      { id:'grid',    label:'Net',   val:grid_imp, color:COLORS.grid },
      { id:'bat_dis', label:'Accu ↓',val:bat_dis,  color:COLORS.battery },
    ].filter(n => n.val > 5);

    const targets = [
      { id:'house',  label:'Huis',    val:other_w, color:COLORS.house },
      { id:'boiler', label:'Boiler',  val:boiler_w,color:COLORS.boiler },
      { id:'ev',     label:'EV',      val:ev_w,    color:COLORS.ev },
      { id:'bat_chg',label:'Accu ↑',  val:bat_chg, color:COLORS.battery },
      { id:'export', label:'Teruglev',val:grid_exp,color:COLORS.export },
    ].filter(n => n.val > 5);

    // Layout nodes vertically centered
    const layoutNodes = (nodes, x) => {
      const totalH = H - 30;
      const totalVal = nodes.reduce((s,n) => s+n.val, 0) || 1;
      const GAP = 6;
      let y = 15;
      return nodes.map(n => {
        const h_px = Math.max(14, (n.val / totalVal) * (totalH - GAP * nodes.length));
        const node = { ...n, x, y, h: h_px, cy: y + h_px/2 };
        y += h_px + GAP;
        return node;
      });
    };

    const srcNodes = layoutNodes(sources, COL1_X);
    const tgtNodes = layoutNodes(targets, COL3_X);

    // Simple flow allocation: distribute source proportionally to targets
    const flows = [];
    const tgtTotalVal = tgtNodes.reduce((s,n) => s+n.val, 0) || 1;
    srcNodes.forEach(src => {
      tgtNodes.forEach(tgt => {
        // Simple proportional split
        const flow_w = src.val * (tgt.val / tgtTotalVal);
        if (flow_w > 10) {
          flows.push({ src, tgt, val: flow_w });
        }
      });
    });

    // Draw SVG
    const fmt = w => w >= 1000 ? `${(w/1000).toFixed(1)}kW` : `${Math.round(w)}W`;

    const nodeRects = (nodes, x) => nodes.map(n => `
      <rect x="${x}" y="${n.y}" width="${NODE_W}" height="${n.h}" rx="3" fill="${n.color}" opacity="0.9"/>
      <text class="node-label" x="${x + (x < W/2 ? NODE_W+5 : -5)}" y="${n.cy+1}" dominant-baseline="middle" text-anchor="${x < W/2 ? 'start' : 'end'}">${n.label}</text>
      <text class="node-value" x="${x + (x < W/2 ? NODE_W+5 : -5)}" y="${n.cy+13}" dominant-baseline="middle" text-anchor="${x < W/2 ? 'start' : 'end'}">${fmt(n.val)}</text>
    `).join('');

    // Flows as cubic bezier paths
    const srcOffsets = {}, tgtOffsets = {};
    srcNodes.forEach(n => srcOffsets[n.id] = n.y);
    tgtNodes.forEach(n => tgtOffsets[n.id] = n.y);

    const flowPaths = flows.map(f => {
      const srcTotal = srcNodes.find(n => n.id === f.src.id)?.val || 1;
      const tgtTotal = tgtNodes.find(n => n.id === f.tgt.id)?.val || 1;
      const sw = Math.max(2, (f.val / srcTotal) * f.src.h);
      const tw = Math.max(2, (f.val / tgtTotal) * f.tgt.h);

      const x1 = COL1_X + NODE_W;
      const y1 = (srcOffsets[f.src.id] || f.src.y) + sw/2;
      const x2 = COL3_X;
      const y2 = (tgtOffsets[f.tgt.id] || f.tgt.y) + tw/2;

      srcOffsets[f.src.id] = (srcOffsets[f.src.id] || f.src.y) + sw;
      tgtOffsets[f.tgt.id] = (tgtOffsets[f.tgt.id] || f.tgt.y) + tw;

      const cx = (x1 + x2) / 2;
      const grad = `grad_${f.src.id}_${f.tgt.id}`;

      return `
        <defs>
          <linearGradient id="${grad}" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="${f.src.color}" stop-opacity="0.7"/>
            <stop offset="100%" stop-color="${f.tgt.color}" stop-opacity="0.7"/>
          </linearGradient>
        </defs>
        <path class="flow-path" 
          d="M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}"
          stroke="url(#${grad})" stroke-width="${Math.max(2,(sw+tw)/2)}" fill="none"/>
      `;
    }).join('');

    const title = this._cfg.title || 'Energie Stromen';
    const totalStr = `${fmt(solar_w)} PV · ${fmt(house_w)} huis`;

    sh.innerHTML = `
      <style>${SANKEY_STYLES}</style>
      <div class="card">
        <div class="card-title">
          <span>⚡ ${title}</span>
          <span style="font-size:10px;color:rgba(255,255,255,.3)">${totalStr}</span>
        </div>
        <div class="sankey-wrap">
          <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">
            ${flowPaths}
            ${nodeRects(srcNodes, COL1_X)}
            ${nodeRects(tgtNodes, COL3_X - NODE_W)}
          </svg>
        </div>
        <div class="legend">
          ${Object.entries(COLORS).map(([k,c]) => `<div class="leg"><div class="leg-dot" style="background:${c}"></div>${k}</div>`).join('')}
        </div>
      </div>
    `;
  }

  getCardSize() { return 3; }
}

customElements.define('cloudems-sankey-card', CloudemsSankeyCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'cloudems-sankey-card',
  name: 'CloudEMS Sankey Energie Stromen',
  description: 'Sankey diagram van energie-stromen in je huis',
});
