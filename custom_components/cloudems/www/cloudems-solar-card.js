// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Solar Card  v5.5.53 — herbouwd naar Solcast-stijl met rolling history

const SOL_VERSION = "5.5.63";
const SOL_STYLES = `
  :host {
    --sl-bg:#0c1409;--sl-surface:#121a0e;--sl-border:rgba(255,255,255,0.07);
    --sl-gold:#f0c040;--sl-gold-dim:rgba(240,192,64,0.10);
    --sl-green:#86efac;--sl-green-dim:rgba(134,239,172,0.08);
    --sl-orange:#fb923c;--sl-blue:#60a5fa;
    --sl-muted:#3d5229;--sl-sub:#86a876;--sl-text:#f0fdf4;
    --sl-mono:'JetBrains Mono',monospace;--sl-r:14px;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--sl-bg);border-radius:var(--sl-r);border:1px solid var(--sl-border);overflow:hidden;font-family:system-ui,sans-serif;}
  .hdr{display:flex;align-items:center;gap:10px;padding:14px 18px 12px;border-bottom:1px solid var(--sl-border);background:linear-gradient(135deg,var(--sl-gold-dim) 0%,transparent 60%);}
  .hdr-icon{font-size:20px;}
  .hdr-texts{flex:1;}
  .hdr-title{font-size:13px;font-weight:700;color:var(--sl-text);letter-spacing:.05em;text-transform:uppercase;}
  .hdr-sub{font-size:11px;color:var(--sl-sub);margin-top:2px;}
  .hdr-watt{font-family:var(--sl-mono);font-size:22px;font-weight:700;color:var(--sl-gold);}
  .top-strip{display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid var(--sl-border);}
  .top-box{padding:12px 14px;border-right:1px solid var(--sl-border);text-align:center;}
  .top-box:last-child{border-right:none;}
  .top-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--sl-muted);}
  .top-val{font-family:var(--sl-mono);font-size:17px;font-weight:600;color:var(--sl-text);margin:2px 0;}
  .top-sub{font-size:10px;color:var(--sl-muted);}
  .tab-bar{display:flex;gap:4px;padding:8px 10px 0;background:rgba(0,0,0,.25);border-bottom:1px solid var(--sl-border);}
  .tab-btn{flex:1;padding:8px 6px 9px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
    color:rgba(255,255,255,.4);background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
    border-bottom:2px solid transparent;border-radius:6px 6px 0 0;cursor:pointer;transition:all .15s;}
  .tab-btn:hover{color:rgba(255,255,255,.7);background:rgba(255,255,255,.08);}
  .tab-btn.active{color:var(--sl-gold);background:rgba(240,192,64,.08);border-color:rgba(240,192,64,.2);border-bottom-color:var(--sl-gold);}
  .tab-pane{display:none;}.tab-pane.active{display:block;}
  .fc-section{padding:12px 14px 4px;}
  .fc-nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;}
  .fc-nav-btn{background:none;border:1px solid rgba(255,255,255,.12);color:rgba(255,255,255,.45);
    border-radius:6px;padding:4px 10px;font-size:10px;cursor:pointer;}
  .fc-nav-btn:hover{border-color:rgba(255,255,255,.3);color:#fff;}
  .fc-nav-btn.disabled{opacity:.2;pointer-events:none;}
  .fc-nav-center{text-align:center;}
  .fc-nav-day{font-size:13px;font-weight:700;color:var(--sl-text);}
  .fc-nav-date{font-size:10px;color:var(--sl-muted);margin-top:1px;}
  .fc-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:10px;}
  .fc-stat{background:rgba(255,255,255,.04);border-radius:6px;padding:6px 8px;text-align:center;}
  .fc-stat-l{font-size:8px;color:rgba(255,255,255,.3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:2px;}
  .fc-stat-v{font-family:var(--sl-mono);font-size:13px;font-weight:700;}
  .fc-stat-v.g{color:var(--sl-green);}
  .fc-stat-v.y{color:var(--sl-gold);}
  .fc-legend{display:flex;gap:12px;margin-bottom:6px;}
  .fc-leg{display:flex;align-items:center;gap:5px;font-size:9px;color:rgba(255,255,255,.4);}
  .fc-dot{width:10px;height:4px;border-radius:2px;}
  .chart-wrap{position:relative;height:80px;margin-bottom:4px;}
  .chart-xlbl{display:flex;justify-content:space-between;font-size:8px;color:rgba(255,255,255,.2);padding:2px 2px 8px;}
  .inv-section{padding:10px 14px 12px;border-top:1px solid var(--sl-border);}
  .inv-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--sl-muted);margin-bottom:8px;}
  .inv-row{padding:6px 0;border-bottom:1px solid rgba(255,255,255,.03);animation:fadeUp .3s ease both;}
  .inv-row:last-child{border-bottom:none;}
  .inv-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
  .inv-name{font-size:13px;font-weight:600;color:var(--sl-text);}
  .inv-pwr{font-family:var(--sl-mono);font-size:14px;font-weight:700;color:var(--sl-gold);}
  .util-bar{height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;margin-bottom:6px;}
  .util-fill{height:100%;border-radius:2px;transition:width .8s;}
  .inv-chips{display:flex;flex-wrap:wrap;gap:4px;}
  .chip{font-family:var(--sl-mono);font-size:9px;padding:2px 7px;border-radius:10px;
    background:rgba(255,255,255,.06);color:var(--sl-sub);border:1px solid var(--sl-border);}
  .chip.phase{background:rgba(134,239,172,.08);color:var(--sl-green);border-color:rgba(134,239,172,.2);}
  .chip.orient{background:var(--sl-gold-dim);color:var(--sl-gold);border-color:rgba(240,192,64,.2);}
  .acc-footer{display:flex;align-items:center;gap:8px;padding:8px 14px;font-size:10px;color:var(--sl-sub);border-top:1px solid var(--sl-border);}
  .acc-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
  .clip-banner{padding:6px 14px;background:rgba(239,68,68,.1);border-bottom:1px solid rgba(239,68,68,.2);font-size:11px;font-weight:600;color:#f87171;display:flex;align-items:center;gap:6px;}
  .empty{padding:32px;text-align:center;color:var(--sl-muted);display:flex;flex-direction:column;align-items:center;gap:10px;}
  .empty-icon{font-size:36px;opacity:.3;}
  @keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
`;

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const fmt = (w, t=1000) => Math.abs(w) >= t ? (w/1000).toFixed(2)+' kW' : Math.round(w)+' W';
const compassLabel = a => ['N','NNO','NO','ONO','O','OZO','ZO','ZZO','Z','ZZW','ZW','WZW','W','WNW','NW','NNW'][Math.round(((a%360)+360)%360/22.5)%16] || '?';
const arr24 = () => new Array(24).fill(0);

