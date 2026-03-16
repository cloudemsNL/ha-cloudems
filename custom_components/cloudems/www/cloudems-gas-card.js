/**
 * CloudEMS Gas Card — cloudems-gas-card
 * Version: 1.0.0
 *
 * Toont:
 *  1. Gasmeter stand + kWh equivalent
 *  2. Verbruik & kosten tabel (dag/week/maand/jaar) met mini barchart
 *  3. Goedkoopste warmtebron vergelijking
 */

class CloudEMSGasCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._prev = '';
  }

  setConfig(c) {
    this._config = c || {};
    // Startup timer: force render after 3s in case state hasn't changed
    setTimeout(() => { this._prev = ''; this._render(); }, 3000);
  }

  set hass(h) {
    this._hass = h;
    this._render();
  }

  _s(e) { return this._hass?.states?.[e] || null; }
  _v(e, d = 0) {
    const s = this._s(e);
    if (!s || s.state === 'unavailable' || s.state === 'unknown') return d;
    return parseFloat(s.state) || d;
  }
  _a(e, k, d = null) { return this._s(e)?.attributes?.[k] ?? d; }

  _render() {
    if (!this._hass) return;

    const gs = 'sensor.cloudems_gasstand';
    const wb = 'sensor.cloudems_goedkoopste_warmtebron';

    const sig = [
      this._s(gs)?.state,
      this._s(wb)?.state,
      this._a(gs, 'dag_m3'),
      this._a(gs, 'week_m3'),
      this._a(gs, 'maand_m3'),
      this._a(gs, 'dag_eur'),
      this._a(wb, 'gas_per_kwh_heat'),
      this._a(wb, 'elec_price_kwh'),
    ].join('|');
    if (sig === this._prev) return;
    this._prev = sig;

    // ── Gas stand ──
    const stand     = this._v(gs, null);
    const kwh       = this._a(gs, 'gas_kwh', null);
    const prijs     = this._a(gs, 'gas_prijs_per_m3', 1.25);
    const meterstand = stand !== null ? stand.toLocaleString('nl-NL', { minimumFractionDigits: 2 }) : '—';
    const kwhStr    = kwh !== null ? parseFloat(kwh).toLocaleString('nl-NL', { minimumFractionDigits: 2 }) : '—';

    // ── Periode verbruik ──
    const dagM3    = this._a(gs, 'dag_m3', 0);
    const weekM3   = this._a(gs, 'week_m3', 0);
    const maandM3  = this._a(gs, 'maand_m3', 0);
    const jaarM3   = this._a(gs, 'jaar_m3', 0);
    const dagEur   = this._a(gs, 'dag_eur', 0);
    const weekEur  = this._a(gs, 'week_eur', 0);
    const maandEur = this._a(gs, 'maand_eur', 0);
    const jaarEur  = this._a(gs, 'jaar_eur', 0);

    const fmt = (v, unit) => v > 0 ? `${v.toFixed(unit === '€' ? 2 : 2)} ${unit}` : '—';
    const maxM3 = Math.max(dagM3, weekM3 / 7, maandM3 / 30, jaarM3 / 365, 0.001);

    const periodes = [
      { label: 'Vandaag',    m3: dagM3,   eur: dagEur,   pct: dagM3 / maxM3 },
      { label: 'Deze week',  m3: weekM3,  eur: weekEur,  pct: (weekM3/7) / maxM3 },
      { label: 'Deze maand', m3: maandM3, eur: maandEur, pct: (maandM3/30) / maxM3 },
      { label: 'Dit jaar',   m3: jaarM3,  eur: jaarEur,  pct: (jaarM3/365) / maxM3 },
    ];

    const periodeRows = periodes.map(p => {
      const barW = Math.min(100, Math.round(p.pct * 100));
      // Show 0.00 if gas module is active but no usage yet, — if module/sensor missing
      const gasActive = stand !== null && stand > 0;
      const hasData = p.m3 > 0;
      return `<div class="prow">
        <span class="plabel">${p.label}</span>
        <div class="pbar-wrap">
          ${hasData ? `<div class="pbar" style="width:${barW}%"></div>` : ''}
        </div>
        <span class="pval">${gasActive ? p.m3.toFixed(2) + ' m³' : '—'}</span>
        <span class="peur">${gasActive ? '€' + p.eur.toFixed(2) : '—'}</span>
      </div>`;
    }).join('');

    // ── Warmtebron ──
    const wbState  = this._s(wb)?.state || '';
    const elecPrijs = this._a(wb, 'elec_price_kwh', null);
    const gasHeat  = this._a(wb, 'gas_per_kwh_heat', null);
    const elecHeat = this._a(wb, 'elec_boiler_per_kwh_heat', null);
    const hpHeat   = this._a(wb, 'heat_pump_per_kwh_heat', null);
    const rec      = this._a(wb, 'recommendation', '');
    const savings  = this._a(wb, 'savings_boiler_ct_per_kwh', null);

    const isElec = wbState === 'elektriciteit';
    const isGas  = wbState === 'gas';
    const wbColor = isElec ? '#4caf50' : isGas ? '#ff8040' : '#ffd600';
    const wbLabel = isElec ? '⚡ Elektriciteit is goedkoper' : isGas ? '🔥 Gas is goedkoper' : '≈ Ongeveer gelijk';

    const bronRows = [
      { label: 'Gas via CV (90% eff.)',      val: gasHeat,  best: isGas },
      { label: 'Elektrische boiler (resist.)', val: elecHeat, best: isElec && !hpHeat },
      hpHeat ? { label: 'Warmtepomp',          val: hpHeat,  best: isElec } : null,
    ].filter(Boolean).map(b => `
      <div class="brow">
        <span class="blabel">${b.label}</span>
        <span class="bval">${b.val != null ? (b.val * 100).toFixed(1) + ' ct/kWh' : '—'}</span>
        <span class="bbest">${b.best ? '✅' : ''}</span>
      </div>`).join('');

    const savingsStr = savings != null && Math.abs(savings) > 0.1
      ? `Besparing: ${Math.abs(savings).toFixed(1)} ct/kWh warmte`
      : '';

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; font-family: var(--primary-font-family, sans-serif); }
        .card { background: rgb(34,34,34); border: 1px solid rgba(255,255,255,0.06);
          border-radius: 16px; overflow: hidden; }
        .t { font-size: 13px; font-weight: 700; letter-spacing: .06em;
          text-transform: uppercase; color: rgba(255,255,255,0.5); padding: 14px 16px 10px; }

        /* Stand */
        .stand { display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .stand-item { flex: 1; padding: 10px 16px 12px; }
        .stand-item + .stand-item { border-left: 1px solid rgba(255,255,255,0.06); }
        .stand-lbl { font-size: 10px; color: rgba(255,255,255,0.4); text-transform: uppercase;
          letter-spacing: .06em; margin-bottom: 3px; }
        .stand-val { font-size: 18px; font-weight: 700; color: #fff; }
        .stand-unit { font-size: 11px; color: rgba(255,255,255,0.5); margin-left: 3px; }

        /* Periodes */
        .periodes { padding: 8px 14px 12px; }
        .prow { display: grid; grid-template-columns: 80px 1fr 70px 60px;
          align-items: center; gap: 8px; padding: 4px 0; }
        .plabel { font-size: 12px; color: rgba(255,255,255,0.6); }
        .pbar-wrap { background: rgba(255,255,255,0.06); border-radius: 3px; height: 6px; overflow: hidden; }
        .pbar { height: 100%; background: linear-gradient(90deg, #ff8040, #ffd600);
          border-radius: 3px; transition: width .3s; }
        .pval { font-size: 12px; color: rgba(255,255,255,0.85); text-align: right; }
        .peur { font-size: 12px; color: #ffd600; text-align: right; font-weight: 600; }

        hr { border: none; border-top: 1px solid rgba(255,255,255,0.07); margin: 0; }

        /* Warmtebron */
        .wbadge { margin: 10px 16px 8px;
          padding: 6px 10px; border-radius: 8px; font-size: 13px; font-weight: 600;
          background: rgba(255,255,255,0.05); border: 1px solid ${wbColor}44;
          color: ${wbColor}; }
        .bronnen { padding: 4px 14px 4px; }
        .brow { display: grid; grid-template-columns: 1fr 90px 24px;
          align-items: center; gap: 6px; padding: 4px 0; }
        .blabel { font-size: 12px; color: rgba(255,255,255,0.7); }
        .bval { font-size: 12px; color: rgba(255,255,255,0.9); text-align: right; font-weight: 600; }
        .bbest { text-align: center; font-size: 14px; }
        .savings { font-size: 11px; color: rgba(255,255,255,0.45); padding: 2px 16px 6px; }
        .footer { font-size: 11px; color: rgba(255,255,255,0.3); padding: 6px 16px 12px; }
      </style>

      <div class="card">
        <div class="t">🔥 Gas</div>

        <div class="stand">
          <div class="stand-item">
            <div class="stand-lbl">Gasmeter stand</div>
            <div class="stand-val">${meterstand}<span class="stand-unit">m³</span></div>
          </div>
          <div class="stand-item">
            <div class="stand-lbl">Equivalent</div>
            <div class="stand-val">${kwhStr}<span class="stand-unit">kWh</span></div>
          </div>
        </div>

        <div class="t" style="padding-bottom:4px">Verbruik & Kosten</div>
        <div class="periodes">${periodeRows}</div>
        <div class="footer">Gasprijs: €${prijs.toFixed(4)}/m³ · Meterstand: ${stand ? stand.toFixed(1) : '—'} m³</div>

        <hr>

        <div class="t" style="padding-bottom:4px">⚡🔥 Goedkoopste Warmtebron</div>
        <div class="wbadge">${wbLabel}</div>
        <div class="bronnen">${bronRows}</div>
        ${savingsStr ? `<div class="savings">${savingsStr}</div>` : ''}
        ${elecPrijs != null ? `<div class="footer">Huidige stroomprijs: €${elecPrijs.toFixed(4)}/kWh</div>` : ''}
      </div>`;
  }

  getCardSize() { return 6; }
  static getConfigElement() { return document.createElement('cloudems-gas-card-editor'); }
  static getStubConfig() { return {}; }
}

if (!customElements.get('cloudems-gas-card')) {
  customElements.define('cloudems-gas-card', CloudEMSGasCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-gas-card')) {
  window.customCards.push({
    type: 'cloudems-gas-card',
    name: 'CloudEMS Gas Card',
    description: 'Gas verbruik, kosten en warmtebron vergelijking',
  });
}

if (!customElements.get('cloudems-gas-card-editor')) {
  class _cloudems_gas_card_editor extends HTMLElement {
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
  customElements.define('cloudems-gas-card-editor', _cloudems_gas_card_editor);
}
