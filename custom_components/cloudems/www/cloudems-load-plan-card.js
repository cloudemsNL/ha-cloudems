// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Load Plan Card v5.4.96 — 24-uurs tijdlijn zoals PredBat

const LPC_VERSION = '5.5.318';
const LPC_SENSOR  = 'sensor.cloudems_load_plan';
const LPC_EPEX    = 'sensor.cloudems_price_current_hour';

class CloudEMSLoadPlanCard extends HTMLElement {
  set hass(h) {
    this._hass = h;
    const key = h?.states[LPC_SENSOR]?.last_changed;
    if (key !== this._prev) { this._prev = key; this._render(); }
  }

  setConfig(c) { this._cfg = c || {}; }
  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement('cloudems-load-plan-card-editor'); }
  static getStubConfig() { return {}; }

  _render() {
    const h = this._hass;
    if (!h) return;

    const plan = h.states[LPC_SENSOR]?.attributes || {};
    const battCharge    = new Set(plan.battery_charge_hours    || []);
    const battDischarge = new Set(plan.battery_discharge_hours || []);
    const boilerHours   = new Set(plan.boiler_hours            || []);
    const evHours       = new Set(plan.ev_charge_hours         || []);
    const ebikeHours    = new Set(plan.ebike_hours             || []);

    // Prijs per uur uit slots
    const priceByHour = {};
    const pvByHour    = {};
    (plan.slots || []).forEach(s => {
      priceByHour[s.hour] = s.price;
      pvByHour[s.hour]    = s.pv_w;
    });

    // Ook EPEX vandaag/morgen uit price sensor voor volle 24u grafiek
    const priceSensor = h.states['sensor.cloudems_epex_vandaag']?.attributes
                     || h.states['sensor.cloudems_price_today']?.attributes
                     || {};
    const epexHours = priceSensor.hourly_prices || priceSensor.today_prices || [];
    epexHours.forEach(e => {
      if (e.hour != null && priceByHour[e.hour] == null) {
        priceByHour[e.hour] = e.price ?? e.price_display;
      }
    });

    const curHour = new Date().getHours();
    const planDate = plan.date || 'morgen';
    const advice   = plan.advice || '';
    const savings  = plan.estimated_savings_eur != null
      ? `€${parseFloat(plan.estimated_savings_eur).toFixed(2)}`
      : '—';
    const pvUtil   = plan.pv_utilisation_pct != null
      ? `${plan.pv_utilisation_pct}%`
      : '—';

    // Max prijs voor schaal
    const allPrices = Object.values(priceByHour).filter(p => p != null);
    const maxPrice  = allPrices.length ? Math.max(...allPrices, 0.01) : 0.30;
    const minPrice  = Math.min(...allPrices, 0);

    // Rijen definitie
    const rows = [
      { key: 'batt_charge',    label: '⚡ Laden',      color: '#3fb950', hours: battCharge,    icon: '⚡' },
      { key: 'batt_discharge', label: '🔋 Ontladen',   color: '#f85149', hours: battDischarge, icon: '🔋' },
      { key: 'boiler',         label: '🌡️ Boiler',     color: '#f97316', hours: boilerHours,   icon: '🌡️' },
      { key: 'ev',             label: '🚗 EV laden',   color: '#60a5fa', hours: evHours,        icon: '🚗' },
      { key: 'ebike',          label: '🚲 E-bike',     color: '#a78bfa', hours: ebikeHours,     icon: '🚲' },
    ].filter(r => r.hours.size > 0);

    // Uur-labels rij (0-23)
    const hourLabels = Array.from({length: 24}, (_, i) => {
      const isCur = i === curHour;
      return `<div class="hour-lbl ${isCur ? 'hour-cur' : ''}">${String(i).padStart(2,'0')}</div>`;
    }).join('');

    // Prijsbalk per uur
    const priceBars = Array.from({length: 24}, (_, i) => {
      const p = priceByHour[i];
      const isCur = i === curHour;
      if (p == null) {
        return `<div class="price-cell price-empty ${isCur ? 'hour-cur-col' : ''}"></div>`;
      }
      const isNeg = p < 0;
      const isHigh = p > 0.25;
      const isMid  = p > 0.15 && !isHigh;
      const barH   = Math.round(Math.abs(p) / maxPrice * 28);
      const col    = isNeg ? '#3fb950' : isHigh ? '#f85149' : isMid ? '#d29922' : '#58a6ff';
      const label  = Math.round(p * 100); // ct/kWh
      return `<div class="price-cell ${isCur ? 'hour-cur-col' : ''}" title="${p.toFixed(4)} €/kWh">
        <div class="price-label" style="color:${col}">${label}</div>
        <div class="price-bar" style="height:${barH}px;background:${col}${isNeg ? '' : '88'};${isNeg ? 'margin-top:auto' : ''}"></div>
      </div>`;
    }).join('');

    // Activiteitsrijen
    const activityRows = rows.map(r => {
      const cells = Array.from({length: 24}, (_, i) => {
        const active = r.hours.has(i);
        const isCur  = i === curHour;
        return `<div class="act-cell ${active ? 'act-on' : ''} ${isCur ? 'hour-cur-col' : ''}"
          style="${active ? `background:${r.color}33;border-color:${r.color}88` : ''}"
          title="${active ? r.label + ' uur ' + i : ''}">
          ${active ? `<span style="color:${r.color}">${r.icon}</span>` : ''}
        </div>`;
      }).join('');
      return `<div class="row-wrap">
        <div class="row-label">${r.label}</div>
        <div class="row-cells">${cells}</div>
      </div>`;
    }).join('');

    // PV balk per uur
    const maxPv = Math.max(...Object.values(pvByHour), 1);
    const pvBars = Array.from({length: 24}, (_, i) => {
      const pv = pvByHour[i] || 0;
      const isCur = i === curHour;
      const h2 = Math.round(pv / maxPv * 24);
      return `<div class="pv-cell ${isCur ? 'hour-cur-col' : ''}" title="${Math.round(pv)}W PV">
        ${pv > 50 ? `<div class="pv-bar" style="height:${h2}px"></div>` : ''}
      </div>`;
    }).join('');

    this.innerHTML = `
    <ha-card>
      <style>
        ha-card { background:#0d1117; border-radius:12px; padding:16px; color:#f0f6fc;
          font-family:'Syne',system-ui,sans-serif; overflow:hidden; }
        .lp-hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }
        .lp-title { font-size:13px; font-weight:800; letter-spacing:.04em; color:#58a6ff; }
        .lp-meta { display:flex; gap:12px; font-size:10px; color:rgba(255,255,255,.4); margin-bottom:12px; }
        .lp-badge { padding:2px 8px; border-radius:10px; font-weight:700; }

        /* Tijdlijn grid */
        .tl-wrap { overflow-x:auto; padding-bottom:4px; }
        .tl { min-width:600px; }

        /* Uur labels */
        .hour-row { display:grid; grid-template-columns:80px repeat(24,1fr); gap:1px; margin-bottom:2px; }
        .hour-lbl { font-size:8px; color:rgba(255,255,255,.25); text-align:center; }
        .hour-cur { color:#58a6ff; font-weight:700; }

        /* Prijs bars */
        .price-row { display:grid; grid-template-columns:80px repeat(24,1fr); gap:1px; height:44px; margin-bottom:2px; }
        .price-cell { display:flex; flex-direction:column; justify-content:flex-end; align-items:center;
          position:relative; height:44px; }
        .price-label { font-size:7px; line-height:1; margin-bottom:1px; font-weight:700; }
        .price-bar { width:80%; border-radius:2px 2px 0 0; min-height:1px; }
        .price-empty { opacity:.1; }

        /* PV bars */
        .pv-row { display:grid; grid-template-columns:80px repeat(24,1fr); gap:1px; height:28px; margin-bottom:4px; }
        .pv-lbl { font-size:9px; color:rgba(255,255,255,.3); display:flex; align-items:flex-end; padding-bottom:2px; }
        .pv-cell { display:flex; align-items:flex-end; justify-content:center; height:28px; }
        .pv-bar { width:80%; background:rgba(210,153,34,.5); border-radius:2px 2px 0 0; }

        /* Activiteitsrijen */
        .row-wrap { display:grid; grid-template-columns:80px 1fr; gap:1px; margin-bottom:2px; align-items:center; }
        .row-label { font-size:10px; color:rgba(255,255,255,.5); white-space:nowrap; overflow:hidden; }
        .row-cells { display:grid; grid-template-columns:repeat(24,1fr); gap:1px; }
        .act-cell { height:22px; border-radius:3px; border:1px solid rgba(255,255,255,.06);
          display:flex; align-items:center; justify-content:center; font-size:10px; }
        .act-on { border-radius:4px; }

        /* Huidig uur kolom */
        .hour-cur-col { background:rgba(88,166,255,.06); border-radius:2px; }

        /* Advies */
        .lp-advice { margin-top:10px; font-size:10px; color:rgba(255,255,255,.4);
          padding:8px 10px; background:rgba(255,255,255,.03); border-radius:6px;
          border-left:2px solid #58a6ff; }
        .lp-row-hdr { font-size:8px; color:rgba(255,255,255,.2); display:flex;
          align-items:center; padding-left:80px; gap:1px; margin-bottom:2px; }
        .sep { height:1px; background:rgba(255,255,255,.06); margin:6px 0; }
      </style>

      <div class="lp-hdr">
        <span class="lp-title">📅 Geplande slots — ${planDate}</span>
        <span style="font-size:10px;color:rgba(255,255,255,.3)">v${LPC_VERSION}</span>
      </div>
      <div class="lp-meta">
        <span>💰 Besparing: <strong style="color:#3fb950">${savings}</strong></span>
        <span>☀️ PV-benutting: <strong style="color:#d29922">${pvUtil}</strong></span>
        ${plan.total_flex_kwh ? `<span>⚡ Flex: <strong>${plan.total_flex_kwh} kWh</strong></span>` : ''}
      </div>

      <div class="tl-wrap"><div class="tl">
        <!-- Uur labels -->
        <div class="hour-row">
          <div style="font-size:9px;color:rgba(255,255,255,.25)">Uur</div>
          ${hourLabels}
        </div>

        <!-- Prijsbalk -->
        <div class="price-row">
          <div style="font-size:9px;color:rgba(255,255,255,.3);display:flex;align-items:flex-end;padding-bottom:2px">ct/kWh</div>
          ${priceBars}
        </div>

        <!-- PV balk -->
        ${maxPv > 50 ? `<div class="pv-row">
          <div class="pv-lbl">☀️ PV</div>
          ${pvBars}
        </div>` : ''}

        <div class="sep"></div>

        <!-- Activiteitsrijen -->
        ${activityRows || `<div style="font-size:11px;color:rgba(255,255,255,.3);padding:8px 0">
          Geen flexibele slots gepland — beschikbaar zodra EPEX-prijzen morgen beschikbaar zijn (~13:00)
        </div>`}
      </div></div>

      ${advice ? `<div class="lp-advice">${advice}</div>` : ''}
    </ha-card>`;
  }
}

if (!customElements.get('cloudems-load-plan-card')) {
  customElements.define('cloudems-load-plan-card', CloudEMSLoadPlanCard);
}

class CloudEMSLoadPlanCardEditor extends HTMLElement {
  setConfig(c) {}
  _render() {
    this.innerHTML = `<p style="padding:8px;color:#aaa;font-size:12px">Geen configuratie vereist.</p>`;
  }
}
if (!customElements.get('cloudems-load-plan-card-editor')) {
  customElements.define('cloudems-load-plan-card-editor', CloudEMSLoadPlanCardEditor);
}