function buildChartSVG(fc, actual, yesterday, nowH, isToday) {
  const W = 100, H = 100, PAD_T = 4, PAD_B = 0;
  const CH = H - PAD_T - PAD_B;
  const allVals = [...(fc||[]), ...(actual||[]).filter(v=>v>0), ...(yesterday||[])].filter(v=>v>0);
  const maxVal = allVals.length ? Math.max(...allVals) * 1.1 : 1;
  const toX = h => (h / 23) * W;
  const toY = v => PAD_T + CH - (v / maxVal) * CH;

  function makeLine(data, color, opacity, dashed) {
    if (!data || data.length < 2) return '';
    const pts = data.map((v,h) => [toX(h), toY(Math.max(0,v))]);
    let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) d += ` L ${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)}`;
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-opacity="${opacity||1}" ${dashed?'stroke-dasharray="3 2"':''} stroke-linecap="round"/>`;
  }
  function makeArea(data, color) {
    if (!data || data.length < 2) return '';
    const pts = data.map((v,h) => [toX(h), toY(Math.max(0,v))]);
    let d = `M ${pts[0][0].toFixed(1)} ${H}`;
    pts.forEach(([x,y]) => d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`);
    d += ` L ${pts[pts.length-1][0].toFixed(1)} ${H} Z`;
    return `<path d="${d}" fill="${color}" fill-opacity="0.12"/>`;
  }

  const actualShow = isToday
    ? (actual||arr24()).map((v,h) => h <= nowH ? v : 0)
    : (actual||arr24());
  const nowX = isToday ? toX(nowH).toFixed(1) : null;

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
    ${makeArea(fc||arr24(), '#f0c040')}
    ${makeArea(actualShow, '#86efac')}
    ${makeLine(yesterday||arr24(), 'rgba(255,255,255,0.3)', 0.6, true)}
    ${makeLine(fc||arr24(), '#f0c040', 0.85, false)}
    ${makeLine(actualShow, '#86efac', 1, false)}
    ${nowX ? `<line x1="${nowX}" y1="${PAD_T}" x2="${nowX}" y2="${H}" stroke="#f0c040" stroke-width="0.8" stroke-opacity="0.6" stroke-dasharray="2 2"/>` : ''}
  </svg>`;
}

class CloudemsSolarCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this._cfg = {};
    this._hass = null;
    this._prev = '';
    this._chartDay = 'today';
    this._activeTab = 'live';
    this._tabManualSet = false;
    this._pvHist = arr24();
    this._pvHistDay = 0;
  }

  setConfig(c) {
    this._cfg = c || {};
  }

  set hass(h) {
    this._hass = h;
    const j = JSON.stringify([
      h.states['sensor.cloudems_solar_system_intelligence']?.state,
      h.states['sensor.cloudems_pv_forecast_today']?.state,
      Math.floor(Date.now() / 10000),
    ]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot;
    if (!sh) return;
    const h = this._hass;
    if (!h) return;
    const c = this._cfg || {};

    try {
      this._renderInner(h, c, sh);
    } catch(e) {
      sh.innerHTML = `<style>${SOL_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">⚠️</span><span style="font-size:11px;color:#f87171">Laad fout: ${e.message}</span></div></div>`;
    }
  }

  _renderInner(h, c, sh) {
    const solS = h.states['sensor.cloudems_solar_system_intelligence']
               ?? h.states['sensor.cloudems_solar_system'];
    const fcS  = h.states['sensor.cloudems_pv_forecast_today']
               ?? h.states['sensor.cloudems_solar_pv_forecast_today'];
    const fcTS = h.states['sensor.cloudems_pv_forecast_tomorrow']
               ?? h.states['sensor.cloudems_solar_pv_forecast_tomorrow'];
    const accS = h.states['sensor.cloudems_pv_forecast_accuracy']
               ?? h.states['sensor.cloudems_solar_pv_forecast_accuracy'];

    if (!solS || solS.state === 'unavailable') {
      sh.innerHTML = `<style>${SOL_STYLES}</style><div class="card"><div class="empty"><span class="empty-icon">☀️</span><span>Laden...</span></div></div>`;
      return;
    }

    const sA = solS.attributes || {};
    const totalW = parseFloat(solS.state) || 0;
    const inverters = sA.inverters || [];
    const peakW = sA.total_peak_w || 0;
    const clipping      = sA.clipping_active || false;
    const clipFcTom     = sA.clipping_forecast_tomorrow || [];  // [{ceiling_w, predicted_clip_kwh, clipped_hours, advice}]

    const fcA = fcS?.attributes || {};
    const fcKwh = parseFloat(fcS?.state || 0) || 0;
    const fcTomKwh = parseFloat(fcTS?.state || 0) || 0;
    // fcA.hourly = [{hour, forecast_w, low_w, high_w, confidence}, ...]
    // Omzetten naar array van 24 kWh waarden voor de grafiek
    const _toArr24 = (objs) => {
      const out = arr24();
      if (!Array.isArray(objs)) return out;
      // Detecteer of het al een getal-array is (actual_hourly_kwh stijl)
      if (objs.length > 0 && typeof objs[0] === 'number') {
        return objs.length === 24 ? objs.slice() : out;
      }
      // Object-stijl: {hour, forecast_w}
      objs.forEach(h => {
        const hr = parseInt(h.hour ?? 0);
        if (hr >= 0 && hr < 24) out[hr] = (parseFloat(h.forecast_w) || 0) / 1000;
      });
      return out;
    };
    const fcHourly = _toArr24(fcA.hourly);
    const fcTomHourly = _toArr24((fcTS?.attributes || {}).hourly_tomorrow);

    const nowH = new Date().getHours();
    const nowDate = new Date();

    // Vandaag uurdata
    // Prio 1: backendHourly uit forecast sensor (persistent, overleeft herstart)
    const backendHourly = fcA.actual_hourly_kwh;
    const backendSum = Array.isArray(backendHourly)
      ? backendHourly.reduce((s, v) => s + (parseFloat(v) || 0), 0) : 0;

    // Prio 2: zelfs als backendHourly allemaal nul is, gebruik het bekende dagkWh totaal
    // Bronnen op volgorde van betrouwbaarheid:
    //  1. sensor.cloudems_self_consumption.pv_today_kwh  (coordinator _pv_today_hourly_kwh som)
    //  2. sensor.cloudems_solar_system.pv_today_kwh      (solar_learner accumulatie)
    const scState    = h.states['sensor.cloudems_self_consumption'];
    const scTodayKwh = parseFloat(scState?.attributes?.pv_today_kwh || 0) || 0;
    const solTodayKwh = parseFloat(sA.pv_today_kwh || 0) || 0;
    const knownTotal = Math.max(scTodayKwh, solTodayKwh);  // beste beschikbare totaal

    if (Array.isArray(backendHourly) && backendHourly.length === 24 && backendSum > 0.01) {
      // Backend heeft echte data — gebruik die direct
      this._pvHist = backendHourly.slice();
      this._pvHistDay = nowDate.getDate();
    } else if (knownTotal > 0.01 && backendSum < 0.01) {
      // Backend is leeg (na herstart) maar totaal is bekend → vul huidig uur bij
      if (!this._pvHist || this._pvHist.length !== 24) this._pvHist = arr24();
      if (nowDate.getDate() !== this._pvHistDay) { this._pvHist = arr24(); this._pvHistDay = nowDate.getDate(); }
      // Zet het bekende totaal in het huidig uur als startpunt (wordt verfijnd zodra backend vult)
      const currentSum = this._pvHist.reduce((s, v) => s + v, 0);
      if (currentSum < knownTotal * 0.9) {
        // Distribueer het verschil over de ochtenduren t/m nu (lineair profiel als noodoplossing)
        const missing = knownTotal - currentSum;
        if (nowH > 0) {
          const perH = missing / Math.max(1, nowH);
          for (let h2 = 0; h2 < nowH; h2++) this._pvHist[h2] = (this._pvHist[h2] || 0) + perH;
        }
        this._pvHistDay = nowDate.getDate();
      }
      const inc = totalW / 1000 * (10 / 3600);
      if (inc > 0) this._pvHist[nowH] = (this._pvHist[nowH] || 0) + inc;
    } else {
      if (!this._pvHist || this._pvHist.length !== 24) this._pvHist = arr24();
      if (nowDate.getDate() !== this._pvHistDay) { this._pvHist = arr24(); this._pvHistDay = nowDate.getDate(); }
      const inc = totalW / 1000 * (10 / 3600);
      if (inc > 0) this._pvHist[nowH] = (this._pvHist[nowH] || 0) + inc;
    }

    // Gisteren uurdata
    const accA = accS?.attributes || {};
    const ystRaw = accA.yesterday_hourly_kwh || {};
    const ystHourly = arr24();
    if (typeof ystRaw === 'object' && !Array.isArray(ystRaw)) {
      Object.entries(ystRaw).forEach(([hr, kwh]) => { ystHourly[parseInt(hr)] = parseFloat(kwh || 0); });
    } else if (Array.isArray(ystRaw) && ystRaw.length === 24) {
      ystRaw.forEach((v, i) => { ystHourly[i] = v; });
    }

    const dailyHistory = accA.daily_history || [];
    const days = this._buildDays(fcHourly, fcTomHourly, ystHourly, dailyHistory, fcKwh, fcTomKwh);
    const dayKeys = Object.keys(days);
    if (!days[this._chartDay]) this._chartDay = 'today';
    const cdData = days[this._chartDay] || days['today'];
    const curIdx = dayKeys.indexOf(this._chartDay);
    const prevKey = curIdx > 0 ? dayKeys[curIdx - 1] : null;
    const nextKey = curIdx < dayKeys.length - 1 ? dayKeys[curIdx + 1] : null;

    const mape14 = parseFloat(accA.mape_14d_pct || 0);
    const accColor = mape14 < 10 ? '#86efac' : mape14 < 20 ? '#f0c040' : '#fb923c';
    const todayTotal = (this._pvHist || arr24()).reduce((a, b) => a + (b || 0), 0);

    const fcExpected = (cdData.fc || arr24()).slice(0, nowH + 1).reduce((a, b) => a + (parseFloat(b)||0), 0);
    const actTotal   = (cdData.actual || arr24()).filter(v => v > 0).reduce((a, b) => a + (parseFloat(b)||0), 0);
    const devPct     = fcExpected > 0 ? ((actTotal - fcExpected) / fcExpected * 100) : 0;
    const devColor   = Math.abs(devPct) < 5 ? '#86efac' : Math.abs(devPct) < 15 ? '#f0c040' : '#fb923c';

    sh.innerHTML = `<style>${SOL_STYLES}</style>
    <div class="card">
      <div class="hdr">
        <span class="hdr-icon">☀️</span>
        <div class="hdr-texts">
          <div class="hdr-title">${esc(c.title || 'Zonnepanelen')}</div>
          <div class="hdr-sub">${inverters.length} omvormer${inverters.length !== 1 ? 's' : ''} · piek ${Math.round(peakW / 1000 * 100) / 100} kW</div>
        </div>
        <span class="hdr-watt">${fmt(totalW)}</span>
      </div>

      ${clipping ? `<div class="clip-banner">⚡ Clipping actief</div>` : ''}

      <div class="top-strip">
        <div class="top-box">
          <div class="top-label">Nu</div>
          <div class="top-val" style="color:${totalW > 0 ? '#f0c040' : '#3d5229'}">${fmt(totalW)}</div>
          <div class="top-sub">piek ${Math.round(peakW / 1000 * 100) / 100} kW</div>
        </div>
        <div class="top-box">
          <div class="top-label">Vandaag</div>
          <div class="top-val" style="color:#86efac">${todayTotal.toFixed(1)} kWh</div>
          <div class="top-sub">gemeten</div>
        </div>
        <div class="top-box">
          <div class="top-label">Morgen</div>
          <div class="top-val">${fcTomKwh.toFixed(1)} kWh</div>
          <div class="top-sub">verwacht</div>
        </div>
      </div>

      <div class="tab-bar">
        ${[{id:'live',l:'☀️ Live'},{id:'analyse',l:'📊 Analyse'},{id:'advies',l:'💡 Advies'}]
          .map(t => `<button class="tab-btn${this._activeTab === t.id ? ' active' : ''}" data-tab="${t.id}">${t.l}</button>`)
          .join('')}
      </div>

      <div class="tab-pane${this._activeTab === 'live' ? ' active' : ''}">
        <div class="fc-section">
          <div class="fc-nav">
            <button class="fc-nav-btn${!prevKey ? ' disabled' : ''}" data-fcnav="prev">← ${prevKey ? days[prevKey].label : ''}</button>
            <div class="fc-nav-center">
              <div class="fc-nav-day">${cdData.label}</div>
              <div class="fc-nav-date">${cdData.dateStr || ''}</div>
            </div>
            <button class="fc-nav-btn${!nextKey ? ' disabled' : ''}" data-fcnav="next">${nextKey ? days[nextKey].label : ''} →</button>
          </div>

          <div class="fc-stats">
            <div class="fc-stat">
              <div class="fc-stat-l">${cdData.isToday ? 'Verwacht tot nu' : 'Totaal verwacht'}</div>
              <div class="fc-stat-v y">${cdData.isYesterday ? '—' : fcExpected.toFixed(1)+' kWh'}</div>
            </div>
            <div class="fc-stat">
              <div class="fc-stat-l">${cdData.isToday ? 'Werkelijk' : 'Werkelijk'}</div>
              <div class="fc-stat-v g">${actTotal.toFixed(1)} kWh</div>
            </div>
            <div class="fc-stat">
              <div class="fc-stat-l">Afwijking</div>
              <div class="fc-stat-v" style="color:${devColor}">${devPct >= 0 ? '+' : ''}${devPct.toFixed(0)}%</div>
            </div>
          </div>

          <div class="fc-legend">
            <div class="fc-leg"><div class="fc-dot" style="background:#f0c040"></div>Verwacht</div>
            <div class="fc-leg"><div class="fc-dot" style="background:#86efac"></div>Werkelijk</div>
            <div class="fc-leg"><div class="fc-dot" style="background:rgba(255,255,255,.3)"></div>Gisteren</div>
          </div>

          <div class="chart-wrap">
            ${buildChartSVG(cdData.fc, cdData.actual, cdData.yesterday, nowH, cdData.isToday)}
          </div>
          <div class="chart-xlbl">
            ${['00','03','06','09','12','15','18','21','23'].map(x => `<span>${x}</span>`).join('')}
          </div>
        </div>

        ${inverters.length ? `
        <div class="inv-section">
          <div class="inv-title">Omvormers (${inverters.length})</div>
          ${inverters.map(inv => {
            // Correcte veldnamen van sensor.cloudems_solar_system_intelligence
            const peakWatt = inv.estimated_wp || inv.peak_w || inv.rated_power_w || 0;
            const utilisPct = inv.utilisation_pct != null
              ? Math.round(inv.utilisation_pct)
              : (peakWatt > 0 ? Math.round((inv.current_w || 0) / peakWatt * 100) : 0);
            const azCompass = inv.azimuth_compass || '';
            const azDeg = inv.azimuth_learned ?? null;
            const tiltDeg = inv.tilt_learned ?? inv.tilt_deg ?? null;
            const phaseLabel = inv.phase_display || (inv.phase ? 'Fase ' + inv.phase : '');
            return `<div class="inv-row">
              <div class="inv-top">
                <div class="inv-name">☀️ ${esc(inv.label || 'Omvormer')}</div>
                <div class="inv-pwr">${fmt(inv.current_w || 0)}</div>
              </div>
              <div class="util-bar"><div class="util-fill" style="width:${Math.min(100,utilisPct)}%;background:${utilisPct>85?'#f0c040':'#86efac'}"></div></div>
              <div class="inv-chips">
                ${peakWatt > 0 ? `<span class="chip">${Math.round(peakWatt).toLocaleString('nl')} Wp</span>` : ''}
                ${azCompass ? `<span class="chip orient">${azCompass}</span>` : ''}
                ${tiltDeg != null ? `<span class="chip orient">∠${Math.round(tiltDeg)}°</span>` : ''}
                ${phaseLabel ? `<span class="chip phase">${phaseLabel}</span>` : ''}
                <span class="chip">${utilisPct}% benut · ${peakWatt > 0 ? Math.round(peakWatt/1000*100)/100+' kW max' : ''}</span>
              </div>
            </div>`;
          }).join('')}
        </div>` : ''}

        <div class="acc-footer">
          <div class="acc-dot" style="background:${accColor}"></div>
          <span>Nauwkeurigheid 14d: <strong>${mape14.toFixed(1)}%</strong> · ${accA.samples || 0} dagen gemeten</span>
        </div>
      </div>

      <div class="tab-pane${this._activeTab === 'analyse' ? ' active' : ''}">
        <div style="padding:14px 16px;">${this._renderAnalyse(accA, dailyHistory)}</div>
      </div>

      <div class="tab-pane${this._activeTab === 'advies' ? ' active' : ''}">
        <div style="padding:14px 16px;">${this._renderAdvies(sA, fcKwh, fcTomKwh, clipFcTom)}</div>
      </div>
    </div>`;

    sh.querySelectorAll('[data-tab]').forEach(btn => {
      btn.addEventListener('click', e => {
        this._activeTab = e.currentTarget.dataset.tab;
        this._tabManualSet = true;
        this._render();
      });
    });
    sh.querySelectorAll('[data-fcnav]').forEach(btn => {
      btn.addEventListener('click', e => {
        const dir = e.currentTarget.dataset.fcnav;
        const keys = Object.keys(days);
        const cur = keys.indexOf(this._chartDay);
        if (dir === 'prev' && cur > 0) this._chartDay = keys[cur - 1];
        if (dir === 'next' && cur < keys.length - 1) this._chartDay = keys[cur + 1];
        this._render();
      });
    });
  }

  _buildDays(fcHourly, fcTomHourly, ystHourly, dailyHistory, fcKwh, fcTomKwh) {
    const days = {};
    const now = new Date();
    const pvHist = this._pvHist || arr24();
    const todayTotal = pvHist.reduce((a, b) => a + (parseFloat(b)||0), 0);

    // Gisteren
    const ystDate = new Date(now);
    ystDate.setDate(ystDate.getDate() - 1);
    const ystTotal = ystHourly.reduce((a, b) => a + (parseFloat(b)||0), 0);
    days['yesterday'] = {
      label: 'Gisteren',
      dateStr: ystDate.toLocaleDateString('nl', {day:'numeric', month:'short'}),
      fc: arr24(), actual: ystHourly, yesterday: arr24(),  // geen forecast voor gisteren
      isToday: false, isTomorrow: false, isYesterday: true,
    };

    // Vandaag
    days['today'] = {
      label: 'Vandaag',
      dateStr: now.toLocaleDateString('nl', {day:'numeric', month:'short'}),
      fc: fcHourly, actual: pvHist, yesterday: ystHourly,
      isToday: true, isTomorrow: false,
    };

    // Morgen
    const tomDate = new Date(now);
    tomDate.setDate(tomDate.getDate() + 1);
    days['tomorrow'] = {
      label: 'Morgen',
      dateStr: tomDate.toLocaleDateString('nl', {day:'numeric', month:'short'}),
      fc: fcTomHourly, actual: arr24(), yesterday: fcHourly,
      isToday: false, isTomorrow: true,
    };

    return days;
  }

  _renderAnalyse(accA, dailyHistory) {
    const hist = (dailyHistory || []).slice(-14).reverse();
    if (!hist.length) return `<div style="color:rgba(255,255,255,.3);font-size:11px;text-align:center;padding:20px 0;">Nog geen history — groeit dagelijks aan</div>`;

    const maxKwh = Math.max(...hist.map(d => d.total_kwh || 0), 1);
    const rows = hist.map(d => {
      const total = d.total_kwh || 0;
      const date = new Date(d.date);
      const dateStr = date.toLocaleDateString('nl', {weekday:'short', day:'numeric', month:'short'});
      const barW = Math.round(total / maxKwh * 100);
      return `<div style="margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px;">
          <span style="color:rgba(255,255,255,.5)">${dateStr}</span>
          <span style="font-family:var(--sl-mono);color:#86efac;font-weight:600">${total.toFixed(1)} kWh</span>
        </div>
        <div style="height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;">
          <div style="height:100%;width:${barW}%;background:#86efac;border-radius:2px;"></div>
        </div>
      </div>`;
    }).join('');

    const mape14 = parseFloat(accA.mape_14d_pct || 0);
    const mape30 = parseFloat(accA.mape_30d_pct || 0);
    // SVG bar chart — horizontale bars per dag
    const SVG_W = 300, BAR_H = 14, GAP = 5;
    const svgH = hist.length * (BAR_H + GAP);
    const labelW = 72, valW = 38, barAreaW = SVG_W - labelW - valW - 8;
    const svgBars = hist.map((d, i) => {
      const total = d.total_kwh || 0;
      const bw = Math.round(total / maxKwh * barAreaW);
      const y = i * (BAR_H + GAP);
      const date = new Date(d.date);
      const lbl = date.toLocaleDateString('nl', {weekday:'short', day:'numeric', month:'short'});
      const col = total >= maxKwh * 0.8 ? '#86efac' : total >= maxKwh * 0.4 ? '#f0c040' : '#fb923c';
      return `<g>
        <text x="0" y="${y + BAR_H - 2}" font-size="9" fill="rgba(255,255,255,.45)">${lbl}</text>
        <rect x="${labelW}" y="${y}" width="${barAreaW}" height="${BAR_H}" rx="3" fill="rgba(255,255,255,.04)"/>
        <rect x="${labelW}" y="${y}" width="${bw}" height="${BAR_H}" rx="3" fill="${col}44"/>
        <rect x="${labelW}" y="${y + BAR_H - 2}" width="${bw}" height="2" rx="1" fill="${col}"/>
        <text x="${SVG_W}" y="${y + BAR_H - 2}" font-size="9" font-weight="600" fill="${col}" text-anchor="end">${total.toFixed(1)}</text>
      </g>`;
    }).join('');

    return `
      <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--sl-muted);margin-bottom:8px;">Productie per dag (${hist.length}d)</div>
      <svg viewBox="0 0 ${SVG_W} ${svgH}" width="100%" style="display:block;margin-bottom:12px;overflow:visible">${svgBars}</svg>
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--sl-border);">
        <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--sl-muted);margin-bottom:8px;">Forecast nauwkeurigheid</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <div style="background:rgba(255,255,255,.04);border-radius:6px;padding:8px;text-align:center;">
            <div style="font-size:9px;color:rgba(255,255,255,.3);margin-bottom:2px;">14 DAGEN</div>
            <div style="font-family:var(--sl-mono);font-size:16px;font-weight:700;color:${mape14<10?'#86efac':mape14<20?'#f0c040':'#fb923c'}">${mape14.toFixed(1)}%</div>
          </div>
          <div style="background:rgba(255,255,255,.04);border-radius:6px;padding:8px;text-align:center;">
            <div style="font-size:9px;color:rgba(255,255,255,.3);margin-bottom:2px;">30 DAGEN</div>
            <div style="font-family:var(--sl-mono);font-size:16px;font-weight:700;color:${mape30<10?'#86efac':mape30<20?'#f0c040':'#fb923c'}">${mape30.toFixed(1)}%</div>
          </div>
        </div>
      </div>`;
  }

  _renderAdvies(sA, fcKwh, fcTomKwh, clipFcTom=[]) {
    const tips = [];
    if (sA.clipping_active) tips.push({icon:'⚡', text:'Clipping actief — omvormer begrenst vermogen.', color:'#f87171'});

    // Clipping forecast morgen
    const totalClipKwh = clipFcTom.reduce((s, c) => s + (c.predicted_clip_kwh || 0), 0);
    if (totalClipKwh >= 0.3) {
      const allHours = clipFcTom.flatMap(c => c.clipped_hours || []);
      const earliestHour = allHours.length ? Math.min(...allHours) : null;
      const latestHour   = allHours.length ? Math.max(...allHours) : null;
      const hoursStr = earliestHour !== null ? `${earliestHour}:00–${latestHour+1}:00` : '';
      tips.push({
        icon: '⚡',
        text: `Morgen ~${totalClipKwh.toFixed(1)} kWh clipping verwacht${hoursStr ? ' tussen ' + hoursStr : ''}. `
             + (earliestHour !== null && earliestHour > 0
               ? `Laad batterij vóór ${earliestHour}:00 om clipping op te vangen.`
               : `Zet verbruikers aan tijdens clipping-uren.`),
        color: '#fb923c'
      });
    } else if (totalClipKwh > 0 && totalClipKwh < 0.3) {
      tips.push({icon:'⚡', text:`Morgen minimale clipping verwacht (~${(totalClipKwh*1000).toFixed(0)} Wh) — geen actie nodig.`, color:'#fbbf24'});
    }

    if (fcTomKwh > fcKwh * 1.2 && fcKwh > 2) tips.push({icon:'☀️', text:`Morgen ${fcTomKwh.toFixed(1)} kWh verwacht — ${((fcTomKwh/fcKwh-1)*100).toFixed(0)}% meer. Goede dag voor zware verbruikers.`, color:'#86efac'});
    if (fcTomKwh < fcKwh * 0.5 && fcKwh > 5) tips.push({icon:'🌥️', text:`Morgen maar ${fcTomKwh.toFixed(1)} kWh — plan wasbeurt vandaag in.`, color:'#60a5fa'});
    if (!tips.length) tips.push({icon:'✅', text:'Systeem functioneert normaal.', color:'#86efac'});
    return tips.map(t => `<div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04);">
      <span style="font-size:16px;flex-shrink:0;">${t.icon}</span>
      <span style="font-size:11px;color:${t.color};line-height:1.5;">${t.text}</span>
    </div>`).join('');
  }

  static getConfigElement() { return document.createElement('cloudems-solar-card-editor'); }
  static getStubConfig() { return {type:'cloudems-solar-card', title:'Zonnepanelen'}; }
}

class CloudemsSolarCardEditor extends HTMLElement {
  setConfig(c) { this._c = c || {}; }
  set hass(h) {}
  connectedCallback() {
    this.innerHTML = `<div style="padding:12px;font-family:system-ui;color:#ccc;">
      <label style="display:block;margin-bottom:8px;font-size:12px;">Titel
        <input style="width:100%;margin-top:4px;padding:6px;background:#1a2310;border:1px solid #2d4a1e;border-radius:4px;color:#fff;font-size:12px;"
          value="${this._c && this._c.title ? this._c.title : 'Zonnepanelen'}" data-key="title">
      </label>
    </div>`;
    this.querySelector('input').addEventListener('change', e => {
      this.dispatchEvent(new CustomEvent('config-changed', {detail:{config:{...(this._c||{}), title:e.target.value}}}));
    });
  }
}

if (!customElements.get('cloudems-solar-card-editor')) customElements.define('cloudems-solar-card-editor', CloudemsSolarCardEditor);
if (!customElements.get('cloudems-solar-card')) customElements.define('cloudems-solar-card', CloudemsSolarCard);

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'cloudems-solar-card'))
  window.customCards.push({type:'cloudems-solar-card', name:'CloudEMS Solar Card', description:'PV forecast met rolling history'});
