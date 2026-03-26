// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Appliance Card  v1.2.0

const APPLIANCE_VERSION = "5.3.56";
const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

const DEVICE_ICONS = {
  vaatwasser:{ icon:"🍽", color:"#378ADD" },
  wasmachine: { icon:"👕", color:"#1D9E75" },
  droger:     { icon:"♨",  color:"#BA7517" },
  droogkast:  { icon:"♨",  color:"#BA7517" },
  boiler:     { icon:"🚿", color:"#e55"    },
  default:    { icon:"🔌", color:"#555"    },
};

// delay_state → human label + kleur + uitleg
const DELAY_INFO = {
  idle:        { label:"Idle",            color:"var(--a-muted)",  icon:"💤", uitleg:"" },
  detected:    { label:"Gedetecteerd",    color:"#fbbf24",         icon:"👁",  uitleg:"Apparaat ingeschakeld gedetecteerd — wacht op grace period voor uitschakelen." },
  intercepted: { label:"Wacht op goedkoop blok", color:"#60a5fa", icon:"⏳", uitleg:"CloudEMS heeft het apparaat uitgeschakeld en wacht op een goedkoop uur of surplus." },
  activating:  { label:"Inschakelen…",   color:"#4ade80",         icon:"▶",  uitleg:"Goedkoop blok bereikt — CloudEMS schakelt het apparaat nu in." },
  cancelled:   { label:"Geannuleerd",    color:"var(--a-amber)",  icon:"✖",  uitleg:"Uitgesteld maar goedkoop blok niet bereikt binnen maximale wachttijd." },
};

function deviceMeta(id) {
  const s = (id||"").toLowerCase();
  for (const [k,v] of Object.entries(DEVICE_ICONS)) {
    if (k!=="default" && s.includes(k)) return v;
  }
  return DEVICE_ICONS.default;
}
function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(typeof ts==="number"?ts*1000:ts).toLocaleTimeString("nl-NL",{hour:"2-digit",minute:"2-digit"});
}
function fmtPrice(p) { return p==null ? "—" : (parseFloat(p)*100).toFixed(1)+" ct"; }
function padH(h)     { return h!=null ? String(h).padStart(2,"0")+":00" : "—"; }

function calcCost(devLogs, histPts, windowH) {
  // Zoek de meest recente activatie (turned_on / activated / surplus_activated)
  const actLog = devLogs.find(e =>
    ["turned_on","activated","surplus_activated","deadline_forced"].includes(e.action)
  );
  if (!actLog) return null;

  const price = actLog.all_in_eur_kwh ?? actLog.price_eur_kwh ?? 0;
  const wh    = parseInt(actLog.window_hours ?? windowH ?? 2);
  if (!price || !wh) return null;

  // Gemiddeld vermogen uit history (indien beschikbaar)
  let avgW = null;
  if (histPts && histPts.length >= 2) {
    const actTs = new Date(actLog.iso).getTime();
    const endTs  = actTs + wh * 3600 * 1000;
    const inRun  = histPts.filter(p => p.ts >= actTs && p.ts <= endTs && p.v > 5);
    if (inRun.length > 3) {
      avgW = inRun.reduce((s, p) => s + p.v, 0) / inRun.length;
    }
  }

  if (avgW != null) {
    // Exacte berekening met gemeten vermogen
    const kwh  = (avgW / 1000) * wh;
    const cost  = kwh * price;
    return { cost, kwh: round2(kwh), avgW: Math.round(avgW), price, wh, exact: true };
  } else {
    // Schatting: window_hours × goedkoopste blok prijs (geen vermogen beschikbaar)
    return { cost: null, kwh: null, avgW: null, price, wh, exact: false };
  }
}

function round2(v) { return Math.round(v * 100) / 100; }

