// CloudEMS Mini Prijs Widget — cloudems-mini-price-card
// Compact EPEX prijskaart met incl/excl belasting toggle.
// Zet bovenaan elk tabblad — altijd weten wat stroom kost.
// v1.0.0

class CloudemsMiniPriceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._prev = '';
    this._showIncl = true; // default: incl. belasting
  }

  setConfig(c) {
    this._cfg = c || {};
    if (this._cfg.show_incl !== undefined) this._showIncl = !!this._cfg.show_incl;
    setTimeout(() => { this._prev = ''; this._render(); }, 500);
  }

  set hass(h) {
    this._hass = h;
    const s = h.states['sensor.cloudems_price_current_hour'];
    const sig = [s?.state, s?.attributes?.price_incl_tax, s?.attributes?.price_excl_tax,
                 s?.attributes?.avg_today_incl_tax, s?.last_changed].join('|');
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _render() {
    const h = this._hass;
    const sh = this.shadowRoot;
    if (!h || !sh) return;

    const s  = h.states['sensor.cloudems_price_current_hour'];
    const a  = s?.attributes || {};
    const si = this._showIncl;

    const nowCt   = (si ? parseFloat(a.price_incl_tax  || a.price_all_in  || s?.state || 0)
                        : parseFloat(a.price_excl_tax  || a.base_epex_price || s?.state || 0)) * 100;
    const avgCt   = (si ? (a.avg_today_incl_tax || 0) : (a.avg_today_excl_tax || 0)) * 100;
    const minCt   = (si ? (a.min_today_incl_tax || 0) : (a.min_today_excl_tax || 0)) * 100;
    const maxCt   = (si ? (a.max_today_incl_tax || 0) : (a.max_today_excl_tax || 0)) * 100;
    const prices  = si ? (a.today_prices_incl_tax || []) : (a.today_prices_excl_tax || []);
    const isNeg   = nowCt < 0;
    const isCheap = !isNeg && nowCt < avgCt * 0.85;
    const isDear  = nowCt > avgCt * 1.3;
    const taxPer  = (a.tax_per_kwh || 0) * 100;
    const nowH    = new Date().getHours();
    const tariff  = a.tariff_group || '—';
    const label   = a.price_label  || 'EPEX';

    const col = isNeg ? '#34d399' : isCheap ? '#86efac' : isDear ? '#f87171' : '#f0c040';
    const icon = isNeg ? '🎉' : isCheap ? '✅' : isDear ? '⚠️' : '⚡';

    // Mini barchart
    let chartSvg = '';
    if (prices.length > 0) {
      const vals = prices.map(p => parseFloat(p.price || p.price_excl_tax || 0) * 100);
      const maxV = Math.max(...vals.map(Math.abs), 0.01);
      const bw = 7, gap = 1, W = (bw + gap) * 24, H = 36, base = H * 0.75;
      const bars = vals.map((v, i) => {
        const isNow = i === nowH;
        const h2 = Math.max(2, Math.abs(v) / maxV * (v >= 0 ? base : H - base));
        const y = v >= 0 ? base - h2 : base;
        const bc = isNow ? '#f0c040' : v < 0 ? '#34d399' : v < avgCt ? '#86efac' : v > maxCt * 0.8 ? '#ef4444' : '#60a5fa';
        const bx = i * (bw + gap);
        return `<rect x="${bx}" y="${y.toFixed(1)}" width="${bw}" height="${h2.toFixed(1)}" rx="1.5" fill="${bc}" opacity="${isNow?1:.65}"/>`;
      }).join('');
      chartSvg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:36px;display:block">
        <line x1="0" y1="${base.toFixed(1)}" x2="${W}" y2="${base.toFixed(1)}" stroke="rgba(255,255,255,.1)" stroke-width="0.5"/>
        ${bars}
      </svg>
      <div style="display:flex;justify-content:space-between;font-size:8px;color:rgba(255,255,255,.25);font-family:monospace;margin:1px 0 4px">
        <span>00</span><span>06</span><span>12</span><span>18</span><span>23</span>
      </div>`;
    }

    sh.innerHTML = `<style>
      :host { display:block; }
      .card { background:rgba(15,20,15,.95); border-radius:10px;
        border:1px solid rgba(255,255,255,.06); padding:10px 14px 8px;
        font-family:system-ui,sans-serif; }
      .row1 { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
      .price { font-family:monospace; font-size:22px; font-weight:700; line-height:1; }
      .unit  { font-size:10px; color:rgba(255,255,255,.4); margin-top:2px; }
      .badge { font-size:9px; padding:2px 7px; border-radius:10px;
        border:1px solid; white-space:nowrap; }
      .stats { display:flex; gap:10px; margin-bottom:6px; }
      .stat  { font-size:10px; color:rgba(255,255,255,.45); }
      .stat strong { color:rgba(255,255,255,.8); }
      .toggle { font-size:9px; padding:2px 8px; border-radius:8px;
        border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.05);
        color:rgba(255,255,255,.5); cursor:pointer; margin-left:auto; }
    </style>
    <div class="card">
      <div class="row1">
        <span style="font-size:14px">${icon}</span>
        <div>
          <div class="price" style="color:${col}">${nowCt.toFixed(1)}<span style="font-size:12px"> ct</span></div>
          <div class="unit">kWh · ${label}</div>
        </div>
        <span class="badge" style="color:${col};border-color:${col}44;background:${col}11">${isNeg?'Negatief!':isCheap?'Goedkoop':isDear?'Duur':'Normaal'}</span>
        <button class="toggle" id="tax-toggle">${si ? '✓ incl. btw' : '○ excl. btw'}</button>
      </div>
      <div class="stats">
        <span class="stat">Min: <strong>${minCt.toFixed(1)} ct</strong></span>
        <span class="stat">Gem: <strong>${avgCt.toFixed(1)} ct</strong></span>
        <span class="stat">Max: <strong>${maxCt.toFixed(1)} ct</strong></span>
        ${taxPer > 0 ? `<span class="stat">EB+BTW: <strong>${taxPer.toFixed(1)} ct</strong></span>` : ''}
      </div>
      ${chartSvg}
    </div>`;

    sh.querySelector('#tax-toggle')?.addEventListener('click', () => {
      this._showIncl = !this._showIncl;
      this._prev = '';
      this._render();
    });
  }

  getCardSize() { return 2; }
  static getStubConfig() { return {}; }
}


if (!customElements.get('cloudems-mini-price-card')) {
  customElements.define('cloudems-mini-price-card', CloudemsMiniPriceCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-mini-price-card')) {
  window.customCards.push({
    type: 'cloudems-mini-price-card',
    name: 'CloudEMS Mini Prijs',
    description: 'Compacte EPEX prijswidget met incl/excl belasting toggle',
  });
}
