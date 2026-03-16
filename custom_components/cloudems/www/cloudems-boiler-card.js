// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. Unauthorized copying, redistribution, or commercial
// use of this file is strictly prohibited. See LICENSE for full terms.

/**
 * CloudEMS Boiler Card  v1.0.0
 * Warm water dashboard — live status, beschikbare liters, douches, grafieken
 *
 *   type: custom:cloudems-boiler-card
 *
 * Optional config:
 *   tank_liters: 80          (standaard: 80L)
 *   cold_water_temp: 10      (standaard: 10°C — inkomend koud water)
 *   shower_temp: 38          (standaard: 38°C — douchetemperatuur)
 *   shower_liters_per_min: 8 (standaard: 8 L/min)
 *   shower_duration_min: 8   (standaard: 8 minuten)
 *   title: "Warm water"
 */

const BOILER_CARD_VERSION = "1.1.2";

// ── Design tokens ────────────────────────────────────────────────────────────
const S = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

  :host { display: block; --gap: 16px; }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: #111318;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px;
    overflow: hidden;
    font-family: 'Syne', sans-serif;
    position: relative;
  }

  /* ── Animated background glow ── */
  .card::before {
    content: '';
    position: absolute;
    inset: -60px;
    background:
      radial-gradient(ellipse 60% 40% at 20% 0%, rgba(255,100,40,0.08) 0%, transparent 60%),
      radial-gradient(ellipse 50% 35% at 80% 100%, rgba(52,140,220,0.06) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
  }

  .inner { position: relative; z-index: 1; }

  /* ── Header ── */
  .hdr {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 18px 20px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }
  .hdr-icon {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, rgba(255,100,40,0.25), rgba(255,160,80,0.1));
    border: 1px solid rgba(255,120,50,0.3);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
  }
  .hdr-title { font-size: 15px; font-weight: 700; color: #f0f0f0; letter-spacing: 0.02em; }
  .hdr-sub   { font-size: 12px; color: #5a6070; margin-top: 1px; font-family: 'JetBrains Mono', monospace; }
  .hdr-badge {
    margin-left: auto;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    font-family: 'JetBrains Mono', monospace;
  }
  .badge-on  { background: rgba(0,220,100,0.12); border: 1px solid rgba(0,220,100,0.3); color: #00dc64; }
  .badge-off { background: rgba(120,120,120,0.12); border: 1px solid rgba(120,120,120,0.2); color: #666; }
  .badge-boost { background: rgba(255,100,40,0.15); border: 1px solid rgba(255,100,40,0.4); color: #ff6428; }
  .badge-green { background: rgba(0,200,120,0.12); border: 1px solid rgba(0,200,120,0.3); color: #00c878; }

  /* ── Hero section: tank visual + main stats ── */
  .hero {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0;
    padding: 20px 20px 0;
    align-items: start;
  }

  /* ── Tank SVG container ── */
  .tank-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding-right: 20px;
  }
  .tank-label { font-size: 10px; color: #444; letter-spacing: 0.1em; text-transform: uppercase; }

  /* ── Right stats ── */
  .stats-col {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .temp-big {
    display: flex;
    align-items: baseline;
    gap: 4px;
  }
  .temp-val { font-size: 52px; font-weight: 800; color: #f0f0f0; line-height: 1; letter-spacing: -2px; }
  .temp-unit { font-size: 22px; font-weight: 600; color: #555; }
  .temp-label { font-size: 11px; color: #5a6070; letter-spacing: 0.06em; text-transform: uppercase; }

  .setpoint-row {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
  }
  .sp-icon { font-size: 14px; }
  .sp-text { font-size: 12px; color: #888; }
  .sp-val  { font-size: 13px; font-weight: 700; color: #e0e0e0; margin-left: auto; font-family: 'JetBrains Mono', monospace; }
  .sp-bar-wrap { position: relative; height: 3px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden; margin-top: 4px; }
  .sp-bar { height: 100%; border-radius: 2px; transition: width 1.2s cubic-bezier(.4,0,.2,1); }

  /* ── Metrics strip ── */
  .metrics {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    margin: 16px 0 0;
    background: rgba(255,255,255,0.05);
    border-top: 1px solid rgba(255,255,255,0.05);
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .metric {
    padding: 14px 12px;
    background: #111318;
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    cursor: default;
    transition: background 0.2s;
  }
  .metric:hover { background: rgba(255,255,255,0.025); }
  .metric-icon { font-size: 18px; }
  .metric-val  {
    font-size: 22px; font-weight: 800; color: #f0f0f0;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.5px;
    line-height: 1;
  }
  .metric-val.accent { color: #ff8040; }
  .metric-val.blue   { color: #52a8ff; }
  .metric-val.green  { color: #00dc64; }
  .metric-label { font-size: 10px; color: #444; letter-spacing: 0.08em; text-transform: uppercase; text-align: center; }

  /* ── Graphs ── */
  .graphs { padding: 16px 20px 20px; }
  .graph-title {
    font-size: 11px; color: #444; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 10px;
    display: flex; align-items: center; gap: 8px;
  }
  .graph-title::after {
    content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.05);
  }

  /* Temperature bar chart */
  .temp-chart { display: flex; align-items: flex-end; gap: 3px; height: 60px; margin-bottom: 4px; }
  .bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; height: 100%; justify-content: flex-end; }
  .bar {
    width: 100%; border-radius: 3px 3px 0 0;
    min-height: 3px;
    transition: height 0.8s cubic-bezier(.4,0,.2,1);
    position: relative;
    overflow: visible;
  }
  .bar-tip {
    position: absolute;
    top: -16px; left: 50%; transform: translateX(-50%);
    font-size: 8px; color: #666;
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
  }
  .bar-lbl { font-size: 9px; color: #333; font-family: 'JetBrains Mono', monospace; }

  /* Shower donut */
  .donut-row { display: flex; align-items: center; gap: 20px; margin-top: 16px; }
  .donut-wrap { position: relative; width: 80px; height: 80px; flex-shrink: 0; }
  .donut-wrap svg { width: 80px; height: 80px; }
  .donut-center {
    position: absolute; inset: 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    pointer-events: none;
  }
  .donut-big   { font-size: 18px; font-weight: 800; color: #f0f0f0; font-family: 'JetBrains Mono', monospace; line-height: 1; }
  .donut-small { font-size: 9px; color: #444; letter-spacing: 0.06em; }
  .donut-info { flex: 1; }
  .donut-row-item { display: flex; justify-content: space-between; font-size: 12px; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
  .donut-row-item:last-child { border: none; }
  .donut-key { color: #666; }
  .donut-v   { color: #e0e0e0; font-weight: 600; font-family: 'JetBrains Mono', monospace; }

  /* ── Footer: mode + legionella ── */
  .footer {
    padding: 12px 20px;
    border-top: 1px solid rgba(255,255,255,0.05);
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .chip {
    padding: 4px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
    display: flex; align-items: center; gap: 5px;
    letter-spacing: 0.04em;
  }
  .chip-mode-boost { background: rgba(255,100,40,0.12); border: 1px solid rgba(255,100,40,0.3); color: #ff6428; }
  .chip-mode-green { background: rgba(0,200,100,0.1); border: 1px solid rgba(0,200,100,0.25); color: #00c878; }
  .chip-mode-off   { background: rgba(120,120,120,0.1); border: 1px solid rgba(120,120,120,0.2); color: #666; }
  .chip-leg-ok     { background: rgba(0,180,255,0.08); border: 1px solid rgba(0,180,255,0.2); color: #00b4ff; }
  .chip-leg-warn   { background: rgba(255,200,0,0.1); border: 1px solid rgba(255,200,0,0.3); color: #ffc800; }
  .chip-power      { background: rgba(255,214,0,0.08); border: 1px solid rgba(255,214,0,0.2); color: #ffd600; }
  .chip-cop        { background: rgba(100,200,255,0.08); border: 1px solid rgba(100,200,255,0.2); color: #64c8ff; }
  .chip-verify     { background: rgba(255,160,0,0.1); border: 1px solid rgba(255,160,0,0.3); color: #ffa000; animation: pulse 2s infinite; }
  @keyframes pulse {
    0%,100% { opacity: 1; } 50% { opacity: 0.5; }
  }

  /* ── Empty state ── */
  .empty { padding: 40px 20px; text-align: center; color: #333; font-size: 13px; }
  .empty-icon { font-size: 36px; display: block; margin-bottom: 12px; }

  /* ── Spinner ── */
  .spinner {
    display: inline-block; width: 20px; height: 20px;
    border: 2px solid rgba(255,255,255,0.1);
    border-top-color: #ff8040;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Multi-boiler tabs ── */
  .tabs { display: flex; gap: 1px; background: rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.06); }
  .tab {
    flex: 1; padding: 9px 4px; text-align: center;
    font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
    color: #444; cursor: pointer; border: none; background: #111318;
    transition: all 0.15s;
  }
  .tab:hover { color: #888; }
  .tab.active { color: #ff8040; border-bottom: 2px solid #ff8040; background: rgba(255,128,64,0.04); }

  /* ── Dual graph: temp + power ── */
  .dual-graph {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .graph-panel { }
  .power-bar {
    width: 100%; border-radius: 3px 3px 0 0;
    min-height: 3px;
    transition: height 0.8s cubic-bezier(.4,0,.2,1);
  }

  /* ── Beslissingslog ── */
  .decisions {
    padding: 14px 20px 20px;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .decisions-title {
    font-size: 11px; color: #444; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 10px;
    display: flex; align-items: center; gap: 8px;
  }
  .decisions-title::after {
    content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.05);
  }
  .dec-list { display: flex; flex-direction: column; gap: 5px; }
  .dec-row {
    display: flex; align-items: baseline; gap: 8px;
    padding: 5px 8px; border-radius: 8px;
    background: rgba(255,255,255,0.02);
    font-size: 12px; line-height: 1.4;
  }
  .dec-row:first-child { background: rgba(255,255,255,0.04); }
  .dec-time { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #555; flex-shrink: 0; }
  .dec-icon { font-size: 12px; flex-shrink: 0; }
  .dec-msg  { color: #888; flex: 1; }
  .dec-cnt  { font-size: 10px; color: #444; font-family: 'JetBrains Mono', monospace; flex-shrink: 0; }
  .dec-empty { font-size: 12px; color: #333; padding: 6px 8px; font-style: italic; }
`;

// ── Helpers ──────────────────────────────────────────────────────────────────

function esc(s) {
  const d = document.createElement('div');
  d.textContent = String(s ?? '');
  return d.innerHTML;
}

/**
 * Bereken beschikbare liters warm water bij een bepaalde douchetemperatuur.
 * Mengverhouding: (T_boiler - T_douche) / (T_douche - T_koud) * V_boiler
 * Maar alleen het deel boven T_douche is bruikbaar.
 */
function calcUsableWater(tempBoiler, tempTarget, tempCold, volumeLiters) {
  if (tempBoiler <= tempTarget) return 0;
  if (tempTarget <= tempCold) return volumeLiters;
  const ratio = (tempBoiler - tempTarget) / (tempTarget - tempCold);
  return Math.round(volumeLiters * (1 + ratio));
}

/**
 * Bereken aantal douches.
 * Elke douche = duur × flow L/min totaalverbruik, gemengd op douchetemperatuur.
 */
function calcShowers(usableLiters, durationMin, flowLperMin) {
  const litersPerShower = durationMin * flowLperMin;
  if (litersPerShower <= 0) return 0;
  return Math.floor(usableLiters / litersPerShower);
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function tempToColor(t) {
  if (t >= 65) return '#ff3020';
  if (t >= 55) return '#ff6428';
  if (t >= 45) return '#ff9030';
  if (t >= 38) return '#ffb830';
  return '#52a8ff';
}

// ── Animating counter ────────────────────────────────────────────────────────
function animateCounter(el, from, to, duration = 800, decimals = 0) {
  const start = performance.now();
  const diff = to - from;
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const ease = 1 - Math.pow(1 - t, 3);
    const val = from + diff * ease;
    el.textContent = val.toFixed(decimals);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── SVG donut chart ──────────────────────────────────────────────────────────
function buildDonut(pct, color, bg = 'rgba(255,255,255,0.05)') {
  const r = 30, cx = 40, cy = 40, stroke = 7;
  const circ = 2 * Math.PI * r;
  const dash = circ * clamp(pct, 0, 1);
  return `
    <svg viewBox="0 0 80 80">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${bg}" stroke-width="${stroke}"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
        stroke="${color}" stroke-width="${stroke}"
        stroke-dasharray="${dash} ${circ}"
        stroke-dashoffset="${circ * 0.25}"
        stroke-linecap="round"
        style="transition: stroke-dasharray 1.2s cubic-bezier(.4,0,.2,1)"/>
    </svg>`;
}

// ── Mini bar chart (48h temps) ───────────────────────────────────────────────
function buildTempLine(history /* [{t, v}] */, setpoint, currentVal) {
  const W = 320, H = 60;
  if (!history || !history.length) {
    return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="display:block"><text x="${W/2}" y="${H/2}" text-anchor="middle" fill="#444" font-size="10">Geen history beschikbaar</text></svg>`;
  }
  // Add current value at the end if available
  const pts = currentVal != null ? [...history, {t: 'nu', v: currentVal}] : history;
  const vals = pts.map(h => h.v);
  const max = Math.max(...vals, setpoint + 3);
  const min = Math.max(0, Math.min(...vals) - 3);
  const range = max - min || 1;
  const pad = 4;
  const xs = pts.map((_, i) => pad + (i / Math.max(pts.length - 1, 1)) * (W - pad * 2));
  const ys = pts.map(h => H - pad - ((h.v - min) / range) * (H - pad * 2));
  const spLine = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const spFill = spLine + ` L${xs[xs.length-1].toFixed(1)},${H} L${xs[0].toFixed(1)},${H} Z`;
  // Setpoint line
  const spY = (H - pad - ((setpoint - min) / range) * (H - pad * 2)).toFixed(1);
  const lastX = xs[xs.length - 1], lastY = ys[ys.length - 1];
  const lastCol = tempToColor(pts[pts.length - 1].v);
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="display:block;overflow:visible">
    <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${lastCol}" stop-opacity="0.3"/><stop offset="100%" stop-color="${lastCol}" stop-opacity="0.02"/></linearGradient></defs>
    <path d="${spFill}" fill="url(#tg)"/>
    <line x1="${pad}" y1="${spY}" x2="${W - pad}" y2="${spY}" stroke="rgba(255,200,0,0.3)" stroke-width="1" stroke-dasharray="3,3"/>
    <path d="${spLine}" fill="none" stroke="${lastCol}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3" fill="${lastCol}"/>
    <text x="${lastX.toFixed(1)}" y="${(lastY - 6).toFixed(1)}" text-anchor="middle" fill="${lastCol}" font-size="9" font-weight="600">${pts[pts.length-1].v.toFixed(0)}°</text>
    ${pts.filter((_,i) => i % Math.max(1, Math.floor(pts.length/4)) === 0).map((_,i,arr) => {
      const origI = Math.round(i * pts.length / arr.length);
      return `<text x="${xs[origI].toFixed(1)}" y="${H}" text-anchor="middle" fill="#444" font-size="8">${pts[origI].t}</text>`;
    }).join('')}
  </svg>`;
}

function buildPowerLine(history /* [{t, v}] */, currentVal, maxPower) {
  const W = 320, H = 60;
  if (!history || !history.length) {
    if (currentVal != null && currentVal > 0) {
      // No history yet but we have live value - show single point
      return `<div style="text-align:center;padding:8px;color:#ffd600;font-size:11px">⚡ ${Math.round(currentVal)}W live — grafiek beschikbaar na eerste uur</div>`;
    }
    return `<div style="text-align:center;padding:8px;color:#444;font-size:10px">Wacht op data…</div>`;
  }
  const pts = currentVal != null ? [...history, {t: 'nu', v: currentVal}] : history;
  const vals = pts.map(h => h.v);
  const maxV = Math.max(...vals, maxPower || 100, 1);
  const pad = 4;
  const xs = pts.map((_, i) => pad + (i / Math.max(pts.length - 1, 1)) * (W - pad * 2));
  const ys = pts.map(h => H - pad - (clamp(h.v / maxV, 0, 1)) * (H - pad * 2));
  const spLine = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const spFill = spLine + ` L${xs[xs.length-1].toFixed(1)},${H} L${xs[0].toFixed(1)},${H} Z`;
  const lastV = pts[pts.length - 1].v;
  const lastCol = lastV > 50 ? '#ffd600' : 'rgba(255,255,255,0.2)';
  const lastX = xs[xs.length - 1], lastY = ys[ys.length - 1];
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="display:block;overflow:visible">
    <defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ffd600" stop-opacity="0.25"/><stop offset="100%" stop-color="#ffd600" stop-opacity="0.02"/></linearGradient></defs>
    <path d="${spFill}" fill="url(#pg)"/>
    <path d="${spLine}" fill="none" stroke="#ffd600" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3" fill="${lastCol}"/>
    ${lastV > 0 ? `<text x="${lastX.toFixed(1)}" y="${(lastY - 6).toFixed(1)}" text-anchor="middle" fill="#ffd600" font-size="9" font-weight="600">${Math.round(lastV)}W</text>` : ''}
    ${pts.filter((_,i) => i % Math.max(1, Math.floor(pts.length/4)) === 0).map((_,i,arr) => {
      const origI = Math.round(i * pts.length / arr.length);
      return `<text x="${xs[origI].toFixed(1)}" y="${H}" text-anchor="middle" fill="#444" font-size="8">${pts[origI].t}</text>`;
    }).join('')}
  </svg>`;
}

// ── Decisions log per boiler ──────────────────────────────────────────────────
function buildDecisionsHtml(log, label, entityId) {
  if (!log || !log.length) {
    return `<div class="dec-empty">Nog geen beslissingen gelogd.</div>`;
  }

  const labelLow  = (label || '').toLowerCase();
  const entityLow = (entityId || '').toLowerCase();

  // Filter entries belonging to this boiler
  const mine = log.filter(entry => {
    const msg = (entry[1] || '').toString().toLowerCase();
    return msg.includes(labelLow) || msg.includes(entityLow);
  });

  if (!mine.length) {
    return `<div class="dec-empty">Geen beslissingen gevonden voor ${esc(label)}.</div>`;
  }

  // Deduplicate consecutive identical messages, max 8 unique shown
  const rows = [];
  let lastMsg = '', count = 0;

  for (const entry of mine) {
    const ts  = entry[0] || '';
    const raw = (entry[1] || '').toString()
      .replace('🔌 ', '')
      .replace('hold_on',  'aan gehouden')
      .replace('hold_off', 'uit gehouden')
      .replace('turn_on',  'aangezet')
      .replace('turn_off', 'uitgezet');

    const rawLow = raw.toLowerCase();
    let icon = '💤';
    if (rawLow.includes('aangezet'))    icon = '▶️';
    else if (rawLow.includes('uitgezet')) icon = '⏹️';
    else if (rawLow.includes('aan gehouden')) icon = '🟢';
    else if (rawLow.includes('uit gehouden')) icon = '⚫';

    // Parse time
    let timeStr = '—';
    try {
      const d = new Date(ts);
      if (!isNaN(d)) timeStr = d.toLocaleTimeString('nl-NL', {hour:'2-digit', minute:'2-digit'});
    } catch(_) {}

    // Strip boiler label prefix from message for cleaner display
    const msgClean = raw
      .replace(new RegExp(`boiler ?\\d*:?\\s*`, 'i'), '')
      .replace(new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ':?\\s*', 'i'), '')
      .trim();

    const msgTrunc = msgClean.length > 70 ? msgClean.slice(0, 68) + '…' : msgClean;

    if (msgTrunc === lastMsg) {
      count++;
      if (rows.length) rows[rows.length - 1].count = count;
    } else {
      if (rows.length >= 8) break;
      lastMsg = msgTrunc;
      count = 1;
      rows.push({ timeStr, icon, msg: msgTrunc, count: 1 });
    }
  }

  const html = rows.map(r => `
    <div class="dec-row">
      <span class="dec-time">${r.timeStr}</span>
      <span class="dec-icon">${r.icon}</span>
      <span class="dec-msg">${esc(r.msg)}</span>
      ${r.count > 1 ? `<span class="dec-cnt">${r.count}×</span>` : ''}
    </div>`).join('');

  return `<div class="dec-list">${html}</div>`;
}

function buildTankSVG(fillPct, tempC) {
  const W = 52, H = 90, R = 8;
  const color = tempToColor(tempC);
  const fillH = Math.round((H - 8) * clamp(fillPct, 0, 1));
  const fillY = H - 4 - fillH;
  const wavePath = `M4,${fillY} Q${W/4},${fillY-3} ${W/2},${fillY} Q${W*3/4},${fillY+3} ${W-4},${fillY} L${W-4},${H-4} L4,${H-4} Z`;

  return `
    <svg width="${W}" height="${H + 20}" viewBox="0 0 ${W} ${H + 20}">
      <defs>
        <linearGradient id="tankGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.9"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0.4"/>
        </linearGradient>
        <clipPath id="tankClip">
          <rect x="4" y="4" width="${W-8}" height="${H-8}" rx="${R-2}"/>
        </clipPath>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
          <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <!-- Tank body -->
      <rect x="2" y="2" width="${W-4}" height="${H-4}" rx="${R}"
        fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" stroke-width="1.5"/>
      <!-- Fill -->
      <g clip-path="url(#tankClip)">
        <path d="${wavePath}" fill="url(#tankGrad)" opacity="0.85" filter="url(#glow)"/>
        <!-- Bubble shimmer -->
        <circle cx="${W*0.35}" cy="${fillY + fillH*0.3}" r="2.5"
          fill="${color}" opacity="0.3">
          <animate attributeName="cy" values="${fillY + fillH*0.3};${fillY + fillH*0.15};${fillY + fillH*0.3}"
            dur="3s" repeatCount="indefinite"/>
        </circle>
        <circle cx="${W*0.65}" cy="${fillY + fillH*0.5}" r="1.8"
          fill="${color}" opacity="0.25">
          <animate attributeName="cy" values="${fillY + fillH*0.5};${fillY + fillH*0.2};${fillY + fillH*0.5}"
            dur="4s" repeatCount="indefinite"/>
        </circle>
      </g>
      <!-- Tick marks -->
      ${[0.25,0.5,0.75].map(p => {
        const y = H - 4 - (H-8)*p;
        return `<line x1="${W-8}" y1="${y}" x2="${W-4}" y2="${y}" stroke="rgba(255,255,255,0.12)" stroke-width="1"/>`;
      }).join('')}
      <!-- Temp label inside tank -->
      <text x="${W/2}" y="${H*0.6}" text-anchor="middle"
        font-family="'JetBrains Mono', monospace" font-size="11" font-weight="600"
        fill="${fillPct > 0.3 ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.3)'}">
        ${tempC ? tempC.toFixed(0) + '°' : '—'}
      </text>
      <!-- Pipe at bottom -->
      <rect x="${W/2 - 4}" y="${H-2}" width="8" height="10" rx="2"
        fill="rgba(255,255,255,0.07)" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
      <!-- Heat element glow at bottom when heating -->
    </svg>`;
}

// ── Main Card ─────────────────────────────────────────────────────────────────
class CloudemsBoilerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._prevJson = '';
    this._activeTab = 0;
    this._history = {};        // entity_id → [{t, v}]
    this._historyPower = {};   // entity_id → [{t, v}]
    this._historyLoading = {};
    this._historyLastFetch = 0; // timestamp ms — throttle op 5 min
  }

  setConfig(cfg) {
    this._cfg = {
      tank_liters: 80,
      cold_water_temp: 10,
      shower_temp: 38,
      shower_liters_per_min: 8,
      shower_duration_min: 8,
      title: 'Warm water',
      ...cfg,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states['sensor.cloudems_boiler_status'];
    // Include temp_c en power_w van alle boilers in de trigger-check —
    // state verandert niet maar attributen wel elke coordinator-cyclus.
    const boilers = st?.attributes?.boilers ?? [];
    // Also watch water_heater entities for setpoint changes
    const vboilerStates = boilers.map(b => {
      const slug = (b.label||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/,'');
      return hass.states[`water_heater.cloudems_boiler_${slug}`]?.attributes?.temperature;
    });
    const json = JSON.stringify([
      st?.last_updated,
      st?.last_changed,
      st?.state,
      boilers.map(b => [b.temp_c, b.current_power_w, b.is_on, b.active_setpoint_c]),
      vboilerStates,
    ]);
    if (json !== this._prevJson) {
      this._prevJson = json;
      this._render();
      // History throttle: max 1x per 5 minuten — recorder API niet elke 10s aanroepen
      const now = Date.now();
      // Eerste load: 30s throttle. Daarna: 5 minuten.
      const throttleMs = this._historyLastFetch === 0 ? 5 * 1000 : 5 * 60 * 1000;
      if (now - this._historyLastFetch > throttleMs) {
        this._historyLastFetch = now;
        this._fetchHistory();
      }
    }
  }

  // ── Fetch temperature history from HA recorder ──────────────────────────
  // ── Fetch temperature + power history from HA recorder ──────────────────
  async _fetchHistory() {
    if (!this._hass) return;
    const st = this._hass.states['sensor.cloudems_boiler_status'];
    if (!st) return;
    const boilers = st.attributes?.boilers ?? [];
    for (const b of boilers) {
      const eid = b.entity_id;
      if (this._historyLoading[eid]) continue;
      this._historyLoading[eid] = true;
      try {
        const end   = new Date();
        const start = new Date(end - 4 * 3600 * 1000); // laatste 4 uur
        // Sensoren gebruiken label-slug (bijv. "boiler_1"), niet entity_id-slug ("ariston")
        const labelSlugH = (b.label || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
        const eidSlugH   = eid.split('.').pop().replace(/-/g, '_');
        // Kies de slug waarvoor de sensor entity daadwerkelijk bestaat
        const tempEidL  = `sensor.cloudems_boiler_${labelSlugH}_temp`;
        const tempEidE  = `sensor.cloudems_boiler_${eidSlugH}_temp`;
        const tempEid   = this._hass.states[tempEidL] ? tempEidL : tempEidE;
        const powerEidL = `sensor.cloudems_boiler_${labelSlugH}_power`;
        const powerEidE = `sensor.cloudems_boiler_${eidSlugH}_power`;
        const powerEid  = this._hass.states[powerEidL] ? powerEidL : powerEidE;
        const eids = `${tempEid},${powerEid}`;
        const url  = `history/period/${start.toISOString()}?filter_entity_id=${eids}&minimal_response=true&no_attributes=true&end_time=${end.toISOString()}`;
        const resp = await this._hass.callApi('GET', url);

        const parseSeries = (arr) => {
          if (!arr || !arr.length) return [];
          const raw  = arr.filter(s => s.state && !isNaN(parseFloat(s.state)));
          const step = Math.max(1, Math.floor(raw.length / 24));
          return raw.filter((_, i) => i % step === 0).slice(-24).map(s => ({
            t: new Date(s.last_changed).getHours() + ':' +
               String(new Date(s.last_changed).getMinutes()).padStart(2,'0'),
            v: parseFloat(s.state)
          }));
        };

        if (resp && Array.isArray(resp)) {
          this._historyPower = this._historyPower || {};
          for (const series of resp) {
            if (!series || !series.length) continue;
            const firstEid = series[0]?.entity_id || '';
            if (firstEid.endsWith('_temp')) {
              this._history[eid] = parseSeries(series);
            } else if (firstEid.endsWith('_power') || firstEid === powerEid) {
              this._historyPower[eid] = parseSeries(series);
            }
          }
          this._render();
        }
      } catch (_) {}
      this._historyLoading[eid] = false;
    }
  }

  _renderWarmtebron(hass) {
    const st = hass.states["sensor.cloudems_goedkoopste_warmtebron"];
    if (!st) return "";
    const state   = st.state;                          // "gas" | "elektriciteit" | "gelijk"
    const elec    = st.attributes?.elec_price_kwh;
    const gasCost = st.attributes?.gas_per_kwh_heat;
    const elecB   = st.attributes?.elec_boiler_per_kwh_heat;
    const rec     = st.attributes?.recommendation || "";
    if (!gasCost && !elecB) return "";

    const icon  = state === "gas" ? "🔥" : state === "elektriciteit" ? "⚡" : "≈";
    const color = state === "gas" ? "#ff8040" : state === "elektriciteit" ? "#4caf50" : "#ffd600";
    const label = state === "gas" ? "Gas goedkoper" : state === "elektriciteit" ? "Elektriciteit goedkoper" : "Gelijk";

    const fmtC = v => v != null ? (v * 100).toFixed(1) + " ct" : "—";

    return `
      <div style="margin:6px 0 4px;padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:10px;border:1px solid rgba(255,255,255,0.06)">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
          <span style="font-size:13px">${icon}</span>
          <span style="font-size:11px;font-weight:700;color:${color}">${label}</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr auto auto;gap:2px 10px;font-size:11px;color:rgba(255,255,255,0.6)">
          <span>🔥 Gas (CV)</span>
          <span style="text-align:right;color:${state==="gas"?"#ff8040":"inherit"}">${fmtC(gasCost)}/kWh warmte</span>
          <span style="color:#4caf50">${state==="gas"?"✅":""}</span>
          <span>⚡ Elektrisch</span>
          <span style="text-align:right;color:${state==="elektriciteit"?"#4caf50":"inherit"}">${fmtC(elecB)}/kWh warmte</span>
          <span style="color:#4caf50">${state==="elektriciteit"?"✅":""}</span>
        </div>
        ${rec ? `<div style="font-size:10px;color:rgba(255,255,255,0.4);margin-top:5px;line-height:1.4">${this._esc ? this._esc(rec) : rec}</div>` : ""}
      </div>`;
  }

  _render() {
    const sh = this.shadowRoot;
    if (!sh) return;
    const hass = this._hass;
    const cfg = this._cfg ?? {};

    if (!hass) {
      sh.innerHTML = `<style>${S}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
      return;
    }

    const statusSensor = hass.states['sensor.cloudems_boiler_status'];
    if (!statusSensor || statusSensor.state === 'unavailable') {
      sh.innerHTML = `<style>${S}</style>
        <div class="card"><div class="empty">
          <span class="empty-icon">🚿</span>
          CloudEMS warm water sensor niet beschikbaar.
        </div></div>`;
      return;
    }

    const allBoilers = statusSensor.attributes?.boilers ?? [];
    if (!allBoilers.length) {
      sh.innerHTML = `<style>${S}</style>
        <div class="card"><div class="empty">
          <span class="empty-icon">🚿</span>
          Geen boilers geconfigureerd.<br>
          Voeg boilers toe via <strong>Instellingen → CloudEMS</strong>.
        </div></div>`;
      return;
    }

    const idx = Math.min(this._activeTab, allBoilers.length - 1);
    const b = allBoilers[idx];

    // ── Calculations ────────────────────────────────────────────────────────
    // Fallback: als temp_c null is (bijv. Ariston 429), lees van recorder sensor
    const labelSlugT = (b.label||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/,'');
    const recorderTempSt = hass.states[`sensor.cloudems_boiler_${labelSlugT}_temp`];
    const recorderTemp = recorderTempSt ? parseFloat(recorderTempSt.state) : null;
    const tempC    = b.temp_c ?? (isNaN(recorderTemp) ? null : recorderTemp);
    // v4.6.93: lees setpoint van de virtuele thermostaat entity.
    // De virtual boiler gebruikt label-slug (bijv. "boiler_1"), NIET entity_id-slug.
    const labelSlug  = (b.label || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '');
    const eidSlug    = (b.entity_id || '').split('.').pop().replace(/-/g, '_');
    // Probeer beide slugvarianten (label eerst, dan entity_id als fallback)
    const vboilerSt  = hass.states[`water_heater.cloudems_boiler_${labelSlug}`]
                    ?? hass.states[`water_heater.cloudems_boiler_${eidSlug}`];
    const vbSetpoint = vboilerSt?.attributes?.temperature ?? null;
    const setpoint   = vbSetpoint ?? b.active_setpoint_c ?? b.setpoint_c ?? 60;
    const maxSp    = b.hardware_max_c || b.max_setpoint_boost_c || Math.max(b.max_setpoint_green_c||0, b.setpoint_c||60, 75);
    // v4.6.170: gebruik recorder sensor als current_power_w niet beschikbaar is
    // NOOIT b.power_w (nominaal vermogen) gebruiken — dat toont bijv. 2500W als de boiler uit staat
    const recorderPowerSt = hass.states[`sensor.cloudems_boiler_${labelSlugT}_power`];
    const recorderPower = recorderPowerSt && recorderPowerSt.state !== 'unavailable' && recorderPowerSt.state !== 'unknown'
      ? parseFloat(recorderPowerSt.state) : null;
    const powerW = b.current_power_w ?? (isNaN(recorderPower) ? null : recorderPower) ?? 0;
    const mode     = (b.actual_mode || '').toLowerCase();
    const isOn     = b.is_on ?? false;
    const isHeating = b.is_heating ?? (powerW > 50);
    const cop      = b.cop_at_current_temp;
    const legDays  = b.legionella_days;
    const brand    = b.brand_label || b.brand || '';
    const btype    = b.boiler_type || 'resistive';
    const label    = b.label || 'Boiler';
    const stall    = b.stall_active ?? false;

    const tankL    = cfg.tank_liters;
    const coldT    = cfg.cold_water_temp;
    const showerT  = cfg.shower_temp;
    const flowLpm  = cfg.shower_liters_per_min;
    const durMin   = cfg.shower_duration_min;

    const safeTemp = tempC ?? setpoint;
    const usableL  = calcUsableWater(safeTemp, showerT, coldT, tankL);
    const showers  = calcShowers(usableL, durMin, flowLpm);
    const fillPct  = tempC != null ? clamp((tempC - coldT) / (maxSp - coldT), 0.05, 1) : 0.5;
    const setpointPct = clamp((setpoint - coldT) / (maxSp - coldT), 0, 1);
    const usablePct = clamp(usableL / (tankL * 2), 0, 1); // max ~2× vol

    // Mode badge
    let badgeClass = 'badge-off', badgeLabel = '⚫ UIT';
    if (isHeating && mode.includes('boost')) { badgeClass = 'badge-boost'; badgeLabel = '🔥 BOOST'; }
    else if (isOn && mode.includes('green')) { badgeClass = 'badge-green'; badgeLabel = '🌿 GREEN'; }
    else if (isOn) { badgeClass = 'badge-on'; badgeLabel = '🟢 AAN'; }

    // Chip for mode
    let modeChipClass = 'chip-mode-off', modeIcon = '💤', modeText = mode || 'uit';
    if (mode.includes('boost')) { modeChipClass = 'chip-mode-boost'; modeIcon = '🔥'; modeText = 'BOOST'; }
    else if (mode.includes('green') || mode.includes('eco')) { modeChipClass = 'chip-mode-green'; modeIcon = '🌿'; modeText = mode.toUpperCase(); }
    else if (isOn) { modeChipClass = 'chip-mode-green'; modeIcon = '🔥'; modeText = 'Aan'; }

    // Setpoint bar color
    const spColor = tempToColor(setpoint);

    // History
    const hist      = this._history[b.entity_id];
    const histPower = (this._historyPower || {})[b.entity_id];

    // Tabs HTML (multi-boiler)
    const tabsHtml = allBoilers.length > 1 ? `
      <div class="tabs">
        ${allBoilers.map((bx, i) => `
          <button class="tab ${i === idx ? 'active' : ''}" data-tab="${i}">
            ${esc(bx.label || `Boiler ${i+1}`)}
          </button>`).join('')}
      </div>` : '';

    sh.innerHTML = `
      <style>${S}</style>
      <div class="card">
        <div class="inner">
          ${tabsHtml}

          <div class="hdr">
            <div class="hdr-icon">🚿</div>
            <div>
              <div class="hdr-title">${esc(cfg.title)} · ${esc(label)}</div>
              <div class="hdr-sub">${esc(brand) || btype} · ${tankL}L tank</div>
            </div>
            <span class="hdr-badge ${badgeClass}">${badgeLabel}</span>
          </div>

          <div class="hero">
            <div class="tank-wrap">
              ${buildTankSVG(fillPct, tempC)}
              <span class="tank-label">${tankL}L</span>
            </div>
            <div class="stats-col">
              <div>
                <div class="temp-label">Huidige temperatuur</div>
                <div class="temp-big">
                  <span class="temp-val" id="tempVal">${tempC != null ? tempC.toFixed(1) : '—'}</span>
                  ${tempC != null ? '<span class="temp-unit">°C</span>' : ''}
                </div>
              </div>

              <div class="setpoint-row">
                <span class="sp-icon">🎯</span>
                <div style="flex:1">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="sp-text">Setpoint</span>
                    <span class="sp-val">${setpoint.toFixed(0)}°C</span>
                  </div>
                  <div class="sp-bar-wrap">
                    <div class="sp-bar" style="width:${setpointPct*100}%;background:${spColor}"></div>
                  </div>
                </div>
              </div>

              <div class="setpoint-row" style="border-color:rgba(255,180,0,0.2)">
                <span class="sp-icon">⚡</span>
                <div style="flex:1">
                  <div style="display:flex;justify-content:space-between">
                    <span class="sp-text">Vermogen</span>
                    <span class="sp-val" style="color:${powerW > 50 ? '#ffd600' : 'rgba(255,255,255,0.4)'}">${powerW.toFixed(0)} W</span>
                  </div>
                  <div class="sp-bar-wrap">
                    <div class="sp-bar" style="width:${powerW > 50 ? clamp(powerW/Math.max(b.power_w||1500,powerW,1)*100,2,100) : 0}%;background:linear-gradient(90deg,#ff8040,#ffd600)"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          ${this._renderWarmtebron(hass)}

          <div class="metrics">
            <div class="metric">
              <span class="metric-icon">🚿</span>
              <span class="metric-val accent" id="showerVal">${showers}</span>
              <span class="metric-label">Douches</span>
            </div>
            <div class="metric">
              <span class="metric-icon">💧</span>
              <span class="metric-val blue" id="litersVal">${usableL}</span>
              <span class="metric-label">Liter @ ${showerT}°C</span>
            </div>
            <div class="metric">
              <span class="metric-icon">${cop ? '🌡️' : '⏱️'}</span>
              <span class="metric-val green">${cop ? cop.toFixed(1) : (tempC != null ? (tempC >= setpoint - 2 ? '100' : Math.round((tempC - coldT) / (setpoint - coldT) * 100)) : '—')}</span>
              <span class="metric-label">${cop ? 'COP' : 'Geladen %'}</span>
            </div>
          </div>

          <div class="graphs">
            <div class="dual-graph">
              <div class="graph-panel">
                <div class="graph-title">🌡️ Temperatuur (4u)</div>
                ${buildTempLine(hist, setpoint, b.temp_c ?? null)}
              </div>
              <div class="graph-panel">
                <div class="graph-title">⚡ Vermogen (4u)</div>
                ${buildPowerLine(histPower, powerW, b.power_w || Math.max(powerW, 1500))}
              </div>
            </div>

            <div class="donut-row" style="margin-top:20px">
              <div>
                <div class="graph-title" style="margin-bottom:12px">💧 Warm water budget</div>
                <div class="donut-row">
                  <div class="donut-wrap">
                    ${buildDonut(usablePct, tempToColor(safeTemp))}
                    <div class="donut-center">
                      <span class="donut-big" id="donutVal">${usableL}</span>
                      <span class="donut-small">liter</span>
                    </div>
                  </div>
                  <div class="donut-info">
                    <div class="donut-row-item">
                      <span class="donut-key">🚿 Per douche</span>
                      <span class="donut-v">${(durMin * flowLpm).toFixed(0)} L</span>
                    </div>
                    <div class="donut-row-item">
                      <span class="donut-key">⏱️ Douchetijd</span>
                      <span class="donut-v">${durMin} min</span>
                    </div>
                    <div class="donut-row-item">
                      <span class="donut-key">🌡️ Koud water</span>
                      <span class="donut-v">${coldT}°C</span>
                    </div>
                    <div class="donut-row-item">
                      <span class="donut-key">💧 Mengtemperatuur</span>
                      <span class="donut-v">${showerT}°C</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="footer">
            <span class="chip ${modeChipClass}">${modeIcon} ${esc(modeText)}</span>
            ${powerW > 50 ? `<span class="chip chip-power">⚡ ${powerW.toFixed(0)}W</span>` : ''}
            ${cop ? `<span class="chip chip-cop">COP ${cop.toFixed(2)}</span>` : ''}
            ${legDays != null ? `<span class="chip ${legDays < 5 ? 'chip-leg-ok' : 'chip-leg-warn'}">🦠 Leg. ${legDays.toFixed(0)}d geleden</span>` : ''}
            ${stall ? `<span class="chip chip-verify">⚠️ Stall</span>` : ''}
          </div>

          <div class="decisions">
            <div class="decisions-title">📋 Beslissingen</div>
            ${buildDecisionsHtml(statusSensor.attributes?.log ?? [], label, b.entity_id)}
          </div>
        </div>
      </div>`;

    // Animate counters from previous value (not 0) to avoid visual reset on each update
    requestAnimationFrame(() => {
      const tv = sh.getElementById('tempVal');
      if (tv && tempC != null) {
        const prev = parseFloat(tv.textContent) || tempC;
        if (Math.abs(prev - tempC) > 0.05) animateCounter(tv, prev, tempC, 600, 1);
        else tv.textContent = tempC.toFixed(1);
      }
      const sv = sh.getElementById('showerVal');
      if (sv) {
        const prev = parseInt(sv.textContent) || 0;
        if (prev !== showers) animateCounter(sv, prev, showers, 500, 0);
      }
      const lv = sh.getElementById('litersVal');
      if (lv) {
        const prev = parseInt(lv.textContent) || 0;
        if (prev !== usableL) animateCounter(lv, prev, usableL, 500, 0);
      }
      const dv = sh.getElementById('donutVal');
      if (dv) {
        const prev = parseInt(dv.textContent) || 0;
        if (prev !== usableL) animateCounter(dv, prev, usableL, 500, 0);
      }
    });

    // Tab click handlers
    sh.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = parseInt(btn.dataset.tab);
        this._render();
      });
    });
  }

  static getStubConfig() {
    return {
      tank_liters: 80,
      cold_water_temp: 10,
      shower_temp: 38,
      shower_liters_per_min: 8,
      shower_duration_min: 8,
    };
  }

  getCardSize() { return 8; }

  static getConfigElement(){ return document.createElement("cloudems-boiler-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-boiler-card"}; }
}



class CloudemsBoilerCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:"open"}); }
  setConfig(c){ this._cfg={...c}; this._render(); }
  _fire(){
    this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true}));
  }
  _render(){
    const cfg=this._cfg||{};
    this.shadowRoot.innerHTML=`
<style>
.wrap{padding:8px;}
.row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.row:last-child{border-bottom:none;}
.lbl{font-size:12px;color:var(--secondary-text-color,#aaa);flex:1;margin-right:8px;}
input[type=text],input[type=number]{background:var(--card-background-color,#1c1c1c);border:1px solid var(--divider-color,rgba(255,255,255,.15));border-radius:6px;color:var(--primary-text-color,#fff);padding:5px 8px;font-size:13px;width:150px;box-sizing:border-box;}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color,#03a9f4);cursor:pointer;}
</style>
<div class="wrap">
        <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"Warm water"}"></div>
        <div class="row"><label class="lbl">Tank inhoud (L)</label><input type="number" name="tank_liters" value="${cfg.tank_liters??80}"></div>
        <div class="row"><label class="lbl">Koud water temp (°C)</label><input type="number" name="cold_water_temp" value="${cfg.cold_water_temp??10}"></div>
        <div class="row"><label class="lbl">Douchetemperatuur (°C)</label><input type="number" name="shower_temp" value="${cfg.shower_temp??38}"></div>
        <div class="row"><label class="lbl">Liter/min douche</label><input type="number" name="shower_liters_per_min" value="${cfg.shower_liters_per_min??8}"></div>
        <div class="row"><label class="lbl">Douchetijd (min)</label><input type="number" name="shower_duration_min" value="${cfg.shower_duration_min??8}"></div>
</div>`;
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{
        const n=el.name, nc={...this._cfg};
        if(n==="title") nc[n]=el.value;
        if(n==="tank_liters") nc[n]=parseFloat(el.value)||80;
        if(n==="cold_water_temp") nc[n]=parseFloat(el.value)||10;
        if(n==="shower_temp") nc[n]=parseFloat(el.value)||38;
        if(n==="shower_liters_per_min") nc[n]=parseFloat(el.value)||8;
        if(n==="shower_duration_min") nc[n]=parseFloat(el.value)||8;
        this._cfg=nc; this._fire();
      });
    });
  }
}
customElements.define("cloudems-boiler-card-editor", CloudemsBoilerCardEditor);
customElements.define('cloudems-boiler-card', CloudemsBoilerCard);
window.customCards = window.customCards ?? [];
window.customCards.push({
  type: 'cloudems-boiler-card',
  name: 'CloudEMS Boiler Card',
  description: 'Warm water dashboard — live temp, beschikbare liters, douches & grafieken',
  preview: true,
});
console.info(
  '%c CLOUDEMS-BOILER-CARD %c v' + BOILER_CARD_VERSION + ' ',
  'background:#ff8040;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px',
  'background:#111318;color:#ff8040;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0'
);