const CSS = `
  :host {
    --a-bg:var(--ha-card-background,var(--card-background-color,#1c1c1c));
    --a-surface:rgba(255,255,255,.04);--a-border:rgba(255,255,255,.08);
    --a-text:var(--primary-text-color,#e8eaed);--a-muted:var(--secondary-text-color,#9aa0a6);
    --a-green:#1D9E75;--a-amber:#BA7517;--a-blue:#378ADD;--a-red:#e55;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--a-bg);border-radius:12px;overflow:hidden;font-family:var(--primary-font-family,sans-serif);}
  .module-warn{padding:8px 16px;background:rgba(192,57,43,.1);border-bottom:0.5px solid rgba(192,57,43,.3);font-size:12px;color:#f87171;}
  .hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 12px;border-bottom:0.5px solid var(--a-border);}
  .hdr-title{font-size:13px;font-weight:500;color:var(--a-muted);}
  .hdr-right{display:flex;align-items:center;gap:10px;}
  .mod-lbl{font-size:11px;color:var(--a-muted);}
  .mod-tog{width:36px;height:20px;border-radius:10px;cursor:pointer;position:relative;border:none;transition:background .2s;}
  .mod-tog.on{background:var(--a-green);}.mod-tog.off{background:rgba(255,255,255,.15);}
  .mod-tog::after{content:'';position:absolute;width:14px;height:14px;border-radius:50%;background:#fff;top:3px;transition:left .2s;}
  .mod-tog.on::after{left:19px;}.mod-tog.off::after{left:3px;}
  /* EPEX */
  .epex-bar{display:flex;gap:6px;padding:8px 16px;border-bottom:0.5px solid var(--a-border);}
  .ep{display:flex;flex-direction:column;align-items:center;padding:5px 10px;border-radius:6px;border:0.5px solid var(--a-border);background:var(--a-surface);min-width:52px;cursor:default;}
  .ep.active{border-color:var(--a-blue);background:rgba(55,138,221,.12);}
  .ep-lbl{font-size:10px;color:var(--a-muted);}
  .ep-time{font-size:13px;font-weight:600;color:var(--a-text);}
  .ep-price{font-size:10px;color:var(--a-muted);}
  /* Totalen */
  .totals{display:flex;border-bottom:0.5px solid var(--a-border);}
  .tot{flex:1;text-align:center;padding:10px 6px;}
  .tot+.tot{border-left:0.5px solid var(--a-border);}
  .tot-val{font-size:18px;font-weight:700;}
  .tot-lbl{font-size:11px;color:var(--a-muted);margin-top:2px;}
  /* Body */
  .body{padding:12px 16px;}
  .empty{padding:32px;text-align:center;color:var(--a-muted);font-size:13px;}
  /* Device card */
  .device{background:var(--a-surface);border:0.5px solid var(--a-border);border-radius:10px;margin-bottom:10px;overflow:hidden;}
  .device:last-child{margin-bottom:0;}
  .dev-hdr{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:0.5px solid var(--a-border);}
  .dev-icon{font-size:20px;width:28px;text-align:center;}
  .dev-name{font-size:14px;font-weight:600;color:var(--a-text);flex:1;}
  .dev-badges{display:flex;gap:6px;align-items:center;}
  .badge{font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;}
  .b-on{background:rgba(29,158,117,.18);color:#4ade80;}
  .b-off{background:rgba(255,255,255,.06);color:var(--a-muted);}
  .b-block{background:rgba(55,138,221,.18);color:#60a5fa;}
  .b-wait{background:rgba(96,165,250,.15);color:#60a5fa;}
  .b-detect{background:rgba(251,191,36,.15);color:#fbbf24;}
  /* Status banner */
  .status-banner{display:flex;align-items:flex-start;gap:8px;padding:8px 14px;border-bottom:0.5px solid var(--a-border);font-size:12px;}
  .status-icon{font-size:16px;flex-shrink:0;}
  .status-text{flex:1;color:var(--a-text);line-height:1.5;}
  .status-sub{color:var(--a-muted);font-size:11px;margin-top:2px;}
  /* Power */
  .power-row{display:flex;align-items:center;gap:10px;padding:8px 14px;border-bottom:0.5px solid var(--a-border);}
  .power-val{font-size:22px;font-weight:700;color:var(--a-text);}
  .power-unit{font-size:13px;color:var(--a-muted);margin-top:4px;}
  /* Graph */
  .graph-wrap{padding:8px 14px 0;border-bottom:0.5px solid var(--a-border);}
  .graph-lbl{font-size:11px;color:var(--a-muted);margin-bottom:4px;}
  .graph-svg{width:100%;height:70px;display:block;}
  .graph-loading{padding:16px 14px;font-size:11px;color:var(--a-muted);}
  /* Details grid */
  .dev-body{padding:10px 14px;display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;}
  .di{display:flex;flex-direction:column;gap:2px;}
  .di-label{font-size:11px;color:var(--a-muted);text-transform:uppercase;letter-spacing:.04em;}
  .di-value{font-size:13px;font-weight:500;color:var(--a-text);}
  .di-value.good{color:var(--a-green);}.di-value.warn{color:var(--a-amber);}.di-value.info{color:var(--a-blue);}
  /* Log */
  .log-toggle{width:100%;font-size:12px;padding:7px 14px;border:none;border-top:0.5px solid var(--a-border);background:transparent;cursor:pointer;color:var(--a-muted);text-align:left;}
  .log-toggle:hover{background:rgba(255,255,255,.04);}
  .log-panel{padding:8px 14px 10px;border-top:0.5px solid var(--a-border);}
  .log-row{display:flex;gap:8px;padding:4px 0;border-bottom:0.5px solid var(--a-border);font-size:12px;}
  .log-row:last-child{border-bottom:none;}
  .log-time{color:var(--a-muted);min-width:38px;font-family:monospace;}
  .log-action{font-weight:600;min-width:80px;}
  .log-reason{color:var(--a-muted);flex:1;}
  .act-turned_on,.act-activating{color:#4ade80;}
  .act-already_on,.act-intercepted{color:#60a5fa;}
  .act-detected{color:#fbbf24;}
  .act-skipped,.act-cancelled{color:var(--a-amber);}
  .act-turned_off{color:#f87171;}
  .cost-row{display:flex;align-items:center;gap:8px;padding:6px 14px;border-top:0.5px solid var(--a-border);font-size:12px;}
  .cost-icon{font-size:14px;}
  .cost-val{font-weight:600;color:var(--a-green);}
  .cost-sub{color:var(--a-muted);flex:1;}
  .cost-est{font-size:10px;color:var(--a-amber);}
`;

class CloudemsApplianceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this._prev = "";
    this._openLogs = new Set();
    this._history = {};   // entity_id → [{ts, value}]
    this._histPending = new Set();
  }

  setConfig(c) { this._cfg = {title:"Slimme Schakelaars",...c}; this._render(); }

  set hass(h) {
    this._hass = h;
    const cs   = h.states["sensor.cloudems_goedkope_uren_schakelaars"];
    const sw   = h.states["switch.cloudems_module_goedkope_uren"];
    const pr   = h.states["sensor.cloudems_price_current_hour"];
    const hist = h.states["sensor.cloudems_decisions_history"];

    // Power sensor live values
    const switches = cs?.attributes?.switches ?? [];
    const sdList   = cs?.attributes?.smart_delay ?? [];
    const powerVals = switches.map(s => {
      const sd = (Array.isArray(sdList) ? sdList : []).find(d => d.entity_id === s.entity_id);
      const ps = sd?.power_sensor;
      return ps ? (h.states[ps]?.state ?? null) : null;
    }).join("|");

    const hash = JSON.stringify([
      cs?.attributes?.switches, cs?.attributes?.smart_delay,
      sw?.state, pr?.attributes?.cheapest_2h_start,
      hist?.last_changed, powerVals,
    ]);
    if (hash !== this._prev) {
      this._prev = hash;
      // Fetch history for power sensors we don't have yet
      this._fetchMissingHistory(switches, sdList);
      this._render();
    }
  }

  async _fetchMissingHistory(switches, sdList) {
    if (!this._hass) return;
    const sdArr = Array.isArray(sdList) ? sdList : [];
    for (const sw of switches) {
      const sd = sdArr.find(d => d.entity_id === sw.entity_id);
      const ps = sd?.power_sensor;
      if (!ps || this._history[ps] || this._histPending.has(ps)) continue;
      this._histPending.add(ps);
      try {
        const end = new Date();
        const start = new Date(end - 12*3600*1000);
        const res = await this._hass.callWS({
          type: "history/history_during_period",
          start_time: start.toISOString(),
          end_time:   end.toISOString(),
          entity_ids: [ps],
          minimal_response: true,
          no_attributes: true,
          significant_changes_only: false,
        });
        const raw = res?.[ps] ?? [];
        this._history[ps] = raw
          .map(s => ({ts: new Date(s.lu*1000||s.last_updated||s.last_changed).getTime(), v: parseFloat(s.s??s.state)}))
          .filter(p => !isNaN(p.v));
      } catch(e) {
        this._history[ps] = [];
      }
      this._histPending.delete(ps);
      this._render();
    }
  }

  _buildGraph(ps, decisions, entityId) {
    const pts = this._history[ps];
    if (!pts || pts.length < 2) return `<div class="graph-loading">Vermogensgrafiek laden…</div>`;

    const W = 480, H = 70, PAD = 2;
    const maxV = Math.max(10, ...pts.map(p => p.v));
    const minT = pts[0].ts, maxT = pts[pts.length-1].ts;
    const tRange = maxT - minT || 1;

    const x = ts => PAD + (ts - minT) / tRange * (W - 2*PAD);
    const y = v  => H - PAD - (v / maxV) * (H - 2*PAD);

    // Line path
    const path = pts.map((p,i) => `${i===0?"M":"L"}${x(p.ts).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    const fill = path + ` L${x(maxT).toFixed(1)},${H} L${x(minT).toFixed(1)},${H} Z`;

    // Event markers van decisions history
    const allDec = this._hass?.states["sensor.cloudems_decisions_history"]?.attributes?.decisions ?? [];
    const evts = allDec.filter(e =>
      (e.entity_id === entityId || e.label === entityId) &&
      ["intercepted","activating","turned_on","turned_off","detected"].includes(e.action)
    );

    const markers = evts.map(e => {
      const ts = new Date(e.iso).getTime();
      if (ts < minT || ts > maxT) return "";
      const ex = x(ts);
      const col = e.action==="intercepted"?"#f87171":e.action==="activating"||e.action==="turned_on"?"#4ade80":"#fbbf24";
      const lbl = e.action==="intercepted"?"uit":e.action==="activating"||e.action==="turned_on"?"aan":"!";
      return `<line x1="${ex}" y1="0" x2="${ex}" y2="${H}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity=".7"/>
              <circle cx="${ex}" cy="${y(0)+2}" r="4" fill="${col}" opacity=".9"/>
              <text x="${ex+3}" y="12" font-size="8" fill="${col}" font-family="monospace">${lbl}</text>`;
    }).join("");

    // Time labels
    const timeLabels = [0, 0.25, 0.5, 0.75, 1].map(frac => {
      const ts = minT + frac * tRange;
      const lx = x(ts);
      const t = new Date(ts).toLocaleTimeString("nl-NL",{hour:"2-digit",minute:"2-digit"});
      return `<text x="${lx}" y="${H-1}" font-size="8" fill="rgba(255,255,255,.3)" text-anchor="middle">${t}</text>`;
    }).join("");

    return `<div class="graph-wrap">
      <div class="graph-lbl">Vermogen 12u · max ${maxV.toFixed(0)}W</div>
      <svg class="graph-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <defs>
          <linearGradient id="pg-${ps.replace(/\W/g,'_')}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#378ADD" stop-opacity=".4"/>
            <stop offset="100%" stop-color="#378ADD" stop-opacity=".0"/>
          </linearGradient>
        </defs>
        <path d="${fill}" fill="url(#pg-${ps.replace(/\W/g,'_')})" />
        <path d="${path}" fill="none" stroke="#378ADD" stroke-width="1.5"/>
        ${markers}
        ${timeLabels}
      </svg>
    </div>`;
  }

  _render() {
    const sh = this.shadowRoot;
    const h = this._hass, c = this._cfg ?? {};
    if (!h) { sh.innerHTML=`<style>${CSS}</style><div class="card"><div class="empty">Laden…</div></div>`; return; }

    const csSensor = h.states["sensor.cloudems_goedkope_uren_schakelaars"];
    const modSw    = h.states["switch.cloudems_module_goedkope_uren"];
    const prAttr   = h.states["sensor.cloudems_price_current_hour"]?.attributes ?? {};
    const moduleOn  = modSw?.state === "on";
    const moduleOff = modSw?.state === "off";
    const nowH = new Date().getHours();

    // EPEX pills
    const epexPills = [1,2,3,4].map(n => {
      const startH = prAttr[`cheapest_${n}h_start`];
      const block  = prAttr[`cheapest_${n}h_block`] ?? {};
      const active = startH != null && nowH >= startH && nowH < startH + n;
      return `<div class="ep ${active?"active":""}">
        <span class="ep-lbl">${n}u</span>
        <span class="ep-time">${padH(startH)}</span>
        <span class="ep-price">${fmtPrice(block.avg_price)}</span>
      </div>`;
    }).join("");

    if (!csSensor || csSensor.state === "unavailable") {
      sh.innerHTML = `<style>${CSS}</style><div class="card">
        ${moduleOff?`<div class="module-warn">⚠️ Module Goedkope Uren staat uit.</div>`:""}
        <div class="hdr"><span class="hdr-title">${esc(c.title)}</span>
          <div class="hdr-right"><span class="mod-lbl">Module</span>
            <button class="mod-tog ${moduleOn?"on":"off"}" data-action="toggle-module"></button></div></div>
        <div class="epex-bar">${epexPills}</div>
        <div class="empty">Geen schakelaars geconfigureerd.<br>Koppel via CloudEMS → Goedkope Uren.</div>
      </div>`;
      this._bindEvents(sh, modSw, []);
      return;
    }

    const switches = csSensor.attributes?.switches ?? [];
    const sdList   = csSensor.attributes?.smart_delay ?? [];
    const sdArr    = Array.isArray(sdList) ? sdList : [];
    const allDec   = h.states["sensor.cloudems_decisions_history"]?.attributes?.decisions ?? [];
    const csDec    = allDec.filter(e => e.cat === "cheap_switch");

    const totalOn      = switches.filter(s => s.current_state === "on").length;
    const totalInBlock = switches.filter(s => s.in_block).length;
    const totalWaiting = sdArr.filter(s => s.delay_state === "intercepted").length;

    const deviceCards = switches.map(sw => {
      const meta = deviceMeta(sw.entity_id);
      const sd   = sdArr.find(d => d.entity_id === sw.entity_id) ?? {};
      const ds   = sd.delay_state ?? "idle";
      const di   = DELAY_INFO[ds] ?? DELAY_INFO.idle;
      const ps   = sd.power_sensor;
      const pwrState = ps ? h.states[ps] : null;
      const pwrW = pwrState && !["unavailable","unknown"].includes(pwrState.state) ? parseFloat(pwrState.state) : null;

      // Badges
      const state = sw.current_state ?? "unavailable";
      let stateBadge = "";
      if (state === "on" && sw.in_block)    stateBadge = `<span class="badge b-block">Aan · goedkoop</span>`;
      else if (state === "on")              stateBadge = `<span class="badge b-on">Aan</span>`;
      else                                  stateBadge = `<span class="badge b-off">Uit</span>`;

      let delayBadge = "";
      if (ds === "intercepted") delayBadge = `<span class="badge b-wait">⏳ Wacht</span>`;
      else if (ds === "detected") delayBadge = `<span class="badge b-detect">👁 Gedetecteerd</span>`;

      // Status banner
      let banner = "";
      if (ds !== "idle") {
        const targetH = sd.target_hour;
        const waitMin = sd.waiting_min;
        let sub = di.uitleg;
        if (ds === "intercepted") {
          sub = `Wacht op ${padH(targetH)}`;
          if (waitMin) sub += ` · Wacht al ${Math.round(waitMin)} min`;
          if (sd.reason) sub += ` · ${sd.reason}`;
        }
        banner = `<div class="status-banner">
          <span class="status-icon">${di.icon}</span>
          <div>
            <div class="status-text"><strong>${di.label}</strong></div>
            <div class="status-sub">${esc(sub)}</div>
          </div>
        </div>`;
      }

      // Power
      const powerRow = ps ? `<div class="power-row">
        <div>
          <div class="power-val" style="color:${pwrW!=null&&pwrW>0?"var(--a-blue)":"var(--a-muted)"}">${pwrW!=null?pwrW.toFixed(0):"—"}</div>
          <div class="power-unit">Watt · ${esc(ps.split(".").pop().replace(/_/g," "))}</div>
        </div>
      </div>` : "";

      // Graph
      const graphHtml = ps ? this._buildGraph(ps, csDec, sw.entity_id) : "";

      // Log
      const devLogs = csDec.filter(e => (e.entity_id||e.label||"") === sw.entity_id).slice(0,10);
      const costInfo = calcCost(devLogs, this._history[ps] || null, windowH);
      const logOpen = this._openLogs.has(sw.entity_id);
      const devName = (sd.label || sw.entity_id).replace(/_/g," ");

      const startH = sw.start_hour ?? sd.cheap_block_start;
      const windowH = sw.window_hours ?? sd.window_hours ?? 4;
      const barPct = (sw.in_block && startH!=null) ? Math.min(100,Math.max(0,((nowH-startH)/windowH)*100)) : 0;

      return `<div class="device">
        <div class="dev-hdr">
          <span class="dev-icon">${meta.icon}</span>
          <span class="dev-name">${esc(devName)}</span>
          <div class="dev-badges">${stateBadge}${delayBadge}</div>
        </div>
        ${banner}
        ${powerRow}
        ${graphHtml}
        <div class="dev-body">
          <div class="di">
            <span class="di-label">Goedkoopste blok</span>
            <span class="di-value ${sw.in_block?"info":""}">${padH(startH)} – ${startH!=null?padH((startH+windowH)%24):"—"}</span>
          </div>
          <div class="di">
            <span class="di-label">Gem. prijs</span>
            <span class="di-value ${sw.avg_price!=null&&sw.avg_price<0.10?"good":sw.avg_price!=null&&sw.avg_price>0.20?"warn":""}">${fmtPrice(sw.avg_price)}</span>
          </div>
          <div class="di">
            <span class="di-label">Venster</span>
            <span class="di-value">${windowH}u · ${esc(sw.earliest_hour??0)}:00–${esc(sw.latest_hour??23)}:00</span>
          </div>
          <div class="di">
            <span class="di-label">Laatste start</span>
            <span class="di-value">${fmtTime(sw.last_triggered)}</span>
          </div>
          ${sw.in_block?`<div style="grid-column:1/-1;height:5px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;margin-top:4px"><div style="height:100%;border-radius:3px;background:var(--a-blue);width:${barPct}%"></div></div>`:""}
        </div>
        ${costInfo ? `<div class="cost-row">
          <span class="cost-icon">💶</span>
          ${costInfo.cost != null
            ? `<span class="cost-val">${(costInfo.cost*100).toFixed(1)} ct</span>
               <span class="cost-sub">${costInfo.kwh} kWh · ${costInfo.avgW}W gem. · €${costInfo.price.toFixed(4)}/kWh</span>
               <span class="cost-est">laatste beurt</span>`
            : `<span class="cost-sub">Prijs: €${costInfo.price.toFixed(4)}/kWh · ${costInfo.wh}u venster</span>
               <span class="cost-est">⚠ geen vermogenssensor → geen kWh</span>`
          }
        </div>` : ""}
        <button class="log-toggle" data-action="toggle-log" data-entity="${esc(sw.entity_id)}">
          ${logOpen?"▼":"▶"} Log (${devLogs.length})
        </button>
        ${logOpen?`<div class="log-panel">${devLogs.length
          ?devLogs.map(e=>`<div class="log-row">
              <span class="log-time">${esc((e.iso||"").substring(11,16))}</span>
              <span class="log-action act-${esc(e.action)}">${esc(e.action)}</span>
              <span class="log-reason">${esc(e.reason)}</span>
            </div>`).join("")
          :`<div style="font-size:12px;color:var(--a-muted)">Nog geen log</div>`
        }</div>`:""}
      </div>`;
    }).join("");

    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      ${moduleOff?`<div class="module-warn">⚠️ Module Goedkope Uren staat uit — zet aan via de schakelaar.</div>`:""}
      <div class="hdr">
        <span class="hdr-title">${esc(c.title)}</span>
        <div class="hdr-right">
          <span class="mod-lbl">Module</span>
          <button class="mod-tog ${moduleOn?"on":"off"}" data-action="toggle-module"></button>
        </div>
      </div>
      <div class="epex-bar">${epexPills}</div>
      <div class="totals">
        <div class="tot"><div class="tot-val" style="color:${totalOn>0?"var(--a-green)":"var(--a-muted)"}">${totalOn}</div><div class="tot-lbl">Aan</div></div>
        <div class="tot"><div class="tot-val" style="color:${totalWaiting>0?"#60a5fa":"var(--a-muted)"}">${totalWaiting}</div><div class="tot-lbl">Wacht</div></div>
        <div class="tot"><div class="tot-val" style="color:${totalInBlock>0?"var(--a-blue)":"var(--a-muted)"}">${totalInBlock}</div><div class="tot-lbl">In blok</div></div>
      </div>
      <div class="body">${switches.length?deviceCards:`<div class="empty">Geen schakelaars geconfigureerd.</div>`}</div>
    </div>`;

    this._bindEvents(sh, modSw, switches);
  }

  _bindEvents(sh, modSw, switches) {
    sh.querySelector("[data-action=toggle-module]")?.addEventListener("click", () => {
      if (!modSw||!this._hass) return;
      this._hass.callService("switch", modSw.state==="on"?"turn_off":"turn_on",
        {entity_id:"switch.cloudems_module_goedkope_uren"});
    });
    sh.querySelector(".body")?.addEventListener("click", e => {
      const btn = e.target.closest("[data-action]");
      if (!btn||btn.dataset.action!=="toggle-log") return;
      const eid = btn.dataset.entity;
      this._openLogs.has(eid)?this._openLogs.delete(eid):this._openLogs.add(eid);
      this._render();
    });
  }

  static getConfigElement() { return document.createElement("cloudems-appliance-card-editor"); }
  static getStubConfig()    { return {title:"Slimme Schakelaars"}; }
  getCardSize() { return 6; }
}

class CloudemsApplianceCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:"open"}); this._cfg={}; }
  setConfig(c)  { this._cfg={...c}; this._render(); }
  set hass(h)   { this._hass=h; }
  _fire() { this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render() {
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>.wrap{padding:8px;}.row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input{background:var(--card-background-color,#1c1c1c);border:1px solid rgba(255,255,255,.15);border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:180px;}</style>
<div class="wrap">
  <div class="row"><label class="lbl">Titel</label><input name="title" value="${esc(cfg.title??"Slimme Schakelaars")}"></div>
</div>`;
    this.shadowRoot.querySelector("input[name=title]")?.addEventListener("change",e=>{
      this._cfg={...this._cfg,title:e.target.value}; this._fire();
    });
  }
}

if (!customElements.get('cloudems-appliance-card-editor')) customElements.define("cloudems-appliance-card-editor",CloudemsApplianceCardEditor);
if (!customElements.get('cloudems-appliance-card')) customElements.define("cloudems-appliance-card",CloudemsApplianceCard);
window.customCards=window.customCards??[];
window.customCards.push({type:"cloudems-appliance-card",name:"CloudEMS Appliance Card",description:"Slimme schakelaars — vaatwasser, wasmachine, droger",preview:true});
console.info(`%c CLOUDEMS-APPLIANCE-CARD %c v${APPLIANCE_VERSION} `,"background:#378ADD;color:#fff;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0e1520;color:#378ADD;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
