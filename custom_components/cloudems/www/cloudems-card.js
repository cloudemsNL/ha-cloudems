/**
 * CloudEMS Dashboard Card — v1.3.0
 * Live energy overview with EPEX price chart, phase bars and EV charging status.
 * Copyright © 2025 CloudEMS — https://cloudems.eu
 */

import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.5.1/lit-element.js?module";

class CloudEMSCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _activeTab: { type: String },
    };
  }

  constructor() {
    super();
    this._activeTab = "overview";
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid CloudEMS card config");
    this.config = config;
  }

  static getConfigElement() {
    return document.createElement("cloudems-card-editor");
  }

  static getStubConfig() {
    return {
      grid_sensor: "sensor.cloudems_netspanning_vermogen",
      price_sensor: "sensor.cloudems_energieprijs",
      phase_sensors: [
        { label: "L1", entity: "sensor.cloudems_fase_l1_stroom", max_a: 25 },
        { label: "L2", entity: "sensor.cloudems_fase_l2_stroom", max_a: 25 },
        { label: "L3", entity: "sensor.cloudems_fase_l3_stroom", max_a: 25 },
      ],
      ev_sensor: "sensor.cloudems_ev_laadstroom_dynamisch",
      solar_sensor: "sensor.cloudems_netspanning_vermogen",
      inverter_sensors: [],
    };
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  _val(entity_id, fallback = null) {
    if (!entity_id || !this.hass) return fallback;
    const s = this.hass.states[entity_id];
    if (!s || s.state === "unavailable" || s.state === "unknown") return fallback;
    const n = parseFloat(s.state);
    return isNaN(n) ? s.state : n;
  }

  _attr(entity_id, attr, fallback = null) {
    if (!entity_id || !this.hass) return fallback;
    const s = this.hass.states[entity_id];
    return s?.attributes?.[attr] ?? fallback;
  }

  _priceColor(price) {
    if (price === null) return "#9ca3af";
    if (price < 0)    return "#10b981";   // green — negative
    if (price < 0.10) return "#34d399";   // light green
    if (price < 0.20) return "#fbbf24";   // amber
    if (price < 0.30) return "#f97316";   // orange
    return "#ef4444";                      // red — expensive
  }

  _phaseColor(pct) {
    if (pct < 60) return "#22c55e";
    if (pct < 80) return "#fbbf24";
    if (pct < 95) return "#f97316";
    return "#ef4444";
  }

  // ── EPEX price chart data ──────────────────────────────────────────────────

  _getEpexData() {
    const sensor = this.config.price_sensor;
    if (!sensor || !this.hass) return [];
    const prices = this._attr(sensor, "next_hours", []) || this._attr(sensor, "prices_today", []);
    if (!Array.isArray(prices) || prices.length === 0) return [];
    return prices; // expected: [{hour: 0, price: 0.12}, ...]
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  render() {
    const cfg = this.config;
    const gridW    = this._val(cfg.grid_sensor, 0);
    const solarW   = this._val(cfg.solar_sensor, 0);
    const price    = this._val(cfg.price_sensor, null);
    const evA      = this._val(cfg.ev_sensor, null);
    const evReason = this._attr(cfg.ev_sensor, "reason", "");

    const costPerHour = (price !== null && typeof gridW === "number")
      ? ((Math.abs(gridW) / 1000) * price).toFixed(3)
      : null;

    const tabs = ["overview", "phases", "prices", "ev", "inverters"];

    return html`
      <ha-card>
        <div class="header">
          <div class="logo">
            <span class="logo-icon">⚡</span>
            <span class="logo-text">CloudEMS</span>
          </div>
          <div class="price-badge" style="background:${this._priceColor(price)}">
            ${price !== null
              ? html`<span class="price-value">${price.toFixed(3)}</span><span class="price-unit"> €/kWh</span>`
              : html`<span class="price-value">—</span>`}
          </div>
        </div>

        <!-- Tab bar -->
        <div class="tabs">
          ${tabs.map(t => html`
            <button class="tab ${this._activeTab === t ? "active" : ""}"
                    @click=${() => this._activeTab = t}>
              ${{"overview":"Overzicht","phases":"Fasen","prices":"Prijzen","ev":"EV","inverters":"Omvormers"}[t]}
            </button>
          `)}
        </div>

        <!-- Tab content -->
        <div class="content">
          ${this._activeTab === "overview"  ? this._renderOverview(gridW, solarW, price, costPerHour)  : ""}
          ${this._activeTab === "phases"    ? this._renderPhases()    : ""}
          ${this._activeTab === "prices"    ? this._renderPrices()    : ""}
          ${this._activeTab === "ev"        ? this._renderEV(evA, evReason, price) : ""}
          ${this._activeTab === "inverters" ? this._renderInverters() : ""}
        </div>
      </ha-card>
    `;
  }

  // ── Overview tab ──────────────────────────────────────────────────────────

  _renderOverview(gridW, solarW, price, costPerHour) {
    const importing = typeof gridW === "number" && gridW > 0;
    const flowIcon  = importing ? "↓" : "↑";
    const flowLabel = importing ? "Afname" : "Teruglevering";
    const flowColor = importing ? "#f97316" : "#22c55e";

    return html`
      <div class="overview-grid">
        <!-- Power flow -->
        <div class="stat-card primary">
          <div class="stat-icon" style="color:${flowColor}">${flowIcon}</div>
          <div class="stat-label">${flowLabel} net</div>
          <div class="stat-value">${typeof gridW === "number" ? Math.abs(gridW).toFixed(0) : "—"}</div>
          <div class="stat-unit">W</div>
        </div>

        <!-- Solar -->
        <div class="stat-card">
          <div class="stat-icon">☀️</div>
          <div class="stat-label">Zonnepanelen</div>
          <div class="stat-value">${typeof solarW === "number" ? solarW.toFixed(0) : "—"}</div>
          <div class="stat-unit">W</div>
        </div>

        <!-- Cost/hour -->
        <div class="stat-card">
          <div class="stat-icon">💶</div>
          <div class="stat-label">Kosten nu</div>
          <div class="stat-value" style="color:${this._priceColor(price)}">
            ${costPerHour !== null ? costPerHour : "—"}
          </div>
          <div class="stat-unit">€/uur</div>
        </div>

        <!-- EPEX price -->
        <div class="stat-card">
          <div class="stat-icon">📈</div>
          <div class="stat-label">EPEX prijs</div>
          <div class="stat-value" style="color:${this._priceColor(price)}">
            ${price !== null ? price.toFixed(3) : "—"}
          </div>
          <div class="stat-unit">€/kWh</div>
        </div>
      </div>

      <!-- Tiny sparkline if price data available -->
      ${this._renderMiniSparkline()}
    `;
  }

  _renderMiniSparkline() {
    const data = this._getEpexData();
    if (data.length === 0) return html``;
    const prices = data.map(d => d.price ?? d.value ?? 0);
    const max = Math.max(...prices, 0.01);
    const min = Math.min(...prices);
    const range = max - min || 0.01;
    const w = 280, h = 50;
    const pts = prices.map((p, i) => {
      const x = (i / (prices.length - 1)) * w;
      const y = h - ((p - min) / range) * h;
      return `${x},${y}`;
    }).join(" ");

    return html`
      <div class="sparkline-wrap">
        <span class="sparkline-label">EPEX vandaag</span>
        <svg viewBox="0 0 ${w} ${h}" class="sparkline">
          <polyline points="${pts}" fill="none" stroke="#6366f1" stroke-width="2" />
        </svg>
      </div>
    `;
  }

  // ── Phases tab ────────────────────────────────────────────────────────────

  _renderPhases() {
    const phases = (this.config.phase_sensors || []);
    if (phases.length === 0) {
      return html`<div class="empty">Geen fase-sensors geconfigureerd in de kaartinstellingen.</div>`;
    }

    return html`
      <div class="phases-list">
        ${phases.map(p => this._renderPhaseRow(p.label || p.entity, p.entity, p.max_a || 25))}
      </div>
    `;
  }

  _renderPhaseRow(label, entity, maxA) {
    const current = this._val(entity, 0);
    const pct = typeof current === "number" ? Math.min(100, (current / maxA) * 100) : 0;
    const color = this._phaseColor(pct);

    return html`
      <div class="phase-row">
        <div class="phase-label">${label}</div>
        <div class="phase-bar-wrap">
          <div class="phase-bar" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="phase-current" style="color:${color}">
          ${typeof current === "number" ? current.toFixed(1) : "—"} A
        </div>
        <div class="phase-max">/ ${maxA} A</div>
      </div>
    `;
  }

  // ── Prices tab ────────────────────────────────────────────────────────────

  _renderPrices() {
    const data = this._getEpexData();
    if (data.length === 0) {
      return html`<div class="empty">Geen EPEX prijsdata beschikbaar.<br>Controleer of de CloudEMS integratie actief is.</div>`;
    }

    const now = new Date().getHours();
    const prices = data.map(d => d.price ?? d.value ?? 0);
    const max = Math.max(...prices, 0.001);
    const min = Math.min(...prices);

    return html`
      <div class="price-chart">
        ${data.map((d, i) => {
          const hour   = d.hour ?? i;
          const price  = d.price ?? d.value ?? 0;
          const barH   = Math.max(4, ((price - min) / (max - min + 0.001)) * 100);
          const color  = this._priceColor(price);
          const active = hour === now;
          return html`
            <div class="bar-wrap ${active ? "active" : ""}">
              <div class="bar-tooltip">${hour}:00 — €${price.toFixed(3)}</div>
              <div class="bar" style="height:${barH}%;background:${color}"></div>
              <div class="bar-label">${hour}</div>
            </div>
          `;
        })}
      </div>
      <div class="price-legend">
        <span style="color:#10b981">■ Goedkoop</span>
        <span style="color:#fbbf24">■ Gemiddeld</span>
        <span style="color:#ef4444">■ Duur</span>
      </div>
    `;
  }

  // ── EV tab ────────────────────────────────────────────────────────────────

  _renderEV(evA, reason, price) {
    const charging = typeof evA === "number" && evA > 0;

    return html`
      <div class="ev-panel">
        <div class="ev-status ${charging ? "charging" : "idle"}">
          <span class="ev-icon">${charging ? "🔌" : "🚗"}</span>
          <span class="ev-state">${charging ? `Aan het laden — ${evA?.toFixed(1)} A` : "Niet aan het laden"}</span>
        </div>
        ${reason ? html`<div class="ev-reason">💬 ${reason}</div>` : ""}
        ${price !== null ? html`
          <div class="ev-price-info">
            Huidige EPEX prijs: <strong style="color:${this._priceColor(price)}">${price.toFixed(3)} €/kWh</strong>
          </div>
        ` : ""}
        <div class="ev-tip">
          Stel de goedkope-prijs drempel in via <em>CloudEMS → Instellingen</em> om
          automatisch te laden op het goedkoopste moment.
        </div>
      </div>
    `;
  }


  // ── Inverters tab (v1.3.0) ───────────────────────────────────────────────

  _renderInverters() {
    const invSensors = this.config.inverter_sensors || [];
    if (invSensors.length === 0) {
      return html`<div class="empty">
        Geen omvormers geconfigureerd.<br>
        Voeg <code>inverter_sensors</code> toe aan de kaartinstellingen,<br>
        of schakel Multi-Omvormer in via CloudEMS → Instellingen.
      </div>`;
    }

    return html`
      <div class="phases-list">
        ${invSensors.map(inv => this._renderInverterRow(inv))}
      </div>
    `;
  }

  _renderInverterRow(inv) {
    const entity  = typeof inv === "string" ? inv : inv.entity;
    const label   = (typeof inv === "object" && inv.label) ? inv.label : entity;
    const peakW   = typeof inv === "object" ? (inv.peak_w || 0) : 0;

    const state = this.hass?.states[entity];
    const currentW = state && state.state !== "unavailable"
      ? parseFloat(state.state) || 0 : null;

    const learnedPeak = state?.attributes?.peak_power_w || peakW;
    const estimatedWp = state?.attributes?.estimated_wp;
    const detectedPhase = state?.attributes?.detected_phase;
    const phaseCertain  = state?.attributes?.phase_certain;
    const outputPct     = state?.attributes?.current_output_pct ?? 100;
    const confident     = state?.attributes?.confident;

    const pct = learnedPeak > 0 && currentW !== null
      ? Math.min(100, (currentW / learnedPeak) * 100) : 0;
    const color = this._phaseColor(outputPct < 100 ? 80 : pct);

    return html`
      <div class="phase-row" style="grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
        <div style="grid-column: span 2; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight:600; font-size:0.85rem;">☀️ ${label}</span>
          <span style="font-size:0.7rem; color:var(--cloudems-subtext)">
            ${detectedPhase
              ? html`Fase <strong style="color:${color}">${detectedPhase}</strong>${phaseCertain ? " ✓" : " ?"}`
              : html`<span style="color:#fbbf24">Fase onbekend</span>`}
          </span>
        </div>
        <!-- Productie-balk -->
        <div class="phase-bar-wrap" style="grid-column: span 2; height:10px;">
          <div class="phase-bar" style="width:${pct}%; background:${color}"></div>
        </div>
        <!-- Waarden -->
        <div style="font-size:0.78rem;">
          <span style="color:var(--cloudems-subtext)">Nu: </span>
          <strong>${currentW !== null ? currentW.toFixed(0) : "—"} W</strong>
        </div>
        <div style="font-size:0.78rem; text-align:right;">
          <span style="color:var(--cloudems-subtext)">Piek: </span>
          <strong>${learnedPeak > 0 ? learnedPeak.toFixed(0) : "Aan het leren…"} W</strong>
          ${estimatedWp ? html`<span style="color:var(--cloudems-subtext)"> (~${estimatedWp} Wp)</span>` : ""}
        </div>
        <!-- PID output indicator -->
        ${outputPct < 100 ? html`
          <div style="grid-column: span 2; font-size:0.72rem; color:#f97316; border-left: 2px solid #f97316; padding-left:6px;">
            ⚡ Gedimmd naar ${outputPct.toFixed(0)}% (fase-bescherming of negatieve prijs)
          </div>
        ` : ""}
        ${!confident && learnedPeak === 0 ? html`
          <div style="grid-column: span 2; font-size:0.72rem; color:var(--cloudems-subtext); border-left:2px solid #6366f1; padding-left:6px;">
            📡 Piekvermogen en fase worden geleerd…
          </div>
        ` : ""}
      </div>
    `;
  }

  // ── Styles ─────────────────────────────────────────────────────────────────

  static get styles() {
    return css`
      ha-card {
        --cloudems-bg: var(--card-background-color, #1e1e2e);
        --cloudems-text: var(--primary-text-color, #cdd6f4);
        --cloudems-subtext: var(--secondary-text-color, #7f849c);
        background: var(--cloudems-bg);
        color: var(--cloudems-text);
        border-radius: 16px;
        overflow: hidden;
        font-family: var(--paper-font-body1_-_font-family, sans-serif);
      }

      /* Header */
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 18px 8px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
      }
      .logo { display: flex; align-items: center; gap: 8px; }
      .logo-icon { font-size: 1.4rem; }
      .logo-text { font-size: 1.1rem; font-weight: 700; letter-spacing: 0.02em; }
      .price-badge {
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 0.85rem;
        font-weight: 700;
        color: #fff;
      }
      .price-unit { font-size: 0.7rem; font-weight: 400; }

      /* Tabs */
      .tabs {
        display: flex;
        padding: 8px 12px 0;
        gap: 4px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
      }
      .tab {
        flex: 1;
        background: none;
        border: none;
        color: var(--cloudems-subtext);
        font-size: 0.78rem;
        padding: 6px 4px;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.15s;
      }
      .tab.active {
        color: #6366f1;
        border-bottom-color: #6366f1;
        font-weight: 600;
      }
      .tab:hover { color: var(--cloudems-text); }

      /* Content */
      .content { padding: 14px 16px 16px; }
      .empty {
        text-align: center;
        color: var(--cloudems-subtext);
        padding: 24px 0;
        font-size: 0.85rem;
        line-height: 1.6;
      }

      /* Overview grid */
      .overview-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        margin-bottom: 12px;
      }
      .stat-card {
        background: rgba(255,255,255,0.04);
        border-radius: 12px;
        padding: 12px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
      }
      .stat-card.primary { grid-column: span 2; flex-direction: row; gap: 12px; justify-content: center; }
      .stat-icon { font-size: 1.4rem; }
      .stat-label { font-size: 0.7rem; color: var(--cloudems-subtext); text-align: center; }
      .stat-value { font-size: 1.5rem; font-weight: 700; }
      .stat-unit  { font-size: 0.7rem; color: var(--cloudems-subtext); }

      /* Sparkline */
      .sparkline-wrap { display: flex; flex-direction: column; gap: 4px; }
      .sparkline-label { font-size: 0.7rem; color: var(--cloudems-subtext); }
      .sparkline { width: 100%; height: 50px; }

      /* Phases */
      .phases-list { display: flex; flex-direction: column; gap: 10px; }
      .phase-row { display: grid; grid-template-columns: 30px 1fr 60px 44px; align-items: center; gap: 8px; }
      .phase-label { font-size: 0.75rem; font-weight: 600; }
      .phase-bar-wrap { background: rgba(255,255,255,0.08); border-radius: 4px; height: 8px; overflow: hidden; }
      .phase-bar { height: 100%; border-radius: 4px; transition: width 0.4s; }
      .phase-current { font-size: 0.8rem; font-weight: 600; text-align: right; }
      .phase-max { font-size: 0.7rem; color: var(--cloudems-subtext); }

      /* Price chart */
      .price-chart {
        display: flex;
        align-items: flex-end;
        gap: 2px;
        height: 100px;
        padding-bottom: 20px;
        position: relative;
      }
      .bar-wrap {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-end;
        position: relative;
        height: 100%;
        cursor: pointer;
      }
      .bar-wrap.active .bar { outline: 2px solid #fff; outline-offset: 1px; }
      .bar { width: 100%; min-height: 4px; border-radius: 2px 2px 0 0; transition: height 0.3s; }
      .bar-label { font-size: 0.55rem; color: var(--cloudems-subtext); position: absolute; bottom: -18px; }
      .bar-tooltip {
        display: none;
        position: absolute;
        bottom: 105%;
        background: #313244;
        color: #cdd6f4;
        font-size: 0.65rem;
        padding: 3px 6px;
        border-radius: 6px;
        white-space: nowrap;
        z-index: 10;
        pointer-events: none;
      }
      .bar-wrap:hover .bar-tooltip { display: block; }
      .price-legend {
        display: flex;
        gap: 12px;
        font-size: 0.7rem;
        color: var(--cloudems-subtext);
        margin-top: 24px;
        justify-content: center;
      }

      /* EV panel */
      .ev-panel { display: flex; flex-direction: column; gap: 12px; }
      .ev-status {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        border-radius: 12px;
        background: rgba(255,255,255,0.04);
      }
      .ev-status.charging { background: rgba(34,197,94,0.12); }
      .ev-icon { font-size: 1.8rem; }
      .ev-state { font-size: 0.9rem; font-weight: 600; }
      .ev-reason {
        font-size: 0.78rem;
        color: var(--cloudems-subtext);
        padding: 0 4px;
      }
      .ev-price-info { font-size: 0.82rem; padding: 0 4px; }
      .ev-tip {
        font-size: 0.72rem;
        color: var(--cloudems-subtext);
        line-height: 1.5;
        border-left: 2px solid #6366f1;
        padding-left: 8px;
      }
    `;
  }
}

customElements.define("cloudems-card", CloudEMSCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "cloudems-card",
  name:        "CloudEMS Dashboard",
  description: "Live energie overzicht — EPEX prijzen, fase bewaking, EV laden, omvormer PID (v1.3)",
  preview:     true,
});
