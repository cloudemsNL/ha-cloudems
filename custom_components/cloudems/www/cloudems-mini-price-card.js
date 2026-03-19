// CloudEMS Mini Prijs Widget — cloudems-mini-price-card
// Compact EPEX prijskaart met incl/excl belasting toggle.
// v1.2.0 — leest sensor.cloudems_energy_epex_today (alle data voor toggle aanwezig)

class CloudemsMiniPriceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._prev = '';
    this._showIncl = true;
  }

  setConfig(c) {
    this._cfg = c || {};
    if (this._cfg.show_incl !== undefined) this._showIncl = !!this._cfg.show_incl;
    setTimeout(() => { this._prev = ''; this._render(); }, 500);
  }

  set hass(h) {
    this._hass = h;
    const ep = h.states['sensor.cloudems_energy_epex_today'];
    const sig = [ep?.attributes?.current_price_display, ep?.attributes?.avg_today,
                 ep?.attributes?.min_today_incl_tax, ep?.last_changed].join('|');
    if (sig !== this._prev) { this._prev = sig; this._render(); }
  }

  _render() {
    const h  = this._hass;
    const sh = this.shadowRoot;
    if (!h || !sh) return;

    // sensor.cloudems_energy_epex_today heeft ALLE data: incl én excl
    const ep = h.states['sensor.cloudems_energy_epex_today'];
    const a  = ep?.attributes || {};
    const si = this._showIncl;

    // Huidige prijs: incl = all-in display, excl = kale EPEX
    const nowEur = si
      ? parseFloat(a.current_price_display || 0)
      : parseFloat((a.today_prices_base?.[new Date().getHours()]?.price)
          || (a.today_prices_excl_tax?.[new Date().getHours()]?.price)
          || a.min_today_excl_tax || 0);
    const nowCt  = nowEur * 100;

    // Barchart: juiste prijzenreeks per toggle
    const prices = si
      ? (a.today_prices_incl_tax || a.today_prices || [])
      : (a.today_prices_excl_tax || a.today_prices_base || a.today_prices || []);

    // v4.6.495: drempels ALTIJD op basis van all-in reeks — zo veranderen balkkleur niet bij toggle.
    // Eerder werden drempels berekend uit de getoonde reeks, waardoor bij EPEX alle drempels
    // verschoven en balkkleur compleet anders werden.
    const _pricesAllIn = a.today_prices_incl_tax || a.today_prices || [];
    const _pValsRef = _pricesAllIn.map(p => parseFloat(p.price || 0) * 100).filter(v => !isNaN(v));
    const avgCt = _pValsRef.length ? _pValsRef.reduce((a,b) => a+b, 0) / _pValsRef.length : 0;
    const minCt = _pValsRef.length ? Math.min(..._pValsRef) : 0;
    const maxCt = _pValsRef.length ? Math.max(..._pValsRef) : 0;
    // Dagstatistieken voor weergave: uit de getoonde reeks
    const _pVals = prices.map(p => parseFloat(p.price || 0) * 100).filter(v => !isNaN(v));
    const minCtDisp = _pVals.length ? Math.min(..._pVals) : 0;
    const maxCtDisp = _pVals.length ? Math.max(..._pVals) : 0;

    const taxPer = (parseFloat(a.tax_per_kwh || 0)) * 100;
    const nowH   = new Date().getHours();
    const label  = si ? (a.price_label || 'EPEX') : (a.price_label_excl || 'excl. belasting');

    // Badge altijd op basis van all-in prijs (niet afhankelijk van toggle)
    const nowCtAllIn = parseFloat(a.current_price_display || 0) * 100;
    const avgCtAllIn = parseFloat(a.avg_today_incl_tax || a.avg_today || 0) * 100;
    const isNeg   = nowCtAllIn < 0;
    const isCheap = !isNeg && avgCtAllIn > 0 && nowCtAllIn < avgCtAllIn * 0.85;
    const isDear  = avgCtAllIn > 0 && nowCtAllIn > avgCtAllIn * 1.3;
    const col     = isNeg ? '#34d399' : isCheap ? '#86efac' : isDear ? '#f87171' : '#f0c040';
    const icon    = isNeg ? '🎉' : isCheap ? '✅' : isDear ? '⚠️' : '⚡';
    const tariff  = a.tariff_group || '';
    const badgeTxt = isNeg ? 'Negatief!' : isCheap ? 'Goedkoop' : isDear ? 'Duur'
      : tariff ? tariff.charAt(0).toUpperCase() + tariff.slice(1) : 'Normaal';

    // Mini barchart
    // v4.6.504: balkkleur altijd op basis van all-in waarde (ongeacht toggle)
    // zodat kleuren identiek zijn in beide modi
    const valsAllIn = _pricesAllIn.map(p => parseFloat(p.price || 0) * 100).filter(v => !isNaN(v));
    let chartSvg = '';
    const vals = prices.map(p => parseFloat(p.price || 0) * 100).filter(v => !isNaN(v));
    if (vals.length > 0) {
      const maxV = Math.max(...vals.map(Math.abs), 0.01);
      const bw = 7, gap = 1, W = (bw + gap) * 24, H = 36, base = H * 0.75;
      const bars = vals.map((v, i) => {
        const isNow = i === nowH;
        const h2    = Math.max(2, Math.abs(v) / maxV * (v >= 0 ? base : H - base));
        const y     = v >= 0 ? base - h2 : base;
        // Kleur op basis van all-in waarde — zelfde drempels in beide modi
        const vRef  = valsAllIn[i] !== undefined ? valsAllIn[i] : v;
        const bc    = isNow ? '#f0c040' : vRef < 0 ? '#34d399' : vRef < avgCt ? '#86efac' : vRef > maxCt * 0.8 ? '#ef4444' : '#60a5fa';
        return `<rect x="${i*(bw+gap)}" y="${y.toFixed(1)}" width="${bw}" height="${h2.toFixed(1)}" rx="1.5" fill="${bc}" opacity="${isNow?1:.65}"/>`;
      }).join('');
      chartSvg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:36px;display:block">
        <line x1="0" y1="${base.toFixed(1)}" x2="${W}" y2="${base.toFixed(1)}" stroke="rgba(255,255,255,.1)" stroke-width="0.5"/>
        ${bars}</svg>
      <div style="display:flex;justify-content:space-between;font-size:8px;color:rgba(255,255,255,.25);font-family:monospace;margin:1px 0 4px">
        <span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>`;
    }

    sh.innerHTML = `<style>
      :host{display:block}
      .card{background:rgba(15,20,15,.95);border-radius:10px;border:1px solid rgba(255,255,255,.06);padding:10px 14px 8px;font-family:system-ui,sans-serif}
      .row1{display:flex;align-items:center;gap:8px;margin-bottom:6px}
      .price{font-family:monospace;font-size:22px;font-weight:700;line-height:1}
      .unit{font-size:10px;color:rgba(255,255,255,.4);margin-top:2px}
      .badge{font-size:9px;padding:2px 7px;border-radius:10px;border:1px solid;white-space:nowrap}
      .stats{display:flex;gap:10px;margin-bottom:6px}
      .stat{font-size:10px;color:rgba(255,255,255,.45)}
      .stat strong{color:rgba(255,255,255,.8)}
      .toggle{font-size:9px;padding:2px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.05);color:rgba(255,255,255,.5);cursor:pointer;margin-left:auto}
    </style>
    <div class="card">
      <div class="row1">
        <span style="font-size:14px">${icon}</span>
        <div>
          <div class="price" style="color:${col}">${nowCt.toFixed(1)}<span style="font-size:12px"> ct</span></div>
          <div class="unit">kWh · ${label}</div>
        </div>
        <span class="badge" style="color:${col};border-color:${col}44;background:${col}11">${badgeTxt}</span>
        <button class="toggle" id="tax-toggle">${si ? '✓ all-in' : '○ kale EPEX'}</button>
      </div>
      <div class="stats">
        <span class="stat">Min: <strong>${minCtDisp.toFixed(1)} ct</strong></span>
        <span class="stat">Gem: <strong>${(_pVals.length?_pVals.reduce((a,b)=>a+b,0)/_pVals.length:0).toFixed(1)} ct</strong></span>
        <span class="stat">Max: <strong>${maxCtDisp.toFixed(1)} ct</strong></span>
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
  static getConfigElement() {
    const el = document.createElement('div');
    el.innerHTML = '<p style="padding:8px;color:#aaa">Geen configuratie vereist.</p>';
    return el;
  }
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
