/**
 * CloudEMS Battery Card  v1.0.0
 * Live status · SoH · Besparingen · Beslissing · Providers
 *
 *   type: custom:cloudems-battery-card
 *
 * Optional:
 *   title: "Mijn Batterij"
 *   show_savings: true       (default true)
 *   show_decision: true      (default true)
 *   show_providers: true     (default true)
 */

const BATT_VERSION = "1.0.0";

// ── Design: deep-space indigo with electric cyan accents ──────────────────────
const BATT_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

  :host {
    --b-bg:         #161b22;
    --b-surface:    #1c2333;
    --b-surface2:   #212840;
    --b-border:     rgba(255,255,255,0.07);
    --b-cyan:       #22d3ee;
    --b-cyan-dim:   rgba(34,211,238,0.1);
    --b-blue:       #60a5fa;
    --b-green:      #34d399;
    --b-amber:      #fbbf24;
    --b-red:        #f87171;
    --b-text:       #e2e8f0;
    --b-muted:      #64748b;
    --b-subtext:    #94a3b8;
    --b-mono:       'JetBrains Mono', monospace;
    --b-sans:       'Outfit', sans-serif;
    --b-r:          14px;
    --b-rs:         8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: var(--b-bg);
    border-radius: var(--b-r);
    border: 1px solid var(--b-border);
    overflow: hidden;
    font-family: var(--b-sans);
    transition: border-color .3s, box-shadow .3s, transform .2s;
  }
  .card:hover {
    border-color: rgba(34,211,238,.3);
    box-shadow: 0 8px 32px rgba(0,0,0,.6), 0 0 24px rgba(34,211,238,.06);
    transform: translateY(-2px);
  }

  /* ── Header ── */
  .hdr {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 12px;
    padding: 16px 18px 14px;
    background: linear-gradient(135deg, var(--b-cyan-dim) 0%, transparent 55%);
    border-bottom: 1px solid var(--b-border);
    position: relative;
    overflow: hidden;
  }
  .hdr::before {
    content: '';
    position: absolute;
    right: -20px; top: -20px;
    width: 100px; height: 100px;
    background: radial-gradient(circle, rgba(34,211,238,.06) 0%, transparent 70%);
    pointer-events: none;
  }
  .hdr-icon { font-size: 22px; line-height: 1; }
  .hdr-title {
    font-size: 14px;
    font-weight: 800;
    color: var(--b-text);
    letter-spacing: .02em;
  }
  .hdr-sub { font-size: 11px; font-weight: 500; color: var(--b-muted); margin-top: 2px; }
  .hdr-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }

  /* ── SOC Ring ── */
  .soc-ring-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 18px 18px 12px;
    gap: 12px;
    border-bottom: 1px solid var(--b-border);
  }
  .soc-ring {
    position: relative;
    width: 110px;
    height: 110px;
  }
  .soc-ring svg { width: 110px; height: 110px; transform: rotate(-90deg); }
  .soc-ring-track { fill: none; stroke: rgba(255,255,255,.06); stroke-width: 8; }
  .soc-ring-fill  { fill: none; stroke-width: 8; stroke-linecap: round; transition: stroke-dashoffset .8s ease, stroke .4s; }
  .soc-ring-text {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
  }
  .soc-pct {
    font-family: var(--b-mono);
    font-size: 22px;
    font-weight: 600;
    color: var(--b-text);
    line-height: 1;
  }
  .soc-label { font-size: 9.5px; font-weight: 600; color: var(--b-muted); text-transform: uppercase; letter-spacing: .1em; }

  .soc-stats {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
    width: 100%;
  }
  .stat-box {
    background: var(--b-surface);
    border: 1px solid var(--b-border);
    border-radius: var(--b-rs);
    padding: 8px 10px;
    text-align: center;
  }
  .stat-box .sv { font-family: var(--b-mono); font-size: 13px; font-weight: 600; color: var(--b-text); }
  .stat-box .sk { font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: .09em; color: var(--b-muted); margin-top: 3px; }

  /* ── Action banner ── */
  .action-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 18px;
    font-size: 12px;
    font-weight: 600;
    border-bottom: 1px solid var(--b-border);
    letter-spacing: .02em;
  }
  .action-banner .icon { font-size: 16px; }
  .action-banner .label { flex: 1; }
  .action-banner .reason { font-size: 10.5px; font-weight: 500; color: var(--b-muted); }
  .action-charge   { background: rgba(34,211,238,.08);  color: var(--b-cyan);  border-left: 3px solid var(--b-cyan); }
  .action-discharge{ background: rgba(251,191,36,.08);  color: var(--b-amber); border-left: 3px solid var(--b-amber); }
  .action-idle     { background: rgba(100,116,139,.06); color: var(--b-muted); border-left: 3px solid rgba(100,116,139,.3); }

  /* ── Sections ── */
  .section { padding: 12px 18px; border-bottom: 1px solid var(--b-border); }
  .section:last-child { border-bottom: none; }
  .sec-title {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .12em;
    color: var(--b-muted);
    margin-bottom: 9px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sec-title::after { content: ''; flex: 1; height: 1px; background: var(--b-border); }

  /* ── Battery rows ── */
  .batt-row {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
    font-size: 12px;
    animation: fadeUp .25s ease both;
  }
  .batt-row:last-child { border-bottom: none; }
  .batt-name { font-weight: 600; color: var(--b-text); }
  .batt-power { font-family: var(--b-mono); font-size: 11px; color: var(--b-subtext); }
  .batt-action-lbl { font-size: 10.5px; font-weight: 600; }
  .act-charge   { color: var(--b-cyan); }
  .act-discharge{ color: var(--b-amber); }
  .act-idle     { color: var(--b-muted); }

  /* ── SOH bar ── */
  .soh-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .soh-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .soh-val { font-family: var(--b-mono); font-size: 15px; font-weight: 600; }
  .soh-meta { font-size: 11px; color: var(--b-subtext); }
  .soh-bar-track {
    height: 6px;
    background: rgba(255,255,255,.06);
    border-radius: 3px;
    overflow: hidden;
  }
  .soh-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width .8s ease;
  }
  .soh-details {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-top: 4px;
  }
  .soh-detail { font-size: 11px; color: var(--b-subtext); }
  .soh-detail span { font-family: var(--b-mono); color: var(--b-text); font-weight: 600; }

  /* ── Savings grid ── */
  .savings-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .sav-box {
    background: var(--b-surface);
    border: 1px solid var(--b-border);
    border-radius: var(--b-rs);
    padding: 9px 12px;
  }
  .sav-box.total {
    grid-column: 1 / -1;
    background: linear-gradient(135deg, rgba(52,211,153,.08), rgba(34,211,238,.06));
    border-color: rgba(52,211,153,.2);
  }
  .sav-val { font-family: var(--b-mono); font-size: 14px; font-weight: 600; color: var(--b-green); }
  .sav-box.total .sav-val { font-size: 18px; }
  .sav-key { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--b-muted); margin-top: 3px; }
  .sav-neg { color: var(--b-red); }
  .sav-row { font-size: 11px; color: var(--b-subtext); margin-top: 5px; font-family: var(--b-mono); }

  /* ── Decision ── */
  .decision-row {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
    font-size: 11.5px;
  }
  .decision-row:last-child { border-bottom: none; }
  .dk { color: var(--b-muted); font-size: 10.5px; }
  .dv { font-family: var(--b-mono); color: var(--b-text); font-weight: 600; text-align: right; }
  .conf-bar {
    width: 48px; height: 4px;
    background: rgba(255,255,255,.07);
    border-radius: 2px;
    overflow: hidden;
  }
  .conf-fill { height: 100%; border-radius: 2px; background: var(--b-cyan); transition: width .6s ease; }
  .chip-src {
    font-family: var(--b-mono);
    font-size: 10px;
    background: rgba(96,165,250,.1);
    color: var(--b-blue);
    border: 1px solid rgba(96,165,250,.2);
    border-radius: 4px;
    padding: 2px 6px;
  }

  /* ── Providers ── */
  .provider-row {
    display: grid;
    grid-template-columns: auto 1fr auto auto auto;
    align-items: center;
    gap: 8px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
    font-size: 12px;
    animation: fadeUp .25s ease both;
  }
  .provider-row:last-child { border-bottom: none; }
  .prov-name { font-weight: 600; color: var(--b-text); }
  .prov-status-ok  { color: var(--b-green); }
  .prov-status-warn{ color: var(--b-amber); }
  .prov-status-err { color: var(--b-red); }
  .prov-meta {
    font-size: 10px;
    color: var(--b-muted);
    text-align: right;
    line-height: 1.5;
    white-space: nowrap;
  }
  .prov-meta-stale { color: var(--b-amber); }
  .mode-pill {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 4px;
    background: var(--b-cyan-dim);
    color: var(--b-cyan);
    border: 1px solid rgba(34,211,238,.2);
    white-space: nowrap;
  }

  /* ── Module off banner ── */
  .module-off {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: rgba(251,191,36,.08);
    border: 1px solid rgba(251,191,36,.3);
    border-radius: var(--b-rs);
    margin: 12px;
    font-size: 12px;
    color: var(--b-amber);
    font-weight: 500;
  }

  /* ── Empty ── */
  .empty { text-align: center; padding: 20px 16px; color: var(--b-muted); font-size: 11.5px; line-height: 1.7; }
  .empty-icon { font-size: 26px; display: block; margin-bottom: 6px; opacity: .45; }

  /* ── Badge ── */
  .badge {
    font-size: 10px; font-weight: 700;
    padding: 2px 8px; border-radius: 20px;
    letter-spacing: .05em;
  }
  .badge-charge    { background: var(--b-cyan-dim); color: var(--b-cyan); border: 1px solid rgba(34,211,238,.25); }
  .badge-discharge { background: rgba(251,191,36,.1); color: var(--b-amber); border: 1px solid rgba(251,191,36,.25); }
  .badge-idle      { background: rgba(100,116,139,.1); color: var(--b-muted); border: 1px solid rgba(100,116,139,.2); }

  .spinner { width: 14px; height: 14px; border: 2px solid rgba(34,211,238,.15); border-top-color: var(--b-cyan); border-radius: 50%; animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin   { to { transform: rotate(360deg); } }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
`;

// ── helpers ───────────────────────────────────────────────────────────────────
const esc = s => String(s ?? "—").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const fmt2 = v => v != null && !isNaN(parseFloat(v)) ? "€" + parseFloat(v).toFixed(2) : "—";

function socColor(pct) {
  if (pct >= 60) return "#34d399";
  if (pct >= 20) return "#fbbf24";
  return "#f87171";
}

function sohColor(pct) {
  if (pct >= 80) return "#34d399";
  if (pct >= 60) return "#fbbf24";
  return "#f87171";
}

function actionInfo(action) {
  if (!action || action === "idle") return { icon: "💤", label: "Idle", cls: "action-idle",    badgeCls: "badge-idle",      prio: "Standaard" };
  if (action.includes("charge"))   return { icon: "⚡", label: "Laden",   cls: "action-charge",   badgeCls: "badge-charge",    prio: "Laden" };
  return                                  { icon: "🔋", label: "Ontladen", cls: "action-discharge", badgeCls: "badge-discharge", prio: "Ontladen" };
}

function battActionLbl(power_w) {
  if (power_w == null) return `<span class="act-idle">— idle</span>`;
  if (power_w > 50)    return `<span class="act-charge">⚡ Laden</span>`;
  if (power_w < -50)   return `<span class="act-discharge">🔋 Ontladen</span>`;
  return `<span class="act-idle">💤 Idle</span>`;
}

const PRIO_LABELS = {1:"🛡️ Veiligheid",2:"📊 Tariefgroep",3:"💶 EPEX",4:"☀️ PV forecast",5:"💤 Standaard"};
const MODE_MAP = {
  home_optimization:"🏠 Thuisopt.", self_consumption:"☀️ Zelfverbruik",
  powerplay:"⚡ Powerplay", manual_control:"🔧 Handmatig",
  thuisoptimalisatie:"🏠 Thuisopt.", zelfverbruik:"☀️ Zelfverbruik",
  powerplay_nl:"⚡ Powerplay", handmatig:"🔧 Handmatig",
};

// ── Card ──────────────────────────────────────────────────────────────────────
class CloudemsBatteryCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); this._prevJson = ""; }

  setConfig(cfg) {
    this._cfg = {
      title: cfg.title ?? "Batterij",
      show_savings:   cfg.show_savings   !== false,
      show_decision:  cfg.show_decision  !== false,
      show_providers: cfg.show_providers !== false,
      ...cfg,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const keys = [
      "sensor.cloudems_batterij_epex_schema",
      "sensor.cloudems_batterij_soh",
      "sensor.cloudems_battery_besparingen",
      "switch.cloudems_module_batterij",
    ];
    const json = JSON.stringify(keys.map(k => hass.states[k]?.last_changed));
    if (json !== this._prevJson) { this._prevJson = json; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    if (!sh) return;
    const hass = this._hass;
    const cfg  = this._cfg ?? {};

    if (!hass) {
      sh.innerHTML = `<style>${BATT_STYLES}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
      return;
    }

    const schema    = hass.states["sensor.cloudems_batterij_epex_schema"];
    const sohSensor = hass.states["sensor.cloudems_batterij_soh"];
    const savSensor = hass.states["sensor.cloudems_battery_besparingen"];
    const modSwitch = hass.states["switch.cloudems_module_batterij"];

    const attrs    = schema?.attributes ?? {};
    const batteries= attrs.batteries ?? [];
    const soc      = attrs.soc_pct;
    const action   = schema?.state ?? "idle";
    const reason   = attrs.reason ?? "—";
    const bd       = attrs.battery_decision ?? {};
    const bp       = attrs.battery_providers ?? {};
    const zpRaw    = attrs.zonneplan;
    const providers= bp.providers ?? [];

    const sohPct   = sohSensor?.attributes?.soh_pct;
    const cycles   = sohSensor?.attributes?.total_cycles;
    const capKwh   = sohSensor?.attributes?.usable_kwh;

    const savTotal = savSensor?.attributes?.total_savings_eur;
    const savEV    = savSensor?.attributes?.eigenverbruik_savings_eur;
    const savArb   = savSensor?.attributes?.arbitrage_savings_eur;
    const savPV    = savSensor?.attributes?.pv_selfconsumption_eur;
    const savLoss  = savSensor?.attributes?.saldering_loss_eur;
    const sessDay  = savSensor?.attributes?.sessions_today ?? 0;
    const kwhDay   = savSensor?.attributes?.kwh_charged_today ?? 0;

    const ai       = actionInfo(action);
    const socNum   = soc != null ? parseFloat(soc) : null;
    const socColor_= socNum != null ? socColor(socNum) : "#64748b";
    const circumference = 2 * Math.PI * 46; // radius 46
    const dashOffset    = socNum != null ? circumference * (1 - socNum / 100) : circumference;

    // ── Module off ──
    const moduleOffHtml = (modSwitch?.state === "off")
      ? `<div class="module-off">⚠️ Batterij module staat uit — schakel in via Configuratie.</div>`
      : "";

    // ── Header subtitle ──
    const totalBatts = batteries.length || 1;
    const subTitle   = `${totalBatts} batterij${totalBatts !== 1 ? "en" : ""} · ${ai.label}`;

    // ── Action banner ──
    const actionBanner = `
      <div class="action-banner ${ai.cls}">
        <span class="icon">${ai.icon}</span>
        <span class="label">${ai.label}</span>
        <span class="reason">${esc(reason)}</span>
      </div>`;

    // ── SOC ring + stats ──
    const battRows = batteries.length > 0 ? batteries.map((b,i) => {
      const s = b.soc_pct; const p = b.power_w;
      const pStr = p != null ? `${Math.abs(parseInt(p))} W` : "—";
      return `<div class="batt-row" style="animation-delay:${i * .06}s">
        <span class="batt-name">${esc(b.label ?? "Batterij")}</span>
        <span class="batt-power">${pStr}</span>
        ${battActionLbl(p)}
        <span style="font-family:var(--b-mono);font-size:12px;color:${s!=null?socColor(parseFloat(s)):"#64748b"};font-weight:600">${s != null ? Math.round(s) + "%" : "—"}</span>
      </div>`;
    }).join("") : `<div class="batt-row">
      <span class="batt-name">Batterij 1</span>
      <span></span>
      ${battActionLbl(null)}
      <span style="font-family:var(--b-mono);font-size:12px;color:${socColor_};font-weight:600">${socNum != null ? Math.round(socNum) + "%" : "—"}</span>
    </div>`;

    const battSection = `
      <div class="section">
        <div class="sec-title">🔋 Live status</div>
        ${battRows}
      </div>`;

    // ── SOH ──
    const sohHtml = sohPct != null ? (() => {
      const s = parseFloat(sohPct);
      const icon = s >= 80 ? "✅" : (s >= 60 ? "🟡" : "🔴");
      const col  = sohColor(s);
      return `
        <div class="soh-row">
          <div class="soh-top">
            <span class="soh-val" style="color:${col}">${icon} ${s.toFixed(1)}%</span>
            <span class="soh-meta">Gezondheid</span>
          </div>
          <div class="soh-bar-track"><div class="soh-bar-fill" style="width:${s}%;background:${col}"></div></div>
          <div class="soh-details">
            <div class="soh-detail">Capaciteit: <span>${capKwh != null ? parseFloat(capKwh).toFixed(1) + " kWh" : "—"}</span></div>
            <div class="soh-detail">Cycli: <span>${cycles != null ? cycles : "—"}</span></div>
          </div>
        </div>`;
    })() : `<div style="font-size:11.5px;color:var(--b-muted)">⏳ SoH wordt berekend na eerste laadcyclus.</div>`;

    // ── Savings ──
    const savingsHtml = cfg.show_savings ? `
      <div class="section">
        <div class="sec-title">💰 Besparingen</div>
        ${savTotal != null ? `
          <div class="savings-grid">
            <div class="sav-box total">
              <div class="sav-val">€ ${parseFloat(savTotal).toFixed(2)}</div>
              <div class="sav-key">Totaal bespaard</div>
              <div class="sav-row">${sessDay} cycli · ${parseFloat(kwhDay).toFixed(1)} kWh vandaag</div>
            </div>
            <div class="sav-box"><div class="sav-val">${fmt2(savEV)}</div><div class="sav-key">Eigenverbruik</div></div>
            <div class="sav-box"><div class="sav-val">${fmt2(savArb)}</div><div class="sav-key">Arbitrage</div></div>
            <div class="sav-box"><div class="sav-val">${fmt2(savPV)}</div><div class="sav-key">PV zelfconsumptie</div></div>
            <div class="sav-box"><div class="sav-val sav-neg">-${fmt2(savLoss)}</div><div class="sav-key">Saldering-verlies</div></div>
          </div>` : `<div class="empty" style="padding:14px 0">⏳ Berekening start na eerste laadcyclus.</div>`}
      </div>` : "";

    // ── Decision ──
    const decisionHtml = cfg.show_decision ? (() => {
      const conf = Math.round((bd.confidence ?? 0) * 100);
      const prioLbl = PRIO_LABELS[bd.priority ?? 5] ?? "—";
      return `
        <div class="section">
          <div class="sec-title">🧠 Beslissing</div>
          <div class="decision-row"><span class="dk">Actie</span><span></span><span class="dv">${esc(ai.label)}</span></div>
          <div class="decision-row"><span class="dk">Laag</span><span></span><span class="dv">${esc(prioLbl)}</span></div>
          <div class="decision-row">
            <span class="dk">Zekerheid</span>
            <div class="conf-bar"><div class="conf-fill" style="width:${conf}%"></div></div>
            <span class="dv">${conf}%</span>
          </div>
          <div class="decision-row"><span class="dk">Tariefgroep</span><span></span><span class="dv">${esc((bd.tariff_group ?? "?").toUpperCase())}</span></div>
          ${bd.source ? `<div class="decision-row"><span class="dk">Bron</span><span></span><span class="chip-src">${esc(bd.source)}</span></div>` : ""}
        </div>`;
    })() : "";

    // ── Providers ──
    const providersHtml = cfg.show_providers ? (() => {
      const allProviders = [];
      const balancer = bp.balancer ?? {};
      const bIntS  = balancer.battery_interval_s;
      const bStale = balancer.battery_stale ?? false;
      const bLagS  = balancer.battery_lag_s;
      const bLagN  = balancer.battery_lag_samples ?? 0;
      const bLagC  = balancer.battery_lag_conf;

      // Interval-label: groen=vers, oranje=stale, grijs=onbekend
      const intLabel = bIntS != null
        ? `<span class="${bStale ? 'prov-meta-stale' : ''}" title="Gemeten update-interval (adaptief)">${bStale ? '⚠ ' : ''}${bIntS < 10 ? bIntS.toFixed(1) : Math.round(bIntS)}s</span>`
        : `<span style="opacity:.4">—</span>`;

      // Lag-label: toont geleerde vertraging of leervoortgang
      const lagLabel = bLagS != null
        ? `<span title="Geleerde vertraging grid→batterij (${bLagN} obs, ${bLagC != null ? Math.round(bLagC*100)+'%' : '?'} conf)">⏱ ${bLagS.toFixed(1)}s</span>`
        : bLagN > 0
          ? `<span style="opacity:.5" title="Nog lerend (${bLagN}/5 observaties)">⏱ ${bLagN}/5</span>`
          : `<span style="opacity:.3" title="Vertraging wordt geleerd">⏱ —</span>`;

      if (zpRaw != null) {
        const ok  = zpRaw.available;
        const det = zpRaw.detected;
        const modeRaw = zpRaw.active_mode;
        const mode = MODE_MAP[modeRaw] ?? (modeRaw ? modeRaw.replace(/_/g," ") : "—");
        const statusCls = ok ? "prov-status-ok" : (det ? "prov-status-warn" : "prov-status-err");
        const statusLbl = ok ? "✅ Actief" : (det ? "🟡 Gevonden" : "❌ Offline");
        allProviders.push(`<div class="provider-row">
          <span>⚡</span>
          <span class="prov-name">Zonneplan Nexus</span>
          <span class="${statusCls}">${statusLbl}</span>
          <span class="mode-pill">${esc(mode)}</span>
          <span class="prov-meta">${intLabel}<br>${lagLabel}</span>
        </div>`);
      }
      providers.filter(p => p.provider_id !== "zonneplan").forEach(p => {
        const ok = p.available; const det = p.detected;
        const statusCls = ok ? "prov-status-ok" : (det ? "prov-status-warn" : "prov-status-err");
        const statusLbl = ok ? "✅ Actief" : (det ? "🟡 Gevonden" : "❌ Offline");
        allProviders.push(`<div class="provider-row">
          <span>🔌</span>
          <span class="prov-name">${esc(p.provider_label ?? p.provider_id)}</span>
          <span class="${statusCls}">${statusLbl}</span>
          <span></span>
          <span class="prov-meta">${intLabel}<br>${lagLabel}</span>
        </div>`);
      });
      if (!allProviders.length) return "";
      return `<div class="section"><div class="sec-title">⚡ Providers</div>${allProviders.join("")}</div>`;
    })() : "";

    // ── Full HTML ──
    sh.innerHTML = `
      <style>${BATT_STYLES}</style>
      <div class="card">
        ${moduleOffHtml}
        <div class="hdr">
          <span class="hdr-icon">🔋</span>
          <div>
            <div class="hdr-title">${esc(cfg.title ?? "Batterij")}</div>
            <div class="hdr-sub">${esc(subTitle)}</div>
          </div>
          <div class="hdr-right">
            <span class="badge ${ai.badgeCls}">${ai.label}</span>
            ${socNum != null ? `<span style="font-family:var(--b-mono);font-size:11px;color:${socColor_};font-weight:600">${Math.round(socNum)}% SOC</span>` : ""}
          </div>
        </div>

        <div class="soc-ring-wrap">
          <div class="soc-ring">
            <svg viewBox="0 0 110 110">
              <circle class="soc-ring-track" cx="55" cy="55" r="46"/>
              <circle class="soc-ring-fill"
                cx="55" cy="55" r="46"
                stroke="${socColor_}"
                stroke-dasharray="${circumference}"
                stroke-dashoffset="${dashOffset}"/>
            </svg>
            <div class="soc-ring-text">
              <span class="soc-pct">${socNum != null ? Math.round(socNum) : "—"}<span style="font-size:12px">%</span></span>
              <span class="soc-label">SOC</span>
            </div>
          </div>
          <div class="soc-stats">
            <div class="stat-box">
              <div class="sv">${sessDay}</div>
              <div class="sk">Cycli</div>
            </div>
            <div class="stat-box">
              <div class="sv">${parseFloat(kwhDay ?? 0).toFixed(1)}</div>
              <div class="sk">kWh vandaag</div>
            </div>
            <div class="stat-box">
              <div class="sv" style="color:${sohPct != null ? sohColor(parseFloat(sohPct)) : "var(--b-muted)"}">${sohPct != null ? parseFloat(sohPct).toFixed(0) + "%" : "—"}</div>
              <div class="sk">SoH</div>
            </div>
          </div>
        </div>

        ${actionBanner}
        ${battSection}

        <div class="section">
          <div class="sec-title">🩺 Gezondheid</div>
          ${sohHtml}
        </div>

        ${savingsHtml}
        ${decisionHtml}
        ${providersHtml}
      </div>`;
  }

  static getStubConfig() { return { title: "Batterij", show_savings: true, show_decision: true, show_providers: true }; }
  getCardSize() { return 8; }
}

customElements.define("cloudems-battery-card", CloudemsBatteryCard);
window.customCards = window.customCards ?? [];
window.customCards.push({ type:"cloudems-battery-card", name:"CloudEMS Battery Card", description:"Live batterij status, SoH, besparingen en beslissing", preview:true });
console.info(`%c CLOUDEMS-BATTERY-CARD %c v${BATT_VERSION} `, "background:#22d3ee;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#161b22;color:#22d3ee;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
