// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. Unauthorized copying, redistribution, or commercial
// use of this file is strictly prohibited. See LICENSE for full terms.

/**
 * CloudEMS Climate EPEX Card  v1.0.0
 * Toont live status van airco's en warmtepompen met EPEX-prijssturing.
 * Meerdere apparaten, offset per apparaat, vermogens, prijs-modus.
 *
 *   type: custom:cloudems-climate-epex-card
 *
 * Optional config:
 *   title: "Klimaat EPEX"
 *   sensor: "sensor.cloudems_climate_epex_status"   (default)
 *   price_sensor: "sensor.cloudems_price_current_hour"  (default)
 */

const CE_CARD_VERSION = "1.1.0";

const S = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

  :host { display: block; }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: #111318;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px;
    overflow: hidden;
    font-family: 'Syne', sans-serif;
    position: relative;
  }

  .card::before {
    content: '';
    position: absolute;
    inset: -60px;
    background:
      radial-gradient(ellipse 60% 40% at 20% 0%, rgba(32,180,255,0.07) 0%, transparent 60%),
      radial-gradient(ellipse 50% 35% at 80% 100%, rgba(255,120,30,0.06) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
  }

  .inner { position: relative; z-index: 1; padding: 20px; }

  /* ── Header ── */
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
  .title { font-size: 1rem; font-weight: 700; color: #e8eaf0; letter-spacing: .04em; text-transform: uppercase; }
  .version { font-size: .65rem; color: rgba(255,255,255,.25); font-family: 'JetBrains Mono', monospace; }

  /* ── Price badge ── */
  .price-row { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
  .price-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 20px;
    font-size: .8rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;
    letter-spacing: .02em;
  }
  .price-badge.cheap  { background: rgba(34,197,94,.15);  color: #4ade80; border: 1px solid rgba(34,197,94,.3); }
  .price-badge.dear   { background: rgba(239,68,68,.15);  color: #f87171; border: 1px solid rgba(239,68,68,.3); }
  .price-badge.neutral{ background: rgba(255,255,255,.08); color: #9ca3af; border: 1px solid rgba(255,255,255,.12);}
  .price-label { font-size: .75rem; color: #6b7280; }

  /* ── Total power ── */
  .total-row { display: flex; align-items: baseline; gap: 6px; margin-bottom: 20px; }
  .total-val  { font-size: 1.8rem; font-weight: 800; color: #e8eaf0; font-family: 'JetBrains Mono', monospace; }
  .total-unit { font-size: .85rem; color: #6b7280; }
  .total-label{ font-size: .75rem; color: #6b7280; margin-left: 4px; }

  /* ── Device list ── */
  .devices { display: flex; flex-direction: column; gap: 10px; }

  .device-card {
    background: rgba(255,255,255,.04);
    border: 1px solid rgba(255,255,255,.07);
    border-radius: 14px;
    padding: 14px 16px;
    display: flex; flex-direction: column; gap: 8px;
  }
  .device-card.off   { opacity: .5; }

  .dev-header { display: flex; align-items: center; justify-content: space-between; }
  .dev-name   { font-size: .85rem; font-weight: 700; color: #d1d5db; }
  .dev-type-chip {
    font-size: .65rem; font-weight: 600; padding: 2px 8px; border-radius: 10px;
    text-transform: uppercase; letter-spacing: .06em;
  }
  .dev-type-chip.heat_pump { background: rgba(251,146,60,.15); color: #fb923c; }
  .dev-type-chip.airco     { background: rgba(56,189,248,.15);  color: #38bdf8; }
  .dev-type-chip.hybrid    { background: rgba(167,139,250,.15); color: #a78bfa; }

  .dev-metrics { display: flex; gap: 16px; flex-wrap: wrap; }
  .metric { display: flex; flex-direction: column; gap: 2px; }
  .metric-val  { font-size: .9rem; font-weight: 700; color: #e8eaf0; font-family: 'JetBrains Mono', monospace; }
  .metric-label{ font-size: .65rem; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }

  .dev-offset-row { display: flex; align-items: center; gap: 8px; }
  .offset-bar-bg {
    flex: 1; height: 4px; background: rgba(255,255,255,.08); border-radius: 4px; overflow: hidden;
  }
  .offset-bar-fill { height: 100%; border-radius: 4px; transition: width .4s ease; }
  .offset-bar-fill.positive { background: linear-gradient(90deg, #fb923c, #fbbf24); }
  .offset-bar-fill.negative { background: linear-gradient(90deg, #38bdf8, #818cf8); }
  .offset-val { font-size: .72rem; font-family: 'JetBrains Mono', monospace; color: #9ca3af; min-width: 48px; text-align: right; }

  .action-chip {
    font-size: .65rem; font-weight: 600; padding: 2px 8px; border-radius: 10px;
    text-transform: uppercase; letter-spacing: .05em;
  }
  .action-chip.heating { background: rgba(251,146,60,.15); color: #fb923c; }
  .action-chip.cooling { background: rgba(56,189,248,.15);  color: #38bdf8; }
  .action-chip.idle    { background: rgba(255,255,255,.06); color: #6b7280; }
  .action-chip.off     { background: rgba(255,255,255,.04); color: #4b5563; }

  /* ── Empty state ── */
  .empty { text-align: center; padding: 32px 16px; color: #4b5563; font-size: .85rem; }

  /* ── Footer ── */
  .footer { margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.06);
            display: flex; justify-content: space-between; align-items: center; }
  .footer-label { font-size: .68rem; color: #374151; font-family: 'JetBrains Mono', monospace; }

  /* ── Uitleg sectie ── */
  .explain-section { margin-top: 18px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,.06); }
  .explain-title { font-size: .75rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px; }
  .explain-table { width: 100%; border-collapse: collapse; font-size: .75rem; margin-bottom: 10px; }
  .explain-table th { color: #4b5563; font-weight: 600; padding: 4px 8px; text-align: left; border-bottom: 1px solid rgba(255,255,255,.06); }
  .explain-table td { color: #9ca3af; padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,.04); }
  .explain-table tr:last-child td { border-bottom: none; }
  .explain-note { font-size: .72rem; color: #4b5563; line-height: 1.5; font-style: italic; }
`;

// ── Mode → badge info ─────────────────────────────────────────────────────
function _modeBadge(mode, priceEur) {
  const fmt = priceEur != null ? ` · ${(priceEur * 100).toFixed(1)} ct` : "";
  if (mode === "cheap")   return { cls: "cheap",   icon: "🟢", label: `Goedkoop${fmt}` };
  if (mode === "dear")    return { cls: "dear",    icon: "🔴", label: `Duur${fmt}` };
  return                         { cls: "neutral", icon: "⚪", label: `Neutraal${fmt}` };
}

function _typeLabel(t) {
  if (t === "heat_pump") return "WP";
  if (t === "airco")     return "Airco";
  return "Hybride";
}

function _actionChip(action) {
  const map = { heating: "Verwarmt", cooling: "Koelt", idle: "Stand-by", off: "Uit" };
  return `<span class="action-chip ${action}">${map[action] || action}</span>`;
}

class CloudEMSClimateEpexCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
  }

  setConfig(config) {
    this._config = {
      title:        config.title        || "Klimaat EPEX",
      sensor:       config.sensor       || "sensor.cloudems_climate_epex_status",
      price_sensor: config.price_sensor || "sensor.cloudems_price_current_hour",
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;

    const epexSt  = this._hass.states[this._config.sensor];
    const priceSt = this._hass.states[this._config.price_sensor];

    const devices    = epexSt?.attributes?.devices    || [];
    const totalPower = epexSt?.attributes?.total_power_w ?? 0;
    const priceEur   = priceSt ? parseFloat(priceSt.state) : null;

    // Determine overall price mode from first device that has one, or from price level
    let globalMode = "neutral";
    if (devices.length > 0) {
      const modes = devices.map(d => d.mode).filter(Boolean);
      if (modes.includes("cheap")) globalMode = "cheap";
      else if (modes.includes("dear")) globalMode = "dear";
    } else if (priceEur != null) {
      globalMode = priceEur < 0.10 ? "cheap" : priceEur > 0.22 ? "dear" : "neutral";
    }

    const badge = _modeBadge(globalMode, priceEur);

    // Build device cards HTML
    let devHtml = "";
    if (devices.length === 0) {
      devHtml = `<div class="empty">Geen apparaten geconfigureerd.<br>Ga naar Instellingen → CloudEMS → Klimaat EPEX.</div>`;
    } else {
      for (const dev of devices) {
        const offsetAbs = Math.abs(dev.applied_offset ?? 0);
        const offsetSign = (dev.applied_offset ?? 0) >= 0 ? "positive" : "negative";
        const offsetPct  = Math.min(100, (offsetAbs / 2.0) * 100); // max 2°C = 100%
        const offsetLabel = dev.applied_offset > 0
          ? `+${dev.applied_offset.toFixed(1)}°C`
          : dev.applied_offset < 0
            ? `${dev.applied_offset.toFixed(1)}°C`
            : "0°C";

        const typeChipCls = dev.device_type || "heat_pump";
        const powerW = dev.power_w ?? 0;
        const curTemp = dev.current_temp != null ? `${dev.current_temp.toFixed(1)}°C` : "—";
        const tgtTemp = dev.target_temp  != null ? `${dev.target_temp.toFixed(1)}°C`  : "—";
        const baseTemp= dev.base_setpoint!= null ? `${dev.base_setpoint.toFixed(1)}°C`: "—";

        devHtml += `
          <div class="device-card ${dev.is_on ? "" : "off"}">
            <div class="dev-header">
              <span class="dev-name">${dev.label || dev.entity_id}</span>
              <div style="display:flex;gap:6px;align-items:center">
                ${_actionChip(dev.action || "off")}
                <span class="dev-type-chip ${typeChipCls}">${_typeLabel(typeChipCls)}</span>
              </div>
            </div>
            <div class="dev-metrics">
              <div class="metric">
                <span class="metric-val">${curTemp}</span>
                <span class="metric-label">Huidig</span>
              </div>
              <div class="metric">
                <span class="metric-val">${tgtTemp}</span>
                <span class="metric-label">Setpoint</span>
              </div>
              <div class="metric">
                <span class="metric-val">${baseTemp}</span>
                <span class="metric-label">Basis (geleerd)</span>
              </div>
              <div class="metric">
                <span class="metric-val">${powerW > 0 ? `${Math.round(powerW)}W` : "—"}</span>
                <span class="metric-label">Vermogen</span>
              </div>
            </div>
            <div class="dev-offset-row">
              <div class="offset-bar-bg">
                <div class="offset-bar-fill ${offsetSign}" style="width:${offsetPct}%"></div>
              </div>
              <span class="offset-val">Offset ${offsetLabel}</span>
            </div>
          </div>
        `;
      }
    }

    const totalFmt = totalPower >= 1000
      ? `${(totalPower / 1000).toFixed(2)}`
      : `${Math.round(totalPower)}`;
    const totalUnit = totalPower >= 1000 ? "kW" : "W";

    this.shadowRoot.innerHTML = `
      <style>${S}</style>
      <div class="card">
        <div class="inner">
          <div class="header">
            <span class="title">${this._config.title}</span>
            <span class="version">v${CE_CARD_VERSION}</span>
          </div>

          <div class="price-row">
            <span class="price-badge ${badge.cls}">${badge.icon} ${badge.label}</span>
            <span class="price-label">EPEX spotprijs dit uur</span>
          </div>

          <div class="total-row">
            <span class="total-val">${totalFmt}</span>
            <span class="total-unit">${totalUnit}</span>
            <span class="total-label">totaal vermogen</span>
          </div>

          <div class="devices">${devHtml}</div>

          <div class="footer">
            <span class="footer-label">sensor.cloudems_climate_epex_status</span>
            <span class="footer-label">${devices.length} apparaat${devices.length !== 1 ? "en" : ""}</span>
          </div>

          <div class="explain-section">
            <div class="explain-title">📊 Hoe werkt EPEX-sturing?</div>
            <table class="explain-table">
              <tr><th>Situatie</th><th>Warmtepomp</th><th>Airco</th></tr>
              <tr><td>🟢 Goedkoop (&lt;85% gem.)</td><td>+offset (voorverwarmen)</td><td>−offset (voorkoelen)</td></tr>
              <tr><td>⚪ Neutraal</td><td>geen offset</td><td>geen offset</td></tr>
              <tr><td>🔴 Duur (&gt;120% gem.)</td><td>−offset (zuiniger)</td><td>+offset (minder koelen)</td></tr>
            </table>
            <p class="explain-note">De module leert wanneer jij verwarmt/koelt en past offsets alleen toe als het apparaat actief is. Basissetpoints worden per apparaat en per uur bijgehouden via EMA-leren.</p>
          </div>
        </div>
      </div>
    `;
  }

  getCardSize() { return Math.max(3, 2 + (this._hass?.states[this._config?.sensor]?.attributes?.devices?.length || 1)); }

  // ── GUI Editor ───────────────────────────────────────────────────────────
  static getConfigElement() {
    return document.createElement("cloudems-climate-epex-card-editor");
  }

  static getStubConfig() {
    return {
      title:        "Klimaat EPEX",
      sensor:       "sensor.cloudems_climate_epex_status",
      price_sensor: "sensor.cloudems_price_current_hour",
    };
  }
}

// ── Editor ────────────────────────────────────────────────────────────────
class CloudEMSClimateEpexCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  _render() {
    const c = this._config;
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 12px; display: flex; flex-direction: column; gap: 10px; font-family: sans-serif; }
        label { font-size: .8rem; color: #6b7280; display: block; margin-bottom: 3px; }
        input { width: 100%; padding: 7px 10px; border-radius: 8px; border: 1px solid #374151;
                background: #1f2937; color: #e8eaf0; font-size: .85rem; }
      </style>
      <div class="editor">
        <div>
          <label>Titel</label>
          <input id="title" value="${c.title || "Klimaat EPEX"}">
        </div>
        <div>
          <label>EPEX sensor (entity_id)</label>
          <input id="sensor" value="${c.sensor || "sensor.cloudems_climate_epex_status"}">
        </div>
        <div>
          <label>Prijssensor (entity_id)</label>
          <input id="price_sensor" value="${c.price_sensor || "sensor.cloudems_price_current_hour"}">
        </div>
      </div>
    `;
    for (const id of ["title", "sensor", "price_sensor"]) {
      this.shadowRoot.getElementById(id).addEventListener("change", (e) => {
        this._config = { ...this._config, [id]: e.target.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
      });
    }
  }
}

if (!customElements.get('cloudems-climate-epex-card')) customElements.define("cloudems-climate-epex-card", CloudEMSClimateEpexCard);
if (!customElements.get('cloudems-climate-epex-card-editor')) customElements.define("cloudems-climate-epex-card-editor", CloudEMSClimateEpexCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "cloudems-climate-epex-card",
  name:        "CloudEMS Climate EPEX",
  description: "Live status van airco's en warmtepompen met EPEX-prijssturing",
  preview:     false,
  documentationURL: "https://cloudems.eu",
});
