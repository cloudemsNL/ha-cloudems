/**
 * CloudEMS Dashboard Card — v1.10.1
 * Visual energy overview: flow diagram · NILM device cards · battery health ·
 * PV forecast · phase bars · EPEX price chart · EV charging · congestion alerts.
 * Copyright © 2025 CloudEMS — https://cloudems.eu
 */

import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.5.1/lit-element.js?module";

// ── Device type icon map ──────────────────────────────────────────────────────
const DEVICE_ICONS = {
  refrigerator:    { emoji: "🧊", color: "#60a5fa", label: "Koelkast/Vriezer" },
  washing_machine: { emoji: "🫧", color: "#818cf8", label: "Wasmachine" },
  dryer:           { emoji: "🌀", color: "#a78bfa", label: "Droogtrommel" },
  dishwasher:      { emoji: "🍽️", color: "#34d399", label: "Vaatwasser" },
  oven:            { emoji: "🔥", color: "#fb923c", label: "Oven/Kookplaat" },
  microwave:       { emoji: "📡", color: "#fbbf24", label: "Magnetron" },
  boiler:          { emoji: "🚿", color: "#22d3ee", label: "Boiler/Douche" },
  heat_pump:       { emoji: "🌡️", color: "#f472b6", label: "Warmtepomp/AC" },
  cv_boiler:       { emoji: "🏠", color: "#fb923c", label: "CV-ketel" },
  ev_charger:      { emoji: "⚡", color: "#4ade80", label: "Laadpaal" },
  light:           { emoji: "💡", color: "#fde68a", label: "Verlichting" },
  solar_inverter:  { emoji: "☀️", color: "#fbbf24", label: "Omvormer" },
  entertainment:   { emoji: "🖥️", color: "#818cf8", label: "TV/Computer" },
  kitchen:         { emoji: "☕", color: "#d97706", label: "Keukenapparaat" },
  power_tool:      { emoji: "🔨", color: "#9ca3af", label: "Gereedschap" },
  garden:          { emoji: "🌿", color: "#86efac", label: "Tuin" },
  medical:         { emoji: "❤️", color: "#f87171", label: "Medisch" },
  unknown:         { emoji: "🔌", color: "#9ca3af", label: "Onbekend" },
};

