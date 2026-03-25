// CloudEMS Fase Balans Historiek Card v1.0.0
const CARD_FASE_HISTORIEK_VERSION = '5.3.31';
// Live + in-memory sparkline history of L1/L2/L3 currents and imbalance

class CloudemsFaseHistoriekCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._p = "";
    // In-memory ring buffer: 120 samples × 5s = 10 minutes
    this._hist = { t: [], l1: [], l2: [], l3: [], imb: [] };
    this._maxSamples = 120;
    this._lastPush = 0;
  }

  setConfig(c) { this._cfg = { title: "⚡ Fase Balans Historiek", ...c }; this._r(); }

  set hass(h) {
    this._hass = h;
    const st = h.states["sensor.cloudems_grid_phase_imbalance"] ||
                h.states["sensor.cloudems_phase_balance"];
    const k = JSON.stringify(st?.last_changed);
    if (k === this._p) return;
    this._p = k;

    // Push to ring buffer every 5s
    const now = Date.now();
    if (now - this._lastPush >= 5000) {
      this._lastPush = now;
      const a = st?.attributes || {};
      const phases = a.phase_currents || {};
      const l1 = parseFloat(a.current_l1 ?? phases.L1 ?? phases.l1 ?? 0);
      const l2 = parseFloat(a.current_l2 ?? phases.L2 ?? phases.l2 ?? 0);
      const l3 = parseFloat(a.current_l3 ?? phases.L3 ?? phases.l3 ?? 0);
      const imb = parseFloat(st?.state ?? a.imbalance_a ?? 0);

      this._hist.t.push(now);
      this._hist.l1.push(l1);
      this._hist.l2.push(l2);
      this._hist.l3.push(l3);
      this._hist.imb.push(imb);

      // Trim to max samples
      if (this._hist.t.length > this._maxSamples) {
        this._hist.t.shift();
        this._hist.l1.shift();
        this._hist.l2.shift();
        this._hist.l3.shift();
        this._hist.imb.shift();
      }
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

    const st = h.states["sensor.cloudems_grid_phase_imbalance"] ||
                h.states["sensor.cloudems_phase_balance"];
    const a = st?.attributes || {};
    const phases = a.phase_currents || {};
    const l1 = parseFloat(a.current_l1 ?? phases.L1 ?? 0);
    const l2 = parseFloat(a.current_l2 ?? phases.L2 ?? 0);
    const l3 = parseFloat(a.current_l3 ?? phases.L3 ?? 0);
    const imb = parseFloat(st?.state ?? a.imbalance_a ?? 0);
    const balanced = a.balanced ?? (imb < 5);
    const maxA = 25; // typical circuit breaker

    // Power quality from separate sensor
    const pq = h.states["sensor.cloudems_power_quality"]?.attributes || {};
    const pfAvg = pq.pf_avg;

    const imbCol = imb < 3 ? '#4ade80' : imb < 8 ? '#fbbf24' : '#f87171';
    const barCol = (a) => a > 20 ? '#f87171' : a > 15 ? '#fbbf24' : '#60a5fa';

    const W = 280, H = 50;
    const hist = this._hist;
    const hasHist = hist.t.length >= 2;

    // Time label for oldest sample
    const oldestAgo = hasHist
      ? Math.round((Date.now() - hist.t[0]) / 60000)
      : 0;

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
.pf{font-size:10px;color:rgba(163,163,163,.5);min-width:44px;text-align:right}
.imb-row{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;background:rgba(255,255,255,.03);border-top:1px solid rgba(255,255,255,.05)}
.chart-wrap{padding:8px 16px 4px}
.chart-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,255,255,.3);text-transform:uppercase;margin-bottom:4px;display:flex;justify-content:space-between}
svg{width:100%;overflow:visible}
.axis{display:flex;justify-content:space-between;font-size:8px;color:rgba(163,163,163,.3);padding:2px 0}
.legend{display:flex;gap:10px;padding:4px 16px 10px;font-size:9px;color:rgba(163,163,163,.5)}
.leg{display:flex;align-items:center;gap:3px}
.leg-line{width:12px;height:2px;border-radius:1px}
</style>
<div class="card">
  <div class="hdr">
    <span>⚡</span>
    <span style="font-size:12px;font-weight:600;color:#fff;flex:1">${c.title}</span>
    <span style="font-size:11px;font-weight:600;color:${imbCol}">${imb.toFixed(1)} A onbalans</span>
  </div>

  <div class="live">
    ${[['L1', l1, '#60a5fa', pq.pf_l1],
       ['L2', l2, '#4ade80', pq.pf_l2],
       ['L3', l3, '#fb923c', pq.pf_l3]].map(([lbl, val, col, pf]) => `
    <div class="phase-row">
      <span class="phase-lbl" style="color:${col}">${lbl}</span>
      <div class="phase-bar-wrap">
        <div class="phase-bar" style="width:${Math.min(100, val/maxA*100).toFixed(0)}%;background:${barCol(val)}"></div>
      </div>
      <span class="phase-val" style="color:${barCol(val)}">${val.toFixed(1)} A</span>
      ${pf != null ? `<span class="pf">φ ${pf.toFixed(3)}</span>` : '<span class="pf"></span>'}
    </div>`).join('')}
  </div>

  <div class="imb-row">
    <span style="font-size:11px;color:rgba(163,163,163,.6)">Onbalans</span>
    <span style="font-size:14px;font-weight:700;color:${imbCol}">${imb.toFixed(1)} A</span>
    <span style="font-size:10px;padding:2px 8px;border-radius:6px;background:${balanced?'rgba(74,222,128,.15)':'rgba(248,113,113,.15)'};color:${balanced?'#4ade80':'#f87171'}">${balanced ? '✓ Gebalanceerd' : '⚠ Onbalans'}</span>
    ${pfAvg != null ? `<span style="font-size:10px;color:rgba(163,163,163,.5)">cos φ ${pfAvg.toFixed(3)}</span>` : ''}
  </div>

  ${hasHist ? `
  <div class="chart-wrap">
    <div class="chart-title">
      <span>Fase stromen — ${oldestAgo}m historiek</span>
      <span style="font-size:8px;color:rgba(163,163,163,.3)">${hist.t.length} samples</span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" height="${H}">
      ${this._sparkline(hist.l1, '#60a5fa', W, H, '#60a5fa')}
      ${this._sparkline(hist.l2, '#4ade80', W, H, '#4ade80')}
      ${this._sparkline(hist.l3, '#fb923c', W, H, '#fb923c')}
    </svg>
    <div class="axis"><span>−${oldestAgo}m</span><span>nu</span></div>
  </div>
  <div class="chart-wrap" style="padding-top:0">
    <div class="chart-title"><span>Onbalans</span></div>
    <svg viewBox="0 0 ${W} 30" height="30">
      ${this._sparkline(hist.imb, imbCol, W, 30, imbCol)}
    </svg>
  </div>
  <div class="legend">
    <span class="leg"><span class="leg-line" style="background:#60a5fa"></span>L1</span>
    <span class="leg"><span class="leg-line" style="background:#4ade80"></span>L2</span>
    <span class="leg"><span class="leg-line" style="background:#fb923c"></span>L3</span>
    <span class="leg"><span class="leg-line" style="background:${imbCol}"></span>Onbalans</span>
  </div>` : `
  <div style="padding:12px 16px;font-size:11px;color:rgba(163,163,163,.4);text-align:center">
    Historiek wordt opgebouwd… (${hist.t.length}/${this._maxSamples} samples)
  </div>`}
</div>`;
  }

  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement("cloudems-fase-historiek-card-editor"); }
  static getStubConfig() { return {}; }
}
class CloudemsFaseHistoriekCardEditor extends HTMLElement {
  setConfig(c){this._config=c;this._r();}
  _r(){if(!this.shadowRoot)this.attachShadow({mode:"open"});this.shadowRoot.innerHTML=`<label style="font-size:12px;color:#aaa;display:block;margin:8px 0 2px">Titel</label><input style="width:100%;box-sizing:border-box;background:#1a1a1a;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:6px;font-size:13px" id="t" value="${this._config?.title||'⚡ Fase Balans Historiek'}"/>`;this.shadowRoot.getElementById("t").addEventListener("input",e=>this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config,title:e.target.value}}})));}
}
if (!customElements.get('cloudems-fase-historiek-card')) customElements.define("cloudems-fase-historiek-card", CloudemsFaseHistoriekCard);
if (!customElements.get('cloudems-fase-historiek-card-editor')) customElements.define("cloudems-fase-historiek-card-editor", CloudemsFaseHistoriekCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type:"cloudems-fase-historiek-card", name:"CloudEMS Fase Balans Historiek" });
