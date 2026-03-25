// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. Unauthorized copying, redistribution, or commercial
// use of this file is strictly prohibited. See LICENSE for full terms.

/**
 * CloudEMS PV Forecast Card  v1.0.0
 * Gecombineerde grafiek: PV forecast + EPEX-prijzen + huidig vermogen
 *
 *   type: custom:cloudems-pv-forecast-card
 *
 * Leest uit:
 *   sensor.cloudems_pv_forecast_today    → attrs.hourly[{hour,forecast_w,low_w,high_w,confidence,solcast_w?}]
 *   sensor.cloudems_pv_forecast_tomorrow → attrs.hourly_tomorrow[...]
 *   sensor.cloudems_energy_epex_today    → attrs.today_prices[{hour,price}], tomorrow_prices
 *   sensor.cloudems_energy_price_current_hour → state = huidige prijs
 *   (optioneel) sensor.cloudems_solar_power   → huidig PV-vermogen
 *
 * Optionele config:
 *   title: "Zonnepanelen"
 *   show_tomorrow: true         (default true)
 *   show_epex: true             (default true — EPEX lijn overlay)
 *   show_confidence: true       (default true — onzekerheidsbanden)
 *   power_sensor: "sensor.mijn_omvormer"   (override live PV sensor)
 */

const PV_CARD_VERSION = "5.3.31";

