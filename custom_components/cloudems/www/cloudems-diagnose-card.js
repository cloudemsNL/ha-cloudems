// Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
// All rights reserved. See LICENSE for full terms.
// CloudEMS Diagnose Card  v1.1.0

const DIAGNOSE_VERSION = "2.0.0";
const _esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const _fmt = (v, dec=1) => v != null && !isNaN(v) ? parseFloat(v).toFixed(dec) : "—";
const _st  = (hass, eid) => hass?.states?.[eid];
const _sv  = (hass, eid) => _st(hass,eid)?.state;
const _sa  = (hass, eid) => _st(hass,eid)?.attributes || {};

const CSS = `
  :host { --bg: var(--ha-card-background,var(--card-background-color,#1c1c1c)); --s:rgba(255,255,255,.04); --b:rgba(255,255,255,.08); --t:var(--primary-text-color,#e8eaed); --m:var(--secondary-text-color,#9aa0a6); --green:#1D9E75; --amber:#BA7517; --red:#e74c3c; --blue:#378ADD; }
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{background:var(--bg);border-radius:12px;overflow:hidden;font-family:var(--primary-font-family,sans-serif);font-size:13px;}
  .tabs{display:flex;overflow-x:auto;border-bottom:0.5px solid var(--b);background:var(--s);}
  .tab{padding:10px 14px;cursor:pointer;white-space:nowrap;font-size:12px;color:var(--m);border-bottom:2px solid transparent;transition:all .2s;}
  .tab.active{color:var(--t);border-bottom-color:var(--green);}
  .tab:hover{color:var(--t);}
  .panel{display:none;padding:14px;}
  .panel.active{display:block;}
  .section{margin-bottom:16px;}
  .section-title{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--m);margin-bottom:8px;padding-bottom:4px;border-bottom:0.5px solid var(--b);}
  .kv{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid var(--b);gap:8px;}
  .kv:last-child{border-bottom:none;}
  .kl{color:var(--m);flex:1;}
  .kv_{font-weight:500;color:var(--t);text-align:right;}
  .ok{color:var(--green)!important;} .warn{color:var(--amber)!important;} .err{color:var(--red)!important;} .info{color:var(--blue)!important;}
  .badge{font-size:10px;padding:2px 7px;border-radius:4px;font-weight:500;}
  .b-ok{background:rgba(29,158,117,.15);color:#4ade80;} .b-warn{background:rgba(186,117,23,.18);color:#fbbf24;} .b-err{background:rgba(231,76,60,.15);color:#f87171;}
  .bar-wrap{height:5px;background:var(--b);border-radius:3px;overflow:hidden;margin-top:4px;}
  .bar-fill{height:100%;border-radius:3px;transition:width .3s;}
  .crash-row{padding:6px 8px;background:rgba(239,68,68,.08);border-radius:6px;border-left:2px solid var(--red);margin-bottom:4px;font-size:11px;}
  .crash-ts{color:var(--m);font-size:10px;}
  .crash-msg{color:#fca5a5;margin-top:2px;word-break:break-word;}
  .nilm-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:0.5px solid var(--b);}
  .nilm-row:last-child{border-bottom:none;}
  .nilm-name{flex:1;color:var(--t);}
  .nilm-w{color:var(--m);min-width:52px;text-align:right;}
  .nilm-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
  .phase-row{display:grid;grid-template-columns:60px 1fr 1fr 1fr;gap:4px;padding:5px 0;border-bottom:0.5px solid var(--b);font-size:12px;}
  .phase-row:last-child{border-bottom:none;}
  .perf-row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid var(--b);font-size:12px;}
  .perf-row:last-child{border-bottom:none;}
`;

// Helper: kv-rij met optionele tooltip (v4.6.583)
function _kvTT(label, val, tipLines, opts) {
  const _TT = window.CloudEMSTooltip;
  if (!_TT || !tipLines) return '<div class="kv"><span class="kl">'+label+'</span><span class="kv_">'+val+'</span></div>';
  const id = 'dg-'+label.replace(/[^a-z0-9]/gi,'_').toLowerCase().slice(0,20);
  const tt = _TT.html(id, label, tipLines, opts||{});
  return '<div class="kv" style="position:relative;cursor:default" '+tt.wrap+'><span class="kl">'+label+'</span><span class="kv_">'+val+'</span>'+tt.tip+'</div>';
}

class CloudemsDiagnoseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this._tab = 0;
    this._prev = "";
  }

  setConfig(c) { this._cfg = c || {}; this._render(); }

  set hass(h) {
    this._hass = h;
    // Hash op kritieke sensoren
    const j = JSON.stringify([
      _sv(h,'sensor.cloudems_system_health'),
      _sv(h,'sensor.cloudems_watchdog'),
      _sv(h,'sensor.cloudems_nilm_diagnostics'),
      _sv(h,'sensor.cloudems_nilm_devices'),
    ]);
    if (j !== this._prev) { this._prev = j; this._render(); }
  }

  _render() {
    const sh = this.shadowRoot; if (!sh) return;
    const h = this._hass;
    if (!h) { sh.innerHTML = `<style>${CSS}</style><div class="card" style="padding:24px;color:var(--m)">Laden…</div>`; return; }

    const tabs = ["💚 Gezondheid","🔁 Watchdog","📡 Sensoren","🔬 NILM","⚡ Fasen","🏎️ Prestaties","🔌 Generator/Groepen","🏠 Slimme Verlichting","🔋 UPS Systemen"];

    sh.innerHTML = `<style>${CSS}</style>
    <div class="card">
      <div class="tabs">
        ${tabs.map((t,i) => `<div class="tab ${i===this._tab?'active':''}" data-tab="${i}">${t}</div>`).join('')}
      </div>
      ${tabs.map((_,i) => `<div class="panel ${i===this._tab?'active':''}" id="panel-${i}">
        ${this[`_panel${i}`]?.call(this) || ''}
      </div>`).join('')}
    </div>`;

    sh.querySelectorAll('.tab').forEach(el => {
      el.addEventListener('click', () => {
        this._tab = parseInt(el.dataset.tab);
        this._render();
      });
    });
  }

  // ── Tab 0: Gezondheid ──────────────────────────────────────────────────────
  _panel0() {
    const h = this._hass;
    const score = parseFloat(_sv(h,'sensor.cloudems_system_health') || 0);
    const a = _sa(h,'sensor.cloudems_system_health');
    const pct = Math.round(score/10*100);
    const col = score>=8?'var(--green)':score>=5?'var(--amber)':'var(--red)';
    const lbl = score>=9?'Uitstekend':score>=7?'Goed':score>=5?'Matig':score>=3?'Slecht':'Kritiek';

    const wd = _sa(h,'sensor.cloudems_watchdog');
    const wdState = _sv(h,'sensor.cloudems_watchdog') || '?';
    const wdCls = wdState==='ok'?'ok':wdState==='warning'?'warn':'err';

    return `
    <div class="section">
      <div class="section-title">Systeemstatus</div>
      <div style="display:flex;align-items:center;gap:12px;padding:10px 0">
        <div style="font-size:40px;font-weight:700;color:${col}">${score.toFixed(1)}</div>
        <div style="flex:1">
          <div style="font-size:14px;font-weight:500;color:var(--t)">${lbl}</div>
          <div class="bar-wrap" style="margin-top:6px"><div class="bar-fill" style="width:${pct}%;background:${col}"></div></div>
          <div style="font-size:10px;color:var(--m);margin-top:3px">${pct}% van 10</div>
        </div>
      </div>
      ${_kvTT("Versie",`v${_esc(a.version||'?')}`,[{label:'Sensor',value:'cloudems_system_health'},{label:'Versie',value:'v'+(a.version||'?')},{label:'Uitleg',value:'Huidig geïnstalleerde CloudEMS versie',dim:true}])}
      ${_kvTT("Uptime",`${a.uptime_h?_fmt(a.uptime_h)+' uur':'—'}`,[{label:'Attribuut',value:'uptime_h'},{label:'Waarde',value:a.uptime_h?_fmt(a.uptime_h)+' uur':'—'},{label:'Uitleg',value:'Tijd actief zonder volledige herstart HA',dim:true}])}
      ${_kvTT("Update cycli",`${a.update_count||'—'}`,[{label:'Attribuut',value:'update_count'},{label:'Uitleg',value:'Aantal succesvolle evaluate-cycli sinds opstart',dim:true}])}
      <div class="kv"><span class="kl">Watchdog</span><span class="kv_ ${wdCls}">${wdState}</span></div>
      <div class="kv"><span class="kl">Fouten (ooit)</span><span class="kv_ ${parseInt(wd.total_failures||0)>100?'warn':''}">${wd.total_failures||0}</span></div>
      <div class="kv"><span class="kl">Herstarts</span><span class="kv_ ${parseInt(wd.total_restarts||0)>5?'warn':''}">${wd.total_restarts||0}</span></div>
      ${_kvTT("Laatste succes",`${_esc(wd.last_success_ago||'—')}`,[{label:'Attribuut',value:'cloudems_watchdog → last_success_ago'},{label:'Normaal',value:'< 30s geleden',dim:true}])}
    </div>

    <div class="section">
      <div class="section-title">Systeembelasting</div>
      ${(() => {
        const perf = _sa(h,'sensor.cloudems_performance') || {};
        const avg = parseFloat(perf.avg_cycle_ms||0);
        const p95 = parseFloat(perf.p95_cycle_ms||0);
        const max = parseFloat(perf.max_cycle_ms||0);
        const mode = perf.mode || '?';
        const modeCls = mode==='NORMAL'?'ok':mode==='REDUCED'?'warn':mode==='MINIMAL'?'warn':'err';
        return `
        <div class="kv"><span class="kl">Modus</span><span class="kv_ ${modeCls}">${mode}</span></div>
        <div class="kv"><span class="kl">Gemiddeld cyclus</span><span class="kv_ ${avg>500?'warn':''}">${avg.toFixed(0)} ms</span></div>
        <div class="kv"><span class="kl">P95 cyclus</span><span class="kv_ ${p95>2000?'warn':''}">${p95.toFixed(0)} ms</span></div>
        <div class="kv"><span class="kl">Maximum</span><span class="kv_ ${max>5000?'err':max>2000?'warn':''}">${max.toFixed(0)} ms</span></div>`;
      })()}
    </div>`;
  }

  // ── Tab 1: Watchdog ────────────────────────────────────────────────────────
  _panel1() {
    const h = this._hass;
    const a = _sa(h,'sensor.cloudems_watchdog');
    const hist = a.history || [];
    const cons = parseInt(a.consecutive_failures||0);
    const maxC = parseInt(a.max_consecutive||3);
    const wdState = _sv(h,'sensor.cloudems_watchdog') || '?';
    const wdCls = wdState==='ok'?'ok':wdState==='warning'?'warn':'err';

    return `
    <div class="section">
      <div class="section-title">Status</div>
      <div class="kv"><span class="kl">Status</span><span class="kv_ ${wdCls}">${wdState}</span></div>
      <div class="kv"><span class="kl">Opeenvolgende fouten</span><span class="kv_ ${cons>0?'warn':''}">${cons}/${maxC}</span></div>
      ${_kvTT("Totaal fouten",`${a.total_failures||0}`,[{label:'Attribuut',value:'total_failures'},{label:'Normaal',value:'< 100 over volledige runtime',dim:true}])}
      <div class="kv"><span class="kl">Automatische herstarts</span><span class="kv_ ${parseInt(a.total_restarts||0)>3?'warn':''}">${a.total_restarts||0}</span></div>
      ${_kvTT("Laatste fout",`${_esc(a.last_failure_ago||'—')}`,[{label:'Attribuut',value:'last_failure_ago'},{label:'Uitleg',value:'Tijd geleden dat de laatste fout optrad',dim:true}])}
      ${_kvTT("Laatste herstart",`${_esc(a.last_restart_ago||'Nooit')}`,[{label:'Attribuut',value:'last_restart_ago'},{label:'Uitleg',value:'Tijd geleden dat watchdog een herstart triggerde',dim:true}])}
      ${_kvTT("Laatste succes",`${_esc(a.last_success_ago||'—')}`,[{label:'Attribuut',value:'last_success_ago'},{label:'Normaal',value:'< 30s geleden',dim:true}])}
      ${a.next_restart_in_s>0?`<div class="kv"><span class="kl">Volgende herstart na</span><span class="kv_ warn">${a.next_restart_in_s}s backoff</span></div>`:''}
    </div>
    ${a.last_failure_msg ? `
    <div class="section">
      <div class="section-title">Laatste foutmelding</div>
      <div class="crash-row"><div class="crash-msg">${_esc(a.last_failure_msg)}</div></div>
    </div>` : ''}
    ${hist.length ? `
    <div class="section">
      <div class="section-title">Crashgeschiedenis (laatste ${hist.length})</div>
      ${[...hist].reverse().map(e => `
        <div class="crash-row">
          <div class="crash-ts">${_esc(e.ts?e.ts.slice(11,19):'?')} &nbsp;·&nbsp; #${e.consecutive||1}</div>
          <div class="crash-msg">${_esc((e.error||'').slice(0,120))}</div>
        </div>`).join('')}
    </div>` : ''}`;
  }

  // ── Tab 2: Sensoren ────────────────────────────────────────────────────────
  _panel2() {
    const h = this._hass;
    const qc = _sa(h,'sensor.cloudems_sensor_kwaliteitscheck');
    const p1 = _sa(h,'sensor.cloudems_p1_diagnostics') || _sa(h,'sensor.cloudems_status');
    const ema = _sa(h,'sensor.cloudems_ema_diagnostics');
    const bal = _sa(h,'sensor.cloudems_energy_balancer') || {};
    const sirDiag = bal.sensor_intervals || {};
    const issues = qc.issues || [];
    const allOk = qc.all_ok || issues.length===0;

    // Helper: kleur op basis van interval verwachting
    const _intColor = (measured, expected) => {
      if (measured == null) return '';
      const ratio = measured / expected;
      if (ratio < 0.4 || ratio > 3.5) return 'err';
      if (ratio < 0.7 || ratio > 2.0) return 'warn';
      return 'ok';
    };

    const gridInt   = bal.grid_interval_s;
    const batInt    = bal.battery_interval_s;
    const batLag    = bal.battery_lag_learned_s;
    const batConf   = bal.battery_lag_confidence;
    const batSampl  = bal.battery_lag_samples || 0;
    const p1Meas    = bal.p1_measured_interval_s;
    const p1Samp    = bal.p1_telegram_samples || 0;
    const dsmrType  = bal.dsmr_type_configured || 'universal';
    const dsmrCorr  = bal.dsmr_type_auto_corrected || false;
    const lagComp   = bal.lag_compensated || false;
    const fastRamp  = bal.fast_ramp_active || false;
    const fastEst   = bal.fast_ramp_battery_est_w;
    const stale     = bal.stale_sensors || [];

    // DSMR type labels
    const dsmrLabels = {dsmr4:'DSMR 4 (~10s)', dsmr5:'DSMR 5 (~1s)', universal:'Universeel'};
    const dsmrExpected = {dsmr4:10, dsmr5:1, universal:null};
    const dsmrLabel = dsmrLabels[dsmrType] || dsmrType;
    const dsmrExp   = dsmrExpected[dsmrType];

    // P1 interval kleur vs. geconfigureerd DSMR type
    const p1Color = (p1Meas != null && dsmrExp != null) ? _intColor(p1Meas, dsmrExp) : '';
    const p1MismatchWarn = p1Color === 'err' || p1Color === 'warn';

    return `
    <div class="section">
      <div class="section-title">Sensor Kwaliteitscheck</div>
      <div class="kv"><span class="kl">Status</span><span class="kv_ ${allOk?'ok':'warn'}">${allOk?'✅ Alle sensoren OK':'⚠️ Problemen gevonden'}</span></div>
      ${issues.map(i => `<div class="kv"><span class="kl err">⚠ ${_esc(i.entity||i.label||'?')}</span><span class="kv_ err">${_esc(i.issue||i.message||'')}</span></div>`).join('')}
    </div>

    <div class="section">
      <div class="section-title">⚡ P1 / DSMR Updatesnelheid</div>
      <div class="kv"><span class="kl">DSMR-type ingesteld</span><span class="kv_ ${dsmrCorr?'warn':'ok'}">${dsmrLabel}${dsmrCorr?' (auto-gecorrigeerd)':''}</span></div>
      ${p1Meas != null
        ? `<div class="kv"><span class="kl">Gemeten P1-interval</span><span class="kv_ ${p1Color}">${p1Meas.toFixed(2)}s <span style="font-size:10px;opacity:.7">(n=${p1Samp})</span></span></div>
           ${p1MismatchWarn ? `<div class="kv"><span class="kl err" style="font-size:11px">⚠ Ingesteld type klopt niet met gemeten snelheid.<br>Pas DSMR-type aan via Instellingen → Netsensoren.</span></div>` : ''}`
        : `<div class="kv"><span class="kl">Gemeten P1-interval</span><span class="kv_ warn">Nog geen data (P1 niet via directe verbinding)</span></div>`
      }
      ${gridInt != null ? `<div class="kv"><span class="kl">Grid sensor interval</span><span class="kv_ ${_intColor(gridInt, dsmrExp||10)}">${gridInt.toFixed(1)}s <span style="font-size:10px;opacity:.7">(geleerd)</span></span></div>` : ''}
      <div class="kv"><span class="kl">Stale sensoren</span><span class="kv_ ${stale.length?'warn':'ok'}">${stale.length?stale.join(', '):'✅ Geen'}</span></div>
    </div>

    <div class="section">
      <div class="section-title">🔋 Accu Cloud-Vertraging (EnergyBalancer)</div>
      ${batLag != null
        ? `<div class="kv"><span class="kl">Geleerde vertraging</span><span class="kv_ ok">${batLag.toFixed(1)}s</span></div>
           <div class="kv"><span class="kl">Betrouwbaarheid</span><span class="kv_ ${batConf>0.6?'ok':batConf>0.3?'warn':'err'}">${batConf!=null?(batConf*100).toFixed(0)+'%':'—'} <span style="font-size:10px;opacity:.7">(${batSampl} metingen)</span></span></div>`
        : `<div class="kv"><span class="kl">Geleerde vertraging</span><span class="kv_ warn">Nog aan het leren (${batSampl}/${8} metingen)</span></div>`
      }
      <div class="kv"><span class="kl">Lag-compensatie actief</span><span class="kv_ ${lagComp?'ok':''}">${lagComp?'✅ Ja':'Nee'}</span></div>
      ${fastRamp
        ? `<div class="kv"><span class="kl">⚡ Fast-ramp inferentie</span><span class="kv_ warn">Actief${fastEst!=null?' ('+Math.round(fastEst)+'W)':''}</span></div>`
        : ''
      }
      ${batInt != null ? `<div class="kv"><span class="kl">Accu sensor interval</span><span class="kv_">${batInt.toFixed(1)}s</span></div>` : ''}
    </div>

    <div class="section">
      <div class="section-title">📡 Sensorsnelheden (${sirDiag.total_sensors||0} sensoren)</div>
      ${sirDiag.total_sensors > 0 ? `
      <div class="kv"><span class="kl">⚡ Realtime (&lt;2s)</span><span class="kv_ ok">${(sirDiag.by_speed||{}).realtime||0}</span></div>
      <div class="kv"><span class="kl">🟢 Snel (&lt;8s)</span><span class="kv_ ok">${(sirDiag.by_speed||{}).fast||0}</span></div>
      <div class="kv"><span class="kl">🟡 Middel (&lt;30s)</span><span class="kv_">${(sirDiag.by_speed||{}).medium||0}</span></div>
      <div class="kv"><span class="kl">🟠 Traag (&lt;120s)</span><span class="kv_ ${((sirDiag.by_speed||{}).slow||0)>0?'warn':''}">${(sirDiag.by_speed||{}).slow||0}</span></div>
      <div class="kv"><span class="kl">☁️ Cloud (≥120s)</span><span class="kv_ ${((sirDiag.by_speed||{}).cloud||0)>0?'warn':''}">${(sirDiag.by_speed||{}).cloud||0}</span></div>
      ${Object.entries(sirDiag.sensors||{})
          .filter(([,v])=>v.speed==='cloud'||v.speed==='slow')
          .slice(0,5)
          .map(([eid,v])=>`<div class="kv"><span class="kl" style="font-size:10px;opacity:.7">${eid.split('.')[1]}</span><span class="kv_ warn">${v.interval_s!=null?v.interval_s.toFixed(1)+'s':'?'} (${v.speed})</span></div>`)
          .join('')}
      ` : '<div style="color:var(--m);font-size:12px">Nog geen sensordata — komt automatisch na een paar cycli.</div>'}
    </div>

    <div class="section">
      <div class="section-title">EMA Sensor Diagnostiek</div>
      ${ema.status ? `<div class="kv"><span class="kl">Status</span><span class="kv_">${_esc(ema.status)}</span></div>` : '<div style="color:var(--m);font-size:12px">EMA diagnostiek start zodra sensoren data leveren.</div>'}
      ${(ema.sensors||[]).slice(0,8).map(s=>`<div class="kv"><span class="kl">${_esc(s.label||s.entity||'?')}</span><span class="kv_ ${s.ok?'ok':'warn'}">${_esc(s.value||'?')}</span></div>`).join('')}
    </div>`;
  }

  // ── Tab 3: NILM ───────────────────────────────────────────────────────────
  _panel3() {
    const h = this._hass;
    const diag = _sa(h,'sensor.cloudems_nilm_diagnostics');
    const devices = _sa(h,'sensor.cloudems_nilm_devices').devices || [];
    const rate = parseFloat(_sv(h,'sensor.cloudems_nilm_diagnostics')||0);

    return `
    <div class="section">
      <div class="section-title">NILM Status</div>
      <div class="kv"><span class="kl">Classificatierate</span><span class="kv_">${_fmt(rate*100,1)}%</span></div>
      <div class="kv"><span class="kl">Events totaal</span><span class="kv_">${diag.events_total||0}</span></div>
      <div class="kv"><span class="kl">Geclassificeerd</span><span class="kv_">${diag.events_classified||0}</span></div>
      <div class="kv"><span class="kl">Gemist</span><span class="kv_ ${parseInt(diag.events_missed||0)>50?'warn':''}">${diag.events_missed||0}</span></div>
      <div class="kv"><span class="kl">Invoermodus</span><span class="kv_">${_esc(diag.input_mode||'per_phase')}</span></div>
      <div class="kv"><span class="kl">NILM gepauzeerd</span><span class="kv_ ${diag.nilm_paused?'warn':'ok'}">${diag.nilm_paused?'⏸ ja':'▶ nee'}</span></div>
    </div>

    <div class="section">
      <div class="section-title">Geleerde apparaten — vermogen & activiteit</div>
      ${devices.slice(0,20).map(d => {
        const on = d.is_on || d.running;
        const col = on ? 'var(--green)' : 'rgba(255,255,255,0.15)';
        return `<div class="nilm-row">
          <div class="nilm-dot" style="background:${col}"></div>
          <span class="nilm-name">${_esc(d.user_name||d.name||'?')}</span>
          <span class="nilm-w">${d.power_w?d.power_w.toFixed(0)+' W':'—'}</span>
          <span class="kv_ ${on?'ok':''}">  ${on?'AAN':'UIT'}</span>
        </div>`;
      }).join('')}
      ${devices.length > 20 ? `<div style="color:var(--m);font-size:11px;margin-top:6px">+${devices.length-20} meer apparaten</div>` : ''}
    </div>`;
  }

  // ── Tab 4: Fasen ──────────────────────────────────────────────────────────
  _panel4() {
    const h = this._hass;
    const statusA = _sa(h,'sensor.cloudems_status') || {};
    const balA    = _sa(h,'sensor.cloudems_grid_phase_imbalance') || {};
    const phases  = statusA.phases || {};
    const L = ['L1','L2','L3'];
    const curA  = { L1: (phases.L1||{}).current_a,  L2: (phases.L2||{}).current_a,  L3: (phases.L3||{}).current_a  };
    const voltV = { L1: (phases.L1||{}).voltage_v,  L2: (phases.L2||{}).voltage_v,  L3: (phases.L3||{}).voltage_v  };
    const impW  = { L1: (phases.L1||{}).power_w > 0 ? (phases.L1||{}).power_w : 0,
                    L2: (phases.L2||{}).power_w > 0 ? (phases.L2||{}).power_w : 0,
                    L3: (phases.L3||{}).power_w > 0 ? (phases.L3||{}).power_w : 0 };
    const expW  = {};
    const imbalA = parseFloat(balA.imbalance_a || statusA.imbalance_a || 0);

    return `
    <div class="section">
      <div class="section-title">Fase details</div>
      <div class="phase-row" style="color:var(--m);font-size:11px">
        <div>Fase</div><div>Stroom (A)</div><div>Spanning (V)</div><div>Vermogen (W)</div>
      </div>
      ${L.map(l => {
        const cur = parseFloat(curA[l]||0);
        const vol = parseFloat(voltV[l]||0);
        const pw  = parseFloat(impW[l]||expW[l]||0);
        return `<div class="phase-row">
          <div style="color:var(--m)">${l}</div>
          <div style="color:${cur>20?'var(--amber)':'var(--t)'}"><strong>${_fmt(cur,1)}</strong></div>
          <div>${_fmt(vol,0)}</div>
          <div>${_fmt(pw,0)}</div>
        </div>`;
      }).join('')}
    </div>

    <div class="section">
      <div class="section-title">Fase onbalans</div>
      <div class="kv"><span class="kl">Onbalans</span><span class="kv_ ${imbalA>5?'err':imbalA>2?'warn':'ok'}">${_fmt(imbalA,2)} A</span></div>
      <div class="kv"><span class="kl">Status</span><span class="kv_ ${imbalA>5?'err':imbalA>2?'warn':'ok'}">${imbalA<2?'✅ OK':imbalA<5?'⚠️ Licht':'🔴 Hoog'}</span></div>
      ${(balA.limit_a||statusA.peak_limit_a)?`<div class="kv"><span class="kl">Piekschavinglimiet</span><span class="kv_">${balA.limit_a||statusA.peak_limit_a} A</span></div>`:''}
    </div>

    <div class="section">
      <div class="section-title">Net & Fasen sensor</div>
      ${(()=>{
        const ph = _st(h,'sensor.cloudems_grid_phase_imbalance');
        const gn = _st(h,'sensor.cloudems_grid_net_power');
        if(ph||gn) return `<div class="kv"><span class="kl">Status</span><span class="kv_ ok">✅ Beschikbaar</span></div>`;
        return `<div class="kv"><span class="kl">Status</span><span class="kv_ err">❌ Niet gevonden</span></div>`;
      })()}
    </div>`;
  }

  // ── Tab 5: Prestaties ──────────────────────────────────────────────────────
  _panel5() {
    const h = this._hass;
    const perf = _sa(h,'sensor.cloudems_performance') || _sa(h,'sensor.cloudems_systeembelasting') || {};
    const avg = parseFloat(perf.avg_cycle_ms||perf.avg||0);
    const p95 = parseFloat(perf.p95_cycle_ms||perf.p95||0);
    const max = parseFloat(perf.max_cycle_ms||perf.max||0);
    const interval = parseFloat(perf.interval_s||perf.interval||30);
    const mode = perf.mode || _sv(h,'sensor.cloudems_performance') || '?';
    const modeCls = mode==='NORMAL'?'ok':mode==='REDUCED'?'warn':mode==='MINIMAL'?'warn':'err';

    // PID diagnostics
    const pid = _sa(h,'sensor.cloudems_pid_diagnostics') || {};

    return `
    <div class="section">
      <div class="section-title">Cyclus prestaties</div>
      <div class="kv"><span class="kl">Modus</span><span class="kv_ ${modeCls}">${mode}</span></div>
      <div class="kv"><span class="kl">Cyclus interval</span><span class="kv_">${interval} s</span></div>
      <div class="kv"><span class="kl">Gemiddeld</span><span class="kv_ ${avg>500?'warn':avg>200?'info':'ok'}">${avg.toFixed(0)} ms</span></div>
      <div class="kv"><span class="kl">P95</span><span class="kv_ ${p95>2000?'warn':''}">${p95.toFixed(0)} ms</span></div>
      <div class="kv"><span class="kl">Maximum</span><span class="kv_ ${max>5000?'err':max>2000?'warn':''}">${max.toFixed(0)} ms</span></div>
      <div style="margin-top:8px">
        <div style="font-size:10px;color:var(--m);margin-bottom:4px">Cyclusduur (${avg.toFixed(0)}ms gemiddeld)</div>
        <div class="bar-wrap"><div class="bar-fill" style="width:${Math.min(100,avg/50)}%;background:${avg>500?'var(--red)':avg>200?'var(--amber)':'var(--green)'}"></div></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">PID EV diagnostiek</div>
      ${Object.keys(pid).length ? Object.entries(pid).slice(0,6).map(([k,v]) =>
        `<div class="kv"><span class="kl">${_esc(k)}</span><span class="kv_">${_esc(String(v).slice(0,30))}</span></div>`
      ).join('') : '<div style="color:var(--m);font-size:12px">Geen EV PID data beschikbaar.</div>'}
    </div>

    <div class="section">
      <div class="section-title">Actiefknoppen</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">
        ${['button.cloudems_herstart','button.cloudems_reload'].map(eid => {
          const st = _st(h,eid);
          if (!st) return '';
          const lbl = st.attributes.friendly_name || eid.split('.').pop().replace(/_/g,' ');
          return `<button data-eid="${eid}" style="font-size:12px;padding:6px 12px;border-radius:6px;border:0.5px solid var(--b);background:var(--s);cursor:pointer;color:var(--t)">${_esc(lbl)}</button>`;
        }).join('')}
      </div>
    </div>`;
  }

  _panel6() {
    const h = this._hass; if (!h) return '';
    const gen  = h.states['sensor.cloudems_status']?.attributes?.generator || {};
    const circ = h.states['sensor.cloudems_status']?.attributes?.circuit_monitor ||
                 (Object.values(h.states).find(s => s.entity_id?.includes('circuit_monitor'))?.attributes) || {};
    const alerts = circ.alerts || {};
    const hasAlerts = Object.keys(alerts).length > 0;

    // Generator sectie
    const genRows = [
      ['Status',         gen.enabled ? (gen.active ? '⚡ Generator actief' : gen.grid_lost ? '🔴 Netuitval' : gen.ups_active ? '🔦 UPS actief' : '✅ Net OK') : '—'],
      ['Vermogen',       gen.active ? (gen.power_w||0).toFixed(0)+' W' : '—'],
      ['Max capaciteit', gen.max_power_w ? gen.max_power_w+'W' : '—'],
      ['ATS type',       gen.ats_type || '—'],
      ['Brandstof',      gen.fuel_type || '—'],
      ['Beperkingen',    (gen.restrictions||[]).join(', ') || 'geen'],
    ].map(([k,v]) => `<div class="kv"><span class="kl">${k}</span><span class="kv_">${_esc(v)}</span></div>`).join('');

    // Circuit alerts sectie
    const alertRows = hasAlerts
      ? Object.entries(alerts).map(([key, a]) => `
        <div style="background:rgba(231,76,60,0.08);border:1px solid rgba(231,76,60,0.2);border-radius:8px;padding:10px;margin-bottom:8px">
          <div style="font-weight:700;color:#e74c3c;margin-bottom:4px">⚡ ${_esc(a.phase)} — ${a.type==='total_zero'?'Totaaluitval':'Fase inactief'}</div>
          <div class="kv"><span class="kl">Gemeten</span><span class="kv_">${(a.power_w||0).toFixed(1)} W</span></div>
          <div class="kv"><span class="kl">Al actief</span><span class="kv_">${Math.round((a.inactive_s||a.since_s||0)/60)} min</span></div>
          ${a.devices?.length ? `<div class="kv"><span class="kl">Getroffen</span><span class="kv_">${_esc(a.devices.slice(0,4).join(', '))}</span></div>` : ''}
        </div>`).join('')
      : '<div style="color:var(--green);font-size:12px">✅ Alle fasen normaal — geen uitval gedetecteerd.</div>';

    // Fase leer-status
    const learnRows = (circ.learn_ready ? Object.entries(circ.learn_ready) : [])
      .map(([ph, ready]) => `<div class="kv"><span class="kl">Fase ${ph}</span><span class="kv_" style="color:${ready?'var(--green)':'var(--amber)'}">${ready?'✅ Geleerd':'⏳ Lerende...'}</span></div>`).join('');

    return `
      <div class="section-title">⚡ Generator & UPS Status</div>
      ${gen.enabled ? genRows : '<div style="color:var(--m);font-size:12px">Generator niet geconfigureerd. Stel in via Instellingen → Energie & Grid → Generator.</div>'}
      <div class="section-title" style="margin-top:14px">🔌 Uitgevallen groepen detector</div>
      ${alertRows}
      ${learnRows ? `<div class="section-title" style="margin-top:10px">📊 Fase leerdata</div>${learnRows}` : ''}
    `;
  }

  _panel7() {
    const h = this._hass; if (!h) return '';
    const la = h.states['sensor.cloudems_lampcirculatie_status']?.attributes?.automation || {};
    const lamps = la.lamps || [];
    const lastActions = la.last_actions || [];

    const statRows = [
      ['Ingeschakeld',   la.enabled ? '✅ Ja' : '❌ Nee'],
      ['Automatisch',    la.auto_count ?? '—'],
      ['Semi-auto',      la.semi_count ?? '—'],
      ['Handmatig',      lamps.filter(l=>l.mode==='manual').length || '—'],
      ['Totaal lampen',  la.lamp_count ?? '—'],
    ].map(([k,v]) => `<div class="kv"><span class="kl">${k}</span><span class="kv_">${v}</span></div>`).join('');

    const modeColors = {auto:'var(--green)', semi:'var(--amber)', manual:'var(--m)'};
    const lampRows = lamps.map(l => `
      <div class="kv">
        <span class="kl">${_esc(l.label)}${l.area?' <small style="color:var(--m)">'+_esc(l.area)+'</small>':''}</span>
        <span class="kv_" style="color:${modeColors[l.mode]||'var(--m)'}">${l.mode==='auto'?'🤖 AUTO':l.mode==='semi'?'🔔 SEMI':'👤 HANDMATIG'}${l.has_presence?' 📡':''}</span>
      </div>`).join('');

    const actionRows = lastActions.slice(-5).reverse().map(a => {
      const ago = a.ts ? Math.round((Date.now()/1000-a.ts)/60) : '?';
      const icon = a.action==='on'?'💡':a.action==='off'?'⬛':a.action==='confirm_request'?'🔔':'ℹ️';
      return `<div class="kv"><span class="kl">${icon} ${_esc(a.label)}</span><span class="kv_" style="font-size:11px">${_esc(a.reason)} <small style="color:var(--m)">${ago}m</small></span></div>`;
    }).join('');

    return `
      <div class="section-title">🏠 Slimme Verlichting Status</div>
      ${statRows}
      ${lampRows ? `<div class="section-title" style="margin-top:14px">💡 Lampen (${lamps.length})</div>${lampRows}` : ''}
      ${actionRows ? `<div class="section-title" style="margin-top:14px">📋 Laatste acties</div>${actionRows}` : ''}
    `;
  }

  _panel8() {
    const h = this._hass; if (!h) return '';
    const ups = h.states['sensor.cloudems_status']?.attributes?.ups || {};
    const units = ups.ups_units || [];

    if (!ups.enabled && !units.length) {
      return `<div class="empty">Geen UPS systemen geconfigureerd.<br>Ga naar Instellingen → Noodstroom & Backup → UPS Systemen.</div>`;
    }

    const unitCards = units.map(u => {
      const batColor = u.battery_pct > 60 ? 'var(--green)' : u.battery_pct > 25 ? 'var(--amber)' : 'var(--red)';
      const stColor  = u.on_battery ? 'var(--amber)' : u.fault ? 'var(--red)' : 'var(--green)';
      const stLabel  = u.on_battery ? (u.low_battery ? '⚠️ Batterij kritiek laag' : '🔋 Op batterij') : u.fault ? '❌ Fout' : '✅ Op net';
      const runMin   = u.runtime_min < 999 ? `${u.runtime_min?.toFixed(0)} min` : '—';
      const onBatMin = u.on_battery_s > 0 ? `${Math.round(u.on_battery_s/60)} min op batterij` : '';
      return `
        <div style="background:rgba(255,255,255,0.03);border:1px solid ${u.on_battery?'rgba(251,146,60,0.3)':'rgba(255,255,255,0.08)'};border-radius:10px;padding:12px;margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:700;color:var(--t)">🔋 ${_esc(u.label)}</span>
            <span style="font-size:11px;color:${stColor}">${stLabel}</span>
          </div>
          <div class="kv"><span class="kl">Batterij</span>
            <span class="kv_">
              <div style="display:inline-flex;align-items:center;gap:6px">
                <div style="width:60px;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">
                  <div style="width:${u.battery_pct||0}%;height:100%;background:${batColor};border-radius:3px"></div>
                </div>
                <span style="color:${batColor}">${(u.battery_pct||0).toFixed(0)}%</span>
              </div>
            </span>
          </div>
          <div class="kv"><span class="kl">Runtime</span><span class="kv_" style="color:${u.runtime_min<5?'var(--red)':u.runtime_min<15?'var(--amber)':'var(--green)'}">${runMin}</span></div>
          ${u.power_w>0?`<div class="kv"><span class="kl">Belasting</span><span class="kv_">${u.power_w.toFixed(0)} W</span></div>`:''}
          ${u.devices_shed>0?`<div class="kv"><span class="kl">Afgeschakeld</span><span class="kv_" style="color:var(--amber)">${u.devices_shed}/${u.devices_total} apparaten</span></div>`:''}
          ${onBatMin?`<div style="font-size:10px;color:var(--m);margin-top:4px">${onBatMin}</div>`:''}
        </div>`;
    }).join('');

    const genActive = ups.generator_active;
    return `
      <div class="section-title">🔋 UPS Status — ${units.length} systeem${units.length!==1?'en':''}</div>
      ${genActive?`<div style="padding:8px 12px;background:rgba(74,222,128,0.08);border-radius:8px;border:1px solid rgba(74,222,128,0.2);font-size:12px;color:var(--green);margin-bottom:10px">⚡ Generator actief — UPS apparaten worden hersteld</div>`:''}
      ${unitCards || '<div style="color:var(--m);font-size:12px">Geen UPS data beschikbaar.</div>'}
    `;
  }

  static getConfigElement() { return document.createElement("cloudems-diagnose-card-editor"); }
  static getStubConfig() { return {type:"custom:cloudems-diagnose-card"}; }
  getCardSize() { return 6; }
}

class CloudemsDiagnoseCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:"open"}); this._cfg = {}; }
  setConfig(c) { this._cfg = {...c}; this._render(); }
  set hass(h) { this._hass = h; }
  _fire() { this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._cfg},bubbles:true,composed:true})); }
  _render() {
    this.shadowRoot.innerHTML = `<div style="padding:8px;font-size:13px;color:var(--secondary-text-color)">Geen configuratie nodig.</div>`;
  }
}

customElements.define("cloudems-diagnose-card-editor", CloudemsDiagnoseCardEditor);
customElements.define("cloudems-diagnose-card", CloudemsDiagnoseCard);
window.customCards = window.customCards ?? [];
window.customCards.push({type:"cloudems-diagnose-card", name:"CloudEMS Diagnose Card", description:"Systeemgezondheid, watchdog, sensoren, NILM en prestaties", preview:true});
console.info(`%c CLOUDEMS-DIAGNOSE-CARD %c v${DIAGNOSE_VERSION} `,"background:#1D9E75;color:#fff;font-weight:700;padding:2px 6px;border-radius:3px 0 0 3px","background:#0e1520;color:#1D9E75;font-weight:700;padding:2px 6px;border-radius:0 3px 3px 0");
