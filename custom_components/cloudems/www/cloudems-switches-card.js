// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. Unauthorized copying, redistribution, or commercial
// use of this file is strictly prohibited. See LICENSE for full terms.

/**
 * CloudEMS Switches Card
 * Goedkope Uren Schakelaars + Slimme Uitstelmodus
 *
 * Install via HACS as a Lovelace resource, then use:
 *   type: custom:cloudems-switches-card
 *
 * Optional config:
 *   title: "Mijn Schakelaars"          # override card title
 *   show_actions: true                  # show recent actions (default: true)
 *   show_cancel_button: true            # show cancel-all-delays button (default: true)
 */

const CARD_VERSION = "1.0.1";

// ── Styles ────────────────────────────────────────────────────────────────────
const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@600;700;800&display=swap');

  :host {
    --cem-bg:        #1a1a1a;
    --cem-surface:   #222222;
    --cem-border:    rgba(255,255,255,0.07);
    --cem-green:     #00c853;
    --cem-green-dim: rgba(0,200,83,0.12);
    --cem-amber:     #ffb300;
    --cem-amber-dim: rgba(255,179,0,0.12);
    --cem-red:       #ef5350;
    --cem-muted:     #6b7280;
    --cem-text:      #e8e8e8;
    --cem-subtext:   #9ca3af;
    --cem-mono:      'JetBrains Mono', monospace;
    --cem-display:   'Syne', sans-serif;
    --cem-radius:    14px;
    --cem-radius-sm: 8px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: var(--cem-bg);
    border-radius: var(--cem-radius);
    border: 1px solid var(--cem-border);
    overflow: hidden;
    font-family: var(--cem-mono);
    transition: border-color .25s, box-shadow .25s, transform .2s;
  }
  .card:hover {
    border-color: rgba(0,200,83,0.35);
    box-shadow: 0 6px 28px rgba(0,0,0,.5), 0 0 20px rgba(0,200,83,.08);
    transform: translateY(-1px);
  }

  /* ── Header ── */
  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px 12px;
    border-bottom: 1px solid var(--cem-border);
    background: linear-gradient(135deg, rgba(0,200,83,.06) 0%, transparent 60%);
  }
  .card-header .icon {
    font-size: 18px;
    line-height: 1;
    filter: drop-shadow(0 0 6px rgba(0,200,83,.5));
  }
  .card-header h1 {
    font-family: var(--cem-display);
    font-size: 13px;
    font-weight: 800;
    letter-spacing: .04em;
    color: var(--cem-text);
    flex: 1;
  }
  .card-header .badge {
    font-family: var(--cem-mono);
    font-size: 10px;
    font-weight: 600;
    background: var(--cem-green-dim);
    color: var(--cem-green);
    border: 1px solid rgba(0,200,83,.25);
    border-radius: 20px;
    padding: 2px 9px;
    letter-spacing: .05em;
  }

  /* ── Sections ── */
  .section {
    padding: 14px 18px;
  }
  .section + .section {
    border-top: 1px solid var(--cem-border);
  }
  .section-title {
    font-family: var(--cem-display);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--cem-muted);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .section-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--cem-border);
  }

  /* ── Status pill ── */
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    margin-bottom: 10px;
    letter-spacing: .03em;
  }
  .status-pill.ok    { background: var(--cem-green-dim); color: var(--cem-green); border: 1px solid rgba(0,200,83,.2); }
  .status-pill.warn  { background: var(--cem-amber-dim); color: var(--cem-amber); border: 1px solid rgba(255,179,0,.25); }
  .status-pill.empty { background: rgba(255,255,255,.04); color: var(--cem-muted); border: 1px solid var(--cem-border); }
  .status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; display: inline-block; }

  /* ── Table ── */
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11.5px;
  }
  .data-table th {
    font-family: var(--cem-display);
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: var(--cem-muted);
    padding: 6px 8px;
    text-align: left;
    background: rgba(255,255,255,.025);
    border-bottom: 1px solid var(--cem-border);
    white-space: nowrap;
  }
  .data-table th:first-child { border-radius: var(--cem-radius-sm) 0 0 0; }
  .data-table th:last-child  { border-radius: 0 var(--cem-radius-sm) 0 0; }
  .data-table td {
    padding: 7px 8px;
    color: var(--cem-subtext);
    border-bottom: 1px solid rgba(255,255,255,.04);
    vertical-align: middle;
  }
  .data-table tr:last-child td { border-bottom: none; }
  .data-table tr:hover td { background: rgba(255,255,255,.02); }

  /* ── Cell types ── */
  .chip {
    font-family: var(--cem-mono);
    font-size: 10.5px;
    background: rgba(120,180,255,.08);
    color: #82b4ff;
    border-radius: 5px;
    padding: 2px 6px;
    border: 1px solid rgba(120,180,255,.15);
    white-space: nowrap;
  }
  .val {
    font-family: var(--cem-mono);
    font-weight: 600;
    color: var(--cem-text);
  }
  .saving-pos { color: var(--cem-green); font-weight: 600; }
  .saving-neg { color: var(--cem-muted); }

  .status-active   { color: var(--cem-green); font-weight: 600; }
  .status-inactive { color: var(--cem-muted); }
  .status-idle     { color: var(--cem-muted); }
  .status-intercepted { color: var(--cem-amber); font-weight: 600; }
  .status-detected    { color: #60a5fa; font-weight: 600; }
  .status-deadline    { color: var(--cem-red); font-weight: 600; }

  .mode-badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 600;
    white-space: nowrap;
  }
  .mode-block { background: rgba(255,179,0,.1); color: var(--cem-amber); border: 1px solid rgba(255,179,0,.2); }
  .mode-price { background: rgba(96,165,250,.1); color: #60a5fa; border: 1px solid rgba(96,165,250,.2); }

  .deadline-inf  { color: var(--cem-muted); }
  .deadline-val  { font-family: var(--cem-mono); font-size: 11px; color: var(--cem-subtext); }
  .deadline-near { color: var(--cem-amber); font-weight: 600; }

  /* ── Empty state ── */
  .empty-state {
    text-align: center;
    padding: 22px 16px;
    color: var(--cem-muted);
    font-size: 11.5px;
    line-height: 1.6;
  }
  .empty-state .empty-icon { font-size: 28px; display: block; margin-bottom: 8px; opacity: .5; }
  .empty-state a { color: var(--cem-green); text-decoration: none; }
  .empty-state a:hover { text-decoration: underline; }

  /* ── Recent actions ── */
  .actions-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .action-item {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    font-size: 11px;
    color: var(--cem-subtext);
    padding: 5px 0;
    border-bottom: 1px solid rgba(255,255,255,.03);
    line-height: 1.4;
  }
  .action-item:last-child { border-bottom: none; }
  .action-item::before { content: '›'; color: var(--cem-green); font-weight: 700; flex-shrink: 0; margin-top: 1px; }

  /* ── Cancel button ── */
  .cancel-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: 100%;
    margin-top: 12px;
    padding: 9px 16px;
    background: rgba(239,83,80,.08);
    border: 1px solid rgba(239,83,80,.25);
    border-radius: var(--cem-radius-sm);
    color: #ef9a9a;
    font-family: var(--cem-display);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background .2s, border-color .2s, transform .15s;
  }
  .cancel-btn:hover {
    background: rgba(239,83,80,.15);
    border-color: rgba(239,83,80,.45);
    transform: translateY(-1px);
  }
  .cancel-btn:active { transform: scale(.98); }

  /* ── Loading / error ── */
  .loading {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 28px;
    gap: 10px;
    color: var(--cem-muted);
    font-size: 12px;
  }
  .spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(0,200,83,.15);
    border-top-color: var(--cem-green);
    border-radius: 50%;
    animation: spin .8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Fade in rows ── */
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .data-table tbody tr {
    animation: fadeUp .25s ease both;
  }
  .data-table tbody tr:nth-child(1) { animation-delay: .04s; }
  .data-table tbody tr:nth-child(2) { animation-delay: .08s; }
  .data-table tbody tr:nth-child(3) { animation-delay: .12s; }
  .data-table tbody tr:nth-child(4) { animation-delay: .16s; }
  .data-table tbody tr:nth-child(5) { animation-delay: .20s; }
