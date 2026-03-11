/**
 * CloudEMS Shutter Card  v1.0.0
 * Rolluiken — Status, beslissing & automaat-beheer
 *
 *   type: custom:cloudems-shutter-card
 *
 * Optional:
 *   title: "Mijn Rolluiken"
 *   show_learning: true     (default true — oriëntatie/leer info)
 */

const SHUTTER_VERSION = "1.0.0";

// ── Design: warm slate with sky-blue accents ──────────────────────────────────
const SHUTTER_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

  :host {
    --s-bg:       #1a1f2e;
    --s-surface:  #212840;
    --s-surface2: #252c3f;
    --s-border:   rgba(255,255,255,0.07);
    --s-sky:      #7dd3fc;
    --s-sky-dim:  rgba(125,211,252,0.1);
    --s-indigo:   #818cf8;
    --s-green:    #4ade80;
    --s-amber:    #fb923c;
    --s-red:      #f87171;
    --s-text:     #e2e8f0;
    --s-muted:    #64748b;
    --s-subtext:  #94a3b8;
    --s-mono:     'JetBrains Mono', monospace;
    --s-sans:     'DM Sans', sans-serif;
    --s-r:        14px;
    --s-rs:       8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: var(--s-bg);
    border-radius: var(--s-r);
    border: 1px solid var(--s-border);
    overflow: hidden;
    font-family: var(--s-sans);
    transition: border-color .3s, box-shadow .3s, transform .2s;
  }
  .card:hover {
    border-color: rgba(125,211,252,.3);
    box-shadow: 0 8px 32px rgba(0,0,0,.55), 0 0 20px rgba(125,211,252,.05);
    transform: translateY(-2px);
  }

  /* ── Header ── */
  .hdr {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 15px 18px 13px;
    background: linear-gradient(135deg, var(--s-sky-dim) 0%, transparent 60%);
    border-bottom: 1px solid var(--s-border);
    position: relative;
    overflow: hidden;
  }
  .hdr::after {
    content: '';
    position: absolute;
    right: 16px; top: 50%;
    transform: translateY(-50%);
    font-size: 52px;
    opacity: .04;
    pointer-events: none;
    line-height: 1;
  }
  .hdr-icon { font-size: 20px; }
  .hdr-texts { flex: 1; }
  .hdr-title { font-size: 14px; font-weight: 800; color: var(--s-text); letter-spacing: .02em; }
  .hdr-sub   { font-size: 11px; font-weight: 500; color: var(--s-muted); margin-top: 2px; }
  .hdr-badges { display: flex; gap: 6px; flex-wrap: wrap; }

  /* ── Summary strip ── */
  .summary-strip {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-bottom: 1px solid var(--s-border);
  }
  .sum-box {
    padding: 11px 14px;
    border-right: 1px solid var(--s-border);
    text-align: center;
  }
  .sum-box:last-child { border-right: none; }
  .sum-val { font-family: var(--s-mono); font-size: 18px; font-weight: 600; color: var(--s-text); }
  .sum-key { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--s-muted); margin-top: 3px; }

  /* ── Section ── */
  .section { padding: 12px 18px; border-bottom: 1px solid var(--s-border); }
  .section:last-child { border-bottom: none; }
  .sec-title {
    font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .12em;
    color: var(--s-muted); margin-bottom: 9px;
    display: flex; align-items: center; gap: 6px;
  }
  .sec-title::after { content: ''; flex: 1; height: 1px; background: var(--s-border); }

  /* ── Shutter row ── */
  .shutter-row {
    background: var(--s-surface);
    border: 1px solid var(--s-border);
    border-radius: var(--s-rs);
    padding: 11px 14px;
    margin-bottom: 8px;
    animation: fadeUp .25s ease both;
  }
  .shutter-row:last-child { margin-bottom: 0; }

  .shutter-top {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 9px;
  }
  .shutter-name { font-size: 13px; font-weight: 700; color: var(--s-text); flex: 1; }
  .auto-badge {
    font-size: 10px; font-weight: 700;
    padding: 2px 8px; border-radius: 20px;
    letter-spacing: .04em;
  }
  .auto-on  { background: rgba(74,222,128,.1); color: var(--s-green); border: 1px solid rgba(74,222,128,.25); }
  .auto-off { background: rgba(248,113,113,.1); color: var(--s-red); border: 1px solid rgba(248,113,113,.25); }

  /* ── Position bar ── */
  .pos-bar-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 9px;
  }
  .pos-bar-track {
    flex: 1; height: 6px;
    background: rgba(255,255,255,.06);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
  }
  .pos-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width .7s ease;
    background: linear-gradient(90deg, var(--s-sky), var(--s-indigo));
  }
  .pos-pct {
    font-family: var(--s-mono);
    font-size: 12px;
    font-weight: 600;
    color: var(--s-text);
    min-width: 34px;
    text-align: right;
  }

  /* ── Shutter meta row ── */
  .shutter-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .meta-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 5px;
    background: rgba(255,255,255,.04);
    border: 1px solid var(--s-border);
    color: var(--s-subtext);
  }
  .meta-chip.open     { background: rgba(74,222,128,.07);  color: var(--s-green); border-color: rgba(74,222,128,.2); }
  .meta-chip.close    { background: rgba(248,113,113,.07); color: var(--s-red);   border-color: rgba(248,113,113,.2); }
  .meta-chip.idle     { background: rgba(100,116,139,.07); color: var(--s-muted); }
  .meta-chip.decision { background: var(--s-sky-dim); color: var(--s-sky); border-color: rgba(125,211,252,.2); }
  .meta-chip.override { background: rgba(251,146,60,.1); color: var(--s-amber); border-color: rgba(251,146,60,.2); }

  /* ── Decision block ── */
  .decision-block {
    background: rgba(255,255,255,.025);
    border-radius: 6px;
    padding: 7px 10px;
    margin-top: 7px;
    font-size: 11px;
    color: var(--s-subtext);
    line-height: 1.5;
    border-left: 2px solid rgba(125,211,252,.35);
  }
  .decision-block strong { color: var(--s-text); }

  /* ── Override list ── */
  .override-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
    font-size: 12px;
    animation: fadeUp .25s ease both;
  }
  .override-row:last-child { border-bottom: none; }
  .ov-name { flex: 1; font-weight: 600; color: var(--s-text); }
  .ov-timer {
    font-family: var(--s-mono);
    font-size: 11px;
    background: rgba(251,146,60,.1);
    color: var(--s-amber);
    border: 1px solid rgba(251,146,60,.2);
    border-radius: 4px;
    padding: 2px 7px;
  }

  /* ── Learning section ── */
  .learn-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    font-size: 11.5px;
    color: var(--s-subtext);
    line-height: 1.5;
    padding: 5px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
  }
  .learn-row:last-child { border-bottom: none; }
  .learn-row .lk { color: var(--s-muted); font-size: 10.5px; min-width: 100px; flex-shrink: 0; }
  .learn-row .lv { font-family: var(--s-mono); color: var(--s-text); font-weight: 600; }

  /* ── Module off ── */
  .module-off {
    display: flex; align-items: center; gap: 10px;
    margin: 12px; padding: 11px 15px;
    background: rgba(251,146,60,.08);
    border: 1px solid rgba(251,146,60,.3);
    border-radius: var(--s-rs);
    font-size: 12px; color: var(--s-amber); font-weight: 500;
  }

  /* ── Empty ── */
  .empty { text-align: center; padding: 20px 16px; color: var(--s-muted); font-size: 11.5px; line-height: 1.7; }
  .empty-icon { font-size: 28px; display: block; margin-bottom: 8px; opacity: .4; }

  /* ── Badge ── */
  .badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 20px; letter-spacing: .05em; }
  .badge-ok     { background: rgba(125,211,252,.1); color: var(--s-sky);    border: 1px solid rgba(125,211,252,.25); }
  .badge-warn   { background: rgba(251,146,60,.1);  color: var(--s-amber);  border: 1px solid rgba(251,146,60,.25); }

  .spinner { width: 14px; height: 14px; border: 2px solid rgba(125,211,252,.15); border-top-color: var(--s-sky); border-radius: 50%; animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin   { to { transform: rotate(360deg); } }
  @keyframes fadeUp { from { opacity:0; transform:translateY(5px); } to { opacity:1; transform:none; } }
`;

// ── helpers ───────────────────────────────────────────────────────────────────
const esc = s => String(s ?? "—").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function posBar(pos) {
  if (pos < 0) return `<div class="pos-bar-wrap"><div class="pos-bar-track"><div class="pos-bar-fill" style="width:0%"></div></div><span class="pos-pct">—</span></div>`;
  return `<div class="pos-bar-wrap">
    <div class="pos-bar-track"><div class="pos-bar-fill" style="width:${pos}%"></div></div>
    <span class="pos-pct">${pos}%</span>
  </div>`;
}

function actionChip(act) {
  if (act === "open")  return `<span class="meta-chip open">🔼 Open</span>`;
  if (act === "close") return `<span class="meta-chip close">🔽 Dicht</span>`;
  return `<span class="meta-chip idle">⏸ Idle</span>`;
}

// ── Card ──────────────────────────────────────────────────────────────────────
class CloudemsShutterCard extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); this._prevJson = ""; }

  setConfig(cfg) {
    this._cfg = { title: cfg.title ?? "Rolluiken", show_learning: cfg.show_learning !== false, ...cfg };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const json = JSON.stringify([
      hass.states["sensor.cloudems_status"]?.last_changed,
      hass.states["switch.cloudems_module_rolluiken"]?.state,
    ]);
    if (json !== this._prevJson) { this._prevJson = json; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    if (!sh) return;
    const hass = this._hass;
    const cfg  = this._cfg ?? {};

    if (!hass) {
      sh.innerHTML = `<style>${SHUTTER_STYLES}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
      return;
    }

    const statusSensor = hass.states["sensor.cloudems_status"];
    const modSwitch    = hass.states["switch.cloudems_module_rolluiken"];
    const shutterData  = statusSensor?.attributes?.shutters ?? {};
    const shutters     = shutterData.shutters ?? [];

    // Module off banner
    const moduleOffHtml = (modSwitch?.state === "off")
      ? `<div class="module-off">⚠️ Rolluiken module staat uit — schakel in via Configuratie.</div>`
      : "";

    // Summary counts
    const total    = shutters.length;
    const autoOn   = shutters.filter(s => s.auto_enabled !== false).length;
    const overrides= shutters.filter(s => s.override_active).length;
    const openCnt  = shutters.filter(s => s.last_action === "open").length;

    // Header badge
    const hasWarning = overrides > 0 || shutters.some(s => s.auto_enabled === false);
    const badgeHtml = total > 0
      ? `<span class="badge ${hasWarning ? "badge-warn" : "badge-ok"}">${total} rolluik${total !== 1 ? "en" : ""}</span>`
      : "";

    // Empty state
    if (total === 0) {
      sh.innerHTML = `
        <style>${SHUTTER_STYLES}</style>
        <div class="card">
          ${moduleOffHtml}
          <div class="hdr">
            <span class="hdr-icon">🪟</span>
            <div class="hdr-texts">
              <div class="hdr-title">${esc(cfg.title)}</div>
              <div class="hdr-sub">Geen rolluiken geconfigureerd</div>
            </div>
          </div>
          <div class="empty">
            <span class="empty-icon">🪟</span>
            Nog geen rolluiken gekoppeld.<br>
            Configureer via <strong>CloudEMS → Rolluiken</strong>.
          </div>
        </div>`;
      return;
    }

    // ── Shutter rows ──
    const shutterRows = shutters.map((s, i) => {
      const pos     = s.position ?? -1;
      const act     = s.last_action ?? "";
      const autoOn  = s.auto_enabled !== false;
      const label   = s.label ?? s.entity_id ?? `Rolluik ${i+1}`;
      const dec     = s.decision;
      const reason  = s.reason;
      const ovAct   = s.override_active;

      const decisionBlock = (dec || reason) ? `
        <div class="decision-block">
          ${dec ? `<strong>${esc(dec)}</strong>` : ""}
          ${reason ? ` — ${esc(reason)}` : ""}
        </div>` : "";

      return `
        <div class="shutter-row" style="animation-delay:${i * .07}s">
          <div class="shutter-top">
            <span class="shutter-name">${esc(label)}</span>
            <span class="auto-badge ${autoOn ? "auto-on" : "auto-off"}">${autoOn ? "🤖 AAN" : "🔴 UIT"}</span>
          </div>
          ${posBar(pos)}
          <div class="shutter-meta">
            ${actionChip(act)}
            ${dec ? `<span class="meta-chip decision">📋 ${esc(dec)}</span>` : ""}
            ${ovAct ? `<span class="meta-chip override">⏱️ Override</span>` : ""}
          </div>
          ${!dec && reason ? decisionBlock : ""}
          ${dec && reason ? `<div class="decision-block">${esc(reason)}</div>` : ""}
        </div>`;
    }).join("");

    // ── Override timers (from sensor entities) ──
    const overrideEntities = Object.values(hass.states).filter(e =>
      e.entity_id.startsWith("sensor.cloudems_rolluik_") &&
      e.entity_id.endsWith("_override_restant") &&
      e.state && e.state !== "00:00:00" &&
      e.state !== "unavailable" && e.state !== "unknown"
    );

    const overrideSection = overrideEntities.length > 0 ? `
      <div class="section">
        <div class="sec-title">⏱️ Actieve overrides</div>
        ${overrideEntities.map((e, i) => {
          const name = e.attributes.friendly_name ?? e.entity_id;
          return `<div class="override-row" style="animation-delay:${i*.06}s">
            <span>⏰</span>
            <span class="ov-name">${esc(name.replace(/override restant/i,"").trim())}</span>
            <span class="ov-timer">${esc(e.state)}</span>
          </div>`;
        }).join("")}
      </div>` : "";

    // ── Learning info ──
    const learningHtml = cfg.show_learning ? `
      <div class="section">
        <div class="sec-title">🧭 Oriëntatie & leren</div>
        <div class="learn-row"><span class="lk">Methode</span><span class="lv">Temp. & zoncorrelatie</span></div>
        <div class="learn-row"><span class="lk">Automaat</span><span class="lv">${autoOn} van ${total} aan</span></div>
        ${overrides > 0 ? `<div class="learn-row"><span class="lk">Overrides</span><span class="lv" style="color:var(--s-amber)">${overrides} actief</span></div>` : ""}
        <div class="learn-row" style="border:none;padding-top:6px;padding-bottom:0;color:var(--s-muted);font-style:italic;font-size:10.5px">
          <span>Oriëntatie wordt automatisch geleerd via temperatuur- en zoncorrelatie.</span>
        </div>
      </div>` : "";

    // ── Full HTML ──
    sh.innerHTML = `
      <style>${SHUTTER_STYLES}</style>
      <div class="card">
        ${moduleOffHtml}
        <div class="hdr">
          <span class="hdr-icon">🪟</span>
          <div class="hdr-texts">
            <div class="hdr-title">${esc(cfg.title)}</div>
            <div class="hdr-sub">${autoOn} automaat aan · ${openCnt} open</div>
          </div>
          <div class="hdr-badges">${badgeHtml}</div>
        </div>

        <div class="summary-strip">
          <div class="sum-box">
            <div class="sum-val">${total}</div>
            <div class="sum-key">Totaal</div>
          </div>
          <div class="sum-box">
            <div class="sum-val" style="color:var(--s-green)">${autoOn}</div>
            <div class="sum-key">Automaat</div>
          </div>
          <div class="sum-box">
            <div class="sum-val" style="color:${overrides > 0 ? "var(--s-amber)" : "var(--s-muted)"}">${overrides}</div>
            <div class="sum-key">Overrides</div>
          </div>
        </div>

        <div class="section">
          <div class="sec-title">🪟 Status & beslissing</div>
          ${shutterRows}
        </div>

        ${overrideSection}
        ${learningHtml}
      </div>`;
  }

  static getStubConfig() { return { title: "Rolluiken", show_learning: true }; }
  getCardSize() { return 6; }
}

customElements.define("cloudems-shutter-card", CloudemsShutterCard);
window.customCards = window.customCards ?? [];
window.customCards.push({ type:"cloudems-shutter-card", name:"CloudEMS Shutter Card", description:"Rolluiken status, beslissing en automaat-beheer", preview:true });
console.info(`%c CLOUDEMS-SHUTTER-CARD %c v${SHUTTER_VERSION} `, "background:#7dd3fc;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#1a1f2e;color:#7dd3fc;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
