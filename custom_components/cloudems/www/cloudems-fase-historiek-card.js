// CloudEMS Fase Balans Historiek Card v5.4.96
const CARD_FASE_HISTORIEK_VERSION = '5.5.318';
// Live sparkline history of L1/L2/L3 currents and imbalance
// v2.0.0: persistent storage via window.storage (survives restarts + page reloads)
//         Future-proof: coordinator kan history via sensor attribuut aanleveren (cloud)

const _FASE_STORAGE_KEY = 'cloudems-fase-hist-v1';
const _FASE_MAX_SAMPLES = 720;   // 720 × 5s = 1 uur
const _FASE_PUSH_INTERVAL = 5000; // ms

class CloudemsFaseHistoriekCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._p = '';
    this._hist = { t: [], l1: [], l2: [], l3: [], imb: [] };
    this._lastPush = 0;
  }

  setConfig(c) { this._cfg = { title: '⚡ Fase Balans Historiek', ...c }; this._r(); }

  // ── Data layer — vervang deze twee methoden voor cloud-integratie ──────────
  // _loadHistory en _saveHistory zijn vervangen door directe sensor-attribuut lezing
  // De coordinator bewaart de historiek in sensor.cloudems_grid_phase_imbalance.phase_history
  // Dit werkt op elk device/browser en overleeft herstarts
  _getBackendHistory(h) {
    const st = h.states["sensor.cloudems_grid_phase_imbalance"] ||
               h.states["sensor.cloudems_phase_balance"];
    return st?.attributes?.phase_history || null;
  }
  // ─────────────────────────────────────────────────────────────────────────

  _pushSample(l1, l2, l3, imb) {
    const now = Date.now();
    this._hist.t.push(now);
    this._hist.l1.push(l1);
    this._hist.l2.push(l2);
    this._hist.l3.push(l3);
    this._hist.imb.push(imb);
    if (this._hist.t.length > _FASE_MAX_SAMPLES) {
      this._hist.t.shift(); this._hist.l1.shift();
      this._hist.l2.shift(); this._hist.l3.shift(); this._hist.imb.shift();
    }
  }

  set hass(h) {
    this._hass = h;
    const st = h.states['sensor.cloudems_grid_phase_imbalance'] ||
               h.states['sensor.cloudems_phase_balance'];
    const k = JSON.stringify(st?.last_changed);
    if (k === this._p) return;
    this._p = k;

    const now = Date.now();
    if (now - this._lastPush >= _FASE_PUSH_INTERVAL) {
      this._lastPush = now;
      const a = st?.attributes || {};
      const phases = a.phase_currents || {};
      const l1  = parseFloat(a.current_l1  ?? phases.L1 ?? phases.l1  ?? 0);
      const l2  = parseFloat(a.current_l2  ?? phases.L2 ?? phases.l2  ?? 0);
      const l3  = parseFloat(a.current_l3  ?? phases.L3 ?? phases.l3  ?? 0);
      const imb = parseFloat(st?.state ?? a.imbalance_a ?? 0);
        this._pushSample(l1, l2, l3, imb);
    }
    this._r();
  }

  _sparkline(values, color, w, h, fillColor) {
    if (values.length < 2) return '';
    const maxV = Math.max(...values, 0.1);
    const minV = Math.min(...values, 0);
    const range = Math.max(maxV - minV, 0.1);
    const pts = values.map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - minV) / range) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `
      ${fillColor ? `<polygon points="${pts} ${w},${h} 0,${h}" fill="${fillColor}" opacity="0.15"/>` : ''}
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  }

  _r() {
    const h = this._hass, c = this._cfg || {};
    const sh = this.shadowRoot; if (!sh || !h) return;

    const st = h.states['sensor.cloudems_grid_phase_imbalance'] ||
               h.states['sensor.cloudems_phase_balance'];
    const a = st?.attributes || {};
    const phases = a.phase_currents || {};
    const l1  = parseFloat(a.current_l1  ?? phases.L1 ?? 0);
    const l2  = parseFloat(a.current_l2  ?? phases.L2 ?? 0);
    const l3  = parseFloat(a.current_l3  ?? phases.L3 ?? 0);
    const imb = parseFloat(st?.state ?? a.imbalance_a ?? 0);
    const balanced = a.balanced ?? (imb < 5);
    const maxA = 25;

    const pq = h.states['sensor.cloudems_power_quality']?.attributes || {};
    const pfAvg = pq.pf_avg;

    const imbCol = imb < 3 ? '#4ade80' : imb < 8 ? '#fbbf24' : '#f87171';
    const barCol = (a) => a > 20 ? '#f87171' : a > 15 ? '#fbbf24' : '#60a5fa';

    const W = 280, H = 50;
    // Gebruik backend historiek (coordinator) als primaire bron — werkt op alle apparaten
    // Valt terug op in-memory buffer als backend nog geen data heeft
    const backendHist = this._getBackendHistory(h);
    const hist = backendHist && backendHist.t && backendHist.t.length >= 2
      ? {
          t:   backendHist.t.map(ts => ts * 1000),  // unix → ms
          l1:  backendHist.l1,
          l2:  backendHist.l2,
          l3:  backendHist.l3,
          imb: backendHist.imb,
        }
      : this._hist;
    const hasHist = hist.t.length >= 2;

    const oldestAgo = hasHist
      ? Math.round((Date.now() - hist.t[0]) / 60000)
      : 0;
    const timeLabel = oldestAgo >= 60
      ? `${Math.floor(oldestAgo/60)}u ${oldestAgo%60}m`
      : `${oldestAgo}m`;

    sh.innerHTML = `