`;

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? "—")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function fmtPrice(val) {
  if (val == null || val === "" || isNaN(parseFloat(val))) return "—";
  return "€" + parseFloat(val).toFixed(4);
}

function fmtSaving(diff) {
  if (diff == null) return `<span class="saving-neg">—</span>`;
  if (diff > 0) return `<span class="saving-pos">💚 €${parseFloat(diff).toFixed(4)}/kWh</span>`;
  return `<span class="saving-neg">➖</span>`;
}

function statusHtml(active) {
  return active
    ? `<span class="status-active">🟢 actief</span>`
    : `<span class="status-inactive">⏸ inactief</span>`;
}

function delayStateHtml(ds) {
  const map = {
    intercepted:     ["⏳", "status-intercepted", "uitgesteld"],
    detected:        ["🔍", "status-detected",     "gedetecteerd"],
    deadline_forced: ["⏰", "status-deadline",     "deadline"],
    idle:            ["✅", "status-idle",          "idle"],
  };
  const [icon, cls, label] = map[ds] ?? ["🚫", "status-inactive", ds];
  return `<span class="${cls}">${icon} ${esc(label)}</span>`;
}

function modeBadge(mode) {
  return mode === "cheapest_block"
    ? `<span class="mode-badge mode-block">🏷️ blok</span>`
    : `<span class="mode-badge mode-price">💶 prijs</span>`;
}

function deadlineHtml(dl_ts, mxh) {
  if (dl_ts) {
    const minLeft = Math.round((parseInt(dl_ts) - Date.now() / 1000) / 60);
    const cls = minLeft < 30 ? "deadline-near" : "deadline-val";
    return `<span class="${cls}">${minLeft} min</span>`;
  }
  if (mxh === 0) return `<span class="deadline-inf">∞</span>`;
  return `<span class="deadline-val">${mxh}h max</span>`;
}

// ── Card class ────────────────────────────────────────────────────────────────
class CloudemsSwithcesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._prevJson = "";
  }

  setConfig(config) {
    this._config = {
      title: config.title ?? "Goedkope Uren Schakelaars",
      show_actions: config.show_actions !== false,
      show_cancel_button: config.show_cancel_button !== false,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render if relevant sensor changed
    const sensors = [
      hass.states["sensor.cloudems_goedkope_uren_schakelaars"],
      hass.states["sensor.cloudems_energy_epex_today"],
    ];
    const json = JSON.stringify(sensors.map(s => s?.last_changed));
    if (json !== this._prevJson) {
      this._prevJson = json;
      this._render();
    }
  }

  _render() {
    const shadow = this.shadowRoot;
    if (!shadow) return;

    const hass = this._hass;
    const cfg  = this._config;

    // ── Gather data ──
    const switchSensor  = hass?.states["sensor.cloudems_goedkope_uren_schakelaars"];
    const priceSensor   = hass?.states["sensor.cloudems_energy_epex_today"];

    const switches      = switchSensor?.attributes?.switches      ?? [];
    const lastActions   = switchSensor?.attributes?.last_actions  ?? [];
    const smartDelay    = switchSensor?.attributes?.smart_delay   ?? {};
    const count         = parseInt(switchSensor?.state ?? "0", 10) || 0;
    const avgToday      = parseFloat(priceSensor?.attributes?.avg_today ?? 0);
    const sdSwitches    = smartDelay?.switches ?? [];
    const pending       = smartDelay?.pending_count ?? 0;

    // ── Section 1: Goedkope Uren Schakelaars ──
    let switchesSection;
    if (!hass) {
      switchesSection = `<div class="loading"><div class="spinner"></div> Verbinden…</div>`;
    } else if (count === 0 || switches.length === 0) {
      switchesSection = `
        <div class="empty-state">
          <span class="empty-icon">🔌</span>
          Geen schakelaars geconfigureerd.<br>
          Voeg ze toe via <a>Instellingen → CloudEMS → Goedkope uren schakelaars</a>.
        </div>`;
    } else {
      const rows = switches.map(sw => {
        const blokPrijs = sw.avg_price != null ? parseFloat(sw.avg_price) : null;
        const diff      = blokPrijs != null ? +(avgToday - blokPrijs).toFixed(4) : null;
        const name      = String(sw.entity_id ?? "").split(".")[1] ?? sw.entity_id;
        return `
          <tr>
            <td><span class="chip">${esc(name)}</span></td>
            <td class="val">${esc(sw.window_hours)}u</td>
            <td>${statusHtml(sw.active)}</td>
            <td class="val">${fmtPrice(blokPrijs)}</td>
            <td class="val">${fmtPrice(avgToday)}</td>
            <td>${fmtSaving(diff)}</td>
          </tr>`;
      }).join("");

      const actionsHtml = (cfg.show_actions && lastActions.length > 0) ? `
        <div class="section-title" style="margin-top:12px">Recente acties</div>
        <div class="actions-list">
          ${lastActions.slice(0, 5).map(a => `<div class="action-item">${esc(a)}</div>`).join("")}
        </div>` : "";

      switchesSection = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Schakelaar</th><th>Venster</th><th>Status</th>
              <th>Blok prijs</th><th>Gem. dag</th><th>Besparing</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        ${actionsHtml}`;
    }

    // ── Section 2: Slimme Uitstelmodus ──
    let delaySection;
    if (!hass) {
      delaySection = `<div class="loading"><div class="spinner"></div> Verbinden…</div>`;
    } else if (sdSwitches.length === 0) {
      delaySection = `
        <div class="empty-state">
          <span class="empty-icon">⏳</span>
          Geen schakelaars geconfigureerd.<br>
          Voeg ze toe via <a>Instellingen → CloudEMS → Slimme Uitstelmodus</a>.
        </div>`;
    } else {
      const pendingPill = pending > 0
        ? `<div class="status-pill warn"><span class="status-dot"></span>⏳ ${pending} schakelaar(s) wachten op goedkoop moment</div>`
        : `<div class="status-pill ok"><span class="status-dot"></span>✅ Geen uitgestelde schakelaars</div>`;

      const rows = sdSwitches.map(sw => {
        const ds    = sw.delay_state ?? "idle";
        const lbl   = sw.label ?? sw.entity_id ?? "—";
        const tgt   = sw.target_hour != null ? String(sw.target_hour).padStart(2,"0") + ":00" : "—";
        const wmin  = sw.waiting_min != null ? `${parseInt(sw.waiting_min)} min` : "—";
        const mxh   = parseInt(sw.max_wait_h ?? 0);
        return `
          <tr>
            <td class="val">${esc(lbl)}</td>
            <td>${delayStateHtml(ds)}</td>
            <td>${modeBadge(sw.wait_mode)}</td>
            <td class="val">${esc(tgt)}</td>
            <td class="val">${esc(wmin)}</td>
            <td>${deadlineHtml(sw.deadline_ts, mxh)}</td>
          </tr>`;
      }).join("");

      const cancelBtn = (cfg.show_cancel_button && pending > 0) ? `
        <button class="cancel-btn" @click="cancelDelay">
          ✕ Annuleer alle uitgestelde schakelaars
        </button>` : "";

      delaySection = `
        ${pendingPill}
        <table class="data-table">
          <thead>
            <tr>
              <th>Apparaat</th><th>Status</th><th>Modus</th>
              <th>Wacht op</th><th>Wachtend</th><th>Deadline</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        ${cancelBtn}`;
    }

    // ── Header badge ──
    const badgeHtml = count > 0
      ? `<span class="badge">${count} actief</span>`
      : "";

    // ── Full card HTML ──
    shadow.innerHTML = `
      <style>${STYLES}</style>
      <div class="card">
        <div class="card-header">
          <span class="icon">⚡</span>
          <h1>${esc(cfg.title)}</h1>
          ${badgeHtml}
        </div>

        <div class="section">
          <div class="section-title">⏱️ Goedkope Uren Schakelaars</div>
          ${switchesSection}
        </div>

        <div class="section">
          <div class="section-title">⏳ Slimme Uitstelmodus</div>
          ${delaySection}
        </div>
      </div>
    `;

    // ── Wire up cancel button ──
    const btn = shadow.querySelector(".cancel-btn");
    if (btn) {
      btn.addEventListener("click", () => this._cancelDelay());
    }
  }

  _cancelDelay() {
    if (!this._hass) return;
    this._hass.callService("cloudems", "smart_delay_cancel", {});
  }

  // ── HACS / HA boilerplate ──
  static getConfigElement() {
    return document.createElement("cloudems-switches-card-editor");
  }

  static getStubConfig() {
    return {
      title: "Goedkope Uren Schakelaars",
      show_actions: true,
      show_cancel_button: true,
    };
  }

  getCardSize() { return 5; }
}