class CloudEMSCard extends LitElement {
  static get properties() {
    return {
      hass:       { type: Object },
      config:     { type: Object },
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
      grid_sensor:      "sensor.cloudems_grid_power_w",
      solar_sensor:     "sensor.cloudems_solar_power_w",
      battery_soh:      "sensor.cloudems_battery_state_of_health",
      congestion:       "sensor.cloudems_grid_congestion_utilisation",
      nilm_sensor:      "sensor.cloudems_nilm_running_devices",
      price_sensor:     "sensor.cloudems_energieprijs",
      forecast_sensor:  "sensor.cloudems_solar_pv_forecast_today",
      hints_sensor:     "sensor.cloudems_sensor_hints",
      ev_sensor:        "sensor.cloudems_ev_laadstroom_dynamisch",
      inverter_sensors: [],
      phase_sensors: [
        { label: "L1", entity: "sensor.cloudems_fase_l1_stroom", max_a: 25 },
        { label: "L2", entity: "sensor.cloudems_fase_l2_stroom", max_a: 25 },
        { label: "L3", entity: "sensor.cloudems_fase_l3_stroom", max_a: 25 },
      ],
    };
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  _val(eid, fb = null) {
    if (!eid || !this.hass) return fb;
    const s = this.hass.states[eid];
    if (!s || ["unavailable", "unknown", ""].includes(s.state)) return fb;
    const n = parseFloat(s.state);
    return isNaN(n) ? s.state : n;
  }

  _attr(eid, attr, fb = null) {
    if (!eid || !this.hass) return fb;
    return this.hass.states[eid]?.attributes?.[attr] ?? fb;
  }

  _priceColor(p) {
    if (p === null || p === undefined) return "#9ca3af";
    if (p < 0)    return "#10b981";
    if (p < 0.10) return "#34d399";
    if (p < 0.20) return "#fbbf24";
    if (p < 0.30) return "#f97316";
    return "#ef4444";
  }

  _phaseColor(pct) {
    if (pct < 60) return "#22c55e";
    if (pct < 80) return "#fbbf24";
    if (pct < 95) return "#f97316";
    return "#ef4444";
  }

  _fmt(w) {
    if (w === null || w === undefined) return "—";
    const abs = Math.abs(w);
    if (abs >= 1000) return (w / 1000).toFixed(1) + " kW";
    return Math.round(w) + " W";
  }

  // ── Main render ──────────────────────────────────────────────────────────

  render() {
    if (!this.hass || !this.config) return html``;

    const gridW       = this._val(this.config.grid_sensor, 0);
    const solarW      = this._val(this.config.solar_sensor, 0);
    const price       = this._val(this.config.price_sensor);
    const costPerHour = this._attr(this.config.price_sensor, "cost_per_hour");
    const evA         = this._val(this.config.ev_sensor);
    const evReason    = this._attr(this.config.ev_sensor, "reason", "");
    const soh         = this._val(this.config.battery_soh);
    const congPct     = this._val(this.config.congestion);
    const congActive  = this._attr(this.config.congestion, "active", false);

    const TABS = [
      { id: "overview",  label: "🏠", title: "Overzicht" },
      { id: "devices",   label: "🔌", title: "Apparaten" },
      { id: "forecast",  label: "☀️", title: "PV Prognose" },
      { id: "phases",    label: "⚡", title: "Fasen" },
      { id: "prices",    label: "💶", title: "Prijzen" },
      { id: "ev",        label: "🚗", title: "EV Laden" },
      { id: "inverters", label: "🔆", title: "Omvormers" },
    ];

    return html`
      <ha-card>
        <div class="header">
          <div class="logo">
            <span class="logo-mark">⚡</span>
            <span class="logo-text">CloudEMS</span>
            ${soh !== null ? html`
              <span class="soh-pill ${soh < 80 ? "crit" : soh < 90 ? "warn" : "ok"}">
                🔋 ${soh.toFixed(0)}%
              </span>` : ""}
          </div>
          <div class="header-right">
            ${congActive ? html`<span class="cong-pill">⚠️ ${congPct?.toFixed(0)}%</span>` : ""}
            ${price !== null ? html`
              <span class="price-pill" style="background:${this._priceColor(price)}20;color:${this._priceColor(price)};border-color:${this._priceColor(price)}40">
                €${price.toFixed(3)}<span class="price-unit">/kWh</span>
              </span>` : ""}
          </div>
        </div>

        <div class="tabs" role="tablist">
          ${TABS.map(t => html`
            <button class="tab ${this._activeTab === t.id ? "active" : ""}"
              title="${t.title}"
              @click=${() => { this._activeTab = t.id; }}>
              <span class="tab-icon">${t.label}</span>
              <span class="tab-label">${t.title}</span>
            </button>`)}
        </div>

        <div class="content">
          ${this._activeTab === "overview"  ? this._renderOverview(gridW, solarW, price, costPerHour, soh, congPct, congActive) : ""}
          ${this._activeTab === "devices"   ? this._renderDevices()   : ""}
          ${this._activeTab === "forecast"  ? this._renderForecast()  : ""}
          ${this._activeTab === "phases"    ? this._renderPhases()    : ""}
          ${this._activeTab === "prices"    ? this._renderPrices()    : ""}
          ${this._activeTab === "ev"        ? this._renderEV(evA, evReason, price) : ""}
          ${this._activeTab === "inverters" ? this._renderInverters() : ""}
        </div>
      </ha-card>
    `;
  }

  // ── Overview ─────────────────────────────────────────────────────────────

  _renderOverview(gridW, solarW, price, costPerHour, soh, congPct, congActive) {
    const importW = Math.max(0, gridW);
    const exportW = gridW < 0 ? Math.abs(gridW) : 0;
    const solar   = Math.max(0, solarW || 0);
    const houseW  = Math.max(0, solar + importW - exportW);

    const gc = exportW > 0 ? "#10b981" : importW > 200 ? "#f97316" : "#6366f1";
    const sc = solar > 100 ? "#fbbf24" : "#475569";

    // SVG arrow sizes proportional to power (1–4px)
    const gf = Math.min(4, Math.max(1, importW / 800));
    const sf = Math.min(4, Math.max(1, solar / 800));

    return html`
      <!-- Energy flow SVG ────────────────── -->
      <svg class="flow-svg" viewBox="0 0 310 170" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="glow-s"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glow-g"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>

        <!-- Grid node (left) -->
        <circle cx="38" cy="85" r="28" fill="${gc}18" stroke="${gc}" stroke-width="1.8"/>
        <text x="38" y="78" text-anchor="middle" font-size="17">🏭</text>
        <text x="38" y="93" text-anchor="middle" font-size="7" fill="${gc}" font-weight="700">Net</text>
        <text x="38" y="103" text-anchor="middle" font-size="6.5" fill="#94a3b8">
          ${importW > 50 ? "▼" + this._fmt(importW) : exportW > 50 ? "▲" + this._fmt(exportW) : "—"}
        </text>

        <!-- Solar node (top-center) -->
        <circle cx="155" cy="28" r="24" fill="${sc}18" stroke="${sc}" stroke-width="1.8"
          filter="${solar > 200 ? "url(#glow-s)" : "none"}"/>
        <text x="155" y="22" text-anchor="middle" font-size="15">☀️</text>
        <text x="155" y="35" text-anchor="middle" font-size="6.5" fill="${sc}" font-weight="700">Zonnestroom</text>
        <text x="155" y="44" text-anchor="middle" font-size="6.5" fill="#94a3b8">${this._fmt(solar)}</text>

        <!-- House node (center) -->
        <circle cx="155" cy="105" r="28" fill="#6366f118" stroke="#6366f1" stroke-width="1.8"/>
        <text x="155" y="98" text-anchor="middle" font-size="17">🏠</text>
        <text x="155" y="113" text-anchor="middle" font-size="7" fill="#818cf8" font-weight="700">Verbruik</text>
        <text x="155" y="123" text-anchor="middle" font-size="6.5" fill="#94a3b8">${this._fmt(houseW)}</text>

        <!-- Battery node (right, optional) -->
        ${soh !== null ? html`
          <circle cx="272" cy="85" r="24" fill="${soh < 80 ? "#f8717118" : "#22c55e18"}" stroke="${soh < 80 ? "#f87171" : "#22c55e"}" stroke-width="1.8"/>
          <text x="272" y="79" text-anchor="middle" font-size="15">🔋</text>
          <text x="272" y="92" text-anchor="middle" font-size="6.5" fill="${soh < 80 ? "#f87171" : "#4ade80"}" font-weight="700">Batterij</text>
          <text x="272" y="102" text-anchor="middle" font-size="6.5" fill="#94a3b8">${soh?.toFixed(0)}% SoH</text>
          <!-- Battery connector -->
          <line x1="248" y1="85" x2="183" y2="98" stroke="${soh < 80 ? "#f87171" : "#22c55e"}" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.5"/>
        ` : ""}

        <!-- Grid → House (import) -->
        ${importW > 50 ? html`
          <path d="M66,87 Q110,95 127,103" fill="none" stroke="${gc}" stroke-width="${gf}" opacity="0.85"
            marker-end="url(#arr-in)"/>
        ` : ""}

        <!-- House → Grid (export) -->
        ${exportW > 50 ? html`
          <path d="M127,107 Q100,100 66,90" fill="none" stroke="#10b981" stroke-width="${gf}" opacity="0.85"
            marker-end="url(#arr-exp)"/>
        ` : ""}

        <!-- Solar → House -->
        ${solar > 50 ? html`
          <line x1="155" y1="52" x2="155" y2="77" stroke="${sc}" stroke-width="${sf}" opacity="0.85"
            marker-end="url(#arr-sol)"/>
        ` : ""}

        <!-- Arrow markers -->
        <defs>
          <marker id="arr-in"  markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 Z" fill="${gc}" opacity="0.8"/></marker>
          <marker id="arr-exp" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 Z" fill="#10b981" opacity="0.8"/></marker>
          <marker id="arr-sol" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 Z" fill="${sc}" opacity="0.8"/></marker>
        </defs>
      </svg>

      <!-- Stats grid ─────────────────────── -->
      <div class="stat-grid">
        <div class="stat-tile">
          <div class="st-icon">💶</div>
          <div class="st-val" style="color:${this._priceColor(price)}">${price !== null ? "€" + price.toFixed(3) : "—"}</div>
          <div class="st-lbl">Prijs /kWh</div>
        </div>
        <div class="stat-tile">
          <div class="st-icon">⏱️</div>
          <div class="st-val">${costPerHour != null ? "€" + Number(costPerHour).toFixed(3) : "—"}</div>
          <div class="st-lbl">Kosten /uur</div>
        </div>
        <div class="stat-tile">
          <div class="st-icon">☀️</div>
          <div class="st-val" style="color:#fbbf24">${this._fmt(solar)}</div>
          <div class="st-lbl">Zonnestroom</div>
        </div>
        <div class="stat-tile ${importW > 0 ? "tile-warn" : "tile-ok"}">
          <div class="st-icon">${importW > 0 ? "📥" : "📤"}</div>
          <div class="st-val" style="color:${importW > 0 ? "#f97316" : "#10b981"}">
            ${importW > 0 ? this._fmt(importW) : this._fmt(exportW)}
          </div>
          <div class="st-lbl">${importW > 0 ? "Afname net" : "Teruglevering"}</div>
        </div>
      </div>

      ${congActive ? html`
        <div class="alert-bar cong">
          <span>⚠️</span>
          <span><strong>Netcongestie actief</strong> — ${congPct?.toFixed(0)}% netbenutting. CloudEMS past belasting automatisch aan.</span>
        </div>` : ""}
      ${this._renderHints()}
    `;
  }

  // ── Sensor hints ─────────────────────────────────────────────────────────

  _renderHints() {
    const eid   = this.config.hints_sensor;
    if (!eid) return "";
    const hints = this._attr(eid, "hints", []) || [];
    const active = hints.filter(h => !h.dismissed);
    if (!active.length) return "";
    return html`
      <div class="hints-wrap">
        ${active.map(h => html`
          <div class="hint-card">
            <div class="hint-icon">💡</div>
            <div class="hint-body">
              <div class="hint-title">${h.title}</div>
              <div class="hint-msg">${h.message}</div>
              <div class="hint-conf">Zekerheid: ${Math.round((h.confidence || 0) * 100)}%</div>
            </div>
          </div>`)}
      </div>`;
  }

  // ── Devices (NILM) ───────────────────────────────────────────────────────

  _renderDevices() {
    const nilmEid = this.config.nilm_sensor;
    if (!nilmEid) return html`<div class="empty">Voeg <code>nilm_sensor</code> toe aan de kaartconfiguratie.</div>`;

    const devices  = this._attr(nilmEid, "devices", []) || [];
    const running  = devices.filter(d => d.state === "on" || d.running);
    const detected = devices.filter(d => !d.running && d.state !== "on" && !d.dismissed);
    const nilmMode = this._attr(nilmEid, "nilm_mode", "pattern");

    const modeLabel = { cloud: "☁️ CloudAI", ollama: "🦙 Ollama", pattern: "📊 Patroon" };

    return html`
      <div class="devices-hdr">
        <span class="devices-title">NILM Apparaatherkenning</span>
        <span class="mode-chip">${modeLabel[nilmMode] ?? nilmMode}</span>
      </div>

      ${running.length > 0 ? html`
        <div class="section-lbl">🟢 Actief nu</div>
        <div class="device-grid">${running.map(d => this._renderDeviceCard(d, true))}</div>
      ` : html`<p class="no-running">Geen actieve apparaten op dit moment</p>`}

      ${detected.length > 0 ? html`
        <div class="section-lbl" style="margin-top:14px">🔍 Recent gedetecteerd</div>
        <div class="device-grid">${detected.map(d => this._renderDeviceCard(d, false))}</div>
      ` : ""}

      ${devices.length === 0 ? html`
        <div class="empty">
          CloudEMS leert je apparaten kennen.<br>
          Na een paar uur verschijnen hier je apparaten.
        </div>` : ""}
    `;
  }

  _renderDeviceCard(device, active) {
    const type = device.device_type || "unknown";
    const icon = DEVICE_ICONS[type] || DEVICE_ICONS.unknown;
    const name = device.name || icon.label;
    const conf = device.confidence ? Math.round(device.confidence * 100) : null;
    const pw   = device.power_w ?? device.power_min;
    const src  = { community: "🌐", ai: "🤖", builtin: "📊" }[device.source] ?? "📊";

    return html`
      <div class="dev-card ${active ? "dev-active" : ""}">
        ${active ? html`<span class="dev-dot"></span>` : ""}
        <div class="dev-icon" style="background:${icon.color}1a;border-color:${icon.color}33">
          ${icon.emoji}
        </div>
        <div class="dev-body">
          <div class="dev-name">${name}</div>
          <div class="dev-type" style="color:${icon.color}">${icon.label}${pw ? " · ~" + this._fmt(pw) : ""}</div>
          ${conf !== null ? html`
            <div class="conf-bar"><div class="conf-fill" style="width:${conf}%;background:${conf > 70 ? "#4ade80" : conf > 45 ? "#fbbf24" : "#f97316"}"></div></div>
            <div class="dev-conf">${src} ${conf}% zekerheid</div>` : ""}
        </div>
      </div>`;
  }

  // ── PV Forecast ──────────────────────────────────────────────────────────

  _renderForecast() {
    const eid    = this.config.forecast_sensor;
    if (!eid) return html`<div class="empty">Stel <code>forecast_sensor</code> in.</div>`;

    const today  = this._val(eid);
    const tomEid = eid.replace("_today", "_tomorrow");
    const tom    = this._val(tomEid);
    const hourly = this._attr(eid, "hourly", []) || [];
    const now    = new Date().getHours();
    const maxW   = hourly.length ? Math.max(...hourly.map(h => (h.forecast_w ?? h ?? 0)), 1) : 1;

    return html`
      <div class="forecast-row">
        <div class="fc-card">
          <div class="fc-emoji">☀️</div>
          <div class="fc-kwh">${today !== null ? today.toFixed(1) + " kWh" : "—"}</div>
          <div class="fc-day">Vandaag</div>
        </div>
        <div class="fc-card fc-dim">
          <div class="fc-emoji">🌤️</div>
          <div class="fc-kwh">${tom !== null ? tom.toFixed(1) + " kWh" : "—"}</div>
          <div class="fc-day">Morgen</div>
        </div>
      </div>

      ${hourly.length > 0 ? html`
        <div class="chart-lbl">Uurprofiel vandaag</div>
        <div class="fc-chart">
          ${hourly.map((h, i) => {
            const w   = h.forecast_w !== undefined ? h.forecast_w : (typeof h === "number" ? h : 0);
            const hr  = h.hour !== undefined ? h.hour : i;
            const pct = Math.max(2, (w / maxW) * 100);
            const cur = hr === now;
            return html`
              <div class="fc-col ${cur ? "fc-now" : ""}">
                <div class="fc-tip">${hr}:00 · ${w.toFixed(0)}W</div>
                <div class="fc-bar" style="height:${pct}%;background:${cur ? "#fbbf24" : w > maxW * 0.7 ? "#f59e0b" : "#6366f1"}"></div>
                ${hr % 4 === 0 ? html`<div class="fc-lbl">${hr}h</div>` : ""}
              </div>`;
          })}
        </div>
      ` : html`<div class="empty" style="padding:16px 0">CloudEMS leert je zonneprofiel — na een paar dagen verschijnt de prognose hier.</div>`}
    `;
  }

  // ── Phases ───────────────────────────────────────────────────────────────

  _renderPhases() {
    const phases = this.config.phase_sensors || [];
    if (!phases.length) return html`<div class="empty">Geen fasesensoren geconfigureerd.</div>`;
    return html`<div class="phase-list">${phases.map(p => this._renderPhaseRow(p.label || "L?", p.entity, p.max_a || 25))}</div>`;
  }

  _renderPhaseRow(label, eid, maxA) {
    const val  = this._val(eid);
    const absA = val !== null ? Math.abs(val) : null;
    const pct  = absA !== null ? Math.min(100, (absA / maxA) * 100) : 0;
    const col  = this._phaseColor(pct);
    const dir  = val !== null && val < 0 ? " ↩" : "";
    return html`
      <div class="phase-row">
        <div class="ph-lbl" style="color:${col}">${label}</div>
        <div class="ph-bar-wrap"><div class="ph-bar" style="width:${pct}%;background:${col}"></div></div>
        <div class="ph-val" style="color:${col}">${absA !== null ? absA.toFixed(1) + " A" + dir : "—"}</div>
        <div class="ph-max">${maxA} A</div>
      </div>`;
  }

  // ── Prices ───────────────────────────────────────────────────────────────

  _renderPrices() {
    const eid    = this.config.price_sensor;
    const prices = this._attr(eid, "prices_today", []) || [];
    const now    = new Date().getHours();
    if (!prices.length) return html`<div class="empty">Geen prijsgegevens beschikbaar.</div>`;
    const maxP = Math.max(...prices.map(p => Math.abs(typeof p === "object" ? p.price : p)), 0.01);

    return html`
      <div class="price-chart">
        ${prices.map((entry, i) => {
          const p   = typeof entry === "object" ? entry.price : entry;
          const hr  = typeof entry === "object" ? entry.hour  : i;
          const pct = (Math.abs(p) / maxP) * 82;
          const col = this._priceColor(p);
          return html`
            <div class="pc-wrap ${hr === now ? "pc-now" : ""}">
              <div class="pc-tip">€${p.toFixed(3)}</div>
              <div class="pc-bar" style="height:${Math.max(3,pct)}px;background:${col}"></div>
              ${hr % 6 === 0 ? html`<div class="pc-lbl">${hr}h</div>` : ""}
            </div>`;
        })}
      </div>
      <div class="price-legend">
        <span>🟢 &lt;€0.10</span><span>🟡 €0.10–0.20</span>
        <span>🟠 €0.20–0.30</span><span>🔴 &gt;€0.30</span>
      </div>`;
  }

  // ── EV ───────────────────────────────────────────────────────────────────

  _renderEV(evA, reason, price) {
    const charging = evA !== null && evA > 0;
    return html`
      <div class="ev-wrap">
        <div class="ev-status ${charging ? "ev-on" : ""}">
          <div class="ev-ico">${charging ? "⚡" : "🚗"}</div>
          <div>
            <div class="ev-state">${charging ? "Laden · " + evA?.toFixed(1) + " A" : "Niet aan het laden"}</div>
            <div class="ev-reason">${reason || (charging ? "Dynamisch gestuurd door CloudEMS" : "Wachten op lage prijs of PV-surplus")}</div>
          </div>
        </div>
        ${price !== null ? html`
          <div class="ev-price">
            Huidig tarief: <strong style="color:${this._priceColor(price)}">€${price.toFixed(3)}/kWh</strong>
            ${price < 0 ? html`<span style="color:#10b981"> — GRATIS laden!</span>` :
              price < 0.10 ? html`<span style="color:#34d399"> — goedkoop uur ✓</span>` : ""}
          </div>` : ""}
        <div class="ev-tip">CloudEMS past het laadvermogen automatisch aan op basis van EPEX-prijs, zonnepaneeloverschot en fasebegrenzing.</div>
      </div>`;
  }

  // ── Inverters ────────────────────────────────────────────────────────────

  _renderInverters() {
    const invs = this.config.inverter_sensors || [];
    if (!invs.length) return html`<div class="empty">Geen omvormers geconfigureerd.<br>Voeg <code>inverter_sensors</code> toe.</div>`;
    return html`<div class="phase-list">${invs.map(inv => this._renderInvRow(inv))}</div>`;
  }

  _renderInvRow(inv) {
    const eid  = typeof inv === "string" ? inv : inv.entity;
    const lbl  = typeof inv === "object" && inv.label ? inv.label : eid;
    const s    = this.hass?.states[eid];
    const curW = s?.state !== "unavailable" ? parseFloat(s?.state) || 0 : null;
    const peak = s?.attributes?.peak_power_w || (typeof inv === "object" ? inv.peak_w : 0) || 0;
    const pct  = peak > 0 && curW !== null ? Math.min(100, (curW / peak) * 100) : 0;
    const outP = s?.attributes?.current_output_pct ?? 100;
    const col  = this._phaseColor(outP < 100 ? 80 : pct);

    return html`
      <div style="margin-bottom:14px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span style="font-weight:600;font-size:0.85rem">☀️ ${lbl}</span>
          <span style="font-size:0.78rem;color:${col};font-weight:600">${curW !== null ? this._fmt(curW) : "—"}</span>
        </div>
        <div class="ph-bar-wrap" style="height:10px"><div class="ph-bar" style="width:${pct}%;background:${col}"></div></div>
        ${outP < 100 ? html`<div style="font-size:0.72rem;color:#f97316;margin-top:4px;padding-left:8px;border-left:2px solid #f97316">⚡ Gedimmd naar ${outP.toFixed(0)}%</div>` : ""}
        <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--c-sub);margin-top:3px">
          <span>Piek: ${peak > 0 ? peak.toFixed(0) + " W" : "Aan het leren…"}</span>
          ${s?.attributes?.estimated_wp ? html`<span>~${s.attributes.estimated_wp} Wp</span>` : ""}
        </div>
      </div>`;
  }

  // ── Styles ───────────────────────────────────────────────────────────────

  static get styles() {
    return css`
      :host {
        --c-bg:      var(--card-background-color, #16161e);
        --c-text:    var(--primary-text-color,    #e2e8f0);
        --c-sub:     var(--secondary-text-color,  #64748b);
        --c-border:  rgba(255,255,255,0.07);
        --c-surf:    rgba(255,255,255,0.04);
        --c-indigo:  #6366f1;
        --c-r:       14px;
      }
      ha-card {
        background: var(--c-bg); color: var(--c-text);
        border-radius: var(--c-r); overflow: hidden;
        font-family: var(--paper-font-body1_-_font-family, ui-sans-serif, sans-serif);
        font-size: 14px; line-height: 1.4;
      }

      /* Header */
      .header { display:flex; align-items:center; justify-content:space-between; padding:12px 16px 10px; border-bottom:1px solid var(--c-border); }
      .logo   { display:flex; align-items:center; gap:7px; }
      .logo-mark { font-size:1.25rem; }
      .logo-text { font-size:1.05rem; font-weight:700; letter-spacing:0.03em; }
      .header-right { display:flex; gap:7px; align-items:center; }

      .soh-pill { border-radius:10px; padding:2px 8px; font-size:0.7rem; font-weight:600; }
      .soh-pill.ok   { background:#22c55e18; color:#4ade80; }
      .soh-pill.warn { background:#fbbf2418; color:#fbbf24; }
      .soh-pill.crit { background:#f8717118; color:#f87171; }

      .price-pill { border-radius:12px; padding:4px 11px; font-size:0.8rem; font-weight:700; border:1px solid; }
      .price-unit { font-size:0.65rem; font-weight:400; }

      .cong-pill { border-radius:10px; padding:2px 8px; font-size:0.7rem; font-weight:600; background:#f9731618; color:#fb923c; animation:pulse 1.8s ease-in-out infinite; }
      @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.55} }

      /* Tabs */
      .tabs { display:flex; overflow-x:auto; padding:6px 10px 0; gap:1px; border-bottom:1px solid var(--c-border); scrollbar-width:none; }
      .tabs::-webkit-scrollbar { display:none; }
      .tab { flex-shrink:0; background:none; border:none; color:var(--c-sub); padding:6px 9px; cursor:pointer; border-bottom:2px solid transparent; transition:all .15s; display:flex; flex-direction:column; align-items:center; gap:1px; }
      .tab-icon  { font-size:1.05rem; }
      .tab-label { font-size:0.6rem; white-space:nowrap; }
      .tab.active { color:var(--c-indigo); border-bottom-color:var(--c-indigo); }
      .tab:hover  { color:var(--c-text); }

      /* Content */
      .content { padding:14px 15px 18px; }
      .empty { text-align:center; color:var(--c-sub); padding:28px 0; font-size:0.82rem; line-height:1.7; }

      /* Flow SVG */
      .flow-svg { width:100%; height:auto; margin-bottom:12px; }

      /* Stat grid */
      .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
      .stat-tile { background:var(--c-surf); border-radius:11px; padding:10px 12px; display:flex; flex-direction:column; align-items:center; gap:2px; border:1px solid var(--c-border); }
      .tile-warn { background:#f9731608; border-color:#f9731630; }
      .tile-ok   { background:#22c55e08; border-color:#22c55e30; }
      .st-icon { font-size:1.1rem; }
      .st-val  { font-size:1.2rem; font-weight:700; }
      .st-lbl  { font-size:0.63rem; color:var(--c-sub); text-align:center; }

      .alert-bar { display:flex; gap:8px; align-items:flex-start; background:#f9731614; border:1px solid #f9731630; border-radius:10px; padding:8px 11px; font-size:0.76rem; color:#fb923c; line-height:1.5; margin-top:10px; }

      /* Devices */
      .devices-hdr   { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
      .devices-title { font-weight:600; font-size:0.88rem; }
      .mode-chip     { background:var(--c-surf); border-radius:9px; padding:2px 8px; font-size:0.68rem; color:var(--c-sub); border:1px solid var(--c-border); }
      .section-lbl   { font-size:0.68rem; color:var(--c-sub); font-weight:600; text-transform:uppercase; letter-spacing:.06em; margin-bottom:8px; }
      .device-grid   { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
      .no-running    { text-align:center; font-size:0.78rem; color:var(--c-sub); padding:6px 0 4px; }

      .dev-card { background:var(--c-surf); border-radius:11px; padding:9px; display:flex; gap:8px; border:1px solid var(--c-border); position:relative; transition:border-color .2s; }
      .dev-card.dev-active { border-color:#22c55e35; background:#22c55e08; }
      .dev-dot  { position:absolute; top:8px; right:8px; width:7px; height:7px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 2px #22c55e40; animation:pulse 2s ease-in-out infinite; }
      .dev-icon { width:34px; height:34px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-size:1.2rem; border:1px solid; flex-shrink:0; }
      .dev-body { flex:1; min-width:0; }
      .dev-name { font-size:0.76rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .dev-type { font-size:0.65rem; margin-top:2px; }
      .conf-bar { background:rgba(255,255,255,.08); border-radius:3px; height:3px; margin-top:5px; overflow:hidden; }
      .conf-fill{ height:100%; border-radius:3px; transition:width .4s; }
      .dev-conf { font-size:0.62rem; color:var(--c-sub); margin-top:2px; }

      /* Forecast */
      .forecast-row { display:flex; gap:10px; margin-bottom:14px; }
      .fc-card { flex:1; background:var(--c-surf); border-radius:11px; padding:11px; text-align:center; border:1px solid var(--c-border); }
      .fc-dim  { opacity:.75; }
      .fc-emoji{ font-size:1.5rem; }
      .fc-kwh  { font-size:1.15rem; font-weight:700; color:#fbbf24; margin:3px 0; }
      .fc-day  { font-size:0.65rem; color:var(--c-sub); }
      .chart-lbl { font-size:0.68rem; color:var(--c-sub); margin-bottom:4px; }
      .fc-chart  { display:flex; align-items:flex-end; gap:2px; height:86px; padding-bottom:16px; position:relative; }
      .fc-col    { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; position:relative; height:100%; }
      .fc-col.fc-now .fc-bar { outline:2px solid #fbbf24; outline-offset:1px; }
      .fc-bar    { width:100%; border-radius:2px 2px 0 0; min-height:2px; transition:height .3s; }
      .fc-lbl    { font-size:0.5rem; color:var(--c-sub); position:absolute; bottom:-13px; }
      .fc-tip    { display:none; position:absolute; bottom:105%; background:#1e293b; color:#e2e8f0; font-size:0.6rem; padding:3px 6px; border-radius:5px; white-space:nowrap; z-index:10; }
      .fc-col:hover .fc-tip { display:block; }

      /* Phases */
      .phase-list { display:flex; flex-direction:column; gap:10px; }
      .phase-row  { display:grid; grid-template-columns:28px 1fr 64px 44px; align-items:center; gap:8px; }
      .ph-lbl     { font-size:0.74rem; font-weight:700; }
      .ph-bar-wrap{ background:rgba(255,255,255,.07); border-radius:4px; height:8px; overflow:hidden; }
      .ph-bar     { height:100%; border-radius:4px; transition:width .4s; }
      .ph-val     { font-size:0.78rem; font-weight:600; text-align:right; }
      .ph-max     { font-size:0.66rem; color:var(--c-sub); }

      /* Prices */
      .price-chart  { display:flex; align-items:flex-end; gap:2px; height:108px; padding-bottom:22px; position:relative; }
      .pc-wrap      { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; position:relative; height:100%; cursor:default; }
      .pc-wrap.pc-now .pc-bar { outline:2px solid #fff8; outline-offset:1px; }
      .pc-bar  { width:100%; min-height:4px; border-radius:2px 2px 0 0; transition:height .3s; }
      .pc-lbl  { font-size:0.5rem; color:var(--c-sub); position:absolute; bottom:-18px; }
      .pc-tip  { display:none; position:absolute; bottom:105%; background:#1e293b; color:#e2e8f0; font-size:0.62rem; padding:3px 6px; border-radius:5px; white-space:nowrap; z-index:10; }
      .pc-wrap:hover .pc-tip { display:block; }
      .price-legend { display:flex; gap:10px; font-size:0.66rem; color:var(--c-sub); margin-top:26px; justify-content:center; flex-wrap:wrap; }

      /* EV */
      .ev-wrap   { display:flex; flex-direction:column; gap:11px; }
      .ev-status { display:flex; align-items:center; gap:12px; padding:13px; border-radius:12px; background:var(--c-surf); border:1px solid var(--c-border); }
      .ev-on     { background:#22c55e0c; border-color:#22c55e30; }
      .ev-ico    { font-size:1.7rem; }
      .ev-state  { font-size:0.88rem; font-weight:600; }
      .ev-reason { font-size:0.74rem; color:var(--c-sub); margin-top:2px; }
      .ev-price  { font-size:0.78rem; padding:0 2px; }
      .ev-tip    { font-size:0.7rem; color:var(--c-sub); line-height:1.6; border-left:2px solid var(--c-indigo); padding-left:9px; }

      /* Hints */
      .hints-wrap { display:flex; flex-direction:column; gap:8px; margin-top:10px; }
      .hint-card  { display:flex; gap:10px; background:#fbbf2410; border:1px solid #fbbf2430; border-radius:11px; padding:10px 12px; }
      .hint-icon  { font-size:1.3rem; flex-shrink:0; }
      .hint-body  { flex:1; }
      .hint-title { font-size:0.8rem; font-weight:700; color:#fbbf24; margin-bottom:3px; }
      .hint-msg   { font-size:0.72rem; color:var(--c-text); line-height:1.5; }
      .hint-conf  { font-size:0.65rem; color:var(--c-sub); margin-top:4px; }
      .alert-bar.cong { margin-top:0; }
    `;
  }
}

customElements.define("cloudems-card", CloudEMSCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "cloudems-card",
  name:        "CloudEMS Dashboard",
  description: "Energiestroomdiagram · NILM apparaatkaarten · PV prognose · Batterijgezondheid · EPEX · EV · Fasen (v1.10.1)",
  preview:     true,
});