<style>
:host{display:block;width:100%}
.card{background:rgb(34,34,34);border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden;font-family:var(--primary-font-family,sans-serif)}
.hdr{display:flex;align-items:center;gap:10px;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,.07)}
.live{padding:12px 16px 8px}
.phase-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.phase-lbl{font-size:11px;font-weight:600;color:rgba(163,163,163,.7);min-width:20px}
.phase-bar-wrap{flex:1;height:8px;background:rgba(255,255,255,.08);border-radius:4px}
.phase-bar{height:8px;border-radius:4px;transition:width .4s}
.phase-val{font-size:11px;font-weight:600;min-width:44px;text-align:right}
.imb-row{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;background:rgba(255,255,255,.03);border-top:1px solid rgba(255,255,255,.05)}
.chart-wrap{padding:8px 16px 4px}
.chart-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;margin-bottom:4px;display:flex;justify-content:space-between}
svg{width:100%;overflow:visible}
.legend{display:flex;gap:10px;padding:4px 16px 10px;font-size:9px;color:rgba(163,163,163,.5)}
.leg{display:flex;align-items:center;gap:3px}
.leg-line{width:12px;height:2px;border-radius:1px}
</style>
<div class="card">
  <div class="hdr">
    <span style="font-size:13px;font-weight:700;color:#e2e8f0">${c.title || '⚡ Fase Balans Historiek'}</span>
    <span style="margin-left:auto;font-size:12px;font-weight:700;color:${imbCol}">${imb.toFixed(1)} A onbalans</span>
  </div>
  <div class="live">
    ${[['L1',l1,'#60a5fa'],['L2',l2,'#f59e0b'],['L3',l3,'#4ade80']].map(([lbl,val,col])=>`
    <div class="phase-row">
      <span class="phase-lbl">${lbl}</span>
      <div class="phase-bar-wrap"><div class="phase-bar" style="width:${Math.min(100,(val/maxA)*100).toFixed(1)}%;background:${barCol(val)}"></div></div>
      <span class="phase-val" style="color:${barCol(val)}">${val.toFixed(1)} A</span>
    </div>`).join('')}
  </div>
  <div class="imb-row">
    <span style="font-size:11px;color:rgba(163,163,163,.6)">Onbalans</span>
    <span style="font-size:14px;font-weight:700;color:${imbCol}">${imb.toFixed(1)} A</span>
    <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${balanced?'rgba(74,222,128,.15)':'rgba(251,191,36,.15)'};color:${balanced?'#4ade80':'#fbbf24'}">${balanced?'✓ Gebalanceerd':'⚠ Onbalans'}</span>
  </div>
  ${hasHist ? `
  <div class="chart-wrap">
    <div class="chart-title">
      <span>FASE STROMEN — ${timeLabel} HISTORIEK</span>
      <span>${hist.t.length} SAMPLES</span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" style="height:${H}px">
      ${this._sparkline(hist.l1,'#60a5fa',W,H,'#60a5fa')}
      ${this._sparkline(hist.l2,'#f59e0b',W,H,'#f59e0b')}
      ${this._sparkline(hist.l3,'#4ade80',W,H,'#4ade80')}
    </svg>
  </div>
  <div class="chart-wrap" style="padding-top:0">
    <div class="chart-title"><span>ONBALANS</span></div>
    <svg viewBox="0 0 ${W} 30" style="height:30px">
      ${this._sparkline(hist.imb,'#a78bfa',W,30,'#a78bfa')}
    </svg>
  </div>` : `<div style="padding:12px 16px;font-size:11px;color:rgba(163,163,163,.4);text-align:center">Historiek wordt opgebouwd...</div>`}
  <div class="legend">
    ${[['#60a5fa','L1'],['#f59e0b','L2'],['#4ade80','L3'],['#a78bfa','Onbalans']].map(([c,l])=>`<div class="leg"><div class="leg-line" style="background:${c}"></div><span>${l}</span></div>`).join('')}
  </div>
</div>`;
  }

  getCardSize() { return 4; }
  static getConfigElement() {
    const e = document.createElement('cloudems-fase-historiek-card-editor');
    return e;
  }
  static getStubConfig() { return {}; }
}

class CloudemsFaseHistoriekCardEditor extends HTMLElement {
  setConfig(c) {}
  get value() { return {}; }
  connectedCallback() {
    if (!this.innerHTML)
      this.innerHTML = `<p style="font-size:12px;color:#666;padding:8px">Geen configuratie vereist.</p>`;
  }
}

customElements.define('cloudems-fase-historiek-card', CloudemsFaseHistoriekCard);
customElements.define('cloudems-fase-historiek-card-editor', CloudemsFaseHistoriekCardEditor);