// ── Stijlen ───────────────────────────────────────────────────────────────────
const PV_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

  :host {
    --pv-bg:        #181f18;
    --pv-surface:   #1e271e;
    --pv-border:    rgba(255,255,255,0.07);
    --pv-green:     #4ade80;
    --pv-green-dim: rgba(74,222,128,0.12);
    --pv-yellow:    #facc15;
    --pv-amber:     #fb923c;
    --pv-sky:       #38bdf8;
    --pv-muted:     #4b5563;
    --pv-text:      #e2e8f0;
    --pv-subtext:   #9ca3af;
    --pv-mono:      'JetBrains Mono', monospace;
    --pv-sans:      'Barlow', sans-serif;
    --pv-r:         14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .card {
    background: var(--pv-bg);
    border-radius: var(--pv-r);
    border: 1px solid var(--pv-border);
    overflow: hidden;
    font-family: var(--pv-sans);
    transition: border-color .3s, transform .2s, box-shadow .3s;
  }
  .card:hover {
    border-color: rgba(74,222,128,.3);
    box-shadow: 0 8px 32px rgba(0,0,0,.5), 0 0 24px rgba(74,222,128,.05);
    transform: translateY(-2px);
  }

  /* ── Header ── */
  .hdr {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 18px 12px;
    background: linear-gradient(135deg, var(--pv-green-dim) 0%, transparent 55%);
    border-bottom: 1px solid var(--pv-border);
  }
  .hdr-icon { font-size: 20px; }
  .hdr-texts { flex: 1; }
  .hdr-title { font-size: 14px; font-weight: 700; color: var(--pv-text); }
  .hdr-sub   { font-size: 11px; color: var(--pv-muted); margin-top: 2px; font-weight: 500; }
  .hdr-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
  .hdr-kwh {
    font-family: var(--pv-mono); font-size: 20px; font-weight: 600;
    color: var(--pv-green); line-height: 1;
  }
  .hdr-kwh-label { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--pv-muted); }

  /* ── Day tabs ── */
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--pv-border);
  }
  .tab {
    flex: 1; padding: 8px 16px; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .08em;
    color: var(--pv-muted); cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color .2s, border-color .2s;
    text-align: center;
    background: none; border-top: none; border-left: none; border-right: none;
  }
  .tab.active { color: var(--pv-green); border-bottom-color: var(--pv-green); }
  .tab:hover:not(.active) { color: var(--pv-subtext); }

  /* ── Stats row ── */
  .stats-row {
    display: grid; gap: 1px;
    background: var(--pv-border);
    border-bottom: 1px solid var(--pv-border);
  }
  .stats-row.cols-3 { grid-template-columns: repeat(3, 1fr); }
  .stats-row.cols-4 { grid-template-columns: repeat(4, 1fr); }
  .stat {
    background: var(--pv-bg);
    padding: 10px 14px; text-align: center;
  }
  .stat-val { font-family: var(--pv-mono); font-size: 14px; font-weight: 600; color: var(--pv-text); }
  .stat-key { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--pv-muted); margin-top: 3px; }
  .stat-val.green  { color: var(--pv-green); }
  .stat-val.yellow { color: var(--pv-yellow); }
  .stat-val.sky    { color: var(--pv-sky); }

  /* ── Chart ── */
  .chart-wrap { padding: 16px 18px 8px; position: relative; }
  canvas { display: block; width: 100%; }

  /* ── Legend ── */
  .legend {
    display: flex; gap: 14px; flex-wrap: wrap;
    padding: 0 18px 14px;
  }
  .leg-item {
    display: flex; align-items: center; gap: 5px;
    font-size: 10.5px; color: var(--pv-subtext); font-weight: 500;
  }
  .leg-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
  .leg-line { width: 16px; height: 2px; flex-shrink: 0; border-radius: 1px; }

  /* ── Current hour highlight ── */
  .now-banner {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 18px;
    background: rgba(74,222,128,.06);
    border-top: 1px solid rgba(74,222,128,.12);
    font-size: 12px; color: var(--pv-subtext);
  }
  .now-banner .now-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--pv-green); box-shadow: 0 0 8px var(--pv-green); flex-shrink: 0; }
  .now-banner .now-val { font-family: var(--pv-mono); color: var(--pv-green); font-weight: 600; }
  .now-banner .now-sep { color: var(--pv-muted); }
  .now-banner .now-price { font-family: var(--pv-mono); color: var(--pv-yellow); font-weight: 600; }

  /* ── Source badge ── */
  .source-badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 9.5px; font-weight: 600; padding: 2px 7px;
    border-radius: 4px; letter-spacing: .04em;
  }
  .src-solcast { background: rgba(56,189,248,.1); color: var(--pv-sky); border: 1px solid rgba(56,189,248,.2); }
  .src-stat    { background: rgba(74,222,128,.1); color: var(--pv-green); border: 1px solid rgba(74,222,128,.2); }

  .empty { text-align: center; padding: 32px; color: var(--pv-muted); font-size: 12px; line-height: 1.7; }
  .spinner { width: 16px; height: 16px; border: 2px solid rgba(74,222,128,.15); border-top-color: var(--pv-green); border-radius: 50%; animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

// ── Helpers ───────────────────────────────────────────────────────────────────
const esc = s => String(s ?? "—").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const fmtKwh = w => w != null ? (w / 1000).toFixed(2) : "—";
const fmtW   = w => w != null ? Math.round(w) + " W" : "—";
const fmtCt  = p => p != null ? (p * 100).toFixed(1) + " ct" : "—";

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Card class ────────────────────────────────────────────────────────────────
class CloudemsPvForecastCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeDay = "today";
    this._prevJson  = "";
    this._cfg       = {};
  }

  setConfig(cfg) {
    this._cfg = {
      title:            cfg.title ?? "Zonnepanelen",
      show_tomorrow:    cfg.show_tomorrow    !== false,
      show_epex:        cfg.show_epex        !== false,
      show_confidence:  cfg.show_confidence  !== false,
      power_sensor:     cfg.power_sensor     ?? null,
      ...cfg,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const keys = [
      "sensor.cloudems_pv_forecast_today",
      "sensor.cloudems_pv_forecast_tomorrow",
      "sensor.cloudems_energy_epex_today",
      "sensor.cloudems_energy_price_current_hour",
      this._cfg.power_sensor,
    ].filter(Boolean);
    const json = JSON.stringify(keys.map(k => hass.states[k]?.last_changed));
    if (json !== this._prevJson) { this._prevJson = json; this._render(); }
  }

  _render() {
    const sh  = this.shadowRoot;
    if (!sh) return;
    const cfg = this._cfg;

    if (!this._hass) {
      sh.innerHTML = `<style>${PV_STYLES}</style><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
      return;
    }

    const hass      = this._hass;
    const todaySensor    = hass.states["sensor.cloudems_pv_forecast_today"];
    const tomorrowSensor = hass.states["sensor.cloudems_pv_forecast_tomorrow"];
    const epexSensor     = hass.states["sensor.cloudems_energy_epex_today"];
    const priceSensor    = hass.states["sensor.cloudems_energy_price_current_hour"];
    const powerSensor    = cfg.power_sensor ? hass.states[cfg.power_sensor] : null;

    const todayKwh    = parseFloat(todaySensor?.state ?? 0) || 0;
    const tomorrowKwh = parseFloat(tomorrowSensor?.state ?? 0) || 0;
    const hourlyToday    = todaySensor?.attributes?.hourly ?? [];
    const hourlyTomorrow = tomorrowSensor?.attributes?.hourly_tomorrow ?? [];
    const epexToday      = epexSensor?.attributes?.today_prices ?? [];
    const epexTomorrow   = epexSensor?.attributes?.tomorrow_prices ?? [];
    const currentPrice   = parseFloat(priceSensor?.state ?? 0) || null;
    const liveW          = powerSensor ? (parseFloat(powerSensor.state) || 0) : null;

    const nowH      = new Date().getHours();
    const hourlyActive = this._activeDay === "today" ? hourlyToday : hourlyTomorrow;
    const epexActive   = this._activeDay === "today" ? epexToday   : epexTomorrow;

    // Stats
    const peakH   = hourlyActive.reduce((m, h) => h.forecast_w > (m?.forecast_w ?? 0) ? h : m, null);
    const avgConf = hourlyActive.length ? Math.round(hourlyActive.reduce((s,h) => s + (h.confidence ?? 0), 0) / hourlyActive.length * 100) : 0;
    const hasSolcast = hourlyActive.some(h => h.solcast_w != null);
    const source     = hasSolcast ? "solcast+statistical" : (todaySensor?.attributes?.source ?? "statistical");
    const srcBadge   = hasSolcast
      ? `<span class="source-badge src-solcast">☀️ Solcast + eigen</span>`
      : `<span class="source-badge src-stat">📊 Statistisch</span>`;

    // Prijs nu
    const nowForecast = hourlyToday.find(h => h.hour === nowH);
    const nowBanner = (liveW != null || nowForecast) ? `
      <div class="now-banner">
        <span class="now-dot"></span>
        <span>Nu:</span>
        <span class="now-val">${liveW != null ? Math.round(liveW) + " W" : (nowForecast ? Math.round(nowForecast.forecast_w) + " W (voorspeld)" : "—")}</span>
        ${currentPrice != null ? `<span class="now-sep">·</span><span class="now-price">${(currentPrice*100).toFixed(1)} ct/kWh EPEX</span>` : ""}
      </div>` : "";

    // Tabs
    const tabsHtml = cfg.show_tomorrow ? `
      <div class="tabs">
        <button class="tab ${this._activeDay === "today" ? "active" : ""}" data-day="today">Vandaag</button>
        <button class="tab ${this._activeDay === "tomorrow" ? "active" : ""}" data-day="tomorrow">Morgen</button>
      </div>` : "";

    // Stats row
    const statCols = cfg.show_epex ? "cols-4" : "cols-3";
    const activeKwh = this._activeDay === "today" ? todayKwh : tomorrowKwh;
    const statsHtml = `
      <div class="stats-row ${statCols}">
        <div class="stat"><div class="stat-val green">${activeKwh.toFixed(2)}</div><div class="stat-key">kWh ${this._activeDay === "today" ? "vandaag" : "morgen"}</div></div>
        <div class="stat"><div class="stat-val yellow">${peakH ? Math.round(peakH.forecast_w) + " W" : "—"}</div><div class="stat-key">Piek ${peakH ? peakH.hour + ":00" : ""}</div></div>
        <div class="stat"><div class="stat-val">${avgConf}%</div><div class="stat-key">Zekerheid</div></div>
        ${cfg.show_epex && currentPrice != null ? `<div class="stat"><div class="stat-val sky">${(currentPrice*100).toFixed(1)} ct</div><div class="stat-key">EPEX nu</div></div>` : ""}
      </div>`;

    // Legend
    const legendHtml = `
      <div class="legend">
        <div class="leg-item"><div class="leg-dot" style="background:#4ade80"></div> Forecast</div>
        ${cfg.show_confidence ? `<div class="leg-item"><div class="leg-dot" style="background:rgba(74,222,128,.25)"></div> Bandbreedte</div>` : ""}
        ${hasSolcast ? `<div class="leg-item"><div class="leg-dot" style="background:#38bdf8"></div> Solcast</div>` : ""}
        ${cfg.show_epex && epexActive.length ? `<div class="leg-item"><div class="leg-line" style="background:#facc15"></div> EPEX prijs</div>` : ""}
        <div style="flex:1"></div>
        ${srcBadge}
      </div>`;

    sh.innerHTML = `
      <style>${PV_STYLES}</style>
      <div class="card">
        <div class="hdr">
          <span class="hdr-icon">🌤️</span>
          <div class="hdr-texts">
            <div class="hdr-title">${esc(cfg.title)}</div>
            <div class="hdr-sub">Open-Meteo ${hasSolcast ? "+ Solcast" : ""} · zelf-lerend profiel</div>
          </div>
          <div class="hdr-right">
            <span class="hdr-kwh">${todayKwh.toFixed(2)}</span>
            <span class="hdr-kwh-label">kWh vandaag</span>
          </div>
        </div>
        ${tabsHtml}
        ${statsHtml}
        <div class="chart-wrap">
          <canvas id="pvChart" height="180"></canvas>
        </div>
        ${legendHtml}
        ${nowBanner}
      </div>`;

    // ── Tab events ──
    sh.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => {
        this._activeDay = btn.dataset.day;
        this._render();
      });
    });

    // ── Draw chart ──
    requestAnimationFrame(() => this._drawChart(hourlyActive, epexActive, nowH));
  }

  _drawChart(hourly, epex, nowH) {
    const sh     = this.shadowRoot;
    const canvas = sh.getElementById("pvChart");
    if (!canvas || !hourly.length) return;

    const ctx    = canvas.getContext("2d");
    const dpr    = window.devicePixelRatio || 1;
    const W      = canvas.parentElement.clientWidth - 36;
    const H      = 180;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width  = W + "px";
    canvas.style.height = H + "px";
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const cfg      = this._cfg;
    const PADB     = 32;   // bottom voor x-labels
    const PADT     = 8;
    const PADL     = 8;
    const PADR     = cfg.show_epex && epex.length ? 42 : 10;
    const chartH   = H - PADB - PADT;
    const chartW   = W - PADL - PADR;

    // ── Data ranges ──
    const maxW     = Math.max(...hourly.map(h => h.high_w ?? h.forecast_w ?? 0), 1);
    const maxEpex  = epex.length ? Math.max(...epex.map(e => e.price ?? e.price_eur_kwh ?? 0), 0.001) : 0;

    const hourMin  = hourly[0]?.hour ?? 0;
    const hourMax  = hourly[hourly.length - 1]?.hour ?? 23;
    const nHours   = hourMax - hourMin + 1;

    const xScale   = h => PADL + (h - hourMin) / Math.max(nHours - 1, 1) * chartW;
    const yScale   = w => PADT + chartH - (w / maxW) * chartH;
    const yEpex    = p => PADT + chartH - (p / maxEpex) * chartH;

    // ── Background grid ──
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth   = 1;
    [0.25, 0.5, 0.75, 1.0].forEach(frac => {
      const y = PADT + chartH * (1 - frac);
      ctx.beginPath(); ctx.moveTo(PADL, y); ctx.lineTo(PADL + chartW, y); ctx.stroke();
    });

    // ── Confidence band ──
    if (cfg.show_confidence && hourly.some(h => h.low_w != null)) {
      ctx.beginPath();
      hourly.forEach((h, i) => {
        const x = xScale(h.hour), y = yScale(h.high_w ?? h.forecast_w);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      [...hourly].reverse().forEach(h => {
        ctx.lineTo(xScale(h.hour), yScale(h.low_w ?? h.forecast_w));
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(74,222,128,0.10)";
      ctx.fill();
    }

    // ── Solcast band ──
    if (hourly.some(h => h.solcast_w != null)) {
      const scData = hourly.filter(h => h.solcast_w != null);
      if (scData.length >= 2) {
        ctx.beginPath();
        scData.forEach((h, i) => {
          const x = xScale(h.hour), y = yScale(h.solcast_high_w ?? h.solcast_w);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        [...scData].reverse().forEach(h => {
          ctx.lineTo(xScale(h.hour), yScale(h.solcast_low_w ?? h.solcast_w));
        });
        ctx.closePath();
        ctx.fillStyle = "rgba(56,189,248,0.08)";
        ctx.fill();
      }
    }

    // ── Bar chart voor forecast ──
    const barW = chartW / nHours * 0.65;
    hourly.forEach(h => {
      const x  = xScale(h.hour);
      const y  = yScale(h.forecast_w);
      const bh = chartH - (y - PADT);
      const isNow = h.hour === nowH && this._activeDay === "today";

      // Bar gradient
      const grad = ctx.createLinearGradient(0, y, 0, PADT + chartH);
      grad.addColorStop(0,   isNow ? "rgba(74,222,128,0.9)"  : "rgba(74,222,128,0.65)");
      grad.addColorStop(1,   isNow ? "rgba(74,222,128,0.15)" : "rgba(74,222,128,0.08)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(x - barW/2, y, barW, bh, [3, 3, 0, 0]);
      ctx.fill();

      // Solcast dot
      if (h.solcast_w != null) {
        ctx.beginPath();
        ctx.arc(x, yScale(h.solcast_w), 2.5, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(56,189,248,0.85)";
        ctx.fill();
      }

      // Now marker
      if (isNow) {
        ctx.strokeStyle = "rgba(74,222,128,0.5)";
        ctx.lineWidth   = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, PADT);
        ctx.lineTo(x, PADT + chartH);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    });

    // ── EPEX lijn ──
    if (cfg.show_epex && epex.length >= 2 && maxEpex > 0) {
      const epexPoints = epex
        .map(e => ({ hour: e.hour ?? 0, price: e.price ?? e.price_eur_kwh ?? 0 }))
        .filter(e => e.price != null);

      if (epexPoints.length >= 2) {
        ctx.beginPath();
        epexPoints.forEach((e, i) => {
          const x = xScale(e.hour), y = yEpex(e.price);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.strokeStyle = "rgba(250,204,21,0.75)";
        ctx.lineWidth   = 1.5;
        ctx.stroke();

        // Y-as rechts voor EPEX
        ctx.fillStyle   = "rgba(250,204,21,0.6)";
        ctx.font        = `500 9px ${this._cfg.sans ?? "Barlow, sans-serif"}`;
        ctx.textAlign   = "left";
        [0, maxEpex / 2, maxEpex].forEach(p => {
          const y = yEpex(p);
          ctx.fillText((p * 100).toFixed(0) + "ct", PADL + chartW + 4, y + 3);
        });
      }
    }

    // ── X-as labels ──
    ctx.fillStyle  = "rgba(156,163,175,0.8)";
    ctx.font       = `500 9.5px var(--pv-mono)`;
    ctx.textAlign  = "center";
    const labelStep = nHours <= 12 ? 2 : 4;
    hourly.forEach(h => {
      if (h.hour % labelStep === 0) {
        ctx.fillText(h.hour + "u", xScale(h.hour), PADT + chartH + 16);
      }
    });

    // ── Y-as labels links ──
    ctx.textAlign  = "left";
    ctx.fillStyle  = "rgba(156,163,175,0.6)";
    ctx.font       = `500 9px var(--pv-mono)`;
    [0.5, 1.0].forEach(frac => {
      const wVal = maxW * frac;
      const y    = yScale(wVal);
      const label = wVal >= 1000 ? (wVal/1000).toFixed(1) + "kW" : Math.round(wVal) + "W";
      ctx.fillText(label, PADL, y - 3);
    });
  }

  static getStubConfig() {
    return { title: "Zonnepanelen", show_tomorrow: true, show_epex: true, show_confidence: true };
  }
  getCardSize() { return 5; }

  static getConfigElement(){ return document.createElement("cloudems-pv-forecast-card-editor"); }
  static getStubConfig(){ return {type:"cloudems-pv-forecast-card"}; }
}



class CloudemsPvForecastCardEditor extends HTMLElement {
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
        <div class="row"><label class="lbl">Titel</label><input type="text" name="title" value="${cfg.title??"Zonnepanelen"}"></div>
        <div class="row"><label class="lbl">Toon morgen forecast</label><input type="checkbox" name="show_tomorrow" ${cfg.show_tomorrow!==false?"checked":""}></div>
        <div class="row"><label class="lbl">Toon EPEX overlay</label><input type="checkbox" name="show_epex" ${cfg.show_epex!==false?"checked":""}></div>
        <div class="row"><label class="lbl">Toon onzekerheidsband</label><input type="checkbox" name="show_confidence" ${cfg.show_confidence!==false?"checked":""}></div>
</div>`;
    this.shadowRoot.querySelectorAll("input").forEach(el=>{
      el.addEventListener("change",()=>{
        const n=el.name, nc={...this._cfg};
        if(n==="title") nc[n]=el.value;
        if(n==="show_tomorrow") nc[n]=el.checked;
        if(n==="show_epex") nc[n]=el.checked;
        if(n==="show_confidence") nc[n]=el.checked;
        this._cfg=nc; this._fire();
      });
    });
  }
}
if (!customElements.get('cloudems-pv-forecast-card-editor')) customElements.define("cloudems-pv-forecast-card-editor", CloudemsPvForecastCardEditor);
if (!customElements.get('cloudems-pv-forecast-card')) customElements.define("cloudems-pv-forecast-card", CloudemsPvForecastCard);
window.customCards = window.customCards ?? [];
window.customCards.push({
  type: "cloudems-pv-forecast-card",
  name: "CloudEMS PV Forecast Card",
  description: "PV forecast grafiek met EPEX overlay, Solcast integratie en onzekerheidsbanden",
  preview: true,
});
console.info(
  `%c CLOUDEMS-PV-FORECAST-CARD %c v${PV_CARD_VERSION} `,
  "background:#4ade80;color:#000;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px",
  "background:#181f18;color:#4ade80;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0"
);