// ── Simple visual config editor ───────────────────────────────────────────────
class CloudemsSwithcesCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; }
  set hass(hass)    { this._hass = hass; }

  connectedCallback() {
    if (this._rendered) return;
    this._rendered = true;
    this.innerHTML = `
      <style>
        .editor { padding: 8px 0; display: flex; flex-direction: column; gap: 10px; }
        label { font-size: 13px; color: var(--primary-text-color); display: flex; flex-direction: column; gap: 4px; }
        input[type=text] {
          background: var(--card-background-color, #222);
          border: 1px solid var(--divider-color, rgba(255,255,255,.1));
          border-radius: 6px; padding: 6px 10px;
          color: var(--primary-text-color); font-size: 13px;
        }
        .row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
      </style>
      <div class="editor">
        <label>Kaart titel
          <input type="text" id="title" value="${this._config?.title ?? "Goedkope Uren Schakelaars"}">
        </label>
        <div class="row">
          <input type="checkbox" id="show_actions" ${this._config?.show_actions !== false ? "checked" : ""}>
          <span>Toon recente acties</span>
        </div>
        <div class="row">
          <input type="checkbox" id="show_cancel_button" ${this._config?.show_cancel_button !== false ? "checked" : ""}>
          <span>Toon annuleer-knop</span>
        </div>
      </div>
    `;
    this.querySelector("#title").addEventListener("input", () => this._fire());
    this.querySelector("#show_actions").addEventListener("change", () => this._fire());
    this.querySelector("#show_cancel_button").addEventListener("change", () => this._fire());
  }

  _fire() {
    const detail = {
      ...this._config,
      title: this.querySelector("#title").value,
      show_actions: this.querySelector("#show_actions").checked,
      show_cancel_button: this.querySelector("#show_cancel_button").checked,
    };
    this.dispatchEvent(new CustomEvent("config-changed", { detail, bubbles: true, composed: true }));
  }
}

// ── Register ──────────────────────────────────────────────────────────────────
customElements.define("cloudems-switches-card", CloudemsSwithcesCard);
customElements.define("cloudems-switches-card-editor", CloudemsSwithcesCardEditor);

window.customCards = window.customCards ?? [];
window.customCards.push({
  type:        "cloudems-switches-card",
  name:        "CloudEMS Switches Card",
  description: "Goedkope Uren Schakelaars & Slimme Uitstelmodus in één kaart",
  preview:     true,
  documentationURL: "https://github.com/your-repo/cloudems",
});

console.info(
  `%c CLOUDEMS-SWITCHES-CARD %c v${CARD_VERSION} `,
  "background:#00c853;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px",
  "background:#1a1a1a;color:#00c853;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0"
);
